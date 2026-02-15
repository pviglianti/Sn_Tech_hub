(function () {
    var tokenInput = document.getElementById("integrationAdminToken");
    var statusBox = document.getElementById("integrationPropertiesStatus");
    var reloadBtn = document.getElementById("integrationReload");
    var saveBtn = document.getElementById("integrationSave");
    var resetBtn = document.getElementById("integrationResetDefaults");
    var sectionsContainer = document.getElementById("integrationSectionsContainer");

    var properties = Array.isArray(window.INTEGRATION_PROPERTIES) ? window.INTEGRATION_PROPERTIES : [];
    var sectionOrder = Array.isArray(window.INTEGRATION_SECTION_ORDER) ? window.INTEGRATION_SECTION_ORDER : [];

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
                body: { success: false, error: String(err) }
            };
        }

        var body;
        try {
            body = await response.json();
        } catch (err) {
            body = { success: false, error: "Invalid JSON response" };
        }
        return { ok: response.ok, status: response.status, body: body };
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function groupBySection(props) {
        var groups = {};
        var order = [];
        props.forEach(function (prop) {
            var sec = prop.section || "Other";
            if (!groups[sec]) {
                groups[sec] = [];
                order.push(sec);
            }
            groups[sec].push(prop);
        });
        // Re-order using sectionOrder if available
        if (sectionOrder.length) {
            var sorted = [];
            sectionOrder.forEach(function (s) {
                if (groups[s]) sorted.push(s);
            });
            order.forEach(function (s) {
                if (sorted.indexOf(s) === -1) sorted.push(s);
            });
            order = sorted;
        }
        return { groups: groups, order: order };
    }

    function renderInputForProp(prop) {
        var value = prop.effective_value == null ? "" : String(prop.effective_value);

        if (prop.value_type === "select" && Array.isArray(prop.options)) {
            var html = '<select class="form-control integration-prop-input" data-key="' + escapeHtml(prop.key) + '">';
            prop.options.forEach(function (opt) {
                var selected = opt.value === value ? " selected" : "";
                html += '<option value="' + escapeHtml(opt.value) + '"' + selected + '>' +
                    escapeHtml(opt.label) + '</option>';
            });
            html += '</select>';
            return html;
        }

        return '<input class="form-control integration-prop-input" data-key="' +
            escapeHtml(prop.key) + '" value="' + escapeHtml(value) + '" />';
    }

    function renderProperties() {
        if (!sectionsContainer) return;
        if (!properties.length) {
            sectionsContainer.innerHTML = '<div class="card mt-1"><p>No properties found.</p></div>';
            return;
        }

        var result = groupBySection(properties);
        var html = "";

        result.order.forEach(function (sectionName) {
            var sectionProps = result.groups[sectionName];
            html += '<div class="card mt-1">';
            html += '<h2>' + escapeHtml(sectionName) + '</h2>';
            html += '<div class="table-scroll"><table class="data-table">';
            html += '<thead><tr>';
            html += '<th>Label</th><th>Value</th><th>Current Stored</th><th>Default</th><th>Description</th>';
            html += '</tr></thead><tbody>';

            sectionProps.forEach(function (prop) {
                var stored = prop.current_value == null || prop.current_value === "" ? "(default)" : prop.current_value;
                html += '<tr>';
                html += '<td><strong>' + escapeHtml(prop.label || "") + '</strong><br><code class="text-muted-plain" style="font-size:0.8em;">' + escapeHtml(prop.key) + '</code></td>';
                html += '<td>' + renderInputForProp(prop) + '</td>';
                html += '<td>' + escapeHtml(stored) + '</td>';
                html += '<td><code>' + escapeHtml(String(prop.default || "")) + '</code></td>';
                html += '<td class="text-muted-plain" style="font-size:0.9em;">' + escapeHtml(prop.description || "") + '</td>';
                html += '</tr>';
            });

            html += '</tbody></table></div></div>';
        });

        sectionsContainer.innerHTML = html;
    }

    function collectUpdates() {
        var updates = {};
        var inputs = document.querySelectorAll(".integration-prop-input");
        inputs.forEach(function (input) {
            var key = input.getAttribute("data-key");
            if (!key) return;
            updates[key] = input.value;
        });
        return updates;
    }

    function setStatus(payload) {
        if (!statusBox) return;
        statusBox.textContent = JSON.stringify(payload, null, 2);
    }

    async function reloadFromServer() {
        setStatus({ success: true, message: "Loading properties..." });
        var result = await fetchJson("/api/integration-properties", { method: "GET" }, true);
        if (result.ok && result.body && Array.isArray(result.body.properties)) {
            properties = result.body.properties;
            renderProperties();
        }
        setStatus(result.body);
    }

    async function saveToServer() {
        var updates = collectUpdates();
        setStatus({ success: true, message: "Saving properties..." });
        var result = await fetchJson(
            "/api/integration-properties",
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ properties: updates })
            },
            true
        );
        if (result.ok && result.body && Array.isArray(result.body.properties)) {
            properties = result.body.properties;
            renderProperties();
        }
        setStatus(result.body);
    }

    function resetFormDefaults() {
        properties = properties.map(function (prop) {
            return Object.assign({}, prop, { effective_value: prop.default });
        });
        renderProperties();
        setStatus({ success: true, message: "Form values reset to defaults. Click Save Changes to persist." });
    }

    if (reloadBtn) reloadBtn.addEventListener("click", reloadFromServer);
    if (saveBtn) saveBtn.addEventListener("click", saveToServer);
    if (resetBtn) resetBtn.addEventListener("click", resetFormDefaults);

    renderProperties();
})();
