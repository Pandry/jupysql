"""
Database provider system for JupySQL.

Providers discover and manage database connections from various sources:
- StaticDatabaseProvider: Manually configured databases
- ConfigFileDatabaseProvider: Databases from ~/.jupysql/connections.ini
- CNPGDatabaseProvider: Kubernetes CNPG clusters/poolers
"""

from .base import DatabaseProvider, DatabaseInfo
from .factory import DatabaseProviderFactory, get_factory

__all__ = [
    "DatabaseProvider",
    "DatabaseInfo",
    "DatabaseProviderFactory",
    "get_factory",
]
