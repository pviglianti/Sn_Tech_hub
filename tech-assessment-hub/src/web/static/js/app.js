// Tech Assessment Hub - JavaScript

console.log('Tech Assessment Hub loaded');

const THEME_STORAGE_KEY = 'tah_theme';
const DEFAULT_THEME = 'classic';
const SUPPORTED_THEMES = new Set([
    'classic',
    'obsidian-command',
    'carbon-glass',
    'nocturne-ember',
]);

function normalizeTheme(themeValue) {
    if (typeof themeValue !== 'string') return DEFAULT_THEME;
    const cleaned = themeValue.trim().toLowerCase();
    if (!SUPPORTED_THEMES.has(cleaned)) return DEFAULT_THEME;
    return cleaned;
}

function readStoredTheme() {
    try {
        return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
    } catch (error) {
        return DEFAULT_THEME;
    }
}

function persistTheme(themeName) {
    try {
        window.localStorage.setItem(THEME_STORAGE_KEY, normalizeTheme(themeName));
    } catch (error) {
        // Ignore storage failures (private mode / storage restrictions)
    }
}

function formatThemeLabel(themeName) {
    const labels = {
        classic: 'Classic',
        'obsidian-command': 'Obsidian Command',
        'carbon-glass': 'Carbon Glass',
        'nocturne-ember': 'Nocturne Ember',
    };
    return labels[normalizeTheme(themeName)] || labels.classic;
}

function applyTheme(themeName) {
    const resolvedTheme = normalizeTheme(themeName);
    if (document && document.documentElement) {
        document.documentElement.setAttribute('data-theme', resolvedTheme);
    }
    return resolvedTheme;
}

function syncThemeControls(themeName) {
    const resolvedTheme = normalizeTheme(themeName);

    const picker = document.querySelector('[data-theme-picker]');
    if (picker) {
        picker.value = resolvedTheme;
    }

    document.querySelectorAll('[data-theme-current]').forEach((node) => {
        node.textContent = formatThemeLabel(resolvedTheme);
    });

    document.querySelectorAll('[data-theme-option]').forEach((button) => {
        const optionTheme = normalizeTheme(button.getAttribute('data-theme-option') || '');
        const isActive = optionTheme === resolvedTheme;
        button.classList.toggle('is-active', isActive);
        button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        button.setAttribute('aria-checked', isActive ? 'true' : 'false');
    });
}

function setTheme(themeName) {
    const resolvedTheme = applyTheme(themeName);
    persistTheme(resolvedTheme);
    syncThemeControls(resolvedTheme);
    return resolvedTheme;
}

function bindThemeControls() {
    const picker = document.querySelector('[data-theme-picker]');
    if (picker) {
        picker.addEventListener('change', (event) => {
            const target = event.target;
            if (!target) return;
            setTheme(target.value);
        });
    }

    document.querySelectorAll('[data-theme-option]').forEach((button) => {
        button.addEventListener('click', () => {
            const selected = button.getAttribute('data-theme-option');
            if (!selected) return;
            setTheme(selected);
            const menu = button.closest('[data-theme-menu]');
            if (menu && menu.hasAttribute('open')) {
                menu.removeAttribute('open');
            }
        });
    });
}

function bootstrapTheme() {
    const initialTheme = applyTheme(readStoredTheme());
    syncThemeControls(initialTheme);
    bindThemeControls();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapTheme, { once: true });
} else {
    bootstrapTheme();
}

// Utility function to make API calls
async function apiCall(url, method = 'GET', data = null) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
        },
    };

    if (data) {
        options.body = JSON.stringify(data);
    }

    const response = await fetch(url, options);
    return response.json();
}

// ---------------------------------------------------------------------------
// Display Timezone — fetched once from /api/display-timezone, then cached.
// Other scripts (DataTable.js, etc.) can read window.TAH_DISPLAY_TIMEZONE.
// ---------------------------------------------------------------------------

window.TAH_DISPLAY_TIMEZONE = null; // set async on load
window.TAH_TIMEZONE_READY = new Promise(function (resolve) {
    window._tahTzResolve = resolve;
});

(function loadDisplayTimezone() {
    fetch('/api/display-timezone')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
            if (data && data.timezone) {
                window.TAH_DISPLAY_TIMEZONE = data.timezone;
            }
        })
        .catch(function () { /* fall back to browser default */ })
        .finally(function () {
            window._tahTzResolve(window.TAH_DISPLAY_TIMEZONE);
        });
})();

// Format dates nicely — uses configured display timezone when available.
function formatDate(dateString) {
    if (!dateString) return '-';
    // Ensure the string is parsed as UTC if it lacks timezone info.
    // ServiceNow and our DB store naive UTC datetimes like "2026-02-15 14:30:00".
    var normalized = String(dateString).trim();
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(normalized) && normalized.indexOf('T') === -1) {
        normalized = normalized.replace(' ', 'T') + 'Z';
    } else if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(normalized) && !/[Zz+\-]\d{0,4}$/.test(normalized)) {
        normalized += 'Z';
    }
    var date = new Date(normalized);
    if (isNaN(date.getTime())) return dateString;

    var opts = {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', hour12: false,
    };
    if (window.TAH_DISPLAY_TIMEZONE) {
        opts.timeZone = window.TAH_DISPLAY_TIMEZONE;
    }
    try {
        return date.toLocaleString('en-US', opts);
    } catch (e) {
        return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
    }
}

// ── Dictionary Pull Progress Monitor ──

/**
 * Poll the dictionary-pull-status endpoint every 3 seconds and update the
 * progress modal in base.html.  Auto-closes when pull completes or fails.
 *
 * @param {number} instanceId  The instance whose dictionary pull to monitor
 */
// ── Global Tab Switcher ──
// Scopes tab switching to the nearest .tab-container, fires a custom event
// for lazy-load listeners.  Replaces per-template openTab/openScanTab/openResultTab.
window.openTab = function openTab(evt, tabName) {
    var container = evt && evt.currentTarget
        ? evt.currentTarget.closest('.tab-container') || document
        : document;
    container.querySelectorAll('.tab-content').forEach(function (el) {
        el.classList.remove('active');
    });
    container.querySelectorAll('.tab-btn').forEach(function (el) {
        el.classList.remove('active');
    });
    var target = document.getElementById(tabName);
    if (target) target.classList.add('active');
    if (evt && evt.currentTarget) evt.currentTarget.classList.add('active');
    document.dispatchEvent(new CustomEvent('tab:activated', { detail: { tabName: tabName } }));
};

window.stopDictPullMonitor = function stopDictPullMonitor() {
    if (window.__dictPullMonitor && window.__dictPullMonitor.timerId) {
        clearInterval(window.__dictPullMonitor.timerId);
    }
    window.__dictPullMonitor = null;
};

window.startDictPullMonitor = function startDictPullMonitor(instanceId) {
    const modal       = document.getElementById('dict-pull-modal');
    const statusText  = document.getElementById('dict-pull-status-text');
    const progressBar = document.getElementById('dict-pull-progress-bar');
    const tableCount  = document.getElementById('dict-pull-table-count');
    const etaSpan     = document.getElementById('dict-pull-eta');

    if (!modal) return;

    if (window.__dictPullMonitor && window.__dictPullMonitor.instanceId === instanceId) {
        return;
    }
    if (window.stopDictPullMonitor) {
        window.stopDictPullMonitor();
    }

    // Show the modal
    modal.style.display = 'flex';
    statusText.textContent  = 'Starting dictionary pull...';
    progressBar.style.width = '0%';
    tableCount.textContent  = '0 / 0 tables';
    etaSpan.textContent     = '';

    const POLL_INTERVAL_MS = 3000;
    let timerId = null;
    window.__dictPullMonitor = { instanceId: instanceId, timerId: null };

    function formatEta(seconds) {
        if (seconds == null || seconds < 0) return '';
        if (seconds < 60) return Math.round(seconds) + 's remaining';
        const mins = Math.floor(seconds / 60);
        const secs = Math.round(seconds % 60);
        return mins + 'm ' + secs + 's remaining';
    }

    async function poll() {
        try {
            const resp = await fetch(
                '/api/instances/' + encodeURIComponent(instanceId) + '/dictionary-pull-status'
            );
            if (!resp.ok) {
                statusText.textContent = 'Unable to fetch status (HTTP ' + resp.status + ')';
                return;
            }
            const data = await resp.json();

            const pct = data.total_tables
                ? Math.round((data.completed_tables / data.total_tables) * 100)
                : 0;

            progressBar.style.width = pct + '%';
            tableCount.textContent  = data.completed_tables + ' / ' + data.total_tables + ' tables';

            if (data.current_table) {
                statusText.textContent = 'Pulling: ' + data.current_table;
            }

            if (data.eta_seconds != null) {
                etaSpan.textContent = formatEta(data.eta_seconds);
            } else {
                etaSpan.textContent = '';
            }

            if (data.status === 'completed') {
                statusText.textContent  = 'Dictionary pull complete!';
                progressBar.style.width = '100%';
                etaSpan.textContent     = '';
                clearInterval(timerId);
                if (window.__dictPullMonitor) {
                    window.__dictPullMonitor.timerId = null;
                }
                setTimeout(function () {
                    modal.style.display = 'none';
                    if (window.stopDictPullMonitor) {
                        window.stopDictPullMonitor();
                    }
                    // Reload page if we're on instances page to update status
                    if (window.location.pathname === '/instances') {
                        window.location.reload();
                    }
                }, 2000);
            } else if (data.status === 'failed') {
                statusText.textContent = 'Pull failed: ' + (data.error || 'unknown error');
                clearInterval(timerId);
                if (window.__dictPullMonitor) {
                    window.__dictPullMonitor.timerId = null;
                }
                setTimeout(function () {
                    modal.style.display = 'none';
                    if (window.stopDictPullMonitor) {
                        window.stopDictPullMonitor();
                    }
                }, 2500);
            } else if (data.status !== 'running') {
                clearInterval(timerId);
                if (window.__dictPullMonitor) {
                    window.__dictPullMonitor.timerId = null;
                }
                modal.style.display = 'none';
                if (window.stopDictPullMonitor) {
                    window.stopDictPullMonitor();
                }
            }
        } catch (err) {
            statusText.textContent = 'Polling error: ' + err.message;
        }
    }

    // First poll immediately, then every 3 seconds
    poll();
    timerId = setInterval(poll, POLL_INTERVAL_MS);
    if (window.__dictPullMonitor) {
        window.__dictPullMonitor.timerId = timerId;
    }
};
