# Kubernetes RBAC Configuration for JupySQL CNPG Provider

This document describes the Kubernetes RBAC (Role-Based Access Control) permissions required for the JupySQL CNPG provider to discover and connect to CloudNativePG databases.

## Overview

The CNPG provider needs specific Kubernetes permissions to:
1. **List and watch CNPG resources** - Discover Cluster and Pooler objects
2. **Read secrets** - Retrieve database credentials
3. **Read serviceaccount namespace** - Auto-detect the current namespace

## Required Permissions

### Minimum Required Permissions

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: jupysql-cnpg-reader
  namespace: default  # Change to your namespace
rules:
  # Permission to discover CNPG clusters and poolers
  - apiGroups: ["postgresql.cnpg.io"]
    resources: ["clusters", "poolers"]
    verbs: ["get", "list", "watch"]

  # Permission to read database credentials from secrets
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
```

### Security Notes

1. **Secret Access**: The `get` permission on secrets allows reading ALL secrets in the namespace. For production:
   - Use a dedicated namespace for JupySQL
   - Limit secret access using resourceNames (see below)
   - Consider using secret management solutions like Vault

2. **Watch Permission**: The `watch` verb enables real-time updates but is optional. You can remove it if only periodic polling is needed.

3. **Namespace Scope**: Use `Role` (namespace-scoped) instead of `ClusterRole` to limit access to a single namespace.

## Production RBAC Configuration

### Option 1: Restrict Secret Access (Recommended)

If you know the secret names in advance, restrict access to specific secrets:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: jupysql-cnpg-reader
  namespace: databases  # Dedicated namespace
rules:
  - apiGroups: ["postgresql.cnpg.io"]
    resources: ["clusters", "poolers"]
    verbs: ["get", "list", "watch"]

  # Restrict to specific secrets only
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
    resourceNames:
      - "my-cluster-app"
      - "my-cluster-readonly"
      - "other-cluster-app"
```

### Option 2: Label-Based Secret Access

Use label selectors to restrict which secrets can be read:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: jupysql-cnpg-reader
  namespace: databases
rules:
  - apiGroups: ["postgresql.cnpg.io"]
    resources: ["clusters", "poolers"]
    verbs: ["get", "list", "watch"]

  # Only secrets with specific label
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list"]
    # Note: RBAC doesn't support label selectors directly
    # You need to use an admission controller or OPA for this
```

**Note**: Kubernetes RBAC doesn't natively support label selectors. Consider using:
- **Open Policy Agent (OPA)** for fine-grained secret access control
- **Kyverno** for policy-based secret access restrictions
- **Separate namespaces** as the simplest isolation mechanism

## Complete Example

### 1. ServiceAccount

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: jupysql
  namespace: databases
  labels:
    app: jupysql
```

### 2. Role

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: jupysql-cnpg-reader
  namespace: databases
rules:
  - apiGroups: ["postgresql.cnpg.io"]
    resources: ["clusters", "poolers"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
```

### 3. RoleBinding

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: jupysql-cnpg-reader
  namespace: databases
subjects:
  - kind: ServiceAccount
    name: jupysql
    namespace: databases
roleRef:
  kind: Role
  name: jupysql-cnpg-reader
  apiGroup: rbac.authorization.k8s.io
```

### 4. Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jupysql
  namespace: databases
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
          image: your-registry/jupysql:latest
          ports:
            - containerPort: 8888
          env:
            - name: JUPYSQL_CNPG_ENABLED
              value: "true"
            - name: JUPYSQL_CNPG_NAMESPACE
              value: "databases"
            - name: JUPYSQL_CNPG_LABEL_SELECTOR
              value: "jupysql.pandry.github.io/enabled=true"
```

## Multi-Namespace Setup

If you need to discover databases across multiple namespaces:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: jupysql-cnpg-reader
rules:
  - apiGroups: ["postgresql.cnpg.io"]
    resources: ["clusters", "poolers"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: jupysql-cnpg-reader
subjects:
  - kind: ServiceAccount
    name: jupysql
    namespace: jupysql-system
roleRef:
  kind: ClusterRole
  name: jupysql-cnpg-reader
  apiGroup: rbac.authorization.k8s.io
```

**⚠️ Warning**: ClusterRole grants access to ALL namespaces. Use with caution in production.

## Verification

Test the permissions before deploying:

```bash
# Check cluster access
kubectl auth can-i get clusters.postgresql.cnpg.io \
  --as=system:serviceaccount:databases:jupysql \
  -n databases

# Check secret access
kubectl auth can-i get secrets \
  --as=system:serviceaccount:databases:jupysql \
  -n databases

# List what the SA can do
kubectl auth can-i --list \
  --as=system:serviceaccount:databases:jupysql \
  -n databases
```

## Troubleshooting

### Permission Denied Errors

If you see errors like:
```
Error listing CNPG clusters: Forbidden: User "system:serviceaccount:default:jupysql"
cannot list resource "clusters" in API group "postgresql.cnpg.io"
```

**Solutions**:
1. Verify RoleBinding exists:
   ```bash
   kubectl get rolebinding jupysql-cnpg-reader -n databases
   ```

2. Check serviceAccountName in Deployment:
   ```bash
   kubectl get pod -l app=jupysql -o jsonpath='{.items[0].spec.serviceAccountName}'
   ```

3. Verify Role rules:
   ```bash
   kubectl describe role jupysql-cnpg-reader -n databases
   ```

### Secret Access Denied

If credentials can't be retrieved:

```
Warning: Could not retrieve password for cluster 'my-cluster', user 'app'
```

**Solutions**:
1. Verify secret exists:
   ```bash
   kubectl get secret my-cluster-app -n databases
   ```

2. Check secret permissions:
   ```bash
   kubectl auth can-i get secret/my-cluster-app \
     --as=system:serviceaccount:databases:jupysql \
     -n databases
   ```

3. Manually test secret retrieval:
   ```bash
   kubectl exec -it deployment/jupysql -- python3 -c "
   from kubernetes import client, config
   config.load_incluster_config()
   v1 = client.CoreV1Api()
   secret = v1.read_namespaced_secret('my-cluster-app', 'databases')
   print('Success!')
   "
   ```

## Security Best Practices

1. **Least Privilege**: Only grant permissions to the specific namespace where databases reside

2. **Secret Isolation**:
   - Use dedicated namespaces for database secrets
   - Don't store application secrets in the same namespace
   - Consider using resourceNames to restrict secret access

3. **Audit Logging**: Enable Kubernetes audit logging to track secret access:
   ```yaml
   apiVersion: audit.k8s.io/v1
   kind: Policy
   rules:
     - level: RequestResponse
       resources:
         - group: ""
           resources: ["secrets"]
   ```

4. **Network Policies**: Restrict pod-to-pod communication:
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: jupysql-allow-postgres
   spec:
     podSelector:
       matchLabels:
         app: jupysql
     policyTypes:
       - Egress
     egress:
       - to:
         - podSelector:
             matchLabels:
               cnpg.io/cluster: my-cluster
         ports:
           - protocol: TCP
             port: 5432
   ```

5. **Credential Rotation**: CNPG supports automatic credential rotation. JupySQL will discover new credentials on the next refresh cycle.

## References

- [Kubernetes RBAC Documentation](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
- [CloudNativePG Security](https://cloudnative-pg.io/documentation/current/security/)
- [Kubernetes Secrets Best Practices](https://kubernetes.io/docs/concepts/configuration/secret/#security-properties)
