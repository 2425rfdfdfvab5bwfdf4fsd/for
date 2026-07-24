/**
 * MT5 Trading Bot Dashboard — Overview page JS
 *
 * Pure vanilla JS. No jQuery. No frameworks.
 * Auto-refreshes every 30 seconds.
 * All data fetched from the Flask REST API (/api/*).
 */

'use strict';

// ── Config ────────────────────────────────────────────────────────────────
const REFRESH_INTERVAL_MS = 30_000;
const MAX_DAILY_TRADES    = 3;   // fallback display limit (overridden by status)
const MAX_CONSEC_LOSSES   = 2;   // fallback

// ── Helpers ───────────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function setText(id, text) {
    const el = $(id);
    if (el) el.textContent = text;
}

function setClass(el, classes) {
    if (typeof el === 'string') el = $(el);
    if (!el) return;
    // Remove state classes then add new ones
    el.classList.remove('green', 'red', 'yellow', 'text-green', 'text-red', 'text-yellow');
    if (classes) classes.split(' ').forEach(c => c && el.classList.add(c));
}

function fmtPrice(v) {
    if (v == null) return '—';
    return Number(v).toFixed(5);
}

function fmtPnl(v) {
    if (v == null) return '—';
    const n = Number(v);
    return (n >= 0 ? '+' : '') + n.toFixed(2);
}

function fmtPct(v) {
    if (v == null) return '—';
    return Number(v).toFixed(2) + '%';
}

function fmtDuration(minutes) {
    if (minutes == null) return '—';
    const m = Math.round(Number(minutes));
    if (m < 60) return m + 'm';
    const h = Math.floor(m / 60), rem = m % 60;
    return rem > 0 ? `${h}h ${rem}m` : `${h}h`;
}

function fmtTime(isoStr) {
    if (!isoStr) return '—';
    try {
        const d = new Date(isoStr);
        return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
    } catch { return isoStr; }
}

function nowStr() {
    return new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

// ── Fetch helpers ─────────────────────────────────────────────────────────

async function apiFetch(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`HTTP ${res.status} from ${path}`);
    return res.json();
}

// ── Render: header & status cards ────────────────────────────────────────

function renderStatus(data) {
    const isOffline = !data || data.status === 'offline' || data.status === 'stale';
    const banner = $('offline-banner');

    if (isOffline) {
        banner && banner.classList.remove('hidden');
    } else {
        banner && banner.classList.add('hidden');
    }

    // Header dot + text
    const dot = $('header-status-dot');
    const statusText = $('header-status-text');

    if (!data) {
        setClass(dot, '');
        setText('header-status-text', 'UNKNOWN');
    } else if (data.status === 'offline') {
        setClass(dot, 'red');
        setText('header-status-text', 'OFFLINE');
    } else if (data.status === 'stale') {
        setClass(dot, 'yellow');
        setText('header-status-text', 'STALE');
    } else {
        setClass(dot, 'green');
        setText('header-status-text', (data.status || 'RUNNING').toUpperCase());
    }

    // Mode badge
    const modeBadge = $('header-mode');
    if (modeBadge) {
        const mode = (data && data.mode) ? data.mode.toUpperCase() : 'DEMO';
        modeBadge.textContent = mode;
        modeBadge.className = 'badge ' + (mode === 'LIVE' ? 'badge-live' : 'badge-demo');
    }

    // Card: BOT STATUS
    const botCard = $('card-bot-status');
    const botVal  = $('val-bot-status');
    if (isOffline) {
        setText('val-bot-status', data && data.status === 'stale' ? 'STALE' : 'STOPPED');
        setClass(botCard, 'red');
        setClass(botVal, 'text-red');
    } else {
        setText('val-bot-status', 'RUNNING');
        setClass(botCard, 'green');
        setClass(botVal, 'text-green');
    }

    // Card: MT5 STATUS
    const mt5Card = $('card-mt5-status');
    const mt5Val  = $('val-mt5-status');
    const mt5Connected = data && data.mt5_connected;
    setText('val-mt5-status', mt5Connected ? 'CONNECTED' : 'DISCONNECTED');
    setClass(mt5Card, mt5Connected ? 'green' : 'red');
    setClass(mt5Val,  mt5Connected ? 'text-green' : 'text-red');

    // Card: SESSION
    const session = (data && data.session) ? data.session.toUpperCase() : '—';
    setText('val-session', session);
    const sessionCard = $('card-session');
    const isActiveSession = ['LONDON', 'NEW_YORK', 'OVERLAP'].includes(session);
    setClass(sessionCard, isActiveSession ? 'green' : '');

    // Card: TRADING ALLOWED
    const allowed = data && data.trading_allowed;
    const tCard = $('card-trading-allowed');
    const tVal  = $('val-trading-allowed');
    setText('val-trading-allowed', allowed ? 'YES' : 'NO');
    setClass(tCard, allowed ? 'green' : 'red');
    setClass(tVal,  allowed ? 'text-green' : 'text-red');

    // Daily metrics from status payload
    const tradesToday = (data && data.trades_today != null) ? data.trades_today : '—';
    const maxTrades   = (data && data.max_daily_trades)     ? data.max_daily_trades : MAX_DAILY_TRADES;
    setText('val-trades',     tradesToday !== '—' ? `${tradesToday} / ${maxTrades}` : '—');
    setText('val-trades-sub', '');

    const dailyPnl = (data && data.daily_pnl != null) ? data.daily_pnl : null;
    const pnlEl = $('val-pnl');
    if (dailyPnl != null) {
        pnlEl.textContent = fmtPnl(dailyPnl);
        setClass(pnlEl, dailyPnl >= 0 ? 'text-green' : 'text-red');
    } else {
        setText('val-pnl', '—');
    }

    const equity = (data && data.equity != null) ? data.equity : null;
    setText('val-equity', equity != null ? `Equity: $${Number(equity).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2})}` : 'Equity: —');

    const dailyLossPct = (data && data.daily_loss_pct != null) ? data.daily_loss_pct : null;
    const maxLossPct   = (data && data.max_daily_loss_pct)     ? data.max_daily_loss_pct : 2.0;
    const lossEl = $('val-daily-loss');
    if (dailyLossPct != null) {
        lossEl.textContent = fmtPct(dailyLossPct);
        const lossRatio = Math.abs(dailyLossPct) / maxLossPct;
        setClass(lossEl, lossRatio >= 0.8 ? 'text-red' : lossRatio >= 0.5 ? 'text-yellow' : 'text-green');
    } else {
        setText('val-daily-loss', '—');
    }
    setText('val-daily-loss-limit', `Limit: ${maxLossPct}%`);

    const consecLosses    = (data && data.consecutive_losses != null) ? data.consecutive_losses : null;
    const maxConsecLosses = (data && data.max_consecutive_losses)     ? data.max_consecutive_losses : MAX_CONSEC_LOSSES;
    const consecEl = $('val-consec-losses');
    if (consecLosses != null) {
        consecEl.textContent = `${consecLosses} / ${maxConsecLosses}`;
        setClass(consecEl, consecLosses >= maxConsecLosses ? 'text-red' : consecLosses > 0 ? 'text-yellow' : 'text-green');
    } else {
        setText('val-consec-losses', '—');
    }
    setText('val-consec-losses-limit', `Max: ${maxConsecLosses}`);
}

// ── Render: open positions table ──────────────────────────────────────────

function renderPositions(data) {
    const positions = (data && data.positions) ? data.positions : [];
    setText('positions-count', positions.length);

    const tbody = $('positions-tbody');
    if (!tbody) return;

    if (positions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-row">No open positions</td></tr>';
        return;
    }

    tbody.innerHTML = positions.map(p => {
        const dirClass = (p.direction || '').toUpperCase() === 'BUY' ? 'dir-buy' : 'dir-sell';
        const pnlClass = p.pnl >= 0 ? 'text-green' : 'text-red';
        const entryTime = p.entry_time ? new Date(p.entry_time) : null;
        const durationMin = entryTime ? Math.round((Date.now() - entryTime.getTime()) / 60_000) : null;

        return `<tr>
            <td><strong>${p.symbol || '—'}</strong></td>
            <td><span class="dir-badge ${dirClass}">${(p.direction || '—').toUpperCase()}</span></td>
            <td class="font-mono">${fmtPrice(p.entry_price)}</td>
            <td class="${pnlClass} font-mono">${p.pnl != null ? fmtPnl(p.pnl) : '—'}</td>
            <td class="font-mono text-muted">${fmtPrice(p.sl_price)}</td>
            <td class="font-mono text-muted">${fmtPrice(p.tp_price)}</td>
            <td class="text-muted">${fmtDuration(durationMin)}</td>
            <td><span class="score-pill">${p.confluence_score != null ? p.confluence_score : '—'}</span></td>
        </tr>`;
    }).join('');
}

// ── Render: trade history table ───────────────────────────────────────────

function renderHistory(data) {
    const trades = (data && data.trades) ? data.trades : [];
    setText('history-count', trades.length);

    const tbody = $('history-tbody');
    if (!tbody) return;

    if (trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="empty-row">No trades today</td></tr>';
        return;
    }

    tbody.innerHTML = trades.map(t => {
        const dirClass = (t.direction || '').toUpperCase() === 'BUY' ? 'dir-buy' : 'dir-sell';
        const pnlClass = (t.pnl || 0) >= 0 ? 'text-green' : 'text-red';

        return `<tr>
            <td class="text-muted">${fmtTime(t.entry_time_utc)}</td>
            <td><strong>${t.symbol || '—'}</strong></td>
            <td><span class="dir-badge ${dirClass}">${(t.direction || '—').toUpperCase()}</span></td>
            <td class="font-mono">${fmtPrice(t.entry_price)}</td>
            <td class="font-mono">${fmtPrice(t.exit_price)}</td>
            <td class="${pnlClass} font-mono">${fmtPnl(t.pnl)}</td>
            <td class="text-muted">${t.r_multiple != null ? Number(t.r_multiple).toFixed(2) + 'R' : '—'}</td>
            <td class="text-muted">${fmtDuration(t.duration_minutes)}</td>
            <td class="text-muted">${t.exit_reason || '—'}</td>
            <td><span class="score-pill">${t.confluence_score != null ? t.confluence_score : '—'}</span></td>
        </tr>`;
    }).join('');
}

// ── Main refresh cycle ────────────────────────────────────────────────────

async function refresh() {
    try {
        const [statusData, posData, tradeData] = await Promise.all([
            apiFetch('/api/status'),
            apiFetch('/api/positions'),
            apiFetch('/api/trades'),
        ]);

        renderStatus(statusData);
        renderPositions(posData);
        renderHistory(tradeData);

    } catch (err) {
        console.error('Dashboard refresh error:', err);
        // Show offline state on fetch failure
        renderStatus(null);
        $('offline-banner') && $('offline-banner').classList.remove('hidden');
    } finally {
        setText('header-updated-time', nowStr());
        const spinner = $('loading-spinner');
        spinner && spinner.classList.add('hidden');
    }
}

// ── History toggle (collapse/expand) ─────────────────────────────────────

function initHistoryToggle() {
    const toggle  = $('history-toggle');
    const body    = $('history-body');
    const chevron = $('history-chevron');
    if (!toggle || !body) return;

    toggle.addEventListener('click', () => {
        const collapsed = body.classList.toggle('collapsed');
        chevron && chevron.classList.toggle('open', !collapsed);
        toggle.setAttribute('aria-expanded', !collapsed);
    });

    toggle.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            toggle.click();
        }
    });
}

// ── Boot ──────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initHistoryToggle();
    refresh();
    setInterval(refresh, REFRESH_INTERVAL_MS);
});
