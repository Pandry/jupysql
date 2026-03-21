# Kubernetes Installation Guide

This guide walks through deploying JupySQL on Kubernetes using the official JupyterHub Helm chart, with:

- **Shared JupyterLab instance** - All users share one server (expandable to per-team later)
- **Real-Time Collaboration (RTC)** - Multiple users edit notebooks together
- **Multiple kernels** - Each user can run independent computations
- **Dex OIDC authentication** - Authenticate users via your identity provider
- **CNPG database discovery** - Auto-discover PostgreSQL clusters with read-only `jupyter` user

## Prerequisites

- Kubernetes cluster (1.25+)
- Helm 3.x installed
- `kubectl` configured for your cluster
- nginx-ingress controller
- Dex instance (or other OIDC provider)
- (Optional) CloudNativePG operator installed for managed PostgreSQL

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Ingress (nginx)                               │
│                     jupysql.example.com                              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                          JupyterHub                                  │
│  ┌────────────┐  ┌────────────┐                                     │
│  │  Hub Pod   │  │ Proxy Pod  │                                     │
│  │ (spawner)  │  │ (routing)  │                                     │
│  └────────────┘  └────────────┘                                     │
│         │                                                            │
│         │  Shared collaboration account: "jupyter"                   │
│         ▼                                                            │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    jupyter (shared pod)                        │  │
│  │                                                                │  │
│  │  👤 Alice ──┐                                                  │  │
│  │  👤 Bob ────┼── All authenticated users share this server     │  │
│  │  👤 Carol ──┘   via role-based access                         │  │
│  │                                                                │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐              │  │
│  │  │ Kernel 1    │ │ Kernel 2    │ │ Kernel 3    │  ...         │  │
│  │  │ (Alice)     │ │ (Bob)       │ │ (Carol)     │              │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘              │  │
│  │                                                                │  │
│  │  RTC enabled - real-time collaborative editing                 │  │
│  │  DB Discovery sidecar - auto-discovers CNPG databases         │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
         │                                        │
         ▼                                        ▼
┌─────────────────┐                    ┌─────────────────────────────┐
│    Dex OIDC     │                    │  CNPG Clusters              │
│    (auth)       │                    │  (label: jupysql.io/expose) │
└─────────────────┘                    └─────────────────────────────┘
```

**How it works:**
1. Single shared **collaboration account** called `jupyter`
2. All authenticated users are granted **role-based access** to this server
3. Users log in via Dex, then access the shared `jupyter` server
4. **RTC enabled** - multiple users edit notebooks together in real-time
5. Each user can start independent kernels for their own computations

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

## Step 5: Create Shared Team Storage

Create a ReadWriteMany PVC that all team pods will share (each team gets a subdirectory):

```yaml
# team-storage-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jupysql-team-storage
  namespace: jupysql
spec:
  accessModes:
    - ReadWriteMany  # Required for shared access
  storageClassName: <your-rwx-storage-class>  # e.g., nfs, cephfs, longhorn, efs
  resources:
    requests:
      storage: 100Gi  # Shared across all teams
```

```bash
kubectl apply -f team-storage-pvc.yaml
```

**Note:** RWX storage classes vary by environment:
- **On-prem:** NFS, CephFS, Longhorn (with RWX)
- **AWS:** EFS (via efs-csi-driver)
- **GCP:** Filestore (via filestore-csi-driver)
- **Azure:** Azure Files

## Step 6: Configure Dex Client

Add JupyterHub as a client in your Dex configuration:

```yaml
# dex-config.yaml
issuer: https://dex.example.com

staticClients:
- id: jupyterhub
  name: JupyterHub
  secret: <generate-a-secure-secret>  # openssl rand -hex 32
  redirectURIs:
  - https://jupysql.example.com/hub/oauth_callback

oauth2:
  skipApprovalScreen: true
  responseTypes: ["code"]
```

**Note:** Team membership is managed in JupyterHub config (Step 7), not via Dex groups. Users just need to authenticate via Dex - their team assignment is defined in `hub.extraConfig`.

## Step 7: Create JupyterHub Values File

This configuration enables **team-based shared pods** with **real-time collaboration**:

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
        - groups  # Required for team routing
      username_claim: email
      claim_groups_key: groups  # Extract groups from token
      allow_all: true

  # Shared collaboration setup - all users share one server
  extraConfig:
    collaboration: |
      # Single shared collaboration account for all users
      collab_user = "jupyter"

      # All authenticated users go into the "users" group
      c.JupyterHub.load_groups = {
          "collaborative": {"users": [collab_user]},
          "users": {"users": []},  # Populated by authenticator
      }

      # Grant all authenticated users access to the shared server
      c.JupyterHub.load_roles = [
          {
              "name": "collab-access",
              "scopes": [
                  f"access:servers!user={collab_user}",   # Connect to server
                  f"admin:servers!user={collab_user}",    # Start/stop server
                  "admin-ui",                              # Access admin UI
                  f"list:users!user={collab_user}",       # See collab user
              ],
              "groups": ["users"],
          },
      ]

      # Auto-add authenticated users to the "users" group
      c.Authenticator.allowed_users = set()  # Allow all authenticated
      c.Authenticator.admin_users = set()

      async def post_auth_hook(authenticator, handler, authentication):
          username = authentication['name']
          # Add user to "users" group on login
          from jupyterhub.orm import Group
          from jupyterhub.app import JupyterHub
          app = JupyterHub.instance()
          group = Group.find(app.db, name="users")
          if group:
              user = app.users.get(username)
              if user and group not in user.groups:
                  user.groups.append(group)
                  app.db.commit()
          return authentication

      c.Authenticator.post_auth_hook = post_auth_hook

      # Enable RTC for the collaboration account
      def pre_spawn_hook(spawner):
          group_names = {group.name for group in spawner.user.groups}
          if "collaborative" in group_names:
              spawner.log.info(f"Enabling RTC for {spawner.user.name}")
              spawner.args.append("--LabApp.collaborative=True")

      c.KubeSpawner.pre_spawn_hook = pre_spawn_hook

singleuser:
  # JupySQL image
  image:
    name: ghcr.io/pandry/jupysql
    tag: master
    pullPolicy: Always

  # Use the discovery ServiceAccount
  serviceAccountName: jupysql-db-discovery

  # RTC is enabled via pre_spawn_hook for collaboration accounts

  # Resources (sized for team use - multiple kernels)
  cpu:
    limit: 4
    guarantee: 1
  memory:
    limit: 8G
    guarantee: 2G

  # Shared team storage (RWX for multiple users)
  # Each team gets a subdirectory via subPath (set in pre_spawn_hook)
  storage:
    type: static
    static:
      pvcName: jupysql-team-storage
      subPath: '{servername}'  # Team name from spawner
    homeMountPath: /home/jovyan

  # Alternative: dynamic storage per team
  # storage:
  #   type: dynamic
  #   capacity: 50Gi
  #   dynamic:
  #     storageClass: <your-rwx-storage-class>
  #   homeMountPath: /home/jovyan

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
                  # Use jupyter read-only user if available
                  secret_name="${cluster}-jupyter"
                  if ! kubectl get secret -n "$ns" "$secret_name" &>/dev/null; then
                    echo "  jupyter secret not found, falling back to app secret"
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

## Step 8: Install JupyterHub

```bash
helm upgrade --install jupysql jupyterhub/jupyterhub \
  --namespace jupysql \
  --values jupyterhub-values.yaml \
  --version 3.3.7
```

## Step 9: Verify Installation

```bash
# Check pods are running
kubectl get pods -n jupysql

# Check user pod has sidecar
kubectl get pods -n jupysql -l component=singleuser-server -o jsonpath='{.items[*].spec.containers[*].name}'
# Should show: notebook db-discovery

# View discovery sidecar logs
kubectl logs -n jupysql jupyter-<username> -c db-discovery -f
```

## Step 10: Configure DNS

Point your domain to the Ingress controller:

```bash
kubectl get svc -n ingress-nginx
```

## Using Read-Only Database Connections

For production databases, it's recommended to use read-only credentials. CNPG supports this via read replicas.

### Create Read-Only User in CNPG

First, create the password secret for the `jupyter` user:

```yaml
# jupyter-db-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: jupyter-db-credentials
  namespace: databases
type: kubernetes.io/basic-auth
stringData:
  username: jupyter
  password: <generate-secure-password>  # openssl rand -base64 24
```

Then configure the CNPG cluster with the `jupyter` user declaratively:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: production-db
  namespace: databases
  labels:
    jupysql.io/expose: "true"
    jupysql.io/readonly: "true"  # Tells sidecar to use jupyter-ro secret
spec:
  instances: 3

  # Declaratively managed roles
  managed:
    roles:
      - name: jupyter
        ensure: present
        login: true
        passwordSecret:
          name: jupyter-db-credentials
        connectionLimit: 20
        # Read-only: no createdb, no createrole, no superuser (defaults)

  # Grant read-only access on init
  bootstrap:
    initdb:
      postInitSQL:
        - GRANT CONNECT ON DATABASE app TO jupyter;
        - GRANT USAGE ON SCHEMA public TO jupyter;
        - GRANT SELECT ON ALL TABLES IN SCHEMA public TO jupyter;
        - ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO jupyter;
```

CNPG will automatically:
1. Create the `jupyter` role with the password from the secret
2. Keep the password in sync if you update the secret
3. Create a connection secret `production-db-jupyter` with full connection details

The sidecar looks for `<cluster>-ro` or `<cluster>-jupyter` secrets when `jupysql.io/readonly: "true"` is set.

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
