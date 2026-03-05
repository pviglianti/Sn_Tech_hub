/**
 * GroupingSignalsPanel.js
 *
 * Displays engine-generated grouping signals with summary cards at top
 * and a unified DataTable below. Filterable by signal type.
 *
 * Usage:
 *   var panel = new GroupingSignalsPanel({
 *       containerId: 'groupingSignalsContainer',
 *       emptyId: 'groupingSignalsEmpty',
 *       loadingId: 'groupingSignalsLoading',
 *       metaId: 'groupingSignalsMeta',
 *       badgeId: 'groupingSignalsTabBadge',
 *       apiUrl: '/api/assessments/123/grouping-signals',
 *   });
 *   panel.refresh();
 *
 * Expected API response (P3B contract):
 *   {
 *     assessment_id: 123, scan_id: 456,
 *     signal_counts: {
 *       update_set_overlap: 0, update_set_artifact_link: 0,
 *       code_reference: 0, structural_relationship: 0,
 *       temporal_cluster: 0, naming_cluster: 0, table_colocation: 0
 *     },
 *     signals: [
 *       { type: "temporal_cluster", id: 12,
 *         label: "admin (2026-03-01T10:00 - 2026-03-01T10:40)",
 *         member_count: 7, confidence: 1.0,
 *         links: { member_result_ids: [101, 102], member_result_urls: ["/results/101"] },
 *         metadata: {}, evidence: {} }
 *     ],
 *     total_signals: 42,
 *     generated_at: "..."
 *   }
 */

/* global formatDate */

(function () {
    'use strict';

    var SIGNAL_TYPE_META = {
        update_set_overlap:      { label: 'Update Set Overlaps',      icon: '&#128260;', color: '#4a90d9' },
        update_set_artifact_link:{ label: 'Update Set Artifact Links', icon: '&#128206;', color: '#6a5acd' },
        temporal_cluster:        { label: 'Temporal Clusters',         icon: '&#128337;', color: '#d9534f' },
        naming_cluster:          { label: 'Naming Clusters',           icon: '&#128196;', color: '#5cb85c' },
        code_reference:          { label: 'Code References',           icon: '&#128279;', color: '#f0ad4e' },
        structural_relationship: { label: 'Structural Relationships',  icon: '&#128200;', color: '#5bc0de' },
        table_colocation:        { label: 'Table Co-location',         icon: '&#128451;', color: '#777'    }
    };

    function GroupingSignalsPanel(opts) {
        this.containerId = opts.containerId;
        this.emptyId = opts.emptyId;
        this.loadingId = opts.loadingId;
        this.metaId = opts.metaId || null;
        this.badgeId = opts.badgeId || null;
        this.apiUrl = opts.apiUrl;
        this._data = null;
        this._activeFilter = null;  // null = all types
    }

    // ── Public API ──────────────────────────────────────────────

    GroupingSignalsPanel.prototype.refresh = function () {
        var self = this;
        this._setLoading(true);
        this._setMeta('Loading signals...');

        fetch(this.apiUrl, { cache: 'no-store' })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                self._data = data;
                self._render(data);
                var totalSignals = data.total_signals || (data.signals || []).length;
                self._updateBadge(totalSignals);
                self._setMeta(totalSignals + ' grouping signals detected');
            })
            .catch(function (err) {
                console.error('GroupingSignalsPanel load error:', err);
                self._renderEmpty();
                self._setMeta('Failed to load grouping signals.');
            })
            .finally(function () {
                self._setLoading(false);
            });
    };

    // ── Rendering ───────────────────────────────────────────────

    GroupingSignalsPanel.prototype._render = function (data) {
        var container = document.getElementById(this.containerId);
        var empty = document.getElementById(this.emptyId);
        if (!container) return;

        var counts = data.signal_counts || {};
        var signals = data.signals || [];

        if (!signals.length) {
            container.innerHTML = '';
            if (empty) empty.style.display = 'block';
            return;
        }
        if (empty) empty.style.display = 'none';

        var html = '';

        // Summary cards
        html += '<div class="gsp-cards">';
        var types = Object.keys(SIGNAL_TYPE_META);
        for (var t = 0; t < types.length; t++) {
            var type = types[t];
            var meta = SIGNAL_TYPE_META[type];
            var count = counts[type] || 0;
            var activeClass = this._activeFilter === type ? ' gsp-card-active' : '';
            html += '<div class="gsp-card' + activeClass + '" data-signal-type="' + type + '">';
            html += '<div class="gsp-card-icon" style="color:' + meta.color + '">' + meta.icon + '</div>';
            html += '<div class="gsp-card-count">' + count + '</div>';
            html += '<div class="gsp-card-label">' + meta.label + '</div>';
            html += '</div>';
        }
        html += '</div>';

        // Filter bar
        if (this._activeFilter) {
            var activeMeta = SIGNAL_TYPE_META[this._activeFilter] || {};
            html += '<div class="gsp-filter-bar">';
            html += 'Showing: <strong>' + (activeMeta.label || this._activeFilter) + '</strong> ';
            html += '<button class="btn btn-sm btn-secondary gsp-clear-filter" type="button">Show All</button>';
            html += '</div>';
        }

        // Signals table
        var filtered = this._activeFilter
            ? signals.filter(function (s) { return s.type === this._activeFilter; }.bind(this))
            : signals;

        html += '<div class="table-scroll">';
        html += '<table class="related-table gsp-table"><thead><tr>';
        html += '<th>Type</th><th>Label</th><th>Members</th><th>Confidence</th>';
        html += '</tr></thead><tbody>';

        for (var i = 0; i < filtered.length; i++) {
            html += this._renderSignalRow(filtered[i]);
        }

        html += '</tbody></table>';
        html += '</div>';

        container.innerHTML = html;
        this._bindEvents(container);
    };

    GroupingSignalsPanel.prototype._renderSignalRow = function (signal) {
        var meta = SIGNAL_TYPE_META[signal.type] || { label: signal.type, icon: '', color: '#999' };
        var confidence = signal.confidence != null
            ? Math.round(signal.confidence * 100) + '%'
            : '-';
        var typeBadge = '<span class="gsp-type-badge" style="border-color:' + meta.color + ';color:' + meta.color + '">' +
                        meta.icon + ' ' + meta.label + '</span>';

        return '<tr>' +
            '<td>' + typeBadge + '</td>' +
            '<td>' + this._esc(signal.label || '-') + '</td>' +
            '<td>' + (signal.member_count || 0) + '</td>' +
            '<td>' + confidence + '</td>' +
            '</tr>';
    };

    GroupingSignalsPanel.prototype._renderEmpty = function () {
        var container = document.getElementById(this.containerId);
        var empty = document.getElementById(this.emptyId);
        if (container) container.innerHTML = '';
        if (empty) empty.style.display = 'block';
    };

    // ── Events ──────────────────────────────────────────────────

    GroupingSignalsPanel.prototype._bindEvents = function (container) {
        var self = this;

        // Card click → filter
        container.querySelectorAll('[data-signal-type]').forEach(function (card) {
            card.addEventListener('click', function () {
                var type = card.getAttribute('data-signal-type');
                if (self._activeFilter === type) {
                    self._activeFilter = null;  // Toggle off
                } else {
                    self._activeFilter = type;
                }
                self._render(self._data);
            });
        });

        // Clear filter button
        var clearBtn = container.querySelector('.gsp-clear-filter');
        if (clearBtn) {
            clearBtn.addEventListener('click', function () {
                self._activeFilter = null;
                self._render(self._data);
            });
        }
    };

    // ── Helpers ─────────────────────────────────────────────────

    GroupingSignalsPanel.prototype._setLoading = function (isLoading) {
        var el = document.getElementById(this.loadingId);
        if (el) el.style.display = isLoading ? 'flex' : 'none';
    };

    GroupingSignalsPanel.prototype._setMeta = function (text) {
        var el = this.metaId ? document.getElementById(this.metaId) : null;
        if (el) el.textContent = text;
    };

    GroupingSignalsPanel.prototype._updateBadge = function (count) {
        var el = this.badgeId ? document.getElementById(this.badgeId) : null;
        if (el) el.textContent = String(count);
    };

    GroupingSignalsPanel.prototype._esc = function (str) {
        if (str == null) return '';
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(String(str)));
        return div.innerHTML;
    };

    // ── Export ───────────────────────────────────────────────────

    window.GroupingSignalsPanel = GroupingSignalsPanel;
})();
