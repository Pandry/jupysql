/**
 * DatabaseTree component - displays hierarchical database structure
 *
 * Hierarchy: Connections → Schemas → Tables → Columns
 */

import React, { useState, useCallback, useRef } from 'react';
import { LabIcon, folderIcon } from '@jupyterlab/ui-components';
import { getAPI, IConnection } from '../services/api';

// ---------------------------------------------------------------------------
// Brand-inspired DB icons — recognisable shapes + official brand colours
// ---------------------------------------------------------------------------

// DuckDB: yellow circle + duck beak (the DuckDB duck logo)
const _DUCKDB_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  // body oval
  `<ellipse cx="11" cy="15" rx="8" ry="6" fill="#FFC107"/>` +
  // head circle
  `<circle cx="13" cy="9" r="5" fill="#FFC107"/>` +
  // beak pointing right
  `<path fill="#FF8F00" d="M17.5 8 L22 10 L17.5 12z"/>` +
  // eye
  `<circle cx="11.5" cy="7.5" r="1.3" fill="#1a1a1a"/>` +
  `<circle cx="11.8" cy="7.2" r="0.5" fill="white"/>` +
  `</svg>`;

// PostgreSQL: blue circle with elephant trunk + ear (the PG elephant logo)
const _PG_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  // head
  `<circle cx="13" cy="11" r="8" fill="#336791"/>` +
  // left ear
  `<ellipse cx="6" cy="9" rx="2.5" ry="3.5" fill="#336791"/>` +
  `<ellipse cx="6.5" cy="9" rx="1.5" ry="2.5" fill="#2a5676"/>` +
  // trunk hanging down-left
  `<path fill="#336791" d="M7 17 Q4 20 6 23 L8 23 Q6.5 20 9 18z"/>` +
  // eye
  `<circle cx="11" cy="9.5" r="1.5" fill="white"/>` +
  `<circle cx="11.5" cy="9.5" r="0.7" fill="#0a1f33"/>` +
  // tusk hint
  `<path stroke="white" stroke-width="1" fill="none" d="M10 15 Q12 17.5 14.5 17"/>` +
  `</svg>`;

// MySQL: blue background + orange dorsal fin (MySQL dolphin logo)
const _MYSQL_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  // dolphin body
  `<path fill="#00618A" d="M4 16 Q2 10 7 7 Q12 4 16 7 Q20 10 18 15 Q16 18 12 17 Q8 16 7 19 L5 22 Q3 19 5 17z"/>` +
  // dorsal fin in orange (MySQL brand orange)
  `<path fill="#F29111" d="M9 7 Q10 2 14 4 Q11 5.5 10 8z"/>` +
  // eye
  `<circle cx="15" cy="10" r="1" fill="white"/>` +
  `</svg>`;

// SQLite: stacked disk layers (the canonical database/SQLite look, steel blue)
const _SQLITE_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<ellipse cx="12" cy="5" rx="8" ry="2.5" fill="#0F7EC1"/>` +
  `<path fill="#0D6FAB" d="M4 5v5c0 1.38 3.58 2.5 8 2.5S20 11.38 20 10V5c-1.65.87-4.56 1.4-8 1.4S5.65 5.87 4 5z"/>` +
  `<ellipse cx="12" cy="10" rx="8" ry="2.5" fill="#0F7EC1"/>` +
  `<path fill="#0D6FAB" d="M4 10v5c0 1.38 3.58 2.5 8 2.5S20 16.38 20 15v-5c-1.65.87-4.56 1.4-8 1.4S5.65 10.87 4 10z"/>` +
  `<ellipse cx="12" cy="15" rx="8" ry="2.5" fill="#0F7EC1"/>` +
  `</svg>`;

// MSSQL: red hexagon + S-curve (SQL Server look)
const _MSSQL_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<path fill="#CC2927" d="M12 2 L20 6.5 V17.5 L12 22 L4 17.5 V6.5z"/>` +
  `<path fill="none" stroke="white" stroke-width="2" stroke-linecap="round"` +
  ` d="M15 9.5 Q15 7 12 7 Q9 7 9 9.5 Q9 12 12 12 Q15 12 15 14.5 Q15 17 12 17 Q9 17 9 14.5"/>` +
  `</svg>`;

// MariaDB: dark blue background with an S-curve similar to MySQL
const _MARIADB_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<circle cx="12" cy="12" r="10" fill="#003545"/>` +
  `<path fill="none" stroke="#C0765A" stroke-width="2.5" stroke-linecap="round"` +
  ` d="M16 9 Q12 6 8 9 Q4 12 8 15 Q12 18 16 15"/>` +
  `</svg>`;

// Oracle: red circle + white O ring (Oracle logo)
const _ORACLE_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<circle cx="12" cy="12" r="10" fill="#F80000"/>` +
  `<ellipse cx="12" cy="12" rx="7" ry="5" fill="none" stroke="white" stroke-width="2.5"/>` +
  `</svg>`;

// Generic: neutral gray cylinder
const _GENERIC_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
  `<ellipse cx="12" cy="6" rx="8" ry="2.5" fill="#616161"/>` +
  `<path fill="#505050" d="M4 6v12c0 1.38 3.58 2.5 8 2.5S20 19.38 20 18V6c-1.65.87-4.56 1.4-8 1.4S5.65 6.87 4 6z"/>` +
  `</svg>`;

const _dbIcons: Record<string, LabIcon> = {
  duckdb:   new LabIcon({ name: 'jupysql:db-duckdb',   svgstr: _DUCKDB_SVG  }),
  sqlite:   new LabIcon({ name: 'jupysql:db-sqlite',   svgstr: _SQLITE_SVG  }),
  postgres: new LabIcon({ name: 'jupysql:db-postgres', svgstr: _PG_SVG      }),
  mysql:    new LabIcon({ name: 'jupysql:db-mysql',    svgstr: _MYSQL_SVG   }),
  mariadb:  new LabIcon({ name: 'jupysql:db-mariadb',  svgstr: _MARIADB_SVG }),
  mssql:    new LabIcon({ name: 'jupysql:db-mssdb',    svgstr: _MSSQL_SVG   }),
  oracle:   new LabIcon({ name: 'jupysql:db-oracle',   svgstr: _ORACLE_SVG  }),
  generic:  new LabIcon({ name: 'jupysql:db-generic',  svgstr: _GENERIC_SVG }),
};

export function getDbIcon(url: string): LabIcon {
  const u = url.toLowerCase();
  if (u.startsWith('duckdb'))                                             return _dbIcons.duckdb;
  if (u.startsWith('sqlite'))                                             return _dbIcons.sqlite;
  if (u.startsWith('postgresql') || u.startsWith('postgres') ||
      u.startsWith('psycopg'))                                            return _dbIcons.postgres;
  if (u.startsWith('mariadb'))                                            return _dbIcons.mariadb;
  if (u.startsWith('mysql'))                                              return _dbIcons.mysql;
  if (u.startsWith('mssql') || u.startsWith('sqlserver'))                return _dbIcons.mssql;
  if (u.startsWith('oracle') || u.startsWith('cx_oracle'))               return _dbIcons.oracle;
  return _dbIcons.generic;
}

export function getDbTypeName(url: string): string {
  const u = url.toLowerCase();
  if (u.startsWith('duckdb'))                                             return 'DuckDB';
  if (u.startsWith('sqlite'))                                             return 'SQLite';
  if (u.startsWith('postgresql') || u.startsWith('postgres') ||
      u.startsWith('psycopg'))                                            return 'PostgreSQL';
  if (u.startsWith('mariadb'))                                            return 'MariaDB';
  if (u.startsWith('mysql'))                                              return 'MySQL';
  if (u.startsWith('mssql') || u.startsWith('sqlserver'))                return 'Microsoft SQL Server';
  if (u.startsWith('oracle') || u.startsWith('cx_oracle'))               return 'Oracle';
  return '';
}

// ---------------------------------------------------------------------------
// Tree types
// ---------------------------------------------------------------------------

type NodeType = 'connection' | 'schema' | 'table' | 'column';

interface ITreeNode {
  id: string;
  label: string;
  type: NodeType;
  icon?: LabIcon;
  loading?: boolean;
  children?: ITreeNode[];
  metadata?: any;
  badge?: string;
}

interface IDatabaseTreeProps {
  connections: IConnection[];
  onNodeClick?: (node: ITreeNode, event: React.MouseEvent) => void;
  onNodeContextMenu?: (node: ITreeNode, event: React.MouseEvent) => void;
  onRefresh?: () => void;
}

export const DatabaseTree: React.FC<IDatabaseTreeProps> = ({
  connections,
  onNodeClick,
  onNodeContextMenu,
}) => {
  const [treeData, setTreeData] = useState<ITreeNode[]>([]);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const api = getAPI();

  // Always keep ref in sync with latest treeData so async callbacks can read
  // the current state without stale-closure or React-18 batching issues.
  const treeDataRef = useRef<ITreeNode[]>([]);
  treeDataRef.current = treeData;

  React.useEffect(() => {
    const connectionNodes: ITreeNode[] = connections.map(conn => ({
      id: `conn-${conn.key}`,
      label: conn.alias || conn.url,
      type: 'connection',
      icon: getDbIcon(conn.url),
      metadata: conn,
    }));
    setTreeData(connectionNodes);
  }, [connections]);

  // -------------------------------------------------------------------------
  // Tree helpers
  // -------------------------------------------------------------------------

  const findNode = (nodes: ITreeNode[], nodeId: string): ITreeNode | null => {
    for (const node of nodes) {
      if (node.id === nodeId) return node;
      if (node.children) {
        const found = findNode(node.children, nodeId);
        if (found) return found;
      }
    }
    return null;
  };

  const updateNode = (
    nodes: ITreeNode[],
    nodeId: string,
    updates: Partial<ITreeNode>
  ): ITreeNode[] =>
    nodes.map(node => {
      if (node.id === nodeId) return { ...node, ...updates };
      if (node.children)
        return { ...node, children: updateNode(node.children, nodeId, updates) };
      return node;
    });

  // -------------------------------------------------------------------------
  // loadChildren
  // -------------------------------------------------------------------------
  const loadChildren = useCallback(
    async (nodeId: string) => {
      const current = findNode(treeDataRef.current, nodeId);

      if (!current) return;
      if (current.loading) return;
      if (current.children && current.children.length > 0) return;

      setTreeData(prev => updateNode(prev, nodeId, { loading: true }));

      try {
        let children: ITreeNode[] = [];

        if (current.type === 'connection') {
          const schemas = await api.getSchemas(current.metadata.key);
          children = schemas.map(schema => ({
            id: `${nodeId}-schema-${schema.name}`,
            label: schema.name,
            type: 'schema' as NodeType,
            icon: folderIcon,
            metadata: {
              schema: schema.name,
              connectionKey: current.metadata.key,
            },
          }));
        } else if (current.type === 'schema') {
          const tables = await api.getTables(
            current.metadata.connectionKey,
            current.metadata.schema
          );
          children = tables.map(table => ({
            id: `${nodeId}-table-${table.name}`,
            label: table.name,
            type: 'table' as NodeType,
            icon: folderIcon,
            metadata: {
              table: table.name,
              schema: current.metadata.schema,
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
            id: `${nodeId}-col-${column.name}`,
            label: column.name,
            type: 'column' as NodeType,
            badge: column.type,
            metadata: {
              column: column.name,
              columnType: column.type,
              table: current.metadata.table,
              schema: current.metadata.schema,
              connectionKey: current.metadata.connectionKey,
            },
          }));
        }

        setTreeData(prev =>
          updateNode(prev, nodeId, { children, loading: false })
        );
      } catch (error) {
        console.error('Error loading children:', error);
        const msg = error instanceof Error ? error.message : String(error);
        setTreeData(prev =>
          updateNode(prev, nodeId, {
            children: [
              {
                id: `${nodeId}-error`,
                label: `Error: ${msg}`,
                type: 'column' as NodeType,
                metadata: {},
              },
            ],
            loading: false,
          })
        );
      }
    },
    [api]
  );

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

  // -------------------------------------------------------------------------
  // Event handlers
  // -------------------------------------------------------------------------

  const handleRowClick = (node: ITreeNode, event: React.MouseEvent) => {
    if (event.button === 2) return;
    if (node.type === 'connection') {
      // Connection row click → open details panel; expansion via arrow only
      if (onNodeClick) onNodeClick(node, event);
    } else {
      if (node.type !== 'column') toggleNode(node.id);
      if (onNodeClick) onNodeClick(node, event);
    }
  };

  const handleArrowClick = (nodeId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    toggleNode(nodeId);
  };

  const handleContextMenu = (node: ITreeNode, event: React.MouseEvent) => {
    event.preventDefault();
    if (onNodeContextMenu) onNodeContextMenu(node, event);
  };

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  const renderNode = (node: ITreeNode, level: number = 0): JSX.Element => {
    const isExpanded = expandedNodes.has(node.id);
    const isLoading = !!node.loading;
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
          {hasChildren && (
            <span
              className="jp-jupysql-tree-arrow"
              onClick={e => handleArrowClick(node.id, e)}
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

          {node.icon && (
            <span title={node.type === 'connection' ? node.label : undefined}>
              <node.icon.react className="jp-jupysql-tree-icon" tag="span" />
            </span>
          )}

          <span className="jp-jupysql-tree-label">{node.label}</span>

          {node.badge && (
            <span className="jp-jupysql-tree-badge">{node.badge}</span>
          )}

          {node.metadata?.is_current && (
            <span
              className="jp-jupysql-current-indicator"
              title="Current connection"
            >
              ●
            </span>
          )}
        </div>

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
