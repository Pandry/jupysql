/**
 * JupySQL JupyterLab Extension
 *
 * Provides a sidebar database browser for exploring database connections,
 * schemas, tables, and columns.
 */

import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ICommandPalette } from '@jupyterlab/apputils';

import { DatabaseBrowserWidget } from './sidebar';

/**
 * The plugin registration information.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupysql-labextension:plugin',
  description: 'JupySQL Database Browser Extension',
  autoStart: true,
  optional: [ICommandPalette],
  activate: (app: JupyterFrontEnd, palette: ICommandPalette | null) => {
    console.log('JupySQL Lab Extension is activated!');

    // Create the database browser widget
    const widget = new DatabaseBrowserWidget(app);

    // Add the widget to the left sidebar
    app.shell.add(widget, 'left', { rank: 500 });

    // Command to toggle the browser
    const toggleCommand = 'jupysql:toggle-browser';
    app.commands.addCommand(toggleCommand, {
      label: 'Toggle Database Browser',
      caption: 'Show/hide the JupySQL database browser',
      execute: () => {
        if (widget.isVisible) {
          widget.setHidden(true);
        } else {
          widget.setHidden(false);
          app.shell.activateById(widget.id);
        }
      }
    });

    // Command to refresh connections
    const refreshCommand = 'jupysql:refresh-connections';
    app.commands.addCommand(refreshCommand, {
      label: 'Refresh Database Connections',
      caption: 'Reload database connections',
      execute: () => {
        // Trigger refresh by updating the widget
        widget.update();
      }
    });

    // Add commands to palette
    if (palette) {
      palette.addItem({ command: toggleCommand, category: 'JupySQL' });
      palette.addItem({ command: refreshCommand, category: 'JupySQL' });
    }

    console.log('JupySQL database browser added to sidebar');
  }
};

export default plugin;
