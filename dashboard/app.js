// The engine logs money as integer hundredths of a cent, so 10000 == $1.00.
const PNL_SCALE = 10000;
const INITIAL_ROWS = 100;

// Order matters: this is the order outcomes appear in the breakdown table.
const OUTCOMES = {
    success:           { label: 'Both legs filled',  short: 'filled',   css: 'out-filled' },
    partial_unwind:    { label: 'Partial, unwound',  short: 'partial',  css: 'out-partial' },
    leg_failed_unwind: { label: 'One leg, unwound',  short: 'unwound',  css: 'out-unwound' },
    failed_no_fill:    { label: 'No fill',           short: 'no fill',  css: 'out-miss' },
};

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const usd = (n) => (n < 0 ? '-$' : '$') + Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
});
const count = (n) => n.toLocaleString('en-US');
const pct = (n, d) => (d ? (100 * n / d).toFixed(1) + '%' : '—');

const dollars = (row) => Number(row.net_realized_pnl || 0) / PNL_SCALE;
const num = (row, key) => Number(row[key] || 0);
const day = (row) => row.timestamp.slice(0, 10);

function dateLabel(isoDay) {
    const [y, m, d] = isoDay.split('-');
    return `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}`;
}

function timeLabel(iso) {
    const [date, rest] = iso.split('T');
    const [, m, d] = date.split('-');
    return `${Number(d)} ${MONTHS[Number(m) - 1]}  ${rest.slice(0, 8)}`;
}

function median(values) {
    if (!values.length) return null;
    const s = [...values].sort((a, b) => a - b);
    const mid = s.length >> 1;
    return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function cell(row, text, className) {
    const td = row.insertCell();
    td.textContent = text;
    if (className) td.className = className;
    return td;
}

async function load() {
    const res = await fetch('data.json');
    if (!res.ok) throw new Error(`data.json returned ${res.status}`);
    const trades = await res.json();
    if (!Array.isArray(trades) || !trades.length) {
        document.getElementById('intro-line').textContent =
            'No execution records in this snapshot. Run build_static_data.py to regenerate data.json.';
        return;
    }
    trades.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    render(trades);
}

function render(trades) {
    const realized = trades.reduce((sum, t) => sum + dollars(t), 0);
    const modelled = trades.reduce((sum, t) => sum + num(t, 'theoretical_profit'), 0) / PNL_SCALE;
    const contracts = trades.reduce((sum, t) => sum + num(t, 'intended_qty'), 0);
    const markets = new Set(trades.map((t) => t.pair_id)).size;
    const filled = trades.filter((t) => t.outcome === 'success' || t.outcome === 'partial_unwind').length;

    const first = dateLabel(day(trades[0]));
    const last = dateLabel(day(trades[trades.length - 1]));

    document.getElementById('intro-line').textContent =
        `${count(trades.length)} arbitrage attempts across ${count(markets)} Kalshi/Polymarket ` +
        `market pairs, ${first} to ${last}. Every figure below is computed from the raw ` +
        `execution log, including the attempts that missed a leg.`;

    setFigure('f-pnl', usd(realized), realized >= 0 ? 'gain' : 'loss');
    setFigure('f-trades', count(trades.length));
    setFigure('f-filled', pct(filled, trades.length));
    setFigure('f-volume', count(contracts));
    setFigure('f-capture', pct(realized, modelled));

    document.getElementById('f-filled-note').textContent = `${count(filled)} of ${count(trades.length)}`;
    document.getElementById('f-capture-note').textContent = `${usd(modelled)} modelled`;

    renderOutcomes(trades);
    renderLatency(trades);
    renderChart(cumulativeByDay(trades));
    renderLedger([...trades].reverse());
}

function setFigure(id, text, className) {
    const el = document.getElementById(id);
    el.textContent = text;
    if (className) el.classList.add(className);
}

function renderOutcomes(trades) {
    const tbody = document.getElementById('outcome-rows');
    for (const [key, meta] of Object.entries(OUTCOMES)) {
        const n = trades.filter((t) => t.outcome === key).length;
        const tr = tbody.insertRow();
        cell(tr, meta.label, meta.css);
        cell(tr, count(n));
        cell(tr, pct(n, trades.length), 'share');
    }
}

function renderLatency(trades) {
    const rows = [
        ['Kalshi', median(trades.map((t) => num(t, 'k_fill_time_ms')).filter((v) => v > 0))],
        ['Polymarket', median(trades.map((t) => num(t, 'p_fill_time_ms')).filter((v) => v > 0))],
    ];
    const tbody = document.getElementById('latency-rows');
    for (const [venue, ms] of rows) {
        const tr = tbody.insertRow();
        cell(tr, venue);
        cell(tr, ms === null ? '—' : `${Math.round(ms)} ms`);
    }
}

function cumulativeByDay(trades) {
    const byDay = new Map();
    for (const t of trades) {
        byDay.set(day(t), (byDay.get(day(t)) || 0) + dollars(t));
    }
    let running = 0;
    return [...byDay].map(([date, delta]) => {
        running += delta;
        return { date, total: running };
    });
}

function renderChart(series) {
    const ctx = document.getElementById('pnl-chart');
    const gridColor = '#eae7e0';

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: series.map((p) => p.date),
            datasets: [{
                data: series.map((p) => p.total),
                borderColor: '#1f3f66',
                borderWidth: 1.5,
                pointRadius: 0,
                pointHitRadius: 12,
                tension: 0,
                fill: false,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    displayColors: false,
                    backgroundColor: '#1c1b19',
                    padding: 8,
                    cornerRadius: 2,
                    titleFont: { size: 11, weight: '400' },
                    bodyFont: { size: 12 },
                    callbacks: {
                        title: (items) => dateLabel(items[0].label),
                        label: (item) => usd(item.parsed.y),
                    },
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                    border: { color: '#cbc7bd' },
                    ticks: {
                        color: '#7a766d',
                        font: { size: 11 },
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 8,
                        callback(value) {
                            const iso = this.getLabelForValue(value);
                            const [, m, d] = iso.split('-');
                            return `${Number(d)} ${MONTHS[Number(m) - 1]}`;
                        },
                    },
                },
                y: {
                    grid: { color: gridColor },
                    border: { display: false },
                    ticks: {
                        color: '#7a766d',
                        font: { size: 11 },
                        maxTicksLimit: 6,
                        callback: (v) => '$' + count(v),
                    },
                },
            },
        },
    });
}

function renderLedger(trades) {
    const tbody = document.getElementById('ledger-rows');
    const foot = document.getElementById('table-foot');
    const label = document.getElementById('row-count');
    let shown = 0;

    const draw = (limit) => {
        for (const t of trades.slice(shown, limit)) {
            const pnl = dollars(t);
            const meta = OUTCOMES[t.outcome] || { short: t.outcome, css: 'out-miss' };
            const tr = tbody.insertRow();
            cell(tr, timeLabel(t.timestamp), 't');
            cell(tr, t.pair_id, 'mkt');
            cell(tr, String(t.strategy).replace('Kalshi', 'K'), 'leg');
            cell(tr, num(t, 'k_price').toFixed(0) + '¢', 'num');
            cell(tr, num(t, 'p_price').toFixed(0) + '¢', 'num');
            cell(tr, count(num(t, 'intended_qty')), 'num');
            cell(tr, `${count(num(t, 'k_fill_qty'))} / ${count(num(t, 'p_fill_qty'))}`, 'num');
            cell(tr, meta.short, meta.css);
            cell(tr, pnl === 0 ? '—' : usd(pnl), 'num ' + (pnl < 0 ? 'loss' : pnl > 0 ? 'gain' : ''));
        }
        shown = Math.min(limit, trades.length);
        label.textContent = shown < trades.length
            ? `${count(shown)} most recent of ${count(trades.length)}`
            : `${count(trades.length)} rows, newest first`;
        foot.hidden = shown >= trades.length;
    };

    draw(INITIAL_ROWS);
    document.getElementById('show-all').addEventListener('click', () => draw(trades.length));
}

load().catch((err) => {
    document.getElementById('intro-line').textContent =
        'Could not load data.json. If you opened this file directly, serve the folder over HTTP instead: python dashboard/server.py';
    console.error(err);
});
