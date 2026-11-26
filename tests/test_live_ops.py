"""Operations: reconciliation, ledger migration, alerts, heartbeat, weekly report, market-hours guard."""

import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

from live.engine.daily import market_is_open
from live.ledger.db import Ledger
from live.notify import Notifier, ping_heartbeat, summarize_run
from live.reconcile import reconcile
from live.report import build_report
from tests.live_helpers import make, replay, session

DAY, NEXT = pd.Timestamp("2021-06-01"), pd.Timestamp("2021-06-02")


class Reconcile(unittest.TestCase):
    def test_fills_recorded_and_positions_match(self):
        engine, broker, ledger = make()
        session(broker, DAY)
        engine.run(DAY)
        session(broker, NEXT)                         # orders fill at the next open
        self.assertEqual(reconcile(ledger, broker, str(NEXT.date())), [])
        statuses = {o["broker_status"] for o in ledger.orders_for(str(DAY.date()))}
        self.assertEqual(statuses, {"filled"})
        self.assertEqual(ledger.unreconciled_orders(), [])

    def test_mismatch_is_reported(self):
        engine, broker, ledger = make()
        session(broker, DAY)
        engine.run(DAY)
        session(broker, NEXT)
        broker.holdings["AAPL"] += 1.0                # someone traded outside the system
        problems = reconcile(ledger, broker, str(NEXT.date()))
        self.assertEqual(len(problems), 1)
        self.assertIn("AAPL", problems[0])
        self.assertTrue(any(e["kind"] == "reconcile_mismatch" for e in ledger.events()))

    def test_long_replay_stays_reconciled(self):
        engine, broker, ledger = make(strategy="momentum_12_1")
        from tests.live_helpers import panel
        for d in panel()["close"].loc["2021-01-04":"2021-06-30"].index:
            session(broker, d)
            self.assertEqual(reconcile(ledger, broker, str(d.date())), [], str(d.date()))
            engine.run(d)


class Migration(unittest.TestCase):
    def test_old_database_gets_new_columns(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE orders (client_order_id TEXT PRIMARY KEY, run_date TEXT NOT NULL, "
                        "ticker TEXT NOT NULL, side TEXT NOT NULL, notional REAL, qty REAL, "
                        "status TEXT NOT NULL, broker_order_id TEXT, updated_utc TEXT)")
            con.commit()
            con.close()
            L = Ledger(path)
            cols = {r[1] for r in L.db.execute("PRAGMA table_info(orders)")}
            self.assertTrue({"broker_status", "filled_qty", "filled_price"} <= cols)
            L.close()


class Alerts(unittest.TestCase):
    def test_disabled_without_token_sends_nothing(self):
        with mock.patch("requests.post") as post:
            self.assertFalse(Notifier(token="", chat_id="").send("hello"))
            post.assert_not_called()

    def test_telegram_message(self):
        with mock.patch("requests.post", return_value=SimpleNamespace(ok=True)) as post:
            self.assertTrue(Notifier(token="T", chat_id="42").send("hi"))
            url = post.call_args.args[0]
            self.assertEqual(url, "https://api.telegram.org/botT/sendMessage")
            self.assertEqual(post.call_args.kwargs["json"], {"chat_id": "42", "text": "hi"})

    def test_alert_failure_never_raises(self):
        with mock.patch("requests.post", side_effect=OSError("no network")):
            self.assertFalse(Notifier(token="T", chat_id="42").send("hi"))

    def test_heartbeat_urls(self):
        with mock.patch("requests.get", return_value=SimpleNamespace(ok=True)) as get:
            ping_heartbeat(True, url="https://hc-ping.com/abc")
            ping_heartbeat(False, url="https://hc-ping.com/abc")
            urls = [c.args[0] for c in get.call_args_list]
            self.assertEqual(urls, ["https://hc-ping.com/abc", "https://hc-ping.com/abc/fail"])
        self.assertFalse(ping_heartbeat(True, url=""))

    def test_routine_run_needs_no_alert(self):
        ok = SimpleNamespace(run_date="2021-06-01", status="completed", message="rebalanced")
        self.assertIsNone(summarize_run(ok, [], []))
        bad = SimpleNamespace(run_date="2021-06-01", status="failed", message="no trade: stale data")
        text = summarize_run(bad, [{"level": "error", "kind": "stale_data", "message": "x"}], [])
        self.assertIn("FAILED", text)


class Report(unittest.TestCase):
    def test_weekly_report_renders(self):
        engine, broker, ledger = make(strategy="three_way")
        replay(engine, broker, "2021-06-01", "2021-06-11")
        reconcile(ledger, broker, "2021-06-11")
        text = build_report(ledger, broker, pd.Timestamp("2021-06-11"))
        for s in ("Weekly report", "Equity", "Positions:", "AAPL", "Orders this week", "Risk state"):
            self.assertIn(s, text)


class MarketHours(unittest.TestCase):
    def test_market_hours(self):
        ny = ZoneInfo("America/New_York")
        self.assertTrue(market_is_open(datetime(2026, 11, 24, 11, 0, tzinfo=ny)))
        self.assertFalse(market_is_open(datetime(2026, 11, 24, 16, 45, tzinfo=ny)))   # scheduled run time
        self.assertFalse(market_is_open(datetime(2026, 11, 26, 11, 0, tzinfo=ny)))    # Thanksgiving


if __name__ == "__main__":
    unittest.main()
