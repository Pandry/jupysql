"""JupySQL JupyterLab Extension Application"""

from jupyter_server.extension.application import ExtensionApp


class JupySQLExtension(ExtensionApp):
    """
    JupySQL extension for JupyterLab.

    Provides REST API endpoints for database browsing and connection management.
    """

    name = "jupysql"
    description = "JupySQL database browser extension for JupyterLab"
    extension_url = "/jupysql"
    load_other_extensions = True
    file_url_prefix = "/jupysql"

    def initialize_settings(self):
        """Initialize settings for the extension."""
        self.log.info(f"JupySQL extension initialized at {self.extension_url}")

    def initialize_handlers(self):
        """Initialize handlers for the extension."""
        from .handlers import setup_handlers

        self.log.info("Setting up JupySQL REST API handlers")
        setup_handlers(self.serverapp.web_app, self.log)


# Entry point for `jupyter server extension` commands
main = launch_new_instance = JupySQLExtension.launch_instance
