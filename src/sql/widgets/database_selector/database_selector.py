from sql.connection import ConnectionManager
from IPython import get_ipython
from sql import display
import time
import json
import os
from sql.widgets import utils

# Widget base dir
BASE_DIR = os.path.dirname(__file__)


class DatabaseSelectorWidget:
    """
    A dropdown widget to switch between database connections.

    This widget provides a visual interface to select and switch between
    available database connections without exposing credentials.

    Examples
    --------
    >>> from sql.widgets import DatabaseSelectorWidget
    >>> selector = DatabaseSelectorWidget()
    >>> selector  # Display in Jupyter
    """

    def __init__(self):
        """
        Creates a database selector widget showing all available connections.

        The widget displays connections using obfuscated URLs (passwords hidden)
        and allows users to switch the active connection via a dropdown.
        """
        self.html = ""

        # Load CSS
        html_style = utils.load_css(f"{BASE_DIR}/css/databaseSelector.css")
        self.add_to_html(html_style)

        # Create selector container
        self.create_selector()

        # Register communication handler
        self.register_comm()

    def _repr_html_(self):
        return self.html

    def add_to_html(self, html):
        self.html += html

    def create_selector(self):
        """
        Creates the HTML structure for the database selector.
        """
        unique_id = str(int(time.time() * 1000))
        container_id = f"databaseSelector_{unique_id}"
        select_id = f"dbSelect_{unique_id}"
        button_id = f"dbButton_{unique_id}"
        status_id = f"dbStatus_{unique_id}"

        # Get all connections with obfuscated URLs (credentials hidden)
        connections = self._get_connections_info()

        # Create selector container
        selector_html = f"""
        <div class="database-selector">
            <div class="database-selector-title">Database Connection Selector</div>
            <div class="database-selector-container" id="{container_id}">
                <label class="database-selector-label" for="{select_id}">
                    Select Connection:
                </label>
                <select id="{select_id}" class="database-selector-select">
                    <option value="">-- Choose a connection --</option>
                </select>
                <button id="{button_id}" class="database-selector-button">
                    Switch
                </button>
            </div>
            <div id="{status_id}" class="database-selector-status"></div>
        </div>
        """
        self.add_to_html(selector_html)

        # Load JavaScript
        html_scripts = utils.load_js([
            utils.set_template_params(
                container_id=container_id,
                select_id=select_id,
                button_id=button_id,
                status_id=status_id,
                connections_json=json.dumps(connections),
                current_connection=self._get_current_connection_key()
            ),
            f"{BASE_DIR}/js/databaseSelector.js"
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

        This handles requests from the JavaScript frontend to switch
        the active database connection.
        """
        def comm_handler(comm, open_msg):
            """Handle received messages from the frontend."""

            @comm.on_msg
            def _recv(msg):
                data = msg["content"]["data"]
                action = data.get("action")
                connection_key = data.get("connection_key")

                try:
                    if action == "switch":
                        result = self._switch_connection(connection_key)
                        comm.send(result)
                    else:
                        comm.send({"success": False, "error": "Unknown action"})

                except Exception as e:
                    comm.send({"success": False, "error": str(e)})

        ipython = get_ipython()

        if hasattr(ipython, "kernel"):
            ipython.kernel.comm_manager.register_target(
                "comm_target_database_selector", comm_handler
            )

    def _switch_connection(self, connection_key):
        """
        Switch to a different database connection.

        Parameters
        ----------
        connection_key : str
            The key of the connection to switch to

        Returns
        -------
        dict
            Result dictionary with success status and message
        """
        try:
            # Find the connection
            target_conn = ConnectionManager.connections.get(connection_key)

            if not target_conn:
                return {
                    "success": False,
                    "error": f"Connection '{connection_key}' not found"
                }

            # Check if it's already the current connection
            if ConnectionManager.current == target_conn:
                return {
                    "success": False,
                    "error": "This connection is already active"
                }

            # Switch the connection
            ConnectionManager.current = target_conn

            # Get a display label
            label = target_conn.alias if target_conn.alias else target_conn.url

            display.message(f"Switched to connection: {label}")

            return {
                "success": True,
                "connection_key": connection_key,
                "connection_label": label
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
