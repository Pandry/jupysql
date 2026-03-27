# Database Provider/Factory Implementation - Summary

This document summarizes the implementation of the database provider/factory pattern for JupySQL, enabling dynamic database discovery from CloudNativePG clusters in Kubernetes.

## Overview

The provider system allows JupySQL to discover databases from multiple sources:
- **Static Provider**: Manually added databases via API
- **Config File Provider**: Databases from `~/.jupysql/connections.ini`
- **CNPG Provider**: Kubernetes CloudNativePG clusters and poolers (with automatic credential resolution)

## Changes Made

### 1. Core Provider System

#### New Files Created:

- **`src/sql/providers/base.py`**
  - `DatabaseInfo` dataclass: Stores database metadata
  - `DatabaseProvider` abstract base class: Interface for all providers

- **`src/sql/providers/factory.py`**
  - `DatabaseProviderFactory`: Singleton factory managing multiple providers
  - Provider registration and aggregation
  - Thread-safe operations

- **`src/sql/providers/__init__.py`**
  - Package exports

- **`src/sql/providers/static.py`**
  - `StaticDatabaseProvider`: In-memory storage for manually added databases
  - Thread-safe add/remove operations

- **`src/sql/providers/config_file.py`**
  - `ConfigFileDatabaseProvider`: Wraps existing ConnectionsFile
  - Auto-refresh on file modification
  - Backwards compatible with `~/.jupysql/connections.ini`

- **`src/sql/providers/cnpg.py`**
  - `CNPGDatabaseProvider`: Kubernetes CNPG integration
  - Discovers clusters and poolers via K8s API
  - Automatic credential resolution from secrets
  - Label-based filtering
  - Auto-refresh with configurable interval
  - Debouncing for manual refreshes

### 2. ConnectionManager Integration

#### Modified: `src/sql/connection/connection.py`

Added three new methods:

```python
@classmethod
def list_available_databases(cls, provider_names=None):
    """List all databases from registered providers"""

@classmethod
def refresh_providers(cls, provider_name=None):
    """Refresh database providers"""

@classmethod
def connect_from_provider(cls, identifier, config=None, alias=None):
    """Connect to a database from a provider by identifier"""
```

### 3. Magic Integration

#### Modified: `src/sql/magic.py`

- Added `_initialize_providers()` method
- Registers all providers during magic initialization
- Called automatically when `%sql` magic is loaded

### 4. REST API Endpoints

#### Modified: `src/sql/labextension/handlers.py`

Added four new handler classes:

1. **`ProvidersHandler`**
   - `GET /jupysql/providers`
   - Lists all registered providers and their status

2. **`AvailableDatabasesHandler`**
   - `GET /jupysql/available-databases?providers=cnpg,config_file`
   - Lists all databases from specified providers (or all if not specified)

3. **`RefreshProvidersHandler`**
   - `POST /jupysql/providers/refresh`
   - Refreshes providers to discover new databases
   - Body: `{"provider_name": "cnpg"}` (optional)

4. **`ConnectFromProviderHandler`**
   - `POST /jupysql/providers/connect`
   - Connects to a database from a provider
   - Body: `{"identifier": "cnpg:cluster:ns:name", "alias": "prod"}`

### 5. Configuration

#### Modified: `Dockerfile`

Added environment variables:
```dockerfile
ENV JUPYSQL_CNPG_ENABLED=false
ENV JUPYSQL_CNPG_LABEL_SELECTOR=jupysql.enabled=true
ENV JUPYSQL_CNPG_AUTO_REFRESH_INTERVAL=100
ENV JUPYSQL_CNPG_DEBOUNCE_INTERVAL=5
```

Added `kubernetes` package to dependencies.

#### Modified: `setup.py`

Added optional dependency group:
```python
CNPG = ["kubernetes>=28.0.0"]

extras_require={
    "cnpg": CNPG,
    "all": DEV + INTEGRATION + CNPG,
}
```

### 6. Documentation

#### New Files:

- **`src/sql/providers/README.md`**
  - Comprehensive guide to the provider system
  - CNPG provider configuration and usage
  - API documentation
  - Troubleshooting guide

- **`examples/kubernetes-cnpg-setup.yaml`**
  - Complete Kubernetes manifest example
  - ServiceAccount, RBAC, CNPG resources
  - JupySQL deployment with CNPG provider enabled

- **`examples/using_providers.py`**
  - Python usage examples
  - Demonstrates all provider features

## Architecture

```
┌─────────────────────────────────────────────────┐
│         DatabaseProviderFactory                  │
│  (Singleton managing all providers)              │
└────────────┬────────────────────────────────────┘
             │
             ├─► StaticDatabaseProvider
             │   └─ In-memory database storage
             │
             ├─► ConfigFileDatabaseProvider
             │   └─ ~/.jupysql/connections.ini
             │
             └─► CNPGDatabaseProvider
                 ├─ Kubernetes API client
                 ├─ Label-based filtering
                 ├─ Credential resolution
                 ├─ Auto-refresh thread
                 └─ Debouncing
```

## CNPG Provider Features

### 1. Automatic Discovery
- Queries Kubernetes API for CNPG Cluster and Pooler resources
- Filters by label selector (configurable)
- Supports multiple namespaces

### 2. Credential Management
- Fetches passwords from Kubernetes secrets
- Secret naming: `{cluster-name}-{username}`
- Defaults to `app` user if not specified in labels
- Credentials refreshed on each provider refresh

### 3. Connection String Generation
- Host: `{resource-name}-rw.{namespace}.svc.cluster.local`
- Port: `5432`
- Database: From cluster spec or defaults to `app`
- Format: `postgresql://{user}:{pass}@{host}:{port}/{db}`

### 4. Label Conventions
- `jupysql.enabled=true` - Include in discovery
- `jupysql.username=myuser` - Specify username
- `jupysql.pooler-type=rw` - Pooler type (rw/ro)

### 5. Auto-Refresh
- Background thread refreshes database list periodically
- Configurable interval (default: 100 seconds)
- Debouncing prevents API spam on manual refresh

## Installation

**Note**: This is a fork of JupySQL with enhanced CNPG provider support.

### From Source

```bash
# Clone the repository
git clone <repository-url>
cd jupysql

# Basic installation
pip install -e .

# With CNPG support
pip install -e ".[cnpg]"

# Full installation (all optional dependencies)
pip install -e ".[all]"
```

### Using Docker

```bash
# Build the Docker image
docker build -t jupysql-cnpg:latest .

# Run with Docker
docker run -p 8888:8888 jupysql-cnpg:latest

# Or deploy to Kubernetes (see QUICKSTART_CNPG.md)
```

## Usage Examples

### Python API

```python
from sql.connection import ConnectionManager
from sql.providers import get_factory

# List all available databases
databases = ConnectionManager.list_available_databases()
for db in databases:
    print(f"{db.name} ({db.provider})")

# Refresh providers
ConnectionManager.refresh_providers("cnpg")

# Connect to a database
conn = ConnectionManager.connect_from_provider(
    identifier="cnpg:cluster:default:my-cluster",
    alias="production"
)
```

### Magic Commands

```python
# Load the SQL magic (providers auto-initialized)
%load_ext sql

# Future enhancement - list available databases
# %sql --list-available

# Future enhancement - connect from provider
# %sql --from-provider cnpg:cluster:default:my-cluster --alias prod
```

### REST API

```bash
# List providers
curl http://localhost:8888/jupysql/providers

# List available databases
curl http://localhost:8888/jupysql/available-databases

# Refresh CNPG provider
curl -X POST http://localhost:8888/jupysql/providers/refresh \
  -H "Content-Type: application/json" \
  -d '{"provider_name": "cnpg"}'

# Connect to a database
curl -X POST http://localhost:8888/jupysql/providers/connect \
  -H "Content-Type: application/json" \
  -d '{"identifier": "cnpg:cluster:default:my-cluster", "alias": "prod"}'
```

## Kubernetes Deployment

### Prerequisites

1. CloudNativePG operator installed
2. CNPG clusters/poolers labeled with `jupysql.enabled=true`
3. ServiceAccount with RBAC permissions

### Quick Start

```bash
# Apply the example manifest
kubectl apply -f examples/kubernetes-cnpg-setup.yaml

# Check JupySQL logs
kubectl logs -l app=jupysql -f

# Port-forward to access JupyterLab
kubectl port-forward svc/jupysql 8888:8888
```

### Configuration

Set environment variables in the deployment:

```yaml
env:
  - name: JUPYSQL_CNPG_ENABLED
    value: "true"
  - name: JUPYSQL_CNPG_LABEL_SELECTOR
    value: "jupysql.enabled=true,environment=production"
  - name: JUPYSQL_CNPG_AUTO_REFRESH_INTERVAL
    value: "60"
```

## Testing

### Manual Testing

1. Start JupySQL:
   ```bash
   jupyter lab
   ```

2. In a notebook:
   ```python
   %load_ext sql

   from sql.providers import get_factory

   # List providers
   factory = get_factory()
   print(factory.list_providers())

   # List databases
   databases = factory.list_databases()
   for db in databases:
       print(f"{db.name}: {db.connection_string}")
   ```

### Integration Testing

```bash
# Run example script
python examples/using_providers.py
```

## Security Considerations

1. **Minimal RBAC**: Grant only `get` on specific secrets
2. **Namespace Scoped**: Use Role, not ClusterRole
3. **Label Filtering**: Use specific selectors
4. **No Password Persistence**: Passwords in memory only
5. **Debouncing**: Prevents K8s API spam

## Troubleshooting

### CNPG Provider Not Discovering Databases

1. Check if enabled:
   ```python
   from sql.providers import get_factory
   factory = get_factory()
   cnpg = factory.get_provider("cnpg")
   print(f"Enabled: {cnpg.is_enabled()}")
   ```

2. Check Kubernetes permissions:
   ```bash
   kubectl auth can-i get clusters.postgresql.cnpg.io
   kubectl auth can-i get secrets
   ```

3. Check labels:
   ```bash
   kubectl get clusters -l jupysql.enabled=true
   kubectl get poolers -l jupysql.enabled=true
   ```

### Import Errors

If you see `ModuleNotFoundError: No module named 'kubernetes'`:

```bash
pip install kubernetes
# or
pip install -e ".[cnpg]"
```

## Future Enhancements

1. **Magic Command Support**: `%sql --from-provider <identifier>`
2. **UI Integration**: Database browser showing provider databases
3. **Additional Providers**:
   - AWS RDS discovery
   - Azure Database discovery
   - Google Cloud SQL discovery
4. **Provider Configuration UI**: Web UI for provider settings
5. **Connection Pooling**: Shared connections across notebooks

## Backwards Compatibility

All changes are fully backwards compatible:
- Existing connection methods still work
- Config file loading unchanged
- No breaking changes to public APIs
- New features are opt-in via environment variables

## Files Changed Summary

### New Files (11):
- `src/sql/providers/__init__.py`
- `src/sql/providers/base.py`
- `src/sql/providers/factory.py`
- `src/sql/providers/static.py`
- `src/sql/providers/config_file.py`
- `src/sql/providers/cnpg.py`
- `src/sql/providers/README.md`
- `examples/kubernetes-cnpg-setup.yaml`
- `examples/using_providers.py`
- `PROVIDERS_IMPLEMENTATION.md` (this file)

### Modified Files (4):
- `src/sql/connection/connection.py` - Added provider integration methods
- `src/sql/magic.py` - Added provider initialization
- `src/sql/labextension/handlers.py` - Added provider API endpoints
- `Dockerfile` - Added kubernetes package and env vars
- `setup.py` - Added CNPG optional dependencies

## Conclusion

The database provider/factory pattern is now fully implemented and ready for use. It provides a flexible, extensible system for discovering databases from various sources, with special focus on Kubernetes CNPG integration for cloud-native deployments.
