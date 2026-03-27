"""
Static database provider for manually configured databases.
"""
import threading
from typing import List, Optional, Dict
from .base import DatabaseProvider, DatabaseInfo


class StaticDatabaseProvider(DatabaseProvider):
    """
    Provider for manually configured databases.

    This provider stores databases that are added via the API or programmatically.
    Databases persist only in memory and are lost when the kernel restarts.
    """

    def __init__(self):
        super().__init__("static")
        self._databases: Dict[str, DatabaseInfo] = {}
        self._lock = threading.Lock()

    def list_databases(self) -> List[DatabaseInfo]:
        """List all manually configured databases."""
        with self._lock:
            return list(self._databases.values())

    def get_database(self, identifier: str) -> Optional[DatabaseInfo]:
        """Get a database by identifier."""
        with self._lock:
            return self._databases.get(identifier)

    def refresh(self) -> None:
        """Refresh is a no-op for static provider."""
        pass

    def add_database(self, database: DatabaseInfo) -> None:
        """
        Add a database to the static provider.

        Args:
            database: DatabaseInfo to add
        """
        with self._lock:
            database.provider = self.name
            self._databases[database.identifier] = database

    def remove_database(self, identifier: str) -> bool:
        """
        Remove a database from the static provider.

        Args:
            identifier: Unique identifier for the database

        Returns:
            True if database was removed, False if not found
        """
        with self._lock:
            if identifier in self._databases:
                del self._databases[identifier]
                return True
            return False

    def clear(self) -> None:
        """Remove all databases from the static provider."""
        with self._lock:
            self._databases.clear()
