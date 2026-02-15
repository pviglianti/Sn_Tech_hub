/**
 * ColumnPicker — Reusable slush-bucket column picker component.
 *
 * Dual-list interface (Available / Selected) with add/remove arrows
 * and up/down reorder for the selected list.  Reference columns that
 * point to locally-available tables are highlighted in blue.
 *
 * Usage:
 *   var picker = new ColumnPicker(containerEl, {
 *       fields:          [{local_column, column_label, is_reference, sn_reference_table, ...}],
 *       selected:        ['name', 'state', ...],        // initial ordered selection
 *       availableTables: { cmdb_ci_service: true, ... }, // for ref highlighting
 *       onChange:         function (selectedColumns) { ... },
 *   });
 *
 *   picker.getSelected();          // current ordered column list
 *   picker.setFields(newFields);   // swap fields (e.g. after schema reload)
 *   picker.setSelected(newCols);   // programmatically change selection
 *   picker.destroy();              // cleanup
 */
window.ColumnPicker = (function () {
    'use strict';

    function ColumnPicker(container, opts) {
        this.container = container;
        this.fields = opts.fields || [];
        this.selected = (opts.selected || []).slice(); // defensive copy
        this.availableTables = opts.availableTables || {};
        this.onChange = opts.onChange || function () {};

        // Internal selection tracking
        this._availSel = null;
        this._selSel = null;

        // Build field lookup
        this._fieldMap = {};
        this._rebuildFieldMap();

        this._build();
    }

    ColumnPicker.prototype._rebuildFieldMap = function () {
        this._fieldMap = {};
        var self = this;
        this.fields.forEach(function (f) {
            self._fieldMap[f.local_column] = f;
        });
    };

    /**
     * Return the current ordered selected-column array.
     */
    ColumnPicker.prototype.getSelected = function () {
        return this.selected.slice();
    };

    /**
     * Replace the field definitions (e.g. after switching instances).
     * Prunes any selected columns that no longer exist in the new field set.
     */
    ColumnPicker.prototype.setFields = function (fields, availableTables) {
        this.fields = fields || [];
        if (availableTables !== undefined) this.availableTables = availableTables;
        this._rebuildFieldMap();

        // Prune selected list to only columns that exist in new fields
        var validCols = {};
        this.fields.forEach(function (f) { validCols[f.local_column] = true; });
        this.selected = this.selected.filter(function (c) { return validCols[c]; });

        this._populateLists();
    };

    /**
     * Programmatically set the selected columns.
     */
    ColumnPicker.prototype.setSelected = function (cols) {
        this.selected = (cols || []).slice();
        this._populateLists();
    };

    /**
     * Build the full slush-bucket DOM inside this.container.
     */
    ColumnPicker.prototype._build = function () {
        var self = this;
        this.container.innerHTML = '';

        // Header
        this._header = document.createElement('div');
        this._header.className = 'dt-col-picker-header';
        this.container.appendChild(this._header);

        // Reset button
        var actions = document.createElement('div');
        actions.className = 'dt-col-picker-actions';
        var resetBtn = document.createElement('button');
        resetBtn.type = 'button';
        resetBtn.className = 'btn btn-sm cb-clear-btn';
        resetBtn.textContent = 'Reset Default';
        resetBtn.addEventListener('click', function () {
            self.selected = self._pickDefaults();
            self._populateLists();
            self._fireChange();
        });
        actions.appendChild(resetBtn);
        this.container.appendChild(actions);

        // Slush bucket container
        var bucket = document.createElement('div');
        bucket.className = 'dt-slush-bucket';

        // --- Available pane (left) ---
        var availPane = document.createElement('div');
        availPane.className = 'dt-slush-pane';
        var availLabel = document.createElement('div');
        availLabel.className = 'dt-slush-label';
        availLabel.textContent = 'Available';
        availPane.appendChild(availLabel);

        this._availList = document.createElement('div');
        this._availList.className = 'dt-slush-list';
        availPane.appendChild(this._availList);
        bucket.appendChild(availPane);

        // --- Center buttons (add / remove) ---
        var centerBtns = document.createElement('div');
        centerBtns.className = 'dt-slush-center';

        var addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'btn btn-sm dt-slush-btn';
        addBtn.innerHTML = '&#9654;';
        addBtn.title = 'Add selected';
        centerBtns.appendChild(addBtn);

        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-sm dt-slush-btn';
        removeBtn.innerHTML = '&#9664;';
        removeBtn.title = 'Remove selected';
        centerBtns.appendChild(removeBtn);

        bucket.appendChild(centerBtns);

        // --- Selected pane (right) ---
        var selPane = document.createElement('div');
        selPane.className = 'dt-slush-pane';
        var selLabel = document.createElement('div');
        selLabel.className = 'dt-slush-label';
        selLabel.textContent = 'Selected';
        selPane.appendChild(selLabel);

        this._selList = document.createElement('div');
        this._selList.className = 'dt-slush-list';
        selPane.appendChild(this._selList);

        // Reorder buttons
        var reorderBtns = document.createElement('div');
        reorderBtns.className = 'dt-slush-reorder';

        var upBtn = document.createElement('button');
        upBtn.type = 'button';
        upBtn.className = 'btn btn-sm dt-slush-btn';
        upBtn.innerHTML = '&#9650;';
        upBtn.title = 'Move up';
        reorderBtns.appendChild(upBtn);

        var downBtn = document.createElement('button');
        downBtn.type = 'button';
        downBtn.className = 'btn btn-sm dt-slush-btn';
        downBtn.innerHTML = '&#9660;';
        downBtn.title = 'Move down';
        reorderBtns.appendChild(downBtn);

        selPane.appendChild(reorderBtns);
        bucket.appendChild(selPane);
        this.container.appendChild(bucket);

        // --- Event handlers ---

        addBtn.addEventListener('click', function () {
            if (!self._availSel) return;
            var col = self._availSel.dataset.col;
            self.selected.push(col);
            self._populateLists();
            self._fireChange();
        });

        removeBtn.addEventListener('click', function () {
            if (!self._selSel) return;
            var col = self._selSel.dataset.col;
            self.selected = self.selected.filter(function (c) { return c !== col; });
            self._populateLists();
            self._fireChange();
        });

        upBtn.addEventListener('click', function () {
            if (!self._selSel) return;
            var col = self._selSel.dataset.col;
            var idx = self.selected.indexOf(col);
            if (idx <= 0) return;
            self.selected.splice(idx, 1);
            self.selected.splice(idx - 1, 0, col);
            self._populateLists();
            self._fireChange();
            // Re-select the moved item
            var items = self._selList.querySelectorAll('.dt-slush-item');
            if (items[idx - 1]) {
                items[idx - 1].classList.add('dt-slush-active');
                self._selSel = items[idx - 1];
            }
        });

        downBtn.addEventListener('click', function () {
            if (!self._selSel) return;
            var col = self._selSel.dataset.col;
            var idx = self.selected.indexOf(col);
            if (idx < 0 || idx >= self.selected.length - 1) return;
            self.selected.splice(idx, 1);
            self.selected.splice(idx + 1, 0, col);
            self._populateLists();
            self._fireChange();
            // Re-select the moved item
            var items = self._selList.querySelectorAll('.dt-slush-item');
            if (items[idx + 1]) {
                items[idx + 1].classList.add('dt-slush-active');
                self._selSel = items[idx + 1];
            }
        });

        this._populateLists();
    };

    /**
     * Rebuild available / selected list DOM from current state.
     */
    ColumnPicker.prototype._populateLists = function () {
        var self = this;
        this._availList.innerHTML = '';
        this._selList.innerHTML = '';
        this._availSel = null;
        this._selSel = null;

        // Available: all fields NOT in selected, sorted alphabetically by label
        var avail = this.fields
            .filter(function (f) { return self.selected.indexOf(f.local_column) === -1; })
            .sort(function (a, b) {
                var la = (a.column_label || a.local_column).toLowerCase();
                var lb = (b.column_label || b.local_column).toLowerCase();
                return la < lb ? -1 : la > lb ? 1 : 0;
            });
        avail.forEach(function (f) { self._makeItem(f.local_column, self._availList, false); });

        // Selected: in current order
        this.selected.forEach(function (col) { self._makeItem(col, self._selList, true); });

        this._header.textContent = 'Columns (' + this.selected.length + '/' + this.fields.length + ')';
    };

    /**
     * Create a single item element in one of the lists.
     */
    ColumnPicker.prototype._makeItem = function (col, listEl, isSel) {
        var self = this;
        var f = this._fieldMap[col] || { local_column: col, column_label: col };
        var item = document.createElement('div');
        item.className = 'dt-slush-item';
        item.dataset.col = col;
        item.textContent = f.column_label || col;

        // Highlight references that point to tables we actually have locally
        if (f.is_reference && f.sn_reference_table && this.availableTables[f.sn_reference_table]) {
            item.classList.add('dt-col-ref-available');
        }

        item.addEventListener('click', function () {
            if (isSel) {
                if (self._availSel) { self._availSel.classList.remove('dt-slush-active'); self._availSel = null; }
                if (self._selSel) self._selSel.classList.remove('dt-slush-active');
                self._selSel = item;
            } else {
                if (self._selSel) { self._selSel.classList.remove('dt-slush-active'); self._selSel = null; }
                if (self._availSel) self._availSel.classList.remove('dt-slush-active');
                self._availSel = item;
            }
            item.classList.add('dt-slush-active');
        });

        // Double-click to move
        item.addEventListener('dblclick', function () {
            if (isSel) {
                self.selected = self.selected.filter(function (c) { return c !== col; });
            } else {
                self.selected.push(col);
            }
            self._populateLists();
            self._fireChange();
        });

        listEl.appendChild(item);
    };

    /**
     * Default column selection — priority columns first, then fill up to 10.
     */
    ColumnPicker.prototype._pickDefaults = function () {
        var PRIORITY_COLS = ['name', 'number', 'short_description', 'state', 'sys_updated_on', 'category', 'u_name'];
        var MAX_DEFAULT = 10;
        var fieldNames = this.fields.map(function (f) { return f.local_column; });
        var chosen = [];

        PRIORITY_COLS.forEach(function (c) {
            if (fieldNames.indexOf(c) !== -1 && chosen.length < MAX_DEFAULT) {
                chosen.push(c);
            }
        });

        this.fields.forEach(function (f) {
            if (chosen.length >= MAX_DEFAULT) return;
            if (chosen.indexOf(f.local_column) === -1) {
                chosen.push(f.local_column);
            }
        });

        return chosen;
    };

    /**
     * Notify consumer of column change.
     */
    ColumnPicker.prototype._fireChange = function () {
        this.onChange(this.selected.slice());
    };

    /**
     * Cleanup.
     */
    ColumnPicker.prototype.destroy = function () {
        this.container.innerHTML = '';
    };

    return ColumnPicker;
})();
