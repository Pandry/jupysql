"""
CNPG (CloudNativePG) database provider for Kubernetes.

Discovers PostgreSQL databases from CNPG clusters and poolers with automatic
credential resolution and refresh.
"""
import os
import time
import threading
import logging
from typing import List, Optional, Dict, Set
from datetime import datetime
import base64
from urllib.parse import quote as url_quote

from .base import DatabaseProvider, DatabaseInfo

logger = logging.getLogger(__name__)


class CNPGDatabaseProvider(DatabaseProvider):
    """
    Provider for CNPG (CloudNativePG) clusters in Kubernetes.

    Discovers PostgreSQL clusters and poolers with specified labels and
    automatically fetches credentials from Kubernetes secrets.

    Configuration via environment variables:
    - JUPYSQL_CNPG_ENABLED: Enable CNPG provider (default: false)
    - JUPYSQL_CNPG_NAMESPACE: Kubernetes namespace (default: current namespace)
    - JUPYSQL_CNPG_LABEL_SELECTOR: Label selector for clusters/poolers (default: jupysql.pandry.github.io/enabled=true)
    - JUPYSQL_CNPG_AUTO_REFRESH_INTERVAL: Auto-refresh interval in seconds (default: 100)
    - JUPYSQL_CNPG_DEBOUNCE_INTERVAL: Debounce interval for manual refresh in seconds (default: 5)
    """

    def __init__(self):
        super().__init__("cnpg")

        # Configuration from environment
        self.enabled = os.getenv("JUPYSQL_CNPG_ENABLED", "false").lower() == "true"
        self.namespace = os.getenv("JUPYSQL_CNPG_NAMESPACE", self._get_current_namespace())
        self.label_selector = os.getenv("JUPYSQL_CNPG_LABEL_SELECTOR", "jupysql.pandry.github.io/enabled=true")
        self.auto_refresh_interval = int(os.getenv("JUPYSQL_CNPG_AUTO_REFRESH_INTERVAL", "100"))
        self.debounce_interval = int(os.getenv("JUPYSQL_CNPG_DEBOUNCE_INTERVAL", "5"))

        # Log configuration on startup
        if self.enabled:
            logger.info(f"CNPG Provider initialized:")
            logger.info(f"  Namespace: {self.namespace}")
            logger.info(f"  Label selector: {self.label_selector}")
            logger.info(f"  Auto-refresh interval: {self.auto_refresh_interval}s")
            logger.info(f"  Debounce interval: {self.debounce_interval}s")

        # State
        self._databases: List[DatabaseInfo] = []
        self._lock = threading.Lock()
        self._last_refresh = 0.0
        self._refresh_thread = None
        self._stop_refresh = threading.Event()
        self._refreshing = False  # Flag to prevent concurrent refreshes

        # Kubernetes client (lazy loaded)
        self._k8s_client = None
        self._k8s_custom_api = None

        # Start auto-refresh if enabled
        if self.enabled:
            self._start_auto_refresh()

    def _get_current_namespace(self) -> str:
        """Get the current Kubernetes namespace from service account."""
        namespace_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
        try:
            with open(namespace_path, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return "default"

    def _init_k8s_client(self):
        """Initialize Kubernetes client with in-cluster config."""
        if self._k8s_client is not None:
            return

        try:
            from kubernetes import client, config

            # Try to load in-cluster config first (for running inside K8s)
            try:
                config.load_incluster_config()
            except config.ConfigException:
                # Fall back to kubeconfig (for local development)
                config.load_kube_config()

            self._k8s_client = client.CoreV1Api()
            self._k8s_custom_api = client.CustomObjectsApi()
        except ImportError:
            logger.warning("kubernetes package not installed. CNPG provider disabled.")
            self.disable()
        except Exception as e:
            logger.error(f"Error initializing Kubernetes client: {e}")
            self.disable()

    def list_databases(self) -> List[DatabaseInfo]:
        """List all databases from CNPG clusters/poolers."""
        with self._lock:
            return self._databases.copy()

    def get_database(self, identifier: str) -> Optional[DatabaseInfo]:
        """Get a database by identifier."""
        with self._lock:
            for db in self._databases:
                if db.identifier == identifier:
                    return db
        return None

    def refresh(self) -> None:
        """
        Refresh the database list from Kubernetes.

        This is debounced to prevent spamming the Kubernetes API.
        """
        current_time = time.time()

        # Debounce check and prevent concurrent refreshes
        with self._lock:
            if current_time - self._last_refresh < self.debounce_interval:
                return
            if self._refreshing:
                logger.debug("Refresh already in progress, skipping")
                return
            self._last_refresh = current_time
            self._refreshing = True

        try:
            self._do_refresh()
        finally:
            with self._lock:
                self._refreshing = False

    def _do_refresh(self) -> None:
        """Actually perform the refresh (no debouncing)."""
        if not self.enabled:
            logger.debug("CNPG provider is disabled, skipping refresh")
            return

        logger.info(f"CNPG provider refresh starting (namespace={self.namespace}, selector={self.label_selector})")

        self._init_k8s_client()
        if self._k8s_client is None:
            logger.warning("Kubernetes client not initialized, cannot refresh")
            return

        databases = []

        # Discover CNPG clusters
        clusters = self._discover_clusters()
        logger.info(f"Discovered {len(clusters)} CNPG cluster(s)")
        databases.extend(clusters)

        # Discover CNPG poolers
        poolers = self._discover_poolers()
        logger.info(f"Discovered {len(poolers)} CNPG pooler(s)")
        databases.extend(poolers)

        with self._lock:
            self._databases = databases

        logger.info(f"CNPG provider refresh complete: {len(databases)} total database(s) available")

    def _discover_clusters(self) -> List[DatabaseInfo]:
        """Discover CNPG clusters with matching labels."""
        databases = []

        try:
            logger.debug(f"Querying K8s API for clusters in namespace '{self.namespace}' with selector '{self.label_selector}'")

            # List CNPG Cluster resources (with timeout to prevent hanging)
            clusters = self._k8s_custom_api.list_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace=self.namespace,
                plural="clusters",
                label_selector=self.label_selector,
                _request_timeout=30,
            )

            cluster_items = clusters.get("items", [])
            logger.debug(f"Found {len(cluster_items)} cluster(s) matching selector")

            for cluster in cluster_items:
                try:
                    cluster_name = cluster.get("metadata", {}).get("name", "unknown")
                    logger.debug(f"Processing cluster: {cluster_name}")

                    db_info = self._create_database_info_from_cluster(cluster)
                    if db_info:
                        databases.append(db_info)
                        logger.info(f"Added cluster: {db_info.name} ({db_info.identifier})")
                    else:
                        logger.warning(f"Cluster '{cluster_name}' returned no database info (missing credentials?)")
                except Exception as e:
                    cluster_name = cluster.get("metadata", {}).get("name", "unknown")
                    logger.error(f"Error processing cluster '{cluster_name}': {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error listing CNPG clusters: {e}", exc_info=True)

        return databases

    def _discover_poolers(self) -> List[DatabaseInfo]:
        """Discover CNPG poolers with matching labels."""
        databases = []

        try:
            logger.debug(f"Querying K8s API for poolers in namespace '{self.namespace}' with selector '{self.label_selector}'")

            # List CNPG Pooler resources (with timeout to prevent hanging)
            poolers = self._k8s_custom_api.list_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace=self.namespace,
                plural="poolers",
                label_selector=self.label_selector,
                _request_timeout=30,
            )

            pooler_items = poolers.get("items", [])
            logger.debug(f"Found {len(pooler_items)} pooler(s) matching selector")

            for pooler in pooler_items:
                try:
                    pooler_name = pooler.get("metadata", {}).get("name", "unknown")
                    logger.debug(f"Processing pooler: {pooler_name}")

                    db_info = self._create_database_info_from_pooler(pooler)
                    if db_info:
                        databases.append(db_info)
                        logger.info(f"Added pooler: {db_info.name} ({db_info.identifier})")
                    else:
                        logger.warning(f"Pooler '{pooler_name}' returned no database info")
                except Exception as e:
                    pooler_name = pooler.get("metadata", {}).get("name", "unknown")
                    logger.error(f"Error processing pooler '{pooler_name}': {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error listing CNPG poolers: {e}", exc_info=True)

        return databases

    def _create_database_info_from_cluster(self, cluster: Dict) -> Optional[DatabaseInfo]:
        """Create DatabaseInfo from a CNPG Cluster resource."""
        metadata = cluster.get("metadata", {})
        spec = cluster.get("spec", {})
        status = cluster.get("status", {})

        name = metadata.get("name")
        if not name:
            logger.warning("Cluster has no name in metadata, skipping")
            return None

        labels = metadata.get("labels", {})

        # Get service name (rw service)
        service_name = f"{name}-rw"
        host = f"{service_name}.{self.namespace}.svc.cluster.local"
        port = 5432

        # Get database name
        database = spec.get("bootstrap", {}).get("initdb", {}).get("database", "app")

        # Get username from labels or use default
        # Check if readonly mode is requested
        readonly = labels.get("jupysql.pandry.github.io/readonly", "false").lower() == "true"
        username = labels.get("jupysql.pandry.github.io/username", "ro" if readonly else "app")

        # Get credentials from secret
        password = self._get_password_from_secret(name, username)
        if not password:
            logger.warning(f"Could not retrieve password for cluster '{name}', user '{username}'")
            return None

        # Build connection string with URL-encoded credentials
        # This handles special characters like @, :, /, # in passwords
        encoded_username = url_quote(username, safe='')
        encoded_password = url_quote(password, safe='')
        connection_string = f"postgresql://{encoded_username}:{encoded_password}@{host}:{port}/{database}"

        # Create identifier
        identifier = f"cnpg:cluster:{self.namespace}:{name}"

        # Get custom alias from labels or use default
        alias = labels.get("jupysql.pandry.github.io/alias", f"{name} (cluster)")

        # Create DatabaseInfo
        return DatabaseInfo(
            identifier=identifier,
            name=alias,
            connection_string=connection_string,
            provider=self.name,
            metadata={
                "source": "cnpg_cluster",
                "namespace": self.namespace,
                "cluster_name": name,
                "service": service_name,
                "type": "cluster",
            },
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            labels=labels,
        )

    def _create_database_info_from_pooler(self, pooler: Dict) -> Optional[DatabaseInfo]:
        """Create DatabaseInfo from a CNPG Pooler resource."""
        metadata = pooler.get("metadata", {})
        spec = pooler.get("spec", {})

        name = metadata.get("name")
        if not name:
            logger.warning("Pooler has no name in metadata, skipping")
            return None

        labels = metadata.get("labels", {})

        # Get cluster reference
        cluster_ref = spec.get("cluster", {}).get("name")
        if not cluster_ref:
            logger.warning(f"Pooler '{name}' has no cluster reference")
            return None

        # Get service name (pooler service is just the pooler name, not {name}-rw)
        service_name = name
        host = f"{service_name}.{self.namespace}.svc.cluster.local"
        port = 5432

        # Get pooler type from labels (rw or ro)
        pooler_type = labels.get("jupysql.pandry.github.io/pooler-type", "rw")

        # Get database name from the referenced cluster
        # Poolers connect to the same database as their parent cluster
        database = self._get_cluster_database(cluster_ref)

        # Get username from labels or use default
        username = labels.get("jupysql.pandry.github.io/username", "app")

        # Get credentials from cluster secret
        password = self._get_password_from_secret(cluster_ref, username)
        if not password:
            logger.warning(f"Could not retrieve password for pooler '{name}', user '{username}'")
            return None

        # Build connection string with URL-encoded credentials
        # This handles special characters like @, :, /, # in passwords
        encoded_username = url_quote(username, safe='')
        encoded_password = url_quote(password, safe='')
        connection_string = f"postgresql://{encoded_username}:{encoded_password}@{host}:{port}/{database}"

        # Create identifier
        identifier = f"cnpg:pooler:{self.namespace}:{name}"

        # Get custom alias from labels or use default
        alias = labels.get("jupysql.pandry.github.io/alias", f"{name} ({pooler_type} pooler)")

        # Create DatabaseInfo
        return DatabaseInfo(
            identifier=identifier,
            name=alias,
            connection_string=connection_string,
            provider=self.name,
            metadata={
                "source": "cnpg_pooler",
                "namespace": self.namespace,
                "pooler_name": name,
                "cluster_name": cluster_ref,
                "service": service_name,
                "type": "pooler",
                "pooler_type": pooler_type,
            },
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            labels=labels,
        )

    def _get_password_from_secret(self, cluster_name: str, username: str) -> Optional[str]:
        """
        Get password from CNPG cluster secret.

        CNPG stores credentials in a secret named {cluster-name}-{username}
        with a 'password' key.
        """
        secret_name = f"{cluster_name}-{username}"

        try:
            secret = self._k8s_client.read_namespaced_secret(
                name=secret_name,
                namespace=self.namespace,
                _request_timeout=10,
            )

            if secret.data is None:
                logger.warning(f"Secret '{secret_name}' has no data")
                return None

            password_b64 = secret.data.get("password")
            if password_b64:
                return base64.b64decode(password_b64).decode("utf-8")

        except Exception as e:
            logger.error(f"Error reading secret '{secret_name}': {e}")

        return None

    def _get_cluster_database(self, cluster_name: str) -> str:
        """
        Get database name from a CNPG cluster.

        Fetches the cluster resource to extract the database name from
        spec.bootstrap.initdb.database. Defaults to 'app' if not found.
        """
        try:
            cluster = self._k8s_custom_api.get_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace=self.namespace,
                plural="clusters",
                name=cluster_name,
                _request_timeout=10,
            )
            spec = cluster.get("spec", {})
            database = spec.get("bootstrap", {}).get("initdb", {}).get("database", "app")
            return database
        except Exception as e:
            logger.warning(f"Could not fetch cluster '{cluster_name}' for database name: {e}")
            return "app"

    def _start_auto_refresh(self) -> None:
        """Start background thread for auto-refresh.

        Performs the initial refresh synchronously to ensure databases are
        available immediately after initialization, then starts a background
        thread for periodic refreshes.
        """
        with self._lock:
            if self._refresh_thread is not None and self._refresh_thread.is_alive():
                return

            # Do initial refresh synchronously to avoid race condition where
            # the UI queries for databases before the first refresh completes
            logger.info("Performing initial CNPG refresh synchronously...")
            self._refreshing = True

        try:
            self._do_refresh()
        finally:
            with self._lock:
                self._refreshing = False

        self._stop_refresh.clear()
        self._refresh_thread = threading.Thread(target=self._auto_refresh_loop, daemon=True)
        self._refresh_thread.start()

    def _auto_refresh_loop(self) -> None:
        """Background loop for auto-refreshing databases."""
        # Initial refresh already done in _start_auto_refresh()
        while not self._stop_refresh.is_set():
            self._stop_refresh.wait(self.auto_refresh_interval)
            if not self._stop_refresh.is_set():
                # Check if another refresh is in progress
                with self._lock:
                    if self._refreshing:
                        continue
                    self._refreshing = True
                try:
                    self._do_refresh()
                finally:
                    with self._lock:
                        self._refreshing = False

    def stop(self) -> None:
        """Stop the auto-refresh background thread."""
        self._stop_refresh.set()
        if self._refresh_thread is not None:
            self._refresh_thread.join(timeout=5)

    def __del__(self):
        """Cleanup when provider is destroyed."""
        self.stop()
