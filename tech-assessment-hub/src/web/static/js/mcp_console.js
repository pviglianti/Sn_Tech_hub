(function () {
    const templateSelect = document.getElementById('mcpTemplate');
    const requestBox = document.getElementById('mcpRequest');
    const responseBox = document.getElementById('mcpResponse');
    const sendBtn = document.getElementById('sendMcp');
    const clearBtn = document.getElementById('clearMcp');

    const capabilitiesBox = document.getElementById('capabilitiesSummary');
    const capabilitiesRefreshBtn = document.getElementById('capabilitiesRefresh');

    const adminTokenInput = document.getElementById('mcpAdminToken');
    const adminDiagnosticsBox = document.getElementById('adminDiagnostics');
    const adminDiagnosticsRefreshBtn = document.getElementById('adminDiagnosticsRefresh');

    const bridgeStatusBox = document.getElementById('bridgeStatus');
    const bridgeConfigBox = document.getElementById('bridgeConfig');
    const bridgeServerName = document.getElementById('bridgeServerName');

    const instances = Array.isArray(window.MCP_INSTANCES) ? window.MCP_INSTANCES : [];
    const defaultInstanceId = instances.length ? instances[0].id : 1;

    const templates = {
        initialize: {
            jsonrpc: '2.0',
            id: 1,
            method: 'initialize',
            params: {}
        },
        tools_list: {
            jsonrpc: '2.0',
            id: 2,
            method: 'tools/list',
            params: {}
        },
        sn_test_connection: {
            jsonrpc: '2.0',
            id: 3,
            method: 'tools/call',
            params: {
                name: 'sn_test_connection',
                arguments: {
                    instance_id: defaultInstanceId
                }
            }
        },
        sn_inventory_summary: {
            jsonrpc: '2.0',
            id: 4,
            method: 'tools/call',
            params: {
                name: 'sn_inventory_summary',
                arguments: {
                    instance_id: defaultInstanceId,
                    scope: 'global'
                }
            }
        },
        sqlite_query: {
            jsonrpc: '2.0',
            id: 5,
            method: 'tools/call',
            params: {
                name: 'sqlite_query',
                arguments: {
                    sql: 'SELECT id, name, company, connection_status FROM instance ORDER BY id DESC',
                    params: {},
                    max_rows: 50
                }
            }
        }
    };

    function adminHeaders() {
        const token = (adminTokenInput && adminTokenInput.value || '').trim();
        return token ? { 'X-MCP-Admin-Token': token } : {};
    }

    async function fetchJson(url, options, useAdminToken) {
        const opts = options ? { ...options } : {};
        const headers = { ...(opts.headers || {}) };
        if (useAdminToken) {
            Object.assign(headers, adminHeaders());
        }
        opts.headers = headers;

        let response;
        try {
            response = await fetch(url, opts);
        } catch (err) {
            return {
                ok: false,
                status: 0,
                body: {
                    success: false,
                    error: 'Failed to reach Tech Assessment Hub server.',
                    detail: String(err),
                    hint: 'If you see ERR_CONNECTION_REFUSED, the server is not running on this port. Restart the app and refresh this page.'
                }
            };
        }

        let body;
        try {
            body = await response.json();
        } catch (err) {
            body = { success: false, error: 'Invalid JSON response' };
        }
        return { ok: response.ok, status: response.status, body: body };
    }

    function loadTemplate(key) {
        const payload = templates[key] || templates.initialize;
        requestBox.value = JSON.stringify(payload, null, 2);
    }

    async function sendRequest() {
        responseBox.textContent = 'Sending...';
        let payload;
        try {
            payload = JSON.parse(requestBox.value);
        } catch (err) {
            responseBox.textContent = 'Invalid JSON payload.';
            return;
        }

        try {
            const result = await fetchJson('/mcp', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            responseBox.textContent = JSON.stringify({
                ok: result.ok,
                status: result.status,
                body: result.body
            }, null, 2);
        } catch (err) {
            responseBox.textContent = JSON.stringify({ success: false, error: String(err) }, null, 2);
        }
    }

    async function refreshCapabilities() {
        if (!capabilitiesBox) return;
        capabilitiesBox.textContent = 'Loading capabilities...';
        try {
            const [capResult, healthResult] = await Promise.all([
                fetchJson('/api/mcp/capabilities', { method: 'GET' }),
                fetchJson('/api/mcp/health', { method: 'GET' })
            ]);
            capabilitiesBox.textContent = JSON.stringify({
                capabilities: capResult.body,
                health: healthResult.body
            }, null, 2);
        } catch (err) {
            capabilitiesBox.textContent = JSON.stringify({ success: false, error: String(err) }, null, 2);
        }
    }

    async function loadAdminDiagnostics() {
        if (!adminDiagnosticsBox) return;
        adminDiagnosticsBox.textContent = 'Loading admin diagnostics...';
        const result = await fetchJson('/api/mcp/admin/diagnostics', { method: 'GET' }, true);
        adminDiagnosticsBox.textContent = JSON.stringify(result.body, null, 2);
    }

    async function loadBridgeConfig() {
        if (!bridgeConfigBox) return;
        const result = await fetchJson('/api/mcp/bridge/config', { method: 'GET' }, true);
        bridgeConfigBox.value = JSON.stringify(result.body, null, 2);
    }

    async function refreshBridgeStatus() {
        if (!bridgeStatusBox) return;
        bridgeStatusBox.textContent = 'Loading bridge status...';
        const result = await fetchJson('/api/mcp/bridge/status', { method: 'GET' }, true);
        bridgeStatusBox.textContent = JSON.stringify(result.body, null, 2);
    }

    async function bridgeAction(path, method, body) {
        const result = await fetchJson(path, {
            method: method || 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: body ? JSON.stringify(body) : undefined
        }, true);
        bridgeStatusBox.textContent = JSON.stringify(result.body, null, 2);
        await refreshBridgeStatus();
        await refreshCapabilities();
    }

    async function saveBridgeConfig() {
        if (!bridgeConfigBox) return;
        let payload;
        try {
            payload = JSON.parse(bridgeConfigBox.value || '{}');
        } catch (err) {
            bridgeStatusBox.textContent = JSON.stringify({ success: false, error: 'Invalid bridge config JSON' }, null, 2);
            return;
        }
        await bridgeAction('/api/mcp/bridge/config', 'POST', payload);
    }

    if (templateSelect) {
        templateSelect.addEventListener('change', function () {
            loadTemplate(templateSelect.value);
        });
    }
    if (sendBtn) {
        sendBtn.addEventListener('click', sendRequest);
    }
    if (clearBtn) {
        clearBtn.addEventListener('click', function () {
            requestBox.value = '';
            responseBox.textContent = 'Cleared.';
        });
    }
    if (capabilitiesRefreshBtn) {
        capabilitiesRefreshBtn.addEventListener('click', refreshCapabilities);
    }
    if (adminDiagnosticsRefreshBtn) {
        adminDiagnosticsRefreshBtn.addEventListener('click', loadAdminDiagnostics);
    }

    const bridgeRefreshBtn = document.getElementById('bridgeRefresh');
    const bridgeStartBtn = document.getElementById('bridgeStart');
    const bridgeStopBtn = document.getElementById('bridgeStop');
    const bridgeRestartBtn = document.getElementById('bridgeRestart');
    const bridgeReloadBtn = document.getElementById('bridgeReload');
    const bridgeReconnectAllBtn = document.getElementById('bridgeReconnectAll');
    const bridgeReconnectOneBtn = document.getElementById('bridgeReconnectOne');
    const bridgeSaveConfigBtn = document.getElementById('bridgeSaveConfig');

    if (bridgeRefreshBtn) bridgeRefreshBtn.addEventListener('click', refreshBridgeStatus);
    if (bridgeStartBtn) bridgeStartBtn.addEventListener('click', function () { bridgeAction('/api/mcp/bridge/start', 'POST'); });
    if (bridgeStopBtn) bridgeStopBtn.addEventListener('click', function () { bridgeAction('/api/mcp/bridge/stop', 'POST'); });
    if (bridgeRestartBtn) bridgeRestartBtn.addEventListener('click', function () { bridgeAction('/api/mcp/bridge/restart', 'POST'); });
    if (bridgeReloadBtn) bridgeReloadBtn.addEventListener('click', function () { bridgeAction('/api/mcp/bridge/reload', 'POST'); });
    if (bridgeReconnectAllBtn) bridgeReconnectAllBtn.addEventListener('click', function () { bridgeAction('/api/mcp/bridge/reconnect-all', 'POST'); });
    if (bridgeReconnectOneBtn) {
        bridgeReconnectOneBtn.addEventListener('click', function () {
            const server = (bridgeServerName && bridgeServerName.value || '').trim();
            if (!server) {
                bridgeStatusBox.textContent = JSON.stringify({ success: false, error: 'Enter server name' }, null, 2);
                return;
            }
            bridgeAction('/api/mcp/bridge/reconnect/' + encodeURIComponent(server), 'POST');
        });
    }
    if (bridgeSaveConfigBtn) bridgeSaveConfigBtn.addEventListener('click', saveBridgeConfig);

    if (templateSelect) {
        loadTemplate(templateSelect.value);
    }

    refreshCapabilities();
})();
