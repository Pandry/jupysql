(function() {
    'use strict';

    const BROWSER_CONFIG = {
        containerId: '{{container_id}}',
        connections: {{connections_json}},
        currentConnection: '{{current_connection}}'
    };

    function createTreeItem(label, icon, badge, level, hasChildren, metadata) {
        const item = document.createElement('li');
        const itemContent = document.createElement('div');
        itemContent.className = 'db-tree-item';
        itemContent.dataset.level = level;
        itemContent.dataset.type = metadata.type;

        if (metadata.type === 'connection') {
            itemContent.dataset.connectionKey = metadata.key;
        }

        if (hasChildren) {
            const expandIcon = document.createElement('span');
            expandIcon.className = 'db-tree-icon';
            expandIcon.innerHTML = '▶';
            itemContent.appendChild(expandIcon);
        } else {
            const spacer = document.createElement('span');
            spacer.style.width = '18px';
            spacer.style.display = 'inline-block';
            itemContent.appendChild(spacer);
        }

        const itemIcon = document.createElement('span');
        itemIcon.className = `db-tree-icon ${icon}`;
        itemContent.appendChild(itemIcon);

        const itemLabel = document.createElement('span');
        itemLabel.className = 'db-tree-label';
        itemLabel.textContent = label;
        itemContent.appendChild(itemLabel);

        if (badge) {
            const badgeEl = document.createElement('span');
            badgeEl.className = 'db-tree-badge';
            badgeEl.textContent = badge;
            itemContent.appendChild(badgeEl);
        }

        if (metadata.isCurrent) {
            const currentIndicator = document.createElement('span');
            currentIndicator.className = 'db-current-indicator';
            currentIndicator.innerHTML = '● active';
            itemContent.appendChild(currentIndicator);
        }

        item.appendChild(itemContent);

        if (hasChildren) {
            const childrenContainer = document.createElement('ul');
            childrenContainer.className = 'db-tree-children';
            item.appendChild(childrenContainer);

            itemContent.addEventListener('click', function(e) {
                e.stopPropagation();
                toggleTreeItem(item, metadata);
            });
        }

        return item;
    }

    function toggleTreeItem(item, metadata) {
        const childrenContainer = item.querySelector('.db-tree-children');
        const expandIcon = item.querySelector('.db-tree-icon');

        if (!childrenContainer) return;

        if (childrenContainer.classList.contains('expanded')) {
            childrenContainer.classList.remove('expanded');
            expandIcon.classList.remove('expanded');
        } else {
            childrenContainer.classList.add('expanded');
            expandIcon.classList.add('expanded');

            if (childrenContainer.children.length === 0) {
                loadChildren(childrenContainer, metadata);
            }
        }
    }

    function loadChildren(container, metadata) {
        container.innerHTML = '<li class="db-loading">Loading...</li>';

        const comm = Jupyter.notebook.kernel.comm_manager.new_comm(
            'comm_target_database_browser',
            {
                action: 'load',
                type: metadata.type,
                connection_key: metadata.connectionKey,
                schema: metadata.schema,
                table: metadata.table
            }
        );

        comm.on_msg(function(msg) {
            const data = msg.content.data;
            container.innerHTML = '';

            if (data.error) {
                const errorItem = document.createElement('li');
                errorItem.className = 'db-error';
                errorItem.textContent = data.error;
                container.appendChild(errorItem);
                return;
            }

            if (data.items && data.items.length > 0) {
                data.items.forEach(function(itemData) {
                    const childMeta = {
                        type: itemData.type,
                        connectionKey: metadata.connectionKey || itemData.key,
                        schema: itemData.schema || metadata.schema,
                        table: itemData.table || metadata.table,
                        isCurrent: itemData.is_current
                    };

                    const childItem = createTreeItem(
                        itemData.label,
                        itemData.icon,
                        itemData.badge,
                        (metadata.level || 0) + 1,
                        itemData.has_children,
                        childMeta
                    );
                    container.appendChild(childItem);
                });
            } else {
                const emptyItem = document.createElement('li');
                emptyItem.className = 'db-empty';
                emptyItem.textContent = 'No items found';
                container.appendChild(emptyItem);
            }

            comm.close();
        });

        comm.send({});
    }

    function initBrowser() {
        const container = document.getElementById(BROWSER_CONFIG.containerId);
        if (!container) return;

        const tree = document.createElement('ul');
        tree.className = 'db-tree';

        BROWSER_CONFIG.connections.forEach(function(conn) {
            const metadata = {
                type: 'connection',
                key: conn.key,
                connectionKey: conn.key,
                isCurrent: conn.is_current,
                level: 0
            };

            const connItem = createTreeItem(
                conn.label,
                'db-connection-icon',
                null,
                0,
                true,
                metadata
            );
            tree.appendChild(connItem);
        });

        container.appendChild(tree);
    }

    if (typeof Jupyter !== 'undefined' && Jupyter.notebook) {
        initBrowser();
    } else {
        document.addEventListener('DOMContentLoaded', initBrowser);
    }
})();
