/* global cytoscape */

(function () {
    'use strict';

    function RelationshipGraph(opts) {
        this.apiUrl = opts.apiUrl;
        this.graphKind = opts.graphKind || 'relationship';
        this.initialSeed = opts.initialSeed || {};

        this.canvasId = opts.canvasId;
        this.detailBodyId = opts.detailBodyId;
        this.statusId = opts.statusId;
        this.nodeCountId = opts.nodeCountId;
        this.edgeCountId = opts.edgeCountId;
        this.breadcrumbsId = opts.breadcrumbsId;
        this.edgeFiltersId = opts.edgeFiltersId;
        this.tablePickerSectionId = opts.tablePickerSectionId;
        this.tableArtifactPickerId = opts.tableArtifactPickerId;
        this.tableGroupingToggleId = opts.tableGroupingToggleId;
        this.searchInputId = opts.searchInputId;
        this.searchButtonId = opts.searchButtonId;
        this.customSectionId = opts.customSectionId;
        this.showCustomId = opts.showCustomId;
        this.showNotCustomId = opts.showNotCustomId;
        this.showModifiedId = opts.showModifiedId;
        this.showNetNewId = opts.showNetNewId;
        this.scopeSectionId = opts.scopeSectionId;
        this.showDirectScopeId = opts.showDirectScopeId;
        this.showAdjacentScopeId = opts.showAdjacentScopeId;
        this.showOutOfScopeId = opts.showOutOfScopeId;
        this.showScopeUnknownId = opts.showScopeUnknownId;
        this.artifactTypeSectionId = opts.artifactTypeSectionId;
        this.artifactTypeFiltersId = opts.artifactTypeFiltersId;
        this.zoomOutButtonId = opts.zoomOutButtonId;
        this.zoomInButtonId = opts.zoomInButtonId;
        this.layoutButtonId = opts.layoutButtonId;
        this.fitButtonId = opts.fitButtonId;
        this.fitAllToggleId = opts.fitAllToggleId;
        this.labelsButtonId = opts.labelsButtonId;
        this.shellId = opts.shellId;
        this.layoutId = opts.layoutId;
        this.sidebarId = opts.sidebarId;
        this.detailPanelId = opts.detailPanelId;
        this.toggleFiltersButtonId = opts.toggleFiltersButtonId;
        this.toggleDetailButtonId = opts.toggleDetailButtonId;
        this.expandButtonId = opts.expandButtonId;
        this.popoutButtonId = opts.popoutButtonId;
        this.panLeftButtonId = opts.panLeftButtonId;
        this.panRightButtonId = opts.panRightButtonId;
        this.panUpButtonId = opts.panUpButtonId;
        this.panDownButtonId = opts.panDownButtonId;
        this.nodeViewSelectId = opts.nodeViewSelectId;

        this.cy = null;
        this.showLabels = true;
        this.nodePresentation = 'artifact';
        this.activeEdgeTypes = new Set();
        this.activeArtifactTypes = new Set();
        this.loadedResultIds = new Set();
        this.expandedResultIds = new Set();
        this.breadcrumbs = [];
        this.currentMode = 'artifact';
        this.currentCenterNodeId = null;
        this.currentPayload = null;
        this.tableCrowdThreshold = 24;
        this.isExpandedView = false;

        this.edgeTypeColors = {
            code_reference: '#f97316',
            structural: '#22c55e',
            shared_dependency: '#ef4444',
            reference_field: '#38bdf8',
            dictionary_binding: '#a855f7',
            target_table: '#facc15',
            same_update_set: '#f43f5e',
            same_table: '#64748b',
            shared_feature: '#14b8a6',
            feature_member: '#8b5cf6',
            feature_context: '#0ea5e9',
            table_member: '#94a3b8',
            dev_chain: '#f59e0b',
        };

        this.artifactTypeColorMap = {
            sys_script: '#3b82f6',
            sys_script_include: '#f97316',
            sys_script_client: '#22c55e',
            sys_ui_policy: '#eab308',
            sys_ui_policy_action: '#14b8a6',
            sys_ui_action: '#ec4899',
            sys_dictionary: '#8b5cf6',
            sys_dictionary_override: '#a855f7',
            sys_choice: '#06b6d4',
            sys_db_object: '#64748b',
            sys_security_acl: '#ef4444',
            sys_data_policy2: '#84cc16',
            sysauto_script: '#f59e0b',
            sysevent_email_action: '#f43f5e',
            sysevent_script_action: '#fb7185',
            sys_hub_flow: '#10b981',
            wf_workflow: '#6366f1',
            sp_widget: '#0ea5e9',
            sp_page: '#0891b2',
            sys_ui_page: '#2563eb',
            sys_ui_macro: '#7c3aed',
            sys_transform_map: '#ca8a04',
            sys_web_service: '#0f766e',
            sys_ui_form: '#4f46e5',
            sys_ui_list: '#9333ea',
            sys_ui_related_list: '#7e22ce',
            sys_report: '#0d9488',
            sys_update_set: '#78716c',
        };
    }

    RelationshipGraph.prototype.init = function () {
        if (!window.cytoscape) {
            this._setStatus('Cytoscape failed to load.');
            return;
        }

        var canvas = document.getElementById(this.canvasId);
        if (!canvas) {
            this._setStatus('Graph canvas not found.');
            return;
        }

        this.cy = cytoscape({
            container: canvas,
            elements: [],
            style: [
                {
                    selector: 'node',
                    style: {
                        'label': 'data(render_label)',
                        'font-size': 10,
                        'min-zoomed-font-size': 8,
                        'text-wrap': 'wrap',
                        'text-max-width': 125,
                        'color': '#e5edf5',
                        'text-outline-width': 0,
                        'text-background-color': '#0f172a',
                        'text-background-opacity': 0.4,
                        'text-background-padding': 2,
                        'text-background-shape': 'round-rectangle',
                        'text-valign': 'data(label_valign)',
                        'text-halign': 'data(label_halign)',
                        'text-margin-x': 'data(label_dx)',
                        'text-margin-y': 'data(label_dy)',
                        'background-color': 'data(bg_color)',
                        'border-width': 2,
                        'border-color': 'data(border_color)',
                        'z-index-compare': 'manual',
                        'z-index': 'data(z_index)',
                        'padding': 6,
                    },
                },
                {
                    selector: 'node[node_type = "artifact"]',
                    style: {
                        'shape': 'round-rectangle',
                        'width': 70,
                        'height': 34,
                    },
                },
                {
                    selector: 'node[node_type = "feature"]',
                    style: {
                        'shape': 'hexagon',
                        'width': 82,
                        'height': 42,
                    },
                },
                {
                    selector: 'node[node_type = "table"]',
                    style: {
                        'shape': 'barrel',
                        'width': 86,
                        'height': 44,
                    },
                },
                {
                    selector: 'node[node_type = "table_group"]',
                    style: {
                        'shape': 'round-rectangle',
                        'width': 110,
                        'height': 48,
                    },
                },
                {
                    selector: 'node[node_type = "dev_record"]',
                    style: {
                        'shape': 'round-rectangle',
                        'width': 84,
                        'height': 38,
                        'border-style': 'dashed',
                        'font-size': 11,
                        'min-zoomed-font-size': 7,
                        'text-max-width': 170,
                        'text-background-opacity': 0.75,
                    },
                },
                {
                    selector: 'node[node_type = "dev_group"]',
                    style: {
                        'shape': 'round-rectangle',
                        'width': 110,
                        'height': 42,
                        'border-style': 'dotted',
                        'font-size': 11,
                        'min-zoomed-font-size': 7,
                        'text-max-width': 170,
                        'text-background-opacity': 0.78,
                    },
                },
                {
                    selector: 'edge',
                    style: {
                        'curve-style': 'bezier',
                        'line-color': 'data(line_color)',
                        'line-style': 'data(line_style)',
                        'width': 2,
                        'target-arrow-shape': 'none',
                        'opacity': 0.86,
                    },
                },
                {
                    selector: '.hidden-node',
                    style: { 'display': 'none' },
                },
                {
                    selector: '.table-crowded-hidden',
                    style: { 'display': 'none' },
                },
                {
                    selector: '.hidden-edge',
                    style: { 'display': 'none' },
                },
                {
                    selector: '.selected-node',
                    style: {
                        'border-width': 4,
                        'border-color': '#fde047',
                    },
                },
            ],
            layout: {
                name: 'cose',
                animate: false,
                fit: true,
                padding: 30,
            },
        });

        this.isExpandedView = this._shellHasClass('rg-expanded');
        this._bindUi();
        this._updateLayoutClasses();
        this._syncNodeViewSelect();
        this._loadInitial();
    };

    RelationshipGraph.prototype._bindUi = function () {
        var self = this;

        this.cy.on('tap', 'node', function (evt) {
            var node = evt.target;
            self.cy.nodes().removeClass('selected-node');
            node.addClass('selected-node');
            var data = node.data();
            self._renderDetail(data);
            self._pushBreadcrumb(data.id, data.label || data.name || data.id);
            if (data.node_type === 'artifact' || data.seed_result_id) {
                self._expandFromArtifact(data);
            } else if (data.node_type === 'table_group') {
                self._setStatus('Use the artifact list to choose the next center node.');
            }
        });

        var searchInput = document.getElementById(this.searchInputId);
        if (searchInput) {
            searchInput.addEventListener('keydown', function (evt) {
                if (evt.key === 'Enter') {
                    evt.preventDefault();
                    self._searchNode();
                }
            });
        }

        var searchBtn = document.getElementById(this.searchButtonId);
        if (searchBtn) {
            searchBtn.addEventListener('click', function () {
                self._searchNode();
            });
        }

        var toggleFiltersBtn = document.getElementById(this.toggleFiltersButtonId);
        if (toggleFiltersBtn) {
            toggleFiltersBtn.classList.add('active');
            toggleFiltersBtn.addEventListener('click', function () {
                self._togglePanel('sidebar');
            });
        }

        var toggleDetailBtn = document.getElementById(this.toggleDetailButtonId);
        if (toggleDetailBtn) {
            toggleDetailBtn.classList.add('active');
            toggleDetailBtn.addEventListener('click', function () {
                self._togglePanel('detail');
            });
        }

        var expandBtn = document.getElementById(this.expandButtonId);
        if (expandBtn) {
            expandBtn.classList.toggle('active', this.isExpandedView);
            expandBtn.addEventListener('click', function () {
                self._toggleExpandedView();
            });
        }

        var popoutBtn = document.getElementById(this.popoutButtonId);
        if (popoutBtn) {
            popoutBtn.addEventListener('click', function () {
                self._openPopoutWindow();
            });
        }

        var panStep = 120;
        var panButtons = [
            { id: this.panLeftButtonId, dx: panStep, dy: 0 },
            { id: this.panRightButtonId, dx: -panStep, dy: 0 },
            { id: this.panUpButtonId, dx: 0, dy: panStep },
            { id: this.panDownButtonId, dx: 0, dy: -panStep },
        ];
        panButtons.forEach(function (item) {
            var btn = document.getElementById(item.id);
            if (!btn) return;
            btn.addEventListener('click', function () {
                self._panGraph(item.dx, item.dy);
            });
        });

        document.addEventListener('keydown', function (evt) {
            var tagName = evt.target && evt.target.tagName ? evt.target.tagName.toLowerCase() : '';
            if (tagName === 'input' || tagName === 'textarea' || evt.target.isContentEditable) {
                return;
            }
            if (evt.key === 'ArrowLeft') {
                evt.preventDefault();
                self._panGraph(panStep, 0);
            } else if (evt.key === 'ArrowRight') {
                evt.preventDefault();
                self._panGraph(-panStep, 0);
            } else if (evt.key === 'ArrowUp') {
                evt.preventDefault();
                self._panGraph(0, panStep);
            } else if (evt.key === 'ArrowDown') {
                evt.preventDefault();
                self._panGraph(0, -panStep);
            }
        });

        [
            this.showCustomId,
            this.showNotCustomId,
            this.showModifiedId,
            this.showNetNewId,
            this.showDirectScopeId,
            this.showAdjacentScopeId,
            this.showOutOfScopeId,
            this.showScopeUnknownId,
        ].forEach(function (toggleId) {
            var input = document.getElementById(toggleId);
            if (!input) return;
            input.addEventListener('change', function () {
                self._applyFilters();
            });
        });

        var layoutBtn = document.getElementById(this.layoutButtonId);
        if (layoutBtn) {
            layoutBtn.addEventListener('click', function () {
                self._runLayout();
            });
        }

        var zoomOutBtn = document.getElementById(this.zoomOutButtonId);
        if (zoomOutBtn) {
            zoomOutBtn.addEventListener('click', function () {
                if (!self.cy) return;
                self.cy.zoom({
                    level: Math.max(0.2, self.cy.zoom() * 0.88),
                    renderedPosition: { x: self.cy.width() / 2, y: self.cy.height() / 2 },
                });
            });
        }

        var zoomInBtn = document.getElementById(this.zoomInButtonId);
        if (zoomInBtn) {
            zoomInBtn.addEventListener('click', function () {
                if (!self.cy) return;
                self.cy.zoom({
                    level: Math.min(3.0, self.cy.zoom() * 1.12),
                    renderedPosition: { x: self.cy.width() / 2, y: self.cy.height() / 2 },
                });
            });
        }

        var fitBtn = document.getElementById(this.fitButtonId);
        if (fitBtn) {
            fitBtn.addEventListener('click', function () {
                self.cy.fit(undefined, 40);
            });
        }

        var fitAllToggle = document.getElementById(this.fitAllToggleId);
        if (fitAllToggle) {
            fitAllToggle.addEventListener('change', function () {
                if (fitAllToggle.checked) {
                    self.cy.fit(undefined, 40);
                } else {
                    self._focusNode(self.currentCenterNodeId);
                }
            });
        }

        var tableGroupingToggle = document.getElementById(this.tableGroupingToggleId);
        if (tableGroupingToggle) {
            tableGroupingToggle.addEventListener('change', function () {
                self._applyTableModeGrouping();
                self._applyFilters();
                self._runLayout();
                self._renderTableArtifactPicker();
            });
        }

        var labelsBtn = document.getElementById(this.labelsButtonId);
        if (labelsBtn) {
            labelsBtn.addEventListener('click', function () {
                self.showLabels = !self.showLabels;
                self.cy.style()
                    .selector('node')
                    .style('label', self.showLabels ? 'data(render_label)' : '')
                    .update();
                labelsBtn.classList.toggle('active', self.showLabels);
            });
        }

        var nodeViewSelect = document.getElementById(this.nodeViewSelectId);
        if (nodeViewSelect) {
            nodeViewSelect.addEventListener('change', function () {
                self.nodePresentation = (nodeViewSelect.value === 'result') ? 'result' : 'artifact';
                self._applyNodePresentation();
            });
        }
    };

    RelationshipGraph.prototype._shellHasClass = function (className) {
        var shell = document.getElementById(this.shellId);
        return !!(shell && shell.classList.contains(className));
    };

    RelationshipGraph.prototype._toggleExpandedView = function () {
        var shell = document.getElementById(this.shellId);
        var btn = document.getElementById(this.expandButtonId);
        if (!shell) return;
        this.isExpandedView = !shell.classList.contains('rg-expanded');
        shell.classList.toggle('rg-expanded', this.isExpandedView);
        if (btn) {
            btn.classList.toggle('active', this.isExpandedView);
        }
        this._scheduleResizeAndRefocus();
    };

    RelationshipGraph.prototype._togglePanel = function (panelKey) {
        var panel = panelKey === 'sidebar'
            ? document.getElementById(this.sidebarId)
            : document.getElementById(this.detailPanelId);
        if (!panel) return;

        var isHidden = panel.classList.contains('rg-panel-hidden');
        panel.classList.toggle('rg-panel-hidden', !isHidden);

        var buttonId = panelKey === 'sidebar' ? this.toggleFiltersButtonId : this.toggleDetailButtonId;
        var button = document.getElementById(buttonId);
        if (button) {
            button.classList.toggle('active', isHidden);
        }

        this._updateLayoutClasses();
        this._scheduleResizeAndRefocus();
    };

    RelationshipGraph.prototype._updateLayoutClasses = function () {
        var layout = document.getElementById(this.layoutId);
        var sidebar = document.getElementById(this.sidebarId);
        var detail = document.getElementById(this.detailPanelId);
        if (!layout) return;
        var sidebarHidden = !!(sidebar && sidebar.classList.contains('rg-panel-hidden'));
        var detailHidden = !!(detail && detail.classList.contains('rg-panel-hidden'));
        layout.classList.toggle('rg-no-sidebar', sidebarHidden);
        layout.classList.toggle('rg-no-detail', detailHidden);
    };

    RelationshipGraph.prototype._scheduleResizeAndRefocus = function () {
        var self = this;
        if (!this.cy) return;
        window.setTimeout(function () {
            if (!self.cy) return;
            self.cy.resize();
            if (self._isFitAllEnabled()) {
                self.cy.fit(self.cy.elements(':visible'), 44);
                return;
            }
            self._focusNode(self.currentCenterNodeId);
        }, 180);
    };

    RelationshipGraph.prototype._panGraph = function (dx, dy) {
        if (!this.cy) return;
        this.cy.panBy({ x: dx, y: dy });
    };

    RelationshipGraph.prototype._openPopoutWindow = function () {
        var features = [
            'noopener=yes',
            'noreferrer=yes',
            'width=1760',
            'height=1080',
            'resizable=yes',
            'scrollbars=yes',
        ].join(',');
        window.open(window.location.href, '_blank', features);
    };

    RelationshipGraph.prototype._loadInitial = function () {
        var self = this;
        this._setStatus('Loading graph seed...');

        this._fetchPayload(this.initialSeed, '')
            .then(function (payload) {
                self.breadcrumbs = [];
                self._renderBreadcrumbs();
                self._replaceGraphWithPayload(payload);
                self._setStatus('Ready. Click node to recenter. Drag background or use arrow pan buttons to move.');
            })
            .catch(function (err) {
                self._setStatus('Failed to load graph: ' + err.message);
            });
    };

    RelationshipGraph.prototype._syncNodeViewSelect = function () {
        var select = document.getElementById(this.nodeViewSelectId);
        if (!select) return;
        select.value = this.nodePresentation;
    };

    RelationshipGraph.prototype._replaceGraphWithPayload = function (payload) {
        if (!payload) return;
        this.cy.elements().remove();
        this.loadedResultIds.clear();
        this.expandedResultIds.clear();
        this.currentPayload = payload;
        this.currentMode = payload.mode || 'artifact';
        this.currentCenterNodeId = (payload.center_node && payload.center_node.id) ? payload.center_node.id : null;
        if (payload.graph_kind === 'dependency' && this.graphKind !== 'dependency') {
            this.graphKind = 'dependency';
        }
        this._syncCustomizationFilters();
        this._mergePayload(payload, true);

        if (payload.center_node && payload.center_node.id) {
            this._focusNode(payload.center_node.id);
            this._pushBreadcrumb(
                payload.center_node.id,
                payload.center_node.label || payload.center_node.name || payload.center_node.id
            );
            this._renderDetail(payload.center_node);
        }
    };

    RelationshipGraph.prototype._fetchPayload = function (seed, excludeCsv) {
        var params = new URLSearchParams();
        if (seed.result_id) params.set('result_id', String(seed.result_id));
        if (seed.feature_id) params.set('feature_id', String(seed.feature_id));
        if (seed.table_name) params.set('table_name', String(seed.table_name));
        if (seed.assessment_id) params.set('assessment_id', String(seed.assessment_id));
        if (seed.instance_id) params.set('instance_id', String(seed.instance_id));
        if (seed.scan_id) params.set('scan_id', String(seed.scan_id));
        params.set('max_neighbors', '30');
        if (excludeCsv) params.set('exclude_result_ids', excludeCsv);

        return fetch(this.apiUrl + '?' + params.toString(), { cache: 'no-store' })
            .then(function (response) {
                if (!response.ok) {
                    return response.json().catch(function () { return {}; }).then(function (payload) {
                        var message = payload && payload.detail ? payload.detail : ('HTTP ' + response.status);
                        throw new Error(message);
                    });
                }
                return response.json();
            });
    };

    RelationshipGraph.prototype._expandFromArtifact = function (nodeData) {
        var self = this;
        var resultId = nodeData.result_id || nodeData.seed_result_id;
        if (!resultId) return;
        this._setStatus('Loading neighborhood for result #' + resultId + '...');

        var seed = {
            result_id: resultId,
            assessment_id: nodeData.assessment_id || this.initialSeed.assessment_id || null,
            instance_id: nodeData.instance_id || this.initialSeed.instance_id || null,
            scan_id: this.initialSeed.scan_id || nodeData.scan_id || null,
        };

        this._fetchPayload(seed, '')
            .then(function (payload) {
                self._replaceGraphWithPayload(payload);
                if (nodeData && nodeData.id) {
                    var selected = self.cy.getElementById(nodeData.id);
                    if (selected && selected.length) {
                        self.cy.nodes().removeClass('selected-node');
                        selected.addClass('selected-node');
                        self._focusNode(nodeData.id);
                        self._renderDetail(selected.data());
                    }
                }
                var added = (payload && payload.summary && payload.summary.returned_neighbor_count) || 0;
                self._setStatus('Loaded ' + added + ' neighbors from result #' + resultId + '.');
            })
            .catch(function (err) {
                self._setStatus('Expansion failed: ' + err.message);
            });
    };

    RelationshipGraph.prototype._mergePayload = function (payload, resetLayout) {
        if (!payload) return;
        if (payload.mode) {
            this.currentMode = payload.mode;
            this._syncCustomizationFilters();
        }
        this.currentPayload = payload;
        this.currentCenterNodeId = (payload.center_node && payload.center_node.id) ? payload.center_node.id : this.currentCenterNodeId;

        var nodes = payload.nodes || [];
        var edges = payload.edges || [];

        for (var i = 0; i < nodes.length; i++) {
            this._upsertNode(nodes[i]);
        }
        for (var j = 0; j < edges.length; j++) {
            this._upsertEdge(edges[j]);
        }

        this._applyTableModeGrouping();
        this._applyNodePresentation();
        this._rebuildArtifactTypeFilters();
        this._rebuildEdgeFilters();
        this._applyFilters();
        this._renderTableArtifactPicker();
        this._updateStats();

        if (resetLayout) {
            this._runLayout();
        } else if (nodes.length || edges.length) {
            this._runLayout();
        }
    };

    RelationshipGraph.prototype._applyNodePresentation = function () {
        if (!this.cy) return;
        var mode = this.nodePresentation === 'result' ? 'result' : 'artifact';
        this.cy.nodes().forEach(function (node) {
            if (node.data('node_type') !== 'artifact') return;
            var nextLabel = mode === 'result'
                ? (node.data('result_view_label') || node.data('render_label'))
                : (node.data('artifact_view_label') || node.data('render_label'));
            node.data('render_label', nextLabel);
        });
    };

    RelationshipGraph.prototype._upsertNode = function (node) {
        if (!node || !node.id) return;

        var normalized = this._normalizeNode(node);
        var existing = this.cy.getElementById(normalized.id);
        if (existing && existing.length) {
            existing.data(normalized);
        } else {
            this.cy.add({ group: 'nodes', data: normalized });
        }

        if (normalized.node_type === 'artifact' && normalized.result_id) {
            this.loadedResultIds.add(normalized.result_id);
        }
    };

    RelationshipGraph.prototype._upsertEdge = function (edge) {
        if (!edge || !edge.id || !edge.source || !edge.target) return;

        var color = this.edgeTypeColors[edge.edge_type] || '#9ca3af';
        var lineStyle = edge.edge_type === 'same_table' ? 'dashed' : 'solid';
        var payload = {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            edge_type: edge.edge_type,
            label: edge.label,
            detail: edge.detail || '',
            line_color: color,
            line_style: lineStyle,
        };

        var existing = this.cy.getElementById(payload.id);
        if (existing && existing.length) {
            existing.data(payload);
        } else {
            this.cy.add({ group: 'edges', data: payload });
        }

        if (!this.activeEdgeTypes.has(edge.edge_type)) {
            this.activeEdgeTypes.add(edge.edge_type);
        }
    };

    RelationshipGraph.prototype._normalizeNode = function (node) {
        var nodeType = node.node_type || 'artifact';
        var baseLabel = node.label || node.name || node.id;
        var renderLabel = baseLabel;
        var resultViewLabel = baseLabel;
        var artifactViewLabel = baseLabel;
        var bgColor = '#475569';
        var borderColor = '#cbd5e1';
        var labelDx = 0;
        var labelDy = 0;
        var labelValign = 'center';
        var labelHalign = 'center';
        var zIndex = 20;

        if (nodeType === 'feature') {
            bgColor = '#6d28d9';
            borderColor = '#ddd6fe';
            renderLabel = '[Feature] ' + baseLabel;
            zIndex = 60;
        } else if (nodeType === 'table') {
            bgColor = '#1d4ed8';
            borderColor = '#bfdbfe';
            renderLabel = '[Table] ' + baseLabel;
            zIndex = 55;
        } else if (nodeType === 'dev_record') {
            var devKind = String(node.dev_kind || '').toLowerCase();
            var compactDevLabel = baseLabel.length > 36 ? (baseLabel.slice(0, 33) + '...') : baseLabel;
            if (devKind === 'artifact_record') {
                bgColor = '#0f766e';
                borderColor = '#5eead4';
                renderLabel = '[Artifact] ' + compactDevLabel;
            } else if (devKind === 'customer_update_xml') {
                bgColor = '#7c2d12';
                borderColor = '#fdba74';
                renderLabel = '[Update XML] ' + compactDevLabel;
            } else if (devKind === 'version_history') {
                bgColor = '#4338ca';
                borderColor = '#c7d2fe';
                renderLabel = '[Version] ' + compactDevLabel;
            } else if (devKind === 'update_set') {
                bgColor = '#0f766e';
                borderColor = '#99f6e4';
                renderLabel = '[Update Set] ' + compactDevLabel;
            } else if (devKind === 'metadata_customization') {
                bgColor = '#7e22ce';
                borderColor = '#e9d5ff';
                renderLabel = '[Metadata Customization] ' + compactDevLabel;
            } else {
                bgColor = '#1f2937';
                borderColor = '#d1d5db';
                renderLabel = '[Related] ' + compactDevLabel;
            }
            labelDx = 18;
            labelDy = -16;
            labelValign = 'top';
            labelHalign = 'left';
            zIndex = 1200;
        } else if (nodeType === 'dev_group') {
            bgColor = '#374151';
            borderColor = '#d1d5db';
            renderLabel = '[Grouped] ' + baseLabel;
            labelDx = 18;
            labelDy = -16;
            labelValign = 'top';
            labelHalign = 'left';
            zIndex = 1100;
        } else {
            var origin = String(node.origin_type || '').toLowerCase();
            var originPrefix = '[OOTB] ';
            var artifactTypeKey = String(node.artifact_type_key || node.table_name || '').trim();
            var artifactTypeColor = this._artifactTypeColor(artifactTypeKey);
            bgColor = artifactTypeColor;
            if (origin === 'modified_ootb') {
                borderColor = '#fde68a';
                originPrefix = '[OOTB*] ';
            } else if (origin === 'net_new_customer') {
                borderColor = '#bfdbfe';
                originPrefix = '[New] ';
            } else if (node.is_customized) {
                borderColor = '#bbf7d0';
                originPrefix = '[Custom] ';
            } else {
                borderColor = '#cbd5e1';
            }

            if (node.is_out_of_scope) {
                borderColor = '#fb7185';
            } else if (node.is_adjacent) {
                borderColor = '#67e8f9';
            }

            resultViewLabel = originPrefix + 'Result #' + (node.result_id || '?') + ' • ' + baseLabel;
            var artifactTypeLabel = String(node.artifact_type_label || node.table_name || '').trim();
            artifactViewLabel = originPrefix + (artifactTypeLabel ? (artifactTypeLabel + ' • ') : '') + baseLabel;
            renderLabel = this.nodePresentation === 'result' ? resultViewLabel : artifactViewLabel;
        }

        return {
            id: node.id,
            node_type: nodeType,
            result_id: node.result_id || null,
            feature_id: node.feature_id || null,
            table_name: node.table_name || null,
            artifact_type_key: node.artifact_type_key || node.table_name || null,
            artifact_type_label: node.artifact_type_label || node.table_name || null,
            assessment_id: node.assessment_id || null,
            instance_id: node.instance_id || null,
            scan_id: node.scan_id || null,
            label: baseLabel,
            name: node.name || null,
            origin_type: node.origin_type || null,
            is_customized: !!node.is_customized,
            is_adjacent: !!node.is_adjacent,
            is_out_of_scope: !!node.is_out_of_scope,
            scope_state: node.scope_state || null,
            sys_id: node.sys_id || null,
            feature_names: node.feature_names || [],
            description: node.description || null,
            disposition: node.disposition || null,
            confidence_score: node.confidence_score,
            confidence_level: node.confidence_level,
            artifact_kind: node.artifact_kind || null,
            dev_kind: node.dev_kind || null,
            dev_chain_role: node.dev_chain_role || null,
            dev_chain_anchor: node.dev_chain_anchor || null,
            seed_result_id: node.seed_result_id || null,
            links: (node.links && typeof node.links === 'object') ? node.links : null,
            record_id: node.record_id || null,
            state: node.state || null,
            hidden_count: node.hidden_count || null,
            total_count: node.total_count || null,
            result_view_label: resultViewLabel,
            artifact_view_label: artifactViewLabel,
            render_label: renderLabel,
            bg_color: bgColor,
            border_color: borderColor,
            label_dx: (typeof node.label_dx === 'number') ? node.label_dx : labelDx,
            label_dy: (typeof node.label_dy === 'number') ? node.label_dy : labelDy,
            label_valign: node.label_valign || labelValign,
            label_halign: node.label_halign || labelHalign,
            z_index: (typeof node.z_index === 'number') ? node.z_index : zIndex,
        };
    };

    RelationshipGraph.prototype._rebuildEdgeFilters = function () {
        var container = document.getElementById(this.edgeFiltersId);
        if (!container) return;

        var counts = {};
        this.cy.edges().forEach(function (edge) {
            var type = edge.data('edge_type') || 'unknown';
            counts[type] = (counts[type] || 0) + 1;
        });

        var edgeTypes = Object.keys(counts).sort();
        if (!edgeTypes.length) {
            container.innerHTML = '<p class="text-muted-sm">No relationships yet.</p>';
            return;
        }

        var html = '';
        for (var i = 0; i < edgeTypes.length; i++) {
            var edgeType = edgeTypes[i];
            if (!this.activeEdgeTypes.has(edgeType)) {
                this.activeEdgeTypes.add(edgeType);
            }
            var checked = this.activeEdgeTypes.has(edgeType) ? 'checked' : '';
            var color = this.edgeTypeColors[edgeType] || '#9ca3af';
            html += '' +
                '<label class="rg-edge-filter">' +
                '<input type="checkbox" data-edge-filter="' + this._esc(edgeType) + '" ' + checked + ' />' +
                '<span class="rg-edge-swatch" style="background:' + this._esc(color) + ';"></span>' +
                '<span>' + this._esc(edgeType.replace(/_/g, ' ')) + ' (' + counts[edgeType] + ')</span>' +
                '</label>';
        }
        container.innerHTML = html;

        var self = this;
        container.querySelectorAll('[data-edge-filter]').forEach(function (input) {
            input.addEventListener('change', function () {
                var edgeType = input.getAttribute('data-edge-filter');
                if (input.checked) {
                    self.activeEdgeTypes.add(edgeType);
                } else {
                    self.activeEdgeTypes.delete(edgeType);
                }
                self._applyFilters();
            });
        });
    };

    RelationshipGraph.prototype._applyTableModeGrouping = function () {
        if (!this.cy) return;

        this.cy.edges('[id ^= "table-group-edge:"]').remove();
        this.cy.nodes('[id ^= "table-group:"]').remove();
        this.cy.nodes('[node_type = "artifact"]').removeClass('table-crowded-hidden');

        if (this.currentMode !== 'table') return;

        var artifacts = this.cy.nodes('[node_type = "artifact"]');
        if (!artifacts || artifacts.length === 0) return;

        var isCrowded = artifacts.length > this.tableCrowdThreshold;
        var groupingToggle = document.getElementById(this.tableGroupingToggleId);
        var groupingEnabled = !!(groupingToggle && groupingToggle.checked);

        if (isCrowded && groupingToggle && !groupingToggle.checked) {
            groupingToggle.checked = true;
            groupingEnabled = true;
        }

        if (!isCrowded || !groupingEnabled) return;

        var tableCollection = this.currentCenterNodeId ? this.cy.getElementById(this.currentCenterNodeId) : this.cy.nodes('[node_type = "table"]');
        var tableNode = tableCollection && tableCollection.length ? tableCollection[0] : null;
        if (!tableNode) return;

        var customCount = 0;
        var ootbCount = 0;
        artifacts.forEach(function (node) {
            if (node.data('is_customized')) {
                customCount += 1;
                node.data('table_bucket', 'custom');
            } else {
                ootbCount += 1;
                node.data('table_bucket', 'ootb');
            }
            node.addClass('table-crowded-hidden');
        });

        var addGroupNode = function (id, label, bgColor, borderColor) {
            return {
                group: 'nodes',
                data: {
                    id: id,
                    node_type: 'table_group',
                    label: label,
                    render_label: label,
                    bg_color: bgColor,
                    border_color: borderColor,
                },
            };
        };

        var additions = [];
        if (customCount > 0) {
            additions.push(addGroupNode('table-group:custom', 'Customized (' + customCount + ')', '#1d4ed8', '#bfdbfe'));
            additions.push({
                group: 'edges',
                data: {
                    id: 'table-group-edge:custom',
                    source: tableNode.id(),
                    target: 'table-group:custom',
                    edge_type: 'table_member',
                    label: 'Table Member Group',
                    line_color: this.edgeTypeColors.table_member || '#94a3b8',
                    line_style: 'solid',
                },
            });
        }
        if (ootbCount > 0) {
            additions.push(addGroupNode('table-group:ootb', 'Not Customized (' + ootbCount + ')', '#334155', '#cbd5e1'));
            additions.push({
                group: 'edges',
                data: {
                    id: 'table-group-edge:ootb',
                    source: tableNode.id(),
                    target: 'table-group:ootb',
                    edge_type: 'table_member',
                    label: 'Table Member Group',
                    line_color: this.edgeTypeColors.table_member || '#94a3b8',
                    line_style: 'solid',
                },
            });
        }
        if (additions.length) {
            this.cy.add(additions);
        }
    };

    RelationshipGraph.prototype._renderTableArtifactPicker = function () {
        var section = document.getElementById(this.tablePickerSectionId);
        var container = document.getElementById(this.tableArtifactPickerId);
        if (!section || !container) return;

        if (this.currentMode !== 'table') {
            section.style.display = 'none';
            return;
        }
        section.style.display = 'block';

        var artifacts = this.cy.nodes('[node_type = "artifact"]');
        if (!artifacts.length) {
            container.innerHTML = '<span class="text-muted-sm">No artifacts in current table payload.</span>';
            return;
        }

        var custom = [];
        var ootb = [];
        artifacts.forEach(function (node) {
            var payload = {
                result_id: node.data('result_id'),
                label: node.data('label') || node.id(),
                origin_type: String(node.data('origin_type') || '').toLowerCase(),
                assessment_id: node.data('assessment_id'),
                instance_id: node.data('instance_id'),
                scan_id: node.data('scan_id'),
                is_customized: !!node.data('is_customized'),
            };
            if (payload.is_customized) {
                custom.push(payload);
            } else {
                ootb.push(payload);
            }
        });

        custom.sort(function (a, b) { return String(a.label).localeCompare(String(b.label)); });
        ootb.sort(function (a, b) { return String(a.label).localeCompare(String(b.label)); });

        var crowded = artifacts.length > this.tableCrowdThreshold;
        var html = '';
        if (crowded) {
            html += '<p class="text-muted-sm" style="margin-bottom:0.45rem;">Crowded table view detected. Grouping is auto-enabled.</p>';
        }

        var renderGroup = function (title, rows) {
            if (!rows.length) return '';
            var block = '<div class="rg-picker-group"><div class="rg-picker-title">' + title + ' (' + rows.length + ')</div><div class="rg-picker-list">';
            for (var i = 0; i < rows.length; i++) {
                var row = rows[i];
                var originTag = '';
                if (row.origin_type === 'modified_ootb') originTag = ' [OOTB Modified]';
                if (row.origin_type === 'net_new_customer') originTag = ' [Customer Created]';
                block += '<button type="button" class="rg-picker-item" data-result-id="' + row.result_id + '">' +
                    this._esc(row.label + originTag) + '</button>';
            }
            block += '</div></div>';
            return block;
        }.bind(this);

        html += renderGroup('Customized', custom);
        html += renderGroup('Not Customized', ootb);
        container.innerHTML = html;

        var self = this;
        container.querySelectorAll('[data-result-id]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var resultId = parseInt(btn.getAttribute('data-result-id'), 10);
                if (!resultId) return;
                var nodeCollection = artifacts.filter(function (n) { return n.data('result_id') === resultId; });
                var node = nodeCollection && nodeCollection.length ? nodeCollection[0] : null;
                var seed = {
                    result_id: resultId,
                    assessment_id: node ? node.data('assessment_id') : (self.initialSeed.assessment_id || null),
                    instance_id: node ? node.data('instance_id') : (self.initialSeed.instance_id || null),
                    scan_id: node ? node.data('scan_id') : (self.initialSeed.scan_id || null),
                };
                self._setStatus('Loading neighborhood for result #' + resultId + '...');
                self._fetchPayload(seed, '').then(function (payload) {
                    self._replaceGraphWithPayload(payload);
                    var added = (payload && payload.summary && payload.summary.returned_neighbor_count) || 0;
                    self._setStatus('Loaded ' + added + ' neighbors from result #' + resultId + '.');
                }).catch(function (err) {
                    self._setStatus('Expansion failed: ' + err.message);
                });
            });
        });
    };

    RelationshipGraph.prototype._syncCustomizationFilters = function () {
        var section = document.getElementById(this.customSectionId);
        if (section) {
            section.style.display = 'block';
        }

        var scopeSection = document.getElementById(this.scopeSectionId);
        if (scopeSection) {
            scopeSection.style.display = 'block';
        }

        var tableSection = document.getElementById(this.tablePickerSectionId);
        if (tableSection) {
            tableSection.style.display = this.currentMode === 'table' ? 'block' : 'none';
        }
    };

    RelationshipGraph.prototype._artifactTypeColor = function (artifactTypeKey) {
        var key = String(artifactTypeKey || '').trim();
        if (!key) return '#475569';
        if (this.artifactTypeColorMap[key]) {
            return this.artifactTypeColorMap[key];
        }

        var hash = 0;
        for (var i = 0; i < key.length; i++) {
            hash = ((hash << 5) - hash) + key.charCodeAt(i);
            hash |= 0;
        }
        var hue = Math.abs(hash) % 360;
        return 'hsl(' + hue + ', 68%, 46%)';
    };

    RelationshipGraph.prototype._rebuildArtifactTypeFilters = function () {
        var section = document.getElementById(this.artifactTypeSectionId);
        var container = document.getElementById(this.artifactTypeFiltersId);
        if (!section || !container || !this.cy) return;

        var counts = {};
        var labels = {};
        var self = this;
        this.cy.nodes('[node_type = "artifact"]').forEach(function (node) {
            var key = String(node.data('artifact_type_key') || node.data('table_name') || '').trim();
            if (!key) return;
            counts[key] = (counts[key] || 0) + 1;
            labels[key] = String(node.data('artifact_type_label') || key);
        });

        var typeKeys = Object.keys(counts).sort(function (left, right) {
            return String(labels[left] || left).localeCompare(String(labels[right] || right));
        });
        section.style.display = typeKeys.length ? 'block' : 'none';
        if (!typeKeys.length) {
            container.innerHTML = '<p class="text-muted-sm">No artifact types loaded.</p>';
            return;
        }

        var nextActive = new Set();
        for (var i = 0; i < typeKeys.length; i++) {
            var typeKey = typeKeys[i];
            if (this.activeArtifactTypes.size === 0 || this.activeArtifactTypes.has(typeKey)) {
                nextActive.add(typeKey);
            }
        }
        this.activeArtifactTypes = nextActive;

        var html = '';
        for (var j = 0; j < typeKeys.length; j++) {
            var artifactTypeKey = typeKeys[j];
            var checked = this.activeArtifactTypes.has(artifactTypeKey) ? 'checked' : '';
            html += '' +
                '<label class="rg-type-filter">' +
                '<input type="checkbox" data-artifact-type-filter="' + this._esc(artifactTypeKey) + '" ' + checked + ' />' +
                '<span class="rg-type-swatch" style="background:' + this._esc(this._artifactTypeColor(artifactTypeKey)) + ';"></span>' +
                '<span>' + this._esc(labels[artifactTypeKey] || artifactTypeKey) + ' (' + counts[artifactTypeKey] + ')</span>' +
                '</label>';
        }
        container.innerHTML = html;

        container.querySelectorAll('[data-artifact-type-filter]').forEach(function (input) {
            input.addEventListener('change', function () {
                var artifactTypeKey = input.getAttribute('data-artifact-type-filter');
                if (input.checked) {
                    self.activeArtifactTypes.add(artifactTypeKey);
                } else {
                    self.activeArtifactTypes.delete(artifactTypeKey);
                }
                self._applyFilters();
            });
        });
    };

    RelationshipGraph.prototype._applyFilters = function () {
        var showCustom = document.getElementById(this.showCustomId);
        var showNotCustom = document.getElementById(this.showNotCustomId);
        var showModified = document.getElementById(this.showModifiedId);
        var showNetNew = document.getElementById(this.showNetNewId);
        var showDirectScope = document.getElementById(this.showDirectScopeId);
        var showAdjacentScope = document.getElementById(this.showAdjacentScopeId);
        var showOutOfScope = document.getElementById(this.showOutOfScopeId);
        var showScopeUnknown = document.getElementById(this.showScopeUnknownId);

        var allowCustom = !(showCustom && !showCustom.checked);
        var allowNotCustom = !(showNotCustom && !showNotCustom.checked);
        var allowModified = !(showModified && !showModified.checked);
        var allowNetNew = !(showNetNew && !showNetNew.checked);
        var allowDirectScope = !(showDirectScope && !showDirectScope.checked);
        var allowAdjacentScope = !(showAdjacentScope && !showAdjacentScope.checked);
        var allowOutOfScope = !(showOutOfScope && !showOutOfScope.checked);
        var allowScopeUnknown = !(showScopeUnknown && !showScopeUnknown.checked);
        if (showModified) showModified.disabled = !allowCustom;
        if (showNetNew) showNetNew.disabled = !allowCustom;

        this.cy.nodes().forEach(function (node) {
            var isArtifact = node.data('node_type') === 'artifact';
            if (!isArtifact) {
                node.removeClass('hidden-node');
                return;
            }

            var isCustomized = !!node.data('is_customized');
            var origin = String(node.data('origin_type') || '').toLowerCase();
            var scopeState = String(node.data('scope_state') || 'unknown').toLowerCase();
            var artifactTypeKey = String(node.data('artifact_type_key') || node.data('table_name') || '').trim();
            var hideNode = false;

            if (isCustomized) {
                if (!allowCustom) {
                    hideNode = true;
                } else if (origin === 'modified_ootb' && !allowModified) {
                    hideNode = true;
                } else if (origin === 'net_new_customer' && !allowNetNew) {
                    hideNode = true;
                }
            } else if (!allowNotCustom) {
                hideNode = true;
            }

            if (!hideNode) {
                if (scopeState === 'direct' && !allowDirectScope) {
                    hideNode = true;
                } else if (scopeState === 'adjacent' && !allowAdjacentScope) {
                    hideNode = true;
                } else if (scopeState === 'out_of_scope' && !allowOutOfScope) {
                    hideNode = true;
                } else if (scopeState === 'unknown' && !allowScopeUnknown) {
                    hideNode = true;
                }
            }

            if (!hideNode && artifactTypeKey && this.activeArtifactTypes.size > 0 && !this.activeArtifactTypes.has(artifactTypeKey)) {
                hideNode = true;
            }

            node.toggleClass('hidden-node', hideNode);
        }.bind(this));

        var activeEdgeTypes = this.activeEdgeTypes;
        this.cy.edges().forEach(function (edge) {
            var edgeType = edge.data('edge_type');
            var sourceHidden = edge.source().hasClass('hidden-node') || edge.source().hasClass('table-crowded-hidden');
            var targetHidden = edge.target().hasClass('hidden-node') || edge.target().hasClass('table-crowded-hidden');
            var hideByType = !activeEdgeTypes.has(edgeType);
            edge.toggleClass('hidden-edge', hideByType || sourceHidden || targetHidden);
        });

        this._updateStats();
    };

    RelationshipGraph.prototype._updateStats = function () {
        var nodeCount = this.cy ? this.cy.nodes(':visible').length : 0;
        var edgeCount = this.cy ? this.cy.edges(':visible').length : 0;
        var nodeCountEl = document.getElementById(this.nodeCountId);
        var edgeCountEl = document.getElementById(this.edgeCountId);
        if (nodeCountEl) nodeCountEl.textContent = String(nodeCount);
        if (edgeCountEl) edgeCountEl.textContent = String(edgeCount);
    };

    RelationshipGraph.prototype._runLayout = function () {
        if (!this.cy) return;
        var self = this;
        var visibleNodeCount = this.cy.nodes(':visible').length;
        var spacingFactor = visibleNodeCount <= 10 ? 1.75 : (visibleNodeCount <= 20 ? 1.6 : (visibleNodeCount <= 35 ? 1.45 : 1.3));
        var idealEdgeLength = visibleNodeCount <= 10 ? 190 : (visibleNodeCount <= 20 ? 165 : (visibleNodeCount <= 35 ? 145 : 125));
        var nodeRepulsion = visibleNodeCount <= 10 ? 1000000 : (visibleNodeCount <= 20 ? 850000 : (visibleNodeCount <= 35 ? 760000 : 650000));

        var layout = this.cy.layout({
            name: 'cose',
            animate: true,
            fit: false,
            padding: 36,
            nodeRepulsion: nodeRepulsion,
            idealEdgeLength: idealEdgeLength,
            edgeElasticity: 80,
            gravity: 0.6,
            spacingFactor: spacingFactor,
        });

        layout.on('layoutstop', function () {
            if (!self.cy) return;
            self._applyDevChainOverlapLayout();
            if (self._isFitAllEnabled()) {
                self.cy.fit(self.cy.elements(':visible'), 44);
                return;
            }
            var targetZoom = self._targetZoomForCount(self.cy.nodes(':visible').length);
            if (self._hasVisibleDevChainStack()) {
                targetZoom = Math.max(targetZoom, 1.02);
            }
            var centerNode = self.currentCenterNodeId ? self.cy.getElementById(self.currentCenterNodeId) : null;
            if (centerNode && centerNode.length && centerNode.visible()) {
                self.cy.animate({
                    center: { eles: centerNode },
                    zoom: targetZoom,
                    duration: 240,
                });
            } else {
                self.cy.animate({
                    fit: { eles: self.cy.elements(':visible'), padding: 90 },
                    duration: 200,
                });
            }
        });
        layout.run();
    };

    RelationshipGraph.prototype._applyDevChainOverlapLayout = function () {
        if (!this.cy || this.currentMode !== 'artifact' || !this.currentCenterNodeId) return;
        var centerNode = this.cy.getElementById(this.currentCenterNodeId);
        if (!centerNode || !centerNode.length || !centerNode.visible()) return;

        var centerPos = centerNode.position();
        var priority = {
            artifact_record: 1,
            customer_update_xml: 2,
            version_history: 3,
            version_history_group: 4,
            metadata_customization: 5,
            update_set: 6,
        };
        var chainNodes = [];
        this.cy.nodes('[node_type = "dev_record"], [node_type = "dev_group"]').forEach(function (node) {
            if (!node.visible()) return;
            if (String(node.data('dev_chain_anchor') || '') !== String(centerNode.id())) return;
            chainNodes.push(node);
        });
        if (!chainNodes.length) return;

        chainNodes.sort(function (a, b) {
            var roleA = String(a.data('dev_chain_role') || 'related');
            var roleB = String(b.data('dev_chain_role') || 'related');
            var priA = priority[roleA] || 99;
            var priB = priority[roleB] || 99;
            if (priA !== priB) return priA - priB;
            return String(a.data('label') || a.id()).localeCompare(String(b.data('label') || b.id()));
        });

        // Staircase stack: front card starts top-right, each next card moves down-left.
        var baseX = centerPos.x + 88;
        var baseY = centerPos.y - 68;
        var stepX = -16;
        var stepY = 16;
        var zBase = 2600;
        var zStep = 10;

        for (var i = 0; i < chainNodes.length; i++) {
            var node = chainNodes[i];
            node.position({
                x: baseX + (stepX * i),
                y: baseY + (stepY * i),
            });
            node.data('z_index', zBase - (i * zStep));
            node.data('label_dx', 26 + (i * 9));
            node.data('label_dy', -20 - (i * 4));
            node.data('label_valign', 'top');
            node.data('label_halign', 'left');
        }
    };

    RelationshipGraph.prototype._hasVisibleDevChainStack = function () {
        if (!this.cy) return false;
        var count = 0;
        this.cy.nodes('[node_type = "dev_record"], [node_type = "dev_group"]').forEach(function (node) {
            if (node.visible()) count += 1;
        });
        return count > 0;
    };

    RelationshipGraph.prototype._isFitAllEnabled = function () {
        var toggle = document.getElementById(this.fitAllToggleId);
        return !!(toggle && toggle.checked);
    };

    RelationshipGraph.prototype._targetZoomForCount = function (visibleCount) {
        if (visibleCount <= 6) return 1.15;
        if (visibleCount <= 12) return 1.03;
        if (visibleCount <= 20) return 0.96;
        if (visibleCount <= 30) return 0.9;
        if (visibleCount <= 45) return 0.83;
        return 0.76;
    };

    RelationshipGraph.prototype._searchNode = function () {
        var input = document.getElementById(this.searchInputId);
        if (!input) return;
        var term = String(input.value || '').trim().toLowerCase();
        if (!term) return;

        var match = this.cy.nodes().filter(function (node) {
            var label = String(node.data('label') || '').toLowerCase();
            var name = String(node.data('name') || '').toLowerCase();
            return label.indexOf(term) !== -1 || name.indexOf(term) !== -1;
        });

        if (!match.length) {
            this._setStatus('No matching nodes for "' + term + '".');
            return;
        }

        var node = match[0];
        this.cy.nodes().removeClass('selected-node');
        node.addClass('selected-node');
        this._focusNode(node.id());
        this._renderDetail(node.data());
        this._pushBreadcrumb(node.id(), node.data('label') || node.id());
    };

    RelationshipGraph.prototype._focusNode = function (nodeId) {
        if (!this.cy || !nodeId) return;
        var node = this.cy.getElementById(nodeId);
        if (!node || !node.length) return;
        this.cy.animate({
            center: { eles: node },
            zoom: Math.max(this.cy.zoom(), 0.85),
            duration: 260,
        });
    };

    RelationshipGraph.prototype._pushBreadcrumb = function (nodeId, label) {
        if (!nodeId) return;
        var last = this.breadcrumbs.length ? this.breadcrumbs[this.breadcrumbs.length - 1] : null;
        if (last && last.id === nodeId) return;

        this.breadcrumbs.push({ id: nodeId, label: label || nodeId });
        if (this.breadcrumbs.length > 14) this.breadcrumbs.shift();
        this._renderBreadcrumbs();
    };

    RelationshipGraph.prototype._renderBreadcrumbs = function () {
        var container = document.getElementById(this.breadcrumbsId);
        if (!container) return;

        if (!this.breadcrumbs.length) {
            container.innerHTML = '<span class="text-muted-sm">No path yet.</span>';
            return;
        }

        var html = '';
        for (var i = 0; i < this.breadcrumbs.length; i++) {
            var crumb = this.breadcrumbs[i];
            html += '<button type="button" class="rg-crumb" data-crumb-id="' + this._esc(crumb.id) + '">' + this._esc(crumb.label) + '</button>';
        }
        container.innerHTML = html;

        var self = this;
        container.querySelectorAll('[data-crumb-id]').forEach(function (button) {
            button.addEventListener('click', function () {
                var id = button.getAttribute('data-crumb-id');
                self._focusNode(id);
                var node = self.cy.getElementById(id);
                if (node && node.length) {
                    self.cy.nodes().removeClass('selected-node');
                    node.addClass('selected-node');
                    self._renderDetail(node.data());
                }
            });
        });
    };

    RelationshipGraph.prototype._renderDetail = function (node) {
        var container = document.getElementById(this.detailBodyId);
        if (!container || !node) return;

        var html = '';
        html += '<div class="rg-meta-row"><strong>' + this._esc(node.label || node.name || node.id) + '</strong></div>';

        if (node.node_type === 'artifact') {
            var badges = '';
            if (node.is_customized) {
                badges += '<span class="rg-badge rg-badge-custom">Customized</span>';
            } else {
                badges += '<span class="rg-badge">OOTB</span>';
            }
            if (node.origin_type === 'modified_ootb') {
                badges += '<span class="rg-badge rg-badge-modified">OOTB Modified</span>';
            }
            if (node.origin_type === 'net_new_customer') {
                badges += '<span class="rg-badge rg-badge-netnew">Customer Created</span>';
            }
            if (node.is_out_of_scope) {
                badges += '<span class="rg-badge">Out Of Scope</span>';
            } else if (node.is_adjacent) {
                badges += '<span class="rg-badge">Adjacent</span>';
            } else if (node.scope_state === 'direct') {
                badges += '<span class="rg-badge">Direct In Scope</span>';
            } else if (node.scope_state === 'unknown') {
                badges += '<span class="rg-badge">Scope Unknown</span>';
            }
            html += '<div class="rg-meta-row">' + badges + '</div>';
            if (node.artifact_type_label) {
                html += '<div class="rg-meta-row"><strong>Artifact Type:</strong> ' + this._esc(node.artifact_type_label) + '</div>';
            }
            html += '<div class="rg-meta-row"><strong>App File Class:</strong> <code>' + this._esc(node.table_name || '-') + '</code></div>';
            html += '<div class="rg-meta-row"><strong>Sys ID:</strong> <code>' + this._esc(node.sys_id || '-') + '</code></div>';
            if (node.result_id != null) {
                html += '<div class="rg-meta-row"><strong>Result ID:</strong> <code>' + this._esc(node.result_id) + '</code></div>';
            }
            if (node.feature_names && node.feature_names.length) {
                html += '<div class="rg-meta-row"><strong>Features:</strong> ' + this._esc(node.feature_names.join(', ')) + '</div>';
            }
        } else if (node.node_type === 'feature') {
            html += '<div class="rg-meta-row"><span class="rg-badge">Feature</span></div>';
            if (node.description) {
                html += '<div class="rg-meta-row"><strong>Description:</strong> ' + this._esc(node.description) + '</div>';
            }
            if (node.disposition) {
                html += '<div class="rg-meta-row"><strong>Disposition:</strong> ' + this._esc(String(node.disposition).replace(/_/g, ' ')) + '</div>';
            }
            if (node.confidence_score != null) {
                html += '<div class="rg-meta-row"><strong>Confidence:</strong> ' + Math.round(Number(node.confidence_score) * 100) + '%</div>';
            }
        } else if (node.node_type === 'table') {
            html += '<div class="rg-meta-row"><span class="rg-badge">Table</span></div>';
            html += '<div class="rg-meta-row"><strong>Name:</strong> <code>' + this._esc(node.table_name || node.name || '-') + '</code></div>';
        } else if (node.node_type === 'dev_record') {
            var devKind = String(node.dev_kind || '').replace(/_/g, ' ');
            html += '<div class="rg-meta-row"><span class="rg-badge">' + this._esc(devKind || 'Related Record') + '</span></div>';
            if (node.table_name) {
                html += '<div class="rg-meta-row"><strong>Table:</strong> <code>' + this._esc(node.table_name) + '</code></div>';
            }
            if (node.sys_id) {
                html += '<div class="rg-meta-row"><strong>Sys ID:</strong> <code>' + this._esc(node.sys_id) + '</code></div>';
            }
            if (node.record_id != null) {
                html += '<div class="rg-meta-row"><strong>Local Record ID:</strong> <code>' + this._esc(node.record_id) + '</code></div>';
            }
            if (node.state) {
                html += '<div class="rg-meta-row"><strong>State:</strong> ' + this._esc(node.state) + '</div>';
            }
        } else if (node.node_type === 'dev_group') {
            html += '<div class="rg-meta-row"><span class="rg-badge">Grouped Records</span></div>';
            if (node.total_count != null) {
                html += '<div class="rg-meta-row"><strong>Total:</strong> ' + this._esc(node.total_count) + '</div>';
            }
            if (node.hidden_count != null) {
                html += '<div class="rg-meta-row"><strong>Grouped:</strong> ' + this._esc(node.hidden_count) + '</div>';
            }
        }

        var linksHtml = this._renderLinks(node.links);
        if (linksHtml) {
            html += '<div class="rg-meta-row"><strong>Open:</strong> ' + linksHtml + '</div>';
        }

        container.innerHTML = html;
    };

    RelationshipGraph.prototype._renderLinks = function (links) {
        if (!links || typeof links !== 'object') return '';
        var labelMap = {
            result: 'Result',
            assessment: 'Assessment',
            graph: 'Relationship Graph',
            dependency_map: 'Dependency Map',
            artifact_record: 'Artifact Record',
            artifact_table: 'Artifact Table',
            record: 'Record',
            table: 'Table',
            data_record: 'Data Record',
        };
        var keys = Object.keys(links);
        if (!keys.length) return '';
        var items = [];
        for (var i = 0; i < keys.length; i++) {
            var key = keys[i];
            var url = links[key];
            if (!url) continue;
            var label = labelMap[key] || key.replace(/_/g, ' ');
            items.push('<a href="' + this._esc(url) + '">' + this._esc(label) + '</a>');
        }
        return items.join(' · ');
    };

    RelationshipGraph.prototype._setStatus = function (text) {
        var status = document.getElementById(this.statusId);
        if (status) status.textContent = text;
    };

    RelationshipGraph.prototype._esc = function (value) {
        if (value == null) return '';
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(String(value)));
        return div.innerHTML;
    };

    window.RelationshipGraph = RelationshipGraph;
})();
