/**
 * MT5 Trading Bot Dashboard — Open Positions page JS
 *
 * Pure vanilla JS. No jQuery. No frameworks.
 * Auto-refreshes every 10 seconds (tighter cycle for live P&L).
 * Data source: /api/positions
 */

'use strict';

const REFRESH_INTERVAL_MS = 10_000;

// ── State ─────────────────────────────────────────────────────────────────
let expandedRows = new Set();   // trade_ids of expanded rows
let countdown    = REFRESH_INTERVAL_MS / 1000;

// ── Helpers ───────────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function setText(id, text) {
    const el = $(id);
    if (el) el.textContent = text;
}

function setClass(el, classes) {
    if (typeof el === 'string') el = $(el);
    if (!el) return;
    el.classList.remove('green', 'red', 'yellow', 'text-green', 'text-red', 'text-yellow');
    if (classes) classes.split(' ').forEach(c => c && el.classList.add(c));
}

function fmtPrice(v, decimals = 5) {
    if (v == null) return '—';
    return Number(v).toFixed(decimals);
}

function fmtPnl(v) {
    if (v == null) return '—';
    const n = Number(v);
    return (n >= 0 ? '+' : '') + n.toFixed(2);
}

function fmtLots(v) {
    if (v == null) return '—';
    return Number(v).toFixed(2);
}

function fmtDuration(entryTimeStr) {
    if (!entryTimeStr) return '—';
    try {
        const entryMs = new Date(entryTimeStr).getTime();
        const diffMin = Math.round((Date.now() - entryMs) / 60_000);
        if (diffMin < 0)  return '—';
        if (diffMin < 60) return diffMin + 'm';
        const h = Math.floor(diffMin / 60), m = diffMin % 60;
        return m > 0 ? `${h}h ${m}m` : `${h}h`;
    } catch { return '—'; }
}

function nowStr() {
    return new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

async function apiFetch(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

// ── Indicator pill ────────────────────────────────────────────────────────

function pill(value, trueLabel, trueClass, falseLabel, falseClass) {
    if (value == null) return '<span class="indicator-pill pill-neutral">—</span>';
    return value
        ? `<span class="indicator-pill ${trueClass}">${trueLabel}</span>`
        : `<span class="indicator-pill ${falseClass}">${falseLabel}</span>`;
}

// ── Expanded detail row ───────────────────────────────────────────────────

function buildDetailRow(pos, colSpan) {
    const score = pos.confluence_score;
    const rr    = pos.rr_ratio != null ? Number(pos.rr_ratio).toFixed(2) + 'R' : '—';
    const sess  = pos.session  || '—';
    const grade = pos.quality_grade || '—';
    const id    = pos.trade_id || '';

    // Simple visual score bar (score out of 10)
    const barPct = score != null ? Math.min(100, (Number(score) / 10) * 100) : 0;
    const barColour = barPct >= 90 ? 'var(--green)' : barPct >= 80 ? 'var(--blue)' : 'var(--yellow)';

    return `
    <tr class="detail-row" id="detail-${id}">
        <td colspan="${colSpan}">
            <div class="detail-grid">
                <div class="detail-block">
                    <div class="detail-title">Confluence Score</div>
                    <div class="score-bar-wrap">
                        <div class="score-bar-track">
                            <div class="score-bar-fill" style="width:${barPct}%;background:${barColour}"></div>
                        </div>
                        <span class="score-bar-label">${score != null ? score + ' / 10' : '—'}</span>
                    </div>
                </div>
                <div class="detail-block">
                    <div class="detail-title">Trade Details</div>
                    <table class="detail-kv">
                        <tr><td>Grade</td><td class="grade-${(grade).replace('+','plus').toLowerCase()}">${grade}</td></tr>
                        <tr><td>R:R</td><td>${rr}</td></tr>
                        <tr><td>Session</td><td>${sess}</td></tr>
                        <tr><td>Ticket</td><td class="text-muted">${id || '—'}</td></tr>
                    </table>
                </div>
                <div class="detail-block">
                    <div class="detail-title">Management Status</div>
                    <table class="detail-kv">
                        <tr><td>Break-even</td><td>${pill(pos.be_applied, 'APPLIED', 'pill-blue', 'NOT YET', 'pill-neutral')}</td></tr>
                        <tr><td>Partial TP</td><td>${pill(pos.partial_taken, 'TAKEN', 'pill-orange', 'NOT YET', 'pill-neutral')}</td></tr>
                        <tr><td>Status</td><td><span class="text-muted">${pos.status || '—'}</span></td></tr>
                    </table>
                </div>
            </div>
        </td>
    </tr>`;
}

// ── Render: summary cards ─────────────────────────────────────────────────

function renderSummary(positions) {
    const count    = positions.length;
    const totalPnl = positions.reduce((s, p) => s + (p.pnl != null ? Number(p.pnl) : 0), 0);
    const totalLots = positions.reduce((s, p) => s + (p.lot_size != null ? Number(p.lot_size) : 0), 0);

    setText('val-pos-count', count);
    const pnlEl = $('val-pos-pnl');
    if (pnlEl) {
        pnlEl.textContent = count > 0 ? fmtPnl(totalPnl) : '—';
        setClass(pnlEl, count > 0 ? (totalPnl >= 0 ? 'text-green' : 'text-red') : '');
    }
    setText('val-pos-lots', count > 0 ? fmtLots(totalLots) : '—');
}

// ── Render: positions table ───────────────────────────────────────────────

function renderTable(positions) {
    setText('positions-count', positions.length);
    const tbody = $('positions-tbody');
    if (!tbody) return;

    if (positions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="13" class="empty-row">No open positions</td></tr>';
        return;
    }

    const rows = [];
    for (const pos of positions) {
        const id       = pos.trade_id || '';
        const isOpen   = expandedRows.has(String(id));
        const dirClass = (pos.direction || '').toUpperCase() === 'BUY' ? 'dir-buy' : 'dir-sell';
        const pnl      = pos.pnl;
        const pnlClass = pnl != null ? (Number(pnl) >= 0 ? 'text-green' : 'text-red') : '';
        const grade    = pos.quality_grade || '—';

        rows.push(`
        <tr class="pos-row${isOpen ? ' row-expanded' : ''}" data-id="${id}" role="button" tabindex="0">
            <td class="expand-cell">${isOpen ? '▼' : '▶'}</td>
            <td><strong>${pos.symbol || '—'}</strong></td>
            <td><span class="dir-badge ${dirClass}">${(pos.direction || '—').toUpperCase()}</span></td>
            <td class="font-mono">${fmtLots(pos.lot_size)}</td>
            <td class="font-mono">${fmtPrice(pos.entry_price)}</td>
            <td class="font-mono text-muted">${fmtPrice(pos.sl_price)}</td>
            <td class="font-mono text-muted">${fmtPrice(pos.tp_price)}</td>
            <td class="${pnlClass} font-mono">${pnl != null ? fmtPnl(pnl) : '—'}</td>
            <td class="text-muted">${fmtDuration(pos.entry_time)}</td>
            <td><span class="score-pill">${pos.confluence_score != null ? pos.confluence_score : '—'}</span></td>
            <td class="grade-${grade.replace('+','plus').toLowerCase()}">${grade}</td>
            <td>${pill(pos.be_applied,      '✓', 'pill-blue',   '—', 'pill-neutral')}</td>
            <td>${pill(pos.partial_taken,   '✓', 'pill-orange', '—', 'pill-neutral')}</td>
        </tr>`);

        if (isOpen) {
            rows.push(buildDetailRow(pos, 13));
        }
    }

    tbody.innerHTML = rows.join('');

    // Attach click handlers
    tbody.querySelectorAll('.pos-row').forEach(row => {
        row.addEventListener('click',   () => toggleRow(row.dataset.id));
        row.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleRow(row.dataset.id); }
        });
    });
}

function toggleRow(id) {
    const key = String(id);
    if (expandedRows.has(key)) { expandedRows.delete(key); }
    else                       { expandedRows.add(key);    }
    // Re-render just the tbody without re-fetching
    const tbody = $('positions-tbody');
    if (!tbody) return;
    // Trigger a cached render with last known data
    if (window._lastPositions) renderTable(window._lastPositions);
}

// ── Countdown ticker ──────────────────────────────────────────────────────

function tickCountdown() {
    countdown -= 1;
    if (countdown < 0) countdown = REFRESH_INTERVAL_MS / 1000;
    setText('val-pos-next-refresh', `Next in ${countdown}s`);
}

// ── Main refresh ──────────────────────────────────────────────────────────

async function refresh() {
    try {
        const data = await apiFetch('/api/positions');
        const positions = (data && data.positions) ? data.positions : [];
        window._lastPositions = positions;

        renderSummary(positions);
        renderTable(positions);
        countdown = REFRESH_INTERVAL_MS / 1000;

    } catch (err) {
        console.error('Positions refresh error:', err);
    } finally {
        setText('header-updated-time', nowStr());
        const spinner = $('loading-spinner');
        spinner && spinner.classList.add('hidden');
    }
}

// ── Boot ──────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    refresh();
    setInterval(refresh, REFRESH_INTERVAL_MS);
    setInterval(tickCountdown, 1000);
});
