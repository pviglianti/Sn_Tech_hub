/**
 * ConditionBuilder — ServiceNow-style condition builder.
 *
 * Each row has its own AND/OR connector to the row above it.
 * OR groups with the previous row (same as SN encoded query):
 *   field1=A ^ field2=B ^OR field2=C
 *   means: field1=A AND (field2=B OR field2=C)
 *
 * Usage:
 *   const cb = new ConditionBuilder(containerEl, {
 *     fields: [{ local_column, column_label, kind, is_reference, sn_reference_table }],
 *     availableTables: { 'sys_user': true, 'cmn_location': true },
 *     onChange: (conditionTree) => { ... }
 *   });
 *
 * Emits JSON matching condition_query_builder.py expected shape:
 *   { logic: "AND", conditions: [ ... ] }
 *   where each condition is { field, operator, value }
 *   and OR groups become nested: { logic: "OR", conditions: [...] }
 */
window.ConditionBuilder = (function () {
    'use strict';

    var OPERATORS_BY_KIND = {
        string: [
            { value: 'is',              label: 'is' },
            { value: 'is_not',          label: 'is not' },
            { value: 'contains',        label: 'contains' },
            { value: 'not_contains',    label: 'does not contain' },
            { value: 'starts_with',     label: 'starts with' },
            { value: 'ends_with',       label: 'ends with' },
            { value: 'is_empty',        label: 'is empty' },
            { value: 'is_not_empty',    label: 'is not empty' },
        ],
        number: [
            { value: 'equals',          label: '=' },
            { value: 'not_equals',      label: '!=' },
            { value: 'greater_than',    label: '>' },
            { value: 'less_than',       label: '<' },
            { value: 'greater_or_equal',label: '>=' },
            { value: 'less_or_equal',   label: '<=' },
            { value: 'is_empty',        label: 'is empty' },
            { value: 'is_not_empty',    label: 'is not empty' },
        ],
        date: [
            { value: 'is',              label: 'is' },
            { value: 'before',          label: 'before' },
            { value: 'after',           label: 'after' },
            { value: 'is_empty',        label: 'is empty' },
            { value: 'is_not_empty',    label: 'is not empty' },
        ],
        boolean: [
            { value: 'is_true',         label: 'is true' },
            { value: 'is_false',        label: 'is false' },
        ],
        reference: [
            { value: 'is',              label: 'is' },
            { value: 'is_not',          label: 'is not' },
            { value: 'contains',        label: 'contains' },
            { value: 'is_empty',        label: 'is empty' },
            { value: 'is_not_empty',    label: 'is not empty' },
        ],
    };

    var NO_VALUE_OPS = { is_empty: 1, is_not_empty: 1, is_true: 1, is_false: 1 };

    function ConditionBuilder(container, opts) {
        this.container = container;
        this.fields = opts.fields || [];
        this.availableTables = opts.availableTables || {};
        this.onChange = opts.onChange || function () {};
        // Each row: { field, operator, value, connector: 'AND'|'OR' }
        // connector is the link TO THIS ROW from the one above it.
        // First row has no connector.
        this.rows = [];

        this._render();
    }

    ConditionBuilder.prototype._render = function () {
        this.container.innerHTML = '';
        this.container.classList.add('condition-builder');

        // Header
        var header = document.createElement('div');
        header.className = 'cb-header';

        var title = document.createElement('span');
        title.className = 'cb-title';
        title.textContent = 'Filters';
        header.appendChild(title);

        var addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'btn btn-sm btn-secondary cb-add-btn';
        addBtn.textContent = '+ Add Filter';
        addBtn.addEventListener('click', this._addRow.bind(this));
        header.appendChild(addBtn);

        var clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.className = 'btn btn-sm cb-clear-btn';
        clearBtn.textContent = 'Clear All';
        clearBtn.addEventListener('click', this._clearAll.bind(this));
        header.appendChild(clearBtn);

        this.container.appendChild(header);

        // Rows container
        this._rowsEl = document.createElement('div');
        this._rowsEl.className = 'cb-rows';
        this.container.appendChild(this._rowsEl);
    };

    ConditionBuilder.prototype._addRow = function () {
        var self = this;
        var idx = this.rows.length;
        var row = {
            field: '',
            operator: '',
            value: '',
            connector: idx > 0 ? 'AND' : null,
        };
        this.rows.push(row);

        var el = document.createElement('div');
        el.className = 'cb-row';
        el.dataset.idx = idx;

        // Connector pill (AND/OR toggle) — only for rows after the first
        if (idx > 0) {
            var pill = document.createElement('button');
            pill.type = 'button';
            pill.className = 'cb-connector-pill';
            pill.textContent = row.connector;
            pill.title = 'Click to toggle AND / OR';
            pill.addEventListener('click', function () {
                row.connector = row.connector === 'AND' ? 'OR' : 'AND';
                pill.textContent = row.connector;
                pill.classList.toggle('cb-connector-or', row.connector === 'OR');
                self._fireChange();
            });
            el.appendChild(pill);
        }

        // Field select
        var fieldSel = document.createElement('select');
        fieldSel.className = 'form-control cb-field-select';
        fieldSel.innerHTML = '<option value="">Select field...</option>';
        this.fields.forEach(function (f) {
            var opt = document.createElement('option');
            opt.value = f.local_column;
            opt.textContent = f.column_label || f.local_column;
            fieldSel.appendChild(opt);
        });
        el.appendChild(fieldSel);

        // Operator select
        var opSel = document.createElement('select');
        opSel.className = 'form-control cb-op-select';
        opSel.innerHTML = '<option value="">operator</option>';
        opSel.disabled = true;
        el.appendChild(opSel);

        // Value input
        var valInput = document.createElement('input');
        valInput.type = 'text';
        valInput.className = 'form-control cb-value-input';
        valInput.placeholder = 'value';
        valInput.disabled = true;
        el.appendChild(valInput);

        // Remove button
        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'cb-remove-btn';
        removeBtn.innerHTML = '&times;';
        removeBtn.title = 'Remove this filter';
        removeBtn.addEventListener('click', function () {
            self._removeRow(idx);
        });
        el.appendChild(removeBtn);

        // Events
        fieldSel.addEventListener('change', function () {
            row.field = fieldSel.value;
            row.operator = '';
            row.value = '';
            self._updateOperators(opSel, valInput, row);
            self._fireChange();
        });

        opSel.addEventListener('change', function () {
            row.operator = opSel.value;
            var needsValue = !NO_VALUE_OPS[row.operator];
            valInput.disabled = !needsValue;
            if (!needsValue) {
                valInput.value = '';
                row.value = '';
            }
            self._fireChange();
        });

        valInput.addEventListener('input', function () {
            row.value = valInput.value;
            self._fireChange();
        });

        valInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                self._fireChange();
            }
        });

        this._rowsEl.appendChild(el);
    };

    ConditionBuilder.prototype._getFieldKind = function (fieldName) {
        var fieldDef = this.fields.find(function (f) { return f.local_column === fieldName; });
        if (!fieldDef) return 'string';
        // Reference fields that point to available local tables use 'reference' kind;
        // others just use 'string' (they're sys_id values, treat as text).
        if (fieldDef.is_reference) {
            if (fieldDef.sn_reference_table && this.availableTables[fieldDef.sn_reference_table]) {
                return 'reference';
            }
            return 'string';
        }
        return fieldDef.kind || 'string';
    };

    ConditionBuilder.prototype._updateOperators = function (opSel, valInput, row) {
        opSel.innerHTML = '<option value="">operator</option>';
        if (!row.field) {
            opSel.disabled = true;
            valInput.disabled = true;
            return;
        }

        var kind = this._getFieldKind(row.field);
        var ops = OPERATORS_BY_KIND[kind] || OPERATORS_BY_KIND.string;
        ops.forEach(function (op) {
            var opt = document.createElement('option');
            opt.value = op.value;
            opt.textContent = op.label;
            opSel.appendChild(opt);
        });
        opSel.disabled = false;
        valInput.disabled = true;
    };

    ConditionBuilder.prototype._removeRow = function (idx) {
        this.rows.splice(idx, 1);
        // If the new first row has a connector, clear it
        if (this.rows.length > 0 && this.rows[0].connector) {
            this.rows[0].connector = null;
        }
        this._rebuildRows();
        this._fireChange();
    };

    ConditionBuilder.prototype._clearAll = function () {
        this.rows = [];
        this._rowsEl.innerHTML = '';
        this._fireChange();
    };

    ConditionBuilder.prototype._rebuildRows = function () {
        var saved = this.rows.slice();
        this.rows = [];
        this._rowsEl.innerHTML = '';
        var self = this;
        saved.forEach(function (r, i) {
            self._addRow();
            var last = self.rows[self.rows.length - 1];
            last.field = r.field;
            last.operator = r.operator;
            last.value = r.value;
            if (i > 0) last.connector = r.connector || 'AND';

            var rowEl = self._rowsEl.lastElementChild;
            var fieldSel = rowEl.querySelector('.cb-field-select');
            var opSel = rowEl.querySelector('.cb-op-select');
            var valInput = rowEl.querySelector('.cb-value-input');
            var pill = rowEl.querySelector('.cb-connector-pill');

            fieldSel.value = r.field;
            self._updateOperators(opSel, valInput, last);
            opSel.value = r.operator;
            if (r.operator && !NO_VALUE_OPS[r.operator]) {
                valInput.disabled = false;
                valInput.value = r.value;
            }
            if (pill && last.connector === 'OR') {
                pill.textContent = 'OR';
                pill.classList.add('cb-connector-or');
            }
        });
    };

    ConditionBuilder.prototype._fireChange = function () {
        this.onChange(this.getConditions());
    };

    /**
     * Build the condition tree using SN-style grouping:
     *   - AND rows separate groups
     *   - OR rows extend the previous group
     *
     * Example: A AND B OR C AND D
     *   → (A) AND (B OR C) AND (D)
     *
     * Emits: { logic: "AND", conditions: [...] }
     * Where OR groups become: { logic: "OR", conditions: [...] }
     */
    ConditionBuilder.prototype.getConditions = function () {
        var valid = this.rows.filter(function (r) {
            if (!r.field || !r.operator) return false;
            if (!NO_VALUE_OPS[r.operator] && !r.value) return false;
            return true;
        });

        if (valid.length === 0) return null;

        // Group rows by connector logic.
        // Start a new group on AND; extend the current group on OR.
        var groups = [];
        var currentGroup = [];

        valid.forEach(function (r, i) {
            var cond = { field: r.field, operator: r.operator, value: r.value || '' };
            if (i === 0 || r.connector === 'AND') {
                // Start a new AND group
                if (currentGroup.length > 0) {
                    groups.push(currentGroup);
                }
                currentGroup = [cond];
            } else {
                // OR — extend current group
                currentGroup.push(cond);
            }
        });
        if (currentGroup.length > 0) {
            groups.push(currentGroup);
        }

        // Flatten: single-item groups stay as conditions,
        // multi-item groups become { logic: "OR", conditions: [...] }
        var topConditions = groups.map(function (group) {
            if (group.length === 1) return group[0];
            return { logic: 'OR', conditions: group };
        });

        if (topConditions.length === 1 && topConditions[0].logic === 'OR') {
            return topConditions[0];
        }

        return {
            logic: 'AND',
            conditions: topConditions,
        };
    };

    function _isGroup(node) {
        return !!(node && typeof node === 'object' && node.logic && Array.isArray(node.conditions));
    }

    function _asTextValue(value) {
        if (value === null || value === undefined) return '';
        return String(value);
    }

    function _normalizeConnector(connector) {
        return String(connector || 'AND').toUpperCase() === 'OR' ? 'OR' : 'AND';
    }

    // Convert a condition tree into row entries that match the builder's
    // row model (flat rows with AND/OR connector to previous row).
    function _flattenNodeToRowDefs(node, targetRows) {
        if (!node) return;

        if (!_isGroup(node)) {
            targetRows.push({
                field: node.field || '',
                operator: node.operator || '',
                value: _asTextValue(node.value),
                connector: 'AND',
            });
            return;
        }

        var logic = String(node.logic || 'AND').toUpperCase();
        var first = true;

        (node.conditions || []).forEach(function (child) {
            var before = targetRows.length;
            _flattenNodeToRowDefs(child, targetRows);
            if (targetRows.length === before) return;

            if (first) {
                targetRows[before].connector = 'AND';
                first = false;
            } else if (logic === 'OR') {
                targetRows[before].connector = 'OR';
            } else {
                targetRows[before].connector = 'AND';
            }
        });
    }

    // Public API used by DataTable to preload query filters (from links, etc.).
    ConditionBuilder.prototype.setConditions = function (conditionTree, silent) {
        if (!conditionTree) {
            this._clearAll();
            return;
        }

        var rowDefs = [];
        _flattenNodeToRowDefs(conditionTree, rowDefs);

        this.rows = rowDefs.map(function (r, idx) {
            return {
                field: r.field || '',
                operator: r.operator || '',
                value: _asTextValue(r.value),
                connector: idx === 0 ? null : _normalizeConnector(r.connector),
            };
        });

        this._rebuildRows();
        if (!silent) {
            this._fireChange();
        }
    };

    ConditionBuilder.prototype.setFields = function (fields) {
        this.fields = fields || [];
        if (this.rows.length > 0) {
            this._rebuildRows();
        }
    };

    ConditionBuilder.prototype.destroy = function () {
        this.container.innerHTML = '';
        this.rows = [];
    };

    return ConditionBuilder;
})();
