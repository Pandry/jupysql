/**
 * DatabaseTree component — hierarchical database structure browser.
 *
 * Renders a tree with four levels:
 *   Connections → Schemas → Tables → Columns
 *
 * Each level is loaded lazily: child nodes are fetched from the server only
 * when the parent node is first expanded.  The tree reflects live kernel state,
 * so refreshing the sidebar re-fetches everything from the current kernel.
 */

import React, { useState, useCallback, useRef } from 'react';
import { LabIcon, folderIcon } from '@jupyterlab/ui-components';
import { getAPI, IConnection } from '../services/api';

// ---------------------------------------------------------------------------
// Database icons
//
// Each icon is an inline SVG that approximates the database's official logo
// using only simple shapes (no external assets required).  They are
// instantiated as LabIcon objects so JupyterLab can apply theme-aware CSS
// filters (e.g. inverting colours in dark mode) via the `.jp-icon*` classes.
// ---------------------------------------------------------------------------

// DuckDB: yellow oval body + circle head + orange beak (the DuckDB duck logo)
const _DUCKDB_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<ellipse cx="11" cy="15" rx="8" ry="6" fill="#FFC107"/>` +
  `<circle cx="13" cy="9" r="5" fill="#FFC107"/>` +
  `<path fill="#FF8F00" d="M17.5 8 L22 10 L17.5 12z"/>` +
  `<circle cx="11.5" cy="7.5" r="1.3" fill="#1a1a1a"/>` +
  `<circle cx="11.8" cy="7.2" r="0.5" fill="white"/>` +
  `</svg>`;

// PostgreSQL: blue circle + ear + trunk (the Postgres elephant logo)
const _PG_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<circle cx="13" cy="11" r="8" fill="#336791"/>` +
  `<ellipse cx="6" cy="9" rx="2.5" ry="3.5" fill="#336791"/>` +
  `<ellipse cx="6.5" cy="9" rx="1.5" ry="2.5" fill="#2a5676"/>` +
  `<path fill="#336791" d="M7 17 Q4 20 6 23 L8 23 Q6.5 20 9 18z"/>` +
  `<circle cx="11" cy="9.5" r="1.5" fill="white"/>` +
  `<circle cx="11.5" cy="9.5" r="0.7" fill="#0a1f33"/>` +
  `<path stroke="white" stroke-width="1" fill="none" d="M10 15 Q12 17.5 14.5 17"/>` +
  `</svg>`;

// MySQL: blue dolphin body + orange dorsal fin (MySQL brand colours)
const _MYSQL_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<path fill="#00618A" d="M4 16 Q2 10 7 7 Q12 4 16 7 Q20 10 18 15 Q16 18 12 17 Q8 16 7 19 L5 22 Q3 19 5 17z"/>` +
  `<path fill="#F29111" d="M9 7 Q10 2 14 4 Q11 5.5 10 8z"/>` +
  `<circle cx="15" cy="10" r="1" fill="white"/>` +
  `</svg>`;

// SQLite: three stacked disk layers (the canonical "database" icon, steel blue)
const _SQLITE_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<ellipse cx="12" cy="5" rx="8" ry="2.5" fill="#0F7EC1"/>` +
  `<path fill="#0D6FAB" d="M4 5v5c0 1.38 3.58 2.5 8 2.5S20 11.38 20 10V5c-1.65.87-4.56 1.4-8 1.4S5.65 5.87 4 5z"/>` +
  `<ellipse cx="12" cy="10" rx="8" ry="2.5" fill="#0F7EC1"/>` +
  `<path fill="#0D6FAB" d="M4 10v5c0 1.38 3.58 2.5 8 2.5S20 16.38 20 15v-5c-1.65.87-4.56 1.4-8 1.4S5.65 10.87 4 10z"/>` +
  `<ellipse cx="12" cy="15" rx="8" ry="2.5" fill="#0F7EC1"/>` +
  `</svg>`;

// MSSQL: red hexagon + S-curve (SQL Server logo)
const _MSSQL_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<path fill="#CC2927" d="M12 2 L20 6.5 V17.5 L12 22 L4 17.5 V6.5z"/>` +
  `<path fill="none" stroke="white" stroke-width="2" stroke-linecap="round"` +
  ` d="M15 9.5 Q15 7 12 7 Q9 7 9 9.5 Q9 12 12 12 Q15 12 15 14.5 Q15 17 12 17 Q9 17 9 14.5"/>` +
  `</svg>`;

// MariaDB: dark navy circle + copper S-curve
const _MARIADB_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<circle cx="12" cy="12" r="10" fill="#003545"/>` +
  `<path fill="none" stroke="#C0765A" stroke-width="2.5" stroke-linecap="round"` +
  ` d="M16 9 Q12 6 8 9 Q4 12 8 15 Q12 18 16 15"/>` +
  `</svg>`;

// Oracle: red circle + white ellipse ring (Oracle logo)
const _ORACLE_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<circle cx="12" cy="12" r="10" fill="#F80000"/>` +
  `<ellipse cx="12" cy="12" rx="7" ry="5" fill="none" stroke="white" stroke-width="2.5"/>` +
  `</svg>`;

// Generic fallback: neutral gray cylinder
const _GENERIC_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<ellipse cx="12" cy="6" rx="8" ry="2.5" fill="#616161"/>` +
  `<path fill="#505050" d="M4 6v12c0 1.38 3.58 2.5 8 2.5S20 19.38 20 18V6c-1.65.87-4.56 1.4-8 1.4S5.65 6.87 4 6z"/>` +
  `</svg>`;

// ---------------------------------------------------------------------------
// DB detection registry
//
// Each entry describes one database type.  Both getDbIcon() and getDbTypeName()
// are driven by this single list, so adding support for a new database only
// requires one new entry here — no need to update two parallel if/else chains.
//
// Entries are checked in order; the first matching prefix wins.
// ---------------------------------------------------------------------------

interface IDbProfile {
  /** URL prefixes that identify this database type (lowercased for matching) */
  prefixes: string[];
  /** Human-readable display name shown in the UI */
  name: string;
  /** LabIcon instance for this database */
  icon: LabIcon;
}

const DB_PROFILES: IDbProfile[] = [
  {
    prefixes: ['duckdb'],
    name:     'DuckDB',
    icon:     new LabIcon({ name: 'jupysql:db-duckdb',   svgstr: _DUCKDB_SVG  }),
  },
  {
    prefixes: ['sqlite'],
    name:     'SQLite',
    icon:     new LabIcon({ name: 'jupysql:db-sqlite',   svgstr: _SQLITE_SVG  }),
  },
  {
    prefixes: ['postgresql', 'postgres', 'psycopg'],
    name:     'PostgreSQL',
    icon:     new LabIcon({ name: 'jupysql:db-postgres', svgstr: _PG_SVG      }),
  },
  {
    prefixes: ['mariadb'],
    name:     'MariaDB',
    icon:     new LabIcon({ name: 'jupysql:db-mariadb',  svgstr: _MARIADB_SVG }),
  },
  {
    prefixes: ['mysql'],
    name:     'MySQL',
    icon:     new LabIcon({ name: 'jupysql:db-mysql',    svgstr: _MYSQL_SVG   }),
  },
  {
    prefixes: ['mssql', 'sqlserver'],
    name:     'Microsoft SQL Server',
    icon:     new LabIcon({ name: 'jupysql:db-mssql',    svgstr: _MSSQL_SVG   }),
  },
  {
    prefixes: ['oracle', 'cx_oracle'],
    name:     'Oracle',
    icon:     new LabIcon({ name: 'jupysql:db-oracle',   svgstr: _ORACLE_SVG  }),
  },
];

/** Fallback icon used when no profile matches the connection URL. */
const _GENERIC_ICON = new LabIcon({ name: 'jupysql:db-generic', svgstr: _GENERIC_SVG });

/**
 * Return the DB profile that matches *url*, or ``null`` for an unknown URL.
 *
 * Matching is based on URL scheme / driver prefix (e.g. "duckdb://",
 * "postgresql+psycopg2://").  Comparison is case-insensitive.
 */
function _detectDb(url: string): IDbProfile | null {
  const lower = url.toLowerCase();
  for (const profile of DB_PROFILES) {
    if (profile.prefixes.some(prefix => lower.startsWith(prefix))) {
      return profile;
    }
  }
  return null;
}

/** Return the LabIcon for a connection URL, falling back to a generic icon. */
export function getDbIcon(url: string): LabIcon {
  return _detectDb(url)?.icon ?? _GENERIC_ICON;
}

/** Return the human-readable database type name for a connection URL, or '' if unknown. */
export function getDbTypeName(url: string): string {
  return _detectDb(url)?.name ?? '';
}

// ---------------------------------------------------------------------------
// Tree node types
// ---------------------------------------------------------------------------

type NodeType = 'connection' | 'schema' | 'table' | 'column';

/**
 * A single node in the database tree.
 *
 * The ``metadata`` field carries node-type-specific data:
 *
 *   connection: { key, url, alias, is_current }   (mirrors IConnection)
 *   schema:     { schema: string, connectionKey: string }
 *   table:      { table: string, schema: string, connectionKey: string }
 *   column:     { column: string, columnType: string, table: string,
 *                 schema: string, connectionKey: string }
 */
interface ITreeNode {
  id:        string;
  label:     string;
  type:      NodeType;
  icon?:     LabIcon;
  /** True while the node's children are being fetched from the server. */
  loading?:  boolean;
  children?: ITreeNode[];
  /** Node-type-specific data used by context-menu actions in sidebar.tsx. */
  metadata?: any;
  /** Short text badge shown after the label (used for column types). */
  badge?:    string;
}

interface IDatabaseTreeProps {
  connections:        IConnection[];
  onNodeClick?:       (node: ITreeNode, event: React.MouseEvent) => void;
  onNodeContextMenu?: (node: ITreeNode, event: React.MouseEvent) => void;
  onRefresh?:         () => void;
}

// ---------------------------------------------------------------------------
// Pure tree-manipulation helpers
//
// These do not depend on component state, so they are defined at module level
// rather than inside the component.  This avoids re-creating them on every
// render and makes them easy to unit-test in isolation.
// ---------------------------------------------------------------------------

/**
 * Search *nodes* (and their descendants) for the node with the given *id*.
 * Returns the node, or ``null`` if not found.
 */
function findNode(nodes: ITreeNode[], nodeId: string): ITreeNode | null {
  for (const node of nodes) {
    if (node.id === nodeId) return node;
    if (node.children) {
      const found = findNode(node.children, nodeId);
      if (found) return found;
    }
  }
  return null;
}

/**
 * Return a new tree array where the node with *nodeId* has been shallowly
 * merged with *updates*.  All other nodes are returned unchanged (by
 * reference), so React's reconciler can skip re-rendering unaffected subtrees.
 */
function updateNode(
  nodes:   ITreeNode[],
  nodeId:  string,
  updates: Partial<ITreeNode>
): ITreeNode[] {
  return nodes.map(node => {
    if (node.id === nodeId) return { ...node, ...updates };
    if (node.children)
      return { ...node, children: updateNode(node.children, nodeId, updates) };
    return node;
  });
}

// ---------------------------------------------------------------------------
// DatabaseTree component
// ---------------------------------------------------------------------------

export const DatabaseTree: React.FC<IDatabaseTreeProps> = ({
  connections,
  onNodeClick,
  onNodeContextMenu,
}) => {
  const [treeData,      setTreeData]      = useState<ITreeNode[]>([]);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const api = getAPI();

  // Keep a ref in sync with the latest treeData so that async callbacks
  // (inside loadChildren) can read the current state without stale-closure
  // issues from React 18's batched state updates.
  const treeDataRef = useRef<ITreeNode[]>([]);
  treeDataRef.current = treeData;

  // Rebuild top-level connection nodes whenever the connections prop changes
  React.useEffect(() => {
    const connectionNodes: ITreeNode[] = connections.map(conn => ({
      id:       `conn-${conn.key}`,
      label:    conn.alias || conn.url,
      type:     'connection',
      icon:     getDbIcon(conn.url),
      // Pass the full connection object so sidebar.tsx can use it in dialogs
      metadata: conn,
    }));
    setTreeData(connectionNodes);
  }, [connections]);

  // ---------------------------------------------------------------------------
  // Child loading
  // ---------------------------------------------------------------------------

  /**
   * Lazily fetch and attach child nodes for *nodeId*.
   *
   * Called the first time a node is expanded.  Child types depend on parent:
   *   connection → schemas
   *   schema     → tables
   *   table      → columns
   *   column     → (leaf node, nothing to load)
   *
   * On error, a placeholder error node is inserted so the UI always shows
   * something rather than silently failing.
   */
  const loadChildren = useCallback(
    async (nodeId: string) => {
      const current = findNode(treeDataRef.current, nodeId);
      if (!current)                                    return;
      if (current.loading)                             return;
      if (current.children && current.children.length) return;

      setTreeData(prev => updateNode(prev, nodeId, { loading: true }));

      try {
        let children: ITreeNode[] = [];

        if (current.type === 'connection') {
          const schemas = await api.getSchemas(current.metadata.key);
          children = schemas.map(schema => ({
            id:       `${nodeId}-schema-${schema.name}`,
            label:    schema.name,
            type:     'schema' as NodeType,
            icon:     folderIcon,
            metadata: {
              schema:        schema.name,
              connectionKey: current.metadata.key,
            },
          }));

        } else if (current.type === 'schema') {
          const tables = await api.getTables(
            current.metadata.connectionKey,
            current.metadata.schema
          );
          children = tables.map(table => ({
            id:       `${nodeId}-table-${table.name}`,
            label:    table.name,
            type:     'table' as NodeType,
            icon:     folderIcon,
            metadata: {
              table:         table.name,
              schema:        current.metadata.schema,
              connectionKey: current.metadata.connectionKey,
            },
          }));

        } else if (current.type === 'table') {
          const columns = await api.getColumns(
            current.metadata.connectionKey,
            current.metadata.table,
            current.metadata.schema
          );
          children = columns.map(column => ({
            id:    `${nodeId}-col-${column.name}`,
            label: column.name,
            type:  'column' as NodeType,
            // Show the SQL type as a small badge after the column name
            badge: column.type,
            metadata: {
              column:        column.name,
              columnType:    column.type,
              table:         current.metadata.table,
              schema:        current.metadata.schema,
              connectionKey: current.metadata.connectionKey,
            },
          }));
        }

        setTreeData(prev => updateNode(prev, nodeId, { children, loading: false }));

      } catch (error) {
        console.error('Error loading children:', error);
        const msg = error instanceof Error ? error.message : String(error);
        // Insert an error placeholder so the user sees what went wrong
        // instead of just an empty (or stuck-loading) subtree.
        setTreeData(prev =>
          updateNode(prev, nodeId, {
            children: [{
              id:       `${nodeId}-error`,
              label:    `Error: ${msg}`,
              type:     'column' as NodeType,  // reuse column styling for the placeholder
              metadata: {},
            }],
            loading: false,
          })
        );
      }
    },
    [api]
  );

  // ---------------------------------------------------------------------------
  // Expand / collapse
  // ---------------------------------------------------------------------------

  const toggleNode = useCallback(
    async (nodeId: string) => {
      if (expandedNodes.has(nodeId)) {
        setExpandedNodes(prev => {
          const next = new Set(prev);
          next.delete(nodeId);
          return next;
        });
      } else {
        await loadChildren(nodeId);
        setExpandedNodes(prev => new Set(prev).add(nodeId));
      }
    },
    [expandedNodes, loadChildren]
  );

  // ---------------------------------------------------------------------------
  // Event handlers
  // ---------------------------------------------------------------------------

  const handleRowClick = (node: ITreeNode, event: React.MouseEvent) => {
    // Ignore right-clicks here (they are handled by onContextMenu instead)
    if (event.button === 2) return;

    // Left-click on any non-leaf node expands/collapses it
    if (node.type !== 'column') {
      toggleNode(node.id);
    }

    // Still notify the parent component for non-connection nodes
    if (node.type !== 'connection' && onNodeClick) {
      onNodeClick(node, event);
    }
  };

  const handleArrowClick = (nodeId: string, event: React.MouseEvent) => {
    // Stop propagation so clicking the arrow doesn't also trigger handleRowClick
    event.stopPropagation();
    toggleNode(nodeId);
  };

  const handleContextMenu = (node: ITreeNode, event: React.MouseEvent) => {
    event.preventDefault();
    if (onNodeContextMenu) onNodeContextMenu(node, event);
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  /**
   * Render a single tree node and (if expanded) its children recursively.
   *
   * *level* controls the left padding used to visually communicate depth.
   * Each level adds 16px so the hierarchy is visually clear even when
   * deeply nested.
   */
  const renderNode = (node: ITreeNode, level: number = 0): JSX.Element => {
    const isExpanded = expandedNodes.has(node.id);
    const isLoading  = !!node.loading;
    const hasChildren = node.type !== 'column';
    const indentStyle = { paddingLeft: `${level * 16 + 8}px` };

    return (
      <div key={node.id} className="jp-jupysql-tree-node-container">
        <div
          className={`jp-jupysql-tree-node ${
            node.metadata?.is_current ? 'jp-jupysql-current-connection' : ''
          }`}
          style={indentStyle}
          onClick={e => handleRowClick(node, e)}
          onContextMenu={e => handleContextMenu(node, e)}
        >
          {/* Expand/collapse arrow — only for non-leaf nodes */}
          {hasChildren && (
            <span
              className="jp-jupysql-tree-arrow"
              onClick={e => handleArrowClick(node.id, e)}
              aria-label={isExpanded ? 'Collapse' : 'Expand'}
            >
              {isLoading ? (
                <span className="jp-jupysql-spinner">⟳</span>
              ) : isExpanded ? (
                '▼'
              ) : (
                '▶'
              )}
            </span>
          )}

          {/* DB / folder icon */}
          {node.icon && (
            <span title={node.type === 'connection' ? node.label : undefined}>
              <node.icon.react className="jp-jupysql-tree-icon" tag="span" />
            </span>
          )}

          {/* Node label */}
          <span className="jp-jupysql-tree-label">{node.label}</span>

          {/* Type badge (shown for column nodes to display the SQL type) */}
          {node.badge && (
            <span className="jp-jupysql-tree-badge">{node.badge}</span>
          )}

          {/* Active-connection indicator dot */}
          {node.metadata?.is_current && (
            <span
              className="jp-jupysql-current-indicator"
              title="Current connection"
            >
              ●
            </span>
          )}
        </div>

        {/* Children (rendered only when the node is expanded) */}
        {isExpanded && node.children && node.children.length > 0 && (
          <div className="jp-jupysql-tree-children">
            {node.children.map(child => renderNode(child, level + 1))}
          </div>
        )}
      </div>
    );
  };

  if (treeData.length === 0) {
    return (
      <div className="jp-jupysql-empty-state">
        <p>No database connections</p>
        <p className="jp-jupysql-empty-hint">Add a connection to get started</p>
      </div>
    );
  }

  return (
    <div className="jp-jupysql-tree">
      {treeData.map(node => renderNode(node))}
    </div>
  );
};
