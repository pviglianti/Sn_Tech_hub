/**
 * ArtifactDetail — Reusable artifact detail + code renderer.
 *
 * Two standalone functions:
 *   ArtifactDetail.loadCode(opts)   — loads code content blocks
 *   ArtifactDetail.loadDetail(opts) — loads full field-value table + code + raw JSON
 *   ArtifactDetail.escapeHtml(str)  — HTML entity escaping
 */
window.ArtifactDetail = (function () {
    'use strict';

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function loadCode(opts) {
        if (!opts.sysClassName || !opts.sysId || !opts.instanceId) return;

        var card = document.getElementById(opts.cardId);
        var loading = opts.loadingId ? document.getElementById(opts.loadingId) : null;
        var container = document.getElementById(opts.containerId);
        if (!card || !container) return;

        var url = '/api/artifacts/' + encodeURIComponent(opts.sysClassName)
            + '/' + encodeURIComponent(opts.sysId)
            + '/code?instance_id=' + opts.instanceId;

        fetch(url, { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (loading) loading.style.display = 'none';
                if (!data || !data.has_code || !data.code_contents || !data.code_contents.length) return;

                card.classList.remove('is-hidden');
                container.innerHTML = data.code_contents.map(function (item) {
                    return '<div class="mt-075">'
                        + '<div class="info-label">' + escapeHtml(item.label) + ' <code>(' + escapeHtml(item.field) + ')</code></div>'
                        + '<pre class="code-block max-h-420">' + escapeHtml(item.content) + '</pre>'
                        + '</div>';
                }).join('');
            })
            .catch(function () {
                if (loading) loading.style.display = 'none';
            });
    }

    function loadDetail(opts) {
        if (!opts.sysClassName || !opts.sysId || !opts.instanceId) return;

        var loading = opts.loadingId ? document.getElementById(opts.loadingId) : null;
        var table = opts.tableId ? document.getElementById(opts.tableId) : null;
        var tbody = opts.bodyId ? document.getElementById(opts.bodyId) : null;
        var empty = opts.emptyId ? document.getElementById(opts.emptyId) : null;
        if (!tbody) return;

        if (loading) { loading.classList.remove('is-hidden'); loading.style.display = ''; }

        var url = '/api/artifacts/' + encodeURIComponent(opts.sysClassName)
            + '/' + encodeURIComponent(opts.sysId)
            + '?instance_id=' + opts.instanceId;

        fetch(url, { cache: 'no-store' })
            .then(function (r) {
                if (loading) loading.classList.add('is-hidden');
                if (!r.ok) throw new Error('not found');
                return r.json();
            })
            .then(function (data) {
                var fieldRows = data.field_rows || [];

                if (opts.nameId) {
                    var nameRow = fieldRows.find(function (r) { return r.field === 'name'; });
                    if (nameRow && nameRow.value) {
                        var nameEl = document.getElementById(opts.nameId);
                        if (nameEl) nameEl.textContent = nameRow.value;
                    }
                }

                if (!fieldRows.length) {
                    if (empty) empty.classList.remove('is-hidden');
                    return;
                }

                if (table) table.classList.remove('is-hidden');
                tbody.innerHTML = fieldRows.map(function (row) {
                    var val = row.value != null ? String(row.value) : '-';
                    var escaped = escapeHtml(val);
                    var isLong = val.length > 200;
                    return '<tr>'
                        + '<td><strong>' + escapeHtml(row.label) + '</strong><br><code class="text-muted-sm">' + escapeHtml(row.field) + '</code></td>'
                        + '<td>' + (isLong ? '<pre class="code-block max-h-200">' + escaped + '</pre>' : escaped) + '</td>'
                        + '</tr>';
                }).join('');

                if (opts.codeCardId && opts.codeContainerId) {
                    var codeContents = data.code_contents || [];
                    if (codeContents.length) {
                        var codeCard = document.getElementById(opts.codeCardId);
                        var codeContainer = document.getElementById(opts.codeContainerId);
                        if (codeCard && codeContainer) {
                            codeCard.classList.remove('is-hidden');
                            codeContainer.innerHTML = codeContents.map(function (item) {
                                return '<div class="mt-075">'
                                    + '<div class="info-label">' + escapeHtml(item.label) + ' <code>(' + escapeHtml(item.field) + ')</code></div>'
                                    + '<pre class="code-block max-h-420">' + escapeHtml(item.content) + '</pre>'
                                    + '</div>';
                            }).join('');
                        }
                    }
                }

                if (opts.rawJsonCardId && opts.rawJsonContentId && data.raw_json) {
                    var rawCard = document.getElementById(opts.rawJsonCardId);
                    var rawContent = document.getElementById(opts.rawJsonContentId);
                    if (rawCard && rawContent) {
                        rawCard.classList.remove('is-hidden');
                        try { rawContent.textContent = JSON.stringify(JSON.parse(data.raw_json), null, 2); }
                        catch (e) { rawContent.textContent = data.raw_json; }
                    }
                }
            })
            .catch(function () {
                if (loading) loading.classList.add('is-hidden');
                if (empty) empty.classList.remove('is-hidden');
            });
    }

    return { loadCode: loadCode, loadDetail: loadDetail, escapeHtml: escapeHtml };
})();
