/**
 * DatabaseTree component - displays hierarchical database structure
 *
 * Hierarchy: Connections → Schemas → Tables → Columns
 */

import React, { useState, useCallback } from 'react';
import { LabIcon, folderIcon } from '@jupyterlab/ui-components';
import { getAPI, IConnection } from '../services/api';

/**
 * Tree node types
 */
type NodeType = 'connection' | 'schema' | 'table' | 'column';

/**
 * Tree node interface
 */
interface ITreeNode {
  id: string;
  label: string;
  type: NodeType;
  icon?: LabIcon;
  expanded?: boolean;
  loading?: boolean;
  children?: ITreeNode[];
  metadata?: any;
  badge?: string;
}

/**
 * Props for DatabaseTree component
 */
interface IDatabaseTreeProps {
  connections: IConnection[];
  onNodeClick?: (node: ITreeNode, event: React.MouseEvent) => void;
  onNodeContextMenu?: (node: ITreeNode, event: React.MouseEvent) => void;
  onRefresh?: () => void;
}

/**
 * DatabaseTree component
 */
export const DatabaseTree: React.FC<IDatabaseTreeProps> = ({
  connections,
  onNodeClick,
  onNodeContextMenu,
  onRefresh,
}) => {
  const [treeData, setTreeData] = useState<ITreeNode[]>([]);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const api = getAPI();

  // Initialize tree with connections
  React.useEffect(() => {
    const connectionNodes: ITreeNode[] = connections.map(conn => ({
      id: `conn-${conn.key}`,
      label: conn.alias || conn.url,
      type: 'connection',
      icon: folderIcon,
      expanded: false,
      children: [],
      metadata: conn,
    }));
    setTreeData(connectionNodes);
  }, [connections]);

  /**
   * Toggle node expansion
   */
  const toggleNode = useCallback(
    async (nodeId: string) => {
      const newExpanded = new Set(expandedNodes);

      if (newExpanded.has(nodeId)) {
        // Collapse
        newExpanded.delete(nodeId);
        setExpandedNodes(newExpanded);
      } else {
        // Expand and load children if needed
        newExpanded.add(nodeId);
        setExpandedNodes(newExpanded);

        // Find the node and load children
        await loadChildren(nodeId);
      }
    },
    [expandedNodes]
  );

  /**
   * Load children for a node
   */
  const loadChildren = async (nodeId: string) => {
    const node = findNode(treeData, nodeId);
    if (!node || node.children && node.children.length > 0) {
      return; // Already loaded
    }

    // Set loading state
    setTreeData(prevData => updateNode(prevData, nodeId, { loading: true }));

    try {
      let children: ITreeNode[] = [];

      if (node.type === 'connection') {
        // Load schemas
        const schemas = await api.getSchemas(node.metadata.key);
        children = schemas.map(schema => ({
          id: `${nodeId}-schema-${schema.name}`,
          label: schema.name,
          type: 'schema' as NodeType,
          icon: folderIcon,
          expanded: false,
          children: [],
          metadata: { schema: schema.name, connectionKey: node.metadata.key },
        }));
      } else if (node.type === 'schema') {
        // Load tables
        const tables = await api.getTables(
          node.metadata.connectionKey,
          node.metadata.schema
        );
        children = tables.map(table => ({
          id: `${nodeId}-table-${table.name}`,
          label: table.name,
          type: 'table' as NodeType,
          icon: folderIcon,
          expanded: false,
          children: [],
          metadata: {
            table: table.name,
            schema: node.metadata.schema,
            connectionKey: node.metadata.connectionKey,
          },
        }));
      } else if (node.type === 'table') {
        // Load columns
        const columns = await api.getColumns(
          node.metadata.connectionKey,
          node.metadata.table,
          node.metadata.schema
        );
        children = columns.map(column => ({
          id: `${nodeId}-col-${column.name}`,
          label: column.name,
          type: 'column' as NodeType,
          badge: column.type,
          metadata: {
            column: column.name,
            columnType: column.type,
            table: node.metadata.table,
            schema: node.metadata.schema,
            connectionKey: node.metadata.connectionKey,
          },
        }));
      }

      // Update node with children
      setTreeData(prevData =>
        updateNode(prevData, nodeId, {
          children,
          loading: false,
          expanded: true,
        })
      );
    } catch (error) {
      console.error('Error loading children:', error);
      const errorMessage = error instanceof Error ? error.message : String(error);
      // Add error node
      setTreeData(prevData =>
        updateNode(prevData, nodeId, {
          children: [
            {
              id: `${nodeId}-error`,
              label: `Error: ${errorMessage}`,
              type: 'column' as NodeType,
              metadata: {},
            },
          ],
          loading: false,
        })
      );
    }
  };

  /**
   * Find a node in the tree
   */
  const findNode = (nodes: ITreeNode[], nodeId: string): ITreeNode | null => {
    for (const node of nodes) {
      if (node.id === nodeId) {
        return node;
      }
      if (node.children) {
        const found = findNode(node.children, nodeId);
        if (found) {
          return found;
        }
      }
    }
    return null;
  };

  /**
   * Update a node in the tree
   */
  const updateNode = (
    nodes: ITreeNode[],
    nodeId: string,
    updates: Partial<ITreeNode>
  ): ITreeNode[] => {
    return nodes.map(node => {
      if (node.id === nodeId) {
        return { ...node, ...updates };
      }
      if (node.children) {
        return {
          ...node,
          children: updateNode(node.children, nodeId, updates),
        };
      }
      return node;
    });
  };

  /**
   * Handle node click
   */
  const handleNodeClick = (node: ITreeNode, event: React.MouseEvent) => {
    // Don't expand on right-click
    if (event.button === 2) {
      return;
    }

    if (node.type !== 'column') {
      toggleNode(node.id);
    }

    if (onNodeClick) {
      onNodeClick(node, event);
    }
  };

  /**
   * Handle context menu
   */
  const handleContextMenu = (node: ITreeNode, event: React.MouseEvent) => {
    event.preventDefault();
    if (onNodeContextMenu) {
      onNodeContextMenu(node, event);
    }
  };

  /**
   * Render a tree node
   */
  const renderNode = (node: ITreeNode, level: number = 0): JSX.Element => {
    const isExpanded = expandedNodes.has(node.id);
    const hasChildren = node.type !== 'column';
    const indentStyle = { paddingLeft: `${level * 16 + 8}px` };

    return (
      <div key={node.id} className="jp-jupysql-tree-node-container">
        <div
          className={`jp-jupysql-tree-node ${node.metadata?.is_current ? 'jp-jupysql-current-connection' : ''}`}
          style={indentStyle}
          onClick={e => handleNodeClick(node, e)}
          onContextMenu={e => handleContextMenu(node, e)}
        >
          {/* Expand/collapse arrow */}
          {hasChildren && (
            <span className="jp-jupysql-tree-arrow">
              {node.loading ? (
                <span className="jp-jupysql-spinner">⟳</span>
              ) : isExpanded ? (
                '▼'
              ) : (
                '▶'
              )}
            </span>
          )}

          {/* Icon */}
          {node.icon && (
            <node.icon.react className="jp-jupysql-tree-icon" tag="span" />
          )}

          {/* Label */}
          <span className="jp-jupysql-tree-label">{node.label}</span>

          {/* Badge (for column types) */}
          {node.badge && (
            <span className="jp-jupysql-tree-badge">{node.badge}</span>
          )}

          {/* Current connection indicator */}
          {node.metadata?.is_current && (
            <span className="jp-jupysql-current-indicator" title="Current connection">
              ●
            </span>
          )}
        </div>

        {/* Children */}
        {isExpanded && node.children && node.children.length > 0 && (
          <div className="jp-jupysql-tree-children">
            {node.children.map(child => renderNode(child, level + 1))}
          </div>
        )}
      </div>
    );
  };

  // Render empty state
  if (treeData.length === 0) {
    return (
      <div className="jp-jupysql-empty-state">
        <p>No database connections</p>
        <p className="jp-jupysql-empty-hint">
          Add a connection to get started
        </p>
      </div>
    );
  }

  return (
    <div className="jp-jupysql-tree">
      {treeData.map(node => renderNode(node))}
    </div>
  );
};
