"""REST API handlers for JupySQL extension"""

import json
import traceback
from typing import Any, Dict, List

from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join
from tornado import web
from jupyter_server.services.kernels.kernelmanager import AsyncMappingKernelManager


class BaseJupySQLHandler(APIHandler):
    """Base handler with common functionality"""

    async def execute_in_kernel(self, code: str, kernel_id: str = None):
        """Execute code in a kernel and return the result"""
        km = self.settings['kernel_manager']

        # If no kernel_id provided, try to find any running kernel
        if not kernel_id:
            kernel_ids = list(km.list_kernel_ids())
            self.log.info(f"Found {len(kernel_ids)} running kernels")
            if not kernel_ids:
                self.log.warning("No running kernels found")
                return None
            kernel_id = kernel_ids[0]  # Use first available kernel
            self.log.info(f"Using kernel: {kernel_id}")

        # Get kernel client
        kernel = km.get_kernel(kernel_id)
        client = kernel.client()
        client.start_channels()

        result_data = None
        try:
            # Execute the code
            msg_id = client.execute(code, silent=True, store_history=False)
            self.log.info(f"Executed code in kernel, msg_id: {msg_id}")

            # Wait for result
            timeout_count = 0
            while timeout_count < 10:
                try:
                    msg = await client.get_iopub_msg(timeout=1)
                    msg_type = msg['msg_type']
                    self.log.debug(f"Got message type: {msg_type}")

                    if msg['parent_header'].get('msg_id') == msg_id:
                        if msg_type == 'stream':
                            # Handle print() output
                            result_data = msg['content']['text']
                            self.log.info(f"Got stream output: {result_data[:100]}")
                        elif msg_type == 'execute_result':
                            result_data = msg['content']['data']['text/plain']
                            self.log.info(f"Got execute_result: {result_data[:100]}")
                        elif msg_type == 'error':
                            self.log.error(f"Kernel error: {msg['content']}")
                            return None
                        elif msg_type == 'status' and msg['content']['execution_state'] == 'idle':
                            # Execution complete
                            break
                except Exception as e:
                    timeout_count += 1
                    self.log.debug(f"Timeout waiting for message: {e}")
        finally:
            client.stop_channels()

        self.log.info(f"Final result: {result_data}")
        return result_data

    def prepare(self):
        """Called before each request"""
        # Log the request
        self.log.debug(f"{self.request.method} {self.request.path}")

    def write_error(self, status_code: int, **kwargs):
        """Write error response"""
        self.set_header("Content-Type", "application/json")
        error_msg = "An error occurred"

        if "exc_info" in kwargs:
            exc_type, exc_value, exc_tb = kwargs["exc_info"]
            error_msg = str(exc_value)
            if self.settings.get("serve_traceback"):
                tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
                self.log.error(f"Error in {self.request.path}: {tb}")

        self.finish(json.dumps({"error": error_msg}))

    def write_json(self, data: Any):
        """Write JSON response"""
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(data))


class ConnectionsHandler(BaseJupySQLHandler):
    """
    Handler for /jupysql/connections endpoint.

    GET: List all connections (with obfuscated credentials)
    POST: Add a new connection
    """

    async def get(self):
        """Get all database connections from all running kernels"""
        try:
            # Get all running kernels
            km = self.settings['kernel_manager']
            kernel_ids = list(km.list_kernel_ids())

            self.log.info(f"Querying {len(kernel_ids)} kernels for connections")

            all_connections = []
            seen_keys = set()

            # Query each kernel for connections
            code = """
import json
try:
    from sql.connection import ConnectionManager
    raw_connections = ConnectionManager._get_connections()
    # Extract only serializable fields
    connections = []
    for conn in raw_connections:
        connections.append({
            'key': str(conn.get('key', '')),
            'url': str(conn.get('url', '')),
            'alias': str(conn.get('alias', '')),
            'current': bool(conn.get('current', False))
        })
    print(json.dumps(connections))
except Exception as e:
    print(json.dumps({'error': str(e)}))
    print("[]")
"""

            for kernel_id in kernel_ids:
                result = await self.execute_in_kernel(code, kernel_id)

                if result:
                    try:
                        result_str = result.strip().strip("'\"")
                        connections = json.loads(result_str)
                        self.log.info(f"Kernel {kernel_id[:8]} has {len(connections)} connections")

                        # Add connections, avoiding duplicates
                        for conn_dict in connections:
                            key = conn_dict["key"]
                            if key not in seen_keys:
                                seen_keys.add(key)
                                all_connections.append({
                                    "key": key,
                                    "url": conn_dict["url"],
                                    "alias": conn_dict["alias"],
                                    "is_current": conn_dict["current"],
                                })
                    except Exception as e:
                        self.log.error(f"Error parsing connections from kernel {kernel_id}: {e}")

            self.log.info(f"Total unique connections found: {len(all_connections)}")
            self.write_json({"connections": all_connections})

        except Exception as e:
            self.log.error(f"Error getting connections: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})

    def post(self):
        """Add a new database connection"""
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            connection_string = data.get("connection_string")
            alias = data.get("alias")

            if not connection_string:
                self.set_status(400)
                self.write_json({"error": "connection_string is required"})
                return

            # Add the connection
            ConnectionManager.set(
                descriptor=connection_string,
                displaycon=False,
                alias=alias,
            )

            self.write_json(
                {
                    "status": "success",
                    "message": f"Connection {alias or connection_string} added successfully",
                }
            )

        except Exception as e:
            self.log.error(f"Error adding connection: {e}")
            self.set_status(400)
            self.write_json({"error": str(e)})


class SchemasHandler(BaseJupySQLHandler):
    """
    Handler for /jupysql/schemas endpoint.

    GET: Get all schemas for a connection
    """

    async def get(self):
        """Get schemas for a connection from kernel"""
        try:
            connection_key = self.get_argument("connection_key", None)

            if not connection_key:
                self.set_status(400)
                self.write_json({"error": "connection_key parameter is required"})
                return

            # Execute in kernel to get schemas
            code = f"""
import json
try:
    from sql.connection import ConnectionManager
    from sql import inspect

    # Get the connection
    target_conn = ConnectionManager.connections.get('{connection_key}')
    if not target_conn:
        print(json.dumps({{"error": "Connection not found"}}))
    else:
        # Temporarily switch to this connection
        original_conn = ConnectionManager.current
        try:
            ConnectionManager.current = target_conn

            # Don't fetch schemas for DBAPI connections
            if hasattr(target_conn, 'is_dbapi_connection') and target_conn.is_dbapi_connection:
                schemas = [{{"name": "(default)", "is_default": True}}]
            else:
                schema_names = inspect.get_schema_names()
                schemas = [{{"name": schema, "is_default": False}} for schema in schema_names]

            print(json.dumps({{"schemas": schemas}}))
        finally:
            # Restore original connection
            ConnectionManager.current = original_conn
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""

            result = await self.execute_in_kernel(code)

            if result:
                result_str = result.strip().strip("'\"")
                data = json.loads(result_str)

                if "error" in data:
                    self.set_status(404 if "not found" in data["error"] else 500)
                    self.write_json({"error": data["error"]})
                else:
                    self.write_json(data)
            else:
                self.set_status(500)
                self.write_json({"error": "No response from kernel"})

        except Exception as e:
            self.log.error(f"Error getting schemas: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class TablesHandler(BaseJupySQLHandler):
    """
    Handler for /jupysql/tables endpoint.

    GET: Get all tables for a schema
    """

    async def get(self):
        """Get tables for a schema from kernel"""
        try:
            connection_key = self.get_argument("connection_key", None)
            schema = self.get_argument("schema", None)

            if not connection_key:
                self.set_status(400)
                self.write_json({"error": "connection_key parameter is required"})
                return

            schema_arg = "None" if not schema or schema == "(default)" else f"'{schema}'"

            # Execute in kernel
            code = f"""
import json
try:
    from sql.connection import ConnectionManager
    from sql import inspect

    target_conn = ConnectionManager.connections.get('{connection_key}')
    if not target_conn:
        print(json.dumps({{"error": "Connection not found"}}))
    else:
        original_conn = ConnectionManager.current
        try:
            ConnectionManager.current = target_conn
            tables_obj = inspect.get_table_names(schema={schema_arg})

            # Extract table names
            table_names = []
            for row in tables_obj._table:
                table_name = row.get_string(fields=["Name"], border=False, header=False).strip()
                table_names.append(table_name)

            tables = [{{"name": table}} for table in table_names]
            print(json.dumps({{"tables": tables}}))
        finally:
            ConnectionManager.current = original_conn
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""

            result = await self.execute_in_kernel(code)

            if result:
                result_str = result.strip().strip("'\"")
                data = json.loads(result_str)

                if "error" in data:
                    self.set_status(404 if "not found" in data["error"] else 500)
                    self.write_json({"error": data["error"]})
                else:
                    self.write_json(data)
            else:
                self.set_status(500)
                self.write_json({"error": "No response from kernel"})

        except Exception as e:
            self.log.error(f"Error getting tables: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class ColumnsHandler(BaseJupySQLHandler):
    """
    Handler for /jupysql/columns endpoint.

    GET: Get all columns for a table
    """

    async def get(self):
        """Get columns for a table from kernel"""
        try:
            connection_key = self.get_argument("connection_key", None)
            schema = self.get_argument("schema", None)
            table = self.get_argument("table", None)

            if not connection_key or not table:
                self.set_status(400)
                self.write_json({"error": "connection_key and table parameters are required"})
                return

            schema_arg = "None" if not schema or schema == "(default)" else f"'{schema}'"

            # Execute in kernel
            code = f"""
import json
try:
    from sql.connection import ConnectionManager
    from sql import inspect

    target_conn = ConnectionManager.connections.get('{connection_key}')
    if not target_conn:
        print(json.dumps({{"error": "Connection not found"}}))
    else:
        original_conn = ConnectionManager.current
        try:
            ConnectionManager.current = target_conn
            columns_obj = inspect.get_columns('{table}', schema={schema_arg})

            # Extract column information
            columns = []
            for row in columns_obj._table:
                col_name = row.get_string(
                    fields=[columns_obj._table.field_names[0]],
                    border=False,
                    header=False
                ).strip()

                col_type = ""
                if len(columns_obj._table.field_names) > 1:
                    col_type = row.get_string(
                        fields=[columns_obj._table.field_names[1]],
                        border=False,
                        header=False
                    ).strip()

                columns.append({{"name": col_name, "type": col_type}})

            print(json.dumps({{"columns": columns}}))
        finally:
            ConnectionManager.current = original_conn
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""

            result = await self.execute_in_kernel(code)

            if result:
                result_str = result.strip().strip("'\"")
                data = json.loads(result_str)

                if "error" in data:
                    self.set_status(404 if "not found" in data["error"] else 500)
                    self.write_json({"error": data["error"]})
                else:
                    self.write_json(data)
            else:
                self.set_status(500)
                self.write_json({"error": "No response from kernel"})

        except Exception as e:
            self.log.error(f"Error getting columns: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class PreviewHandler(BaseJupySQLHandler):
    """
    Handler for /jupysql/preview endpoint.

    GET: Get preview data for a table
    """

    async def get(self):
        """Get preview data for a table from kernel"""
        try:
            connection_key = self.get_argument("connection_key", None)
            schema = self.get_argument("schema", None)
            table = self.get_argument("table", None)
            limit = int(self.get_argument("limit", "100"))
            offset = int(self.get_argument("offset", "0"))

            if not connection_key or not table:
                self.set_status(400)
                self.write_json(
                    {"error": "connection_key and table parameters are required"}
                )
                return

            # Execute in kernel
            code = f"""
import json
try:
    from sql.connection import ConnectionManager
    from sql import inspect

    target_conn = ConnectionManager.connections.get('{connection_key}')
    if not target_conn:
        print(json.dumps({{"error": "Connection not found"}}))
    else:
        original_conn = ConnectionManager.current
        try:
            ConnectionManager.current = target_conn

            # Fetch paginated data
            data, column_names = inspect.fetch_sql_with_pagination(
                table='{table}',
                offset={offset},
                n_rows={limit},
                sort_column=None,
                sort_order="DESC",
            )

            print(json.dumps({{
                "data": data,
                "columns": column_names,
                "offset": {offset},
                "limit": {limit}
            }}))
        finally:
            ConnectionManager.current = original_conn
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""

            result = await self.execute_in_kernel(code)

            if result:
                result_str = result.strip().strip("'\"")
                data = json.loads(result_str)

                if "error" in data:
                    self.set_status(404 if "not found" in data["error"] else 500)
                    self.write_json({"error": data["error"]})
                else:
                    self.write_json(data)
            else:
                self.set_status(500)
                self.write_json({"error": "No response from kernel"})

        except Exception as e:
            self.log.error(f"Error getting preview data: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class SwitchConnectionHandler(BaseJupySQLHandler):
    """
    Handler for /jupysql/switch endpoint.

    POST: Switch the active database connection
    """

    async def post(self):
        """Switch to a different connection in kernel"""
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            connection_key = data.get("connection_key")

            if not connection_key:
                self.set_status(400)
                self.write_json({"error": "connection_key is required"})
                return

            # Execute in kernel to switch connection
            code = f"""
import json
try:
    from sql.connection import ConnectionManager

    # Get the target connection
    target_conn = ConnectionManager.connections.get('{connection_key}')
    if not target_conn:
        print(json.dumps({{"error": "Connection not found"}}))
    else:
        # Check if already current
        if ConnectionManager.current == target_conn:
            label = target_conn.alias if target_conn.alias else str(target_conn.url)
            print(json.dumps({{
                "status": "success",
                "message": "This connection is already active",
                "connection_label": label
            }}))
        else:
            # Switch the connection
            ConnectionManager.current = target_conn
            label = target_conn.alias if target_conn.alias else str(target_conn.url)
            print(json.dumps({{
                "status": "success",
                "message": f"Switched to connection: {{label}}",
                "connection_label": label
            }}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""

            result = await self.execute_in_kernel(code)

            if result:
                result_str = result.strip().strip("'\"")
                data = json.loads(result_str)

                if "error" in data:
                    self.set_status(404 if "not found" in data["error"] else 500)
                    self.write_json({"error": data["error"]})
                else:
                    self.write_json(data)
            else:
                self.set_status(500)
                self.write_json({"error": "No response from kernel"})

        except Exception as e:
            self.log.error(f"Error switching connection: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


def setup_handlers(web_app, log):
    """
    Set up the REST API handlers.

    Parameters
    ----------
    web_app : tornado.web.Application
        The Jupyter server web application
    log : logging.Logger
        Logger instance
    """
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]

    # Define all handlers — url_path_join handles the base_url prefix correctly
    # and avoids double-slashes when base_url is "/"
    handlers = [
        (url_path_join(base_url, "jupysql", "connections"), ConnectionsHandler),
        (url_path_join(base_url, "jupysql", "schemas"), SchemasHandler),
        (url_path_join(base_url, "jupysql", "tables"), TablesHandler),
        (url_path_join(base_url, "jupysql", "columns"), ColumnsHandler),
        (url_path_join(base_url, "jupysql", "preview"), PreviewHandler),
        (url_path_join(base_url, "jupysql", "switch"), SwitchConnectionHandler),
    ]

    # Add handlers to the web app
    web_app.add_handlers(host_pattern, handlers)

    log.info(f"JupySQL REST API handlers registered at {base_url}jupysql/*")
