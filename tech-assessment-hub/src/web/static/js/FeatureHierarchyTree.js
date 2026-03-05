/**
 * FeatureHierarchyTree.js
 *
 * Expandable tree component for displaying features and their linked scan results.
 * Supports: expand/collapse, provenance badges, ungrouped bucket, lazy-loading.
 *
 * Usage:
 *   var tree = new FeatureHierarchyTree({
 *       containerId: 'featureTreeContainer',
 *       emptyId: 'featureTreeEmpty',
 *       loadingId: 'featureTreeLoading',
 *       metaId: 'featureTreeMeta',
 *       badgeId: 'featuresTabBadge',
 *       apiUrl: '/api/assessments/123/feature-hierarchy',
 *   });
 *   tree.refresh();
 *
 * Expected API response shape (P3B contract):
 *   {
 *     assessment_id: 123, scan_id: 456,
 *     features: [
 *       {
 *         id: 9, name: "Approval Workflow", description: "...",
 *         parent_id: null, member_count: 1, context_artifact_count: 1,
 *         subtree_member_count: 1, subtree_context_artifact_count: 1,
 *         members: [
 *           { scan_result: { id: 101, name: "...", table_name: "sys_script",
 *               origin_type: "modified_ootb", is_customized: true },
 *             membership_type: "primary", assignment_source: "ai",
 *             assignment_confidence: 0.91, iteration_number: 2, evidence: {} }
 *         ],
 *         context_artifacts: [
 *           { scan_result: { id: 202, name: "...", table_name: "sys_script_include",
 *               origin_type: "ootb_untouched", is_customized: false },
 *             context_type: "structural_neighbor", confidence: 0.77,
 *             iteration_number: 1, evidence: {} }
 *         ],
 *         children: []
 *       }
 *     ],
 *     ungrouped_customizations: [
 *       { app_file_class: "sys_script", count: 3,
 *         results: [{ id: 777, name: "...", table_name: "sys_script",
 *           origin_type: "net_new_customer", is_customized: true }] }
 *     ],
 *     summary: {
 *       feature_count: 4, customized_member_count: 10,
 *       context_artifact_count: 6, ungrouped_customized_count: 2
 *     },
 *     generated_at: "..."
 *   }
 */

/* global formatDate */

(function () {
    'use strict';

    function FeatureHierarchyTree(opts) {
        this.containerId = opts.containerId;
        this.emptyId = opts.emptyId;
        this.loadingId = opts.loadingId;
        this.metaId = opts.metaId || null;
        this.badgeId = opts.badgeId || null;
        this.apiUrl = opts.apiUrl;
        this.scopeAssessmentId = null;
        this.scopeScanId = null;
        this._data = null;
        this._expandedFeatures = {};  // Track expand state by feature ID
        this._expandedUngrouped = {};  // Track expand state by class
        this._deriveScopeFromApiUrl();
    }

    // ── Public API ──────────────────────────────────────────────

    FeatureHierarchyTree.prototype.refresh = function () {
        var self = this;
        this._setLoading(true);
        this._setMeta('Loading features...');

        fetch(this.apiUrl, { cache: 'no-store' })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                self._data = data;
                self._render(data);
                var summary = data.summary || {};
                self._updateBadge(summary.feature_count || 0);
                self._setMeta(
                    (summary.feature_count || 0) + ' features, ' +
                    (summary.customized_member_count || 0) + ' grouped, ' +
                    (summary.ungrouped_customized_count || 0) + ' ungrouped'
                );
            })
            .catch(function (err) {
                console.error('FeatureHierarchyTree load error:', err);
                self._renderEmpty();
                self._setMeta('Failed to load features.');
            })
            .finally(function () {
                self._setLoading(false);
            });
    };

    FeatureHierarchyTree.prototype.expandAll = function () {
        if (!this._data) return;
        var self = this;
        (this._data.features || []).forEach(function (f) { self._setExpandedRecursive(f, true); });
        Object.keys(this._expandedUngrouped).forEach(function (k) { self._expandedUngrouped[k] = true; });
        this._render(this._data);
    };

    FeatureHierarchyTree.prototype.collapseAll = function () {
        this._expandedFeatures = {};
        this._expandedUngrouped = {};
        if (this._data) this._render(this._data);
    };

    // ── Rendering ───────────────────────────────────────────────

    FeatureHierarchyTree.prototype._render = function (data) {
        var container = document.getElementById(this.containerId);
        var empty = document.getElementById(this.emptyId);
        if (!container) return;

        var features = data.features || [];
        var ungroupedList = data.ungrouped_customizations || [];
        var ungroupedTotal = 0;
        for (var u = 0; u < ungroupedList.length; u++) { ungroupedTotal += ungroupedList[u].count || 0; }

        if (!features.length && !ungroupedTotal) {
            container.innerHTML = '';
            if (empty) empty.style.display = 'block';
            return;
        }
        if (empty) empty.style.display = 'none';

        var html = '<div class="fht-tree">';

        // Toolbar
        html += '<div class="fht-toolbar">';
        html += '<button class="btn btn-sm btn-secondary fht-expand-all" type="button">Expand All</button> ';
        html += '<button class="btn btn-sm btn-secondary fht-collapse-all" type="button">Collapse All</button>';
        html += '</div>';

        // Feature nodes
        for (var i = 0; i < features.length; i++) {
            html += this._renderFeatureNode(features[i], 0);
        }

        // Ungrouped bucket
        if (ungroupedTotal > 0) {
            html += this._renderUngroupedBucket(ungroupedList, ungroupedTotal);
        }

        html += '</div>';
        container.innerHTML = html;
        this._bindTreeEvents(container);
    };

    FeatureHierarchyTree.prototype._renderFeatureNode = function (feature, depth) {
        var isExpanded = !!this._expandedFeatures[feature.id];
        var hasChildren = (feature.members && feature.members.length) ||
                          (feature.children && feature.children.length) ||
                          (feature.context_artifacts && feature.context_artifacts.length);
        var chevron = hasChildren
            ? '<span class="fht-chevron ' + (isExpanded ? 'fht-chevron-open' : '') + '">&#9654;</span>'
            : '<span class="fht-chevron fht-chevron-leaf"></span>';

        var dispositionBadge = feature.disposition
            ? '<span class="fht-badge fht-disposition-' + feature.disposition + '">' +
              feature.disposition.replace(/_/g, ' ') + '</span>'
            : '';

        var confidenceBadge = feature.confidence_score != null
            ? '<span class="fht-badge fht-confidence">' +
              Math.round(feature.confidence_score * 100) + '%</span>'
            : '';

        var memberCount = feature.member_count || (feature.members ? feature.members.length : 0);

        var html = '<div class="fht-node fht-depth-' + depth + '" data-feature-id="' + feature.id + '">';
        html += '<div class="fht-node-header" data-toggle-feature="' + feature.id + '">';
        html += chevron;
        html += '<span class="fht-node-icon">&#128230;</span> ';
        html += '<a href="/features/' + feature.id + '" class="fht-node-name" onclick="event.stopPropagation()">';
        html += this._esc(feature.name) + '</a>';
        html += ' <a href="' + this._esc(this._buildGraphHref({ featureId: feature.id })) + '" onclick="event.stopPropagation()" target="_blank" rel="noopener noreferrer" style="font-size:0.75rem;">Graph</a>';
        html += ' <span class="fht-count">(' + memberCount + ')</span>';
        html += dispositionBadge;
        html += confidenceBadge;
        if (feature.pass_number) {
            html += '<span class="fht-badge fht-pass">Pass ' + feature.pass_number + '</span>';
        }
        html += '</div>';

        // Expanded content
        if (isExpanded && hasChildren) {
            html += '<div class="fht-node-body">';

            // AI Summary
            if (feature.ai_summary) {
                html += '<div class="fht-summary">' + this._esc(feature.ai_summary) + '</div>';
            }

            // Members (customized records)
            if (feature.members && feature.members.length) {
                html += '<div class="fht-section">';
                html += '<div class="fht-section-label">Customized Members</div>';
                html += '<table class="related-table fht-members-table"><thead><tr>';
                html += '<th>Name</th><th>Class</th><th>Origin</th><th>Source</th><th>Confidence</th>';
                html += '</tr></thead><tbody>';
                for (var m = 0; m < feature.members.length; m++) {
                    html += this._renderMemberRow(feature.members[m]);
                }
                html += '</tbody></table>';
                html += '</div>';
            }

            // Context artifacts (non-customized supporting evidence)
            if (feature.context_artifacts && feature.context_artifacts.length) {
                html += '<div class="fht-section">';
                html += '<div class="fht-section-label">Supporting Context</div>';
                html += '<table class="related-table fht-context-table"><thead><tr>';
                html += '<th>Name</th><th>Class</th><th>Context Type</th><th>Confidence</th>';
                html += '</tr></thead><tbody>';
                for (var c = 0; c < feature.context_artifacts.length; c++) {
                    html += this._renderContextRow(feature.context_artifacts[c]);
                }
                html += '</tbody></table>';
                html += '</div>';
            }

            // OOTB Recommendations
            if (feature.recommendations && feature.recommendations.length) {
                html += '<div class="fht-section">';
                html += '<div class="fht-section-label">OOTB Recommendations</div>';
                for (var r = 0; r < feature.recommendations.length; r++) {
                    html += this._renderRecommendationCard(feature.recommendations[r]);
                }
                html += '</div>';
            }

            // Child features (recursive)
            if (feature.children && feature.children.length) {
                for (var ch = 0; ch < feature.children.length; ch++) {
                    html += this._renderFeatureNode(feature.children[ch], depth + 1);
                }
            }

            html += '</div>'; // fht-node-body
        }

        html += '</div>'; // fht-node
        return html;
    };

    FeatureHierarchyTree.prototype._renderMemberRow = function (member) {
        var sr = member.scan_result || {};
        var graphHref = sr.id ? this._buildGraphHref({ resultId: sr.id }) : '#';
        var originClass = sr.origin_type ? 'origin-' + sr.origin_type : '';
        var origin = sr.origin_type
            ? '<span class="origin-badge ' + originClass + '">' +
              (sr.origin_type || '').replace(/_/g, ' ') + '</span>'
            : '-';
        var sourceBadge = member.assignment_source
            ? '<span class="fht-badge fht-source-' + member.assignment_source + '">' +
              member.assignment_source + '</span>'
            : '-';
        var confidence = member.assignment_confidence != null
            ? Math.round(member.assignment_confidence * 100) + '%'
            : '-';

        return '<tr>' +
            '<td><a href="/results/' + (sr.id || '') + '">' +
            this._esc(sr.name || '-') + '</a>' +
            ' <a href="' + this._esc(graphHref) + '" target="_blank" rel="noopener noreferrer" style="font-size:0.75rem;">Graph</a></td>' +
            '<td><code>' + this._esc(sr.table_name || '-') + '</code></td>' +
            '<td>' + origin + '</td>' +
            '<td>' + sourceBadge + '</td>' +
            '<td>' + confidence + '</td>' +
            '</tr>';
    };

    FeatureHierarchyTree.prototype._renderContextRow = function (ctx) {
        var sr = ctx.scan_result || {};
        var graphHref = sr.id ? this._buildGraphHref({ resultId: sr.id }) : '#';
        var confidence = ctx.confidence != null
            ? Math.round(ctx.confidence * 100) + '%'
            : '-';
        return '<tr class="fht-context-row">' +
            '<td><a href="/results/' + (sr.id || '') + '">' +
            this._esc(sr.name || '-') + '</a>' +
            ' <a href="' + this._esc(graphHref) + '" target="_blank" rel="noopener noreferrer" style="font-size:0.75rem;">Graph</a></td>' +
            '<td><code>' + this._esc(sr.table_name || '-') + '</code></td>' +
            '<td>' + this._esc((ctx.context_type || '').replace(/_/g, ' ')) + '</td>' +
            '<td>' + confidence + '</td>' +
            '</tr>';
    };

    FeatureHierarchyTree.prototype._renderRecommendationCard = function (rec) {
        var typeColors = {
            replace: '#d9534f', refactor: '#f0ad4e', keep: '#5cb85c', remove: '#777'
        };
        var typeIcons = {
            replace: '&#128260;', refactor: '&#128295;', keep: '&#9989;', remove: '&#128465;'
        };
        var recType = rec.recommendation_type || 'keep';
        var color = typeColors[recType] || '#999';
        var icon = typeIcons[recType] || '';
        var recTypeLabel = String(recType || '').replace(/_/g, ' ').toUpperCase();
        var confidence = rec.fit_confidence != null
            ? Math.round(rec.fit_confidence * 100) + '%'
            : '-';

        var html = '<div class="fht-rec-card" style="border-left: 3px solid ' + color + '">';
        html += '<div class="fht-rec-header">';
        html += '<span class="fht-badge" style="background:' + color + ';color:#fff">';
        html += icon + ' ' + this._esc(recTypeLabel) + '</span>';
        html += ' <span class="fht-rec-confidence">' + confidence + ' confidence</span>';
        html += '</div>';
        if (rec.ootb_capability_name) {
            html += '<div class="fht-rec-capability"><strong>OOTB Capability:</strong> ' +
                    this._esc(rec.ootb_capability_name) + '</div>';
        }
        if (rec.product_name || rec.sku_or_license) {
            html += '<div class="fht-rec-product">';
            if (rec.product_name) html += '<strong>Product:</strong> ' + this._esc(rec.product_name);
            if (rec.sku_or_license) html += ' <span class="fht-badge fht-sku">' + this._esc(rec.sku_or_license) + '</span>';
            html += '</div>';
        }
        if (rec.requires_plugins && rec.requires_plugins.length) {
            var plugins = Array.isArray(rec.requires_plugins) ? rec.requires_plugins : [rec.requires_plugins];
            html += '<div class="fht-rec-plugins"><strong>Plugins:</strong> ';
            html += plugins.map(function (p) { return '<code>' + this._esc(p) + '</code>'; }.bind(this)).join(', ');
            html += '</div>';
        }
        if (rec.rationale) {
            html += '<div class="fht-rec-rationale">' + this._esc(rec.rationale) + '</div>';
        }
        html += '</div>';
        return html;
    };

    FeatureHierarchyTree.prototype._renderUngroupedBucket = function (ungroupedList, ungroupedTotal) {
        var html = '<div class="fht-ungrouped">';
        html += '<div class="fht-ungrouped-header">';
        html += '<span class="fht-node-icon">&#128196;</span> ';
        html += '<strong>Ungrouped Customizations</strong>';
        html += ' <span class="fht-count">(' + ungroupedTotal + ')</span>';
        html += '</div>';

        for (var g = 0; g < ungroupedList.length; g++) {
            var group = ungroupedList[g];
            var classKey = group.app_file_class || '';
            var isExpanded = !!this._expandedUngrouped[classKey];

            html += '<div class="fht-ungrouped-class" data-ungrouped-class="' + this._esc(classKey) + '">';
            html += '<div class="fht-ungrouped-class-header" data-toggle-ungrouped="' + this._esc(classKey) + '">';
            html += '<span class="fht-chevron ' + (isExpanded ? 'fht-chevron-open' : '') + '">&#9654;</span>';
            html += '<code>' + this._esc(classKey) + '</code>';
            html += ' <span class="fht-count">(' + (group.count || 0) + ')</span>';
            html += '</div>';

            var results = group.results || [];
            if (isExpanded && results.length) {
                html += '<div class="fht-ungrouped-items">';
                html += '<table class="related-table fht-members-table"><thead><tr>';
                html += '<th>Name</th><th>Class</th><th>Origin</th>';
                html += '</tr></thead><tbody>';
                for (var it = 0; it < results.length; it++) {
                    var item = results[it];
                    var graphHref = item.id ? this._buildGraphHref({ resultId: item.id }) : '#';
                    var originClass = item.origin_type ? 'origin-' + item.origin_type : '';
                    var origin = item.origin_type
                        ? '<span class="origin-badge ' + originClass + '">' +
                          (item.origin_type || '').replace(/_/g, ' ') + '</span>'
                        : '-';
                    html += '<tr>' +
                        '<td><a href="/results/' + (item.id || '') + '">' +
                        this._esc(item.name || '-') + '</a>' +
                        ' <a href="' + this._esc(graphHref) + '" target="_blank" rel="noopener noreferrer" style="font-size:0.75rem;">Graph</a></td>' +
                        '<td><code>' + this._esc(item.table_name || '-') + '</code></td>' +
                        '<td>' + origin + '</td>' +
                        '</tr>';
                }
                html += '</tbody></table>';
                html += '</div>';
            }
            html += '</div>';
        }

        html += '</div>';
        return html;
    };

    FeatureHierarchyTree.prototype._renderEmpty = function () {
        var container = document.getElementById(this.containerId);
        var empty = document.getElementById(this.emptyId);
        if (container) container.innerHTML = '';
        if (empty) empty.style.display = 'block';
    };

    // ── Events ──────────────────────────────────────────────────

    FeatureHierarchyTree.prototype._bindTreeEvents = function (container) {
        var self = this;

        // Feature expand/collapse
        container.querySelectorAll('[data-toggle-feature]').forEach(function (el) {
            el.addEventListener('click', function (e) {
                if (e.target.tagName === 'A') return; // Don't toggle on link click
                var fid = parseInt(el.getAttribute('data-toggle-feature'), 10);
                self._expandedFeatures[fid] = !self._expandedFeatures[fid];
                self._render(self._data);
            });
        });

        // Ungrouped class expand/collapse
        container.querySelectorAll('[data-toggle-ungrouped]').forEach(function (el) {
            el.addEventListener('click', function () {
                var cls = el.getAttribute('data-toggle-ungrouped');
                self._expandedUngrouped[cls] = !self._expandedUngrouped[cls];
                self._render(self._data);
            });
        });

        // Expand/Collapse all buttons
        var expandBtn = container.querySelector('.fht-expand-all');
        var collapseBtn = container.querySelector('.fht-collapse-all');
        if (expandBtn) expandBtn.addEventListener('click', function () { self.expandAll(); });
        if (collapseBtn) collapseBtn.addEventListener('click', function () { self.collapseAll(); });
    };

    // ── Helpers ─────────────────────────────────────────────────

    FeatureHierarchyTree.prototype._setLoading = function (isLoading) {
        var el = document.getElementById(this.loadingId);
        if (el) el.style.display = isLoading ? 'flex' : 'none';
    };

    FeatureHierarchyTree.prototype._setMeta = function (text) {
        var el = this.metaId ? document.getElementById(this.metaId) : null;
        if (el) el.textContent = text;
    };

    FeatureHierarchyTree.prototype._updateBadge = function (count) {
        var el = this.badgeId ? document.getElementById(this.badgeId) : null;
        if (el) el.textContent = String(count);
    };

    FeatureHierarchyTree.prototype._setExpandedRecursive = function (feature, state) {
        this._expandedFeatures[feature.id] = state;
        if (feature.children) {
            for (var i = 0; i < feature.children.length; i++) {
                this._setExpandedRecursive(feature.children[i], state);
            }
        }
    };

    FeatureHierarchyTree.prototype._deriveScopeFromApiUrl = function () {
        if (!this.apiUrl) return;
        var assessmentMatch = this.apiUrl.match(/\/api\/assessments\/(\d+)\/feature-hierarchy/);
        if (assessmentMatch && assessmentMatch[1]) {
            this.scopeAssessmentId = parseInt(assessmentMatch[1], 10);
        }
        var scanMatch = this.apiUrl.match(/\/api\/scans\/(\d+)\/feature-hierarchy/);
        if (scanMatch && scanMatch[1]) {
            this.scopeScanId = parseInt(scanMatch[1], 10);
        }
    };

    FeatureHierarchyTree.prototype._buildGraphHref = function (opts) {
        var params = new URLSearchParams();
        if (opts && opts.resultId) params.set('result_id', String(opts.resultId));
        if (opts && opts.featureId) params.set('feature_id', String(opts.featureId));
        if (this.scopeAssessmentId) params.set('assessment_id', String(this.scopeAssessmentId));
        if (this.scopeScanId) params.set('scan_id', String(this.scopeScanId));
        return '/relationship-graph?' + params.toString();
    };

    FeatureHierarchyTree.prototype._esc = function (str) {
        if (str == null) return '';
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(String(str)));
        return div.innerHTML;
    };

    // ── Export ───────────────────────────────────────────────────

    window.FeatureHierarchyTree = FeatureHierarchyTree;
})();
