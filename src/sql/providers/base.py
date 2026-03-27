"""
Database provider base class and data models.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime


@dataclass
class DatabaseInfo:
    """Information about an available database."""

    identifier: str  # Unique identifier for the database
    name: str  # Display name
    connection_string: str  # SQLAlchemy connection string
    provider: str  # Name of the provider that supplied this database
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata

    # CNPG-specific fields (optional)
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    # Metadata
    discovered_at: datetime = field(default_factory=datetime.now)
    labels: Dict[str, str] = field(default_factory=dict)

    def __hash__(self):
        return hash(self.identifier)

    def __eq__(self, other):
        if not isinstance(other, DatabaseInfo):
            return False
        return self.identifier == other.identifier


class DatabaseProvider(ABC):
    """
    Abstract base class for database providers.

    Providers discover and manage database connections from various sources
    (static configuration, config files, Kubernetes CNPG, etc.)
    """

    def __init__(self, name: str):
        self.name = name
        self._enabled = True

    @abstractmethod
    def list_databases(self) -> List[DatabaseInfo]:
        """
        List all databases available from this provider.

        Returns:
            List of DatabaseInfo objects
        """
        pass

    @abstractmethod
    def get_database(self, identifier: str) -> Optional[DatabaseInfo]:
        """
        Get a specific database by identifier.

        Args:
            identifier: Unique identifier for the database

        Returns:
            DatabaseInfo if found, None otherwise
        """
        pass

    @abstractmethod
    def refresh(self) -> None:
        """
        Refresh the provider's database list.

        This may involve re-reading configuration files, querying Kubernetes, etc.
        """
        pass

    def enable(self) -> None:
        """Enable this provider."""
        self._enabled = True

    def disable(self) -> None:
        """Disable this provider."""
        self._enabled = False

    def is_enabled(self) -> bool:
        """Check if this provider is enabled."""
        return self._enabled
