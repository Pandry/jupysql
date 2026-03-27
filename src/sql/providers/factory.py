"""
Database provider factory for managing multiple providers.
"""
import threading
import logging
from typing import List, Dict, Optional
from .base import DatabaseProvider, DatabaseInfo

logger = logging.getLogger(__name__)


class DatabaseProviderFactory:
    """
    Singleton factory that manages database providers.

    Aggregates databases from multiple sources (static, config files, CNPG, etc.)
    and provides a unified interface for discovering available databases.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._providers: Dict[str, DatabaseProvider] = {}
        self._lock = threading.Lock()
        self._initialized = True

    def register_provider(self, provider: DatabaseProvider) -> None:
        """
        Register a database provider.

        Args:
            provider: DatabaseProvider instance to register
        """
        with self._lock:
            self._providers[provider.name] = provider

    def unregister_provider(self, name: str) -> None:
        """
        Unregister a database provider.

        Args:
            name: Name of the provider to unregister
        """
        with self._lock:
            if name in self._providers:
                del self._providers[name]

    def get_provider(self, name: str) -> Optional[DatabaseProvider]:
        """
        Get a provider by name.

        Args:
            name: Name of the provider

        Returns:
            DatabaseProvider if found, None otherwise
        """
        return self._providers.get(name)

    def list_providers(self) -> List[str]:
        """
        List all registered provider names.

        Returns:
            List of provider names
        """
        return list(self._providers.keys())

    def list_databases(self, provider_names: Optional[List[str]] = None) -> List[DatabaseInfo]:
        """
        List all databases from enabled providers.

        Args:
            provider_names: Optional list of provider names to query.
                          If None, queries all enabled providers.

        Returns:
            Aggregated list of DatabaseInfo objects from all providers
        """
        databases = []
        seen_identifiers = set()

        providers_to_query = (
            [self._providers[name] for name in provider_names if name in self._providers]
            if provider_names
            else self._providers.values()
        )

        for provider in providers_to_query:
            if not provider.is_enabled():
                continue

            try:
                provider_databases = provider.list_databases()
                for db in provider_databases:
                    # Deduplicate by identifier (first provider wins)
                    if db.identifier not in seen_identifiers:
                        databases.append(db)
                        seen_identifiers.add(db.identifier)
            except Exception as e:
                # Log error but continue with other providers
                logger.error(f"Error listing databases from provider '{provider.name}': {e}")

        return databases

    def get_database(self, identifier: str) -> Optional[DatabaseInfo]:
        """
        Get a database by identifier from any provider.

        Args:
            identifier: Unique identifier for the database

        Returns:
            DatabaseInfo if found, None otherwise
        """
        for provider in self._providers.values():
            if not provider.is_enabled():
                continue

            try:
                db = provider.get_database(identifier)
                if db:
                    return db
            except Exception as e:
                logger.error(f"Error getting database from provider '{provider.name}': {e}")

        return None

    def refresh_all(self) -> None:
        """Refresh all enabled providers."""
        for provider in self._providers.values():
            if provider.is_enabled():
                try:
                    provider.refresh()
                except Exception as e:
                    logger.error(f"Error refreshing provider '{provider.name}': {e}")

    def refresh_provider(self, name: str) -> None:
        """
        Refresh a specific provider.

        Args:
            name: Name of the provider to refresh
        """
        provider = self._providers.get(name)
        if provider and provider.is_enabled():
            provider.refresh()


# Global singleton instance
_factory = DatabaseProviderFactory()


def get_factory() -> DatabaseProviderFactory:
    """Get the global DatabaseProviderFactory instance."""
    return _factory
