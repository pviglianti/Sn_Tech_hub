(function () {
    var tokenInput = document.getElementById("aiSetupAdminToken");
    var scopeSelect = document.getElementById("aiSetupScope");

    var runtimeModeSelect = document.getElementById("aiRuntimeMode");
    var runtimeProviderSelect = document.getElementById("aiRuntimeProvider");
    var runtimeModelChoiceSelect = document.getElementById("aiRuntimeModelChoice");
    var runtimeCustomModelInput = document.getElementById("aiRuntimeCustomModel");
    var runtimeModelCatalogMeta = document.getElementById("aiRuntimeModelCatalogMeta");

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
    var runtimeRefreshCatalogBtn = document.getElementById("aiSetupRefreshCatalog");
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
    var instanceOptions = Array.isArray(window.AI_SETUP_INSTANCE_OPTIONS) ? window.AI_SETUP_INSTANCE_OPTIONS : [];
    var selectedInstanceId = window.AI_SETUP_SELECTED_INSTANCE_ID;

    var PROVIDER_DEFAULT_CHOICE = "__provider_default__";
    var CUSTOM_MODEL_CHOICE = "__custom_model__";
    var providerCatalogModels = [];

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

    function setRuntimeModelCatalogMeta(message) {
        if (!runtimeModelCatalogMeta) return;
        runtimeModelCatalogMeta.textContent = String(message || "");
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

    function setRuntimeModelOptions(models) {
        var options = [
            { value: PROVIDER_DEFAULT_CHOICE, label: "Provider default" },
        ];
        var seen = {};
        (Array.isArray(models) ? models : []).forEach(function (model) {
            if (!model || model.value == null) return;
            var value = String(model.value).trim();
            if (!value || value === "custom" || seen[value]) return;
            seen[value] = true;
            options.push({
                value: value,
                label: String(model.label || value),
            });
        });
        options.push({ value: CUSTOM_MODEL_CHOICE, label: "Custom model ID..." });
        populateSelect(runtimeModelChoiceSelect, options);
    }

    function syncRuntimeModelInputState() {
        if (!runtimeCustomModelInput || !runtimeModelChoiceSelect) return;
        var isCustomChoice = runtimeModelChoiceSelect.value === CUSTOM_MODEL_CHOICE;
        runtimeCustomModelInput.disabled = !isCustomChoice;
        if (isCustomChoice) {
            runtimeCustomModelInput.removeAttribute("aria-disabled");
        } else {
            runtimeCustomModelInput.setAttribute("aria-disabled", "true");
        }
    }

    function applyRuntimeModelSelection(modelValue) {
        var normalized = String(modelValue || "").trim();
        setRuntimeModelOptions(providerCatalogModels);
        if (!runtimeModelChoiceSelect) return;

        if (!normalized || normalized === "custom") {
            runtimeModelChoiceSelect.value = PROVIDER_DEFAULT_CHOICE;
            if (runtimeCustomModelInput) runtimeCustomModelInput.value = "";
            syncRuntimeModelInputState();
            return;
        }

        var optionValues = Array.from(runtimeModelChoiceSelect.options).map(function (opt) {
            return opt.value;
        });
        if (optionValues.indexOf(normalized) >= 0) {
            runtimeModelChoiceSelect.value = normalized;
            if (runtimeCustomModelInput) runtimeCustomModelInput.value = "";
        } else {
            runtimeModelChoiceSelect.value = CUSTOM_MODEL_CHOICE;
            if (runtimeCustomModelInput) runtimeCustomModelInput.value = normalized;
        }
        syncRuntimeModelInputState();
    }

    function resolveRuntimeModelValue() {
        if (!runtimeModelChoiceSelect) return "";
        if (runtimeModelChoiceSelect.value === PROVIDER_DEFAULT_CHOICE) {
            return "custom";
        }
        if (runtimeModelChoiceSelect.value === CUSTOM_MODEL_CHOICE) {
            return String(runtimeCustomModelInput && runtimeCustomModelInput.value || "").trim();
        }
        return String(runtimeModelChoiceSelect.value || "").trim();
    }

    async function refreshModelCatalog(selectedModel, suppressStatus) {
        var provider = String(runtimeProviderSelect && runtimeProviderSelect.value || "").trim();
        var modelToKeep = selectedModel == null ? resolveRuntimeModelValue() : String(selectedModel || "").trim();

        if (!provider) {
            providerCatalogModels = [];
            applyRuntimeModelSelection(modelToKeep);
            setRuntimeModelCatalogMeta("Select a provider to load provider-specific model suggestions.");
            if (!suppressStatus) {
                setStatus({ success: false, error: "Provider is required before loading model suggestions." });
            }
            return;
        }

        if (!suppressStatus) {
            setStatus({ success: true, message: "Loading model catalog...", provider: provider });
        }
        setRuntimeModelCatalogMeta("Loading provider model suggestions...");

        var url = withScope(
            "/api/integration-properties/ai-model-catalog?provider=" + encodeURIComponent(provider)
        );
        var result = await fetchJson(url, { method: "GET" }, true);

        if (result.ok && result.body) {
            providerCatalogModels = Array.isArray(result.body.models) ? result.body.models : [];
            applyRuntimeModelSelection(modelToKeep);

            var meta = "Provider-specific suggestions unavailable.";
            if (result.body.error) {
                meta = "Model suggestions unavailable: " + result.body.error;
            } else if (result.body.dynamic) {
                meta = "Loaded " + providerCatalogModels.length + " provider model suggestion";
                if (providerCatalogModels.length !== 1) {
                    meta += "s";
                }
                meta += ".";
            }
            if (result.body.timeout_seconds) {
                meta += " Timeout: " + result.body.timeout_seconds + "s.";
            }
            setRuntimeModelCatalogMeta(meta);

            if (!suppressStatus) {
                setStatus(result.body);
            }
            return;
        }

        providerCatalogModels = [];
        applyRuntimeModelSelection(modelToKeep);
        var errorMessage = (result.body && (result.body.error || result.body.detail)) || "Model catalog request failed.";
        setRuntimeModelCatalogMeta("Model suggestions unavailable: " + errorMessage);
        if (!suppressStatus) {
            setStatus(result.body);
        }
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

        selectedInstanceId = result.body.instance_id;
        if (scopeSelect) {
            scopeSelect.value = selectedInstanceId == null ? "" : String(selectedInstanceId);
        }

        await refreshModelCatalog(
            modelProp ? String(modelProp.effective_value || modelProp.default || "") : "",
            true
        );

        setStatus({
            success: true,
            message: "Runtime properties loaded.",
            scope_instance_id: selectedInstanceId,
            runtime: {
                mode: runtimeModeSelect ? runtimeModeSelect.value : null,
                provider: runtimeProviderSelect ? runtimeProviderSelect.value : null,
                model: resolveRuntimeModelValue() || null,
            },
        });
    }

    async function saveRuntime() {
        if (!runtimeModeSelect || !runtimeProviderSelect || !runtimeModelChoiceSelect) return;
        var modelValue = resolveRuntimeModelValue();
        if (!modelValue) {
            setStatus({ success: false, error: "Custom model ID is required when custom model is selected." });
            return;
        }

        var payload = {
            properties: {},
        };
        payload.properties[runtimeKeys.mode] = runtimeModeSelect.value;
        payload.properties[runtimeKeys.provider] = runtimeProviderSelect.value;
        payload.properties[runtimeKeys.model] = modelValue;

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
        if (!result.ok) {
            setStatus(result.body);
            return;
        }
        await loadRuntime();
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
    setRuntimeModelOptions([]);
    syncRuntimeModelInputState();
    initScopeOptions();
    setRuntimeModelCatalogMeta("Provider-specific suggestions load from the selected provider when available.");

    if (scopeSelect) {
        scopeSelect.addEventListener("change", loadRuntime);
    }
    if (runtimeProviderSelect) {
        runtimeProviderSelect.addEventListener("change", function () {
            refreshModelCatalog(resolveRuntimeModelValue(), true);
        });
    }
    if (runtimeModelChoiceSelect) {
        runtimeModelChoiceSelect.addEventListener("change", syncRuntimeModelInputState);
    }
    if (runtimeLoadBtn) runtimeLoadBtn.addEventListener("click", loadRuntime);
    if (runtimeSaveBtn) runtimeSaveBtn.addEventListener("click", saveRuntime);
    if (runtimeRefreshCatalogBtn) {
        runtimeRefreshCatalogBtn.addEventListener("click", function () {
            refreshModelCatalog(resolveRuntimeModelValue(), false);
        });
    }
    if (bridgeLoadBtn) bridgeLoadBtn.addEventListener("click", loadBridgeConfig);
    if (bridgeSaveBtn) bridgeSaveBtn.addEventListener("click", function () { saveBridgeConfig(false); });
    if (bridgeSaveAndStartBtn) bridgeSaveAndStartBtn.addEventListener("click", function () { saveBridgeConfig(true); });
    if (bridgeRestartBtn) bridgeRestartBtn.addEventListener("click", function () { bridgeAction("/api/mcp/bridge/restart"); });
    if (bridgeStopBtn) bridgeStopBtn.addEventListener("click", function () { bridgeAction("/api/mcp/bridge/stop"); });
    if (pipelineStartBtn) pipelineStartBtn.addEventListener("click", startPipelineStage);

    loadRuntime();
    loadBridgeConfig();
})();
