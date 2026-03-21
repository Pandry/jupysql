# Kubernetes Installation Guide

This guide walks through deploying JupySQL on Kubernetes using the official JupyterHub Helm chart, with Dex OIDC authentication, persistent storage, and automatic CNPG database connection discovery.

## Prerequisites

- Kubernetes cluster (1.25+)
- Helm 3.x installed
- `kubectl` configured for your cluster
- nginx-ingress controller
- Dex instance running and accessible
- (Optional) CloudNativePG operator installed for managed PostgreSQL

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                     Ingress (nginx)                               │
│                   jupysql.example.com                             │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│                        JupyterHub                                 │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────────────┐  │
│  │  Hub Pod   │  │ Proxy Pod  │  │       User Pod              │  │
│  │ (spawner)  │  │ (routing)  │  │  ┌──────────────────────┐  │  │
│  │            │  │            │  │  │  JupySQL Container   │  │  │
│  │            │  │            │  │  │  ghcr.io/pandry/     │  │  │
│  │            │  │            │  │  │  jupysql:master      │  │  │
│  │            │  │            │  │  └──────────┬───────────┘  │  │
│  │            │  │            │  │             │ localhost    │  │
│  │            │  │            │  │  ┌──────────▼───────────┐  │  │
│  │            │  │            │  │  │  DB Discovery        │  │  │
│  │            │  │            │  │  │  Sidecar             │  │  │
│  │            │  │            │  │  │  (adds connections   │  │  │
│  │            │  │            │  │  │   via JupySQL API)   │  │  │
│  └────────────┘  └────────────┘  │  └──────────────────────┘  │  │
│                                   └────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
        │                                       │
        ▼                                       ▼
┌───────────────┐                    ┌─────────────────────────────┐
│   Dex OIDC    │                    │  CNPG Clusters              │
│   (auth)      │                    │  (label: jupysql.io/expose) │
└───────────────┘                    └─────────────────────────────┘
```

## Step 1: Add JupyterHub Helm Repository

```bash
helm repo add jupyterhub https://hub.jupyter.org/helm-chart/
helm repo update
```

## Step 2: Create Namespace

```bash
kubectl create namespace jupysql
```

## Step 3: Label CNPG Clusters for Discovery

Add the `jupysql.io/expose` label to CNPG clusters you want available in JupySQL:

```bash
# Label an existing cluster
kubectl label cluster.postgresql.cnpg.io/my-cluster \
  jupysql.io/expose=true \
  -n my-namespace

# Or include in cluster spec
```

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: analytics-db
  namespace: databases
  labels:
    jupysql.io/expose: "true"       # Required: enables discovery
    jupysql.io/alias: "analytics"   # Optional: friendly name in UI
    jupysql.io/readonly: "true"     # Optional: use read-only credentials
spec:
  instances: 3
  # ... rest of cluster spec
```

## Step 4: Create RBAC for DB Discovery

The sidecar needs read-only access to discover CNPG clusters and read their secrets:

```yaml
# db-discovery-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: jupysql-db-discovery
  namespace: jupysql
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: jupysql-db-discovery
rules:
# Read CNPG cluster resources
- apiGroups: ["postgresql.cnpg.io"]
  resources: ["clusters"]
  verbs: ["get", "list", "watch"]
# Read secrets (for connection credentials)
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"]
# List namespaces to scan
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: jupysql-db-discovery
subjects:
- kind: ServiceAccount
  name: jupysql-db-discovery
  namespace: jupysql
roleRef:
  kind: ClusterRole
  name: jupysql-db-discovery
  apiGroup: rbac.authorization.k8s.io
```

```bash
kubectl apply -f db-discovery-rbac.yaml
```

## Step 5: Configure Dex Client

Add a client configuration to your Dex instance:

```yaml
# Add to your Dex config
staticClients:
- id: jupyterhub
  name: JupyterHub
  secret: <generate-a-secure-secret>  # openssl rand -hex 32
  redirectURIs:
  - https://jupysql.example.com/hub/oauth_callback
```

## Step 6: Create JupyterHub Values File

```yaml
# jupyterhub-values.yaml

proxy:
  secretToken: <generate-with-openssl-rand-hex-32>
  service:
    type: ClusterIP

hub:
  config:
    JupyterHub:
      authenticator_class: generic-oauth
    GenericOAuthenticator:
      client_id: jupyterhub
      client_secret: <your-dex-client-secret>
      oauth_callback_url: https://jupysql.example.com/hub/oauth_callback
      authorize_url: https://dex.example.com/auth
      token_url: https://dex.example.com/token
      userdata_url: https://dex.example.com/userinfo
      scope:
        - openid
        - email
        - profile
      username_claim: email
      allow_all: true

singleuser:
  # JupySQL image
  image:
    name: ghcr.io/pandry/jupysql
    tag: master
    pullPolicy: Always

  # Use the discovery ServiceAccount
  serviceAccountName: jupysql-db-discovery

  # Resources
  cpu:
    limit: 2
    guarantee: 0.5
  memory:
    limit: 4G
    guarantee: 1G

  # Persistent storage for notebooks
  storage:
    type: dynamic
    capacity: 10Gi
    dynamic:
      storageClass: <your-storage-class>
    homeMountPath: /home/jovyan

  # DB Discovery sidecar - discovers CNPG clusters and adds them via API
  extraContainers:
    - name: db-discovery
      image: bitnami/kubectl:latest
      command:
        - /bin/bash
        - -c
        - |
          #!/bin/bash
          set -e

          JUPYSQL_API="http://localhost:8888/jupysql/connections"
          LABEL_SELECTOR="jupysql.io/expose=true"
          POLL_INTERVAL=${POLL_INTERVAL:-60}

          # Wait for JupyterLab to be ready
          echo "Waiting for JupyterLab API..."
          until curl -sf http://localhost:8888/api/status >/dev/null 2>&1; do
            sleep 2
          done
          echo "JupyterLab is ready"

          # Track which connections we've added
          declare -A ADDED_CONNECTIONS

          discover_and_add() {
            echo "$(date): Scanning for CNPG clusters..."

            # Get all namespaces
            for ns in $(kubectl get namespaces -o jsonpath='{.items[*].metadata.name}'); do
              # Get clusters with our label
              clusters=$(kubectl get clusters.postgresql.cnpg.io -n "$ns" \
                -l "$LABEL_SELECTOR" \
                -o jsonpath='{.items[*].metadata.name}' 2>/dev/null) || continue

              for cluster in $clusters; do
                conn_key="${ns}/${cluster}"

                # Skip if already added
                [[ -n "${ADDED_CONNECTIONS[$conn_key]}" ]] && continue

                echo "Found cluster: $conn_key"

                # Check for readonly label
                use_readonly=$(kubectl get cluster.postgresql.cnpg.io "$cluster" -n "$ns" \
                  -o jsonpath='{.metadata.labels.jupysql\.io/readonly}' 2>/dev/null)

                # Determine which secret to use
                if [[ "$use_readonly" == "true" ]]; then
                  # Use read-only user if available
                  secret_name="${cluster}-ro"
                  if ! kubectl get secret -n "$ns" "$secret_name" &>/dev/null; then
                    echo "  Read-only secret not found, falling back to app secret"
                    secret_name="${cluster}-app"
                  fi
                else
                  secret_name="${cluster}-app"
                fi

                # Get connection details from secret
                if ! kubectl get secret -n "$ns" "$secret_name" &>/dev/null; then
                  echo "  Secret $secret_name not found, skipping"
                  continue
                fi

                host=$(kubectl get secret -n "$ns" "$secret_name" -o jsonpath='{.data.host}' | base64 -d)
                port=$(kubectl get secret -n "$ns" "$secret_name" -o jsonpath='{.data.port}' | base64 -d)
                dbname=$(kubectl get secret -n "$ns" "$secret_name" -o jsonpath='{.data.dbname}' | base64 -d)
                user=$(kubectl get secret -n "$ns" "$secret_name" -o jsonpath='{.data.user}' | base64 -d)
                password=$(kubectl get secret -n "$ns" "$secret_name" -o jsonpath='{.data.password}' | base64 -d)

                # Get optional alias from label
                alias=$(kubectl get cluster.postgresql.cnpg.io "$cluster" -n "$ns" \
                  -o jsonpath='{.metadata.labels.jupysql\.io/alias}' 2>/dev/null)
                [[ -z "$alias" ]] && alias="${ns}-${cluster}"

                # Build connection URL
                conn_url="postgresql://${user}:${password}@${host}:${port}/${dbname}"

                # Add connection via JupySQL API
                echo "  Adding connection: $alias"
                response=$(curl -sf -X POST "$JUPYSQL_API" \
                  -H "Content-Type: application/json" \
                  -d "{\"connection_string\": \"$conn_url\", \"alias\": \"$alias\"}" 2>&1) || {
                  echo "  Failed to add connection: $response"
                  continue
                }

                ADDED_CONNECTIONS[$conn_key]=1
                echo "  Successfully added: $alias"
              done
            done
          }

          # Initial discovery
          discover_and_add

          # Continuous polling for new clusters
          while true; do
            sleep "$POLL_INTERVAL"
            discover_and_add
          done
      env:
        - name: POLL_INTERVAL
          value: "60"  # Check for new clusters every 60 seconds
      resources:
        requests:
          cpu: 10m
          memory: 32Mi
        limits:
          cpu: 100m
          memory: 64Mi

# Ingress
ingress:
  enabled: true
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/proxy-body-size: "64m"
  hosts:
    - jupysql.example.com
  tls:
    - secretName: jupysql-tls
      hosts:
        - jupysql.example.com

# Cull idle servers
cull:
  enabled: true
  timeout: 3600
  every: 300
  maxAge: 28800

scheduling:
  userScheduler:
    enabled: false
  userPlaceholder:
    enabled: false
```

## Step 7: Install JupyterHub

```bash
helm upgrade --install jupysql jupyterhub/jupyterhub \
  --namespace jupysql \
  --values jupyterhub-values.yaml \
  --version 3.3.7
```

## Step 8: Verify Installation

```bash
# Check pods are running
kubectl get pods -n jupysql

# Check user pod has sidecar
kubectl get pods -n jupysql -l component=singleuser-server -o jsonpath='{.items[*].spec.containers[*].name}'
# Should show: notebook db-discovery

# View discovery sidecar logs
kubectl logs -n jupysql jupyter-<username> -c db-discovery -f
```

## Step 9: Configure DNS

Point your domain to the Ingress controller:

```bash
kubectl get svc -n ingress-nginx
```

## Using Read-Only Database Connections

For production databases, it's recommended to use read-only credentials. CNPG supports this via read replicas.

### Create Read-Only User in CNPG

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: production-db
  labels:
    jupysql.io/expose: "true"
    jupysql.io/readonly: "true"  # Use read-only credentials
spec:
  instances: 3

  # Enable managed roles
  managed:
    roles:
      - name: jupysql_readonly
        ensure: present
        login: true
        passwordSecret:
          name: production-db-ro
        connectionLimit: 10

  # Grant read-only access via bootstrap SQL
  bootstrap:
    initdb:
      postInitSQL:
        - GRANT CONNECT ON DATABASE app TO jupysql_readonly;
        - GRANT USAGE ON SCHEMA public TO jupysql_readonly;
        - GRANT SELECT ON ALL TABLES IN SCHEMA public TO jupysql_readonly;
        - ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO jupysql_readonly;
```

Create the password secret:

```bash
kubectl create secret generic production-db-ro \
  --from-literal=username=jupysql_readonly \
  --from-literal=password=$(openssl rand -base64 24) \
  -n databases
```

### Alternative: Create Read-Only Secret Manually

If you can't modify the CNPG cluster, create a read-only secret with the same format:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: production-db-ro
  namespace: databases
type: kubernetes.io/basic-auth
stringData:
  host: production-db-ro.databases.svc.cluster.local  # Read replica endpoint
  port: "5432"
  dbname: app
  user: readonly_user
  password: <readonly-password>
```

## Troubleshooting

### Sidecar not discovering databases

```bash
# Check sidecar logs
kubectl logs -n jupysql jupyter-<username> -c db-discovery

# Test RBAC permissions
kubectl auth can-i list clusters.postgresql.cnpg.io --as=system:serviceaccount:jupysql:jupysql-db-discovery
kubectl auth can-i get secrets --as=system:serviceaccount:jupysql:jupysql-db-discovery
```

### Connections not appearing in sidebar

```bash
# Check JupySQL API directly from user pod
kubectl exec -n jupysql jupyter-<username> -c notebook -- \
  curl -s http://localhost:8888/jupysql/connections
```

### Check Authentication

```bash
kubectl exec -n jupysql -it deploy/hub -- \
  curl -I https://dex.example.com/.well-known/openid-configuration
```

### Debug User Pod

```bash
kubectl describe pod -n jupysql jupyter-<username>
kubectl logs -n jupysql jupyter-<username> -c notebook
kubectl logs -n jupysql jupyter-<username> -c db-discovery
```

## Security Considerations

1. **Read-Only Access**: Use `jupysql.io/readonly=true` label for production databases
2. **Network Policies**: Restrict which pods can access database services
3. **Secret Rotation**: Integrate with external-secrets-operator for automatic rotation
4. **Audit Logging**: Enable PostgreSQL audit logging for compliance
5. **Namespace Isolation**: Limit RBAC to specific namespaces if needed:

```yaml
# Restrict to specific namespaces
apiVersion: rbac.authorization.k8s.io/v1
kind: Role  # Use Role instead of ClusterRole
metadata:
  name: jupysql-db-discovery
  namespace: databases  # Only this namespace
rules:
- apiGroups: ["postgresql.cnpg.io"]
  resources: ["clusters"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"]
```

## Customization

### Adding Pre-installed Python Packages

```yaml
singleuser:
  extraEnv:
    PIP_PACKAGES: "scikit-learn seaborn plotly"
  lifecycleHooks:
    postStart:
      exec:
        command: ["pip", "install", "--user", "scikit-learn", "seaborn", "plotly"]
```

### Restricting Access by Group

```yaml
hub:
  config:
    GenericOAuthenticator:
      allowed_groups:
        - data-team
        - analysts
      admin_groups:
        - platform-admins
      claim_groups_key: groups
```

### Multiple Database Types

The sidecar can be extended to discover other database types. Modify the discovery script to also check for:

- MySQL Operator clusters
- Redis clusters
- MongoDB Atlas connections via ConfigMaps

## Next Steps

- Configure [JupySQL connections file](./user-guide/connection-file.md) for persistent connections
- Set up [profiles](https://z2jh.jupyter.org/en/stable/jupyterhub/customizing/user-environment.html#using-multiple-profiles-to-let-users-select-their-environment) for different resource tiers
- Enable [shared notebooks](https://z2jh.jupyter.org/en/stable/jupyterhub/customizing/user-storage.html#shared-volumes) for team collaboration
