(function () {
    var tokenInput = document.getElementById("aiSetupAdminToken");
    var scopeSelect = document.getElementById("aiSetupScope");

    var runtimeModeSelect = document.getElementById("aiRuntimeMode");
    var runtimeProviderSelect = document.getElementById("aiRuntimeProvider");
    var runtimeModelSelect = document.getElementById("aiRuntimeModel");

    var bridgeEnabledInput = document.getElementById("aiBridgeEnabled");
    var bridgeCommandInput = document.getElementById("aiBridgeCommand");
    var bridgeArgsInput = document.getElementById("aiBridgeArgs");
    var bridgeCwdInput = document.getElementById("aiBridgeCwd");
    var bridgeRpcUrlInput = document.getElementById("aiBridgeRpcUrl");
    var bridgeMgmtUrlInput = document.getElementById("aiBridgeMgmtUrl");
    var bridgeEventUrlInput = document.getElementById("aiBridgeEventUrl");
    var bridgeHealthUrlInput = document.getElementById("aiBridgeHealthUrl");
    var bridgeEnvJsonInput = document.getElementById("aiBridgeEnvJson");

    var runtimeLoadBtn = document.getElementById("aiSetupLoadRuntime");
    var runtimeSaveBtn = document.getElementById("aiSetupSaveRuntime");
    var bridgeLoadBtn = document.getElementById("aiSetupLoadBridge");
    var bridgeSaveBtn = document.getElementById("aiSetupSaveBridge");
    var bridgeSaveAndStartBtn = document.getElementById("aiSetupSaveAndStartBridge");
    var bridgeRestartBtn = document.getElementById("aiSetupRestartBridge");
    var bridgeStopBtn = document.getElementById("aiSetupStopBridge");

    var statusBox = document.getElementById("aiSetupStatus");
    var bridgeStatusBox = document.getElementById("aiSetupBridgeStatus");

    var pipelineAssessmentIdInput = document.getElementById("aiPipelineAssessmentId");
    var pipelineTargetStageSelect = document.getElementById("aiPipelineTargetStage");
    var pipelineSkipReviewInput = document.getElementById("aiPipelineSkipReview");
    var pipelineForceInput = document.getElementById("aiPipelineForce");
    var pipelineStartBtn = document.getElementById("aiPipelineStartBtn");
    var pipelineResponseBox = document.getElementById("aiPipelineResponse");

    var runtimeKeys = window.AI_RUNTIME_KEYS || {};
    var runtimeModeOptions = Array.isArray(window.AI_RUNTIME_MODE_OPTIONS) ? window.AI_RUNTIME_MODE_OPTIONS : [];
    var runtimeProviderOptions = Array.isArray(window.AI_RUNTIME_PROVIDER_OPTIONS) ? window.AI_RUNTIME_PROVIDER_OPTIONS : [];
    var runtimeModelOptions = Array.isArray(window.AI_RUNTIME_MODEL_OPTIONS) ? window.AI_RUNTIME_MODEL_OPTIONS : [];
    var instanceOptions = Array.isArray(window.AI_SETUP_INSTANCE_OPTIONS) ? window.AI_SETUP_INSTANCE_OPTIONS : [];
    var selectedInstanceId = window.AI_SETUP_SELECTED_INSTANCE_ID;

    function setStatus(payload) {
        if (!statusBox) return;
        statusBox.textContent = JSON.stringify(payload, null, 2);
    }

    function setBridgeStatus(payload) {
        if (!bridgeStatusBox) return;
        bridgeStatusBox.textContent = JSON.stringify(payload, null, 2);
    }

    function setPipelineResponse(payload) {
        if (!pipelineResponseBox) return;
        pipelineResponseBox.textContent = JSON.stringify(payload, null, 2);
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function adminHeaders() {
        var token = (tokenInput && tokenInput.value || "").trim();
        return token ? { "X-MCP-Admin-Token": token } : {};
    }

    async function fetchJson(url, options, useAdminToken) {
        var opts = options ? Object.assign({}, options) : {};
        var headers = Object.assign({}, opts.headers || {});
        if (useAdminToken) {
            Object.assign(headers, adminHeaders());
        }
        opts.headers = headers;

        var response;
        try {
            response = await fetch(url, opts);
        } catch (err) {
            return {
                ok: false,
                status: 0,
                body: { success: false, error: String(err) },
            };
        }

        var body;
        try {
            body = await response.json();
        } catch (_err) {
            body = { success: false, error: "Invalid JSON response" };
        }
        return { ok: response.ok, status: response.status, body: body };
    }

    function selectedScopeInstanceId() {
        if (!scopeSelect || !scopeSelect.value) return null;
        var parsed = Number(scopeSelect.value);
        return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
    }

    function withScope(url) {
        var instanceId = selectedScopeInstanceId();
        if (!instanceId) return url;
        var join = url.indexOf("?") >= 0 ? "&" : "?";
        return url + join + "instance_id=" + encodeURIComponent(String(instanceId));
    }

    function populateSelect(selectEl, options) {
        if (!selectEl) return;
        var html = "";
        options.forEach(function (opt) {
            html += '<option value="' + escapeHtml(opt.value) + '">' + escapeHtml(opt.label) + "</option>";
        });
        selectEl.innerHTML = html;
    }

    function initScopeOptions() {
        if (!scopeSelect) return;
        var html = ['<option value="">Global Defaults (all instances)</option>'];
        instanceOptions.forEach(function (inst) {
            html.push(
                '<option value="' + escapeHtml(String(inst.id)) + '">' +
                escapeHtml(inst.name) + " (id " + escapeHtml(String(inst.id)) + ")" +
                "</option>"
            );
        });
        scopeSelect.innerHTML = html.join("");
        if (selectedInstanceId != null && selectedInstanceId !== "") {
            scopeSelect.value = String(selectedInstanceId);
        }
    }

    function _findProperty(properties, key) {
        if (!Array.isArray(properties)) return null;
        for (var i = 0; i < properties.length; i += 1) {
            var row = properties[i];
            if (row && row.key === key) return row;
        }
        return null;
    }

    async function loadRuntime() {
        setStatus({ success: true, message: "Loading runtime properties..." });
        var result = await fetchJson(withScope("/api/integration-properties"), { method: "GET" }, true);
        if (!result.ok) {
            setStatus(result.body);
            return;
        }
        var properties = (result.body && result.body.properties) || [];
        var modeProp = _findProperty(properties, runtimeKeys.mode);
        var providerProp = _findProperty(properties, runtimeKeys.provider);
        var modelProp = _findProperty(properties, runtimeKeys.model);

        if (modeProp && runtimeModeSelect) runtimeModeSelect.value = String(modeProp.effective_value || modeProp.default || "");
        if (providerProp && runtimeProviderSelect) runtimeProviderSelect.value = String(providerProp.effective_value || providerProp.default || "");
        if (modelProp && runtimeModelSelect) runtimeModelSelect.value = String(modelProp.effective_value || modelProp.default || "");

        selectedInstanceId = result.body.instance_id;
        if (scopeSelect) {
            scopeSelect.value = selectedInstanceId == null ? "" : String(selectedInstanceId);
        }
        setStatus({
            success: true,
            message: "Runtime properties loaded.",
            scope_instance_id: selectedInstanceId,
            runtime: {
                mode: runtimeModeSelect ? runtimeModeSelect.value : null,
                provider: runtimeProviderSelect ? runtimeProviderSelect.value : null,
                model: runtimeModelSelect ? runtimeModelSelect.value : null,
            },
        });
    }

    async function saveRuntime() {
        if (!runtimeModeSelect || !runtimeProviderSelect || !runtimeModelSelect) return;
        var payload = {
            properties: {},
        };
        payload.properties[runtimeKeys.mode] = runtimeModeSelect.value;
        payload.properties[runtimeKeys.provider] = runtimeProviderSelect.value;
        payload.properties[runtimeKeys.model] = runtimeModelSelect.value;

        setStatus({ success: true, message: "Saving runtime properties..." });
        var result = await fetchJson(
            withScope("/api/integration-properties"),
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            },
            true
        );
        setStatus(result.body);
    }

    function _splitArgs(text) {
        return String(text || "")
            .split(/\r?\n/g)
            .map(function (line) { return line.trim(); })
            .filter(function (line) { return line.length > 0; });
    }

    function _parseEnvJson() {
        var raw = (bridgeEnvJsonInput && bridgeEnvJsonInput.value || "").trim();
        if (!raw) return {};
        var parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            throw new Error("Environment JSON must be an object.");
        }
        var env = {};
        Object.keys(parsed).forEach(function (k) {
            env[String(k)] = String(parsed[k]);
        });
        return env;
    }

    async function loadBridgeConfig() {
        setStatus({ success: true, message: "Loading bridge config..." });
        var result = await fetchJson("/api/mcp/bridge/config", { method: "GET" }, true);
        if (!result.ok || !result.body || !result.body.config) {
            setStatus(result.body);
            return;
        }
        var cfg = result.body.config;
        if (bridgeEnabledInput) bridgeEnabledInput.checked = !!cfg.enabled;
        if (bridgeCommandInput) bridgeCommandInput.value = cfg.command || "";
        if (bridgeArgsInput) bridgeArgsInput.value = Array.isArray(cfg.args) ? cfg.args.join("\n") : "";
        if (bridgeCwdInput) bridgeCwdInput.value = cfg.cwd || "";
        if (bridgeRpcUrlInput) bridgeRpcUrlInput.value = cfg.rpc_url || "";
        if (bridgeMgmtUrlInput) bridgeMgmtUrlInput.value = cfg.management_base_url || "";
        if (bridgeEventUrlInput) bridgeEventUrlInput.value = cfg.event_url || "";
        if (bridgeHealthUrlInput) bridgeHealthUrlInput.value = cfg.health_url || "";
        if (bridgeEnvJsonInput) {
            var env = cfg.env && typeof cfg.env === "object" ? cfg.env : {};
            bridgeEnvJsonInput.value = Object.keys(env).length ? JSON.stringify(env, null, 2) : "";
        }

        await refreshBridgeStatus();
        setStatus({ success: true, message: "Bridge config loaded." });
    }

    function collectBridgePayload() {
        return {
            enabled: bridgeEnabledInput ? !!bridgeEnabledInput.checked : false,
            command: bridgeCommandInput ? String(bridgeCommandInput.value || "").trim() : "",
            args: bridgeArgsInput ? _splitArgs(bridgeArgsInput.value) : [],
            cwd: bridgeCwdInput ? String(bridgeCwdInput.value || "").trim() : "",
            rpc_url: bridgeRpcUrlInput ? String(bridgeRpcUrlInput.value || "").trim() : "",
            management_base_url: bridgeMgmtUrlInput ? String(bridgeMgmtUrlInput.value || "").trim() : "",
            event_url: bridgeEventUrlInput ? String(bridgeEventUrlInput.value || "").trim() : "",
            health_url: bridgeHealthUrlInput ? String(bridgeHealthUrlInput.value || "").trim() : "",
            env: _parseEnvJson(),
        };
    }

    async function saveBridgeConfig(startAfterSave) {
        var payload;
        try {
            payload = collectBridgePayload();
        } catch (err) {
            setStatus({ success: false, error: String(err) });
            return;
        }

        setStatus({ success: true, message: "Saving bridge config..." });
        var saveResult = await fetchJson(
            "/api/mcp/bridge/config",
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            },
            true
        );
        if (!saveResult.ok) {
            setStatus(saveResult.body);
            return;
        }

        if (startAfterSave) {
            var startResult = await fetchJson("/api/mcp/bridge/start", { method: "POST" }, true);
            setStatus(startResult.body);
        } else {
            setStatus(saveResult.body);
        }
        await refreshBridgeStatus();
    }

    async function bridgeAction(path) {
        var result = await fetchJson(path, { method: "POST" }, true);
        setStatus(result.body);
        await refreshBridgeStatus();
    }

    async function refreshBridgeStatus() {
        var result = await fetchJson("/api/mcp/bridge/status", { method: "GET" }, true);
        setBridgeStatus(result.body);
    }

    async function startPipelineStage() {
        var assessmentIdRaw = pipelineAssessmentIdInput ? pipelineAssessmentIdInput.value : "";
        var assessmentId = Number(assessmentIdRaw);
        if (!Number.isInteger(assessmentId) || assessmentId <= 0) {
            setPipelineResponse({ success: false, error: "Assessment ID must be a positive integer." });
            return;
        }
        var targetStage = pipelineTargetStageSelect ? pipelineTargetStageSelect.value : "";
        if (!targetStage) {
            setPipelineResponse({ success: false, error: "Target stage is required." });
            return;
        }

        var payload = {
            target_stage: targetStage,
            skip_review: !!(pipelineSkipReviewInput && pipelineSkipReviewInput.checked),
            force: !!(pipelineForceInput && pipelineForceInput.checked),
        };
        setPipelineResponse({ success: true, message: "Starting pipeline stage..." });
        var result = await fetchJson(
            "/api/assessments/" + encodeURIComponent(String(assessmentId)) + "/advance-pipeline",
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            },
            false
        );
        setPipelineResponse(result.body);
    }

    populateSelect(runtimeModeSelect, runtimeModeOptions);
    populateSelect(runtimeProviderSelect, runtimeProviderOptions);
    populateSelect(runtimeModelSelect, runtimeModelOptions);
    initScopeOptions();

    if (scopeSelect) {
        scopeSelect.addEventListener("change", loadRuntime);
    }
    if (runtimeLoadBtn) runtimeLoadBtn.addEventListener("click", loadRuntime);
    if (runtimeSaveBtn) runtimeSaveBtn.addEventListener("click", saveRuntime);
    if (bridgeLoadBtn) bridgeLoadBtn.addEventListener("click", loadBridgeConfig);
    if (bridgeSaveBtn) bridgeSaveBtn.addEventListener("click", function () { saveBridgeConfig(false); });
    if (bridgeSaveAndStartBtn) bridgeSaveAndStartBtn.addEventListener("click", function () { saveBridgeConfig(true); });
    if (bridgeRestartBtn) bridgeRestartBtn.addEventListener("click", function () { bridgeAction("/api/mcp/bridge/restart"); });
    if (bridgeStopBtn) bridgeStopBtn.addEventListener("click", function () { bridgeAction("/api/mcp/bridge/stop"); });
    if (pipelineStartBtn) pipelineStartBtn.addEventListener("click", startPipelineStage);

    loadRuntime();
    loadBridgeConfig();
})();
