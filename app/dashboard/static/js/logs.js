/**
 * MT5 Trading Bot Dashboard — Log Viewer page JS
 *
 * Pure vanilla JS. No jQuery. No frameworks.
 * Auto-refreshes every 15 seconds.
 * Data source: /api/logs?lines=500
 *
 * Log line format (from app/logger.py):
 *   "2026-07-24 10:30:00 | INFO     | app.mt5.connection                   | message"
 *
 * Wrapped in an IIFE to avoid global const/function name collisions with
 * dashboard.js (which is loaded on every page via base.html).
 */

(function () {
'use strict';

const LOGS_REFRESH_MS = 15_000;
const LINES_TO_FETCH  = 500;

// ── State ─────────────────────────────────────────────────────────────────

let allParsedLines = [];   // [{time, level, module, message, raw}]
let activeLevel    = 'ALL';
let searchTerm     = '';
let autoScroll     = true;

// ── Helpers ───────────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function nowStr() {
    return new Date().toLocaleTimeString('en-GB', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    });
}

async function apiFetch(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`HTTP ${res.status} from ${path}`);
    return res.json();
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ── Log line parser ───────────────────────────────────────────────────────

// Expected: "2026-07-24 10:30:00 | INFO     | app.mt5.connection | message text"
const LOG_RE = /^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*\|\s*(\w+)\s*\|\s*([^\|]+?)\s*\|\s*([\s\S]*)$/;

const LEVEL_ORDER = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];

function parseLine(raw) {
    const m = LOG_RE.exec(raw);
    if (!m) {
        return { time: '', level: 'INFO', module: '', message: raw, raw };
    }
    return {
        time:    m[1].trim(),
        level:   m[2].trim().toUpperCase(),
        module:  m[3].trim(),
        message: m[4].trim(),
        raw,
    };
}

// ── Level → CSS class ─────────────────────────────────────────────────────

function levelClass(level) {
    switch (level) {
        case 'DEBUG':    return 'log-debug';
        case 'INFO':     return 'log-info';
        case 'WARNING':  return 'log-warning';
        case 'ERROR':    return 'log-error';
        case 'CRITICAL': return 'log-critical';
        default:         return 'log-info';
    }
}

// ── Filter + render ───────────────────────────────────────────────────────

function applyFilters() {
    const term = searchTerm.toLowerCase();

    return allParsedLines.filter(ln => {
        // Level filter
        if (activeLevel !== 'ALL' && ln.level !== activeLevel) return false;
        // Text search
        if (term && !ln.raw.toLowerCase().includes(term)) return false;
        return true;
    });
}

function renderTable(filtered) {
    const tbody = $('logs-tbody');
    if (!tbody) return;

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-row">No log lines match the current filter</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(ln => {
        const cls = levelClass(ln.level);
        return `<tr class="${cls}">
            <td class="log-col-time log-time text-muted">${escapeHtml(ln.time || '—')}</td>
            <td class="log-col-level"><span class="log-level-badge log-badge-${ln.level.toLowerCase()}">${escapeHtml(ln.level)}</span></td>
            <td class="log-col-module log-module text-muted" title="${escapeHtml(ln.module)}">${escapeHtml(ln.module)}</td>
            <td class="log-col-msg log-message">${escapeHtml(ln.message)}</td>
        </tr>`;
    }).join('');
}

function updateLineCount(total, visible) {
    const countEl = $('logs-line-count');
    if (countEl) countEl.textContent = `Showing last ${total} lines`;

    const visEl = $('logs-visible-count');
    if (visEl) visEl.textContent = visible;
}

function scrollToBottom() {
    if (!autoScroll) return;
    const wrap = $('logs-table-wrap');
    if (wrap) wrap.scrollTop = wrap.scrollHeight;
}

function redraw() {
    const filtered = applyFilters();
    renderTable(filtered);
    updateLineCount(allParsedLines.length, filtered.length);
    scrollToBottom();
}

// ── Data fetch ────────────────────────────────────────────────────────────

async function refresh() {
    try {
        const data = await apiFetch(`/api/logs?lines=${LINES_TO_FETCH}`);
        const rawLines = (data && Array.isArray(data.lines)) ? data.lines : [];
        allParsedLines = rawLines.map(parseLine);
        redraw();
    } catch (err) {
        console.error('Log viewer refresh error:', err);
    } finally {
        const text = $('header-updated-time');
        if (text) text.textContent = nowStr();

        const spinner = $('loading-spinner');
        if (spinner) spinner.classList.add('hidden');
    }
}

// ── Event wiring ──────────────────────────────────────────────────────────

function initFilterButtons() {
    document.querySelectorAll('.log-filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            activeLevel = btn.dataset.level || 'ALL';
            document.querySelectorAll('.log-filter-btn').forEach(b => b.classList.remove('log-filter-active'));
            btn.classList.add('log-filter-active');
            redraw();
        });
    });
}

function initSearch() {
    const input = $('log-search');
    if (!input) return;
    input.addEventListener('input', () => {
        searchTerm = input.value;
        redraw();
    });
}

function initAutoScrollToggle() {
    const toggle = $('auto-scroll-toggle');
    if (!toggle) return;
    toggle.addEventListener('change', () => {
        autoScroll = toggle.checked;
        if (autoScroll) scrollToBottom();
    });
}

// ── Boot ──────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initFilterButtons();
    initSearch();
    initAutoScrollToggle();
    refresh();
    setInterval(refresh, LOGS_REFRESH_MS);
});

})(); // end IIFE
