# Production Deployment Guide

This document covers deploying JupySQL in production: hardening the Docker image,
running it on Kubernetes with JupyterHub for multiple users and teams, configuring
single sign-on (SSO) with Google or Dex, and troubleshooting common issues.

---

## Table of Contents

1. [Prerequisites and mental model](#prerequisites-and-mental-model)
2. [Hardening the Docker image](#hardening-the-docker-image)
3. [Kubernetes with JupyterHub (multi-user)](#kubernetes-with-jupyterhub-multi-user)
   - [Architecture overview](#architecture-overview)
   - [Installing JupyterHub with Helm](#installing-jupyterhub-with-helm)
   - [Using the JupySQL image as the singleuser server](#using-the-jupysql-image-as-the-singleuser-server)
4. [Shared kernels and team workspaces](#shared-kernels-and-team-workspaces)
   - [Option A: Real-time collaboration (recommended)](#option-a-real-time-collaboration-recommended)
   - [Option B: Pre-configured team connections](#option-b-pre-configured-team-connections)
   - [Option C: Jupyter Enterprise Gateway](#option-c-jupyter-enterprise-gateway)
5. [SSO: Google as Identity Provider](#sso-google-as-identity-provider)
6. [SSO: Dex as Identity Provider](#sso-dex-as-identity-provider)
7. [Database credentials management](#database-credentials-management)
8. [Persistent storage](#persistent-storage)
9. [Network policies and security hardening](#network-policies-and-security-hardening)
10. [Common issues and troubleshooting](#common-issues-and-troubleshooting)

---

## Prerequisites and mental model

Before reading on, it helps to understand how the three layers of this system
relate to each other:

```
Browser
  │  HTTPS
  ▼
JupyterHub proxy  (single entry point, handles auth)
  │
  ├─► Hub process  (manages users, spawns/stops servers)
  │
  └─► Per-user JupyterLab server  (one Pod per user in K8s)
           │
           └─► IPython kernels  (one per open notebook)
                    └─► ConnectionManager  (holds SQL connections)
```

**JupyterHub** is the standard open-source tool for running Jupyter for multiple
users.  It spawns an isolated JupyterLab server (a Pod on Kubernetes) for each
user when they log in, and proxies their browser traffic to it.

**The JupySQL image** becomes the *singleuser server* image — the container that
runs JupyterLab + the JupySQL extension inside each user's Pod.

**SQL connections** live in the IPython kernel, which runs inside the user's Pod.
The JupySQL sidebar extension communicates with the kernel via the REST API
defined in `src/sql/labextension/handlers.py`.

---

## Hardening the Docker image

The development `Dockerfile` starts JupyterLab with all security features
disabled (`--ServerApp.token='' ... --ServerApp.disable_check_xsrf=True`).
**Never use those flags in production.**

When running behind JupyterHub the hub configures authentication for you; you
only need to make sure the image is clean and runs as a non-root user.

### Production Dockerfile

```dockerfile
# ── Stage 1: build the JupyterLab extension ──────────────────────────────────
FROM docker.io/library/python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY package.json setup.py setup.cfg pyproject.toml MANIFEST.in README.md ./
COPY jupysql_labextension/package.json jupysql_labextension/
COPY jupysql_labextension/tsconfig.json jupysql_labextension/

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir 'jupyterlab>=4.0.0,<5'

COPY src/             src/
COPY jupysql_labextension/src/   jupysql_labextension/src/
COPY jupysql_labextension/style/ jupysql_labextension/style/
COPY jupyter-config/  jupyter-config/

WORKDIR /build/jupysql_labextension
RUN npm ci && npm run build:lib:prod && npm run build:labextension

# ── Stage 2: production runtime ───────────────────────────────────────────────
FROM docker.io/library/python:3.11-slim

# Install only what is needed at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user — JupyterHub sets the UID at spawn time via
# KubeSpawner.uid, but having a named user makes the image easier to reason about.
ARG NB_USER=jovyan
ARG NB_UID=1000
RUN useradd --create-home --shell /bin/bash --uid "${NB_UID}" "${NB_USER}"

WORKDIR /app

COPY --from=builder /build/ /app/
COPY --from=builder /build/jupysql/labextension/ /app/jupysql/labextension/

# jupyterhub package needed so jupyterhub-singleuser entrypoint is available
# and the server can register itself with the Hub via the API token.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        'jupyterlab>=4.0.0,<5' \
        'jupyterhub>=4.0.0' \
        psycopg2-binary duckdb-engine matplotlib pandas

RUN pip install -e . && \
    mkdir -p /usr/local/share/jupyter/labextensions/jupysql-labextension && \
    cp -r jupysql/labextension/. \
          /usr/local/share/jupyter/labextensions/jupysql-labextension/ && \
    mkdir -p /usr/local/etc/jupyter/jupyter_server_config.d/ && \
    cp jupyter-config/jupyter_server_config.d/jupysql.json \
       /usr/local/etc/jupyter/jupyter_server_config.d/jupysql.json

RUN jupyter server extension list && jupyter labextension list

# Switch to the non-root user for the runtime
USER ${NB_USER}
WORKDIR /home/${NB_USER}

EXPOSE 8888

# NOTE: No --ServerApp.token or --ServerApp.password here.
# JupyterHub injects its own token and sets up the hub URL via environment
# variables (JUPYTERHUB_API_TOKEN, JUPYTERHUB_SERVICE_URL, etc.) when it
# spawns this container.  Use `jupyterhub-singleuser` as the entrypoint so
# the server registers itself with the Hub correctly.
CMD ["jupyterhub-singleuser", "--ip=0.0.0.0", "--port=8888"]
```

### Key differences from the dev image

| Setting | Development | Production |
|---------|-------------|------------|
| Token auth | Disabled (`token=''`) | Managed by JupyterHub |
| XSRF | Disabled | Enabled (only the extension endpoints opt out, which is safe) |
| User | root | non-root `jovyan` |
| Entrypoint | `jupyter lab` | `jupyterhub-singleuser` |
| `npm run build` | dev build (source maps) | `build:lib:prod` (minified) |

---

## Kubernetes with JupyterHub (multi-user)

### Architecture overview

```
Namespace: jupyterhub
│
├── Deployment: hub           (JupyterHub process)
├── Deployment: proxy         (configurable-http-proxy)
├── Service:    proxy-public  (LoadBalancer / Ingress entry point)
│
└── Per-user (created at login, deleted at logout):
    ├── Pod:        jupyter-<username>
    ├── PVC:        claim-<username>   (home directory)
    └── Service:    jupyter-<username>
```

### Installing JupyterHub with Helm

The official Zero to JupyterHub Helm chart is the standard installation path.

```bash
# Add the JupyterHub Helm repo
helm repo add jupyterhub https://hub.jupyter.org/helm-chart/
helm repo update

# Create a namespace
kubectl create namespace jupyterhub

# Deploy (replace values with your own — see below)
helm upgrade --install jupyterhub jupyterhub/jupyterhub \
  --namespace jupyterhub \
  --version 3.3.8 \
  --values config.yaml \
  --timeout 10m
```

### Using the JupySQL image as the singleuser server

In `config.yaml` (your Helm values file), point the singleuser profile at your
published JupySQL image:

```yaml
# config.yaml — Helm values for JupyterHub

singleuser:
  image:
    name: your-registry/jupysql-lab   # your production image
    tag: "1.0.0"
    pullPolicy: IfNotPresent

  # Default resource limits — tune for your workload
  cpu:
    limit: 2
    guarantee: 0.5
  memory:
    limit: 4G
    guarantee: 512M

  # Storage: each user gets a persistent home directory
  storage:
    type: dynamic
    capacity: 10Gi
    homeMountPath: /home/jovyan

  # Environment variables available in every user's kernel
  extraEnv:
    JUPYTER_ENABLE_LAB: "yes"

  # Lifecycle hooks — run after the server starts
  # (useful for pre-loading extensions or notebooks)
  lifecycleHooks:
    postStart:
      exec:
        command:
          - "sh"
          - "-c"
          - |
            # Copy team notebooks from a shared location on first login
            [ -d /home/jovyan/shared ] || ln -s /shared/notebooks /home/jovyan/shared

hub:
  config:
    # Authentication is configured in the sections below
    JupyterHub:
      admin_access: true
```

#### Multiple profiles (optional)

If your teams need different resource allocations or pre-loaded packages,
define named profiles:

```yaml
singleuser:
  profileList:
    - display_name: "Standard (2 CPU / 4 GB)"
      description: "For everyday analysis"
      default: true
      kubespawner_override:
        cpu_limit: 2
        mem_limit: "4G"

    - display_name: "Large (8 CPU / 32 GB)"
      description: "For heavy data processing"
      kubespawner_override:
        cpu_limit: 8
        mem_limit: "32G"

    - display_name: "GPU"
      description: "Includes CUDA drivers"
      kubespawner_override:
        image: your-registry/jupysql-lab-gpu:1.0.0
        extra_resource_limits:
          nvidia.com/gpu: "1"
```

---

## Shared kernels and team workspaces

### The challenge

JupyterHub's default model gives each user a completely isolated server (Pod).
SQL connections live inside IPython kernels, which live inside that isolated Pod.
"Sharing a kernel" means multiple users working in the same IPython process.

There are three practical approaches, each with different trade-offs.

---

### Option A: Real-time collaboration (recommended)

JupyterHub 4.x supports **real-time collaboration (RTC)** via the
`jupyter-collaboration` package.  In RTC mode multiple users can join the same
user's server and share its kernels live — edits to a notebook are synchronized
in real time, and every collaborator runs code in the same kernel, which means
they share the same `ConnectionManager` state.

#### How it works

1. User A logs in → JupyterHub spawns their Pod and server.
2. User B navigates to `https://<hub>/user/user-a/` → JupyterHub proxies them
   into User A's server (if User A has granted access or if admins have
   configured shared access).
3. Both users see the same notebook and run code in the same kernel.
4. Any `%sql` connection opened by User A is immediately visible to User B
   in the JupySQL sidebar.

#### Setup

```bash
# Install in the JupySQL image (add to Dockerfile)
pip install jupyter-collaboration
```

Enable in the Hub Helm values:

```yaml
# config.yaml
hub:
  extraConfig:
    collaboration: |
      # Allow users to access each other's servers
      c.JupyterHub.load_roles = [
        {
          "name": "user",
          "scopes": [
            "self",
            # allow any logged-in user to access any other user's server
            # (restrict this with groups if you want team-only access)
            "access:servers",
          ],
        }
      ]

singleuser:
  extraEnv:
    # Enable RTC mode in JupyterLab
    JUPYTER_COLLABORATIVE: "true"

  # JupyterLab starts with collaboration mode enabled
  cmd:
    - "jupyterhub-singleuser"
    - "--collaborative"
```

#### Team-scoped access with groups

To restrict collaboration to teams rather than all users:

```yaml
hub:
  extraConfig:
    teams: |
      # Only members of the same group can access each other's servers
      c.JupyterHub.load_roles = [
        {
          "name": "team-analytics-collab",
          "scopes": ["access:servers!group=analytics"],
          "groups": ["analytics"],
        },
        {
          "name": "team-ml-collab",
          "scopes": ["access:servers!group=ml"],
          "groups": ["ml"],
        },
      ]
```

Users in the `analytics` group can navigate to any other `analytics` member's
server; users in `ml` can only access `ml` servers.  Group membership is
populated by the authenticator (see the SSO sections below).

#### Limitations of RTC

- All collaborators share the **same file system** (User A's PVC).  User B's
  own notebooks remain on their own PVC, which they can access on their own server.
- If User A's server is stopped, all collaborators lose access.
- Network latency affects the real-time sync experience.

---

### Option B: Pre-configured team connections

Rather than sharing kernels, configure each team's database connections
centrally so they are available automatically when any team member's server
starts.  This is simpler and more robust than kernel sharing.

#### Using environment variables

Inject connection strings as environment variables, then auto-connect on kernel
startup via a JupyterLab startup script.

In `config.yaml`:

```yaml
singleuser:
  extraEnv:
    # These are picked up by the startup script below
    TEAM_DB_URL: "postgresql://analyst:secret@postgres.internal/analytics"
    TEAM_DB_ALIAS: "analytics-db"

  # Run this script every time a kernel starts
  lifecycleHooks:
    postStart:
      exec:
        command:
          - "sh"
          - "-c"
          - |
            mkdir -p /home/jovyan/.ipython/profile_default/startup
            cat > /home/jovyan/.ipython/profile_default/startup/00-jupysql.py << 'EOF'
            import os
            db_url   = os.environ.get("TEAM_DB_URL")
            db_alias = os.environ.get("TEAM_DB_ALIAS", "")
            if db_url:
                ip = get_ipython()
                ip.run_line_magic("load_ext", "sql")
                args = db_url + (f" --alias {db_alias}" if db_alias else "")
                ip.run_line_magic("sql", args)
            EOF
```

The startup script runs inside every new kernel, so the connection is available
in the JupySQL sidebar without any user action.

#### Using Kubernetes Secrets

Never put database passwords in plain-text Helm values.  Use Kubernetes Secrets
and mount them as environment variables:

```bash
# Create the Secret
kubectl create secret generic team-db-creds \
  --namespace jupyterhub \
  --from-literal=TEAM_DB_URL="postgresql://analyst:s3cret@postgres.internal/analytics"
```

```yaml
# config.yaml
singleuser:
  extraEnv:
    TEAM_DB_URL:
      valueFrom:
        secretKeyRef:
          name: team-db-creds
          key: TEAM_DB_URL
```

---

### Option C: Jupyter Enterprise Gateway

[Jupyter Enterprise Gateway](https://jupyter-enterprise-gateway.readthedocs.io/)
(JEG) decouples kernels from the JupyterLab server.  Kernels run on remote
machines (or as separate Kubernetes Pods) managed by JEG, and multiple
JupyterLab servers can connect to the same kernel.

This is the most powerful option for true kernel sharing but also the most
operationally complex.  Use it when:

- Teams need to run long-lived kernels that survive individual user sessions.
- Kernels need more resources than a user's normal Pod can provide.
- Multiple users need to connect to the same already-running computation.

JEG setup is outside the scope of this document.  See the
[Zero to JEG guide](https://jupyter-enterprise-gateway.readthedocs.io/en/latest/getting-started-kubernetes.html)
for Kubernetes installation instructions.

---

## SSO: Google as Identity Provider

Google OAuth2 is the simplest SSO integration if your organization uses Google
Workspace (G Suite).

### 1. Create a Google OAuth2 application

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs &
   Services → Credentials.
2. Click **Create Credentials** → **OAuth client ID**.
3. Application type: **Web application**.
4. Authorized redirect URIs: `https://<your-hub-domain>/hub/oauth_callback`
5. Note the **Client ID** and **Client Secret**.

### 2. Store credentials in a Kubernetes Secret

```bash
kubectl create secret generic jupyterhub-google-oauth \
  --namespace jupyterhub \
  --from-literal=client_id="123456789-abc.apps.googleusercontent.com" \
  --from-literal=client_secret="GOCSPX-your-secret"
```

### 3. Configure JupyterHub

```yaml
# config.yaml
hub:
  extraEnv:
    GOOGLE_CLIENT_ID:
      valueFrom:
        secretKeyRef:
          name: jupyterhub-google-oauth
          key: client_id
    GOOGLE_CLIENT_SECRET:
      valueFrom:
        secretKeyRef:
          name: jupyterhub-google-oauth
          key: client_secret

  config:
    JupyterHub:
      authenticator_class: google

    GoogleOAuthenticator:
      client_id:     "$(GOOGLE_CLIENT_ID)"
      client_secret: "$(GOOGLE_CLIENT_SECRET)"

      # Restrict login to a specific Google Workspace domain
      hosted_domain:
        - "yourcompany.com"

      # Map Google groups to JupyterHub admin status
      admin_google_groups:
        - "data-platform-admins@yourcompany.com"

      # Map Google groups to JupyterHub groups (used for RTC team scoping)
      # Requires the Google Admin SDK API to be enabled and service account
      # credentials to be configured (see oauthenticator docs).
      manage_groups: true

      # Users not in this list cannot log in (comment out to allow any domain member)
      allowed_google_groups:
        - "data-analysts@yourcompany.com"
        - "ml-engineers@yourcompany.com"

      # OAuth2 scopes — openid + email is the minimum; profile gives display name
      scope:
        - "openid"
        - "email"
        - "profile"

    # The callback URL must match what you registered in Google Cloud Console
    Authenticator:
      auto_login: true  # skip the JupyterHub login page, go straight to Google
```

### 4. Install the required Python package

Add to your Hub image or specify it in the Helm values:

```yaml
hub:
  extraPip:
    - oauthenticator>=16.0
```

### 5. Group-to-team mapping (optional)

If you want JupySQL teams to match Google Groups, enable the `manage_groups`
option (requires Google Admin SDK API and a service account):

```bash
# Store the service account JSON key as a Secret
kubectl create secret generic google-service-account \
  --namespace jupyterhub \
  --from-file=credentials.json=/path/to/service-account-key.json
```

```yaml
hub:
  extraVolumes:
    - name: google-sa
      secret:
        secretName: google-service-account

  extraVolumeMounts:
    - name: google-sa
      mountPath: /etc/google
      readOnly: true

  extraEnv:
    GOOGLE_APPLICATION_CREDENTIALS: "/etc/google/credentials.json"

  config:
    GoogleOAuthenticator:
      manage_groups: true
      # Groups are synced from Google on every login
```

---

## SSO: Dex as Identity Provider

[Dex](https://dexidp.io/) is an open-source OpenID Connect (OIDC) provider that
federates to many upstream identity sources: LDAP/Active Directory, GitHub,
SAML, other OIDC providers, and more.  Use Dex when:

- Your organization uses LDAP or Active Directory and you need to bridge it to OIDC.
- You want a single OIDC endpoint that aggregates multiple upstream IdPs.
- You need fine-grained control over claims and group mappings without modifying
  JupyterHub's authenticator.

### Architecture with Dex

```
Browser
  └─► JupyterHub  ─OIDC──► Dex  ─connector──► LDAP / GitHub / SAML / Google
```

JupyterHub treats Dex as an opaque OIDC provider; Dex handles the federation
complexity.

### 1. Deploy Dex on Kubernetes

```bash
helm repo add dex https://charts.dexidp.io
helm repo update

helm upgrade --install dex dex/dex \
  --namespace dex \
  --create-namespace \
  --values dex-values.yaml
```

**`dex-values.yaml`** — minimal example with GitHub + LDAP connectors:

```yaml
# dex-values.yaml
config:
  issuer: "https://dex.yourcompany.com"

  storage:
    type: kubernetes
    config:
      inCluster: true

  web:
    http: 0.0.0.0:5556

  # OAuth2 clients — one entry per application that uses Dex
  staticClients:
    - id: jupyterhub
      name: JupyterHub
      # Store this in a Kubernetes Secret in production (see secretEnv below)
      secret: "change-me-to-a-long-random-string"
      redirectURIs:
        - "https://<your-hub-domain>/hub/oauth_callback"

  connectors:
    # ── GitHub connector ──────────────────────────────────────────────────────
    - type: github
      id: github
      name: GitHub
      config:
        clientID: "$GITHUB_CLIENT_ID"        # from a Kubernetes Secret
        clientSecret: "$GITHUB_CLIENT_SECRET"
        redirectURI: "https://dex.yourcompany.com/callback"
        # Restrict to members of a specific GitHub org
        orgs:
          - name: yourcompany
            # Map GitHub teams to Dex groups
            teams:
              - data-platform
              - ml-engineers

    # ── LDAP / Active Directory connector ─────────────────────────────────────
    - type: ldap
      id: ldap
      name: LDAP
      config:
        host: "ldap.yourcompany.com:636"
        insecureNoSSL: false
        rootCA: "/etc/dex/ldap-ca.crt"

        # Service account for directory lookups
        bindDN: "cn=dex,ou=service-accounts,dc=yourcompany,dc=com"
        bindPW: "$LDAP_BIND_PASSWORD"

        usernamePrompt: "Email"

        userSearch:
          baseDN: "ou=users,dc=yourcompany,dc=com"
          filter: "(objectClass=person)"
          username: mail
          idAttr: DN
          emailAttr: mail
          nameAttr: displayName

        groupSearch:
          baseDN: "ou=groups,dc=yourcompany,dc=com"
          filter: "(objectClass=groupOfNames)"
          userMatchers:
            - userAttr: DN
              groupAttr: member
          nameAttr: cn

  oauth2:
    skipApprovalScreen: true
    # Return groups in the ID token so JupyterHub can read them
    responseTypes: ["code"]
    grantTypes: ["authorization_code", "refresh_token"]

# Expose Dex externally (add TLS via cert-manager in production)
ingress:
  enabled: true
  hosts:
    - host: dex.yourcompany.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - dex.yourcompany.com
      secretName: dex-tls
```

For sensitive values (client secrets, LDAP bind password), use Kubernetes
Secrets and reference them in Dex's `envFrom`:

```yaml
# dex-values.yaml (continued)
envFrom:
  - secretRef:
      name: dex-connectors-secrets  # contains GITHUB_CLIENT_ID, LDAP_BIND_PASSWORD, etc.
```

### 2. Configure JupyterHub to use Dex

Store the Dex client secret:

```bash
kubectl create secret generic jupyterhub-dex-oidc \
  --namespace jupyterhub \
  --from-literal=client_secret="change-me-to-a-long-random-string"
```

```yaml
# config.yaml
hub:
  extraEnv:
    OIDC_CLIENT_SECRET:
      valueFrom:
        secretKeyRef:
          name: jupyterhub-dex-oidc
          key: client_secret

  config:
    JupyterHub:
      authenticator_class: "oauthenticator.generic.GenericOAuthenticator"

    GenericOAuthenticator:
      client_id:     "jupyterhub"          # must match dex staticClients[].id
      client_secret: "$(OIDC_CLIENT_SECRET)"

      # Dex endpoints (replace with your actual Dex domain)
      authorize_url:    "https://dex.yourcompany.com/auth"
      token_url:        "https://dex.yourcompany.com/token"
      userdata_url:     "https://dex.yourcompany.com/userinfo"

      # OIDC discovery is simpler — use this if you prefer auto-configuration
      # login_service:  "dex"
      # oidc_issuer:    "https://dex.yourcompany.com"

      # The claim in the ID token that contains the username
      username_claim: "email"

      # Request groups to be included in the token
      scope:
        - "openid"
        - "email"
        - "profile"
        - "groups"          # Dex emits group membership in this scope

      # Map the "groups" claim from the token to JupyterHub groups
      claim_groups_key: "groups"
      manage_groups:    true

      # Allow only specific groups to log in
      allowed_groups:
        - "yourcompany:data-platform"   # GitHub org:team format
        - "data-analysts"               # LDAP cn format

      # Groups whose members become JupyterHub admins
      admin_groups:
        - "yourcompany:data-platform"

  extraPip:
    - oauthenticator>=16.0
```

### 3. OIDC discovery (alternative, simpler approach)

If Dex exposes a discovery document (it does by default at
`https://dex.yourcompany.com/.well-known/openid-configuration`), you can use
the OIDC authenticator which auto-configures all endpoints:

```yaml
hub:
  config:
    JupyterHub:
      authenticator_class: "oauthenticator.openid.OpenIDConnectAuthenticator"

    OpenIDConnectAuthenticator:
      client_id:     "jupyterhub"
      client_secret: "$(OIDC_CLIENT_SECRET)"
      oidc_issuer:   "https://dex.yourcompany.com"
      scope:
        - "openid"
        - "email"
        - "profile"
        - "groups"
      username_claim:    "email"
      claim_groups_key:  "groups"
      manage_groups:     true
      allowed_groups:
        - "data-analysts"
```

---

## Database credentials management

Database passwords must never be stored in Helm values or baked into the image.
Use Kubernetes Secrets and mount them as environment variables.

### Per-team connection strings

```bash
# Create one Secret per team
kubectl create secret generic db-creds-analytics \
  --namespace jupyterhub \
  --from-literal=DB_URL="postgresql://analyst_ro:s3cret@pg.internal/analytics"

kubectl create secret generic db-creds-ml \
  --namespace jupyterhub \
  --from-literal=DB_URL="postgresql://ml_ro:s3cret@pg.internal/ml_datalake"
```

Use KubeSpawner's `profile_list` to inject the right credentials per team:

```yaml
singleuser:
  profileList:
    - display_name: "Analytics team"
      kubespawner_override:
        extra_env:
          DB_URL:
            valueFrom:
              secretKeyRef:
                name: db-creds-analytics
                key: DB_URL
          DB_ALIAS: "analytics-db"

    - display_name: "ML team"
      kubespawner_override:
        extra_env:
          DB_URL:
            valueFrom:
              secretKeyRef:
                name: db-creds-ml
                key: DB_URL
          DB_ALIAS: "ml-datalake"
```

### External secrets operator (recommended at scale)

For larger deployments, use the
[External Secrets Operator](https://external-secrets.io/) to sync credentials
from Vault, AWS Secrets Manager, or GCP Secret Manager into Kubernetes Secrets
automatically:

```yaml
# ExternalSecret that pulls from HashiCorp Vault
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: db-creds-analytics
  namespace: jupyterhub
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: db-creds-analytics
  data:
    - secretKey: DB_URL
      remoteRef:
        key: secret/data/jupysql/analytics
        property: db_url
```

---

## Persistent storage

Each user's notebooks and local files live on a PersistentVolumeClaim (PVC)
created by KubeSpawner at first login.

### Home directory PVC

```yaml
singleuser:
  storage:
    type: dynamic
    capacity: 10Gi
    storageClass: standard     # use your cluster's preferred StorageClass
    homeMountPath: /home/jovyan
    dynamic:
      storageClass: standard
      pvcNameTemplate: "claim-{username}"
      volumeNameTemplate: "claim-{username}"
      storageAccessModes: ["ReadWriteOnce"]
```

### Shared team read-only volumes

To give all users access to shared datasets without copying:

```yaml
# A ReadWriteMany PVC (backed by NFS, CephFS, or similar)
# --- shared-data-pvc.yaml ---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: shared-datasets
  namespace: jupyterhub
spec:
  accessModes: ["ReadOnlyMany"]
  resources:
    requests:
      storage: 500Gi
  storageClassName: nfs-storage
```

```yaml
# config.yaml — mount the shared PVC into every user Pod
singleuser:
  extraVolumes:
    - name: shared-datasets
      persistentVolumeClaim:
        claimName: shared-datasets
        readOnly: true

  extraVolumeMounts:
    - name: shared-datasets
      mountPath: /shared/datasets
      readOnly: true
```

---

## Network policies and security hardening

### Restrict kernel-to-internet access

By default pods can reach the internet.  Restrict outbound traffic so kernels
can only talk to approved databases and the JupyterHub API:

```yaml
# network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: jupysql-singleuser
  namespace: jupyterhub
spec:
  podSelector:
    matchLabels:
      component: singleuser-server    # label applied by KubeSpawner
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Only the JupyterHub proxy may initiate connections to user Pods
    - from:
        - podSelector:
            matchLabels:
              component: proxy
  egress:
    # JupyterHub Hub API (for token validation)
    - to:
        - podSelector:
            matchLabels:
              component: hub
      ports:
        - port: 8081
    # Approved databases (adjust CIDRs / ports for your environment)
    - to:
        - ipBlock:
            cidr: 10.0.0.0/8    # internal network range
      ports:
        - port: 5432    # PostgreSQL
        - port: 3306    # MySQL
        - port: 1433    # MSSQL
    # DNS
    - to:
        - namespaceSelector: {}
      ports:
        - port: 53
          protocol: UDP
```

### Pod security standards

```yaml
# config.yaml
singleuser:
  extraLabels:
    # Enforce restricted pod security (no privileged containers, no host paths, etc.)
    pod-security.kubernetes.io/enforce: restricted

  uid: 1000
  fsGid: 100

  extraPodConfig:
    securityContext:
      runAsNonRoot: true
      seccompProfile:
        type: RuntimeDefault
```

### TLS / Ingress

Route external HTTPS traffic through an Ingress with TLS termination:

```yaml
# config.yaml
proxy:
  service:
    type: ClusterIP    # let the Ingress handle the external exposure

ingress:
  enabled: true
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/proxy-body-size: "0"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"    # long-lived WebSocket connections
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
  hosts:
    - "jupyter.yourcompany.com"
  tls:
    - hosts:
        - "jupyter.yourcompany.com"
      secretName: jupyterhub-tls
```

---

## Common issues and troubleshooting

### Sidebar shows "Error loading connections" or empty state

**Symptom**: The database browser sidebar shows an error or no connections even
though the user has run `%sql` in a notebook.

**Causes and fixes**:

1. **No running kernel** — the sidebar queries the kernel for connections.  Open a
   notebook and run at least one cell to ensure a kernel is started before
   using the sidebar.

2. **Server extension not loaded** — verify the extension is registered:
   ```bash
   kubectl exec -n jupyterhub pod/jupyter-<username> -- \
     jupyter server extension list
   # You should see: sql.labextension  enabled
   ```
   If it is missing, check that the `jupyter-config/` files were copied into
   the image correctly (see the Dockerfile).

3. **CORS or proxy misconfiguration** — the sidebar makes REST calls to
   `/jupysql/connections`.  If the Ingress strips or rewrites the path, the
   calls will 404.  Check the proxy logs:
   ```bash
   kubectl logs -n jupyterhub deployment/proxy
   ```

4. **Extension loaded but JupySQL not installed in the kernel environment** —
   the extension's handlers execute `from sql.connection import ConnectionManager`
   inside the kernel.  If JupySQL is not installed in the kernel's Python
   environment, this import fails.  Verify:
   ```bash
   kubectl exec -n jupyterhub pod/jupyter-<username> -- pip show jupysql
   ```

---

### Users cannot log in (SSO)

**Symptom**: After Google / Dex authentication, JupyterHub shows "403 Forbidden"
or "User not allowed".

**Fixes**:

1. **Domain/group restriction** — confirm the user's email domain or group is in
   `hosted_domain` / `allowed_groups`:
   ```yaml
   GoogleOAuthenticator:
     hosted_domain: ["yourcompany.com"]
   # or
   GenericOAuthenticator:
     allowed_groups: ["data-analysts"]
   ```

2. **Groups not in token** — for group-based access, the groups claim must be
   present in the OIDC token.  With Dex, ensure `"groups"` is in the requested
   scopes and that the connector (LDAP/GitHub) is configured to emit group
   membership.  Inspect the raw token:
   ```bash
   # In the Hub logs, enable debug logging to see decoded tokens
   kubectl logs -n jupyterhub deployment/hub | grep -i "user info"
   ```

3. **Redirect URI mismatch** — the redirect URI registered in Google Cloud
   Console or the Dex `staticClients[].redirectURIs` must exactly match
   `https://<your-hub-domain>/hub/oauth_callback`.  A trailing slash or
   `http` vs `https` mismatch will cause a login failure.

4. **Clock skew** — OIDC tokens are time-sensitive.  If the Dex pod's clock
   drifts by more than a few minutes, tokens will be rejected.  Ensure all
   nodes use NTP (most Kubernetes nodes do by default).

---

### Database connection fails (from the Add Connection dialog)

**Symptom**: Adding a connection via the sidebar shows "Connection failed" or
an error like `could not connect to server`.

**Fixes**:

1. **Network policy blocks the connection** — if you have applied the network
   policies from this guide, verify the target database IP/port is in the
   egress allow-list.  Temporarily disable the policy and retry to confirm:
   ```bash
   kubectl delete networkpolicy jupysql-singleuser -n jupyterhub
   ```

2. **Wrong credentials / URL format** — test the connection string directly
   in a notebook cell:
   ```python
   %load_ext sql
   %sql postgresql://user:pass@host:5432/dbname
   ```
   The error message in the cell output is more descriptive than what the
   sidebar shows.

3. **Missing database driver** — the driver package must be installed in the
   kernel's Python environment.  Common drivers and their pip packages:

   | Database | Connection URL prefix | Driver package |
   |----------|-----------------------|----------------|
   | PostgreSQL | `postgresql://` | `psycopg2-binary` or `psycopg` |
   | MySQL | `mysql+pymysql://` | `pymysql` |
   | MSSQL | `mssql+pyodbc://` | `pyodbc` + ODBC driver |
   | DuckDB | `duckdb://` | `duckdb-engine` |
   | Snowflake | `snowflake://` | `snowflake-sqlalchemy` |

   Install missing packages in the image or via a startup script.

---

### Context menu actions do not insert cells

**Symptom**: Right-clicking a table or column and selecting "Preview: first 10 rows"
does nothing, or shows a "Open a notebook first" warning.

**Fix**: The cell-insertion logic (`insertIntoNotebook` in `sidebar.tsx`) searches
for an open notebook in JupyterLab's main area.  If no notebook is open (only
the launcher tab, for example), it cannot insert a cell.  Open a notebook first,
then use the context menu.

---

### Pod OOM-killed after running large queries

**Symptom**: The kernel dies mid-query, JupyterLab shows "Kernel died" or the
pod is restarted.

**Fixes**:

1. **Increase memory limits** for the user profile:
   ```yaml
   singleuser:
     memory:
       limit: 8G
       guarantee: 1G
   ```

2. **Use JupySQL's `autolimit`** to cap result set sizes automatically:
   ```python
   %config SqlMagic.autolimit = 10000
   ```

3. **Use DuckDB instead of loading data into Python** — DuckDB runs queries
   inside the kernel but processes data in a streaming fashion, which is far
   more memory-efficient than loading a full result set into a Pandas DataFrame.

---

### Real-time collaboration: users see different connection lists

**Symptom**: User A and User B are both in the same server (RTC mode), but the
JupySQL sidebar shows different connections for each of them.

**Cause**: The JupySQL sidebar runs inside each user's *browser*, and it makes
REST API calls that target the kernel.  In RTC mode both browsers share the
same kernel, so the connections are actually identical.  However, the sidebar
React state is local to each browser session, meaning it may fall out of sync
if one user adds a connection while the other's sidebar is already open.

**Fix**: Click the **Refresh** (⟳) button in the sidebar.  This forces a fresh
`GET /jupysql/connections` call and syncs the displayed list with the kernel's
actual state.

---

### JupyterHub upgrade breaks the extension

**Symptom**: After upgrading the Helm chart, the sidebar no longer loads or the
`/jupysql/*` routes return 404.

**Fix**: The `jupyterhub-singleuser` package version in the image must be
compatible with the Hub version.  When upgrading the Helm chart, also rebuild
the JupySQL image with a matching `jupyterhub` pip package version:

```dockerfile
# In your Dockerfile, pin to the same major version as your Helm chart
RUN pip install --no-cache-dir 'jupyterhub>=4.0.0,<5'
```

Check the
[Zero to JupyterHub changelog](https://z2jh.jupyter.org/en/stable/changelog.html)
for breaking changes before upgrading.

---

### Dex tokens rejected ("token is expired" or "invalid issuer")

**Symptom**: After SSO login, JupyterHub shows an authentication error even
though Dex accepted the login.

**Fixes**:

1. **Token expiry** — Dex issues short-lived tokens (default 24 hours).  If
   the user's session is older than that, they need to re-authenticate.
   Increase the token lifetime in Dex's config if needed:
   ```yaml
   # dex-values.yaml
   config:
     expiry:
       idTokens: 24h
       refreshTokens:
         validIfNotUsedFor: 720h  # 30 days
   ```

2. **Issuer URL mismatch** — the `issuer` in Dex's config must exactly match
   the `oidc_issuer` / `authorize_url` host configured in JupyterHub.  A
   mismatch (e.g. `http://` vs `https://`, or a trailing slash) causes token
   validation to fail.

3. **TLS certificate not trusted** — if Dex uses a private CA, the JupyterHub
   Hub pod must trust that CA.  Mount the CA bundle and set `SSL_CERT_FILE`:
   ```yaml
   hub:
     extraVolumes:
       - name: dex-ca
         configMap:
           name: dex-ca-bundle
     extraVolumeMounts:
       - name: dex-ca
         mountPath: /etc/ssl/dex
     extraEnv:
       SSL_CERT_FILE: /etc/ssl/dex/ca.crt
   ```

---

### Getting more diagnostic information

```bash
# JupyterHub Hub logs (auth failures, spawn errors)
kubectl logs -n jupyterhub deployment/hub --tail=100 -f

# Proxy logs (routing issues, 502s)
kubectl logs -n jupyterhub deployment/proxy --tail=100 -f

# A specific user's server logs (kernel errors, extension errors)
kubectl logs -n jupyterhub pod/jupyter-<username> --tail=200 -f

# Describe a user's pod (OOM kills, image pull failures)
kubectl describe pod -n jupyterhub jupyter-<username>

# Check the JupySQL REST extension is registered in the running server
kubectl exec -n jupyterhub pod/jupyter-<username> -- \
  jupyter server extension list

# Check the lab extension is installed
kubectl exec -n jupyterhub pod/jupyter-<username> -- \
  jupyter labextension list

# Enable verbose Hub logging in config.yaml
hub:
  config:
    Application:
      log_level: DEBUG
```
