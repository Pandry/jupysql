"""
Config file database provider for ~/.jupysql/connections.ini files.
"""
import configparser
from pathlib import Path
from typing import List, Optional
from sqlalchemy.engine.url import URL
import ast

from .base import DatabaseProvider, DatabaseInfo


def _parse_config_section(section):
    """Parse a config section into a dictionary."""
    url_args = dict(section)
    if "query" in url_args:
        url_args["query"] = ast.literal_eval(url_args["query"])
    return url_args


class ConfigFileDatabaseProvider(DatabaseProvider):
    """
    Provider for databases defined in ~/.jupysql/connections.ini files.

    This wraps the existing ConnectionsFile functionality and provides
    backwards compatibility with the legacy DSN file format.
    """

    def __init__(self, config_path: str = "~/.jupysql/connections.ini"):
        super().__init__("config_file")
        self.config_path = Path(config_path).expanduser()
        self._databases: List[DatabaseInfo] = []
        self._last_modified = None

        # Try initial load
        try:
            self.refresh()
        except FileNotFoundError:
            # Config file doesn't exist yet, that's ok
            pass

    def list_databases(self) -> List[DatabaseInfo]:
        """List all databases from the config file."""
        # Auto-refresh if file has been modified
        self._check_and_refresh()
        return self._databases.copy()

    def get_database(self, identifier: str) -> Optional[DatabaseInfo]:
        """Get a database by identifier (section name)."""
        self._check_and_refresh()
        for db in self._databases:
            if db.identifier == identifier:
                return db
        return None

    def refresh(self) -> None:
        """Reload databases from the config file."""
        if not self.config_path.exists():
            self._databases = []
            self._last_modified = None
            return

        parser = configparser.ConfigParser()
        try:
            cfg_content = self.config_path.read_text()
            parser.read_string(cfg_content)
        except Exception as e:
            print(f"Error reading config file {self.config_path}: {e}")
            return

        databases = []
        for section_name in parser.sections():
            try:
                section = parser.items(section_name)
                url_args = _parse_config_section(section)
                url = URL.create(**url_args)
                connection_string = str(url.render_as_string(hide_password=False))

                # Create DatabaseInfo
                identifier = f"config_file:{section_name}"
                db_info = DatabaseInfo(
                    identifier=identifier,
                    name=section_name,
                    connection_string=connection_string,
                    provider=self.name,
                    metadata={
                        "source": "config_file",
                        "section": section_name,
                        "file": str(self.config_path),
                    },
                    host=url_args.get("host"),
                    port=url_args.get("port"),
                    database=url_args.get("database"),
                    username=url_args.get("username"),
                )
                databases.append(db_info)
            except Exception as e:
                print(f"Error parsing config section '{section_name}': {e}")
                continue

        self._databases = databases
        self._last_modified = self.config_path.stat().st_mtime

    def _check_and_refresh(self) -> None:
        """Check if config file has been modified and refresh if needed."""
        if not self.config_path.exists():
            if self._databases:
                # File was deleted
                self._databases = []
                self._last_modified = None
            return

        current_mtime = self.config_path.stat().st_mtime
        if self._last_modified is None or current_mtime > self._last_modified:
            self.refresh()
