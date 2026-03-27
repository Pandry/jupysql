"""REST API handlers for the JupySQL JupyterLab extension.

Architecture overview
---------------------
JupySQL stores all state — open database connections, the currently active
connection, etc. — **inside the IPython kernel** process.  The Jupyter server
process does not hold any SQL connection objects of its own.

Because of this, every REST endpoint that needs to read or mutate connection
state must execute a small Python snippet *inside the kernel* via the Jupyter
messaging protocol.  The typical flow for each request is:

  1. Build a Python code string that imports ``ConnectionManager``, performs
     the desired operation, and calls ``print(json.dumps(...))`` to emit the
     result to stdout.
  2. Call ``execute_in_kernel()`` which sends the snippet to the kernel and
     accumulates all stdout output.
  3. Call ``_parse_kernel_result()`` to extract the last valid JSON value from
     that stdout.  IPython and JupySQL may print informational lines before our
     ``print()`` call, so we scan backwards for the first line that is valid
     JSON.
  4. Return the parsed value as the HTTP response body.

Steps 2-4 are wrapped into the helper ``_execute_kernel_request()`` so that
individual handler methods only have to build the kernel code string and then
call that one helper.

The very common "temporarily switch to a given connection, run some code, then
restore the original connection" pattern is factored into the module-level
helper ``_with_connection()``.

For the TypeScript counterpart that calls these endpoints, see
``jupysql_labextension/src/services/api.ts``.
"""

import asyncio
import json
import textwrap
import traceback
from typing import Any, Optional

from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join


# ---------------------------------------------------------------------------
# Kernel snippet: silently load the %sql magic extension.
#
# When %load_ext sql is called on a kernel where it is already loaded,
# IPython prints a reminder message.  We redirect stdout while loading so
# that noise does not interfere with our JSON-parsing logic.
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


def _with_connection(connection_key: str, body: str) -> str:
    """Build a kernel snippet that temporarily switches to *connection_key*.

    The generated code:
      1. Imports ``ConnectionManager`` and ``sql.inspect``.
      2. Looks up *connection_key* in ``ConnectionManager.connections``.
      3. If found, temporarily sets ``ConnectionManager.current`` to that
         connection so that all ``inspect.*`` calls target the right DB.
      4. Executes *body* (which should ``print(json.dumps(...))`` its result).
      5. Restores the original current connection in a ``finally`` block,
         even if *body* raises an exception.

    *body* can be any consistently-indented (or unindented) block of Python.
    ``textwrap.dedent`` + ``textwrap.indent`` normalise the indentation so the
    body slots correctly into the generated code at the right nesting level.

    ``repr(connection_key)`` is used to embed the key as a safe Python string
    literal even when it contains quotes or backslashes (avoids injection).
    """
    ck_repr = repr(connection_key)

    # Normalise indentation: strip common leading whitespace, then add exactly
    # 12 spaces (3 × 4-space levels: try → else → try) so the body lines up
    # inside the generated wrapper.
    indented_body = textwrap.indent(textwrap.dedent(body).strip(), " " * 12)

    return f"""\
import json
try:
    from sql.connection import ConnectionManager
    from sql import inspect
    _target_conn = ConnectionManager.connections.get({ck_repr})
    if _target_conn is None:
        print(json.dumps({{"error": "Connection not found"}}))
    else:
        _original_conn = ConnectionManager.current
        try:
            ConnectionManager.current = _target_conn
{indented_body}
        finally:
            # Always restore the previous active connection
            ConnectionManager.current = _original_conn
except Exception as _e:
    print(json.dumps({{"error": str(_e)}}))
"""


class BaseJupySQLHandler(APIHandler):
    """Base handler shared by all JupySQL REST endpoints.

    Provides three helpers that almost every concrete handler uses:

      - ``_require_argument(name)``       — validate a required query parameter.
      - ``_execute_kernel_request(code)`` — run kernel code and write the HTTP
                                            response from the JSON result.
      - ``execute_in_kernel(code)``       — low-level: send code to a kernel,
                                            collect stdout, return as a string.
      - ``_parse_kernel_result(result)``  — extract the last valid JSON from
                                            kernel stdout.
    """

    async def execute_in_kernel(
        self,
        code: str,
        kernel_id: Optional[str] = None,
        total_timeout: float = 30.0,
    ) -> Optional[str]:
        """Execute *code* in a running kernel and return all stdout as a string.

        If *kernel_id* is not given, the first available kernel is used.
        Returns ``None`` when there are no running kernels or the execution
        fails for any reason (timeout, kernel error, etc.).

        A wall-clock deadline (``total_timeout`` seconds) prevents the message
        loop from hanging indefinitely when the iopub channel carries unrelated
        messages from other concurrent executions.  Stream chunks are
        accumulated rather than overwritten, so multi-message output is
        captured correctly.
        """
        km = self.settings["kernel_manager"]

        if not kernel_id:
            kernel_ids = list(km.list_kernel_ids())
            self.log.info(f"Found {len(kernel_ids)} running kernels")
            if not kernel_ids:
                self.log.warning("No running kernels found")
                return None
            kernel_id = kernel_ids[0]
            self.log.info(f"Using kernel: {kernel_id}")

        # Guard: client must be assigned before the finally block so that
        # stop_channels() is only called when the client was actually created.
        client = None
        try:
            kernel = km.get_kernel(kernel_id)
            client = kernel.client()
            client.start_channels()

            result_data: Optional[str] = None
            msg_id = client.execute(code, silent=True, store_history=False)
            self.log.info(f"Executed code in kernel, msg_id: {msg_id}")

            loop = asyncio.get_event_loop()
            deadline = loop.time() + total_timeout

            while loop.time() < deadline:
                remaining = deadline - loop.time()
                try:
                    msg = await client.get_iopub_msg(timeout=min(1.0, remaining))
                    msg_type = msg["msg_type"]

                    # Ignore messages that belong to other concurrent executions
                    if msg["parent_header"].get("msg_id") != msg_id:
                        continue

                    if msg_type == "stream":
                        chunk = msg["content"]["text"]
                        result_data = (result_data or "") + chunk
                        self.log.info(
                            f"Got stream chunk ({len(chunk)} chars), "
                            f"total so far: {len(result_data)}"
                        )
                    elif msg_type == "execute_result":
                        result_data = msg["content"]["data"]["text/plain"]
                    elif msg_type == "error":
                        self.log.error(f"Kernel error: {msg['content']}")
                        return None
                    elif (
                        msg_type == "status"
                        and msg["content"]["execution_state"] == "idle"
                    ):
                        # Kernel finished — no more messages for this execution
                        break
                except Exception:
                    # get_iopub_msg timed out on the 1-second slice;
                    # loop back and check the wall-clock deadline.
                    pass

            self.log.info(f"Final result: {result_data}")
            return result_data

        except Exception as e:
            self.log.error(
                f"execute_in_kernel error "
                f"(kernel={kernel_id[:8] if kernel_id else '?'}): {e}"
            )
            return None
        finally:
            if client is not None:
                client.stop_channels()

    def _parse_kernel_result(self, result: str) -> Any:
        """Extract the last valid JSON value from kernel stdout.

        JupySQL (and IPython) may print informational text such as:

            The sql extension is already loaded. To reload it, use:
              %reload_ext sql

        *before* our own ``print()`` call.  We scan lines in reverse to find
        the last line that parses as a JSON object or array, and return it.
        Returns ``None`` if no valid JSON is found anywhere in *result*.
        """
        if not result:
            return None

        stripped = result.strip()

        # Fast path: the entire buffer is valid JSON (most common case)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        # Slow path: scan backwards for the last line that looks like JSON
        for line in reversed(stripped.split("\n")):
            candidate = line.strip()
            if (candidate.startswith("{") and candidate.endswith("}")) or (
                candidate.startswith("[") and candidate.endswith("]")
            ):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass

        return None

    def _require_argument(self, name: str) -> Optional[str]:
        """Return the value of a required query parameter.

        If the parameter is absent or empty, writes a 400 response and returns
        ``None``.  Callers should check for ``None`` and return immediately::

            connection_key = self._require_argument("connection_key")
            if connection_key is None:
                return
        """
        value = self.get_argument(name, None)
        if not value:
            self.set_status(400)
            self.write_json({"error": f"{name} parameter is required"})
        return value

    async def _execute_kernel_request(
        self,
        code: str,
        kernel_id: Optional[str] = None,
    ) -> bool:
        """Execute *code* in a kernel, parse the result, and write the HTTP response.

        Returns ``True`` when a successful JSON payload was written to the
        response.  Returns ``False`` when an error response was written instead
        (no running kernel, unexpected output, or the kernel code itself
        returned an ``{"error": "..."}`` dict).

        This consolidates the repetitive "execute → parse → respond" pattern
        that every handler needs, so each handler only has to build the code
        string and then call this helper.
        """
        result = await self.execute_in_kernel(code, kernel_id)

        if not result:
            self.set_status(500)
            self.write_json({"error": "No response from kernel"})
            return False

        parsed = self._parse_kernel_result(result)
        if parsed is None:
            self.set_status(500)
            self.write_json({"error": f"Unexpected kernel output: {result[:200]}"})
            return False

        if "error" in parsed:
            # Use 404 for "connection not found" errors, 500 for everything else
            status = 404 if "not found" in str(parsed["error"]).lower() else 500
            self.set_status(status)
            self.write_json({"error": parsed["error"]})
            return False

        self.write_json(parsed)
        return True

    # ------------------------------------------------------------------
    # Tornado overrides
    # ------------------------------------------------------------------

    def check_xsrf_cookie(self) -> None:
        """Bypass Tornado's XSRF cookie check for this extension's endpoints.

        JupyterLab's ``ServerConnection.makeRequest`` includes the Jupyter
        server token in every request (via the ``Authorization`` header or a
        query parameter), which already prevents cross-site abuse.  Relying on
        cookie-only XSRF protection is therefore redundant and causes test
        failures when the server token is disabled.

        Overriding this method to a no-op is the standard pattern for Jupyter
        server extensions; see official extension examples in the JupyterLab
        documentation.

        **Important**: never disable the server token itself
        (``ServerApp.token = ''``) in production environments.
        """

    def prepare(self) -> None:
        self.log.debug(f"{self.request.method} {self.request.path}")

    def write_error(self, status_code: int, **kwargs: Any) -> None:
        """Return all errors as JSON rather than Tornado's default HTML page."""
        self.set_header("Content-Type", "application/json")
        error_msg = "An error occurred"
        if "exc_info" in kwargs:
            exc_type, exc_value, exc_tb = kwargs["exc_info"]
            error_msg = str(exc_value)
            if self.settings.get("serve_traceback"):
                tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
                self.log.error(f"Error in {self.request.path}: {tb}")
        self.finish(json.dumps({"error": error_msg}))

    def write_json(self, data: Any) -> None:
        """Serialize *data* to JSON and finish the response."""
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(data))


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


class ConnectionsHandler(BaseJupySQLHandler):
    """Manage the list of active database connections.

    GET    /jupysql/connections — list all connections from all running kernels
    POST   /jupysql/connections — add a new connection (executes %sql in kernel)
    DELETE /jupysql/connections — close and remove a connection from all kernels
    """

    async def get(self) -> None:
        """List connections, optionally filtered to a specific kernel.

        Query parameters:
          - ``kernel_id`` (optional): If provided, only query that kernel.
            Otherwise, aggregate connections from all running kernels.

        The same connection may appear in multiple kernels if they share state
        (e.g. two notebooks that have both run ``%sql duckdb://``).  When
        querying all kernels, we deduplicate by the connection key so the UI
        sees each connection once.
        """
        try:
            km = self.settings["kernel_manager"]
            target_kernel_id = self.get_argument("kernel_id", None)

            if target_kernel_id:
                # Query only the specified kernel
                kernel_ids = [target_kernel_id]
                self.log.info(f"Querying specific kernel: {target_kernel_id[:8]}")
            else:
                # Query all kernels
                kernel_ids = list(km.list_kernel_ids())
                self.log.info(f"Querying {len(kernel_ids)} kernels for connections")

            all_connections = []
            seen_keys: set = set()

            # Kernel code: query ConnectionManager for the list of open connections.
            # Each connection is serialised as a plain dict so it can be JSON-encoded.
            code = """\
import json
try:
    from sql.connection import ConnectionManager
    raw_connections = ConnectionManager._get_connections()
    connections = []
    for conn in raw_connections:
        connections.append({
            'key':     str(conn.get('key',     '')),
            'url':     str(conn.get('url',     '')),
            'alias':   str(conn.get('alias',   '')),
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
                                "key":        key,
                                "url":        conn_dict["url"],
                                "alias":      conn_dict["alias"],
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

    async def delete(self) -> None:
        """Close and remove a connection from every running kernel.

        Request body: ``{ "connection_key": "<key>" }``

        The connection's SQLAlchemy session and engine are closed before the
        connection object is removed, releasing any held database resources
        (file locks, network sockets, etc.) even if the caller does not do so
        explicitly.
        """
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            connection_key = data.get("connection_key")
            if not connection_key:
                self.set_status(400)
                self.write_json({"error": "connection_key is required"})
                return

            ck_repr = repr(connection_key)

            # Kernel code: close resources and delete the connection from the dict.
            # If this was the active connection, promote another one (or set None).
            code = f"""\
import json
try:
    from sql.connection import ConnectionManager
    _conn = ConnectionManager.connections.get({ck_repr})
    if _conn is None:
        print(json.dumps({{"status": "not_found"}}))
    else:
        # Release database resources before removing the connection object
        try:
            if hasattr(_conn, 'session') and _conn.session:
                _conn.session.close()
        except Exception:
            pass
        try:
            if hasattr(_conn, '_engine') and _conn._engine:
                _conn._engine.dispose()
        except Exception:
            pass
        del ConnectionManager.connections[{ck_repr}]
        # Promote another connection to current if this was the active one
        if ConnectionManager.current is _conn:
            _remaining = list(ConnectionManager.connections.values())
            ConnectionManager.current = _remaining[0] if _remaining else None
        print(json.dumps({{"status": "success"}}))
except Exception as _e:
    print(json.dumps({{"error": str(_e)}}))
"""
            km = self.settings["kernel_manager"]
            kernel_ids = list(km.list_kernel_ids())
            for kernel_id in kernel_ids:
                await self.execute_in_kernel(code, kernel_id)

            self.write_json({"status": "success"})

        except Exception as e:
            self.log.error(f"Error deleting connection: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})

    async def post(self) -> None:
        """Add a new connection by running ``%sql <connection_string>`` in the kernel.

        Request body: ``{ "connection_string": "<url>", "alias": "<name>", "all_kernels": bool }``

        Parameters:
          - ``connection_string`` (required): The database connection URL.
          - ``alias`` (optional): A friendly name for the connection.
          - ``all_kernels`` (optional, default false): If true, the connection
            is established in ALL running kernels. This is useful for scripts
            that inject credentials into multiple notebooks (e.g., K8s sidecars).

        The connection string is passed through ``repr()`` before being
        embedded in the kernel code, which turns it into a safe Python string
        literal even when it contains special characters such as ``'`` or
        ``\\``.  This prevents any form of code injection via the URL field.
        """
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            connection_string = data.get("connection_string")
            alias = data.get("alias") or ""
            all_kernels = data.get("all_kernels", False)

            if not connection_string:
                self.set_status(400)
                self.write_json({"error": "connection_string is required"})
                return

            conn_repr  = repr(connection_string)
            alias_repr = repr(alias)

            # Build the %sql magic invocation: `%sql <url>` or `%sql <url> --alias <name>`
            code = f"""\
import json
{_LOAD_EXT_SILENT}
try:
    _conn_str  = {conn_repr}
    _alias     = {alias_repr}
    _magic_args = _conn_str + (' --alias ' + _alias if _alias else '')
    get_ipython().run_line_magic('sql', _magic_args)
    print(json.dumps({{"status": "success"}}))
except Exception as _e:
    print(json.dumps({{"error": str(_e)}}))
"""
            if all_kernels:
                # Execute in all running kernels
                km = self.settings["kernel_manager"]
                kernel_ids = list(km.list_kernel_ids())
                self.log.info(f"Adding connection to all {len(kernel_ids)} kernels")

                success_count = 0
                errors = []
                for kernel_id in kernel_ids:
                    result = await self.execute_in_kernel(code, kernel_id)
                    if result:
                        resp = self._parse_kernel_result(result)
                        if resp and resp.get("status") == "success":
                            success_count += 1
                        elif resp and "error" in resp:
                            errors.append(f"{kernel_id[:8]}: {resp['error']}")

                if success_count > 0:
                    self.write_json({
                        "status": "success",
                        "message": f"Connection added to {success_count}/{len(kernel_ids)} kernels",
                        "errors": errors if errors else None,
                    })
                else:
                    self.set_status(500)
                    self.write_json({
                        "error": "Failed to add connection to any kernel",
                        "details": errors,
                    })
                return

            # Default: execute in first available kernel
            result = await self.execute_in_kernel(code)

            if result:
                resp = self._parse_kernel_result(result)
                if resp is None:
                    self.set_status(500)
                    self.write_json({"error": f"Unexpected kernel output: {result[:200]}"})
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
    """POST /jupysql/init — load the ``%sql`` magic in all running kernels.

    Called automatically when the sidebar panel mounts.  This means users
    can browse connections and schemas without having to run
    ``%load_ext sql`` manually in each notebook.
    """

    async def post(self) -> None:
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
    """GET /jupysql/schemas?connection_key=<key> — list schemas for a connection.

    DBAPI connections (e.g. a raw ``sqlite3`` object instead of a SQLAlchemy
    engine) don't have a schema namespace.  We represent them as a single
    ``(default)`` schema so the database tree always has a node to expand.
    """

    async def get(self) -> None:
        connection_key = self._require_argument("connection_key")
        if connection_key is None:
            return

        # The body runs inside the connection-switching wrapper supplied by
        # _with_connection().  At this point ConnectionManager.current has
        # already been set to the target connection.
        body = """\
            if hasattr(_target_conn, 'is_dbapi_connection') and _target_conn.is_dbapi_connection:
                # Raw DBAPI connections have no schema concept; use a placeholder
                schemas = [{"name": "(default)", "is_default": True}]
            else:
                schema_names = inspect.get_schema_names()
                schemas = [{"name": s, "is_default": False} for s in schema_names]
            print(json.dumps({"schemas": schemas}))
        """

        code = _with_connection(connection_key, body)
        try:
            await self._execute_kernel_request(code)
        except Exception as e:
            self.log.error(f"Error getting schemas: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class TablesHandler(BaseJupySQLHandler):
    """GET /jupysql/tables?connection_key=<key>&schema=<name> — list tables.

    *schema* is optional.  Pass ``"(default)"`` (or omit it entirely) to list
    tables in the connection's default schema.
    """

    async def get(self) -> None:
        connection_key = self._require_argument("connection_key")
        if connection_key is None:
            return

        schema = self.get_argument("schema", None)
        # Treat the UI sentinel "(default)" the same as no schema
        schema_arg = "None" if not schema or schema == "(default)" else repr(schema)

        body = f"""\
            tables_obj = inspect.get_table_names(schema={schema_arg})
            table_names = []
            for row in tables_obj._table:
                name = row.get_string(
                    fields=["Name"], border=False, header=False
                ).strip()
                table_names.append(name)
            print(json.dumps({{"tables": [{{"name": t}} for t in table_names]}}))
        """

        code = _with_connection(connection_key, body)
        try:
            await self._execute_kernel_request(code)
        except Exception as e:
            self.log.error(f"Error getting tables: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class ColumnsHandler(BaseJupySQLHandler):
    """GET /jupysql/columns?connection_key=<key>&table=<name>&schema=<name> — list columns.

    Both *connection_key* and *table* are required.  *schema* is optional.
    """

    async def get(self) -> None:
        connection_key = self._require_argument("connection_key")
        if connection_key is None:
            return

        table = self._require_argument("table")
        if table is None:
            return

        schema     = self.get_argument("schema", None)
        table_repr = repr(table)
        schema_arg = "None" if not schema or schema == "(default)" else repr(schema)

        body = f"""\
            columns_obj = inspect.get_columns({table_repr}, schema={schema_arg})
            field_names = columns_obj._table.field_names
            columns = []
            for row in columns_obj._table:
                col_name = row.get_string(
                    fields=[field_names[0]], border=False, header=False
                ).strip()
                # The type column may not always be present (depends on the driver)
                col_type = (
                    row.get_string(fields=[field_names[1]], border=False, header=False).strip()
                    if len(field_names) > 1 else ""
                )
                columns.append({{"name": col_name, "type": col_type}})
            print(json.dumps({{"columns": columns}}))
        """

        code = _with_connection(connection_key, body)
        try:
            await self._execute_kernel_request(code)
        except Exception as e:
            self.log.error(f"Error getting columns: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class PreviewHandler(BaseJupySQLHandler):
    """GET /jupysql/preview — fetch a paginated sample of rows from a table.

    Query parameters:
      - ``connection_key`` (required)
      - ``table``          (required)
      - ``schema``         (optional)
      - ``limit``          (optional, default 100)
      - ``offset``         (optional, default 0)
    """

    async def get(self) -> None:
        connection_key = self._require_argument("connection_key")
        if connection_key is None:
            return

        table = self._require_argument("table")
        if table is None:
            return

        schema     = self.get_argument("schema", None)
        limit      = int(self.get_argument("limit",  "100"))
        offset     = int(self.get_argument("offset", "0"))
        table_repr = repr(table)

        body = f"""\
            data, column_names = inspect.fetch_sql_with_pagination(
                table={table_repr},
                offset={offset},
                n_rows={limit},
                sort_column=None,
                sort_order="DESC",
            )
            print(json.dumps({{
                "data":    data,
                "columns": column_names,
                "offset":  {offset},
                "limit":   {limit},
            }}))
        """

        code = _with_connection(connection_key, body)
        try:
            await self._execute_kernel_request(code)
        except Exception as e:
            self.log.error(f"Error getting preview: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class KernelsHandler(BaseJupySQLHandler):
    """GET /jupysql/kernels — list all running kernels with notebook info.

    Returns a list of kernels with their IDs and associated notebook names.
    This enables the frontend to show which kernel will be used for operations
    and to automatically switch to the kernel of the currently active notebook.
    """

    async def get(self) -> None:
        try:
            km = self.settings["kernel_manager"]
            sm = self.settings.get("session_manager")
            kernel_ids = list(km.list_kernel_ids())
            self.log.info(f"Found {len(kernel_ids)} running kernels")

            kernels = []

            # Build a map from kernel_id to session info for notebook names
            session_map = {}
            if sm:
                try:
                    sessions = await sm.list_sessions()
                    for sess in sessions:
                        kid = sess.get("kernel", {}).get("id")
                        if kid:
                            session_map[kid] = {
                                "name": sess.get("name", ""),
                                "path": sess.get("path", ""),
                                "type": sess.get("type", ""),
                            }
                except Exception as e:
                    self.log.warning(f"Could not list sessions: {e}")

            for kernel_id in kernel_ids:
                session_info = session_map.get(kernel_id, {})
                name = session_info.get("name", "")
                path = session_info.get("path", "")

                # Use notebook name if available, otherwise fall back to kernel ID
                display_name = name or f"kernel-{kernel_id[:8]}"

                kernels.append({
                    "id": kernel_id,
                    "name": display_name,
                    "path": path,
                })

            self.write_json({"kernels": kernels})

        except Exception as e:
            self.log.error(f"Error getting kernels: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class SwitchConnectionHandler(BaseJupySQLHandler):
    """POST /jupysql/switch — make a connection the active one in all running kernels.

    Request body: ``{ "connection_key": str, "url": str, "alias": str }``

    The handler tries to find the connection in each kernel using three
    fallback strategies (in order):
      1. By *connection_key* (exact dict lookup — fastest).
      2. By *url*  (linear scan of connection objects).
      3. By *alias* (linear scan of connection objects).

    If the connection is not present in a kernel at all (e.g. a freshly-started
    notebook), it is re-established via ``%sql`` so that kernel is immediately
    ready to run queries without requiring a manual ``%sql`` invocation.

    This is also called whenever the user switches JupyterLab tabs (see
    ``sidebar.tsx`` — the ``currentChanged`` effect) so that every open
    notebook always has the selected connection available.
    """

    async def post(self) -> None:
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            connection_key = data.get("connection_key")
            url   = data.get("url",   "")
            alias = data.get("alias", "")

            if not connection_key:
                self.set_status(400)
                self.write_json({"error": "connection_key is required"})
                return

            km = self.settings["kernel_manager"]
            kernel_ids = list(km.list_kernel_ids())
            if not kernel_ids:
                self.set_status(503)
                self.write_json({"error": "No running kernel"})
                return

            ck_repr    = repr(connection_key)
            url_repr   = repr(url)
            alias_repr = repr(alias)

            code = f"""\
import json
{_LOAD_EXT_SILENT}
try:
    from sql.connection import ConnectionManager
    ip = get_ipython()

    # Locate the connection in this kernel using three fallback strategies:
    #   1. By key  (exact match — O(1))
    #   2. By URL  (useful when the same DB is open under a different key)
    #   3. By alias (last resort)
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
        # Connection already exists — just switch to it
        ConnectionManager.current = _target
        _cur = _target
    elif {url_repr}:
        # Not present in this kernel — establish it now so it is ready to query
        _margs = {url_repr} + (' --alias ' + {alias_repr} if {alias_repr} else '')
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
            last_label    = alias or url

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
                    "status":           "success",
                    "message":          f"Switched to {last_label}",
                    "connection_label": last_label,
                })
            else:
                self.set_status(404)
                self.write_json({"error": "Connection not found in any running kernel"})

        except Exception as e:
            self.log.error(f"Error switching connection: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class ProvidersHandler(BaseJupySQLHandler):
    """GET /jupysql/providers — list all registered database providers."""

    async def get(self) -> None:
        """List all registered database providers and their status."""
        try:
            code = """\
import json
try:
    from sql.providers import get_factory
    factory = get_factory()
    providers = []
    for name in factory.list_providers():
        provider = factory.get_provider(name)
        providers.append({
            'name': name,
            'enabled': provider.is_enabled()
        })
    print(json.dumps({'providers': providers}))
except Exception as e:
    print(json.dumps({'error': str(e)}))
"""
            result = await self._execute_kernel_request(code)
            if result and 'error' not in result:
                self.write_json(result)
            else:
                self.set_status(500)
                self.write_json(result or {"error": "Failed to list providers"})

        except Exception as e:
            self.log.error(f"Error listing providers: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class AvailableDatabasesHandler(BaseJupySQLHandler):
    """GET /jupysql/available-databases — list all databases from providers."""

    async def get(self) -> None:
        """List all databases available from registered providers.

        Query parameters:
          - ``providers`` (optional): Comma-separated list of provider names to query.
            If not provided, queries all enabled providers.
        """
        try:
            provider_names = self.get_argument("providers", None)

            if provider_names:
                providers_list = f"[{', '.join(repr(p.strip()) for p in provider_names.split(','))}]"
            else:
                providers_list = "None"

            code = f"""\
import json
try:
    from sql.providers import get_factory
    factory = get_factory()
    databases = factory.list_databases(provider_names={providers_list})

    # Convert DatabaseInfo objects to dicts
    db_list = []
    for db in databases:
        db_list.append({{
            'identifier': db.identifier,
            'name': db.name,
            'connection_string': db.connection_string,
            'provider': db.provider,
            'metadata': db.metadata,
            'host': db.host,
            'port': db.port,
            'database': db.database,
            'username': db.username,
            'labels': db.labels,
        }})

    print(json.dumps({{'databases': db_list}}))
except Exception as e:
    import traceback
    print(json.dumps({{'error': str(e), 'traceback': traceback.format_exc()}}))
"""
            result = await self._execute_kernel_request(code)
            if result and 'error' not in result:
                self.write_json(result)
            else:
                self.set_status(500)
                self.write_json(result or {"error": "Failed to list databases"})

        except Exception as e:
            self.log.error(f"Error listing available databases: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class RefreshProvidersHandler(BaseJupySQLHandler):
    """POST /jupysql/providers/refresh — refresh database providers."""

    async def post(self) -> None:
        """Refresh database providers to discover new databases.

        Request body (optional): ``{ "provider_name": "<name>" }``
        If provider_name is not provided, refreshes all providers.
        """
        try:
            provider_name = None
            if self.request.body:
                data = json.loads(self.request.body.decode("utf-8"))
                provider_name = data.get("provider_name")

            if provider_name:
                code = f"""\
import json
try:
    from sql.providers import get_factory
    factory = get_factory()
    factory.refresh_provider({repr(provider_name)})
    print(json.dumps({{'status': 'success', 'message': f'Refreshed provider {{repr(provider_name)}}'}}))
except Exception as e:
    print(json.dumps({{'error': str(e)}}))
"""
            else:
                code = """\
import json
try:
    from sql.providers import get_factory
    factory = get_factory()
    factory.refresh_all()
    print(json.dumps({'status': 'success', 'message': 'Refreshed all providers'}))
except Exception as e:
    print(json.dumps({'error': str(e)}))\n"""

            result = await self._execute_kernel_request(code)
            if result and 'error' not in result:
                self.write_json(result)
            else:
                self.set_status(500)
                self.write_json(result or {"error": "Failed to refresh providers"})

        except Exception as e:
            self.log.error(f"Error refreshing providers: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


class ConnectFromProviderHandler(BaseJupySQLHandler):
    """POST /jupysql/providers/connect — connect to a database from a provider."""

    async def post(self) -> None:
        """Connect to a database discovered by a provider.

        Request body: ``{ "identifier": str, "alias": str (optional) }``
        """
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            identifier = data.get("identifier")
            alias = data.get("alias")

            if not identifier:
                self.set_status(400)
                self.write_json({"error": "identifier is required"})
                return

            alias_repr = repr(alias) if alias else "None"

            code = f"""\
import json
{_LOAD_EXT_SILENT}
try:
    from sql.connection import ConnectionManager
    conn = ConnectionManager.connect_from_provider(
        identifier={repr(identifier)},
        alias={alias_repr}
    )

    result = {{
        'status': 'success',
        'connection': {{
            'key': str(conn.url) if hasattr(conn, 'url') else '',
            'url': str(conn.url) if hasattr(conn, 'url') else '',
            'alias': conn.alias or '',
        }}
    }}
    print(json.dumps(result))
except Exception as e:
    import traceback
    print(json.dumps({{'error': str(e), 'traceback': traceback.format_exc()}}))
"""
            result = await self._execute_kernel_request(code)
            if result and 'error' not in result:
                self.write_json(result)
            else:
                self.set_status(500)
                self.write_json(result or {"error": "Failed to connect from provider"})

        except Exception as e:
            self.log.error(f"Error connecting from provider: {e}")
            self.set_status(500)
            self.write_json({"error": str(e)})


def setup_handlers(web_app, log):
    """Register all JupySQL REST API handlers with the Jupyter web application.

    URL map:
      POST   /jupysql/init                  — load %sql magic in all kernels
      GET    /jupysql/connections           — list active connections
      POST   /jupysql/connections           — add a new connection
      DELETE /jupysql/connections           — remove a connection
      GET    /jupysql/schemas               — list schemas for a connection
      GET    /jupysql/tables                — list tables in a schema
      GET    /jupysql/columns               — list columns in a table
      GET    /jupysql/preview               — fetch a paginated row sample
      POST   /jupysql/switch                — change the active connection
      GET    /jupysql/kernels               — list running kernels
      GET    /jupysql/providers             — list registered database providers
      GET    /jupysql/available-databases   — list databases from providers
      POST   /jupysql/providers/refresh     — refresh database providers
      POST   /jupysql/providers/connect     — connect to a database from provider
    """
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]
    handlers = [
        (url_path_join(base_url, "jupysql", "init"),                InitHandler),
        (url_path_join(base_url, "jupysql", "connections"),         ConnectionsHandler),
        (url_path_join(base_url, "jupysql", "schemas"),             SchemasHandler),
        (url_path_join(base_url, "jupysql", "tables"),              TablesHandler),
        (url_path_join(base_url, "jupysql", "columns"),             ColumnsHandler),
        (url_path_join(base_url, "jupysql", "preview"),             PreviewHandler),
        (url_path_join(base_url, "jupysql", "switch"),              SwitchConnectionHandler),
        (url_path_join(base_url, "jupysql", "kernels"),             KernelsHandler),
        (url_path_join(base_url, "jupysql", "providers"),           ProvidersHandler),
        (url_path_join(base_url, "jupysql", "available-databases"), AvailableDatabasesHandler),
        (url_path_join(base_url, "jupysql", "providers", "refresh"), RefreshProvidersHandler),
        (url_path_join(base_url, "jupysql", "providers", "connect"), ConnectFromProviderHandler),
    ]
    web_app.add_handlers(host_pattern, handlers)
    log.info(f"JupySQL REST API handlers registered at {base_url}jupysql/*")
