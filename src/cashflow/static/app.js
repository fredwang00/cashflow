// ── State ──────────────────────────────────────────────────────────────────
let currentYear = new Date().getFullYear();
let currentMonth = new Date().getMonth() + 1;
let categoryChart = null;
let trendChart = null;
let sortCol = 'date';
let sortAsc = false;
let categoryFilter = 'all'; // 'all' | 'necessity' | 'want'
let allByCategory = [];

// ── Helpers ───────────────────────────────────────────────────────────────
function fmt(n) {
    const abs = Math.abs(n);
    const str = abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (n < 0 ? '-$' : '$') + str;
}

function monthName(m) {
    return new Date(2000, m - 1).toLocaleString('en-US', { month: 'long' });
}

function pctColor(pct) {
    if (pct > 95) return 'red';
    if (pct > 80) return 'yellow';
    return 'green';
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.textContent;
}

function badgeEl(who) {
    if (!who) return document.createTextNode('');
    const span = document.createElement('span');
    span.className = 'badge badge-' + escapeHtml(who);
    span.textContent = who;
    return span;
}

function timeAgo(isoStr) {
    if (!isoStr) return 'never';
    const diff = Date.now() - new Date(isoStr).getTime();
    const h = Math.floor(diff / 3600000);
    const d = Math.floor(h / 24);
    if (d > 1) return d + ' days ago';
    if (d === 1) return 'yesterday';
    if (h > 1) return h + ' hours ago';
    if (h === 1) return '1 hour ago';
    return 'just now';
}

// ── DOM refs ──────────────────────────────────────────────────────────────
const $monthLabel    = document.getElementById('month-label');
const $burnAmount    = document.getElementById('burn-amount');
const $burnBar       = document.getElementById('burn-bar');
const $burnDetail    = document.getElementById('burn-detail');
const $surplusAmt    = document.getElementById('surplus-amount');
const $surplusDetail = document.getElementById('surplus-detail');
const $reviewCount   = document.getElementById('review-count');
const $reviewDetail  = document.getElementById('review-detail');
const $txBody        = document.getElementById('tx-body');
const $freshness     = document.getElementById('freshness');

// ── API ───────────────────────────────────────────────────────────────────
async function fetchJson(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(url + ': ' + res.status);
    return res.json();
}

// ── Status state ──────────────────────────────────────────────────────────
let statusData = { ceiling: 12000, surplus_goal: 40000, review_queue: 0 };

function renderStatus(s) {
    statusData = s;
    renderBurnCard(s.month_spending, s.ceiling, s.days_left);
    renderSurplusCard(s.ytd_surplus, s.surplus_goal);

    const total = s.review_queue || 0;
    const uncat = s.review_uncategorized || 0;
    const lowConf = s.review_low_confidence || 0;
    $reviewCount.textContent = total;
    $reviewCount.className = 'big-number ' + (total > 0 ? 'color-yellow' : 'color-green');
    if (total === 0) {
        $reviewDetail.textContent = 'All clear';
    } else if (uncat > 0 && lowConf > 0) {
        $reviewDetail.textContent = uncat + ' uncategorized · ' + lowConf + ' low-confidence';
    } else if (uncat > 0) {
        $reviewDetail.textContent = uncat + ' need a category';
    } else {
        $reviewDetail.textContent = lowConf + ' low-confidence — run cashflow review';
    }

    if ($freshness) {
        $freshness.textContent = 'Last import: ' + timeAgo(s.last_import);
    }
}

function renderBurnCard(spending, ceiling, daysLeft) {
    const pct = ceiling > 0 ? (spending / ceiling) * 100 : 0;
    const color = pctColor(pct);
    $burnAmount.textContent = fmt(spending);
    $burnAmount.className = 'big-number color-' + color;
    $burnBar.style.width = Math.min(pct, 100) + '%';
    $burnBar.className = 'progress-bar-fill ' + color;
    var detail = Math.round(pct) + '% of ' + fmt(ceiling) + ' ceiling';
    if (daysLeft !== null) detail += ' · ' + daysLeft + ' days left';
    $burnDetail.textContent = detail;
}

function renderSurplusCard(surplus, goal) {
    const now = new Date();
    const isCurrentYear = (currentYear === now.getFullYear());
    const isCurrentOrPastMonth = !isCurrentYear || currentMonth <= now.getMonth() + 1;

    $surplusAmt.textContent = fmt(surplus);
    $surplusAmt.className = 'big-number ' + (surplus >= 0 ? 'color-green' : 'color-red');

    // Update card title to reflect the viewing context
    const $surplusCard = document.getElementById('surplus-card');
    if ($surplusCard) {
        const h2 = $surplusCard.querySelector('h2');
        if (h2) {
            h2.textContent = isCurrentYear ? 'YTD Surplus' : currentYear + ' Surplus';
        }
    }

    const monthsElapsed = currentMonth;
    const pace = (isCurrentYear && monthsElapsed > 0) ? (surplus / monthsElapsed) * 12 : null;
    $surplusDetail.textContent = 'Goal: ' + fmt(goal) + (pace !== null ? ' · On pace: ' + fmt(pace) : '');
}

// ── Render: Category Chart ────────────────────────────────────────────────
const CATEGORY_COLORS = [
    '#60a5fa', '#6ee7b7', '#fbbf24', '#f87171', '#c084fc',
    '#fb923c', '#38bdf8', '#a78bfa', '#f472b6', '#34d399',
    '#e879f9', '#facc15',
];

function applyFilterAndRender() {
    let filtered = allByCategory;
    if (categoryFilter === 'necessity') {
        filtered = allByCategory.filter(function(c) { return c.category_type === 'necessity'; });
    } else if (categoryFilter === 'want') {
        filtered = allByCategory.filter(function(c) { return c.category_type === 'want'; });
    }
    renderCategoryChart(filtered);

    // Update filter button active states
    document.querySelectorAll('.cat-filter-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.filter === categoryFilter);
    });
}

function renderCategoryChart(byCategory) {
    const sorted = [...byCategory].sort(function(a, b) { return b.total - a.total; });
    const labels = sorted.map(function(c) { return c.category || 'Uncategorized'; });
    const data = sorted.map(function(c) { return c.total; });
    const colors = labels.map(function(_, i) { return CATEGORY_COLORS[i % CATEGORY_COLORS.length]; });

    var wrap = document.getElementById('category-chart-wrap');
    var chartHeight = Math.max(200, sorted.length * 28 + 20);
    wrap.style.height = chartHeight + 'px';
    var canvas = document.getElementById('category-chart');

    if (categoryChart) {
        categoryChart.data.labels = labels;
        categoryChart.data.datasets[0].data = data;
        categoryChart.data.datasets[0].backgroundColor = colors;
        categoryChart.update();
    } else {
        categoryChart = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{ data: data, backgroundColor: colors, borderRadius: 4 }],
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: function(ctx) { return fmt(ctx.parsed.x); } } },
                },
                scales: {
                    x: {
                        ticks: { callback: function(v) { return fmt(v); }, color: '#94a3b8' },
                        grid: { color: '#334155' },
                    },
                    y: { ticks: { color: '#e2e8f0' }, grid: { display: false } },
                },
            },
        });
    }
}

// ── Render: Trend Chart ───────────────────────────────────────────────────
function renderTrendChart(yearly) {
    const now = new Date();
    const isCurrentYear = (currentYear === now.getFullYear());
    const currentM = isCurrentYear ? now.getMonth() + 1 : 12;

    // Only show months with data or up to current month
    const visibleMonths = yearly.months.filter(function(m) {
        return m.spending > 0 || m.income > 0 || m.month <= currentM;
    });

    const labels = visibleMonths.map(function(m) { return monthName(m.month).slice(0, 3); });
    const spending = visibleMonths.map(function(m, i) {
        // Future months: null (not zero) so Chart.js doesn't draw them
        const mo = visibleMonths[i].month;
        return (isCurrentYear && mo > currentM) ? null : m.spending;
    });
    const income = visibleMonths.map(function(m, i) {
        const mo = visibleMonths[i].month;
        return (isCurrentYear && mo > currentM) ? null : m.income;
    });
    const net = visibleMonths.map(function(m, i) {
        const mo = visibleMonths[i].month;
        return (isCurrentYear && mo > currentM) ? null : m.surplus;
    });

    if (trendChart) {
        trendChart.data.labels = labels;
        trendChart.data.datasets[0].data = spending;
        trendChart.data.datasets[1].data = income;
        trendChart.data.datasets[2].data = net;
        trendChart.update();
    } else {
        trendChart = new Chart(document.getElementById('trend-chart'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Spending',
                        data: spending,
                        borderColor: '#f87171',
                        backgroundColor: 'rgba(248,113,113,0.08)',
                        fill: false,
                        tension: 0.3,
                        pointRadius: 3,
                        spanGaps: false,
                    },
                    {
                        label: 'Income',
                        data: income,
                        borderColor: '#6ee7b7',
                        backgroundColor: 'rgba(110,231,183,0.08)',
                        fill: false,
                        tension: 0.3,
                        pointRadius: 3,
                        spanGaps: false,
                    },
                    {
                        label: 'Net',
                        data: net,
                        borderColor: '#60a5fa',
                        backgroundColor: 'rgba(96,165,250,0.08)',
                        fill: false,
                        tension: 0.3,
                        pointRadius: 3,
                        borderDash: [4, 3],
                        spanGaps: false,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { labels: { color: '#94a3b8' } },
                    tooltip: { callbacks: { label: function(ctx) { return ctx.dataset.label + ': ' + fmt(ctx.parsed.y); } } },
                },
                scales: {
                    x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                    y: { ticks: { callback: function(v) { return fmt(v); }, color: '#94a3b8' }, grid: { color: '#334155' } },
                },
            },
        });
    }
}

// ── Render: Transactions ──────────────────────────────────────────────────
var currentTransactions = [];

function renderTransactions(transactions) {
    currentTransactions = transactions;
    sortTransactions();
}

function sortTransactions() {
    var txs = currentTransactions.slice();
    txs.sort(function(a, b) {
        var va = a[sortCol], vb = b[sortCol];
        if (sortCol === 'amount') return sortAsc ? va - vb : vb - va;
        va = (va || '').toString().toLowerCase();
        vb = (vb || '').toString().toLowerCase();
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ? 1 : -1;
        return 0;
    });
    renderTxRows(txs);
}

function renderTxRows(txs) {
    while ($txBody.firstChild) $txBody.removeChild($txBody.firstChild);

    var rows = txs.slice(0, 200);
    for (var i = 0; i < rows.length; i++) {
        var tx = rows[i];
        var tr = document.createElement('tr');

        var tdDate = document.createElement('td');
        tdDate.textContent = tx.date;
        tr.appendChild(tdDate);

        var tdMerch = document.createElement('td');
        tdMerch.textContent = tx.merchant || tx.description || '';
        tr.appendChild(tdMerch);

        var tdAmt = document.createElement('td');
        tdAmt.className = 'amount' + (tx.amount < 0 ? ' negative' : '');
        tdAmt.textContent = fmt(tx.amount);
        tr.appendChild(tdAmt);

        var tdCat = document.createElement('td');
        if (!tx.category) {
            var span = document.createElement('span');
            span.className = 'badge badge-uncategorized';
            span.textContent = 'Uncategorized';
            tdCat.appendChild(span);
        } else {
            tdCat.textContent = tx.category;
        }
        tr.appendChild(tdCat);

        var tdWho = document.createElement('td');
        tdWho.appendChild(badgeEl(tx.who));
        tr.appendChild(tdWho);

        $txBody.appendChild(tr);
    }
}

// Table header sorting
document.querySelectorAll('#tx-table thead th').forEach(function(th) {
    th.addEventListener('click', function() {
        var col = th.dataset.col;
        if (sortCol === col) {
            sortAsc = !sortAsc;
        } else {
            sortCol = col;
            sortAsc = col === 'date' ? false : true;
        }
        document.querySelectorAll('#tx-table thead th').forEach(function(h) { h.removeAttribute('data-sort'); });
        th.setAttribute('data-sort', sortAsc ? 'asc' : 'desc');
        sortTransactions();
    });
});

// Category filter buttons
document.querySelectorAll('.cat-filter-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
        categoryFilter = btn.dataset.filter;
        applyFilterAndRender();
    });
});

// ── Navigation ────────────────────────────────────────────────────────────
function updateMonthLabel() {
    $monthLabel.textContent = monthName(currentMonth) + ' ' + currentYear;
}

document.getElementById('prev-month').addEventListener('click', function() {
    currentMonth--;
    if (currentMonth < 1) { currentMonth = 12; currentYear--; }
    loadMonth();
});

document.getElementById('next-month').addEventListener('click', function() {
    currentMonth++;
    if (currentMonth > 12) { currentMonth = 1; currentYear++; }
    loadMonth();
});

// ── Data Loading ──────────────────────────────────────────────────────────
async function loadMonth() {
    updateMonthLabel();

    var results = await Promise.all([
        fetchJson('/api/monthly/' + currentYear + '/' + currentMonth),
        fetchJson('/api/yearly/' + currentYear),
    ]);

    var monthly = results[0];
    var yearly = results[1];

    var now = new Date();
    var isCurrentMonth = (currentYear === now.getFullYear() && currentMonth === now.getMonth() + 1);
    var daysInMonth = new Date(currentYear, currentMonth, 0).getDate();
    var daysLeft = isCurrentMonth ? daysInMonth - now.getDate() : null;
    renderBurnCard(monthly.total, statusData.ceiling, daysLeft);

    var ytdSurplus = 0;
    for (var i = 0; i < currentMonth; i++) {
        ytdSurplus += yearly.months[i].surplus;
    }
    renderSurplusCard(ytdSurplus, statusData.surplus_goal);

    allByCategory = monthly.by_category || [];
    applyFilterAndRender();
    renderTransactions(monthly.transactions || []);
    renderTrendChart(yearly);
}

async function init() {
    updateMonthLabel();

    try {
        var results = await Promise.all([
            fetchJson('/api/status'),
            fetchJson('/api/monthly/' + currentYear + '/' + currentMonth),
            fetchJson('/api/yearly/' + currentYear),
        ]);

        renderStatus(results[0]);
        allByCategory = results[1].by_category || [];
        applyFilterAndRender();
        renderTransactions(results[1].transactions || []);
        renderTrendChart(results[2]);
    } catch (err) {
        console.error('Failed to load dashboard:', err);
    }
}

init();
