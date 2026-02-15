/**
 * Pre Flight Data Browser — powered by DataTable.js, ConditionBuilder.js, ColumnPicker.js.
 *
 * Keeps: tab navigation, instance selector, pull/cancel/clear buttons, status polling,
 *        record preview modal, raw JSON modal.
 * Replaces: manual renderTable(), hardcoded referenceLinks, titleize(), search bar.
 */
(() => {
    const config = window.DATA_BROWSER || {};
    const dataTypes = config.dataTypes || [];
    const dataTypeLabels = config.dataTypeLabels || {};
    const instanceSelect = document.getElementById('instanceSelect');
    const tabs = Array.from(document.querySelectorAll('.tab-btn'));
    const currentLabel = document.getElementById('currentDataTypeLabel');
    const currentStatus = document.getElementById('currentDataTypeStatus');
    const instanceMeta = document.getElementById('instanceMeta');
    const pullAllFullBtn = document.getElementById('pullAllFullBtn');
    const pullAllDeltaBtn = document.getElementById('pullAllDeltaBtn');
    const clearAllInstanceBtn = document.getElementById('clearAllInstanceBtn');
    const clearAllAndPullBtn = document.getElementById('clearAllAndPullBtn');
    const preflightJobLogLink = document.getElementById('preflightJobLogLink');
    const pullFullBtn = document.getElementById('pullFullBtn');
    const pullDeltaBtn = document.getElementById('pullDeltaBtn');
    const cancelTypeBtn = document.getElementById('cancelTypeBtn');
    const cancelAllPullsBtn = document.getElementById('cancelAllPullsBtn');
    const clearTypeBtn = document.getElementById('clearTypeBtn');
    const dataProgress = document.getElementById('dataProgress');
    const progressBar = dataProgress ? dataProgress.querySelector('.progress-bar') : null;
    const rawModal = document.getElementById('rawModal');
    const rawModalClose = document.getElementById('rawModalClose');
    const rawModalContent = document.getElementById('rawModalContent');
    const recordPreviewModal = document.getElementById('recordPreviewModal');
    const recordPreviewClose = document.getElementById('recordPreviewClose');
    const recordPreviewFrame = document.getElementById('recordPreviewFrame');
    const recordPreviewOpenTab = document.getElementById('recordPreviewOpenTab');
    const dataTableContainer = document.getElementById('dataTableContainer');

    if (!instanceSelect || !dataTableContainer) {
        return;
    }

    const state = {
        instanceId: config.instanceId || null,
        dataType: config.defaultDataType || dataTypes[0] || null,
        status: null,
        lastPullStatus: null,
        statusRequestInFlight: false,
    };

    /** @type {DataTable|null} */
    let activeDataTable = null;

    // ── Helpers ──────────────────────────────────────────────────────

    function labelForDataType(dataType) {
        return dataTypeLabels[dataType] || dataType;
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        if (!response.ok) throw new Error(`Request failed (${response.status})`);
        return response.json();
    }

    async function postJson(url, payload) {
        return fetchJson(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        });
    }

    // ── Instance meta ───────────────────────────────────────────────

    function setInstanceMeta() {
        const selected = instanceSelect.options[instanceSelect.selectedIndex];
        if (!selected || !selected.value) {
            instanceMeta.textContent = '';
            updatePreflightJobLogLink();
            return;
        }
        const url = selected.getAttribute('data-url') || '';
        const company = selected.getAttribute('data-company') || '';
        const version = selected.getAttribute('data-version') || '';
        const parts = [];
        if (url) parts.push(url);
        if (company) parts.push(`Company: ${company}`);
        if (version) parts.push(`Version: ${version}`);
        instanceMeta.textContent = parts.join(' · ');
        updatePreflightJobLogLink();
    }

    function updatePreflightJobLogLink() {
        if (!preflightJobLogLink) return;
        const base = '/job-log?module=preflight';
        if (state.instanceId) {
            preflightJobLogLink.href = `${base}&instance_id=${encodeURIComponent(state.instanceId)}`;
        } else {
            preflightJobLogLink.href = base;
        }
    }

    // ── Action button state ─────────────────────────────────────────

    function setActionState(enabled) {
        [
            pullAllFullBtn, pullAllDeltaBtn, clearAllInstanceBtn, clearAllAndPullBtn, cancelAllPullsBtn,
            pullFullBtn, pullDeltaBtn, cancelTypeBtn, clearTypeBtn,
        ].forEach((btn) => {
            if (btn) btn.disabled = !enabled;
        });
    }

    function setBusy(isBusy, message) {
        if (dataProgress) {
            dataProgress.style.display = isBusy ? 'block' : 'none';
        }
        if (message) {
            currentStatus.textContent = message;
        }
        [
            pullAllFullBtn, pullAllDeltaBtn, clearAllInstanceBtn, clearAllAndPullBtn, cancelAllPullsBtn,
            pullFullBtn, pullDeltaBtn, cancelTypeBtn, clearTypeBtn,
        ].forEach((btn) => {
            if (btn) btn.disabled = isBusy;
        });
    }

    function setProgress(expectedTotal, pulledSoFar) {
        if (!dataProgress || !progressBar) return;
        if (!expectedTotal || expectedTotal <= 0) {
            dataProgress.classList.remove('determinate');
            progressBar.style.width = '';
            return;
        }
        const pct = Math.min(100, Math.max(0, Math.round((pulledSoFar / expectedTotal) * 100)));
        dataProgress.classList.add('determinate');
        progressBar.style.width = `${pct}%`;
    }

    function formatEta(seconds) {
        if (seconds === null || seconds === undefined) return '';
        const total = Math.max(0, Math.round(seconds));
        const hrs = Math.floor(total / 3600);
        const mins = Math.floor((total % 3600) / 60);
        const secs = total % 60;
        if (hrs > 0) return `${hrs}h:${String(mins).padStart(2, '0')}m:${String(secs).padStart(2, '0')}s`;
        if (mins > 0) return `${mins}m:${String(secs).padStart(2, '0')}s`;
        return `${secs}s`;
    }

    // ── Status polling ──────────────────────────────────────────────

    async function loadStatus() {
        if (!state.instanceId) {
            state.status = null;
            updateStatusLine();
            return;
        }
        if (state.statusRequestInFlight) return;
        state.statusRequestInFlight = true;
        try {
            const data = await fetchJson(`/api/instances/${state.instanceId}/data-status`);
            state.status = data;
            updateBadgeCounts();
            updateStatusLine();

            const pull = state.status?.pulls?.[state.dataType];
            if (pull && pull.status !== state.lastPullStatus && pull.status === 'completed') {
                refreshDataTable();
            }
            state.lastPullStatus = pull?.status || null;
        } catch (err) {
            currentStatus.textContent = 'Status unavailable.';
        } finally {
            state.statusRequestInFlight = false;
        }
    }

    function updateBadgeCounts() {
        if (!state.status) return;
        const counts = state.status.record_counts || {};
        for (const [dataType, count] of Object.entries(counts)) {
            const badge = document.querySelector(`[data-badge='${dataType}']`);
            if (badge) badge.textContent = count ?? 0;
        }
    }

    function updateStatusLine() {
        if (!state.instanceId || !state.dataType) {
            currentLabel.textContent = 'Select a data type';
            currentStatus.textContent = 'No instance selected.';
            currentStatus.title = '';
            setActionState(false);
            return;
        }
        currentLabel.textContent = labelForDataType(state.dataType);
        setActionState(true);
        if (!state.status || !state.status.pulls) {
            currentStatus.textContent = 'Status loading...';
            currentStatus.title = '';
            return;
        }

        const pull = state.status.pulls[state.dataType];
        const run = state.status.active_run || state.status.latest_run;
        const recordCount = (state.status.record_counts || {})[state.dataType] ?? 0;
        if (!pull) {
            currentStatus.textContent = `Records: ${recordCount}`;
            currentStatus.title = '';
            return;
        }
        const lastPulled = pull.last_pulled_at ? pull.last_pulled_at.replace('T', ' ').slice(0, 16) : '-';
        const pulledSoFar = pull.records_pulled ?? 0;
        const expectedTotal = pull.expected_total ?? null;
        const cancelRequested = !!pull.cancel_requested;
        if (pull.status === 'running') {
            const duration = pull.duration ? Math.round(pull.duration) : 0;
            let message = `Status: running · Pulled so far: ${pulledSoFar}`;
            if (expectedTotal) message += ` of ${expectedTotal}`;
            message += ` · In DB: ${recordCount}`;
            if (duration > 600 && pulledSoFar === 0) {
                message += ' · No records pulled after 10+ min (check permissions/query)';
            }
            if (cancelRequested) message += ' · Cancel requested';
            if (run && run.status === 'running') {
                const runQueueTotal = run.queue_total || 0;
                const runCurrentIndex = run.current_index || 1;
                const runPct = run.progress_pct ?? 0;
                const runCurrentLabel = run.current_data_type_label || run.current_data_type || 'Current';
                const etaText = formatEta(run.estimated_remaining_seconds);
                message += ` · Pulling ${runCurrentIndex} of ${runQueueTotal}`;
                message += ` · ${runCurrentLabel}`;
                if (runPct !== null && runPct !== undefined) message += ` · ${runPct}% overall`;
                if (etaText) message += ` · ETA ${etaText}`;
            }
            currentStatus.textContent = message;
            currentStatus.title = '';
            if (dataProgress) dataProgress.style.display = 'block';
            setProgress(expectedTotal, pulledSoFar);
        } else if (pull.status === 'cancelled') {
            currentStatus.textContent = `Status: cancelled · Records: ${recordCount} · Last pulled: ${lastPulled}`;
            currentStatus.title = '';
            if (dataProgress) dataProgress.style.display = 'none';
            setProgress(null, 0);
        } else if (pull.status === 'failed' && pull.error_message) {
            currentStatus.textContent = `Status: failed · ${pull.error_message}`;
            currentStatus.title = pull.error_message;
            if (dataProgress) dataProgress.style.display = 'none';
            setProgress(null, 0);
        } else {
            currentStatus.textContent = `Status: ${pull.status} · Records: ${recordCount} · Last pulled: ${lastPulled}`;
            currentStatus.title = '';
            if (dataProgress) dataProgress.style.display = 'none';
            setProgress(null, 0);
        }

        if (run && run.status && run.status !== 'running') {
            const runQueueTotal = run.queue_total || 0;
            const runCompleted = run.queue_completed || 0;
            const runPct = run.progress_pct ?? 0;
            const etaText = formatEta(run.estimated_remaining_seconds);
            let suffix = ` · Run ${run.status}: ${runCompleted}/${runQueueTotal}`;
            if (runPct !== null && runPct !== undefined) suffix += ` · ${runPct}%`;
            if (etaText) suffix += ` · ETA ${etaText}`;
            currentStatus.textContent += suffix;
        }
    }

    // ── DataTable lifecycle ─────────────────────────────────────────

    function destroyDataTable() {
        if (activeDataTable) {
            activeDataTable.destroy();
            activeDataTable = null;
        }
    }

    function refreshDataTable() {
        if (activeDataTable) {
            activeDataTable.refresh();
        }
    }

    function createDataTable() {
        destroyDataTable();
        if (!state.instanceId || !state.dataType) {
            dataTableContainer.innerHTML = '<p class="muted" style="padding:2rem;text-align:center;">Select an instance and data type.</p>';
            return;
        }

        if (!window.DataTable) {
            dataTableContainer.innerHTML = '<p class="muted" style="padding:2rem;text-align:center;">DataTable.js not loaded.</p>';
            return;
        }

        activeDataTable = new window.DataTable(dataTableContainer, {
            dataUrl: '/api/data-browser/records',
            schemaUrl: '/api/data-browser/schema?table=' + encodeURIComponent(state.dataType) +
                       '&instance_id=' + state.instanceId,
            instanceId: state.instanceId,
            tableName: state.dataType,
            pageSize: 50,
            storageKey: 'db_' + state.dataType + '_' + state.instanceId,
            onReferenceClick: function (snRefTable, value) {
                // Navigate to dynamic browser for the referenced table
                window.location.href = '/browse/' + encodeURIComponent(snRefTable) +
                    '?instance_id=' + state.instanceId +
                    '&filter_field=sys_id&filter_value=' + encodeURIComponent(value);
            },
            onRecordClick: function (_sysId, row) {
                // Open record preview using the static model's _id
                var recordId = row && row._id ? row._id : null;
                if (recordId) {
                    openRecordPreview(recordId);
                }
            },
        });

        activeDataTable.init().catch(function (err) {
            console.error('[data_browser] DataTable init error:', err);
            dataTableContainer.innerHTML =
                '<p style="padding:2rem;text-align:center;color:var(--danger-color);">Failed to load table data.</p>';
        });
    }

    // ── Record preview modal ────────────────────────────────────────

    function buildRecordDetailUrl(recordId, previewMode) {
        const base = `/data-browser/record?instance_id=${state.instanceId}&data_type=${encodeURIComponent(state.dataType)}&record_id=${recordId}`;
        return previewMode ? `${base}&preview=1` : base;
    }

    function openRecordPreview(recordId) {
        if (!recordPreviewModal || !recordPreviewFrame || !recordPreviewOpenTab || !recordId) return;
        recordPreviewOpenTab.href = buildRecordDetailUrl(recordId, false);
        recordPreviewFrame.src = buildRecordDetailUrl(recordId, true);
        recordPreviewModal.style.display = 'flex';
    }

    function closeRecordPreview() {
        if (!recordPreviewModal || !recordPreviewFrame) return;
        recordPreviewModal.style.display = 'none';
        recordPreviewFrame.src = 'about:blank';
    }

    // ── Raw JSON modal ──────────────────────────────────────────────

    function openRawModal(rawJson) {
        if (!rawModal || !rawModalContent) return;
        try {
            const parsed = JSON.parse(rawJson);
            rawModalContent.textContent = JSON.stringify(parsed, null, 2);
        } catch (err) {
            rawModalContent.textContent = rawJson;
        }
        rawModal.style.display = 'block';
    }

    function closeRawModal() {
        if (rawModal) rawModal.style.display = 'none';
    }

    // ── Tab switching ───────────────────────────────────────────────

    function setActiveTab(dataType) {
        tabs.forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.dataType === dataType);
        });
        state.dataType = dataType;
        updateStatusLine();
        createDataTable();
    }

    // ── Event listeners ─────────────────────────────────────────────

    instanceSelect.addEventListener('change', () => {
        const value = instanceSelect.value;
        state.instanceId = value ? parseInt(value, 10) : null;
        setInstanceMeta();
        updateStatusLine();
        loadStatus();
        createDataTable();
        if (state.instanceId) {
            const url = new URL(window.location.href);
            url.searchParams.set('instance_id', state.instanceId);
            window.history.replaceState({}, '', url);
        }
    });

    tabs.forEach((btn) => {
        btn.addEventListener('click', () => setActiveTab(btn.dataset.dataType));
    });

    // Pull buttons
    if (pullFullBtn) {
        pullFullBtn.addEventListener('click', async () => {
            if (!state.instanceId || !state.dataType) return;
            try {
                setBusy(true, 'Starting full pull...');
                await postJson('/api/data-browser/pull', {
                    instance_id: state.instanceId,
                    data_type: state.dataType,
                    mode: 'full',
                });
                await loadStatus();
            } catch (err) {
                alert('Failed to start pull. Check server logs for details.');
            } finally {
                setBusy(false);
            }
        });
    }

    if (pullDeltaBtn) {
        pullDeltaBtn.addEventListener('click', async () => {
            if (!state.instanceId || !state.dataType) return;
            try {
                setBusy(true, 'Starting delta pull...');
                await postJson('/api/data-browser/pull', {
                    instance_id: state.instanceId,
                    data_type: state.dataType,
                    mode: 'delta',
                });
                await loadStatus();
            } catch (err) {
                alert('Failed to start delta pull. Check server logs for details.');
            } finally {
                setBusy(false);
            }
        });
    }

    if (cancelTypeBtn) {
        cancelTypeBtn.addEventListener('click', async () => {
            if (!state.instanceId || !state.dataType) return;
            if (!confirm(`Cancel the running pull for ${labelForDataType(state.dataType)}?`)) return;
            try {
                setBusy(true, 'Requesting cancel...');
                await postJson('/api/data-browser/cancel', {
                    instance_id: state.instanceId,
                    data_type: state.dataType,
                });
                await loadStatus();
            } catch (err) {
                alert('Failed to request cancel. Check server logs for details.');
            } finally {
                setBusy(false);
            }
        });
    }

    if (cancelAllPullsBtn) {
        cancelAllPullsBtn.addEventListener('click', async () => {
            if (!state.instanceId) return;
            if (!confirm('Cancel ALL running or queued pulls for this instance?')) return;
            try {
                setBusy(true, 'Requesting cancel for all pulls...');
                await postJson('/api/data-browser/cancel', { instance_id: state.instanceId });
                await loadStatus();
            } catch (err) {
                alert('Failed to request cancel for all pulls. Check server logs for details.');
            } finally {
                setBusy(false);
            }
        });
    }

    if (clearTypeBtn) {
        clearTypeBtn.addEventListener('click', async () => {
            if (!state.instanceId || !state.dataType) return;
            if (!confirm(`Clear all cached ${labelForDataType(state.dataType)} data for this instance?`)) return;
            try {
                setBusy(true, 'Clearing selected data...');
                await postJson('/api/data-browser/clear', {
                    instance_id: state.instanceId,
                    data_type: state.dataType,
                });
                await loadStatus();
                refreshDataTable();
            } catch (err) {
                alert('Failed to clear selected data. Check server logs for details.');
            } finally {
                setBusy(false);
            }
        });
    }

    if (pullAllFullBtn) {
        pullAllFullBtn.addEventListener('click', async () => {
            if (!state.instanceId) return;
            try {
                setBusy(true, 'Starting full pull for all data types...');
                await postJson(`/api/instances/${state.instanceId}/data-refresh`, { mode: 'full' });
                await loadStatus();
            } catch (err) {
                alert('Failed to start full pull. Check server logs for details.');
            } finally {
                setBusy(false);
            }
        });
    }

    if (pullAllDeltaBtn) {
        pullAllDeltaBtn.addEventListener('click', async () => {
            if (!state.instanceId) return;
            try {
                setBusy(true, 'Starting delta pull for all data types...');
                await postJson(`/api/instances/${state.instanceId}/data-refresh`, { mode: 'delta' });
                await loadStatus();
            } catch (err) {
                alert('Failed to start delta pull. Check server logs for details.');
            } finally {
                setBusy(false);
            }
        });
    }

    if (clearAllInstanceBtn) {
        clearAllInstanceBtn.addEventListener('click', async () => {
            if (!state.instanceId) return;
            if (!confirm('Clear ALL cached data for this instance?')) return;
            try {
                setBusy(true, 'Clearing all data for instance...');
                await postJson('/api/data-browser/clear', { instance_id: state.instanceId });
                await loadStatus();
                refreshDataTable();
            } catch (err) {
                alert('Failed to clear all data. Check server logs for details.');
            } finally {
                setBusy(false);
            }
        });
    }

    if (clearAllAndPullBtn) {
        clearAllAndPullBtn.addEventListener('click', async () => {
            if (!state.instanceId || !state.dataType) return;
            if (!confirm(`Clear ALL cached data and re-pull ${labelForDataType(state.dataType)}?`)) return;
            try {
                setBusy(true, 'Clearing all data and starting pull...');
                await postJson('/api/data-browser/clear', { instance_id: state.instanceId });
                await postJson('/api/data-browser/pull', {
                    instance_id: state.instanceId,
                    data_type: state.dataType,
                    mode: 'full',
                });
                await loadStatus();
            } catch (err) {
                alert('Failed to clear and re-pull data. Check server logs for details.');
            } finally {
                setBusy(false);
            }
        });
    }

    // Modal close handlers
    if (rawModalClose) rawModalClose.addEventListener('click', closeRawModal);
    if (recordPreviewClose) recordPreviewClose.addEventListener('click', closeRecordPreview);
    window.addEventListener('click', (event) => {
        if (event.target === rawModal) closeRawModal();
        if (event.target === recordPreviewModal) closeRecordPreview();
    });
    window.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeRawModal();
            closeRecordPreview();
        }
    });

    // ── Initial load ────────────────────────────────────────────────
    setInstanceMeta();
    updatePreflightJobLogLink();
    if (state.dataType) {
        setActiveTab(state.dataType);
    }
    if (state.instanceId) {
        loadStatus();
    } else {
        updateStatusLine();
    }

    setInterval(() => {
        if (state.instanceId) loadStatus();
    }, 5000);
})();
