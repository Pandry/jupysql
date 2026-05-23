# Auto-load JupySQL extension and connect provider-discovered databases.
#
# This runs at IPython kernel startup so that:
# 1. The %sql magic is available immediately (no manual %load_ext sql)
# 2. Databases discovered by providers (e.g. CNPG) are auto-connected
#    and appear in the JupyterLab sidebar databrowser right away
#
# Debug output is gated behind JUPYSQL_DEBUG=1 (env var).
import os

_debug = os.getenv("JUPYSQL_DEBUG", "").lower() in ("1", "true", "yes")

try:
    get_ipython().run_line_magic("load_ext", "sql")
except Exception:
    pass

try:
    from sql.connection import ConnectionManager
    from sql.providers import get_factory

    factory = get_factory()
    databases = factory.list_databases()

    if _debug:
        import sys
        print(
            f"[JupySQL] Auto-connect: {len(databases)} database(s) from providers",
            file=sys.stderr,
        )

    for db in databases:
        try:
            # Skip if a connection with this alias already exists
            if db.name and db.name in ConnectionManager.connections:
                continue
            ConnectionManager.connect_from_provider(db.identifier, alias=db.name)
        except Exception as exc:
            if _debug:
                import sys
                print(
                    f"[JupySQL] Auto-connect failed for {db.name}: {exc}",
                    file=sys.stderr,
                )
except Exception:
    # Non-fatal: providers may not be configured
    pass
