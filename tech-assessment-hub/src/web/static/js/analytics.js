/* Instance Comparison Analytics */

let configChart = null;
let tasksChart = null;
let userSetRange = false;
let currentInstances = [];
let configSeriesState = {};
let taskSeriesState = {};
let configRangeSeries = {};
let taskRangeSeries = {};

function setChartLoading(canvasId, message = 'Loading...') {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.clientWidth || 400;
    const height = canvas.clientHeight || 200;
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.fillStyle = '#64748b';
    ctx.font = '14px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(message, canvas.width / 2, canvas.height / 2);
    ctx.restore();
}

const CONFIG_SERIES = [
    { key: 'script_includes', label: 'Script Includes', color: '#2563eb', value: inst => (inst.inventory || {}).script_includes },
    { key: 'business_rules', label: 'Business Rules', color: '#16a34a', value: inst => (inst.inventory || {}).business_rules },
    { key: 'client_scripts', label: 'Client Scripts', color: '#ea580c', value: inst => (inst.inventory || {}).client_scripts },
    { key: 'ui_policies', label: 'UI Policies', color: '#7c3aed', value: inst => (inst.inventory || {}).ui_policies },
    { key: 'ui_actions', label: 'UI Actions', color: '#0ea5e9', value: inst => (inst.inventory || {}).ui_actions },
    { key: 'ui_pages', label: 'UI Pages', color: '#f59e0b', value: inst => (inst.inventory || {}).ui_pages },
    { key: 'scheduled_jobs', label: 'Scheduled Jobs', color: '#14b8a6', value: inst => (inst.inventory || {}).scheduled_jobs },
    { key: 'metadata_customizations', label: 'Metadata Customizations', color: '#ef4444', value: inst => inst.sys_metadata_customization_count },
    { key: 'update_sets_global', label: 'Update Sets (Global)', color: '#1d4ed8', value: inst => (inst.update_set_counts || {}).global },
    { key: 'update_sets_scoped', label: 'Update Sets (Scoped)', color: '#0369a1', value: inst => (inst.update_set_counts || {}).scoped ?? (inst.update_set_counts || {}).non_global },
    { key: 'update_sets_total', label: 'Update Sets (Total)', color: '#0f766e', value: inst => (inst.update_set_counts || {}).total },
    { key: 'update_xml_global', label: 'Customer Update XML (Global)', color: '#b45309', value: inst => (inst.sys_update_xml_counts || {}).global ?? inst.sys_update_xml_total },
    { key: 'update_xml_scoped', label: 'Customer Update XML (Scoped)', color: '#a16207', value: inst => (inst.sys_update_xml_counts || {}).scoped ?? (inst.sys_update_xml_counts || {}).non_global },
    { key: 'update_xml_total', label: 'Customer Update XML (Total)', color: '#c2410c', value: inst => (inst.sys_update_xml_counts || {}).total ?? inst.sys_update_xml_total },
    { key: 'custom_scoped_apps_x', label: 'Custom Scoped Apps (x_)', color: '#4f46e5', value: inst => inst.custom_scoped_app_count_x },
    { key: 'custom_scoped_apps_u', label: 'Custom Scoped Apps (u_)', color: '#6d28d9', value: inst => inst.custom_scoped_app_count_u },
    { key: 'custom_tables_x', label: 'Custom Tables (x_)', color: '#a21caf', value: inst => inst.custom_table_count_x },
    { key: 'custom_tables_u', label: 'Custom Tables (u_)', color: '#be185d', value: inst => inst.custom_table_count_u },
    { key: 'custom_fields_x', label: 'Custom Fields (x_)', color: '#15803d', value: inst => inst.custom_field_count_x },
    { key: 'custom_fields_u', label: 'Custom Fields (u_)', color: '#166534', value: inst => inst.custom_field_count_u },
];

const CONFIG_RANGE_SERIES = [
    { key: 'script_includes', label: 'Script Includes', color: '#2563eb' },
    { key: 'business_rules', label: 'Business Rules', color: '#16a34a' },
    { key: 'client_scripts', label: 'Client Scripts', color: '#ea580c' },
    { key: 'ui_policies', label: 'UI Policies', color: '#7c3aed' },
    { key: 'ui_actions', label: 'UI Actions', color: '#0ea5e9' },
    { key: 'ui_pages', label: 'UI Pages', color: '#f59e0b' },
    { key: 'scheduled_jobs', label: 'Scheduled Jobs', color: '#14b8a6' }
];

const TASK_SERIES = [
    { key: 'task', label: 'All Tasks', color: '#2563eb' },
    { key: 'incident', label: 'Incident', color: '#16a34a' },
    { key: 'change_request', label: 'Change Request', color: '#ea580c' },
    { key: 'change_task', label: 'Change Task', color: '#7c3aed' },
    { key: 'problem', label: 'Problem', color: '#0ea5e9' },
    { key: 'problem_task', label: 'Problem Task', color: '#f59e0b' },
    { key: 'sc_req_item', label: 'Requested Item', color: '#14b8a6' },
    { key: 'sc_task', label: 'SC Task', color: '#ef4444' }
];

function getSelectedInstanceIds() {
    const select = document.getElementById('instanceSelect');
    const selected = Array.from(select.options)
        .filter(option => option.selected)
        .map(option => option.value);
    if (selected.length) return selected;
    return Array.from(select.options).map(option => option.value);
}

function formatValue(value) {
    if (value === null || value === undefined) return 'N/A';
    if (typeof value === 'number') return value.toLocaleString();
    return value;
}

function formatDate(value) {
    if (!value) return 'N/A';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'N/A';
    return date.toISOString().slice(0, 10);
}

function getSeriesValue(seriesData, key, inst) {
    if (!seriesData || !seriesData[key]) return null;
    const value = seriesData[key][String(inst.id)];
    return value === undefined ? null : value;
}

function instanceLabel(instance) {
    const company = instance.company || 'No Company';
    return `${company} - ${instance.name}`;
}

function getDefaultRange(instances) {
    const ages = instances
        .map(inst => inst.instance_age_years)
        .filter(age => typeof age === 'number');

    if (!ages.length) return 'last_90_days';
    const maxAge = Math.max(...ages);

    if (maxAge <= 2) return 'all_time';
    if (maxAge <= 5) return 'last_2_years';
    return 'last_5_years';
}

async function fetchConfigRangeSummary(instanceIds) {
    const params = getTaskRangeParams();
    params.set('instance_ids', instanceIds || 'all');
    const response = await fetch(`/api/analytics/config-summary?${params.toString()}`);
    if (!response.ok) {
        throw new Error(`Config summary request failed (${response.status})`);
    }
    const data = await response.json();
    return data.series || {};
}

async function fetchTaskRangeSummary(instanceIds) {
    const params = getTaskRangeParams();
    params.set('instance_ids', instanceIds || 'all');
    const response = await fetch(`/api/analytics/tasks-summary?${params.toString()}`);
    if (!response.ok) {
        throw new Error(`Task summary request failed (${response.status})`);
    }
    const data = await response.json();
    return data.series || {};
}

function renderPivotTable(containerId, instances, rows, options = {}) {
    const container = document.getElementById(containerId);
    if (!instances.length) {
        container.innerHTML = '<p class="error">No instances selected</p>';
        return;
    }

    const showRange = options.showRange === true;
    const rangeLabel = options.rangeLabel || 'Range';

    let html = '<div class="table-scroll"><table class="data-table">';
    html += '<thead><tr><th>Metric</th>';
    instances.forEach(inst => {
        html += `<th>${instanceLabel(inst)}</th>`;
        if (showRange) {
            html += `<th class="range-col">${instanceLabel(inst)} (${rangeLabel})</th>`;
        }
    });
    html += '</tr></thead><tbody>';

    rows.forEach(row => {
        html += `<tr><td>${row.label}</td>`;
        instances.forEach(inst => {
            html += `<td>${formatValue(row.value(inst))}</td>`;
            if (showRange) {
                const rangeValue = row.rangeValue ? row.rangeValue(inst) : null;
                html += `<td class="range-col">${formatValue(rangeValue)}</td>`;
            }
        });
        html += '</tr>';
    });

    html += '</tbody></table></div>';
    container.innerHTML = html;
}

function buildConfigChart(instances) {
    if (configChart) {
        configChart.destroy();
        configChart = null;
    }
    setChartLoading('configChart');
    const labels = instances.map(instanceLabel);

    const datasets = CONFIG_RANGE_SERIES
        .filter(series => configSeriesState[series.key])
        .map(series => ({
            label: series.label,
            data: instances.map(inst => {
                const value = getSeriesValue(configRangeSeries, series.key, inst);
                return value === null ? null : Number(value) || 0;
            }),
            backgroundColor: series.color,
            borderColor: series.color
        }));

    const ctx = document.getElementById('configChart').getContext('2d');

    configChart = new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets },
        options: {
            responsive: true,
            plugins: { legend: { position: 'bottom' } },
            scales: {
                x: { stacked: false },
                y: { beginAtZero: true }
            }
        }
    });
}

function initializeSeries(listId, state, seriesList, onToggle) {
    if (!Object.keys(state).length) {
        seriesList.forEach(series => {
            state[series.key] = true;
        });
    }

    const list = document.getElementById(listId);
    if (!list) return;

    list.innerHTML = '';
    seriesList.forEach(series => {
        const id = `${listId}-${series.key}`;
        const wrapper = document.createElement('label');
        wrapper.className = 'config-series-item';
        wrapper.innerHTML = `
            <input type="checkbox" id="${id}" data-key="${series.key}" ${state[series.key] ? 'checked' : ''}>
            <span>${series.label}</span>
        `;
        list.appendChild(wrapper);
    });

    list.querySelectorAll('input[type="checkbox"]').forEach(input => {
        input.addEventListener('change', event => {
            const key = event.target.dataset.key;
            state[key] = event.target.checked;
            if (onToggle) onToggle();
        });
    });
}

function setAllSeries(state, seriesList, enabled, listId, onToggle) {
    seriesList.forEach(series => {
        state[series.key] = enabled;
    });
    initializeSeries(listId, state, seriesList, onToggle);
    if (onToggle) onToggle();
}

function getTaskRangeParams() {
    const range = document.getElementById('taskRangeSelect').value;
    const params = new URLSearchParams();
    params.set('range', range);

    if (range === 'custom') {
        const value = document.getElementById('customRangeValue').value;
        const unit = document.getElementById('customRangeUnit').value;
        params.set('custom_value', value);
        params.set('custom_unit', unit);
    }

    return params;
}

function buildTaskChart(instances) {
    if (tasksChart) {
        tasksChart.destroy();
        tasksChart = null;
    }
    setChartLoading('tasksChart');
    const selectedTypes = TASK_SERIES
        .filter(series => taskSeriesState[series.key])
        .map(series => series.key);
    const seriesData = taskRangeSeries || {};

    const labels = instances.map(instanceLabel);
    const datasets = TASK_SERIES
        .filter(series => taskSeriesState[series.key])
        .map(series => {
            const seriesCounts = seriesData[series.key] || {};
            return {
                label: series.label,
                data: instances.map(inst => {
                    const value = seriesCounts[String(inst.id)];
                    return value === null || value === undefined ? null : value;
                }),
                backgroundColor: series.color,
                borderColor: series.color
            };
        });

    const ctx = document.getElementById('tasksChart').getContext('2d');
    if (tasksChart) {
        tasksChart.destroy();
    }

    tasksChart = new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets },
        options: {
            responsive: true,
            plugins: { legend: { position: 'bottom' } },
            scales: {
                x: { stacked: true },
                y: { beginAtZero: true, stacked: true }
            }
        }
    });
}

function renderConfigTable(instances) {
    const rangeKeys = new Set([
        ...CONFIG_RANGE_SERIES.map(series => series.key),
        'metadata_customizations',
        'update_sets_global',
        'update_sets_scoped',
        'update_sets_total',
        'update_xml_global',
        'update_xml_scoped',
        'update_xml_total'
    ]);

    const configRows = [
        { key: 'script_includes', label: 'Script Includes', value: inst => (inst.inventory || {}).script_includes },
        { key: 'business_rules', label: 'Business Rules', value: inst => (inst.inventory || {}).business_rules },
        { key: 'client_scripts', label: 'Client Scripts', value: inst => (inst.inventory || {}).client_scripts },
        { key: 'ui_policies', label: 'UI Policies', value: inst => (inst.inventory || {}).ui_policies },
        { key: 'ui_actions', label: 'UI Actions', value: inst => (inst.inventory || {}).ui_actions },
        { key: 'ui_pages', label: 'UI Pages', value: inst => (inst.inventory || {}).ui_pages },
        { key: 'scheduled_jobs', label: 'Scheduled Jobs', value: inst => (inst.inventory || {}).scheduled_jobs },
        { key: 'metadata_customizations', label: 'Metadata Customizations', value: inst => inst.sys_metadata_customization_count },
        { key: 'update_sets_global', label: 'Update Sets (Global)', value: inst => (inst.update_set_counts || {}).global },
        { key: 'update_sets_scoped', label: 'Update Sets (Scoped)', value: inst => (inst.update_set_counts || {}).scoped ?? (inst.update_set_counts || {}).non_global },
        { key: 'update_sets_total', label: 'Update Sets (Total)', value: inst => (inst.update_set_counts || {}).total },
        { key: 'update_xml_global', label: 'Customer Update XML (Global)', value: inst => (inst.sys_update_xml_counts || {}).global ?? inst.sys_update_xml_total },
        { key: 'update_xml_scoped', label: 'Customer Update XML (Scoped)', value: inst => (inst.sys_update_xml_counts || {}).scoped ?? (inst.sys_update_xml_counts || {}).non_global },
        { key: 'update_xml_total', label: 'Customer Update XML (Total)', value: inst => (inst.sys_update_xml_counts || {}).total ?? inst.sys_update_xml_total },
        { label: 'Custom Scoped Apps (x_)', value: inst => inst.custom_scoped_app_count_x },
        { label: 'Custom Scoped Apps (u_)', value: inst => inst.custom_scoped_app_count_u },
        { label: 'Custom Tables (x_)', value: inst => inst.custom_table_count_x },
        { label: 'Custom Tables (u_)', value: inst => inst.custom_table_count_u },
        { label: 'Custom Fields (x_)', value: inst => inst.custom_field_count_x },
        { label: 'Custom Fields (u_)', value: inst => inst.custom_field_count_u },
        { label: 'Metrics Last Refreshed', value: inst => formatDate(inst.metrics_last_refreshed_at) },
        { label: 'Instance DOB', value: inst => formatDate(inst.instance_dob) },
        { label: 'Instance Age (years)', value: inst => inst.instance_age_years }
    ].map(row => ({
        ...row,
        rangeValue: row.key && rangeKeys.has(row.key)
            ? (inst => getSeriesValue(configRangeSeries, row.key, inst))
            : null
    }));

    renderPivotTable('configTable', instances, configRows, { showRange: true, rangeLabel: 'Range' });
}

function renderTaskTable(instances) {
    const baseTaskRows = [
        { key: 'task', label: 'All Tasks' },
        { key: 'incident', label: 'Incident' },
        { key: 'change_request', label: 'Change Request' },
        { key: 'change_task', label: 'Change Task' },
        { key: 'problem', label: 'Problem' },
        { key: 'problem_task', label: 'Problem Task' },
        { key: 'sc_req_item', label: 'Requested Item' },
        { key: 'sc_task', label: 'SC Task' }
    ];

    const taskRows = [];
    baseTaskRows.forEach(row => {
        taskRows.push({
            label: row.label,
            value: inst => (inst.task_counts || {})[row.key],
            rangeValue: inst => getSeriesValue(taskRangeSeries, row.key, inst)
        });
    });

    const hasArchive = baseTaskRows.some(row =>
        instances.some(inst => {
            const value = (inst.task_counts || {})[`archive_${row.key}`];
            return typeof value === 'number' && value > 0;
        })
    );

    if (hasArchive) {
        baseTaskRows.forEach(row => {
            const archiveKey = `archive_${row.key}`;
            const hasArchiveForType = instances.some(inst => {
                const value = (inst.task_counts || {})[archiveKey];
                return typeof value === 'number' && value > 0;
            });

            if (!hasArchiveForType) {
                return;
            }

            taskRows.push({
                label: `${row.label} (Archived)`,
                value: inst => (inst.task_counts || {})[archiveKey],
                rangeValue: null
            });

            taskRows.push({
                label: `${row.label} (Total incl. Archive)`,
                value: inst => {
                    const live = (inst.task_counts || {})[row.key] || 0;
                    const archived = (inst.task_counts || {})[archiveKey] || 0;
                    return live + archived;
                },
                rangeValue: inst => getSeriesValue(taskRangeSeries, row.key, inst)
            });
        });
    }

    renderPivotTable('taskTable', instances, taskRows, { showRange: true, rangeLabel: 'Range' });
}

async function loadSummary() {
    setChartLoading('configChart');
    setChartLoading('tasksChart');
    const instanceIds = getSelectedInstanceIds();
    const query = instanceIds.length ? instanceIds.join(',') : 'all';

    let instances = [];
    try {
        const response = await fetch(`/api/analytics/summary?instance_ids=${query}`);
        if (!response.ok) {
            throw new Error(`Summary request failed (${response.status})`);
        }
        const data = await response.json();
        instances = data.instances || [];
    } catch (error) {
        console.error(error);
        document.getElementById('configTable').innerHTML = '<p class="error">Failed to load summary metrics.</p>';
        document.getElementById('taskTable').innerHTML = '<p class="error">Failed to load summary metrics.</p>';
        return;
    }
    currentInstances = instances;

    if (!instances.length) {
        document.getElementById('configTable').innerHTML = '<p class="error">No instances found</p>';
        document.getElementById('taskTable').innerHTML = '<p class="error">No instances found</p>';
        return;
    }

    initializeSeries('configSeriesList', configSeriesState, CONFIG_RANGE_SERIES, () => buildConfigChart(currentInstances));
    initializeSeries('taskSeriesList', taskSeriesState, TASK_SERIES, () => buildTaskChart(currentInstances));

    if (!userSetRange) {
        document.getElementById('taskRangeSelect').value = getDefaultRange(instances);
    }

    const instanceIdQuery = instanceIds.length ? instanceIds.join(',') : 'all';
    try {
        configRangeSeries = await fetchConfigRangeSummary(instanceIdQuery);
    } catch (error) {
        console.error(error);
        configRangeSeries = {};
    }
    try {
        taskRangeSeries = await fetchTaskRangeSummary(instanceIdQuery);
    } catch (error) {
        console.error(error);
        taskRangeSeries = {};
    }

    renderConfigTable(instances);
    renderTaskTable(instances);
    buildConfigChart(instances);
    buildTaskChart(instances);
}

async function refreshSelectedMetrics() {
    const ids = getSelectedInstanceIds();
    if (!ids.length) return;

    for (const id of ids) {
        await fetch(`/instances/${id}/metrics/refresh`, { method: 'POST' });
    }

    await loadSummary();
}

function setupTabs() {
    const buttons = document.querySelectorAll('.analytics-tabs .tab-btn');
    const panels = {
        config: document.getElementById('configChartPanel'),
        tasks: document.getElementById('tasksChartPanel')
    };

    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            Object.values(panels).forEach(panel => panel.classList.remove('active'));
            panels[btn.dataset.tab].classList.add('active');
        });
    });
}

function selectAllInstances() {
    const select = document.getElementById('instanceSelect');
    Array.from(select.options).forEach(option => {
        option.selected = true;
    });
}

function toggleCustomRangeFields() {
    const rangeSelect = document.getElementById('taskRangeSelect');
    const customGroup = document.getElementById('customRangeGroup');
    if (rangeSelect.value === 'custom') {
        customGroup.style.display = 'block';
    } else {
        customGroup.style.display = 'none';
    }
}

window.addEventListener('DOMContentLoaded', () => {
    selectAllInstances();
    setupTabs();

    const instanceSelect = document.getElementById('instanceSelect');
    instanceSelect.addEventListener('change', loadSummary);
    instanceSelect.addEventListener('input', loadSummary);

    const rangeSelect = document.getElementById('taskRangeSelect');
    rangeSelect.addEventListener('change', () => {
        userSetRange = true;
        toggleCustomRangeFields();
        loadSummary();
    });

    document.getElementById('customRangeValue').addEventListener('input', () => {
        userSetRange = true;
        loadSummary();
    });
    document.getElementById('customRangeUnit').addEventListener('change', () => {
        userSetRange = true;
        loadSummary();
    });

    document.getElementById('refreshMetricsBtn').addEventListener('click', refreshSelectedMetrics);
    document.getElementById('configSelectAll').addEventListener('click', () => setAllSeries(configSeriesState, CONFIG_RANGE_SERIES, true, 'configSeriesList', () => buildConfigChart(currentInstances)));
    document.getElementById('configSelectNone').addEventListener('click', () => setAllSeries(configSeriesState, CONFIG_RANGE_SERIES, false, 'configSeriesList', () => buildConfigChart(currentInstances)));
    document.getElementById('taskSelectAll').addEventListener('click', () => setAllSeries(taskSeriesState, TASK_SERIES, true, 'taskSeriesList', () => buildTaskChart(currentInstances)));
    document.getElementById('taskSelectNone').addEventListener('click', () => setAllSeries(taskSeriesState, TASK_SERIES, false, 'taskSeriesList', () => buildTaskChart(currentInstances)));

    toggleCustomRangeFields();
    loadSummary();
});
