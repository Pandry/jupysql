/**
 * Main sidebar component for JupySQL database browser
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ReactWidget } from '@jupyterlab/apputils';
import { LabIcon } from '@jupyterlab/ui-components';
import { JupyterFrontEnd } from '@jupyterlab/application';
import { Menu } from '@lumino/widgets';
import { DatabaseTree, getDbIcon, getDbTypeName } from './components/DatabaseTree';
import { getAPI, IConnection } from './services/api';

// Counter for unique temporary command IDs
let _ctxCmdCounter = 0;

// ---------------------------------------------------------------------------
// Sidebar tab icon — a database cylinder that adapts to JupyterLab themes
// ---------------------------------------------------------------------------
const DB_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <path class="jp-icon3" fill="#616161"
    d="M12 3C7.58 3 4 4.79 4 7s3.58 4 8 4 8-1.79 8-4-3.58-4-8-4z"/>
  <path class="jp-icon3" fill="#616161"
    d="M4 9v4c0 2.21 3.59 4 8 4s8-1.79 8-4V9c-1.65 1.07-4.56 1.73-8 1.73S5.65 10.07 4 9z"/>
  <path class="jp-icon3" fill="#616161"
    d="M4 15v2c0 2.21 3.59 4 8 4s8-1.79 8-4v-2c-1.65 1.07-4.56 1.73-8 1.73S5.65 16.07 4 15z"/>
</svg>`;

export const dbIcon = new LabIcon({
  name: 'jupysql:database',
  svgstr: DB_ICON_SVG,
});

// ---------------------------------------------------------------------------
// Detected DB type preview — shown inside dialogs as the user types a URL
// ---------------------------------------------------------------------------
const DbTypePreview: React.FC<{ url: string }> = ({ url }) => {
  const typeName = getDbTypeName(url.trim());
  if (!typeName) return null;
  const icon = getDbIcon(url.trim());
  return (
    <div className="jp-jupysql-db-type-preview">
      <span className="jp-jupysql-db-type-preview-icon">
        <icon.react tag="span" className="jp-jupysql-type-icon-sm" />
      </span>
      <span className="jp-jupysql-db-type-preview-name">{typeName}</span>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Context menu items descriptor (used to build a Lumino Menu at runtime)
// ---------------------------------------------------------------------------
interface IContextMenuItem {
  label?: string;
  action?: () => void;
  divider?: boolean;
}

// ---------------------------------------------------------------------------
// "Add connection" dialog
// ---------------------------------------------------------------------------
interface IAddConnectionDialogProps {
  onConnect: (connectionString: string, alias: string) => Promise<void>;
  onCancel: () => void;
}

const AddConnectionDialog: React.FC<IAddConnectionDialogProps> = ({
  onConnect,
  onCancel,
}) => {
  const [connStr, setConnStr] = useState('');
  const [alias, setAlias] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !connecting) onCancel();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [connecting, onCancel]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!connStr.trim()) {
      setError('Connection string is required');
      return;
    }
    setConnecting(true);
    setError(null);
    try {
      await onConnect(connStr.trim(), alias.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setConnecting(false);
    }
  };

  return (
    <div
      className="jp-jupysql-dialog-overlay"
      onClick={e => {
        if (e.target === e.currentTarget && !connecting) onCancel();
      }}
    >
      <div className="jp-jupysql-dialog" role="dialog" aria-modal="true">
        <div className="jp-jupysql-dialog-header">
          <dbIcon.react tag="span" className="jp-jupysql-dialog-icon" />
          <span className="jp-jupysql-dialog-title">Add Connection</span>
          <button
            className="jp-jupysql-dialog-close"
            onClick={onCancel}
            disabled={connecting}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="jp-jupysql-dialog-body">
          <div className="jp-jupysql-form-group">
            <label className="jp-jupysql-form-label">
              Connection string <span className="jp-jupysql-required">*</span>
            </label>
            <input
              ref={inputRef}
              type="text"
              value={connStr}
              onChange={e => setConnStr(e.target.value)}
              placeholder="e.g. duckdb://  or  sqlite:///mydb.db"
              className="jp-jupysql-input"
              disabled={connecting}
            />
            <DbTypePreview url={connStr} />
          </div>

          <div className="jp-jupysql-form-group">
            <label className="jp-jupysql-form-label">
              Alias <span className="jp-jupysql-optional">(optional)</span>
            </label>
            <input
              type="text"
              value={alias}
              onChange={e => setAlias(e.target.value)}
              placeholder="e.g. mydb"
              className="jp-jupysql-input"
              disabled={connecting}
            />
          </div>

          <p className="jp-jupysql-form-hint">
            Examples: <code>duckdb://</code>, <code>sqlite:///data.db</code>,{' '}
            <code>postgresql://user:pass@host/db</code>
          </p>

          {error && (
            <p className="jp-jupysql-error-message jp-jupysql-dialog-error">
              {error}
            </p>
          )}

          <div className="jp-jupysql-dialog-actions">
            <button
              type="button"
              onClick={onCancel}
              disabled={connecting}
              className="jp-jupysql-button jp-jupysql-button-secondary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={connecting || !connStr.trim()}
              className="jp-jupysql-button"
            >
              {connecting ? 'Connecting…' : 'Connect'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Connection details / edit panel
// ---------------------------------------------------------------------------
interface IConnectionDetailsPanelProps {
  connection: IConnection;
  onClose: () => void;
  onSwitch: (key: string) => void;
  onSaveAlias: (connection: IConnection, newAlias: string) => Promise<void>;
}

const ConnectionDetailsPanel: React.FC<IConnectionDetailsPanelProps> = ({
  connection,
  onClose,
  onSwitch,
  onSaveAlias,
}) => {
  const [alias, setAlias] = useState(connection.alias || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const typeName = getDbTypeName(connection.url);
  const icon = getDbIcon(connection.url);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSaveAlias(connection, alias.trim());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  };

  const aliasChanged = alias.trim() !== (connection.alias || '');

  return (
    <div
      className="jp-jupysql-dialog-overlay"
      onClick={e => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="jp-jupysql-dialog" role="dialog" aria-modal="true">
        {/* Header */}
        <div className="jp-jupysql-dialog-header">
          <span className="jp-jupysql-conn-detail-icon">
            <icon.react tag="span" className="jp-jupysql-dialog-icon" />
          </span>
          <span className="jp-jupysql-dialog-title" title={connection.url}>
            {connection.alias || connection.url}
          </span>
          <button
            className="jp-jupysql-dialog-close"
            onClick={onClose}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="jp-jupysql-dialog-body">
          {/* DB type row */}
          {typeName && (
            <div className="jp-jupysql-conn-type-row">
              <icon.react tag="span" className="jp-jupysql-conn-type-icon" />
              <span className="jp-jupysql-conn-type-name">{typeName}</span>
              {connection.is_current && (
                <span className="jp-jupysql-conn-active-badge">active</span>
              )}
            </div>
          )}

          {/* URL (read-only) */}
          <div className="jp-jupysql-form-group">
            <label className="jp-jupysql-form-label">URL</label>
            <input
              type="text"
              value={connection.url}
              readOnly
              className="jp-jupysql-input jp-jupysql-input-readonly"
              title={connection.url}
            />
          </div>

          {/* Alias (editable) */}
          <div className="jp-jupysql-form-group">
            <label className="jp-jupysql-form-label">
              Alias <span className="jp-jupysql-optional">(optional)</span>
            </label>
            <input
              type="text"
              value={alias}
              onChange={e => setAlias(e.target.value)}
              placeholder="e.g. mydb"
              className="jp-jupysql-input"
              disabled={saving}
            />
          </div>

          {error && (
            <p className="jp-jupysql-error-message jp-jupysql-dialog-error">
              {error}
            </p>
          )}

          <div className="jp-jupysql-dialog-actions">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="jp-jupysql-button jp-jupysql-button-secondary"
            >
              Cancel
            </button>
            {!connection.is_current && (
              <button
                type="button"
                onClick={() => {
                  onSwitch(connection.key);
                  onClose();
                }}
                disabled={saving}
                className="jp-jupysql-button jp-jupysql-button-secondary"
              >
                Switch to this
              </button>
            )}
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || !aliasChanged}
              className="jp-jupysql-button"
            >
              {saving ? 'Saving…' : 'Save alias'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main panel component
// ---------------------------------------------------------------------------
interface IDatabaseBrowserPanelProps {
  app: JupyterFrontEnd;
}

const DatabaseBrowserPanel: React.FC<IDatabaseBrowserPanelProps> = ({ app }) => {
  const [connections, setConnections] = useState<IConnection[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedConnection, setSelectedConnection] = useState<string | null>(null);
  const [showDialog, setShowDialog] = useState<boolean>(false);
  const [detailConn, setDetailConn] = useState<IConnection | null>(null);
  const api = getAPI();

  // Keep refs in sync so async callbacks always see the latest values
  const selectedConnectionRef = useRef<string | null>(null);
  const connectionsRef = useRef<IConnection[]>([]);
  selectedConnectionRef.current = selectedConnection;
  connectionsRef.current = connections;

  /** Load connections from API and sync selectedConnection with kernel reality. */
  const loadConnections = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const conns = await api.getConnections();
      setConnections(conns);
      // Always sync: clear when nothing is active (e.g. after kernel restart)
      const current = conns.find(c => c.is_current);
      setSelectedConnection(current?.key ?? null);
    } catch (err) {
      console.error('Error loading connections:', err);
      setError(err instanceof Error ? err.message : 'Failed to load connections');
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    (async () => {
      try {
        await api.initExtension();
      } catch {
        // Non-fatal: extension may already be loaded or no kernel running
      }
      await loadConnections();
    })();
  }, []);

  /**
   * Re-apply the selected connection whenever the active tab changes.
   * This ensures freshly opened notebooks get the connection applied to
   * their kernel without the user having to run %sql manually.
   */
  useEffect(() => {
    const labShell = app.shell as any;
    if (!labShell?.currentChanged) return;

    const handleCurrentChanged = async () => {
      const key = selectedConnectionRef.current;
      if (!key) return;
      const conn = connectionsRef.current.find(c => c.key === key);
      if (!conn) return;
      try {
        await api.switchConnection(key, conn.url, conn.alias ?? undefined);
      } catch {
        // Non-fatal: kernel may not be ready yet
      }
    };

    labShell.currentChanged.connect(handleCurrentChanged);
    return () => labShell.currentChanged.disconnect(handleCurrentChanged);
  }, [api]);

  /** Switch active connection */
  const handleConnectionSwitch = async (connectionKey: string) => {
    if (connectionKey === selectedConnection) return;
    const conn = connections.find(c => c.key === connectionKey);
    try {
      const result = await api.switchConnection(
        connectionKey,
        conn?.url,
        conn?.alias ?? undefined
      );
      if (result.status === 'success') {
        setSelectedConnection(connectionKey);
        app.commands.execute('apputils:notify', {
          message: result.message || `Switched to ${result.connection_label}`,
          type: 'success',
        });
        await loadConnections();
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      app.commands.execute('apputils:notify', {
        message: `Failed to switch connection: ${msg}`,
        type: 'error',
      });
    }
  };

  /** Update alias by re-running %sql with the new alias */
  const handleSaveAlias = async (connection: IConnection, newAlias: string) => {
    await api.addConnection(connection.url, newAlias || undefined);
    await loadConnections();
    app.commands.execute('apputils:notify', {
      message: `Alias updated for ${newAlias || connection.url}`,
      type: 'success',
    });
  };

  // ---------------------------------------------------------------------------
  // Cell insertion helpers
  // ---------------------------------------------------------------------------

  /** Ensure connection `key` is the active one; switch if needed. */
  const ensureConnectionActive = useCallback(async (key: string): Promise<void> => {
    const conn = connectionsRef.current.find(c => c.key === key);
    if (!conn || conn.is_current) return;
    const result = await api.switchConnection(key, conn.url, conn.alias ?? undefined);
    if (result.status === 'success') {
      setSelectedConnection(key);
      await loadConnections();
    }
  }, [api, loadConnections]);

  /** Helper to qualify a table name with its schema. */
  const tableRef = (schema: string, table: string): string =>
    schema && schema !== '(default)' ? `${schema}.${table}` : table;

  /**
   * Find the first open notebook panel and insert `codes` as new code cells,
   * one after another, below the currently active cell.
   */
  const insertIntoNotebook = useCallback(async (codes: string[]): Promise<void> => {
    let nbPanel: any = null;
    for (const w of app.shell.widgets('main')) {
      if ((w as any).content?.model?.cells !== undefined) {
        nbPanel = w;
        break;
      }
    }

    if (!nbPanel) {
      app.commands.execute('apputils:notify', {
        message: 'Open a notebook first to insert the query',
        type: 'warning',
      });
      return;
    }

    // Activate the notebook so commands target it, then wait one frame
    app.shell.activateById(nbPanel.id);
    await new Promise(r => requestAnimationFrame(r));

    for (const code of codes) {
      await app.commands.execute('notebook:insert-cell-below');
      const cell = nbPanel.content?.activeCell;
      cell?.model?.sharedModel?.setSource(code);
    }
  }, [app]);

  /**
   * Build and open a native Lumino Menu for the given tree node.
   * Lumino's Menu handles its own viewport-aware positioning, so it looks and
   * behaves exactly like every other JupyterLab context menu.
   */
  const handleNodeContextMenu = useCallback((node: any, event: React.MouseEvent) => {
    event.preventDefault();

    const items: IContextMenuItem[] = [];

    if (node.type === 'connection') {
      const conn = connectionsRef.current.find(c => c.key === node.metadata?.key);
      items.push({ label: 'Edit connection…', action: () => { if (conn) setDetailConn(conn); } });

    } else if (node.type === 'table') {
      const { table = '', schema = '', connectionKey = '' } = node.metadata ?? {};
      const tref = tableRef(schema, table);
      const insertQuery = async (sql: string) => {
        await ensureConnectionActive(connectionKey);
        await insertIntoNotebook([sql]);
      };
      items.push(
        { label: 'Preview: first 10 rows',  action: () => insertQuery(`%%sql\nSELECT * FROM ${tref} LIMIT 10`) },
        { label: 'Preview: first 100 rows', action: () => insertQuery(`%%sql\nSELECT * FROM ${tref} LIMIT 100`) },
        { label: 'Row count',               action: () => insertQuery(`%%sql\nSELECT COUNT(*) FROM ${tref}`) },
      );

    } else if (node.type === 'column') {
      const { column = '', columnType = '', table = '', schema = '', connectionKey = '' } = node.metadata ?? {};
      const tref = tableRef(schema, table);
      const isNumeric = /INT|FLOAT|DOUBLE|REAL|NUMERIC|DECIMAL|NUMBER|BIGINT|SMALLINT|TINYINT/.test(
        columnType.toUpperCase()
      );

      const insertChart = async () => {
        await ensureConnectionActive(connectionKey);
        if (isNumeric) {
          await insertIntoNotebook([
            `%%sql _result <<\nSELECT ${column}\nFROM ${tref}\nWHERE ${column} IS NOT NULL\nLIMIT 10000`,
            `import matplotlib.pyplot as plt\n_result.DataFrame()['${column}'].plot.hist(\n    bins=20, figsize=(10, 5), title='${column} distribution')\nplt.tight_layout(); plt.show()`,
          ]);
        } else {
          await insertIntoNotebook([
            `%%sql _result <<\nSELECT ${column}, COUNT(*) AS n\nFROM ${tref}\nGROUP BY ${column}\nORDER BY n DESC\nLIMIT 20`,
            `import matplotlib.pyplot as plt\n_df = _result.DataFrame()\n_df.plot.barh(\n    x='${column}', y='n',\n    figsize=(10, max(4, len(_df) * 0.4)),\n    title='${column} value counts', legend=False)\nplt.tight_layout(); plt.show()`,
          ]);
        }
      };

      items.push(
        { label: 'Value counts', action: async () => {
          await ensureConnectionActive(connectionKey);
          await insertIntoNotebook([
            `%%sql\nSELECT ${column}, COUNT(*) AS n\nFROM ${tref}\nGROUP BY ${column}\nORDER BY n DESC\nLIMIT 20`,
          ]);
        }},
        { label: isNumeric ? 'Histogram chart' : 'Bar chart (value counts)', action: insertChart },
        { divider: true },
        { label: 'Null count', action: async () => {
          await ensureConnectionActive(connectionKey);
          await insertIntoNotebook([
            `%%sql\nSELECT COUNT(*) - COUNT(${column}) AS nulls,\n       COUNT(*) AS total\nFROM ${tref}`,
          ]);
        }},
        { label: 'Distinct values', action: async () => {
          await ensureConnectionActive(connectionKey);
          await insertIntoNotebook([`%%sql\nSELECT DISTINCT ${column}\nFROM ${tref}\nLIMIT 20`]);
        }},
      );
    }

    if (items.length === 0) return;

    // Build a Lumino Menu — positioned and styled by JupyterLab's own system
    const menu = new Menu({ commands: app.commands });
    const disposables: Array<{ dispose(): void }> = [];

    for (const item of items) {
      if (item.divider) {
        menu.addItem({ type: 'separator' });
        continue;
      }
      const id = `jupysql:ctx-tmp-${_ctxCmdCounter++}`;
      disposables.push(
        app.commands.addCommand(id, {
          label: item.label ?? '',
          execute: item.action ?? (() => { /* no-op */ }),
        })
      );
      menu.addItem({ command: id });
    }

    menu.aboutToClose.connect(() => {
      // Clean up temporary commands after the menu closes
      requestAnimationFrame(() => {
        menu.dispose();
        disposables.forEach(d => d.dispose());
      });
    });

    menu.open(event.clientX, event.clientY);
  }, [app, ensureConnectionActive, insertIntoNotebook]);

  /** Submit the add-connection dialog */
  const handleConnect = async (connectionString: string, alias: string) => {
    await api.addConnection(connectionString, alias || undefined);
    setShowDialog(false);
    await loadConnections();
    app.commands.execute('apputils:notify', {
      message: `Connected to ${alias || connectionString}`,
      type: 'success',
    });
  };

  /** Open connection details panel on left-click of a connection node */
  const handleNodeClick = (node: any, _event: React.MouseEvent) => {
    if (node.type === 'connection' && node.metadata) {
      const conn = connections.find(c => c.key === node.metadata.key);
      if (conn) setDetailConn(conn);
    }
  };

  if (loading) {
    return (
      <div className="jp-jupysql-browser-loading">
        <div className="jp-jupysql-spinner-large">Loading…</div>
      </div>
    );
  }

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
      {/* Add-connection dialog (modal overlay) */}
      {showDialog && (
        <AddConnectionDialog
          onConnect={handleConnect}
          onCancel={() => setShowDialog(false)}
        />
      )}

      {/* Connection details / edit panel */}
      {detailConn && (
        <ConnectionDetailsPanel
          connection={detailConn}
          onClose={() => setDetailConn(null)}
          onSwitch={key => {
            handleConnectionSwitch(key);
          }}
          onSaveAlias={handleSaveAlias}
        />
      )}

      {/* Header */}
      <div className="jp-jupysql-browser-header">
        <div className="jp-jupysql-browser-logo">
          <dbIcon.react tag="span" className="jp-jupysql-header-icon" />
          <span className="jp-jupysql-header-label">JupySQL</span>
        </div>
        <div className="jp-jupysql-browser-actions">
          <button
            className="jp-jupysql-icon-button"
            onClick={loadConnections}
            title="Refresh"
          >
            ⟳
          </button>
          <button
            className="jp-jupysql-icon-button jp-jupysql-icon-button-add"
            onClick={() => setShowDialog(true)}
            title="Add connection"
          >
            +
          </button>
        </div>
      </div>

      {/* Active connection selector */}
      {connections.length > 0 && (
        <div className="jp-jupysql-connection-selector">
          <label htmlFor="connection-select" className="jp-jupysql-label">
            Active connection
          </label>
          <select
            id="connection-select"
            className="jp-jupysql-select"
            value={selectedConnection || ''}
            onChange={e => handleConnectionSwitch(e.target.value)}
          >
            <option value="">— select —</option>
            {connections.map(conn => (
              <option key={conn.key} value={conn.key}>
                {conn.alias || conn.url}
                {conn.is_current ? ' ✓' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Tree / empty state */}
      <div className="jp-jupysql-browser-content">
        {connections.length === 0 ? (
          <div className="jp-jupysql-empty-state">
            <dbIcon.react tag="div" className="jp-jupysql-empty-icon" />
            <p>No connections yet</p>
            <p className="jp-jupysql-empty-hint">
              Click <strong>+</strong> to add a database connection.
            </p>
            <button
              className="jp-jupysql-button"
              onClick={() => setShowDialog(true)}
            >
              + Add connection
            </button>
          </div>
        ) : (
          <DatabaseTree
            connections={connections}
            onNodeClick={handleNodeClick}
            onNodeContextMenu={handleNodeContextMenu}
            onRefresh={loadConnections}
          />
        )}
      </div>

      {/* Footer */}
      <div className="jp-jupysql-browser-footer">
        <small>
          {connections.length} connection{connections.length !== 1 ? 's' : ''}
        </small>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// ReactWidget wrapper (JupyterLab panel)
// ---------------------------------------------------------------------------
export class DatabaseBrowserWidget extends ReactWidget {
  private app: JupyterFrontEnd;

  constructor(app: JupyterFrontEnd) {
    super();
    this.app = app;
    this.id = 'jupysql-database-browser';
    this.title.icon = dbIcon;
    this.title.label = '';
    this.title.caption = 'JupySQL Database Browser';
    this.title.closable = true;
    this.addClass('jp-jupysql-browser-widget');
  }

  render(): JSX.Element {
    return <DatabaseBrowserPanel app={this.app} />;
  }
}
