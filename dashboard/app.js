document.addEventListener('DOMContentLoaded', async () => {
    try {
        const response = await fetch('data.json');
        const trades = await response.json();
        
        if (!trades || trades.length === 0) {
            console.log("No trades found.");
            return;
        }

        processAndRenderData(trades);
    } catch (err) {
        console.error("Failed to load trade data:", err);
    }
});

function processAndRenderData(trades) {
    let totalPnL = 0;
    let totalTrades = trades.length;
    let successfulTrades = 0;
    let totalVolume = 0;

    // Sort by timestamp just in case
    trades.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

    const dailyPnL = {};
    const cumulativePnLData = [];
    let currentCumulative = 0;

    // Aggregate metrics
    trades.forEach(trade => {
        const pnl = parseFloat(trade.net_realized_pnl) / 100; // Assuming it was in hundredths of a cent, so divide by 100 to get dollars (if it's cents, wait: 1 contract = 100 cents = $1. Let's assume net_realized_pnl is in cents, so /100 to get USD. Actually, code says "hundredths of a cent", so 10000 = $1. Let's divide by 10000)
        
        // Let's divide by 100 to convert "hundredths of a cent" to "cents", then by 100 to get dollars. Total 10000.
        const pnlDollars = pnl / 100; 

        totalPnL += pnlDollars;
        totalVolume += parseInt(trade.intended_qty) || 0;

        if (trade.outcome === 'success') {
            successfulTrades++;
        } else if (trade.outcome === 'partial_unwind' && pnlDollars > 0) {
            successfulTrades++; // Count partials that made money as wins
        }

        // Daily aggregation for chart
        const date = trade.timestamp.split('T')[0];
        if (!dailyPnL[date]) {
            dailyPnL[date] = 0;
        }
        dailyPnL[date] += pnlDollars;
    });

    // Compute cumulative data for chart
    for (const [date, dailyValue] of Object.entries(dailyPnL)) {
        currentCumulative += dailyValue;
        cumulativePnLData.push({ x: date, y: currentCumulative });
    }

    // Update UI Metrics
    const formatCurrency = (val) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
    
    const pnlEl = document.getElementById('total-pnl');
    pnlEl.textContent = formatCurrency(totalPnL);
    if (totalPnL < 0) {
        pnlEl.classList.remove('positive');
        pnlEl.classList.add('negative');
    }

    document.getElementById('win-rate').textContent = `${((successfulTrades / totalTrades) * 100).toFixed(1)}%`;
    document.getElementById('total-trades').textContent = new Intl.NumberFormat('en-US').format(totalTrades);
    document.getElementById('total-volume').textContent = new Intl.NumberFormat('en-US').format(totalVolume);

    // Render Chart
    renderChart(cumulativePnLData);

    // Render Table (all trades)
    renderTable(trades.reverse());
}

function renderChart(data) {
    const ctx = document.getElementById('pnlChart').getContext('2d');
    
    // Gradient fill
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.5)');
    gradient.addColorStop(1, 'rgba(59, 130, 246, 0.0)');

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.map(d => d.x),
            datasets: [{
                label: 'Cumulative PnL ($)',
                data: data.map(d => d.y),
                borderColor: '#3b82f6',
                backgroundColor: gradient,
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 6,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: 'rgba(15, 17, 21, 0.9)',
                    titleColor: '#94a3b8',
                    bodyColor: '#e2e8f0',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1
                }
            },
            scales: {
                x: {
                    grid: { display: false, drawBorder: false },
                    ticks: { color: '#94a3b8', maxTicksLimit: 10 }
                },
                y: {
                    grid: { color: 'rgba(255,255,255,0.05)', drawBorder: false },
                    ticks: {
                        color: '#94a3b8',
                        callback: (value) => '$' + value
                    }
                }
            },
            interaction: {
                mode: 'nearest',
                axis: 'x',
                intersect: false
            }
        }
    });
}

function renderTable(trades) {
    const tbody = document.getElementById('trades-tbody');
    tbody.innerHTML = '';

    trades.forEach(trade => {
        const tr = document.createElement('tr');
        
        // Format timestamp
        const timeObj = new Date(trade.timestamp);
        const timeStr = timeObj.toLocaleString([], { month: 'short', day: '2-digit', hour: '2-digit', minute:'2-digit', second:'2-digit' });
        
        // Outcome Badge
        let badgeClass = 'success';
        let outcomeText = 'Success';
        if (trade.outcome === 'failed_no_fill' || trade.outcome === 'leg_failed_unwind') {
            badgeClass = 'failed';
            outcomeText = 'Failed';
        } else if (trade.outcome === 'partial_unwind') {
            badgeClass = 'partial';
            outcomeText = 'Partial';
        }

        // PnL
        const pnl = (parseFloat(trade.net_realized_pnl) / 10000).toFixed(2);
        const pnlClass = pnl >= 0 ? 'text-positive' : 'text-negative';
        const pnlText = pnl >= 0 ? `+$${pnl}` : `-$${Math.abs(pnl)}`;

        tr.innerHTML = `
            <td>${timeStr}</td>
            <td style="font-weight: 600;">${trade.pair_id}</td>
            <td style="color: #94a3b8;">${trade.strategy}</td>
            <td>${trade.intended_qty}</td>
            <td><span class="badge ${badgeClass}">${outcomeText}</span></td>
            <td class="${pnlClass}">${pnlText}</td>
        `;
        tbody.appendChild(tr);
    });
}
