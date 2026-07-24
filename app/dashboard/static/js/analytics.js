/**
 * MT5 Trading Bot Dashboard — Analytics page JS
 *
 * Pure vanilla JS. Chart.js loaded from CDN.
 * Data sources: /api/stats, /api/equity_curve, /api/trades, /api/rejections
 */

'use strict';

// ── Chart.js theme defaults ───────────────────────────────────────────────
const CHART_DEFAULTS = {
    color:           '#8b949e',
    borderColor:     '#30363d',
    backgroundColor: '#161b22',
};
Chart.defaults.color            = CHART_DEFAULTS.color;
Chart.defaults.borderColor      = CHART_DEFAULTS.borderColor;
Chart.defaults.backgroundColor  = CHART_DEFAULTS.backgroundColor;
Chart.defaults.font.family      = "'Segoe UI', system-ui, sans-serif";
Chart.defaults.font.size        = 12;

const PALETTE = {
    green:  '#3fb950',
    red:    '#f85149',
    blue:   '#58a6ff',
    yellow: '#d29922',
    purple: '#bc8cff',
    orange: '#e8941a',
};

// ── State ─────────────────────────────────────────────────────────────────
let activePeriod = '7d';
let charts       = {};        // { equityChart, winLossChart, scoreChart, rejectionChart }
let allTrades    = [];        // cached full trade list
let sortCol      = 'entry_time_utc';
let sortAsc      = false;

// ── Helpers ───────────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }
function setText(id, v) { const el=$(id); if (el) el.textContent = v; }

function fmtPnl(v) {
    if (v == null) return '—';
    const n = Number(v);
    return (n >= 0 ? '+' : '') + n.toFixed(2);
}
function fmtPrice(v) {
    if (v == null) return '—';
    return Number(v).toFixed(5);
}
function fmtDuration(mins) {
    if (mins == null) return '—';
    const m = Math.round(Number(mins));
    if (m < 60) return m + 'm';
    const h = Math.floor(m / 60), r = m % 60;
    return r ? `${h}h ${r}m` : `${h}h`;
}
function fmtDate(iso) {
    if (!iso) return '—';
    return iso.slice(0, 10);
}
function fmtTime(iso) {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit',hour12:false}); }
    catch { return iso; }
}
function nowStr() {
    return new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
}

async function apiFetch(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`HTTP ${r.status} from ${path}`);
    return r.json();
}

// ── Destroy + recreate a chart ────────────────────────────────────────────
function makeChart(key, canvasId, config) {
    if (charts[key]) { charts[key].destroy(); }
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    charts[key] = new Chart(ctx, config);
}

// ── Period selector ───────────────────────────────────────────────────────
function initPeriodTabs() {
    document.querySelectorAll('.period-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            activePeriod = btn.dataset.period;
            document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('period-active'));
            btn.classList.add('period-active');
            refresh();
        });
    });
}

// ── Key metrics ───────────────────────────────────────────────────────────
function renderMetrics(stats) {
    const total   = stats.total_trades || 0;
    const wins    = stats.wins         || 0;
    const losses  = stats.losses       || 0;
    const pnl     = stats.total_pnl    != null ? stats.total_pnl : null;
    const winRate = stats.win_rate_pct != null ? stats.win_rate_pct : null;
    const avgRR   = stats.avg_r_multiple != null ? stats.avg_r_multiple : null;
    const avgScore= stats.avg_confluence_score != null ? stats.avg_confluence_score : null;

    setText('val-total-trades', total);
    setText('val-win-loss',     `${wins} / ${losses}`);

    const wrEl = $('val-win-rate');
    if (wrEl) {
        wrEl.textContent = winRate != null ? winRate.toFixed(1) + '%' : '—';
        wrEl.className   = 'card-value ' + (winRate >= 55 ? 'text-green' : winRate >= 45 ? 'text-yellow' : 'text-red');
    }
    const pnlEl = $('val-total-pnl');
    if (pnlEl) {
        pnlEl.textContent = pnl != null ? fmtPnl(pnl) : '—';
        pnlEl.className   = 'card-value ' + (pnl != null ? (pnl >= 0 ? 'text-green' : 'text-red') : '');
    }
    setText('val-avg-rr',    avgRR   != null ? avgRR.toFixed(2) + 'R' : '—');
    setText('val-avg-score', avgScore!= null ? avgScore.toFixed(2)     : '—');
}

// ── Equity curve chart ────────────────────────────────────────────────────
function renderEquityChart(equityData) {
    setText('equity-points', equityData.length + ' pts');

    const labels = equityData.map(d => d.date);
    const values = equityData.map(d => d.cumulative_pnl);
    const positive = values.length > 0 && values[values.length - 1] >= 0;

    makeChart('equityChart', 'equityChart', {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label:           'Cumulative P&L',
                data:            values,
                borderColor:     positive ? PALETTE.green : PALETTE.red,
                backgroundColor: positive ? 'rgba(63,185,80,0.08)' : 'rgba(248,81,73,0.08)',
                borderWidth:     2,
                pointRadius:     equityData.length > 30 ? 0 : 3,
                fill:            true,
                tension:         0.3,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: '#21262d' }, ticks: { maxTicksLimit: 8 } },
                y: { grid: { color: '#21262d' } },
            },
        },
    });
}

// ── Win/loss by symbol bar chart ──────────────────────────────────────────
function renderWinLossChart(trades) {
    const bySymbol = {};
    for (const t of trades) {
        const sym = t.symbol || 'OTHER';
        if (!bySymbol[sym]) bySymbol[sym] = { wins: 0, losses: 0 };
        if ((t.pnl || 0) > 0) bySymbol[sym].wins++;
        else if ((t.pnl || 0) < 0) bySymbol[sym].losses++;
    }
    const symbols = Object.keys(bySymbol);
    makeChart('winLossChart', 'winLossChart', {
        type: 'bar',
        data: {
            labels: symbols,
            datasets: [
                { label: 'Wins',   data: symbols.map(s => bySymbol[s].wins),   backgroundColor: PALETTE.green  },
                { label: 'Losses', data: symbols.map(s => bySymbol[s].losses), backgroundColor: PALETTE.red    },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'top' } },
            scales: {
                x: { grid: { color: '#21262d' } },
                y: { grid: { color: '#21262d' }, ticks: { stepSize: 1 } },
            },
        },
    });
}

// ── Confluence score histogram ────────────────────────────────────────────
function renderScoreChart(trades) {
    // Buckets: 8.0–8.4, 8.5–8.9, 9.0–9.4, 9.5–10.0
    const buckets  = ['8.0–8.4', '8.5–8.9', '9.0–9.4', '9.5–10.0'];
    const counts   = [0, 0, 0, 0];
    for (const t of trades) {
        const s = Number(t.confluence_score || 0);
        if      (s < 8.5)  counts[0]++;
        else if (s < 9.0)  counts[1]++;
        else if (s < 9.5)  counts[2]++;
        else               counts[3]++;
    }
    makeChart('scoreChart', 'scoreChart', {
        type: 'bar',
        data: {
            labels: buckets,
            datasets: [{
                label:           'Trades',
                data:            counts,
                backgroundColor: [PALETTE.yellow, PALETTE.blue, PALETTE.green, PALETTE.green],
                borderRadius:    4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: '#21262d' } },
                y: { grid: { color: '#21262d' }, ticks: { stepSize: 1 } },
            },
        },
    });
}

// ── Rejection categories pie chart ────────────────────────────────────────
function renderRejectionChart(rejections) {
    const counts = {};
    for (const r of rejections) {
        const cat = r.rejection_category || 'OTHER';
        counts[cat] = (counts[cat] || 0) + 1;
    }
    // Sort and take top 5
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 5);
    const labels  = sorted.map(([k]) => k);
    const values  = sorted.map(([, v]) => v);
    const colours = [PALETTE.red, PALETTE.yellow, PALETTE.blue, PALETTE.purple, PALETTE.orange];

    makeChart('rejectionChart', 'rejectionChart', {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data:            values,
                backgroundColor: colours.slice(0, labels.length),
                borderColor:     '#161b22',
                borderWidth:     2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right', labels: { boxWidth: 12, padding: 10 } },
            },
        },
    });
}

// ── Session performance table ─────────────────────────────────────────────
function renderSessionTable(trades) {
    const sessions = {};
    for (const t of trades) {
        const sess = (t.session || 'UNKNOWN').toUpperCase();
        if (!sessions[sess]) sessions[sess] = { trades: 0, wins: 0, losses: 0, pnl: 0 };
        sessions[sess].trades++;
        const pnl = t.pnl || 0;
        sessions[sess].pnl += pnl;
        if (pnl > 0) sessions[sess].wins++;
        else if (pnl < 0) sessions[sess].losses++;
    }
    const tbody = $('session-tbody');
    if (!tbody) return;
    const rows = Object.entries(sessions);
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-row">No session data</td></tr>';
        return;
    }
    tbody.innerHTML = rows
        .sort((a, b) => b[1].trades - a[1].trades)
        .map(([sess, d]) => {
            const wr     = d.trades ? ((d.wins / d.trades) * 100).toFixed(1) : '0.0';
            const avgPnl = d.trades ? (d.pnl / d.trades).toFixed(2) : '0.00';
            const wrCls  = Number(wr) >= 55 ? 'text-green' : Number(wr) >= 45 ? 'text-yellow' : 'text-red';
            const pnlCls = d.pnl >= 0 ? 'text-green' : 'text-red';
            return `<tr>
                <td><strong>${sess}</strong></td>
                <td>${d.trades}</td>
                <td class="text-green">${d.wins}</td>
                <td class="text-red">${d.losses}</td>
                <td class="${wrCls}">${wr}%</td>
                <td class="${pnlCls}">${fmtPnl(d.pnl)}</td>
                <td class="${pnlCls}">${fmtPnl(avgPnl)}</td>
            </tr>`;
        }).join('');
}

// ── Trade history table ───────────────────────────────────────────────────
function renderHistoryTable(trades) {
    setText('history-count', trades.length);
    const tbody = $('history-tbody');
    if (!tbody) return;
    if (trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-row">No trade history</td></tr>';
        return;
    }

    // Sort
    const sorted = [...trades].sort((a, b) => {
        let va = a[sortCol], vb = b[sortCol];
        if (va == null) va = '';
        if (vb == null) vb = '';
        if (typeof va === 'string') return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        return sortAsc ? va - vb : vb - va;
    });

    tbody.innerHTML = sorted.map(t => {
        const dir    = (t.direction || '—').toUpperCase();
        const dirCls = dir === 'BUY' ? 'dir-buy' : 'dir-sell';
        const pnl    = t.pnl;
        const pnlCls = pnl != null ? (Number(pnl) >= 0 ? 'text-green' : 'text-red') : '';
        const grade  = t.quality_grade || '—';

        return `<tr>
            <td class="text-muted">${fmtDate(t.entry_time_utc)} ${fmtTime(t.entry_time_utc)}</td>
            <td><strong>${t.symbol || '—'}</strong></td>
            <td><span class="dir-badge ${dirCls}">${dir}</span></td>
            <td><span class="score-pill">${t.confluence_score != null ? t.confluence_score : '—'}</span></td>
            <td class="font-mono">${fmtPrice(t.entry_price)}</td>
            <td class="font-mono">${fmtPrice(t.exit_price)}</td>
            <td class="${pnlCls} font-mono">${fmtPnl(pnl)}</td>
            <td class="text-muted">${t.r_multiple != null ? Number(t.r_multiple).toFixed(2)+'R' : '—'}</td>
            <td class="text-muted">${fmtDuration(t.duration_minutes)}</td>
        </tr>`;
    }).join('');
}

// ── Sortable headers ──────────────────────────────────────────────────────
function initSortableHeaders() {
    document.querySelectorAll('th.sortable').forEach(th => {
        th.style.cursor = 'pointer';
        th.addEventListener('click', () => {
            const col = th.dataset.col;
            if (sortCol === col) { sortAsc = !sortAsc; }
            else { sortCol = col; sortAsc = false; }
            document.querySelectorAll('th.sortable .sort-icon').forEach(ic => ic.textContent = '⇅');
            const icon = th.querySelector('.sort-icon');
            if (icon) icon.textContent = sortAsc ? '▲' : '▼';
            renderHistoryTable(allTrades);
        });
    });
}

// ── CSV export ────────────────────────────────────────────────────────────
function exportCSV() {
    const headers = ['Date','Symbol','Direction','Score','Grade','Entry','Exit','PnL','R-Multiple','Duration','Session','ExitReason'];
    const rows = allTrades.map(t => [
        t.entry_time_utc || '',
        t.symbol         || '',
        t.direction      || '',
        t.confluence_score != null ? t.confluence_score : '',
        t.quality_grade  || '',
        t.entry_price    != null ? t.entry_price : '',
        t.exit_price     != null ? t.exit_price  : '',
        t.pnl            != null ? t.pnl         : '',
        t.r_multiple     != null ? t.r_multiple  : '',
        t.duration_minutes != null ? t.duration_minutes : '',
        t.session        || '',
        t.exit_reason    || '',
    ]);
    const csv = [headers, ...rows].map(r => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `trades_${activePeriod}_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

// ── Main refresh ──────────────────────────────────────────────────────────
async function refresh() {
    try {
        const [statsData, equityData, tradesData, rejectionsData] = await Promise.all([
            apiFetch(`/api/stats?period=${activePeriod}`),
            apiFetch(`/api/equity_curve?period=${activePeriod}`),
            apiFetch(`/api/trades?limit=500`),
            apiFetch(`/api/rejections`),
        ]);

        const trades     = (tradesData    && tradesData.trades)         ? tradesData.trades         : [];
        const equity     = (equityData    && equityData.equity_curve)   ? equityData.equity_curve   : [];
        const rejections = (rejectionsData && rejectionsData.rejections) ? rejectionsData.rejections : [];

        allTrades = trades;

        renderMetrics(statsData || {});
        renderEquityChart(equity);
        renderWinLossChart(trades);
        renderScoreChart(trades);
        renderRejectionChart(rejections);
        renderSessionTable(trades);
        renderHistoryTable(trades);

    } catch (err) {
        console.error('Analytics refresh error:', err);
    } finally {
        setText('header-updated-time', nowStr());
        const spinner = $('loading-spinner');
        spinner && spinner.classList.add('hidden');
    }
}

// ── Boot ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initPeriodTabs();
    initSortableHeaders();
    $('csv-export-btn') && $('csv-export-btn').addEventListener('click', exportCSV);
    refresh();
});
