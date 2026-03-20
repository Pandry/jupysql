# Architecture: JupySQL JupyterLab Extension

This document explains how the JupySQL database-browser extension is structured,
why it is built the way it is, and how to add new capabilities to it.  It is
aimed at developers who are new to writing JupyterLab extensions.

---

## Table of Contents

1. [What this project is](#what-this-project-is)
2. [High-level architecture](#high-level-architecture)
3. [The kernel-execution model (the key insight)](#the-kernel-execution-model)
4. [Backend: Python server extension](#backend-python-server-extension)
   - [Entry points](#entry-points)
   - [REST API handlers](#rest-api-handlers)
   - [Handler helpers](#handler-helpers)
5. [Frontend: TypeScript / React extension](#frontend-typescript--react-extension)
   - [Plugin registration](#plugin-registration)
   - [Sidebar panel](#sidebar-panel)
   - [Database tree](#database-tree)
   - [API client](#api-client)
6. [Data flow: opening a connection](#data-flow-opening-a-connection)
7. [Data flow: browsing the database tree](#data-flow-browsing-the-database-tree)
8. [Context menus and notebook cell insertion](#context-menus-and-notebook-cell-insertion)
9. [Security model](#security-model)
10. [How to extend the project](#how-to-extend-the-project)
    - [Adding a new database icon](#adding-a-new-database-icon)
    - [Adding a new context-menu action](#adding-a-new-context-menu-action)
    - [Adding a new REST endpoint](#adding-a-new-rest-endpoint)
11. [File map](#file-map)

---

## What this project is

JupySQL is a SQL client for Jupyter notebooks.  This project adds a
**visual database browser** to JupyterLab's left sidebar.  From the sidebar
users can:

- Add and manage database connections without writing any Python.
- Browse schemas → tables → columns of any connected database.
- Right-click a table or column to insert a ready-to-run SQL snippet (or a
  matplotlib chart) into the active notebook.
- Switch the active connection so it is available in all open notebooks.

The browser is built as two cooperating pieces:

| Layer | Language | Location |
|-------|----------|----------|
| **Server extension** | Python | `src/sql/labextension/` |
| **Lab extension** (frontend) | TypeScript / React | `jupysql_labextension/src/` |

---

## High-level architecture

```
Browser (JupyterLab UI)
│
│  React sidebar panel
│    └─ DatabaseTree component
│         └─ calls JupySQLAPI (fetch)
│
│  HTTP REST (same origin as Jupyter server)
│
Jupyter Server process
│
│  Tornado web app
│    └─ JupySQL REST handlers
│         └─ kernel_manager.get_kernel(kernel_id)
│              └─ client.execute(python_code)
│
│  Jupyter messaging protocol (ZMQ)
│
IPython Kernel process (one per notebook)
│
│  ConnectionManager (JupySQL)
│    └─ dict of open SQLAlchemy / DBAPI connections
│    └─ .current  → the active connection
```

The important thing to understand is that **all SQL connection objects live in
the kernel process**, not in the server process.  The server extension acts as
a thin bridge that translates HTTP requests into kernel code executions.

---

## The kernel-execution model

### Why run code in the kernel?

JupySQL's `%sql` magic stores connection objects inside the IPython kernel's
namespace (via `ConnectionManager`, which is a class-level dict).  There is no
way for the Jupyter server to access those objects directly because the server
and kernel run in separate processes and communicate only through the Jupyter
messaging protocol.

The solution: every REST handler that needs to read or mutate connection state
**builds a small Python code string, sends it to the kernel via the messaging
protocol, and reads the JSON output from stdout**.

### The pattern in code

Every handler that queries connection state follows this skeleton:

```python
# 1. Build a Python snippet that does the work and prints JSON
code = """\
import json
try:
    from sql.connection import ConnectionManager
    ...do work...
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({"error": str(e)}))
"""

# 2. Send to kernel, collect stdout (execute_in_kernel)
raw_output = await self.execute_in_kernel(code)

# 3. Extract the last valid JSON line from stdout (_parse_kernel_result)
parsed = self._parse_kernel_result(raw_output)

# 4. Return as HTTP response (write_json)
self.write_json(parsed)
```

Steps 2-4 are wrapped in `_execute_kernel_request()` so handlers only need to
build the code string.

### Why _parse_kernel_result scans backwards

IPython (and JupySQL itself) sometimes print informational messages to stdout
*before* our own `print()` call.  For example:

```
The sql extension is already loaded. To reload it, use:
  %reload_ext sql
{"schemas": [...]}
```

`_parse_kernel_result()` scans the output **backwards**, looking for the last
line that is valid JSON.  This makes the parsing robust against any prefix
output from IPython.

### Safety: why repr() is used to embed values

When building the kernel code string, user-supplied values (connection keys,
table names, URLs) are embedded using Python's `repr()` function:

```python
ck_repr = repr(connection_key)
code = f"conn = ConnectionManager.connections.get({ck_repr})"
```

`repr()` produces a safe Python string literal (e.g. `'my"db'` or
`'table\\nname'`) that cannot break out of the string context and inject
arbitrary code.  **Never** interpolate user values directly into kernel code
strings without `repr()`.

### The _with_connection() helper

Many endpoints need to temporarily switch `ConnectionManager.current` to a
specific connection, run some code, then restore the original.  This pattern
is factored into `_with_connection(connection_key, body)`:

```
import json                          # ─┐
try:                                 #  │
    from sql.connection import ...   #  │  generated wrapper
    _target_conn = CM.get(key)       #  │
    if _target_conn is None:         #  │
        print(json.dumps(error))     #  │
    else:                            #  │
        _original = CM.current       #  │
        try:                         #  │
            CM.current = _target     #  │
            <body>                   # ─┘ your code goes here
        finally:
            CM.current = _original   # always restored
except Exception as _e:
    print(json.dumps(error))
```

The `body` parameter is a string of Python code that runs inside the
connection scope.  It should `print(json.dumps(...))` its result.

---

## Backend: Python server extension

### Entry points

| File | Purpose |
|------|---------|
| `src/sql/labextension/__init__.py` | Exports `_jupyter_server_extension_points()` — the function Jupyter calls to discover this extension |
| `src/sql/labextension/app.py` | `JupySQLExtension(ExtensionApp)` — calls `setup_handlers()` on startup |
| `src/sql/labextension/handlers.py` | All REST handler classes and the `setup_handlers()` function |

### REST API handlers

| Handler class | URL | Methods | What it does |
|---------------|-----|---------|--------------|
| `InitHandler` | `/jupysql/init` | POST | Loads `%sql` magic in all kernels silently |
| `ConnectionsHandler` | `/jupysql/connections` | GET, POST, DELETE | List / add / remove connections |
| `SchemasHandler` | `/jupysql/schemas` | GET | List schemas for a connection |
| `TablesHandler` | `/jupysql/tables` | GET | List tables in a schema |
| `ColumnsHandler` | `/jupysql/columns` | GET | List columns in a table |
| `PreviewHandler` | `/jupysql/preview` | GET | Paginated row sample |
| `SwitchConnectionHandler` | `/jupysql/switch` | POST | Change active connection in all kernels |

All handlers extend `BaseJupySQLHandler`.

### Handler helpers

`BaseJupySQLHandler` provides three helpers that almost every handler uses:

```python
# Validate a required query parameter; write 400 and return None if missing
connection_key = self._require_argument("connection_key")
if connection_key is None:
    return

# Execute Python code in a kernel and write the JSON result as the HTTP response.
# Returns True on success, False if an error response was written instead.
await self._execute_kernel_request(code)

# Low-level: send code to kernel, return raw stdout string (or None on failure)
result = await self.execute_in_kernel(code, kernel_id=None, total_timeout=30.0)

# Extract the last valid JSON from kernel stdout
parsed = self._parse_kernel_result(result)
```

---

## Frontend: TypeScript / React extension

### Plugin registration

`src/index.ts` is the entry point loaded by JupyterLab.  It:

1. Creates a `DatabaseBrowserWidget` (a `ReactWidget` subclass).
2. Adds the widget to the left sidebar (`rank: 500`).
3. Registers two commands in the command palette:
   - `jupysql:toggle-browser` — show/hide the sidebar.
   - `jupysql:refresh-connections` — reload the connection list.

### Sidebar panel

`src/sidebar.tsx` contains three React components:

#### `AddConnectionDialog`
A modal dialog for adding a new connection.  Shows a connection-string input,
an optional alias input, and a real-time database-type preview (via
`DbTypePreview` → `getDbTypeName`).

#### `ConnectionDetailsPanel`
A modal dialog for editing or deleting an existing connection.  Shows the
current URL and alias as editable fields, a delete confirmation flow, and a
"Switch to this" button for non-active connections.

#### `DatabaseBrowserPanel`
The main panel component.  Responsibilities:

- **State**: connection list, loading/error state, selected connection,
  dialog visibility, detail-panel target.
- **`loadConnections()`**: fetches the connection list from `/jupysql/connections`
  and syncs `selectedConnection` with the kernel's current connection.
- **Tab-change listener**: listens to `app.shell.currentChanged` and
  re-applies the selected connection to each new kernel the user navigates to.
  This ensures every notebook is immediately ready to run `%%sql` without a
  manual `%sql` setup step.
- **Context menus** (`handleNodeContextMenu`): builds a native Lumino `Menu`
  for right-clicked tree nodes.  See the [context menus](#context-menus-and-notebook-cell-insertion) section.
- **`insertIntoNotebook(codes)`**: locates the first open notebook panel and
  inserts one new code cell per item in `codes`, below the active cell.

`DatabaseBrowserWidget` is a `ReactWidget` that wraps `DatabaseBrowserPanel`
so it can live in JupyterLab's widget system.

### Database tree

`src/components/DatabaseTree.tsx` renders the four-level tree:

```
Connection (DuckDB icon, connection label)
  └─ Schema  (folder icon, schema name)
       └─ Table  (folder icon, table name)
            └─ Column  (no icon, column name + type badge)
```

Key design decisions:

- **Lazy loading**: child nodes are only fetched when the user first expands a
  parent.  This keeps the initial load fast even when a database has hundreds
  of tables.
- **`DB_PROFILES` registry**: a single array of `{ prefixes, name, icon }`
  objects drives both `getDbIcon()` and `getDbTypeName()`.  Adding a new
  database type requires one new entry in `DB_PROFILES`; no other changes.
- **Pure helpers outside the component**: `findNode()` and `updateNode()` are
  defined at module level (not inside the component) because they are pure
  functions with no dependency on React state.  This avoids re-creating them
  on every render and makes them easy to test.

### API client

`src/services/api.ts` exports a singleton `JupySQLAPI` class.  Obtain it via
`getAPI()`.  All HTTP calls go through `ServerConnection.makeRequest()` which
automatically adds the Jupyter authentication token to every request.

Available methods:

| Method | Calls | Returns |
|--------|-------|---------|
| `getConnections()` | GET /connections | `IConnection[]` |
| `addConnection(url, alias?)` | POST /connections | `IConnectionResponse` |
| `deleteConnection(key)` | DELETE /connections | `{ status }` |
| `switchConnection(key, url?, alias?)` | POST /switch | `IConnectionResponse` |
| `initExtension()` | POST /init | `{ status }` |
| `getSchemas(key)` | GET /schemas | `ISchema[]` |
| `getTables(key, schema)` | GET /tables | `ITable[]` |
| `getColumns(key, table, schema)` | GET /columns | `IColumn[]` |
| `getTablePreview(key, table, schema, limit, offset)` | GET /preview | `ITablePreview` |

---

## Data flow: opening a connection

```
User types "duckdb://" in AddConnectionDialog
  │
  └─ handleConnect(connStr, alias)
       │
       └─ api.addConnection("duckdb://", "")
            │
            │  POST /jupysql/connections
            │  body: { connection_string: "duckdb://", alias: "" }
            │
            └─ ConnectionsHandler.post()
                 │
                 └─ execute_in_kernel("""
                      %load_ext sql (silently)
                      get_ipython().run_line_magic('sql', 'duckdb://')
                      print(json.dumps({"status": "success"}))
                    """)
                      │
                      └─ kernel runs %sql duckdb://
                           └─ ConnectionManager adds DuckDB connection
```

---

## Data flow: browsing the database tree

```
User expands a "connection" node in DatabaseTree
  │
  └─ toggleNode(nodeId)
       │
       └─ loadChildren(nodeId)  [node.type === 'connection']
            │
            └─ api.getSchemas(connection.key)
                 │
                 │  GET /jupysql/schemas?connection_key=<key>
                 │
                 └─ SchemasHandler.get()
                      │
                      └─ _with_connection(key, body) generates:
                           ConnectionManager.current = target_conn
                           schemas = inspect.get_schema_names()
                           print(json.dumps({"schemas": [...]}))
                           ConnectionManager.current = original_conn
                              │
                              └─ schemas returned as JSON to frontend
                                   └─ DatabaseTree renders schema nodes
```

The same pattern repeats one level deeper when a schema node is expanded
(fetches tables) and again when a table node is expanded (fetches columns).

---

## Context menus and notebook cell insertion

Right-clicking a tree node opens a native Lumino context menu built in
`handleNodeContextMenu()` in `sidebar.tsx`.

The menu items differ by node type:

| Node type | Menu items |
|-----------|------------|
| **connection** | Edit connection…, Delete connection |
| **table** | Preview: first 10 rows, Preview: first 100 rows, Row count |
| **column** | Value counts, Histogram / Bar chart, Null count, Distinct values |

When a menu item is selected:

1. `ensureConnectionActive(key)` checks whether the connection is currently
   active; if not, calls `api.switchConnection()` first.
2. `insertIntoNotebook(codes)` finds the first open notebook panel and inserts
   one code cell per item.  Each cell is pre-filled with the relevant SQL
   (or matplotlib) snippet ready to run.

For numeric columns, the chart snippet generates a histogram using
`_result.DataFrame().plot.hist()`.  For text/categorical columns it generates
a horizontal bar chart of value counts.

The Lumino menu works by registering a **temporary command** for each item
(`jupysql:ctx-tmp-N`).  These commands are disposed via `aboutToClose` as soon
as the menu closes to avoid leaking entries in the CommandRegistry.

---

## Security model

### Authentication

All API requests are made by `ServerConnection.makeRequest()` which
automatically includes the Jupyter server token (`Authorization: token <tok>`
header).  The server validates this token on every request before dispatching
to a handler.

### XSRF bypass

`BaseJupySQLHandler` overrides `check_xsrf_cookie()` to do nothing.  This is
the standard pattern for Jupyter server extensions.  XSRF protection matters
when cookies are the **only** authentication mechanism (because browsers send
cookies automatically on cross-origin requests).  Jupyter also requires the
server token, which a malicious cross-origin page cannot obtain, so XSRF adds
no meaningful extra protection here.

**Do not disable the server token (`ServerApp.token = ''`) in production.**

### Code injection prevention

User-supplied values (connection strings, table names, connection keys) are
**never** interpolated directly into kernel code strings.  They are always
wrapped in `repr()` first, which produces a safe Python string literal.

---

## How to extend the project

### Adding a new database icon

1. Create an SVG string constant in
   `jupysql_labextension/src/components/DatabaseTree.tsx` (follow the same
   naming convention: `_MYDB_SVG`).
2. Add one new entry to the `DB_PROFILES` array:
   ```typescript
   {
     prefixes: ['mydb', 'mydb+driver'],
     name:     'My Database',
     icon:     new LabIcon({ name: 'jupysql:db-mydb', svgstr: _MYDB_SVG }),
   },
   ```
   That is all.  Both `getDbIcon()` and `getDbTypeName()` are automatically
   driven by this list.

### Adding a new context-menu action

Edit `handleNodeContextMenu()` in `sidebar.tsx`.  The items array is
constructed based on `node.type`.  Add a new `{ label, action }` object to
the relevant section:

```typescript
} else if (node.type === 'table') {
  items.push(
    // existing items ...
    { label: 'My new action', action: async () => {
        await ensureConnectionActive(connectionKey);
        await insertIntoNotebook([`%%sql\nSELECT ... FROM ${tref}`]);
    }},
  );
}
```

### Adding a new REST endpoint

1. **Backend** — add a handler class to `handlers.py`:
   ```python
   class MyHandler(BaseJupySQLHandler):
       """GET /jupysql/my-endpoint — description."""
       async def get(self) -> None:
           connection_key = self._require_argument("connection_key")
           if connection_key is None:
               return
           body = """
               result = ...some inspection code...
               print(json.dumps({"result": result}))
           """
           code = _with_connection(connection_key, body)
           try:
               await self._execute_kernel_request(code)
           except Exception as e:
               self.log.error(f"Error: {e}")
               self.set_status(500)
               self.write_json({"error": str(e)})
   ```
   Register it in `setup_handlers()`:
   ```python
   (url_path_join(base_url, "jupysql", "my-endpoint"), MyHandler),
   ```

2. **Frontend** — add a method to `JupySQLAPI` in `api.ts`:
   ```typescript
   async getMyData(connectionKey: string): Promise<IMyData[]> {
     const response = await this.get<{ result: IMyData[] }>(
       'my-endpoint',
       { connection_key: connectionKey }
     );
     return response.result;
   }
   ```

3. Call the new method from wherever you need it in the React components.

---

## File map

```
jupysql/
│
├── src/sql/labextension/          Python server extension
│   ├── __init__.py                Exposes _jupyter_server_extension_points()
│   ├── app.py                     JupySQLExtension(ExtensionApp) — registers handlers
│   └── handlers.py                All REST handlers + _with_connection() helper
│
├── jupysql_labextension/          JupyterLab (TypeScript) extension
│   ├── package.json               npm metadata, build scripts
│   └── src/
│       ├── index.ts               Plugin registration, command palette entries
│       ├── sidebar.tsx            Main panel: dialogs, context menus, state
│       ├── components/
│       │   └── DatabaseTree.tsx   Lazy tree: DB_PROFILES, icons, expand/collapse
│       └── services/
│           └── api.ts             HTTP client (JupySQLAPI singleton)
│
├── jupysql/labextension/          Built JS output (committed; served by JupyterLab)
│
├── jupyter-config/                Jupyter server config that enables the extension
│
├── Dockerfile                     Production container (Node + Python)
├── docker-compose.yml             jupysql (prod) + jupysql-dev (watch mode)
│
├── BUILD.md                       How to build and run locally or with Docker
├── COMPILE.md                     TypeScript compilation guide
├── ARCHITECTURE.md                This file
└── PRODUCTION.md                  Kubernetes / JupyterHub deployment, SSO, troubleshooting
```
