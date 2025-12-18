/**
 * Main sidebar component for JupySQL database browser
 */

import React, { useState, useEffect } from 'react';
import { ReactWidget } from '@jupyterlab/apputils';
import { JupyterFrontEnd } from '@jupyterlab/application';
import { DatabaseTree } from './components/DatabaseTree';
import { getAPI, IConnection } from './services/api';

/**
 * Props for DatabaseBrowserPanel
 */
interface IDatabaseBrowserPanelProps {
  app: JupyterFrontEnd;
}

/**
 * Main database browser panel component
 */
const DatabaseBrowserPanel: React.FC<IDatabaseBrowserPanelProps> = ({ app }) => {
  const [connections, setConnections] = useState<IConnection[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedConnection, setSelectedConnection] = useState<string | null>(null);
  const api = getAPI();

  /**
   * Load connections from API
   */
  const loadConnections = async () => {
    setLoading(true);
    setError(null);

    try {
      const conns = await api.getConnections();
      setConnections(conns);

      // Set selected connection to current
      const current = conns.find(c => c.is_current);
      if (current) {
        setSelectedConnection(current.key);
      }
    } catch (err) {
      console.error('Error loading connections:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to load connections';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  /**
   * Initialize - load connections on mount
   */
  useEffect(() => {
    loadConnections();
  }, []);

  /**
   * Handle connection switch
   */
  const handleConnectionSwitch = async (connectionKey: string) => {
    if (connectionKey === selectedConnection) {
      return; // Already selected
    }

    try {
      const result = await api.switchConnection(connectionKey);

      if (result.status === 'success') {
        setSelectedConnection(connectionKey);

        // Show notification
        app.commands.execute('apputils:notify', {
          message: result.message || `Switched to ${result.connection_label}`,
          type: 'success',
        });

        // Refresh connections to update UI
        await loadConnections();
      }
    } catch (err) {
      console.error('Error switching connection:', err);
      const errorMessage = err instanceof Error ? err.message : String(err);
      app.commands.execute('apputils:notify', {
        message: `Failed to switch connection: ${errorMessage}`,
        type: 'error',
      });
    }
  };

  /**
   * Handle add connection button
   */
  const handleAddConnection = () => {
    // TODO: Open connection form dialog (Phase 4)
    app.commands.execute('apputils:notify', {
      message: 'Add connection dialog coming soon!',
      type: 'info',
    });
  };

  /**
   * Handle node click in tree
   */
  const handleNodeClick = (node: any, event: React.MouseEvent) => {
    console.log('Node clicked:', node);
    // Future: handle different click actions
  };

  /**
   * Handle node context menu
   */
  const handleNodeContextMenu = (node: any, event: React.MouseEvent) => {
    console.log('Context menu:', node);
    // TODO: Show context menu (Phase 4)
  };

  /**
   * Render loading state
   */
  if (loading) {
    return (
      <div className="jp-jupysql-browser-loading">
        <div className="jp-jupysql-spinner-large">Loading...</div>
      </div>
    );
  }

  /**
   * Render error state
   */
  if (error) {
    return (
      <div className="jp-jupysql-browser-error">
        <p className="jp-jupysql-error-message">Error: {error}</p>
        <button className="jp-jupysql-button" onClick={loadConnections}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="jp-jupysql-browser">
      {/* Header with title and actions */}
      <div className="jp-jupysql-browser-header">
        <h2 className="jp-jupysql-browser-title">Database Browser</h2>
        <div className="jp-jupysql-browser-actions">
          <button
            className="jp-jupysql-icon-button"
            onClick={loadConnections}
            title="Refresh"
          >
            ⟳
          </button>
          <button
            className="jp-jupysql-icon-button"
            onClick={handleAddConnection}
            title="Add Connection"
          >
            +
          </button>
        </div>
      </div>

      {/* Connection selector dropdown */}
      {connections.length > 0 && (
        <div className="jp-jupysql-connection-selector">
          <label htmlFor="connection-select" className="jp-jupysql-label">
            Active Connection:
          </label>
          <select
            id="connection-select"
            className="jp-jupysql-select"
            value={selectedConnection || ''}
            onChange={e => handleConnectionSwitch(e.target.value)}
          >
            <option value="">-- Select Connection --</option>
            {connections.map(conn => (
              <option key={conn.key} value={conn.key}>
                {conn.alias || conn.url}
                {conn.is_current ? ' (current)' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Database tree */}
      <div className="jp-jupysql-browser-content">
        <DatabaseTree
          connections={connections}
          onNodeClick={handleNodeClick}
          onNodeContextMenu={handleNodeContextMenu}
          onRefresh={loadConnections}
        />
      </div>

      {/* Footer with info */}
      <div className="jp-jupysql-browser-footer">
        <small>{connections.length} connection(s)</small>
      </div>
    </div>
  );
};

/**
 * Widget wrapper for the database browser panel
 */
export class DatabaseBrowserWidget extends ReactWidget {
  private app: JupyterFrontEnd;

  constructor(app: JupyterFrontEnd) {
    super();
    this.app = app;
    this.id = 'jupysql-database-browser';
    this.title.label = 'Database Browser';
    this.title.caption = 'JupySQL Database Browser';
    this.title.closable = true;
    this.addClass('jp-jupysql-browser-widget');
  }

  render(): JSX.Element {
    return <DatabaseBrowserPanel app={this.app} />;
  }
}
