import sqlite3
from datetime import date
from fastapi.testclient import TestClient
from cashflow.server import create_app
from cashflow.db import create_schema, store_transactions, store_income
from cashflow.seed import seed_all
from cashflow.models import ParsedTransaction


def _make_app(db_path):
    return create_app(str(db_path))


def _seed_and_populate(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    seed_all(conn)
    txns = [
        ParsedTransaction(date=date(2026, 3, 1), amount=1500.0, description="KROGER", merchant="Kroger", source_id="test-1", source_type="csv", account_name="Bank of America"),
        ParsedTransaction(date=date(2026, 3, 5), amount=3450.37, description="NEWREZ MORTGAGE", merchant="Newrez Mortgage", source_id="test-2", source_type="csv", account_name="Checking"),
        ParsedTransaction(date=date(2026, 3, 10), amount=200.0, description="TARGET", merchant="Target", source_id="test-3", source_type="csv", account_name="Target Card"),
        ParsedTransaction(date=date(2026, 2, 15), amount=800.0, description="KROGER", merchant="Kroger", source_id="test-4", source_type="csv", account_name="Bank of America"),
    ]
    store_transactions(conn, txns)
    conn.execute("UPDATE transactions SET status = 'confirmed', category_id = (SELECT id FROM categories WHERE name = 'Groceries') WHERE source_id = 'test-1'")
    conn.execute("UPDATE transactions SET status = 'confirmed', category_id = (SELECT id FROM categories WHERE name = 'Mortgage') WHERE source_id = 'test-2'")
    conn.commit()
    store_income(conn, [
        {"date": date(2026, 1, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "inc-1"},
        {"date": date(2026, 2, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "inc-2"},
        {"date": date(2026, 3, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "inc-3"},
    ])
    conn.close()


def test_status_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "month_spending" in data
    assert "ceiling" in data
    assert "ytd_surplus" in data
    assert "review_queue" in data


def test_monthly_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/monthly/2026/3")
    assert resp.status_code == 200
    data = resp.json()
    assert "transactions" in data
    assert "by_category" in data
    assert "total" in data


def test_transactions_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/transactions?year=2026&month=3")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_yearly_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/yearly/2026")
    assert resp.status_code == 200
    data = resp.json()
    assert "months" in data
    assert "ytd_income" in data
    assert "ytd_spending" in data
    assert "ytd_surplus" in data


def test_yearly_baseline_excludes_reimbursed(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)

    # Flag one transaction as reimbursed
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE transactions SET is_reimbursed = 1 WHERE source_id = 'test-1'")
    conn.commit()
    conn.close()

    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/yearly/2026")
    data = resp.json()
    march = data["months"][2]  # March = index 2
    # Baseline should exclude the $1500 reimbursed Kroger transaction
    assert march["spending_baseline"] < march["spending"]


def test_toggle_reimbursed(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)

    resp = client.post("/api/transactions/1/toggle-reimbursed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_reimbursed"] is True

    # Toggle off
    resp = client.post("/api/transactions/1/toggle-reimbursed")
    data = resp.json()
    assert data["is_reimbursed"] is False


def test_monthly_includes_is_reimbursed(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE transactions SET is_reimbursed = 1 WHERE source_id = 'test-1'")
    conn.commit()
    conn.close()

    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/monthly/2026/3")
    data = resp.json()
    reimbursed_txns = [t for t in data["transactions"] if t.get("is_reimbursed")]
    assert len(reimbursed_txns) == 1


def test_index_serves_html(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_status_uses_net_spending_consistently(tmp_path, monkeypatch):
    class MarchDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 3, 20)

    monkeypatch.setattr('cashflow.server.date', MarchDate)
    db_path = tmp_path / 'test.db'
    _seed_and_populate(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE transactions SET reimbursed_amount = 1000 WHERE source_id = 'test-1'")
    client = TestClient(_make_app(db_path))
    status = client.get('/api/status').json()
    assert status['month_spending'] == 4150.37
    assert status['ytd_spending'] == 4950.37
    assert status['ytd_surplus'] == 17802.05
    assert status['month_spending'] == client.get('/api/monthly/2026/3').json()['total']


def test_yearly_baseline_includes_refunds(tmp_path):
    db_path = tmp_path / 'test.db'
    _seed_and_populate(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE transactions SET amount = -200 WHERE source_id = 'test-3'")
        conn.execute("UPDATE transactions SET is_one_off = 1 WHERE source_id = 'test-2'")
    march = TestClient(_make_app(db_path)).get('/api/yearly/2026').json()['months'][2]
    assert march['spending_baseline'] == 1300.0
    assert march['spending'] == march['spending_baseline'] + march['spending_oneoffs']


def _run_dashboard_script(script):
    """Run browser logic with DOM, network and Chart boundaries replaced."""
    import shutil
    import subprocess
    from pathlib import Path
    import pytest

    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for dashboard JavaScript regression tests')
    app_js = Path(__file__).parents[1] / 'src/cashflow/static/app.js'
    harness = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
function element() {
    return {
        children: [], style: {}, dataset: {}, className: '', textContent: '', events: {},
        classList: { contains() { return false; }, toggle() {} },
        get firstChild() { return this.children[0]; },
        appendChild(child) { this.children.push(child); },
        removeChild(child) { this.children.splice(this.children.indexOf(child), 1); },
        addEventListener(name, fn) { this.events[name] = fn; },
        querySelector() { return element(); }
    };
}
const elements = {};
global.document = {
    getElementById(id) { return elements[id] ||= element(); },
    querySelectorAll() { return []; }, createElement: element, createTextNode: element
};
global.Chart = function(canvas, config) { this.data = config.data; this.update = () => {}; };
global.fetch = () => new Promise(() => {});
global.prompt = () => null;
global.alert = () => {};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
'''
    result = subprocess.run(
        [node, '-e', harness + '\n(async () => {\n' + script + '\n})().catch(e => { console.error(e); process.exitCode = 1; });', str(app_js)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_dashboard_zero_baseline_is_not_replaced_by_total():
    _run_dashboard_script('''
        currentYear = 2020; trendView = 'baseline';
        renderTrendChart({months: [{month: 1, spending: 100, spending_baseline: 0, income: 300, surplus: 200}]});
        assert.deepEqual(trendChart.data.datasets[0].data, [0]);
        assert.deepEqual(trendChart.data.datasets[2].data, [300]);
    ''')


def test_dashboard_cancel_oneoff_does_not_write():
    _run_dashboard_script('''
        let writes = 0;
        fetch = async () => { writes++; return {ok: true, json: async () => ({is_one_off: true})}; };
        renderTxRows([{id: 1, amount: 100}]);
        const button = elements['tx-body'].children[0].children[5].children[0];
        await button.events.click.call(button);
        assert.equal(writes, 0);
    ''')


def test_dashboard_reimbursement_refreshes_amounts_and_charts():
    _run_dashboard_script('''
        currentYear = 2020; currentMonth = 1;
        const transaction = {id: 1, date: '2020-01-01', amount: 100, reimbursed_amount: 0};
        const months = Array.from({length: 12}, (_, i) => ({month: i + 1, spending: 0, income: 300, surplus: 300}));
        fetch = async (url) => ({ok: true, json: async () => {
            if (url.includes('toggle-reimbursed')) return {id: 1, is_reimbursed: true, reimbursed_amount: 100};
            if (url.includes('monthly')) return {total: 0, transactions: [{...transaction, reimbursed_amount: 100, is_reimbursed: true}], by_category: []};
            return {months};
        }});
        renderTxRows([transaction]);
        const button = elements['tx-body'].children[0].children[6].children[0];
        await button.events.click.call(button);
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(elements['tx-body'].children[0].children[2].textContent, '$0.00');
        assert.equal(elements['burn-amount'].textContent, '$0.00');
        assert.equal(trendChart.data.datasets[0].data[0], 0);
    ''')


def test_dashboard_ignores_stale_month_responses():
    _run_dashboard_script('''
        const pending = [];
        fetch = (url) => new Promise(resolve => pending.push({url, resolve}));
        currentYear = 2020; currentMonth = 1;
        const first = loadMonth();
        currentMonth = 2;
        const second = loadMonth();
        const months = Array.from({length: 12}, (_, i) => ({month: i + 1, spending: 0, income: 0, surplus: 0}));
        pending[2].resolve({ok: true, json: async () => ({total: 200, transactions: [], by_category: []})});
        pending[3].resolve({ok: true, json: async () => ({months})});
        await second;
        pending[0].resolve({ok: true, json: async () => ({total: 100, transactions: [], by_category: []})});
        pending[1].resolve({ok: true, json: async () => ({months})});
        await first;
        assert.equal(elements['burn-amount'].textContent, '$200.00');
    ''')


def test_transactions_default_to_current_year(tmp_path, monkeypatch):
    class FutureDate(date):
        @classmethod
        def today(cls):
            return cls(2027, 3, 20)

    monkeypatch.setattr('cashflow.server.date', FutureDate)
    db_path = tmp_path / 'test.db'
    _seed_and_populate(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE transactions SET date = '2027-03-01' WHERE source_id = 'test-1'")
    data = TestClient(_make_app(db_path)).get('/api/transactions').json()
    assert len(data) == 1
    assert data[0]['date'] == '2027-03-01'


def test_missing_transaction_toggles_return_not_found(tmp_path):
    db_path = tmp_path / 'test.db'
    _seed_and_populate(db_path)
    client = TestClient(_make_app(db_path))
    for action in ('toggle-oneoff', 'toggle-reimbursed'):
        assert client.post(f'/api/transactions/999/{action}').status_code == 404


def test_dashboard_displays_every_monthly_transaction():
    _run_dashboard_script('''
        renderTxRows(Array.from({length: 201}, (_, i) => ({id: i, amount: 100})));
        assert.equal(elements['tx-body'].children.length, 201);
    ''')


def test_dashboard_renders_transactions_when_chart_library_is_unavailable():
    _run_dashboard_script('''
        Chart = undefined;
        currentYear = 2020; currentMonth = 1;
        fetch = async (url) => ({ok: true, json: async () => {
            if (url.includes('monthly')) return {total: 100, transactions: [{id: 1, amount: 100}], by_category: [{category: 'Groceries', total: 100}]};
            return {months: Array.from({length: 12}, (_, i) => ({month: i + 1, spending: 100, income: 300, surplus: 200}))};
        }});
        await loadMonth();
        assert.equal(elements['burn-amount'].textContent, '$100.00');
        assert.equal(elements['tx-body'].children.length, 1);
        assert.equal(elements['tx-body'].children[0].children[2].textContent, '$100.00');
    ''')


def test_api_rejects_invalid_months(tmp_path):
    db_path = tmp_path / 'test.db'
    _seed_and_populate(db_path)
    client = TestClient(_make_app(db_path))
    for month in (0, 13):
        assert client.get(f'/api/monthly/2026/{month}').status_code == 422
        assert client.get(f'/api/transactions?year=2026&month={month}').status_code == 422
