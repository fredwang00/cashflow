import math
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from cashflow.cli import cli
from cashflow.db import store_transactions
from cashflow.models import ParsedTransaction
from cashflow.parsers.chase import parse_chase_csv
from cashflow.parsers.robinhood import parse_robinhood_csv
from cashflow.parsers.amex import parse_amex_csv
from cashflow.parsers.citi import parse_citi
from cashflow.parsers.bofa_checking import parse_bofa_checking_csv
from cashflow.seed import seed_all

FIXTURES = Path(__file__).parent / 'fixtures'


def test_chase_refund_reduces_spending_but_payment_does_not(tmp_path):
    path = tmp_path / 'chase.csv'
    path.write_text('Transaction Date,Description,Type,Amount\n'
                    '09/01/2026,SHOP,Sale,-100\n'
                    '09/02/2026,SHOP,Return,25\n'
                    '09/03/2026,PAYMENT THANK YOU,Payment,75\n')
    assert [t.amount for t in parse_chase_csv(path)] == [100, -25]


def test_robinhood_refund_is_not_a_payment_or_rewards_redemption(tmp_path):
    path = tmp_path / 'robinhood.csv'
    path.write_text('Date,Time,Cardholder,Amount,Points,Balance,Status,Type,Merchant,Description\n'
                    '2026-09-01,12:00 PM,Fei Wang,100,0,,Posted,Purchase,SHOP,\n'
                    '2026-09-02,12:00 PM,Fei Wang,-25,0,,Posted,Refund,SHOP,\n'
                    '2026-09-03,12:00 PM,Fei Wang,-75,0,,Posted,Payment,Payment,\n'
                    '2026-09-04,12:00 PM,Fei Wang,-5,0,,Posted,Other,Points Redeemed,POINTS REDEEMED\n')
    assert [t.amount for t in parse_robinhood_csv(path)] == [100, -25]


def test_amex_excludes_payment_but_keeps_merchant_refund(tmp_path):
    path = tmp_path / 'amex.csv'
    path.write_text('Date,Description,Card Member,Amount,Reference\n'
                    '09/01/2026,SHOP,FEI WANG,100,1\n'
                    '09/02/2026,SHOP,FEI WANG,-25,2\n'
                    '09/03/2026,ONLINE PAYMENT - THANK YOU,FEI WANG,-75,3\n')
    assert [t.amount for t in parse_amex_csv(path)] == [100, -25]


def test_citi_keeps_merchant_refund(tmp_path):
    path = tmp_path / 'citi.txt'
    path.write_text('Sep 1, 2026\nFEI WANG\nSHOP\n$100.00\n'
                    'Sep 2, 2026\nFEI WANG\nSHOP\n-$25.00\n'
                    'Sep 3, 2026\nFEI WANG\nAUTOPAY PAYMENT\n-$75.00\nEnd of Activity\n')
    assert [t.amount for t in parse_citi(path)] == [100, -25]


def test_checking_does_not_discard_paper_check_expenses(tmp_path):
    path = tmp_path / 'stmt.csv'
    path.write_text('Date,Description,Amount,Running Bal.\n09/01/2026,Check 1234,-100.00,200.00\n')
    expenses, _ = parse_bofa_checking_csv(path)
    assert [t.amount for t in expenses] == [100]


def test_checking_wrong_header_is_an_error(tmp_path):
    from cashflow.errors import ParseError
    path = tmp_path / 'bofa.csv'
    path.write_text('Posted Date,Payee,Amount\n09/01/2026,SHOP,-100\n')
    with pytest.raises(ParseError):
        parse_bofa_checking_csv(path)


@pytest.mark.parametrize(('fixture', 'filename', 'account'), [
    ('bofa_cc_sample.csv', 'bofa-credit.csv', 'Bank of America'),
    ('amex_sample.csv', 'amex_2026.csv', 'Amex Gold'),
    ('target_sample.csv', 'target.csv', 'Target Card'),
    ('chase_sample.csv', 'download.csv', 'Chase Prime Visa'),
])
def test_ingest_uses_csv_content_not_filename(tmp_path, monkeypatch, fixture, filename, account):
    monkeypatch.delenv('CASHFLOW_LLM_URL', raising=False)
    path = tmp_path / filename
    path.write_bytes((FIXTURES / fixture).read_bytes())
    dbpath = tmp_path / 'db.sqlite'
    result = CliRunner().invoke(cli, ['--db', str(dbpath), 'ingest', '--files', str(path)])
    assert result.exit_code == 0, result.output
    with sqlite3.connect(dbpath) as conn:
        rows = conn.execute('SELECT DISTINCT a.name FROM transactions t JOIN accounts a ON a.id=t.account_id').fetchall()
    assert rows == [(account,)]


def test_successful_duplicate_import_updates_import_history(tmp_path, monkeypatch):
    monkeypatch.delenv('CASHFLOW_LLM_URL', raising=False)
    dbpath = tmp_path / 'db.sqlite'
    args = ['--db', str(dbpath), 'ingest', '--files', str(FIXTURES/'chase_sample.csv')]
    runner = CliRunner()
    assert runner.invoke(cli, args).exit_code == 0
    assert runner.invoke(cli, args).exit_code == 0
    with sqlite3.connect(dbpath) as conn:
        assert conn.execute('SELECT COUNT(*) FROM ingest_state WHERE last_sync IS NOT NULL').fetchone()[0] >= 1


def test_store_transactions_does_not_hide_constraint_failures(db):
    seed_all(db)
    txn = ParsedTransaction(date(2026,9,1), 10, 'Shop', 'Shop', 'invalid', 'invalid-source', 'Checking')
    with pytest.raises(sqlite3.IntegrityError):
        store_transactions(db, [txn])


@pytest.mark.parametrize('amount', [math.nan, math.inf, -math.inf])
def test_store_rejects_nonfinite_amounts(db, amount):
    seed_all(db)
    txn = ParsedTransaction(date(2026,9,1), amount, 'Shop', 'Shop', 'nonfinite', 'csv', 'Checking')
    with pytest.raises(ValueError):
        store_transactions(db, [txn])
    assert db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 0


def test_invalid_batch_does_not_leave_partial_import(db):
    seed_all(db)
    txn = ParsedTransaction(date(2026,9,1), 10, 'Shop', 'Shop', 'valid', 'csv', 'Checking')
    with pytest.raises(sqlite3.IntegrityError):
        store_transactions(db, [txn, replace(txn, source_id='invalid', who='invalid')])
    assert db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 0


def test_rule_set_treats_wildcards_as_literal_text(tmp_path):
    dbpath = tmp_path / 'db.sqlite'
    runner = CliRunner()
    runner.invoke(cli, ['--db', str(dbpath), 'status'])
    with sqlite3.connect(dbpath) as conn:
        acct = conn.execute('SELECT id FROM accounts LIMIT 1').fetchone()[0]
        for ident, merchant in [('one', 'A_B'), ('two', 'ACB')]:
            conn.execute("INSERT INTO transactions(source_id,date,amount,description,merchant,account_id,source_type) VALUES (?, '2026-09-01', 10, ?, ?, ?, 'csv')", (ident,merchant,merchant,acct))
    result = runner.invoke(cli, ['--db', str(dbpath), 'rule', 'set', 'A_B', 'Groceries'])
    assert result.exit_code == 0
    with sqlite3.connect(dbpath) as conn:
        assert conn.execute("SELECT status FROM transactions WHERE merchant='ACB'").fetchone()[0] == 'pending'
        assert conn.execute("SELECT status FROM transactions WHERE merchant='A_B'").fetchone()[0] == 'confirmed'


def test_empty_rule_is_rejected(tmp_path):
    result = CliRunner().invoke(cli, ['--db', str(tmp_path/'db.sqlite'), 'rule', 'set', '', 'Groceries'])
    assert result.exit_code != 0


def test_fees_does_not_project_interest_late_fees_or_cashback_as_annual(tmp_path):
    dbpath = tmp_path / 'db.sqlite'
    runner = CliRunner()
    runner.invoke(cli, ['--db', str(dbpath), 'status'])
    with sqlite3.connect(dbpath) as conn:
        acct = conn.execute('SELECT id FROM accounts LIMIT 1').fetchone()[0]
        cat = conn.execute("SELECT id FROM categories WHERE name='Credit Card Fees'").fetchone()[0]
        for ident, merchant, amount in [('annual', 'ANNUAL FEE', 95), ('late', 'Late Fee', 29), ('interest','Interest Charge',94.87), ('cashback','CASHBACK',-5.32), ('metal','Metal Card',40)]:
            conn.execute("INSERT INTO transactions(source_id,date,amount,description,merchant,account_id,category_id,source_type) VALUES (?, '2024-02-29', ?, ?, ?, ?, ?, 'csv')", (ident,amount,merchant,merchant,acct,cat))
    result = runner.invoke(cli, ['--db', str(dbpath), 'fees'])
    assert result.exit_code == 0, result.output
    assert '2025-02-28' in result.output
    assert '$95.00/year' in result.output
    assert 'Interest Charge' not in result.output
    assert 'Late Fee' not in result.output


def test_import_identity_collision_fails_instead_of_losing_different_charge(db):
    seed_all(db)
    txn = ParsedTransaction(date(2026,9,1), 10, 'Shop', 'Shop', 'collision', 'csv', 'Checking')
    store_transactions(db, [txn])
    with pytest.raises(ValueError, match='source'):
        store_transactions(db, [replace(txn, amount=20)])
    assert db.execute('SELECT amount FROM transactions').fetchone()[0] == 10


def test_auto_ingests_default_inbox(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.delenv('CASHFLOW_LLM_URL', raising=False)
    inbox = tmp_path/'cashflow'/'inbox'
    inbox.mkdir(parents=True)
    (inbox/'download.csv').write_bytes((FIXTURES/'chase_sample.csv').read_bytes())
    dbpath = tmp_path/'db.sqlite'
    result = CliRunner().invoke(cli, ['--db', str(dbpath), 'ingest', '--auto'])
    assert result.exit_code == 0, result.output
    with sqlite3.connect(dbpath) as conn:
        assert conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 6


def test_robinhood_pending_authorization_not_counted_as_final_spending(tmp_path):
    path = tmp_path/'robinhood.csv'
    path.write_text('Date,Time,Cardholder,Amount,Points,Balance,Status,Type,Merchant,Description\n'
                    '2026-09-01,12:00 PM,Fei Wang,100,0,,Pending,Purchase,SHOP,\n'
                    '2026-09-01,12:00 PM,Fei Wang,120,0,,Posted,Purchase,SHOP,\n')
    assert [t.amount for t in parse_robinhood_csv(path)] == [120]


def test_import_timestamp_is_unambiguous_utc(tmp_path, monkeypatch):
    from datetime import datetime
    monkeypatch.delenv('CASHFLOW_LLM_URL', raising=False)
    dbpath = tmp_path/'db.sqlite'
    result = CliRunner().invoke(cli, ['--db', str(dbpath), 'ingest', '--files', str(FIXTURES/'chase_sample.csv')])
    assert result.exit_code == 0
    with sqlite3.connect(dbpath) as conn:
        timestamp = conn.execute('SELECT last_sync FROM ingest_state LIMIT 1').fetchone()[0]
    assert datetime.fromisoformat(timestamp).utcoffset() is not None


def test_nonfinite_reimbursement_never_changes_ledger(tmp_path):
    dbpath = tmp_path/'db.sqlite'
    runner = CliRunner()
    runner.invoke(cli, ['--db', str(dbpath), 'status'])
    with sqlite3.connect(dbpath) as conn:
        acct = conn.execute('SELECT id FROM accounts LIMIT 1').fetchone()[0]
        conn.execute("INSERT INTO transactions(source_id,date,amount,description,merchant,account_id,source_type) VALUES ('finite', '2026-09-01', 10, 'Shop', 'Shop', ?, 'csv')", (acct,))
    result = runner.invoke(cli, ['--db', str(dbpath), 'reimburse', '1', 'nan'])
    assert result.exit_code != 0
    with sqlite3.connect(dbpath) as conn:
        assert conn.execute('SELECT reimbursed_amount FROM transactions').fetchone()[0] == 0


def test_chase_freedom_import_stays_separate_from_prime(tmp_path, monkeypatch):
    monkeypatch.delenv('CASHFLOW_LLM_URL', raising=False)
    dbpath = tmp_path/'db.sqlite'
    runner = CliRunner()
    for name in ('chase-prime.csv','chase-freedom.csv'):
        path=tmp_path/name
        path.write_bytes((FIXTURES/'chase_sample.csv').read_bytes())
        result=runner.invoke(cli,['--db',str(dbpath),'ingest','--files',str(path)])
        assert result.exit_code == 0, result.output
    with sqlite3.connect(dbpath) as conn:
        rows=conn.execute('SELECT a.name,COUNT(*) FROM transactions t JOIN accounts a ON a.id=t.account_id GROUP BY a.name ORDER BY a.name').fetchall()
    assert rows == [('Chase Freedom',6),('Chase Prime Visa',6)]


def test_robinhood_cardholder_case_preserves_identity_and_attribution(tmp_path):
    path=tmp_path/'robinhood.csv'
    text=(FIXTURES/'robinhood_sample.csv').read_text()
    path.write_text(text)
    old=parse_robinhood_csv(path)
    path.write_text(text.replace('Fei Wang','fei wang').replace('Wendy Rizzo','wendy rizzo'))
    new=parse_robinhood_csv(path)
    assert [(t.source_id,t.who) for t in new] == [(t.source_id,t.who) for t in old]


@pytest.mark.parametrize('parser,fixture', [(parse_chase_csv,'chase_sample.csv'),(parse_robinhood_csv,'robinhood_sample.csv')])
def test_same_export_repeated_purchases_are_not_silently_lost(tmp_path,parser,fixture):
    import csv,io
    rows=list(csv.reader(io.StringIO((FIXTURES/fixture).read_text())))
    row=rows[1] if parser is parse_chase_csv else rows[3]
    path=tmp_path/'export.csv'
    with path.open('w',newline='') as f:
        csv.writer(f).writerows([rows[0],row,row])
    txns=parser(path)
    assert len(txns)==2
    assert len({t.source_id for t in txns})==2
    assert [t.source_id for t in parser(path)] == [t.source_id for t in txns]
