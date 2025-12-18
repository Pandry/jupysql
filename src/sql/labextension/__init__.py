"""JupySQL JupyterLab Server Extension"""

from .app import JupySQLExtension


def _jupyter_server_extension_points():
    """
    Returns a list of dictionaries with metadata describing
    where to find the `_load_jupyter_server_extension` function.
    """
    return [{"module": "sql.labextension.app", "app": JupySQLExtension}]
