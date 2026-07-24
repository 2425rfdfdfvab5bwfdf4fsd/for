/**
 * MT5 Trading Bot Dashboard — Health Monitor page JS
 *
 * Pure vanilla JS. No jQuery. No frameworks.
 * Auto-refreshes every 30 seconds.
 * Data source: /api/health
 *
 * Wrapped in an IIFE to avoid global const/function name collisions with
 * dashboard.js (which is loaded on every page via base.html).
 */

(function () {
'use strict';

const HEALTH_REFRESH_MS = 30_000;

// ── Helpers ───────────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function nowStr() {
    return new Date().toLocaleTimeString('en-GB', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    });
}

async function apiFetch(path) {
    const res = await fetch(path);
    // Accept 200 and 503 — health endpoint returns 503 when checks fail (still valid JSON)
    if (!res.ok && res.status !== 503) throw new Error(`HTTP ${res.status} from ${path}`);
    return res.json();
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function fmtSeconds(s) {
    if (s == null) return '—';
    if (s < 60)   return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    return `${Math.floor(s / 3600)}h ago`;
}

// ── Item builder ──────────────────────────────────────────────────────────

/**
 * Build a <li> health item.
 * @param {boolean|null} ok  - true=green, false=red, null=warning/unknown
 * @param {string}       label   - main label text
 * @param {string}       [detail] - optional detail suffix
 * @param {boolean}      [warn]   - if true, use warning style instead of error
 */
function buildItem(ok, label, detail, warn) {
    let cls, icon;
    if (ok === true)        { cls = 'health-ok';      icon = '✅'; }
    else if (warn === true) { cls = 'health-warn';    icon = '⚠️'; }
    else                    { cls = 'health-error';   icon = '❌'; }

    const detailHtml = detail
        ? `<span class="health-detail">${escapeHtml(detail)}</span>`
        : '';

    return `<li class="health-item ${cls}">
        <span class="health-icon">${icon}</span>
        <span class="health-label">${escapeHtml(label)}${detailHtml}</span>
    </li>`;
}

// ── Group renderers ───────────────────────────────────────────────────────

function renderBotGroup(checks) {
    const hb     = checks.heartbeat || {};
    const items  = [];

    // Heartbeat fresh?
    const hbOk  = hb.ok === true;
    const hbAge = hb.age_seconds != null ? fmtSeconds(hb.age_seconds) : null;
    const hbErr = hb.error || null;

    if (hbErr) {
        items.push(buildItem(false, 'Bot process running', 'heartbeat not found'));
        items.push(buildItem(false, 'Heartbeat fresh', hbErr));
    } else {
        items.push(buildItem(hbOk,  'Bot process running',  hbOk ? null : 'no heartbeat'));
        items.push(buildItem(hbOk,  'Heartbeat fresh',      hbAge || null));
    }

    return items.join('');
}

function renderDataGroup(checks) {
    const db  = checks.database || {};
    const log = checks.log_file || {};
    const items = [];

    // Database
    items.push(buildItem(db.ok === true,  'Database accessible',  db.error || null));

    // Log file
    items.push(buildItem(log.ok === true, 'Log file present',     log.ok ? null : 'app.log not found'));

    return items.join('');
}

function renderConfigGroup(checks) {
    const cfg   = checks.config || {};
    const items = [];

    // Config loaded
    items.push(buildItem(cfg.ok === true, 'Configuration loaded', cfg.error || null));

    // Trading mode
    const mode = cfg.trading_mode || '—';
    items.push(buildItem(true, 'Trading mode', mode));

    // Live trading guard
    const isLive = cfg.live_trading === true;
    items.push(buildItem(
        !isLive,
        'LIVE_TRADING guard',
        isLive ? '⚠ LIVE mode active — real orders enabled' : 'DEMO/safe',
        false,
    ));

    return items.join('');
}

// ── Main render ───────────────────────────────────────────────────────────

function renderHealth(data) {
    const checks  = (data && data.checks) || {};
    const overall = data && data.ok;

    // Banner
    const banner     = $('health-banner');
    const bannerIcon = $('health-banner-icon');
    const bannerText = $('health-banner-text');
    if (banner && bannerIcon && bannerText) {
        bannerIcon.textContent = overall ? '✅' : '❌';
        bannerText.textContent = overall ? 'All systems operational' : 'One or more checks failed';
        banner.className = 'health-banner ' + (overall ? 'health-banner-ok' : 'health-banner-fail');
    }

    // Groups
    const botEl    = $('group-bot');
    const dataEl   = $('group-data');
    const cfgEl    = $('group-config');

    if (botEl)  botEl.innerHTML  = renderBotGroup(checks);
    if (dataEl) dataEl.innerHTML = renderDataGroup(checks);
    if (cfgEl)  cfgEl.innerHTML  = renderConfigGroup(checks);
}

// ── Refresh ───────────────────────────────────────────────────────────────

async function refresh() {
    try {
        const data = await apiFetch('/api/health');
        renderHealth(data);
    } catch (err) {
        console.error('Health monitor refresh error:', err);
        // Show error state in banner
        const banner = $('health-banner');
        const bannerText = $('health-banner-text');
        if (banner) banner.className = 'health-banner health-banner-fail';
        if (bannerText) bannerText.textContent = 'Could not reach /api/health';
    } finally {
        const updated = $('header-updated-time');
        if (updated) updated.textContent = nowStr();

        const spinner = $('loading-spinner');
        if (spinner) spinner.classList.add('hidden');
    }
}

// ── Boot ──────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    refresh();
    setInterval(refresh, HEALTH_REFRESH_MS);
});

})(); // end IIFE
