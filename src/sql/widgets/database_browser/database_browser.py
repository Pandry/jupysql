from sql.connection import ConnectionManager
from IPython import get_ipython
import time
import json
import os
from sql.widgets import utils
from sql import inspect, exceptions

# Widget base dir
BASE_DIR = os.path.dirname(__file__)


class DatabaseBrowserWidget:
    """
    A tree-view widget to browse database connections, schemas, tables, and columns.

    This widget provides a visual interface to explore database structure without
    exposing credentials or connection details to users.

    Examples
    --------
    >>> from sql.widgets import DatabaseBrowserWidget
    >>> browser = DatabaseBrowserWidget()
    >>> browser  # Display in Jupyter
    """

    def __init__(self):
        """
        Creates a database browser widget showing all connections and their structure.

        The widget displays connections using obfuscated URLs (passwords hidden)
        and allows users to expand connections to see schemas, tables, and columns.
        """
        self.html = ""

        # Load CSS
        html_style = utils.load_css(f"{BASE_DIR}/css/databaseBrowser.css")
        self.add_to_html(html_style)

        # Create browser container
        self.create_browser()

        # Register communication handler
        self.register_comm()

    def _repr_html_(self):
        return self.html

    def add_to_html(self, html):
        self.html += html

    def create_browser(self):
        """
        Creates the HTML structure for the database browser.
        """
        unique_id = str(int(time.time() * 1000))
        container_id = f"databaseBrowser_{unique_id}"

        # Get all connections with obfuscated URLs (credentials hidden)
        connections = self._get_connections_info()

        # Create browser container
        browser_html = f"""
        <div class="database-browser">
            <div class="database-browser-title">Database Browser</div>
            <div id="{container_id}"></div>
        </div>
        """
        self.add_to_html(browser_html)

        # Load JavaScript
        html_scripts = utils.load_js([
            utils.set_template_params(
                container_id=container_id,
                connections_json=json.dumps(connections),
                current_connection=self._get_current_connection_key()
            ),
            f"{BASE_DIR}/js/databaseBrowser.js"
        ])
        self.add_to_html(html_scripts)

    def _get_connections_info(self):
        """
        Get information about all connections with credentials hidden.

        Returns
        -------
        list
            List of dictionaries containing connection info with obfuscated URLs
        """
        connections = []

        for conn_dict in ConnectionManager._get_connections():
            # Use alias if available, otherwise use obfuscated URL
            label = conn_dict['alias'] if conn_dict['alias'] else conn_dict['url']

            connections.append({
                'key': conn_dict['key'],
                'label': label,
                'is_current': conn_dict['current']
            })

        return connections

    def _get_current_connection_key(self):
        """Get the key of the current connection."""
        if ConnectionManager.current:
            for conn_dict in ConnectionManager._get_connections():
                if conn_dict['current']:
                    return conn_dict['key']
        return None

    def register_comm(self):
        """
        Register communication handler between frontend and kernel.

        This handles requests from the JavaScript frontend to load
        schemas, tables, and columns dynamically.
        """
        def comm_handler(comm, open_msg):
            """Handle received messages from the frontend."""

            @comm.on_msg
            def _recv(msg):
                data = msg["content"]["data"]
                action = data.get("action")
                item_type = data.get("type")
                connection_key = data.get("connection_key")
                schema = data.get("schema")
                table = data.get("table")

                try:
                    if action == "load":
                        if item_type == "connection":
                            # Load schemas for this connection
                            items = self._load_schemas(connection_key)
                        elif item_type == "schema":
                            # Load tables for this schema
                            items = self._load_tables(connection_key, schema)
                        elif item_type == "table":
                            # Load columns for this table
                            items = self._load_columns(connection_key, schema, table)
                        else:
                            items = []

                        comm.send({"items": items})

                except Exception as e:
                    comm.send({"error": str(e)})

        ipython = get_ipython()

        if hasattr(ipython, "kernel"):
            ipython.kernel.comm_manager.register_target(
                "comm_target_database_browser", comm_handler
            )

    def _switch_connection(self, connection_key):
        """Temporarily switch to a connection to inspect it."""
        original_connection = ConnectionManager.current
        try:
            target_conn = ConnectionManager.connections.get(connection_key)
            if target_conn:
                ConnectionManager.current = target_conn
            return target_conn
        except Exception:
            ConnectionManager.current = original_connection
            raise

    def _load_schemas(self, connection_key):
        """
        Load schemas for a given connection.

        Parameters
        ----------
        connection_key : str
            The connection key

        Returns
        -------
        list
            List of schema information dictionaries
        """
        original_connection = ConnectionManager.current

        try:
            # Switch to the target connection
            target_conn = self._switch_connection(connection_key)

            if not target_conn:
                return []

            # Don't fetch schemas for DBAPI connections
            if target_conn.is_dbapi_connection:
                # For DBAPI connections, directly load tables
                return [{
                    'label': '(default schema)',
                    'icon': 'db-schema-icon',
                    'type': 'schema',
                    'schema': None,
                    'has_children': True
                }]

            schema_names = inspect.get_schema_names()

            items = []
            for schema in schema_names:
                items.append({
                    'label': schema,
                    'icon': 'db-schema-icon',
                    'type': 'schema',
                    'schema': schema,
                    'has_children': True
                })

            return items

        except Exception as e:
            return [{
                'label': f'Error: {str(e)}',
                'icon': 'db-error',
                'type': 'error',
                'has_children': False
            }]
        finally:
            # Restore original connection
            ConnectionManager.current = original_connection

    def _load_tables(self, connection_key, schema):
        """
        Load tables for a given schema.

        Parameters
        ----------
        connection_key : str
            The connection key
        schema : str
            The schema name

        Returns
        -------
        list
            List of table information dictionaries
        """
        original_connection = ConnectionManager.current

        try:
            # Switch to the target connection
            target_conn = self._switch_connection(connection_key)

            if not target_conn:
                return []

            # Get table names
            tables_obj = inspect.get_table_names(schema=schema)

            # Extract table names from the Tables object
            table_names = []
            for row in tables_obj._table:
                table_name = row.get_string(
                    fields=["Name"], border=False, header=False
                ).strip()
                table_names.append(table_name)

            items = []
            for table in table_names:
                items.append({
                    'label': table,
                    'icon': 'db-table-icon',
                    'type': 'table',
                    'table': table,
                    'has_children': True
                })

            return items

        except Exception as e:
            return [{
                'label': f'Error: {str(e)}',
                'icon': 'db-error',
                'type': 'error',
                'has_children': False
            }]
        finally:
            # Restore original connection
            ConnectionManager.current = original_connection

    def _load_columns(self, connection_key, schema, table):
        """
        Load columns for a given table.

        Parameters
        ----------
        connection_key : str
            The connection key
        schema : str
            The schema name
        table : str
            The table name

        Returns
        -------
        list
            List of column information dictionaries
        """
        original_connection = ConnectionManager.current

        try:
            # Switch to the target connection
            target_conn = self._switch_connection(connection_key)

            if not target_conn:
                return []

            # Get columns
            columns_obj = inspect.get_columns(table, schema)

            items = []
            for row in columns_obj._table:
                # Get column name (first field)
                col_name = row.get_string(
                    fields=[columns_obj._table.field_names[0]],
                    border=False,
                    header=False
                ).strip()

                # Get column type if available
                col_type = ""
                if len(columns_obj._table.field_names) > 1:
                    col_type = row.get_string(
                        fields=[columns_obj._table.field_names[1]],
                        border=False,
                        header=False
                    ).strip()

                label = f"{col_name}"
                badge = col_type if col_type else None

                items.append({
                    'label': label,
                    'icon': 'db-column-icon',
                    'badge': badge,
                    'type': 'column',
                    'has_children': False
                })

            return items

        except Exception as e:
            return [{
                'label': f'Error: {str(e)}',
                'icon': 'db-error',
                'type': 'error',
                'has_children': False
            }]
        finally:
            # Restore original connection
            ConnectionManager.current = original_connection
