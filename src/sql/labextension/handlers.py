"""REST API handlers for JupySQL extension"""

import asyncio
import json
import traceback
from typing import Any

from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join


class BaseJupySQLHandler(APIHandler):
    """Base handler with common functionality"""

    async def execute_in_kernel(
        self, code: str, kernel_id: str = None, total_timeout: float = 30.0
    ):
        """Execute code in a kernel and return all stdout as a string.

        Uses a wall-clock deadline so the loop cannot run indefinitely even
        when the iopub channel carries unrelated messages from other
        executions.  Stream chunks are accumulated (not overwritten) so
        multi-message output is captured correctly.
        """
        km = self.settings['kernel_manager']

        if not kernel_id:
            kernel_ids = list(km.list_kernel_ids())
            self.log.info(f"Found {len(kernel_ids)} running kernels")
            if not kernel_ids:
                self.log.warning("No running kernels found")
                return None
            kernel_id = kernel_ids[0]
            self.log.info(f"Using kernel: {kernel_id}")

        client = None  # guard: must be set before the finally block can call stop_channels
        try:
            kernel = km.get_kernel(kernel_id)
            client = kernel.client()
            client.start_channels()

            result_data = None
            msg_id = client.execute(code, silent=True, store_history=False)
            self.log.info(f"Executed code in kernel, msg_id: {msg_id}")

            loop = asyncio.get_event_loop()
            deadline = loop.time() + total_timeout

            while loop.time() < deadline:
                remaining = deadline - loop.time()
                try:
                    msg = await client.get_iopub_msg(timeout=min(1.0, remaining))
                    msg_type = msg['msg_type']

                    if msg['parent_header'].get('msg_id') != msg_id:
                        continue  # message belongs to a different execution

                    if msg_type == 'stream':
                        chunk = msg['content']['text']
                        result_data = (result_data or '') + chunk
                        self.log.info(
                            f"Got stream chunk ({len(chunk)} chars), "
                            f"total: {len(result_data)}"
                        )
                    elif msg_type == 'execute_result':
                        result_data = msg['content']['data']['text/plain']
                    elif msg_type == 'error':
                        self.log.error(f"Kernel error: {msg['content']}")
                        return None
                    elif (
                        msg_type == 'status'
                        and msg['content']['execution_state'] == 'idle'
                    ):
                        break
                except Exception:
                    pass  # get_iopub_msg timed out — keep looping until deadline

            self.log.info(f"Final result: {result_data}")
            return result_data

        except Exception as e:
            self.log.error(f"execute_in_kernel error (kernel={kernel_id[:8] if kernel_id else '?'}): {e}")
            return None
        finally:
            if client is not None:
                client.stop_channels()

    def _parse_kernel_result(self, result: str):
        """Extract the last valid JSON value from kernel stdout.

        jupysql may print informational lines like
            The sql extension is already loaded. To reload it, use:
              %reload_ext sql
        *before* our own print() call.  We scan lines in reverse to find the
        last well-formed JSON object or array and return its parsed value.
        Returns None if nothing parses.
        """
        if not result:
            return None
        stripped = result.strip()
        # Fast path: the whole buffer is valid JSON
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
        # Slow path: last line that looks like a JSON value
        for line in reversed(stripped.split('\n')):
            candidate = line.strip()
            if (candidate.startswith('{') and candidate.endswith('}')) or \
               (candidate.startswith('[') and candidate.endswith(']')):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
        return None

    def check_xsrf_cookie(self):
        """Skip XSRF — the JupyterLab frontend handles auth; tests also need
        unrestricted access when the server token is disabled."""
        pass

    def prepare(self):
        self.log.debug(f"{self.request.method} {self.request.path}")

    def write_error(self, status_code: int, **kwargs):
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
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(data))


# ---------------------------------------------------------------------------
# Kernel helper: load the sql extension silently (no "already loaded" noise)
# ---------------------------------------------------------------------------
_LOAD_EXT_SILENT = """\
import sys as _sys
from io import StringIO as _StringIO
_buf = _StringIO()
_old_out, _sys.stdout = _sys.stdout, _buf
try:
    get_ipython().run_line_magic('load_ext', 'sql')
except Exception:
    pass
finally:
    _sys.stdout = _old_out
del _buf, _old_out, _sys, _StringIO
"""


class ConnectionsHandler(BaseJupySQLHandler):
    """GET /jupysql/connections — list active connections
    POST /jupysql/connections — add a new connection
    """

    async def get(self):
        try:
            km = self.settings['kernel_manager']
            kernel_ids = list(km.list_kernel_ids())
            self.log.info(f"Querying {len(kernel_ids)} kernels for connections")

            all_connections = []
            seen_keys: set = set()

            code = """\
import json
try:
    from sql.connection import ConnectionManager
    raw_connections = ConnectionManager._get_connections()
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
"""
            for kernel_id in kernel_ids:
                result = await self.execute_in_kernel(code, kernel_id)
                if not result:
                    continue
                try:
                    parsed = self._parse_kernel_result(result)
                    if not isinstance(parsed, list):
                        continue
                    self.log.info(
                        f"Kernel {kernel_id[:8]} has {len(parsed)} connections"
                    )
                    for conn_dict in parsed:
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
                    self.log.error(
                        f"Error parsing connections from kernel {kernel_id}: {e}"
                    )

            self.log.info(f"Total unique connections found: {len(all_connections)}")
            self.write_json({"connections": all_connections})
        except Exception as e:
            self.log.error(f"Error getting connections: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})

    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            connection_string = data.get("connection_string")
            alias = data.get("alias") or ""

            if not connection_string:
                self.set_status(400)
                self.write_json({"error": "connection_string is required"})
                return

            conn_repr = repr(connection_string)
            alias_repr = repr(alias)

            code = f"""\
import json
{_LOAD_EXT_SILENT}
try:
    _conn_str = {conn_repr}
    _alias = {alias_repr}
    ip = get_ipython()
    magic_args = _conn_str
    if _alias:
        magic_args = magic_args + ' --alias ' + _alias
    ip.run_line_magic('sql', magic_args)
    print(json.dumps({{"status": "success"}}))
except Exception as _e:
    print(json.dumps({{"error": str(_e)}}))
"""
            result = await self.execute_in_kernel(code)

            if result:
                resp = self._parse_kernel_result(result)
                if resp is None:
                    self.set_status(500)
                    self.write_json({
                        "error": f"Unexpected kernel output: {result[:200]}"
                    })
                    return
                if "error" in resp:
                    self.set_status(400)
                self.write_json(resp)
            else:
                self.set_status(503)
                self.write_json({"error": "No running kernel to execute connection in"})
        except Exception as e:
            self.log.error(f"Error adding connection: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class InitHandler(BaseJupySQLHandler):
    """POST /jupysql/init — load the %sql magic in all running kernels."""

    async def post(self):
        code = f"""\
import json
{_LOAD_EXT_SILENT}
print(json.dumps({{"status": "success"}}))
"""
        try:
            result = await self.execute_in_kernel(code)
            if result:
                parsed = self._parse_kernel_result(result)
                self.write_json(parsed or {"status": "success"})
            else:
                self.write_json({"status": "no_kernel"})
        except Exception as e:
            self.log.error(f"Error initialising sql extension: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class SchemasHandler(BaseJupySQLHandler):
    """GET /jupysql/schemas — list schemas for a connection."""

    async def get(self):
        try:
            connection_key = self.get_argument("connection_key", None)
            if not connection_key:
                self.set_status(400)
                self.write_json({"error": "connection_key parameter is required"})
                return

            ck_repr = repr(connection_key)
            code = f"""\
import json
try:
    from sql.connection import ConnectionManager
    from sql import inspect
    target_conn = ConnectionManager.connections.get({ck_repr})
    if not target_conn:
        print(json.dumps({{"error": "Connection not found"}}))
    else:
        original_conn = ConnectionManager.current
        try:
            ConnectionManager.current = target_conn
            if hasattr(target_conn, 'is_dbapi_connection') and target_conn.is_dbapi_connection:
                schemas = [{{"name": "(default)", "is_default": True}}]
            else:
                schema_names = inspect.get_schema_names()
                schemas = [{{"name": s, "is_default": False}} for s in schema_names]
            print(json.dumps({{"schemas": schemas}}))
        finally:
            ConnectionManager.current = original_conn
except Exception as _e:
    print(json.dumps({{"error": str(_e)}}))
"""
            result = await self.execute_in_kernel(code)
            if result:
                parsed = self._parse_kernel_result(result)
                if parsed is None:
                    self.set_status(500)
                    self.write_json({"error": "Unexpected kernel output"})
                    return
                if "error" in parsed:
                    self.set_status(404 if "not found" in parsed["error"] else 500)
                    self.write_json({"error": parsed["error"]})
                else:
                    self.write_json(parsed)
            else:
                self.set_status(500)
                self.write_json({"error": "No response from kernel"})
        except Exception as e:
            self.log.error(f"Error getting schemas: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class TablesHandler(BaseJupySQLHandler):
    """GET /jupysql/tables — list tables for a schema."""

    async def get(self):
        try:
            connection_key = self.get_argument("connection_key", None)
            schema = self.get_argument("schema", None)
            if not connection_key:
                self.set_status(400)
                self.write_json({"error": "connection_key parameter is required"})
                return

            ck_repr = repr(connection_key)
            schema_arg = "None" if not schema or schema == "(default)" else repr(schema)

            code = f"""\
import json
try:
    from sql.connection import ConnectionManager
    from sql import inspect
    target_conn = ConnectionManager.connections.get({ck_repr})
    if not target_conn:
        print(json.dumps({{"error": "Connection not found"}}))
    else:
        original_conn = ConnectionManager.current
        try:
            ConnectionManager.current = target_conn
            tables_obj = inspect.get_table_names(schema={schema_arg})
            table_names = []
            for row in tables_obj._table:
                name = row.get_string(
                    fields=["Name"], border=False, header=False
                ).strip()
                table_names.append(name)
            print(json.dumps({{"tables": [{{"name": t}} for t in table_names]}}))
        finally:
            ConnectionManager.current = original_conn
except Exception as _e:
    print(json.dumps({{"error": str(_e)}}))
"""
            result = await self.execute_in_kernel(code)
            if result:
                parsed = self._parse_kernel_result(result)
                if parsed is None:
                    self.set_status(500)
                    self.write_json({"error": "Unexpected kernel output"})
                    return
                if "error" in parsed:
                    self.set_status(404 if "not found" in parsed["error"] else 500)
                    self.write_json({"error": parsed["error"]})
                else:
                    self.write_json(parsed)
            else:
                self.set_status(500)
                self.write_json({"error": "No response from kernel"})
        except Exception as e:
            self.log.error(f"Error getting tables: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class ColumnsHandler(BaseJupySQLHandler):
    """GET /jupysql/columns — list columns for a table."""

    async def get(self):
        try:
            connection_key = self.get_argument("connection_key", None)
            schema = self.get_argument("schema", None)
            table = self.get_argument("table", None)
            if not connection_key or not table:
                self.set_status(400)
                self.write_json({
                    "error": "connection_key and table parameters are required"
                })
                return

            ck_repr = repr(connection_key)
            table_repr = repr(table)
            schema_arg = "None" if not schema or schema == "(default)" else repr(schema)

            code = f"""\
import json
try:
    from sql.connection import ConnectionManager
    from sql import inspect
    target_conn = ConnectionManager.connections.get({ck_repr})
    if not target_conn:
        print(json.dumps({{"error": "Connection not found"}}))
    else:
        original_conn = ConnectionManager.current
        try:
            ConnectionManager.current = target_conn
            columns_obj = inspect.get_columns({table_repr}, schema={schema_arg})
            columns = []
            field_names = columns_obj._table.field_names
            for row in columns_obj._table:
                col_name = row.get_string(
                    fields=[field_names[0]], border=False, header=False
                ).strip()
                col_type = ""
                if len(field_names) > 1:
                    col_type = row.get_string(
                        fields=[field_names[1]], border=False, header=False
                    ).strip()
                columns.append({{"name": col_name, "type": col_type}})
            print(json.dumps({{"columns": columns}}))
        finally:
            ConnectionManager.current = original_conn
except Exception as _e:
    print(json.dumps({{"error": str(_e)}}))
"""
            result = await self.execute_in_kernel(code)
            if result:
                parsed = self._parse_kernel_result(result)
                if parsed is None:
                    self.set_status(500)
                    self.write_json({"error": "Unexpected kernel output"})
                    return
                if "error" in parsed:
                    self.set_status(404 if "not found" in parsed["error"] else 500)
                    self.write_json({"error": parsed["error"]})
                else:
                    self.write_json(parsed)
            else:
                self.set_status(500)
                self.write_json({"error": "No response from kernel"})
        except Exception as e:
            self.log.error(f"Error getting columns: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class PreviewHandler(BaseJupySQLHandler):
    """GET /jupysql/preview — preview rows for a table."""

    async def get(self):
        try:
            connection_key = self.get_argument("connection_key", None)
            schema = self.get_argument("schema", None)
            table = self.get_argument("table", None)
            limit = int(self.get_argument("limit", "100"))
            offset = int(self.get_argument("offset", "0"))
            if not connection_key or not table:
                self.set_status(400)
                self.write_json({
                    "error": "connection_key and table parameters are required"
                })
                return

            ck_repr = repr(connection_key)
            table_repr = repr(table)

            code = f"""\
import json
try:
    from sql.connection import ConnectionManager
    from sql import inspect
    target_conn = ConnectionManager.connections.get({ck_repr})
    if not target_conn:
        print(json.dumps({{"error": "Connection not found"}}))
    else:
        original_conn = ConnectionManager.current
        try:
            ConnectionManager.current = target_conn
            data, column_names = inspect.fetch_sql_with_pagination(
                table={table_repr},
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
except Exception as _e:
    print(json.dumps({{"error": str(_e)}}))
"""
            result = await self.execute_in_kernel(code)
            if result:
                parsed = self._parse_kernel_result(result)
                if parsed is None:
                    self.set_status(500)
                    self.write_json({"error": "Unexpected kernel output"})
                    return
                if "error" in parsed:
                    self.set_status(404 if "not found" in parsed["error"] else 500)
                    self.write_json({"error": parsed["error"]})
                else:
                    self.write_json(parsed)
            else:
                self.set_status(500)
                self.write_json({"error": "No response from kernel"})
        except Exception as e:
            self.log.error(f"Error getting preview: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class SwitchConnectionHandler(BaseJupySQLHandler):
    """POST /jupysql/switch — set the active connection in all running kernels.

    Body: { "connection_key": str, "url": str, "alias": str }

    For each running kernel:
      - If the connection already exists in that kernel, sets it as current.
      - If it does not exist yet (e.g. a freshly-started kernel), re-establishes
        it via %sql so the user can query immediately without running %sql manually.
    """

    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            connection_key = data.get("connection_key")
            url = data.get("url", "")
            alias = data.get("alias", "")

            if not connection_key:
                self.set_status(400)
                self.write_json({"error": "connection_key is required"})
                return

            km = self.settings['kernel_manager']
            kernel_ids = list(km.list_kernel_ids())
            if not kernel_ids:
                self.set_status(503)
                self.write_json({"error": "No running kernel"})
                return

            ck_repr = repr(connection_key)
            url_repr = repr(url)
            alias_repr = repr(alias)

            code = f"""\
import json
{_LOAD_EXT_SILENT}
try:
    from sql.connection import ConnectionManager
    ip = get_ipython()

    # Locate connection in this kernel by key, then URL, then alias
    _target = ConnectionManager.connections.get({ck_repr})
    if _target is None and {url_repr}:
        for _c in ConnectionManager.connections.values():
            if str(getattr(_c, 'url', '')) == {url_repr}:
                _target = _c
                break
    if _target is None and {alias_repr}:
        for _c in ConnectionManager.connections.values():
            if getattr(_c, 'alias', None) == {alias_repr}:
                _target = _c
                break

    if _target is not None:
        # Connection exists in this kernel — just switch to it
        ConnectionManager.current = _target
        _cur = _target
    elif {url_repr}:
        # Not yet present — establish it so this kernel is ready to query
        _margs = {url_repr}
        if {alias_repr}:
            _margs = _margs + ' --alias ' + {alias_repr}
        ip.run_line_magic('sql', _margs)
        _cur = ConnectionManager.current
    else:
        _cur = None

    if _cur is not None:
        _label = getattr(_cur, 'alias', None) or str(getattr(_cur, 'url', ''))
        print(json.dumps({{"status": "success", "connection_label": _label}}))
    else:
        print(json.dumps({{"error": "Connection not found and no URL provided"}}))
except Exception as _e:
    print(json.dumps({{"error": str(_e)}}))
"""

            success_count = 0
            last_label = alias or url

            for kernel_id in kernel_ids:
                result = await self.execute_in_kernel(code, kernel_id)
                if not result:
                    continue
                parsed = self._parse_kernel_result(result)
                if parsed and parsed.get("status") == "success":
                    success_count += 1
                    last_label = parsed.get("connection_label") or last_label

            if success_count > 0:
                self.write_json({
                    "status": "success",
                    "message": f"Switched to {last_label}",
                    "connection_label": last_label,
                })
            else:
                self.set_status(404)
                self.write_json({"error": "Connection not found in any running kernel"})

        except Exception as e:
            self.log.error(f"Error switching connection: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


def setup_handlers(web_app, log):
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]
    handlers = [
        (url_path_join(base_url, "jupysql", "init"), InitHandler),
        (url_path_join(base_url, "jupysql", "connections"), ConnectionsHandler),
        (url_path_join(base_url, "jupysql", "schemas"), SchemasHandler),
        (url_path_join(base_url, "jupysql", "tables"), TablesHandler),
        (url_path_join(base_url, "jupysql", "columns"), ColumnsHandler),
        (url_path_join(base_url, "jupysql", "preview"), PreviewHandler),
        (url_path_join(base_url, "jupysql", "switch"), SwitchConnectionHandler),
    ]
    web_app.add_handlers(host_pattern, handlers)
    log.info(f"JupySQL REST API handlers registered at {base_url}jupysql/*")
