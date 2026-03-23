/**
 * Main sidebar component for JupySQL database browser
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ReactWidget } from '@jupyterlab/apputils';
import { LabIcon } from '@jupyterlab/ui-components';
import { JupyterFrontEnd } from '@jupyterlab/application';
import { Menu } from '@lumino/widgets';
import { DatabaseTree, getDbIcon, getDbTypeName } from './components/DatabaseTree';
import { getAPI, IConnection, IKernel } from './services/api';

// Counter for unique temporary Lumino command IDs.
//
// Lumino context menus work by registering a temporary command with the app's
// CommandRegistry and then referencing that command's ID in the menu.  We
// append an ever-increasing number to ensure each menu item gets a unique ID,
// since registering the same ID twice throws an error.  The temporary commands
// are disposed as soon as the menu closes (see the `aboutToClose` handler below).
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
  onSave: (connection: IConnection, newUrl: string, newAlias: string) => Promise<void>;
  onDelete: (connection: IConnection) => Promise<void>;
}

const ConnectionDetailsPanel: React.FC<IConnectionDetailsPanelProps> = ({
  connection,
  onClose,
  onSwitch,
  onSave,
  onDelete,
}) => {
  const [urlValue, setUrlValue] = useState(connection.url);
  const [alias, setAlias] = useState(connection.alias || '');
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const typeName = getDbTypeName(urlValue.trim() || connection.url);
  const icon = getDbIcon(urlValue.trim() || connection.url);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose, saving]);

  const urlChanged   = urlValue.trim() !== connection.url;
  const aliasChanged = alias.trim() !== (connection.alias || '');
  const changed = urlChanged || aliasChanged;

  const handleSave = async () => {
    if (!urlValue.trim()) { setError('URL is required'); return; }
    setSaving(true);
    setError(null);
    try {
      await onSave(connection, urlValue.trim(), alias.trim());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setSaving(true);
    setError(null);
    try {
      await onDelete(connection);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
      setConfirmDelete(false);
    }
  };

  return (
    <div
      className="jp-jupysql-dialog-overlay"
      onClick={e => {
        if (e.target === e.currentTarget && !saving) onClose();
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
            disabled={saving}
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

          {/* URL (editable) */}
          <div className="jp-jupysql-form-group">
            <label className="jp-jupysql-form-label">
              URL <span className="jp-jupysql-required">*</span>
            </label>
            <input
              type="text"
              value={urlValue}
              onChange={e => setUrlValue(e.target.value)}
              placeholder="e.g. duckdb:// or postgresql://user:pass@host/db"
              className="jp-jupysql-input"
              disabled={saving}
            />
            {urlChanged && <DbTypePreview url={urlValue} />}
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

          {/* Delete confirmation prompt */}
          {confirmDelete && (
            <p className="jp-jupysql-dialog-error jp-jupysql-delete-confirm">
              Remove this connection from all kernels?
            </p>
          )}

          <div className="jp-jupysql-dialog-actions">
            {/* Delete — left-aligned */}
            {!confirmDelete ? (
              <button
                type="button"
                onClick={() => setConfirmDelete(true)}
                disabled={saving}
                className="jp-jupysql-button jp-jupysql-button-danger"
              >
                Delete
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => setConfirmDelete(false)}
                  disabled={saving}
                  className="jp-jupysql-button jp-jupysql-button-secondary"
                >
                  Keep
                </button>
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={saving}
                  className="jp-jupysql-button jp-jupysql-button-danger"
                >
                  {saving ? 'Deleting…' : 'Confirm delete'}
                </button>
              </>
            )}

            <span style={{ flex: 1 }} />

            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="jp-jupysql-button jp-jupysql-button-secondary"
            >
              Cancel
            </button>
            {!connection.is_current && !confirmDelete && (
              <button
                type="button"
                onClick={() => { onSwitch(connection.key); onClose(); }}
                disabled={saving}
                className="jp-jupysql-button jp-jupysql-button-secondary"
              >
                Switch to this
              </button>
            )}
            {!confirmDelete && (
              <button
                type="button"
                onClick={handleSave}
                disabled={saving || !changed}
                className="jp-jupysql-button"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            )}
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
  const [kernels, setKernels] = useState<IKernel[]>([]);
  const [selectedKernel, setSelectedKernel] = useState<string | null>(null);
  const api = getAPI();

  // Keep refs in sync so async callbacks always see the latest values
  const selectedConnectionRef = useRef<string | null>(null);
  const connectionsRef = useRef<IConnection[]>([]);
  const selectedKernelRef = useRef<string | null>(null);
  selectedConnectionRef.current = selectedConnection;
  connectionsRef.current = connections;
  selectedKernelRef.current = selectedKernel;

  /** Load connections from API for the selected kernel and sync selectedConnection. */
  const loadConnections = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // If a kernel is selected, load connections for that kernel only
      // Otherwise, load connections from all kernels (aggregated)
      const conns = await api.getConnections(selectedKernelRef.current ?? undefined);
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

  /** Load list of running kernels from API. */
  const loadKernels = useCallback(async () => {
    try {
      const kerns = await api.getKernels();
      setKernels(kerns);
      // If no kernel is selected yet, select the first one
      if (!selectedKernelRef.current && kerns.length > 0) {
        setSelectedKernel(kerns[0].id);
      }
      // If selected kernel no longer exists, clear or select the first available
      if (selectedKernelRef.current && !kerns.find(k => k.id === selectedKernelRef.current)) {
        setSelectedKernel(kerns.length > 0 ? kerns[0].id : null);
      }
    } catch (err) {
      console.error('Error loading kernels:', err);
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
      await loadKernels();
    })();
  }, []);

  /**
   * Re-apply the selected connection and detect the active kernel whenever the
   * active JupyterLab tab changes.
   *
   * Why: Each notebook runs in its own kernel.  A freshly-opened notebook has no
   * connections until the user runs ``%sql <url>``.  By listening to the shell's
   * ``currentChanged`` signal we automatically push the currently-selected
   * connection into any new kernel the moment the user switches to that tab,
   * so they can run ``%%sql`` queries immediately without any setup.
   *
   * Additionally, when the user switches to a different notebook, we automatically
   * update the selected kernel to match that notebook's kernel, so operations in
   * the databrowser target the correct kernel.
   */
  useEffect(() => {
    const labShell = app.shell as any;
    if (!labShell?.currentChanged) return;

    const handleCurrentChanged = async () => {
      // Detect the kernel of the currently active widget (notebook)
      const currentWidget = labShell.currentWidget;
      if (currentWidget) {
        // NotebookPanel has a sessionContext with kernel info
        const sessionContext = (currentWidget as any).sessionContext;
        if (sessionContext?.session?.kernel?.id) {
          const activeKernelId = sessionContext.session.kernel.id;
          // Only update if different from current selection
          if (activeKernelId !== selectedKernelRef.current) {
            setSelectedKernel(activeKernelId);
            // Update the ref immediately so loadConnections uses the new kernel
            selectedKernelRef.current = activeKernelId;
            // Refresh kernel list and connections for the new kernel
            await loadKernels();
            await loadConnections();
          }
        }
      }

      // Apply the selected connection to the (now active) kernel
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
  }, [api, loadKernels]);

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

  /** Switch active kernel and reload connections for that kernel */
  const handleKernelSwitch = async (kernelId: string) => {
    if (kernelId === selectedKernel) return;
    setSelectedKernel(kernelId);
    // Update the ref immediately so loadConnections uses the new kernel
    selectedKernelRef.current = kernelId;
    const kernel = kernels.find(k => k.id === kernelId);
    if (kernel) {
      app.commands.execute('apputils:notify', {
        message: `Switched to kernel: ${kernel.name}`,
        type: 'info',
      });
    }
    // Reload connections for the newly selected kernel
    await loadConnections();
  };

  /** Save URL and/or alias changes for an existing connection. */
  const handleSave = async (connection: IConnection, newUrl: string, newAlias: string) => {
    if (newUrl !== connection.url) {
      // URL changed: delete old connection, then create the new one
      await api.deleteConnection(connection.key);
    }
    await api.addConnection(newUrl, newAlias || undefined);
    await loadConnections();
    app.commands.execute('apputils:notify', {
      message: `Connection updated: ${newAlias || newUrl}`,
      type: 'success',
    });
  };

  /** Remove a connection from all kernels. */
  const handleDeleteConnection = async (connection: IConnection) => {
    await api.deleteConnection(connection.key);
    await loadConnections();
    app.commands.execute('apputils:notify', {
      message: `Removed connection: ${connection.alias || connection.url}`,
      type: 'info',
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

  /**
   * Qualify a table name with its schema when needed.
   *
   * SQL queries require the fully-qualified form ``schema.table`` when the
   * schema is not the connection's default.  The tree uses ``"(default)"`` as
   * a sentinel value for the default schema (see SchemasHandler in handlers.py),
   * so we strip it out here.
   */
  const tableRef = (schema: string, table: string): string =>
    schema && schema !== '(default)' ? `${schema}.${table}` : table;

  /**
   * Insert *codes* as new code cells into the first open notebook.
   *
   * Each string in *codes* becomes one new cell inserted below the currently
   * active cell, in order.  This is used by context-menu actions on tables and
   * columns to inject ready-to-run SQL / matplotlib snippets into the notebook.
   *
   * The notebook panel is located by checking for the presence of a ``cells``
   * model on each widget in the main area — the standard JupyterLab shape for
   * a NotebookPanel.  We activate the panel before inserting so that the
   * "insert below" command targets the right notebook.
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
      items.push(
        { label: 'Edit connection…', action: () => { if (conn) setDetailConn(conn); } },
        { divider: true },
        { label: 'Delete connection', action: async () => {
          if (conn) await handleDeleteConnection(conn);
        }},
      );

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
  }, [app, ensureConnectionActive, insertIntoNotebook, handleDeleteConnection]);

  /** Refresh both connections and kernels */
  const handleRefresh = useCallback(async () => {
    await Promise.all([loadConnections(), loadKernels()]);
  }, [loadConnections, loadKernels]);

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
        <button className="jp-jupysql-button" onClick={handleRefresh}>
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
          onSwitch={key => { handleConnectionSwitch(key); }}
          onSave={handleSave}
          onDelete={handleDeleteConnection}
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
            onClick={handleRefresh}
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

      {/* Kernel selector */}
      {kernels.length > 0 && (
        <div className="jp-jupysql-kernel-selector">
          <label htmlFor="kernel-select" className="jp-jupysql-label">
            Target kernel
          </label>
          <select
            id="kernel-select"
            className="jp-jupysql-select"
            value={selectedKernel || ''}
            onChange={e => handleKernelSwitch(e.target.value)}
          >
            <option value="">— select —</option>
            {kernels.map(kernel => (
              <option key={kernel.id} value={kernel.id}>
                {kernel.name}
                {kernel.id === selectedKernel ? ' ✓' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

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
