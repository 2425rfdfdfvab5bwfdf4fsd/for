/**
 * MT5 Trading Bot Dashboard — Market Scanner page JS
 *
 * Pure vanilla JS. No jQuery. No frameworks.
 * Auto-refreshes every 30 seconds.
 * Data sources: /api/signals/history, /api/status
 */

'use strict';

const REFRESH_INTERVAL_MS = 30_000;
const SYMBOLS = ['EURUSD', 'GBPUSD', 'USDJPY'];

// ── Helpers ───────────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }
function setText(id, text) { const el = $(id); if (el) el.textContent = text; }

function fmtTime(isoStr) {
    if (!isoStr) return '—';
    try {
        const d = new Date(isoStr);
        return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    } catch { return isoStr; }
}

function nowStr() {
    return new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

async function apiFetch(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`HTTP ${res.status} from ${path}`);
    return res.json();
}

// ── Filter icon helpers ───────────────────────────────────────────────────

/**
 * Derive filter status icons from the most recent rejection for a symbol.
 * If no rejection exists (signal was executed), all filters are shown as passed.
 */
function buildFilterIcons(lastRejection) {
    const cat = lastRejection ? (lastRejection.rejection_category || '').toUpperCase() : '';

    const filters = [
        { label: 'Session',    blocked: cat.includes('SESSION')    },
        { label: 'Spread',     blocked: cat.includes('SPREAD')     },
        { label: 'News',       blocked: cat.includes('NEWS')       },
        { label: 'Volatility', blocked: cat.includes('VOLATILITY') },
    ];

    return filters.map(f =>
        `<span class="filter-tag ${f.blocked ? 'filter-blocked' : 'filter-ok'}">
            ${f.blocked ? '⚠' : '✓'} ${f.label}
        </span>`
    ).join('');
}

// ── Symbol card builder ───────────────────────────────────────────────────

function buildSymbolCard(symbol, signals, session) {
    // Find most recent signal for this symbol
    const symSignals = signals
        .filter(s => (s.symbol || '').toUpperCase() === symbol)
        .sort((a, b) => {
            const ta = a.entry_time_utc || a.timestamp_utc || '';
            const tb = b.entry_time_utc || b.timestamp_utc || '';
            return tb.localeCompare(ta);
        });

    const latest    = symSignals[0] || null;
    const lastReject = symSignals.find(s => s.signal_outcome === 'REJECTED') || null;

    // Derive values
    const lastTime   = latest ? (latest.entry_time_utc || latest.timestamp_utc || null) : null;
    const direction  = latest ? (latest.direction || 'NONE').toUpperCase() : 'NONE';
    const score      = latest ? latest.confluence_score : null;
    const grade      = latest ? (latest.quality_grade  || '—') : '—';
    const spread     = lastReject ? (lastReject.spread_pips != null ? lastReject.spread_pips.toFixed(1) + ' pips' : '—') : '—';
    const outcome    = latest ? latest.signal_outcome : 'NO_SIGNAL';

    // Card status
    let statusLabel = 'NO_SIGNAL';
    let statusClass = 'status-neutral';
    if (outcome === 'EXECUTED')   { statusLabel = 'EXECUTED';       statusClass = 'status-green';  }
    else if (outcome === 'REJECTED') {
        const cat = lastReject ? (lastReject.rejection_category || '').toUpperCase() : '';
        statusLabel = cat.includes('SESSION') || cat.includes('SPREAD') || cat.includes('NEWS') || cat.includes('VOLATILITY')
            ? 'FILTER_BLOCKED' : 'REJECTED';
        statusClass = 'status-red';
    }

    // Direction styling
    let dirClass = '', dirLabel = direction;
    if (direction === 'BUY')  { dirClass = 'dir-buy';  }
    if (direction === 'SELL') { dirClass = 'dir-sell'; }
    if (direction === 'NONE') { dirClass = '';          dirLabel = 'NONE'; }

    return `
    <div class="symbol-card">
        <div class="symbol-card-header">
            <span class="symbol-name">${symbol}</span>
            <span class="scanner-status ${statusClass}">${statusLabel}</span>
        </div>

        <div class="symbol-meta-row">
            <span class="meta-item"><span class="meta-label">Last scan</span> ${lastTime ? fmtTime(lastTime) : '—'}</span>
            <span class="meta-item"><span class="meta-label">Spread</span> ${spread}</span>
            <span class="meta-item"><span class="meta-label">Session</span> ${session || '—'}</span>
        </div>

        <div class="filter-row">${buildFilterIcons(lastReject)}</div>

        <div class="signal-summary-row">
            <div class="sig-item">
                <div class="sig-label">Last Signal</div>
                <div class="sig-value ${dirClass}">${dirLabel}</div>
            </div>
            <div class="sig-item">
                <div class="sig-label">Score</div>
                <div class="sig-value">${score != null ? score + '/10' : '—'}</div>
            </div>
            <div class="sig-item">
                <div class="sig-label">Grade</div>
                <div class="sig-value grade-${(grade || '').replace('+', 'plus').toLowerCase()}">${grade}</div>
            </div>
        </div>
    </div>`;
}

// ── Render: symbol grid ───────────────────────────────────────────────────

function renderSymbolGrid(signals, session) {
    const grid = $('symbol-grid');
    if (!grid) return;
    grid.innerHTML = SYMBOLS.map(sym => buildSymbolCard(sym, signals, session)).join('');
}

// ── Render: signal history table ──────────────────────────────────────────

function renderSignalsTable(signals) {
    setText('signals-count', signals.length);
    const tbody = $('signals-tbody');
    if (!tbody) return;

    if (signals.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-row">No signals today</td></tr>';
        return;
    }

    // Sort ascending by time for the table
    const sorted = [...signals].sort((a, b) => {
        const ta = a.entry_time_utc || a.timestamp_utc || '';
        const tb = b.entry_time_utc || b.timestamp_utc || '';
        return ta.localeCompare(tb);
    });

    tbody.innerHTML = sorted.map(s => {
        const time      = s.entry_time_utc || s.timestamp_utc || '';
        const dir       = (s.direction || '—').toUpperCase();
        const dirClass  = dir === 'BUY' ? 'dir-buy' : dir === 'SELL' ? 'dir-sell' : '';
        const outcome   = s.signal_outcome || '—';
        const outcomeClass = outcome === 'EXECUTED' ? 'text-green' : outcome === 'REJECTED' ? 'text-red' : 'text-muted';
        const detail    = s.rejection_detail || s.exit_reason || '—';
        const grade     = s.quality_grade || '—';
        const score     = s.confluence_score != null ? s.confluence_score : '—';

        return `<tr>
            <td class="text-muted">${fmtTime(time)}</td>
            <td><strong>${s.symbol || '—'}</strong></td>
            <td><span class="dir-badge ${dirClass}">${dir}</span></td>
            <td><span class="score-pill">${score}</span></td>
            <td class="grade-${(grade).replace('+','plus').toLowerCase()}">${grade}</td>
            <td class="${outcomeClass} font-bold">${outcome}</td>
            <td class="text-muted detail-cell" title="${detail}">${detail}</td>
        </tr>`;
    }).join('');
}

// ── Main refresh ──────────────────────────────────────────────────────────

async function refresh() {
    try {
        const [histData, statusData] = await Promise.all([
            apiFetch('/api/signals/history'),
            apiFetch('/api/status'),
        ]);

        const signals = (histData && histData.signals) ? histData.signals : [];
        const session = statusData ? (statusData.session || '—').toUpperCase() : '—';

        renderSymbolGrid(signals, session);
        renderSignalsTable(signals);

    } catch (err) {
        console.error('Scanner refresh error:', err);
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
});
