/**
 * ResultsFilterTable — Reusable scan results list with classification + class filters.
 *
 * Consolidates the duplicated results rendering/filtering pipeline from
 * assessment_detail.html and scan_detail.html.
 *
 * Usage:
 *   var rft = new ResultsFilterTable({
 *       resultsApiUrl: '/api/assessments/5/results',
 *       optionsApiUrl: '/api/results/options',
 *       optionsApiBaseParams: { instance_id: '2', assessment_ids: '5' },
 *       bodyId: 'assessmentResultsBody',
 *       emptyId: 'assessmentResultsEmpty',
 *       loadingId: 'assessmentResultsLoading',
 *       metaId: 'assessmentResultsMeta',
 *       classificationId: 'assessmentResultsClassification',
 *       classFilterId: 'assessmentResultsClassFilter',
 *       showScanColumn: true,
 *       onCounts: function(payload, scopedCount) { ... },
 *   });
 *   rft.bindControls('assessmentResultsApply', 'assessmentResultsReset');
 *   rft.refresh();
 */
window.ResultsFilterTable = (function () {
    'use strict';

    // ── Classification → API params mapping ──
    // Used by both the options fetch and the results fetch.
    function classificationToParams(classificationVal) {
        var p = {};
        if (classificationVal === 'all') {
            p.customized_only = 'false';
        } else if (classificationVal === 'customized') {
            p.customized_only = 'true';
            p.customization_type = 'all';
        } else if (classificationVal === 'modified_ootb') {
            p.customized_only = 'true';
            p.customization_type = 'modified_ootb';
        } else if (classificationVal === 'net_new_customer') {
            p.customized_only = 'true';
            p.customization_type = 'net_new_customer';
        } else if (classificationVal === 'ootb_untouched') {
            p.customized_only = 'false';
            p.customization_type = 'ootb_untouched';
        } else if (classificationVal === 'unknown') {
            p.customized_only = 'false';
            p.customization_type = 'unknown';
        } else if (classificationVal === 'uncustomized') {
            p.customized_only = 'false';
            p.customization_type = 'uncustomized';
        }
        return p;
    }

    function ResultsFilterTable(opts) {
        this.resultsApiUrl = opts.resultsApiUrl;
        this.optionsApiUrl = opts.optionsApiUrl || '/api/results/options';
        this.optionsApiBaseParams = opts.optionsApiBaseParams || {};
        this.fixedParams = opts.fixedParams || {};
        this.bodyId = opts.bodyId;
        this.emptyId = opts.emptyId;
        this.loadingId = opts.loadingId;
        this.metaId = opts.metaId;
        this.classificationId = opts.classificationId;
        this.classFilterId = opts.classFilterId;
        this.showScanColumn = opts.showScanColumn || false;
        // Optional callbacks
        this.onCounts = opts.onCounts || null; // function(payload, scopedCount)
        this.onMeta = opts.onMeta || null;     // function(payload, scopedCount) → string
    }

    ResultsFilterTable.prototype.setLoading = function (isLoading) {
        var overlay = document.getElementById(this.loadingId);
        if (overlay) overlay.style.display = isLoading ? 'flex' : 'none';
    };

    ResultsFilterTable.prototype.renderRows = function (rows) {
        var tbody = document.getElementById(this.bodyId);
        var empty = document.getElementById(this.emptyId);
        if (!tbody || !empty) return;

        if (!rows.length) {
            tbody.innerHTML = '';
            empty.style.display = 'block';
            return;
        }

        empty.style.display = 'none';
        var showScan = this.showScanColumn;
        tbody.innerHTML = rows.map(function (row) {
            var classification = row.customization_classification
                ? row.customization_classification.replaceAll('_', ' ') : '-';
            var originClass = row.origin_type ? 'origin-' + row.origin_type : '';
            var originCell = row.origin_type
                ? '<span class="origin-badge ' + originClass + '">' + classification + '</span>'
                : '-';
            var scanCell = showScan
                ? '<td>' + (row.scan && row.scan.name ? row.scan.name : '-') + '</td>'
                : '';
            return '<tr>'
                + '<td><a href="/results/' + row.id + '">' + (row.name || row.sys_id) + '</a></td>'
                + '<td><code>' + (row.table_name || '-') + '</code></td>'
                + scanCell
                + '<td>' + (row.is_customized ? 'Yes' : 'No') + '</td>'
                + '<td>' + originCell + '</td>'
                + '<td>' + (row.review_status ? row.review_status.replaceAll('_', ' ') : '-') + '</td>'
                + '<td>' + (row.disposition ? row.disposition.replaceAll('_', ' ') : '-') + '</td>'
                + '<td>' + formatDate(row.sys_updated_on) + '</td>'
                + '<td><a class="btn btn-sm" href="/results/' + row.id + '">View</a></td>'
                + '</tr>';
        }).join('');
    };

    ResultsFilterTable.prototype._getClassificationValue = function () {
        var el = document.getElementById(this.classificationId);
        return el ? el.value : 'all';
    };

    ResultsFilterTable.prototype._loadClassOptions = function () {
        var self = this;
        var classFilter = document.getElementById(this.classFilterId);
        if (!classFilter) return Promise.resolve(null);

        var classVal = this._getClassificationValue();
        var baseParams = Object.assign({}, this.optionsApiBaseParams, this.fixedParams, classificationToParams(classVal));
        var params = new URLSearchParams(baseParams);

        var currentValue = classFilter.value;
        return fetch(this.optionsApiUrl + '?' + params.toString(), { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (payload) {
                if (!payload) return null;
                var options = payload.app_file_classes || [];
                classFilter.innerHTML = '<option value="">All Classes</option>';
                options.forEach(function (value) {
                    var opt = document.createElement('option');
                    opt.value = value;
                    opt.textContent = value;
                    classFilter.appendChild(opt);
                });
                if (currentValue && options.includes(currentValue)) {
                    classFilter.value = currentValue;
                }
                return Number(payload.scoped_count != null ? payload.scoped_count : 0);
            })
            .catch(function () { return null; });
    };

    ResultsFilterTable.prototype.refresh = function () {
        var self = this;
        var meta = document.getElementById(this.metaId);
        var classFilter = document.getElementById(this.classFilterId);
        if (!classFilter) return;

        this.setLoading(true);
        if (meta) meta.textContent = 'Loading...';

        this._loadClassOptions()
            .then(function (scopedCount) {
                var classVal = self._getClassificationValue();
                var apiParams = Object.assign({ limit: '500' }, self.fixedParams, classificationToParams(classVal));
                if (classFilter.value) {
                    apiParams.app_file_classes = classFilter.value;
                }
                var params = new URLSearchParams(apiParams);

                return fetch(self.resultsApiUrl + '?' + params.toString(), { cache: 'no-store' })
                    .then(function (r) {
                        if (!r.ok) throw new Error('Request failed');
                        return r.json();
                    })
                    .then(function (payload) {
                        self.renderRows(payload.results || []);

                        // Let caller handle counts/badge updates
                        if (self.onCounts) {
                            self.onCounts(payload, scopedCount);
                        }

                        // Meta text
                        if (meta) {
                            if (self.onMeta) {
                                meta.textContent = self.onMeta(payload, scopedCount);
                            } else {
                                var count = Number(payload.count || 0);
                                var total = Number(payload.total || 0);
                                meta.textContent = 'Showing ' + count + ' of ' + total + ' results';
                            }
                        }
                    });
            })
            .catch(function () {
                self.renderRows([]);
                if (self.onCounts) {
                    self.onCounts(null, null);
                }
                if (meta) meta.textContent = 'Failed to load results.';
            })
            .then(function () {
                self.setLoading(false);
            });
    };

    ResultsFilterTable.prototype.bindControls = function (applyId, resetId) {
        var self = this;
        var classification = document.getElementById(this.classificationId);
        var classFilter = document.getElementById(this.classFilterId);
        var apply = document.getElementById(applyId);
        var reset = document.getElementById(resetId);

        if (classification) classification.addEventListener('change', function () { self.refresh(); });
        if (classFilter) classFilter.addEventListener('change', function () { self.refresh(); });
        if (apply) apply.addEventListener('click', function () { self.refresh(); });
        if (reset) reset.addEventListener('click', function () {
            if (classification) classification.value = 'all';
            if (classFilter) classFilter.value = '';
            self.refresh();
        });
    };

    // Export the params helper for external use (e.g., customizations tab reuse)
    ResultsFilterTable.classificationToParams = classificationToParams;

    return ResultsFilterTable;
})();
