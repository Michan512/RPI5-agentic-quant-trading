"""
SQLite ledger: the live system's memory and audit trail (and, later, the tax record).

Tables
  runs        one row per trading day the engine ran (unique run_date) + status
  targets     strategy target weights recorded on each run
  orders      every order planned/submitted; PRIMARY KEY client_order_id
  equity      account value after each run
  cash_flows  deposits (+) and withdrawals (-), for the hard-stop maths
  state       key/value: flags (disabled, paused, rollbacks) and the auto-promotion entry
  events      halts, alerts and errors
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_date TEXT PRIMARY KEY,
    status TEXT NOT NULL,               -- started | completed | failed | skipped
    started_utc TEXT, finished_utc TEXT,
    transition_pending INTEGER DEFAULT 0,  -- turnover cap left the target unreached
    note TEXT
);
CREATE TABLE IF NOT EXISTS targets (
    run_date TEXT, strategy TEXT, ticker TEXT, weight REAL,
    PRIMARY KEY (run_date, strategy, ticker)
);
CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,
    run_date TEXT NOT NULL, ticker TEXT NOT NULL, side TEXT NOT NULL,
    notional REAL, qty REAL,
    status TEXT NOT NULL,               -- planned | submitted | failed
    broker_order_id TEXT, updated_utc TEXT,
    broker_status TEXT,                 -- filled | rejected | expired | ... (from reconcile)
    filled_qty REAL, filled_price REAL
);
CREATE TABLE IF NOT EXISTS shadow_targets (   -- paper-comparison books: recorded, never traded
    run_date TEXT, strategy TEXT, ticker TEXT, weight REAL,
    PRIMARY KEY (run_date, strategy, ticker)
);
CREATE TABLE IF NOT EXISTS equity (run_date TEXT PRIMARY KEY, equity REAL, cash REAL);
CREATE TABLE IF NOT EXISTS cash_flows (flow_date TEXT, amount REAL, kind TEXT);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (
    ts_utc TEXT, run_date TEXT, level TEXT, kind TEXT, message TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: Path | str = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a database was created."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(orders)")}
        for name, kind in (("broker_status", "TEXT"), ("filled_qty", "REAL"), ("filled_price", "REAL")):
            if name not in cols:
                self.db.execute(f"ALTER TABLE orders ADD COLUMN {name} {kind}")

    def close(self) -> None:
        self.db.close()

    def __del__(self):
        try:
            self.db.close()
        except Exception:
            pass

    # ---- runs ---------------------------------------------------------------
    def get_run(self, run_date: str) -> dict | None:
        r = self.db.execute("SELECT * FROM runs WHERE run_date=?", (run_date,)).fetchone()
        return dict(r) if r else None

    def start_run(self, run_date: str) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO runs(run_date, status, started_utc) VALUES (?,?,?)",
                            (run_date, "started", _now()))
            self.db.execute("UPDATE runs SET status='started' WHERE run_date=? AND status!='completed'",
                            (run_date,))

    def finish_run(self, run_date: str, status: str, note: str = "") -> None:
        with self.db:
            self.db.execute("UPDATE runs SET status=?, finished_utc=?, note=? WHERE run_date=?",
                            (status, _now(), note, run_date))

    def last_completed_run(self, before: str | None = None) -> dict | None:
        q = "SELECT * FROM runs WHERE status='completed'"
        args: tuple = ()
        if before:
            q += " AND run_date < ?"
            args = (before,)
        r = self.db.execute(q + " ORDER BY run_date DESC LIMIT 1", args).fetchone()
        return dict(r) if r else None

    # ---- plan: targets + orders, saved atomically before anything is sent ----
    def save_plan(self, run_date: str, targets: dict[str, dict[str, float]],
                  orders: list[dict], transition_pending: bool) -> None:
        with self.db:
            for strategy, weights in targets.items():
                self.db.execute("DELETE FROM targets WHERE run_date=? AND strategy=?", (run_date, strategy))
                self.db.executemany(
                    "INSERT INTO targets VALUES (?,?,?,?)",
                    [(run_date, strategy, t, float(w)) for t, w in weights.items()] or
                    [(run_date, strategy, "__CASH__", 0.0)])
            self.db.executemany(
                "INSERT INTO orders(client_order_id, run_date, ticker, side, notional, qty, status, updated_utc)"
                " VALUES (?,?,?,?,?,?, 'planned', ?)",
                [(o["client_order_id"], run_date, o["ticker"], o["side"], o.get("notional"), o.get("qty"), _now())
                 for o in orders])
            self.db.execute("UPDATE runs SET transition_pending=? WHERE run_date=?",
                            (int(transition_pending), run_date))

    def has_plan(self, run_date: str) -> bool:
        return self.db.execute("SELECT 1 FROM targets WHERE run_date=? LIMIT 1", (run_date,)).fetchone() is not None

    def orders_for(self, run_date: str, status: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM orders WHERE run_date=?", [run_date]
        if status:
            q += " AND status=?"
            args.append(status)
        return [dict(r) for r in self.db.execute(q + " ORDER BY side DESC, ticker", args)]  # sells first

    def mark_order(self, client_order_id: str, status: str, broker_order_id: str | None = None) -> None:
        with self.db:
            self.db.execute("UPDATE orders SET status=?, broker_order_id=COALESCE(?, broker_order_id), "
                            "updated_utc=? WHERE client_order_id=?",
                            (status, broker_order_id, _now(), client_order_id))

    FINAL_STATUSES = ("filled", "rejected", "expired", "canceled", "cancelled", "done_for_day")

    def unreconciled_orders(self) -> list[dict]:
        """Submitted orders whose final broker outcome isn't recorded yet."""
        marks = ",".join("?" * len(self.FINAL_STATUSES))
        return [dict(r) for r in self.db.execute(
            f"SELECT * FROM orders WHERE status='submitted' AND "
            f"(broker_status IS NULL OR broker_status NOT IN ({marks})) ORDER BY run_date",
            self.FINAL_STATUSES)]

    def record_fill(self, client_order_id: str, broker_status: str, filled_qty: float | None,
                    filled_price: float | None) -> None:
        with self.db:
            self.db.execute("UPDATE orders SET broker_status=?, filled_qty=?, filled_price=?, updated_utc=? "
                            "WHERE client_order_id=?",
                            (broker_status, filled_qty, filled_price, _now(), client_order_id))

    def positions_from_fills(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for t, side, q in self.db.execute("SELECT ticker, side, filled_qty FROM orders WHERE filled_qty > 0"):
            out[t] = out.get(t, 0.0) + (q if side == "buy" else -q)
        return {t: q for t, q in out.items() if abs(q) > 1e-9}

    def orders_between(self, start: str, end: str) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM orders WHERE run_date BETWEEN ? AND ? ORDER BY run_date, side DESC, ticker", (start, end))]

    def events_between(self, start: str, end: str) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM events WHERE run_date BETWEEN ? AND ? ORDER BY ts_utc", (start, end))]

    def latest_targets(self, strategy: str, before: str | None = None) -> dict[str, float] | None:
        q, args = "SELECT MAX(run_date) FROM targets WHERE strategy=?", [strategy]
        if before:
            q += " AND run_date < ?"
            args.append(before)
        d = self.db.execute(q, args).fetchone()[0]
        if d is None:
            return None
        rows = self.db.execute("SELECT ticker, weight FROM targets WHERE run_date=? AND strategy=?", (d, strategy))
        return {t: w for t, w in rows if t != "__CASH__"}

    def targets_on(self, run_date: str) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for s, t, w in self.db.execute("SELECT strategy, ticker, weight FROM targets WHERE run_date=?", (run_date,)):
            out.setdefault(s, {})
            if t != "__CASH__":
                out[s][t] = w
        return out

    # ---- shadow books (gate 3 paper comparisons; never traded) -----------------
    def save_shadow_targets(self, run_date: str, targets: dict[str, dict[str, float]]) -> None:
        with self.db:
            for strategy, weights in targets.items():
                self.db.execute("DELETE FROM shadow_targets WHERE run_date=? AND strategy=?", (run_date, strategy))
                self.db.executemany(
                    "INSERT INTO shadow_targets VALUES (?,?,?,?)",
                    [(run_date, strategy, t, float(w)) for t, w in weights.items()] or
                    [(run_date, strategy, "__CASH__", 0.0)])

    def latest_shadow_targets(self, strategy: str, before: str | None = None) -> dict[str, float] | None:
        q, args = "SELECT MAX(run_date) FROM shadow_targets WHERE strategy=?", [strategy]
        if before:
            q += " AND run_date < ?"
            args.append(before)
        d = self.db.execute(q, args).fetchone()[0]
        if d is None:
            return None
        rows = self.db.execute("SELECT ticker, weight FROM shadow_targets WHERE run_date=? AND strategy=?",
                               (d, strategy))
        return {t: w for t, w in rows if t != "__CASH__"}

    def recorded_targets(self, strategy: str) -> dict[str, dict[str, float]]:
        """Every recorded day's target for a strategy, traded (targets) or shadow, by run date."""
        out: dict[str, dict[str, float]] = {}
        for table in ("shadow_targets", "targets"):          # traded records win on the same day
            days: dict[str, dict[str, float]] = {}
            for d, t, w in self.db.execute(f"SELECT run_date, ticker, weight FROM {table} WHERE strategy=?",
                                           (strategy,)):
                days.setdefault(d, {})
                if t != "__CASH__":
                    days[d][t] = w
            out.update(days)
        return dict(sorted(out.items()))

    # ---- equity, cash flows, state, events -----------------------------------
    def record_equity(self, run_date: str, equity: float, cash: float) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?)", (run_date, equity, cash))

    def equity_history(self) -> list[tuple[str, float]]:
        return [(r[0], r[1]) for r in self.db.execute("SELECT run_date, equity FROM equity ORDER BY run_date")]

    def add_cash_flow(self, flow_date: str, amount: float, kind: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO cash_flows VALUES (?,?,?)", (flow_date, amount, kind))

    def cash_flows(self) -> list[tuple[str, float]]:
        return [(r[0], r[1]) for r in self.db.execute("SELECT flow_date, amount FROM cash_flows ORDER BY flow_date")]

    def net_deposits(self) -> float:
        """Deposits minus withdrawals."""
        return float(self.db.execute("SELECT COALESCE(SUM(amount), 0) FROM cash_flows").fetchone()[0])

    def get_flag(self, key: str) -> bool:
        r = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return bool(r and json.loads(r[0]))

    def set_flag(self, key: str, value: bool) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(bool(value))))

    def true_flags(self, prefix: str) -> list[str]:
        """Keys of flags set to true that start with prefix."""
        return [k for k, v in self.db.execute("SELECT key, value FROM state WHERE key LIKE ?", (prefix + "%",))
                if json.loads(v) is True]

    def get_value(self, key: str):
        """A JSON value from the state table (None if unset)."""
        r = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def set_value(self, key: str, value) -> None:
        with self.db:
            if value is None:
                self.db.execute("DELETE FROM state WHERE key=?", (key,))
            else:
                self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))

    def log_event(self, run_date: str, level: str, kind: str, message: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (_now(), run_date, level, kind, message))

    def events(self, run_date: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM events", ()
        if run_date:
            q, args = q + " WHERE run_date=?", (run_date,)
        return [dict(r) for r in self.db.execute(q + " ORDER BY ts_utc", args)]
