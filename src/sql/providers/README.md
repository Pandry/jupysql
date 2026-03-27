# JupySQL Database Providers

Database providers enable automatic discovery and management of database connections from various sources.

## Overview

JupySQL supports multiple database providers:

1. **StaticDatabaseProvider** - Manually configured databases via API
2. **ConfigFileDatabaseProvider** - Databases from `~/.jupysql/connections.ini`
3. **CNPGDatabaseProvider** - Kubernetes CloudNativePG clusters and poolers

## CNPG Provider

The CNPG provider automatically discovers PostgreSQL databases from CloudNativePG clusters and poolers running in Kubernetes.

### Configuration

Configure the CNPG provider using environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `JUPYSQL_CNPG_ENABLED` | `false` | Enable CNPG provider |
| `JUPYSQL_CNPG_NAMESPACE` | auto-detect | Kubernetes namespace to search |
| `JUPYSQL_CNPG_LABEL_SELECTOR` | `jupysql.enabled=true` | Label selector for filtering |
| `JUPYSQL_CNPG_AUTO_REFRESH_INTERVAL` | `100` | Auto-refresh interval (seconds) |
| `JUPYSQL_CNPG_DEBOUNCE_INTERVAL` | `5` | Manual refresh debounce (seconds) |

### Kubernetes Setup

#### 1. Label Your CNPG Resources

Add labels to your CNPG Cluster or Pooler resources:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: my-postgres-cluster
  labels:
    jupysql.enabled: "true"
    jupysql.username: "app"  # Optional: specify username (default: "app")
spec:
  instances: 3
  # ... rest of cluster spec
```

For poolers:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Pooler
metadata:
  name: my-pooler-rw
  labels:
    jupysql.enabled: "true"
    jupysql.username: "app"
    jupysql.pooler-type: "rw"  # rw or ro
spec:
  cluster:
    name: my-postgres-cluster
  # ... rest of pooler spec
```

#### 2. Create ServiceAccount and RBAC

**📖 For detailed RBAC configuration, multi-namespace setup, and security best practices, see [KUBERNETES_RBAC.md](../../../KUBERNETES_RBAC.md)**

Create a ServiceAccount with permissions to list CNPG resources and read secrets:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: jupysql-sa
  namespace: default
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: jupysql-cnpg-reader
  namespace: default
rules:
  # Read CNPG clusters and poolers
  - apiGroups: ["postgresql.cnpg.io"]
    resources: ["clusters", "poolers"]
    verbs: ["get", "list", "watch"]
  # Read secrets for credentials
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: jupysql-cnpg-reader-binding
  namespace: default
subjects:
  - kind: ServiceAccount
    name: jupysql-sa
    namespace: default
roleRef:
  kind: Role
  name: jupysql-cnpg-reader
  apiGroup: rbac.authorization.k8s.io
```

#### 3. Deploy JupySQL with ServiceAccount

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jupysql
spec:
  template:
    spec:
      serviceAccountName: jupysql-sa
      containers:
        - name: jupysql
          image: your-jupysql-image:latest
          env:
            - name: JUPYSQL_CNPG_ENABLED
              value: "true"
            - name: JUPYSQL_CNPG_LABEL_SELECTOR
              value: "jupysql.enabled=true"
          ports:
            - containerPort: 8888
```

### How It Works

1. **Discovery**: The provider queries the Kubernetes API for CNPG Cluster and Pooler resources matching the label selector
2. **Credentials**: For each resource, it looks up the corresponding Kubernetes secret:
   - Secret name format: `{cluster-name}-{username}`
   - Key: `password`
   - Username: From label `jupysql.username` or defaults to `app`
3. **Connection String**: Builds PostgreSQL connection strings using:
   - Host: `{resource-name}-rw.{namespace}.svc.cluster.local`
   - Port: `5432`
   - Database: From cluster spec or defaults to `app`
   - Credentials: From secret

### Label Conventions

- `jupysql.enabled=true` - Include this resource in discovery
- `jupysql.username=myuser` - Username to use (default: `app`)
- `jupysql.pooler-type=rw` - Pooler type for display (rw/ro)

### Multiple Poolers

If you have both read-write and read-only poolers, label them separately:

```yaml
# Read-write pooler
apiVersion: postgresql.cnpg.io/v1
kind: Pooler
metadata:
  name: mydb-rw
  labels:
    jupysql.enabled: "true"
    jupysql.pooler-type: "rw"
---
# Read-only pooler
apiVersion: postgresql.cnpg.io/v1
kind: Pooler
metadata:
  name: mydb-ro
  labels:
    jupysql.enabled: "true"
    jupysql.pooler-type: "ro"
```

Both will be discovered and added to the database list.

## API Endpoints

### List Providers

```bash
GET /jupysql/providers
```

Returns:
```json
{
  "providers": [
    {"name": "static", "enabled": true},
    {"name": "config_file", "enabled": true},
    {"name": "cnpg", "enabled": true}
  ]
}
```

### List Available Databases

```bash
GET /jupysql/available-databases?providers=cnpg,config_file
```

Returns:
```json
{
  "databases": [
    {
      "identifier": "cnpg:cluster:default:my-cluster",
      "name": "my-cluster (cluster)",
      "connection_string": "postgresql://app:***@my-cluster-rw.default.svc.cluster.local:5432/app",
      "provider": "cnpg",
      "metadata": {
        "source": "cnpg_cluster",
        "namespace": "default",
        "cluster_name": "my-cluster"
      },
      "labels": {
        "jupysql.enabled": "true"
      }
    }
  ]
}
```

### Refresh Providers

```bash
POST /jupysql/providers/refresh
Content-Type: application/json

{
  "provider_name": "cnpg"  // Optional, refreshes all if omitted
}
```

### Connect to Database from Provider

```bash
POST /jupysql/providers/connect
Content-Type: application/json

{
  "identifier": "cnpg:cluster:default:my-cluster",
  "alias": "production-db"  // Optional
}
```

## Programmatic Usage

### Python API

```python
from sql.connection import ConnectionManager
from sql.providers import get_factory

# List all available databases
factory = get_factory()
databases = factory.list_databases()

for db in databases:
    print(f"{db.name}: {db.provider}")

# Connect to a database from a provider
conn = ConnectionManager.connect_from_provider(
    identifier="cnpg:cluster:default:my-cluster",
    alias="production"
)

# Refresh providers
ConnectionManager.refresh_providers("cnpg")
```

### Magic Commands

```python
# List available databases (future feature)
%sql --list-available

# Connect from provider
%sql --from-provider cnpg:cluster:default:my-cluster --alias production
```

## Security Considerations

1. **ServiceAccount Permissions**: Grant minimal permissions - only `get` on specific secrets
2. **Namespace Isolation**: Use namespace-scoped Roles, not ClusterRoles
3. **Label Filtering**: Use specific label selectors to limit discovery scope
4. **Password Storage**: Passwords are stored in memory only, never persisted
5. **Auto-refresh**: Be mindful of the refresh interval to avoid API rate limiting

## Troubleshooting

### CNPG Provider Not Discovering Databases

1. Check if CNPG provider is enabled:
   ```python
   from sql.providers import get_factory
   factory = get_factory()
   cnpg = factory.get_provider("cnpg")
   print(cnpg.is_enabled())
   ```

2. Verify Kubernetes permissions:
   ```bash
   kubectl auth can-i get clusters.postgresql.cnpg.io
   kubectl auth can-i get secrets
   ```

3. Check labels on CNPG resources:
   ```bash
   kubectl get clusters -l jupysql.enabled=true
   kubectl get poolers -l jupysql.enabled=true
   ```

4. Verify secrets exist:
   ```bash
   kubectl get secret my-cluster-app
   ```

### Connection Fails

1. Check service DNS resolution:
   ```bash
   kubectl exec -it my-pod -- nslookup my-cluster-rw.default.svc.cluster.local
   ```

2. Verify credentials:
   ```bash
   kubectl get secret my-cluster-app -o jsonpath='{.data.password}' | base64 -d
   ```

3. Check CNPG cluster status:
   ```bash
   kubectl get cluster my-cluster -o yaml
   ```
