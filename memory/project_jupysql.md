---
name: JupySQL project context
description: JupySQL JupyterLab extension — architecture, fixed bugs, known patterns
type: project
---

## Architecture

- Python backend: `src/sql/labextension/handlers.py` — REST API handlers (Tornado) mounted at `/jupysql/*`
- TypeScript frontend: `jupysql_labextension/src/` — React sidebar widget
  - `index.ts` — JupyterLab plugin registration
  - `sidebar.tsx` — main panel (DatabaseBrowserPanel) + AddConnectionDialog
  - `components/DatabaseTree.tsx` — hierarchical tree: connections → schemas → tables → columns
  - `services/api.ts` — typed API client (singleton via `getAPI()`)
  - `style/index.css` — all styles

## Key patterns

- `execute_in_kernel(code, kernel_id?)` — runs Python in a kernel, captures stdout
- `_parse_kernel_result(result)` — extracts the LAST valid JSON from kernel stdout (handles jupysql info lines before our `print(json.dumps(...))`)
- `_LOAD_EXT_SILENT` — silently loads `%sql` magic before kernel code to avoid "already loaded" noise
- All React state reads inside async callbacks use `useRef` to avoid stale closures

## Bugs fixed (2026-03-20)

### Switch not applying to correct kernel
- **Root cause**: `execute_in_kernel(code)` with no kernel_id always picked `kernel_ids[0]`, not necessarily the user's active notebook kernel
- **Fix**: `SwitchConnectionHandler` now iterates ALL running kernels; for each kernel it either sets `ConnectionManager.current` (connection already present) or runs `%sql url [--alias name]` to establish it first
- **API change**: POST `/jupysql/switch` now also accepts `url` and `alias` in the body; frontend (`api.ts`) passes them via `switchConnection(key, url, alias)`

### Selected connection not cleared after kernel restart
- **Root cause**: `loadConnections` only set `selectedConnection` when a `is_current` was found, never cleared it
- **Fix**: always `setSelectedConnection(current?.key ?? null)` — if no current exists (e.g. after restart), the dropdown resets to "— select —"

### No auto-switch when opening a new notebook
- **Fix**: `sidebar.tsx` listens to `app.shell.currentChanged`; when the active tab changes and a connection is selected, re-applies the switch via `api.switchConnection` (which now establishes the connection in new kernels too)

## DB-type icons (2026-03-20)

Added in `DatabaseTree.tsx` — coloured cylinder SVGs keyed by URL scheme:
- DuckDB → yellow (#FFC107)
- SQLite → blue (#0F7EC1)
- PostgreSQL → dark blue (#336791)
- MySQL → orange+blue (#F29111 / #00618A)
- MSSQL → red (#CC2927)
- Oracle → red (#F80000)
- Generic → grey (#616161)

Icon has `title={node.label}` wrapper so hovering shows the DB name.

## Multiple databases in one notebook

Already supported by jupysql natively:
```
%sql --alias conn1      # switch to conn1
%sql SELECT * FROM t1   # queries conn1
%sql --alias conn2      # switch to conn2
%sql SELECT * FROM t2   # queries conn2
```
The cell magic `%%sql alias_name` (line 1 of cell) also lets you target a specific connection per-cell without changing the global current.
