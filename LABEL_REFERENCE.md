# JupySQL CNPG Label Reference

## Label Namespace

All JupySQL labels use the `jupysql.pandry.github.io/` namespace to avoid conflicts and follow Kubernetes domain-based label conventions.

## Required Labels

### Enable Discovery

To make a CNPG cluster or pooler discoverable by JupySQL:

```yaml
labels:
  jupysql.pandry.github.io/enabled: "true"
```

**This is the ONLY required label.** All others are optional.

## Optional Labels

### Custom Display Alias

Override the default display name:

```yaml
labels:
  jupysql.pandry.github.io/alias: "Production DB"
```

**Default behavior:**
- Clusters: `{cluster-name} (cluster)`
- Poolers: `{pooler-name} (rw pooler)` or `{pooler-name} (ro pooler)`

### Database Username

Specify which database user to connect as:

```yaml
labels:
  jupysql.pandry.github.io/username: "myuser"
```

**Default:** `app` (or `ro` if readonly=true)

The provider will look for secret: `{cluster-name}-{username}`

### Read-Only Mode

Mark a cluster as read-only to automatically use the `ro` user:

```yaml
labels:
  jupysql.pandry.github.io/readonly: "true"
```

**Default:** `false`

When `readonly=true` and no explicit username is set, the provider will:
1. Use username `ro`
2. Look for secret `{cluster-name}-ro`

### Pooler Type

For poolers, indicate whether it's read-write or read-only:

```yaml
labels:
  jupysql.pandry.github.io/pooler-type: "rw"  # or "ro"
```

**Default:** `rw`

This only affects the display name: `{pooler-name} (rw pooler)` vs `{pooler-name} (ro pooler)`

## Complete Examples

### Basic Cluster

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: my-postgres
  namespace: databases
  labels:
    jupysql.pandry.github.io/enabled: "true"
spec:
  instances: 3
  # ... rest of spec
```

**Result:** Discovered as "my-postgres (cluster)" using user `app` and secret `my-postgres-app`

### Read-Only Cluster

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: analytics-db
  namespace: databases
  labels:
    jupysql.pandry.github.io/enabled: "true"
    jupysql.pandry.github.io/readonly: "true"
    jupysql.pandry.github.io/alias: "Analytics (Read-Only)"
spec:
  instances: 3
  # ... rest of spec
```

**Result:** Discovered as "Analytics (Read-Only)" using user `ro` and secret `analytics-db-ro`

### Custom User

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: production-db
  namespace: databases
  labels:
    jupysql.pandry.github.io/enabled: "true"
    jupysql.pandry.github.io/username: "datascience"
    jupysql.pandry.github.io/alias: "Production"
spec:
  instances: 3
  # ... rest of spec
```

**Result:** Discovered as "Production" using user `datascience` and secret `production-db-datascience`

### Pooler (Read-Write)

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Pooler
metadata:
  name: my-pooler-rw
  namespace: databases
  labels:
    jupysql.pandry.github.io/enabled: "true"
    jupysql.pandry.github.io/pooler-type: "rw"
    jupysql.pandry.github.io/alias: "Production Pool (RW)"
spec:
  cluster:
    name: my-postgres
  instances: 2
  type: rw
  # ... rest of spec
```

**Result:** Discovered as "Production Pool (RW)" connecting to `my-pooler-rw.databases.svc.cluster.local:5432`

### Pooler (Read-Only)

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Pooler
metadata:
  name: my-pooler-ro
  namespace: databases
  labels:
    jupysql.pandry.github.io/enabled: "true"
    jupysql.pandry.github.io/pooler-type: "ro"
    jupysql.pandry.github.io/readonly: "true"
    jupysql.pandry.github.io/alias: "Analytics Pool (RO)"
spec:
  cluster:
    name: my-postgres
  instances: 2
  type: ro
  # ... rest of spec
```

**Result:** Discovered as "Analytics Pool (RO)" using user `ro` and secret `my-postgres-ro`

## Label Existing Resources

### Label a Cluster

```bash
kubectl label cluster my-postgres jupysql.pandry.github.io/enabled=true
```

### Add Multiple Labels

```bash
kubectl label cluster analytics-db \
  jupysql.pandry.github.io/enabled=true \
  jupysql.pandry.github.io/readonly=true \
  jupysql.pandry.github.io/alias="Analytics"
```

### Label a Pooler

```bash
kubectl label pooler my-pooler-rw \
  jupysql.pandry.github.io/enabled=true \
  jupysql.pandry.github.io/pooler-type=rw
```

## Verify Labels

```bash
# List all discoverable clusters
kubectl get clusters -A -l jupysql.pandry.github.io/enabled=true

# List all discoverable poolers
kubectl get poolers -A -l jupysql.pandry.github.io/enabled=true

# Show labels on a specific resource
kubectl get cluster my-postgres -o jsonpath='{.metadata.labels}' | jq
```

## Environment Variable Configuration

### Default Label Selector

```bash
JUPYSQL_CNPG_LABEL_SELECTOR=jupysql.pandry.github.io/enabled=true
```

### Custom Selector

You can combine multiple label selectors:

```bash
# Only production databases
JUPYSQL_CNPG_LABEL_SELECTOR="jupysql.pandry.github.io/enabled=true,environment=production"

# Only databases for a specific tenant
JUPYSQL_CNPG_LABEL_SELECTOR="jupysql.pandry.github.io/enabled=true,tenant=acme"
```

## Debugging

### Check Provider Configuration

In a Jupyter notebook:

```python
from sql.providers import get_factory

factory = get_factory()
cnpg = factory.get_provider("cnpg")

print(f"Enabled: {cnpg.is_enabled()}")
print(f"Namespace: {cnpg.namespace}")
print(f"Label selector: {cnpg.label_selector}")
```

### List Discovered Databases

```python
from sql.providers import get_factory

factory = get_factory()
databases = factory.list_databases(provider_names=["cnpg"])

print(f"Found {len(databases)} databases:")
for db in databases:
    print(f"  {db.name}")
    print(f"    Identifier: {db.identifier}")
    print(f"    Host: {db.host}")
    print(f"    Labels: {db.labels}")
```

### Force Refresh

```python
from sql.providers import get_factory

factory = get_factory()
factory.refresh_provider("cnpg")

# Check again
databases = factory.list_databases(provider_names=["cnpg"])
print(f"After refresh: {len(databases)} databases")
```

### Check Logs

The provider logs extensively at INFO and DEBUG levels:

```bash
# In JupyterLab, check the terminal output or
kubectl logs -l app=jupysql --tail=100

# Look for lines like:
# INFO:sql.providers.cnpg:CNPG Provider initialized:
# INFO:sql.providers.cnpg:  Namespace: databases
# INFO:sql.providers.cnpg:  Label selector: jupysql.pandry.github.io/enabled=true
# INFO:sql.providers.cnpg:CNPG provider refresh starting...
# INFO:sql.providers.cnpg:Discovered 2 CNPG cluster(s)
# INFO:sql.providers.cnpg:Added cluster: my-postgres (cluster) (cnpg:cluster:databases:my-postgres)
```

## Migration from Old Labels

If you were using the old label format:

| Old Label | New Label |
|-----------|-----------|
| `jupysql.enabled=true` | `jupysql.pandry.github.io/enabled=true` |
| `jupysql.username=myuser` | `jupysql.pandry.github.io/username=myuser` |
| `jupysql.pooler-type=rw` | `jupysql.pandry.github.io/pooler-type=rw` |
| `jupysql.io/expose=true` | `jupysql.pandry.github.io/enabled=true` |
| `jupysql.io/readonly=true` | `jupysql.pandry.github.io/readonly=true` |
| `jupysql.io/alias=name` | `jupysql.pandry.github.io/alias=name` |

### Bulk Update Script

```bash
#!/bin/bash
# Update all clusters
kubectl get clusters -A -l jupysql.enabled=true -o json | \
  jq -r '.items[] | "\(.metadata.namespace) \(.metadata.name)"' | \
  while read ns name; do
    kubectl label cluster -n "$ns" "$name" jupysql.pandry.github.io/enabled=true
    kubectl label cluster -n "$ns" "$name" jupysql.enabled-
  done

# Update all poolers
kubectl get poolers -A -l jupysql.enabled=true -o json | \
  jq -r '.items[] | "\(.metadata.namespace) \(.metadata.name)"' | \
  while read ns name; do
    kubectl label pooler -n "$ns" "$name" jupysql.pandry.github.io/enabled=true
    kubectl label pooler -n "$ns" "$name" jupysql.enabled-
  done
```

## Troubleshooting

### No Databases Discovered

1. **Check CNPG provider is enabled:**
   ```python
   from sql.providers import get_factory
   factory = get_factory()
   cnpg = factory.get_provider("cnpg")
   print(f"Enabled: {cnpg.is_enabled()}")
   ```

2. **Verify label selector matches:**
   ```bash
   # What the provider is looking for
   echo $JUPYSQL_CNPG_LABEL_SELECTOR

   # What's actually labeled
   kubectl get clusters -A --show-labels
   ```

3. **Check RBAC permissions:**
   ```bash
   kubectl auth can-i get clusters.postgresql.cnpg.io --as=system:serviceaccount:$NAMESPACE:$SERVICEACCOUNT
   kubectl auth can-i get poolers.postgresql.cnpg.io --as=system:serviceaccount:$NAMESPACE:$SERVICEACCOUNT
   kubectl auth can-i get secrets --as=system:serviceaccount:$NAMESPACE:$SERVICEACCOUNT
   ```

4. **Check logs for errors:**
   Look for ERROR or WARNING messages in the provider logs.

### Secret Not Found

If you see "Could not retrieve password for cluster 'X', user 'Y'":

1. **Verify secret exists:**
   ```bash
   kubectl get secret {cluster-name}-{username} -n {namespace}
   ```

2. **Check secret has password key:**
   ```bash
   kubectl get secret {cluster-name}-{username} -n {namespace} -o jsonpath='{.data.password}'
   ```

3. **Verify RBAC allows reading this secret:**
   ```bash
   kubectl auth can-i get secret/{cluster-name}-{username} -n {namespace} --as=system:serviceaccount:$NAMESPACE:$SERVICEACCOUNT
   ```
