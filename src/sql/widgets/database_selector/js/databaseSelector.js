(function() {
    'use strict';

    const SELECTOR_CONFIG = {
        containerId: '{{container_id}}',
        selectId: '{{select_id}}',
        buttonId: '{{button_id}}',
        statusId: '{{status_id}}',
        connections: {{connections_json}},
        currentConnection: '{{current_connection}}'
    };

    function initSelector() {
        const selectElement = document.getElementById(SELECTOR_CONFIG.selectId);
        const buttonElement = document.getElementById(SELECTOR_CONFIG.buttonId);
        const statusElement = document.getElementById(SELECTOR_CONFIG.statusId);

        if (!selectElement || !buttonElement || !statusElement) return;

        // Populate select options
        SELECTOR_CONFIG.connections.forEach(function(conn) {
            const option = document.createElement('option');
            option.value = conn.key;
            option.textContent = conn.label;

            if (conn.is_current) {
                option.selected = true;
                option.textContent += ' (current)';
            }

            selectElement.appendChild(option);
        });

        // Handle switch button click
        buttonElement.addEventListener('click', function() {
            const selectedKey = selectElement.value;

            if (!selectedKey) {
                showStatus('Please select a connection', 'error');
                return;
            }

            // Check if already current
            const selectedConn = SELECTOR_CONFIG.connections.find(
                function(c) { return c.key === selectedKey; }
            );

            if (selectedConn && selectedConn.is_current) {
                showStatus('This connection is already active', 'error');
                return;
            }

            // Disable button and show loading
            buttonElement.disabled = true;
            buttonElement.textContent = 'Switching...';
            statusElement.style.display = 'none';

            // Send switch request to kernel
            const comm = Jupyter.notebook.kernel.comm_manager.new_comm(
                'comm_target_database_selector',
                {
                    action: 'switch',
                    connection_key: selectedKey
                }
            );

            comm.on_msg(function(msg) {
                const data = msg.content.data;

                buttonElement.disabled = false;
                buttonElement.textContent = 'Switch';

                if (data.success) {
                    showStatus(
                        'Successfully switched to ' + data.connection_label,
                        'success'
                    );

                    // Update options to reflect new current connection
                    updateSelectOptions(selectedKey);
                } else {
                    showStatus(
                        'Error: ' + (data.error || 'Failed to switch connection'),
                        'error'
                    );
                }

                comm.close();
            });

            comm.send({});
        });

        function showStatus(message, type) {
            statusElement.textContent = message;
            statusElement.className = 'database-selector-status ' + type;
        }

        function updateSelectOptions(newCurrentKey) {
            Array.from(selectElement.options).forEach(function(option) {
                option.textContent = option.textContent.replace(' (current)', '');

                if (option.value === newCurrentKey) {
                    option.textContent += ' (current)';
                    option.selected = true;
                }
            });

            // Update config
            SELECTOR_CONFIG.connections.forEach(function(conn) {
                conn.is_current = (conn.key === newCurrentKey);
            });
            SELECTOR_CONFIG.currentConnection = newCurrentKey;
        }
    }

    if (typeof Jupyter !== 'undefined' && Jupyter.notebook) {
        initSelector();
    } else {
        document.addEventListener('DOMContentLoaded', initSelector);
    }
})();
