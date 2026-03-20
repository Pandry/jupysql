---
name: JupySQL Extension Architecture
description: Architecture, components, and customization context for the JupySQL JupyterLab extension fork
type: project
---

## What this project is

A fork/customization of [JupySQL](https://github.com/ploomber/jupysql) that adds a polished JupyterLab sidebar database browser. The Python core (magic system, connection management, etc.) is largely upstream JupySQL; the custom work lives in:

- `src/sql/labextension/` — Jupyter server extension (REST API)
- `jupysql_labextension/src/` — TypeScript/React JupyterLab frontend

## Key architectural decision: kernel-execution model

All SQL state (connections, current connection) lives **inside the IPython kernel process**, not in the Jupyter server. Every REST endpoint must execute Python code snippets in the kernel via the Jupyter messaging protocol and parse the JSON output from stdout.

## Custom frontend files

- `index.ts` — plugin entry point, registers sidebar widget and commands
- `sidebar.tsx` — main panel: connection management dialogs, context menus, notebook cell insertion
- `components/DatabaseTree.tsx` — hierarchical DB tree (connections → schemas → tables → columns), DB-specific icons
- `services/api.ts` — REST client, singleton `JupySQLAPI` class

## Custom backend files

- `src/sql/labextension/handlers.py` — all REST handlers (init, connections CRUD, schemas, tables, columns, preview, switch)
- `src/sql/labextension/app.py` — ExtensionApp registration
- `src/sql/labextension/__init__.py` — `_jupyter_server_extension_points`

## REST API surface

| Method | URL | Purpose |
|--------|-----|---------|
| POST | /jupysql/init | Load %sql magic in all kernels |
| GET | /jupysql/connections | List all connections across kernels |
| POST | /jupysql/connections | Add a new connection via %sql magic |
| DELETE | /jupysql/connections | Close and remove a connection |
| GET | /jupysql/schemas | List schemas for a connection |
| GET | /jupysql/tables | List tables in a schema |
| GET | /jupysql/columns | List columns in a table |
| GET | /jupysql/preview | Paginated row sample |
| POST | /jupysql/switch | Switch active connection in all kernels |

## Security model

XSRF is bypassed in handlers (standard Jupyter extension pattern). Real auth comes from the Jupyter server token, passed in every request by `ServerConnection.makeRequest`. Do NOT disable the server token in production.
