# Quick Start: JupySQL with CNPG Provider

Get JupySQL automatically discovering your CloudNativePG databases in 5 minutes!

## Prerequisites

- Kubernetes cluster with CloudNativePG operator
- kubectl configured
- One or more CNPG clusters running

## Step 1: Label Your CNPG Clusters

Add the `jupysql.pandry.github.io/enabled=true` label to your CNPG clusters:

```bash
# Label an existing cluster
kubectl label cluster my-postgres-cluster jupysql.pandry.github.io/enabled=true

# Or edit the cluster YAML
kubectl edit cluster my-postgres-cluster
```

Add to the metadata:
```yaml
metadata:
  labels:
    jupysql.pandry.github.io/enabled: "true"
```

Verify:
```bash
kubectl get clusters -l jupysql.pandry.github.io/enabled=true
```

## Step 2: Create ServiceAccount and RBAC

**📖 For detailed RBAC configuration and security best practices, see [KUBERNETES_RBAC.md](KUBERNETES_RBAC.md)**

Save this as `jupysql-rbac.yaml`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: jupysql
  namespace: default
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: jupysql-cnpg-reader
  namespace: default
rules:
  - apiGroups: ["postgresql.cnpg.io"]
    resources: ["clusters", "poolers"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: jupysql-cnpg-reader
  namespace: default
subjects:
  - kind: ServiceAccount
    name: jupysql
roleRef:
  kind: Role
  name: jupysql-cnpg-reader
  apiGroup: rbac.authorization.k8s.io
```

Apply it:
```bash
kubectl apply -f jupysql-rbac.yaml
```

## Step 3: Deploy JupySQL

Save this as `jupysql-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jupysql
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: jupysql
  template:
    metadata:
      labels:
        app: jupysql
    spec:
      serviceAccountName: jupysql
      containers:
        - name: jupysql
          image: your-jupysql-image:latest
          ports:
            - containerPort: 8888
          env:
            - name: JUPYSQL_CNPG_ENABLED
              value: "true"
            - name: JUPYSQL_CNPG_LABEL_SELECTOR
              value: "jupysql.pandry.github.io/enabled=true"
---
apiVersion: v1
kind: Service
metadata:
  name: jupysql
  namespace: default
spec:
  selector:
    app: jupysql
  ports:
    - port: 8888
      targetPort: 8888
```

Apply it:
```bash
kubectl apply -f jupysql-deployment.yaml
```

## Step 4: Access JupyterLab

Port-forward to access JupyterLab:
```bash
kubectl port-forward svc/jupysql 8888:8888
```

Open your browser to http://localhost:8888

## Step 5: Use the Provider

In a Jupyter notebook:

```python
# The %sql magic is automatically loaded on kernel start
# (no need for %load_ext sql)

# List available databases
from sql.providers import get_factory

factory = get_factory()
databases = factory.list_databases()

print(f"Found {len(databases)} databases:")
for db in databases:
    print(f"  - {db.name} ({db.provider})")
```

Connect to a database:

```python
from sql.connection import ConnectionManager

# Connect to the first CNPG database
cnpg_dbs = [db for db in databases if db.provider == "cnpg"]
if cnpg_dbs:
    conn = ConnectionManager.connect_from_provider(
        identifier=cnpg_dbs[0].identifier,
        alias="production"
    )
    print(f"Connected to {conn.alias}")
```

Run queries:

```python
%%sql
SELECT version();
```

## Configuration Options

Customize the CNPG provider via environment variables:

```yaml
env:
  # Enable CNPG provider
  - name: JUPYSQL_CNPG_ENABLED
    value: "true"

  # Namespace to search (default: auto-detect)
  - name: JUPYSQL_CNPG_NAMESPACE
    value: "default"

  # Label selector (default: jupysql.pandry.github.io/enabled=true)
  - name: JUPYSQL_CNPG_LABEL_SELECTOR
    value: "jupysql.pandry.github.io/enabled=true,environment=production"

  # Auto-refresh interval in seconds (default: 100)
  - name: JUPYSQL_CNPG_AUTO_REFRESH_INTERVAL
    value: "60"

  # Manual refresh debounce in seconds (default: 5)
  - name: JUPYSQL_CNPG_DEBOUNCE_INTERVAL
    value: "10"
```

## Multiple Poolers

If you have both read-write and read-only poolers:

```bash
# Label the read-write pooler
kubectl label pooler my-db-rw jupysql.pandry.github.io/enabled=true jupysql.pandry.github.io/pooler-type=rw

# Label the read-only pooler
kubectl label pooler my-db-ro jupysql.pandry.github.io/enabled=true jupysql.pandry.github.io/pooler-type=ro
```

Both will appear in the database list:
```
my-db-rw (rw pooler)
my-db-ro (ro pooler)
```

## Custom Users

To use a different database user:

```bash
# Label the cluster with custom username
kubectl label cluster my-postgres-cluster jupysql.pandry.github.io/username=myuser
```

The provider will look for the secret `my-postgres-cluster-myuser`.

## Troubleshooting

### No databases found

1. Check labels:
   ```bash
   kubectl get clusters -l jupysql.pandry.github.io/enabled=true
   kubectl get poolers -l jupysql.pandry.github.io/enabled=true
   ```

2. Check JupySQL logs:
   ```bash
   kubectl logs -l app=jupysql
   ```

3. Verify RBAC permissions:
   ```bash
   kubectl auth can-i get clusters.postgresql.cnpg.io --as=system:serviceaccount:default:jupysql
   kubectl auth can-i get secrets --as=system:serviceaccount:default:jupysql
   ```

### Connection fails

1. Verify secret exists:
   ```bash
   kubectl get secret my-cluster-app
   kubectl get secret my-cluster-app -o jsonpath='{.data.password}' | base64 -d
   ```

2. Check cluster is ready:
   ```bash
   kubectl get cluster my-cluster
   ```

3. Test connectivity from pod:
   ```bash
   kubectl exec -it deployment/jupysql -- bash
   psql "postgresql://app:PASSWORD@my-cluster-rw.default.svc.cluster.local:5432/app"
   ```

## Next Steps

- Read the [full documentation](src/sql/providers/README.md)
- See the [complete Kubernetes example](examples/kubernetes-cnpg-setup.yaml)
- Try the [Python usage examples](examples/using_providers.py)

## Building and Deploying the Docker Image

**Note**: This guide uses a fork of JupySQL with enhanced CNPG provider support.

```bash
# Clone the repository
git clone <repository-url>
cd jupysql

# Build the image
docker build -t your-registry/jupysql-cnpg:latest .

# Push to registry
docker push your-registry/jupysql-cnpg:latest

# Update your deployment to use the new image
kubectl set image deployment/jupysql jupysql=your-registry/jupysql-cnpg:latest
```

Alternatively, use the image directly in your deployment:
```yaml
containers:
  - name: jupysql
    image: your-registry/jupysql-cnpg:latest
```

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review logs: `kubectl logs -l app=jupysql`
3. Verify Kubernetes setup with example manifests
4. Open an issue on GitHub

---

**That's it!** Your JupySQL instance now automatically discovers CNPG databases. Happy querying! 🎉
