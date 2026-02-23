(function () {
    var tokenInput = document.getElementById("integrationAdminToken");
    var statusBox = document.getElementById("integrationPropertiesStatus");
    var reloadBtn = document.getElementById("integrationReload");
    var saveBtn = document.getElementById("integrationSave");
    var resetBtn = document.getElementById("integrationResetDefaults");
    var sectionsContainer = document.getElementById("integrationSectionsContainer");
    var instanceScopeSelect = document.getElementById("integrationInstanceScope");

    var properties = Array.isArray(window.INTEGRATION_PROPERTIES) ? window.INTEGRATION_PROPERTIES : [];
    var sectionOrder = Array.isArray(window.INTEGRATION_SECTION_ORDER) ? window.INTEGRATION_SECTION_ORDER : [];
    var instanceOptions = Array.isArray(window.INTEGRATION_INSTANCE_OPTIONS) ? window.INTEGRATION_INSTANCE_OPTIONS : [];
    var selectedInstanceId = window.INTEGRATION_SELECTED_INSTANCE_ID;

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

    function selectedScopeInstanceId() {
        if (!instanceScopeSelect || !instanceScopeSelect.value) return null;
        var parsed = Number(instanceScopeSelect.value);
        return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
    }

    function withScope(url) {
        var instanceId = selectedScopeInstanceId();
        if (!instanceId) return url;
        var join = url.indexOf("?") >= 0 ? "&" : "?";
        return url + join + "instance_id=" + encodeURIComponent(String(instanceId));
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

        if (prop.value_type === "multiselect" && Array.isArray(prop.options)) {
            var selected = value ? value.split(",").map(function(s) { return s.trim(); }) : [];
            var maxSel = prop.max_selections || prop.options.length;
            var id = "ms-" + escapeHtml(prop.key).replace(/\./g, "-");
            var html = '<div class="multiselect-dual" data-key="' + escapeHtml(prop.key) + '" data-max="' + maxSel + '">';
            html += '<input type="hidden" class="integration-prop-input" data-key="' + escapeHtml(prop.key) + '" value="' + escapeHtml(value) + '" />';
            html += '<div style="display:flex;gap:0.5rem;align-items:flex-start;">';
            // Available list
            html += '<div style="flex:1;"><label style="font-size:0.75rem;color:var(--text-muted);">Available</label>';
            html += '<select id="' + id + '-avail" multiple size="5" style="width:100%;font-size:0.85rem;">';
            prop.options.forEach(function (opt) {
                if (selected.indexOf(opt.value) === -1) {
                    html += '<option value="' + escapeHtml(opt.value) + '">' + escapeHtml(opt.label) + '</option>';
                }
            });
            html += '</select></div>';
            // Buttons
            html += '<div style="display:flex;flex-direction:column;gap:0.25rem;padding-top:1.2rem;">';
            html += '<button type="button" class="btn btn-sm ms-add" data-target="' + id + '" title="Add">&rarr;</button>';
            html += '<button type="button" class="btn btn-sm ms-remove" data-target="' + id + '" title="Remove">&larr;</button>';
            html += '</div>';
            // Selected list
            html += '<div style="flex:1;"><label style="font-size:0.75rem;color:var(--text-muted);">Selected (max ' + maxSel + ')</label>';
            html += '<select id="' + id + '-selected" multiple size="5" style="width:100%;font-size:0.85rem;">';
            selected.forEach(function (val) {
                var lbl = val;
                prop.options.forEach(function (opt) { if (opt.value === val) lbl = opt.label; });
                html += '<option value="' + escapeHtml(val) + '">' + escapeHtml(lbl) + '</option>';
            });
            html += '</select></div>';
            html += '</div></div>';
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

    function initScopeOptions() {
        if (!instanceScopeSelect) return;

        var opts = ['<option value="">Global Defaults (all instances)</option>'];
        instanceOptions.forEach(function (inst) {
            opts.push(
                '<option value="' + escapeHtml(String(inst.id)) + '">' +
                escapeHtml(inst.name) + " (id " + escapeHtml(String(inst.id)) + ")" +
                '</option>'
            );
        });
        instanceScopeSelect.innerHTML = opts.join("");
        if (selectedInstanceId != null && selectedInstanceId !== "") {
            instanceScopeSelect.value = String(selectedInstanceId);
        }
    }

    async function reloadFromServer() {
        setStatus({ success: true, message: "Loading properties..." });
        var result = await fetchJson(withScope("/api/integration-properties"), { method: "GET" }, true);
        if (result.ok && result.body && Array.isArray(result.body.properties)) {
            properties = result.body.properties;
            selectedInstanceId = result.body.instance_id;
            renderProperties();
        }
        setStatus(result.body);
    }

    async function saveToServer() {
        var updates = collectUpdates();
        setStatus({ success: true, message: "Saving properties..." });
        var result = await fetchJson(
            withScope("/api/integration-properties"),
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ properties: updates })
            },
            true
        );
        if (result.ok && result.body && Array.isArray(result.body.properties)) {
            properties = result.body.properties;
            selectedInstanceId = result.body.instance_id;
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
    if (instanceScopeSelect) {
        instanceScopeSelect.addEventListener("change", function () {
            reloadFromServer();
        });
    }

    // Multiselect dual-list event delegation
    if (sectionsContainer) {
        sectionsContainer.addEventListener("click", function (e) {
            var btn = e.target.closest(".ms-add, .ms-remove");
            if (!btn) return;
            var targetId = btn.getAttribute("data-target");
            if (!targetId) return;
            var availEl = document.getElementById(targetId + "-avail");
            var selectedEl = document.getElementById(targetId + "-selected");
            var wrapper = btn.closest(".multiselect-dual");
            if (!availEl || !selectedEl || !wrapper) return;
            var hiddenInput = wrapper.querySelector("input.integration-prop-input");
            var maxSel = parseInt(wrapper.getAttribute("data-max") || "99", 10);

            if (btn.classList.contains("ms-add")) {
                var opts = Array.from(availEl.selectedOptions);
                if (selectedEl.options.length + opts.length > maxSel) {
                    alert("Max " + maxSel + " selections allowed.");
                    return;
                }
                opts.forEach(function (opt) {
                    selectedEl.appendChild(opt);
                });
            } else {
                Array.from(selectedEl.selectedOptions).forEach(function (opt) {
                    availEl.appendChild(opt);
                });
            }
            // Sync hidden input value
            var vals = Array.from(selectedEl.options).map(function (o) { return o.value; });
            if (hiddenInput) hiddenInput.value = vals.join(",");
        });
    }

    initScopeOptions();
    renderProperties();
})();
