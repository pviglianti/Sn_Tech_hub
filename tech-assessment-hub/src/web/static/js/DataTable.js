/**
 * DataTable — Reusable, schema-driven table component.
 *
 * Usage:
 *   const dt = new DataTable(containerEl, {
 *     dataUrl:    '/api/dynamic-browser/records',
 *     schemaUrl:  '/api/dynamic-browser/field-schema?table=X&instance_id=Y',
 *     instanceId: 2,
 *     tableName:  'cmdb_ci_service',
 *     onReferenceClick: (refTable, sysIdValue) => { ... },
 *     onRecordClick:    (sysId) => { ... },
 *     pageSize:   50,
 *     storageKey: 'dt_cmdb_ci_service_2',
 *     initialFilter: { field: 'sys_id', value: 'abc123' },
 *     initialConditions: { logic: 'AND', conditions: [...] },
 *     includeTableAndInstanceParams: false, // for non-table APIs
 *   });
 *   await dt.init();
 */
window.DataTable = (function () {
    'use strict';

    var PRIORITY_COLS = ['name', 'number', 'short_description', 'state', 'sys_updated_on', 'category', 'u_name'];
    var MAX_DEFAULT_COLS = 10;
    var PAGE_SIZES = [25, 50, 100, 200];

    function DataTable(container, opts) {
        this.container = container;
        this.dataUrl = opts.dataUrl;
        this.schemaUrl = opts.schemaUrl;
        this.instanceId = opts.instanceId;
        this.tableName = opts.tableName;
        this.onReferenceClick = opts.onReferenceClick || function () {};
        this.onRecordClick = opts.onRecordClick || function () {};
        this.pageSize = opts.pageSize || 50;
        this.storageKey = opts.storageKey || ('dt_' + opts.tableName + '_' + opts.instanceId);
        this.initialFilter = opts.initialFilter || null;
        this.initialConditions = opts.initialConditions || null;
        this.includeTableAndInstanceParams = opts.includeTableAndInstanceParams !== false;

        // Extension: custom cell renderers — map of column_name → function(value, rowData, tdElement)
        this.customRenderers = opts.customRenderers || {};

        // Extension: row selection checkboxes
        this.selectable = !!opts.selectable;
        this.onSelectionChange = opts.onSelectionChange || function () {};
        this._selectedRowIds = new Set();
        this._rowIdField = opts.rowIdField || 'id';

        this.schema = null;
        this.fields = [];
        this.visibleColumns = [];
        this.sortField = null;
        this.sortDir = 'asc';
        this.offset = 0;
        this.total = 0;
        this.rows = [];
        this.conditions = null;
        this._loading = false;
        this._conditionBuilder = null;
        this._fetchSeq = 0;
    }

    DataTable.prototype.init = async function () {
        this._buildSkeleton();
        await this._fetchSchema();
        this._restorePrefs();

        // Set up condition builder
        if (window.ConditionBuilder && this._cbContainer) {
            this._conditionBuilder = new window.ConditionBuilder(this._cbContainer, {
                fields: this.fields,
                availableTables: this._availableTables,
                onChange: function (conds) {
                    this.conditions = conds;
                    this.offset = 0;
                    this.refresh();
                }.bind(this),
            });

            // If there are initial conditions, preload them into the builder.
            if (this.initialConditions && typeof this._conditionBuilder.setConditions === 'function') {
                this._conditionBuilder.setConditions(this.initialConditions, true);
                this.conditions = this._conditionBuilder.getConditions();
            } else if (this.initialFilter && this.initialFilter.field && this.initialFilter.value) {
                // Backward-compatible single-field preload.
                this._conditionBuilder._addRow();
                var row = this._conditionBuilder.rows[0];
                row.field = this.initialFilter.field;
                row.operator = 'is';
                row.value = this.initialFilter.value;
                this._conditionBuilder._rebuildRows();
                this.conditions = this._conditionBuilder.getConditions();
            }
        }

        await this.refresh();
    };

    DataTable.prototype._buildSkeleton = function () {
        this.container.innerHTML = '';
        this.container.classList.add('dt-container');

        // Condition builder area
        this._cbContainer = document.createElement('div');
        this._cbContainer.className = 'dt-condition-area';
        this.container.appendChild(this._cbContainer);

        // Toolbar: column picker + page size + info
        var toolbar = document.createElement('div');
        toolbar.className = 'dt-toolbar';

        // Column picker button
        var colPickerWrap = document.createElement('div');
        colPickerWrap.className = 'dt-col-picker-wrap';

        var colBtn = document.createElement('button');
        colBtn.type = 'button';
        colBtn.className = 'btn btn-sm btn-secondary dt-col-picker-btn';
        colBtn.innerHTML = '&#9776; Columns';
        colBtn.addEventListener('click', this._toggleColumnPicker.bind(this));
        colPickerWrap.appendChild(colBtn);

        this._colPickerDropdown = document.createElement('div');
        this._colPickerDropdown.className = 'dt-col-picker-dropdown';
        this._colPickerDropdown.style.display = 'none';
        colPickerWrap.appendChild(this._colPickerDropdown);

        toolbar.appendChild(colPickerWrap);

        // Page size selector
        var pageSizeWrap = document.createElement('div');
        pageSizeWrap.className = 'dt-pagesize-wrap';
        var pageSizeLabel = document.createElement('span');
        pageSizeLabel.className = 'dt-pagesize-label';
        pageSizeLabel.textContent = 'Show:';
        pageSizeWrap.appendChild(pageSizeLabel);

        this._pageSizeSelect = document.createElement('select');
        this._pageSizeSelect.className = 'form-control dt-pagesize-select';
        PAGE_SIZES.forEach(function (s) {
            var opt = document.createElement('option');
            opt.value = s;
            opt.textContent = s;
            if (s === this.pageSize) opt.selected = true;
            this._pageSizeSelect.appendChild(opt);
        }.bind(this));
        this._pageSizeSelect.addEventListener('change', function () {
            this.pageSize = parseInt(this._pageSizeSelect.value, 10);
            this.offset = 0;
            this.refresh();
        }.bind(this));
        pageSizeWrap.appendChild(this._pageSizeSelect);
        toolbar.appendChild(pageSizeWrap);

        // Info text
        this._infoEl = document.createElement('span');
        this._infoEl.className = 'dt-info';
        toolbar.appendChild(this._infoEl);

        this.container.appendChild(toolbar);

        // Table scroll wrapper (with loading overlay)
        var scrollWrap = document.createElement('div');
        scrollWrap.className = 'table-scroll dt-table-scroll';

        this._loadingOverlay = document.createElement('div');
        this._loadingOverlay.className = 'table-loading-overlay';
        this._loadingOverlay.style.display = 'none';
        this._loadingOverlay.innerHTML =
            '<div class="table-loading-pill"><span class="table-spinner"></span> Loading…</div>';
        scrollWrap.appendChild(this._loadingOverlay);

        this._tableEl = document.createElement('table');
        this._tableEl.className = 'data-table dt-table';
        this._thead = document.createElement('thead');
        this._tbody = document.createElement('tbody');
        this._tableEl.appendChild(this._thead);
        this._tableEl.appendChild(this._tbody);
        scrollWrap.appendChild(this._tableEl);

        this.container.appendChild(scrollWrap);

        // Pagination
        var pager = document.createElement('div');
        pager.className = 'dt-pager';

        this._prevBtn = document.createElement('button');
        this._prevBtn.type = 'button';
        this._prevBtn.className = 'btn btn-sm btn-secondary';
        this._prevBtn.textContent = '← Previous';
        this._prevBtn.addEventListener('click', this._prevPage.bind(this));
        pager.appendChild(this._prevBtn);

        this._pageInfoEl = document.createElement('span');
        this._pageInfoEl.className = 'dt-page-info';
        pager.appendChild(this._pageInfoEl);

        this._nextBtn = document.createElement('button');
        this._nextBtn.type = 'button';
        this._nextBtn.className = 'btn btn-sm btn-secondary';
        this._nextBtn.textContent = 'Next →';
        this._nextBtn.addEventListener('click', this._nextPage.bind(this));
        pager.appendChild(this._nextBtn);

        this.container.appendChild(pager);

        // Close column picker on outside click
        document.addEventListener('click', function (e) {
            if (!colPickerWrap.contains(e.target)) {
                this._colPickerDropdown.style.display = 'none';
            }
        }.bind(this));
    };

    DataTable.prototype._fetchSchema = async function () {
        var res = await fetch(this.schemaUrl);
        if (!res.ok) throw new Error('Failed to load schema: ' + res.status);
        this.schema = await res.json();
        this.fields = this.schema.fields || [];
        // Set of tables that exist locally — used to decide if reference
        // links are browseable (blue + clickable) vs just underlined.
        this._availableTables = {};
        (this.schema.available_tables || []).forEach(function (t) {
            this._availableTables[t] = true;
        }.bind(this));
    };

    DataTable.prototype._restorePrefs = function () {
        var savedCols = null;
        try {
            var raw = localStorage.getItem(this.storageKey + '_columns');
            if (raw) savedCols = JSON.parse(raw);
        } catch (e) { /* ignore */ }

        if (savedCols && Array.isArray(savedCols) && savedCols.length > 0) {
            this.visibleColumns = savedCols;
        } else {
            this._pickDefaultColumns();
        }
    };

    DataTable.prototype._pickDefaultColumns = function () {
        // Delegate to ColumnPicker if available, otherwise use built-in fallback
        if (window.ColumnPicker) {
            var tmp = new window.ColumnPicker(document.createElement('div'), {
                fields: this.fields,
                selected: [],
            });
            this.visibleColumns = tmp._pickDefaults();
            tmp.destroy();
        } else {
            var fieldNames = this.fields.map(function (f) { return f.local_column; });
            var chosen = [];
            PRIORITY_COLS.forEach(function (c) {
                if (fieldNames.indexOf(c) !== -1 && chosen.length < MAX_DEFAULT_COLS) chosen.push(c);
            });
            this.fields.forEach(function (f) {
                if (chosen.length >= MAX_DEFAULT_COLS) return;
                if (chosen.indexOf(f.local_column) === -1) chosen.push(f.local_column);
            });
            this.visibleColumns = chosen;
        }
    };

    DataTable.prototype._savePrefs = function () {
        try {
            localStorage.setItem(this.storageKey + '_columns', JSON.stringify(this.visibleColumns));
        } catch (e) { /* ignore */ }
    };

    DataTable.prototype.refresh = async function () {
        if (this._loading) return;
        this._loading = true;
        this._loadingOverlay.style.display = 'flex';

        var seq = ++this._fetchSeq;

        var queryParts = [
            'offset=' + this.offset,
            'limit=' + this.pageSize,
        ];

        if (this.includeTableAndInstanceParams) {
            queryParts.unshift(
                'instance_id=' + this.instanceId
            );
            queryParts.unshift(
                'table=' + encodeURIComponent(this.tableName)
            );
        }

        var url = this.dataUrl +
            (this.dataUrl.indexOf('?') === -1 ? '?' : '&') +
            queryParts.join('&');

        if (this.sortField) {
            url += '&sort_field=' + encodeURIComponent(this.sortField);
            url += '&sort_dir=' + this.sortDir;
        }

        if (this.conditions) {
            url += '&conditions=' + encodeURIComponent(JSON.stringify(this.conditions));
        }

        try {
            var res = await fetch(url);
            if (seq !== this._fetchSeq) return; // stale
            if (!res.ok) throw new Error('Records fetch failed: ' + res.status);
            var data = await res.json();
            if (seq !== this._fetchSeq) return;

            this.total = data.total || 0;
            this.rows = data.rows || [];
            this._renderTable();
            this._renderPager();
        } catch (err) {
            console.error('[DataTable] fetch error:', err);
            this._tbody.innerHTML =
                '<tr><td colspan="99" style="text-align:center;color:var(--danger-color);padding:2rem;">' +
                'Error loading data: ' + err.message + '</td></tr>';
        } finally {
            this._loading = false;
            this._loadingOverlay.style.display = 'none';
        }
    };

    DataTable.prototype._renderTable = function () {
        var self = this;
        var fieldMap = {};
        this.fields.forEach(function (f) { fieldMap[f.local_column] = f; });

        // Render thead
        this._thead.innerHTML = '';
        var headerRow = document.createElement('tr');

        // Selection checkbox column header
        if (this.selectable) {
            var selectTh = document.createElement('th');
            selectTh.className = 'dt-th dt-th-select';
            selectTh.style.width = '36px';
            var selectAllCb = document.createElement('input');
            selectAllCb.type = 'checkbox';
            selectAllCb.title = 'Select/deselect all visible rows';
            selectAllCb.addEventListener('change', function () {
                self._toggleSelectAll(selectAllCb.checked);
            });
            this._selectAllCheckbox = selectAllCb;
            selectTh.appendChild(selectAllCb);
            headerRow.appendChild(selectTh);
        }

        this.visibleColumns.forEach(function (col) {
            var th = document.createElement('th');
            var fm = fieldMap[col];
            var label = fm ? (fm.column_label || col) : col;

            th.className = 'dt-th';
            if (fm && fm.is_reference) th.classList.add('dt-th-ref');
            if (self.sortField === col) {
                th.classList.add(self.sortDir === 'asc' ? 'dt-sort-asc' : 'dt-sort-desc');
            }

            th.textContent = label;
            th.title = col + (fm ? ' (' + (fm.sn_internal_type || fm.kind) + ')' : '');

            th.style.cursor = 'pointer';
            th.addEventListener('click', function () {
                if (self.sortField === col) {
                    self.sortDir = self.sortDir === 'asc' ? 'desc' : 'asc';
                } else {
                    self.sortField = col;
                    self.sortDir = 'asc';
                }
                self.offset = 0;
                self.refresh();
            });

            headerRow.appendChild(th);
        });

        this._thead.appendChild(headerRow);

        // Render tbody
        this._tbody.innerHTML = '';

        var totalCols = this.visibleColumns.length + (this.selectable ? 1 : 0);

        if (this.rows.length === 0) {
            var emptyRow = document.createElement('tr');
            var emptyTd = document.createElement('td');
            emptyTd.colSpan = totalCols || 1;
            emptyTd.className = 'dt-empty';
            emptyTd.textContent = 'No records found';
            emptyRow.appendChild(emptyTd);
            this._tbody.appendChild(emptyRow);
            this._syncSelectAllCheckbox();
            return;
        }

        // Determine the "record link column" — the first visible column
        // that is NOT a reference field and not sys_id.  This column gets
        // rendered as a blue clickable link that opens the record detail.
        var recordLinkCol = null;
        for (var i = 0; i < this.visibleColumns.length; i++) {
            var c = this.visibleColumns[i];
            if (c === 'sys_id') continue;
            var cfm = fieldMap[c];
            if (cfm && cfm.is_reference) continue;
            // Skip columns with custom renderers from being record-link columns
            if (self.customRenderers[c]) continue;
            recordLinkCol = c;
            break;
        }

        this.rows.forEach(function (row) {
            var tr = document.createElement('tr');
            tr.className = 'dt-row';
            var rowSysId = row['sys_id'] || row['sn_sys_id'];
            var rowId = row[self._rowIdField];

            // Selection checkbox cell
            if (self.selectable) {
                var selectTd = document.createElement('td');
                selectTd.className = 'dt-cell dt-cell-select';
                var cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.checked = self._selectedRowIds.has(rowId);
                cb.addEventListener('change', function (e) {
                    e.stopPropagation();
                    if (cb.checked) {
                        self._selectedRowIds.add(rowId);
                    } else {
                        self._selectedRowIds.delete(rowId);
                    }
                    self._syncSelectAllCheckbox();
                    self.onSelectionChange(self.getSelectedRows());
                });
                cb.addEventListener('click', function (e) { e.stopPropagation(); });
                selectTd.appendChild(cb);
                tr.appendChild(selectTd);
            }

            self.visibleColumns.forEach(function (col) {
                var td = document.createElement('td');
                td.className = 'dt-cell';
                var value = row[col];
                var displayVal = value != null ? String(value) : '';
                var fm = fieldMap[col];

                // Custom renderer takes priority
                if (self.customRenderers[col]) {
                    self.customRenderers[col](value, row, td);
                } else if (fm && fm.is_reference && fm.sn_reference_table && displayVal) {
                    var refAvailable = !!self._availableTables[fm.sn_reference_table];
                    if (refAvailable) {
                        // Blue clickable link — table exists locally
                        var link = document.createElement('a');
                        link.href = '/browse/' + encodeURIComponent(fm.sn_reference_table) +
                            '/record/' + encodeURIComponent(displayVal) +
                            '?instance_id=' + self.instanceId;
                        link.className = 'ref-link';
                        link.textContent = displayVal;
                        link.title = 'Open record in ' + fm.sn_reference_table;
                        link.addEventListener('click', function (e) {
                            e.preventDefault();
                            e.stopPropagation();
                            self.onReferenceClick(fm.sn_reference_table, displayVal);
                        });
                        td.appendChild(link);
                    } else {
                        // Underlined but not blue — referenced table not in our DB
                        var span = document.createElement('span');
                        span.className = 'ref-unavailable';
                        span.textContent = displayVal;
                        span.title = fm.sn_reference_table + ' (not available locally)';
                        td.appendChild(span);
                    }
                } else if (col === recordLinkCol && displayVal && rowSysId) {
                    // First content column — blue link that opens this record's detail
                    var recLink = document.createElement('a');
                    recLink.href = '/browse/' + encodeURIComponent(self.tableName) +
                        '/record/' + encodeURIComponent(rowSysId) +
                        '?instance_id=' + self.instanceId;
                    recLink.className = 'ref-link dt-record-link';
                    recLink.textContent = displayVal.length > 120
                        ? displayVal.substring(0, 120) + '…' : displayVal;
                    if (displayVal.length > 120) recLink.title = displayVal;
                    recLink.addEventListener('click', function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        self.onRecordClick(rowSysId, row);
                    });
                    td.appendChild(recLink);
                } else if (col === 'sys_id' && displayVal) {
                    var sysLink = document.createElement('a');
                    sysLink.href = '/browse/' + encodeURIComponent(self.tableName) +
                        '/record/' + encodeURIComponent(displayVal) +
                        '?instance_id=' + self.instanceId;
                    sysLink.className = 'ref-link dt-sysid-link';
                    sysLink.textContent = displayVal.substring(0, 8) + '…';
                    sysLink.title = displayVal;
                    sysLink.addEventListener('click', function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        self.onRecordClick(displayVal, row);
                    });
                    td.appendChild(sysLink);
                } else if (fm && fm.kind === 'date' && displayVal) {
                    // Datetime cell — format using configured display timezone
                    var formatted = (typeof formatDate === 'function') ? formatDate(displayVal) : displayVal;
                    td.textContent = formatted;
                    if (formatted !== displayVal) td.title = displayVal + ' (UTC)';
                } else {
                    // Plain text cell
                    if (displayVal.length > 120) {
                        td.textContent = displayVal.substring(0, 120) + '…';
                        td.title = displayVal;
                    } else {
                        td.textContent = displayVal;
                    }
                }

                tr.appendChild(td);
            });

            // Row click also opens record detail (unless a link was clicked)
            tr.addEventListener('click', function () {
                if (rowSysId) self.onRecordClick(rowSysId, row);
            });

            self._tbody.appendChild(tr);
        });

        this._syncSelectAllCheckbox();

        // Update info
        var from = this.total > 0 ? this.offset + 1 : 0;
        var to = Math.min(this.offset + this.pageSize, this.total);
        this._infoEl.textContent = from + '–' + to + ' of ' + this.total.toLocaleString() + ' records';
    };

    DataTable.prototype._renderPager = function () {
        var currentPage = Math.floor(this.offset / this.pageSize) + 1;
        var totalPages = Math.max(1, Math.ceil(this.total / this.pageSize));
        this._pageInfoEl.textContent = 'Page ' + currentPage + ' of ' + totalPages;
        this._prevBtn.disabled = this.offset <= 0;
        this._nextBtn.disabled = (this.offset + this.pageSize) >= this.total;
    };

    DataTable.prototype._prevPage = function () {
        this.offset = Math.max(0, this.offset - this.pageSize);
        this.refresh();
    };

    DataTable.prototype._nextPage = function () {
        if (this.offset + this.pageSize < this.total) {
            this.offset += this.pageSize;
            this.refresh();
        }
    };

    DataTable.prototype._toggleColumnPicker = function () {
        var dd = this._colPickerDropdown;
        if (dd.style.display === 'none') {
            this._ensureColumnPicker();
            dd.style.display = 'block';
        } else {
            dd.style.display = 'none';
        }
    };

    // Lazily create the ColumnPicker instance inside the dropdown.
    // Delegates all slush-bucket logic to the standalone ColumnPicker component.
    DataTable.prototype._ensureColumnPicker = function () {
        if (this._columnPicker) return;
        if (!window.ColumnPicker) {
            console.warn('[DataTable] ColumnPicker.js not loaded — column picker disabled');
            return;
        }
        var self = this;
        this._columnPicker = new window.ColumnPicker(this._colPickerDropdown, {
            fields: this.fields,
            selected: this.visibleColumns,
            availableTables: this._availableTables,
            onChange: function (selectedColumns) {
                self.visibleColumns = selectedColumns;
                self._savePrefs();
                self._renderTable();
            },
        });
    };

    // ----- Selection helpers -----

    DataTable.prototype._toggleSelectAll = function (checked) {
        var self = this;
        this.rows.forEach(function (row) {
            var rowId = row[self._rowIdField];
            if (rowId == null) return;
            if (checked) {
                self._selectedRowIds.add(rowId);
            } else {
                self._selectedRowIds.delete(rowId);
            }
        });
        // Update checkboxes in DOM
        var cbs = this._tbody.querySelectorAll('.dt-cell-select input[type="checkbox"]');
        cbs.forEach(function (cb) { cb.checked = checked; });
        this.onSelectionChange(this.getSelectedRows());
    };

    DataTable.prototype._syncSelectAllCheckbox = function () {
        if (!this._selectAllCheckbox) return;
        if (this.rows.length === 0) {
            this._selectAllCheckbox.checked = false;
            this._selectAllCheckbox.indeterminate = false;
            return;
        }
        var self = this;
        var selectedCount = 0;
        this.rows.forEach(function (row) {
            if (self._selectedRowIds.has(row[self._rowIdField])) selectedCount++;
        });
        if (selectedCount === 0) {
            this._selectAllCheckbox.checked = false;
            this._selectAllCheckbox.indeterminate = false;
        } else if (selectedCount === this.rows.length) {
            this._selectAllCheckbox.checked = true;
            this._selectAllCheckbox.indeterminate = false;
        } else {
            this._selectAllCheckbox.checked = false;
            this._selectAllCheckbox.indeterminate = true;
        }
    };

    // ----- Public row access methods -----

    /**
     * Return all rows currently loaded on the visible page.
     */
    DataTable.prototype.getVisibleRows = function () {
        return this.rows.slice();
    };

    /**
     * Return rows whose IDs are in the current selection set.
     */
    DataTable.prototype.getSelectedRows = function () {
        var self = this;
        return this.rows.filter(function (row) {
            return self._selectedRowIds.has(row[self._rowIdField]);
        });
    };

    /**
     * Return array of selected row IDs.
     */
    DataTable.prototype.getSelectedRowIds = function () {
        return Array.from(this._selectedRowIds);
    };

    /**
     * Clear the selection set.
     */
    DataTable.prototype.clearSelection = function () {
        this._selectedRowIds.clear();
        this._renderTable();
        this.onSelectionChange([]);
    };

    /**
     * Select all visible rows.
     */
    DataTable.prototype.selectAllVisible = function () {
        this._toggleSelectAll(true);
    };

    /**
     * Update a row's data in-place (for optimistic UI after API calls).
     * Finds the row by rowIdField, merges updates, re-renders.
     */
    DataTable.prototype.updateRowData = function (rowId, updates) {
        var self = this;
        for (var i = 0; i < this.rows.length; i++) {
            if (this.rows[i][this._rowIdField] === rowId) {
                for (var key in updates) {
                    if (updates.hasOwnProperty(key)) {
                        this.rows[i][key] = updates[key];
                    }
                }
                break;
            }
        }
        this._renderTable();
    };

    /**
     * Bulk update multiple rows in-place. rowUpdates is an array of
     * { id: rowId, ...fields }. Re-renders once after all updates.
     */
    DataTable.prototype.bulkUpdateRowData = function (rowUpdates) {
        var self = this;
        var updateMap = {};
        rowUpdates.forEach(function (u) {
            updateMap[u[self._rowIdField] || u.id] = u;
        });
        for (var i = 0; i < this.rows.length; i++) {
            var rowId = this.rows[i][this._rowIdField];
            var upd = updateMap[rowId];
            if (upd) {
                for (var key in upd) {
                    if (upd.hasOwnProperty(key) && key !== self._rowIdField) {
                        this.rows[i][key] = upd[key];
                    }
                }
            }
        }
        this._renderTable();
    };

    DataTable.prototype.destroy = function () {
        if (this._conditionBuilder) this._conditionBuilder.destroy();
        if (this._columnPicker) this._columnPicker.destroy();
        this.container.innerHTML = '';
    };

    return DataTable;
})();
