"""
Go-live mechanics (proposal, "Go-live, scaling and stop rules"):

  Half-size start   An approved entry with "live_since" trades at half size for its
                    first 4 weeks, then full size only if fills and the ledger
                    matched over that time (no reconcile mismatches or failed orders).
  Rollback          For the first 3 months after live_since, every run compares the
                    account's cumulative return since go-live with what the paper
                    books predict for the same days at the same sizes. A gap above
                    3 points switches back to the entry's "previous" strategy (full
                    size, a known strategy), or pauses trading if there is none.
                    Either way a critical event is logged, which sends an alert.

approved.json entry, e.g.:
    {"strategy": "vol_target_15", "allocation": 1.0, "live_since": "2027-06-01",
     "previous": "buy_hold_index"}
Entries without "live_since" (e.g. benchmarks on paper) get neither mechanism.
"half_size": true still forces half size by hand.

The Pi never edits approved.json (it only pulls it); a rollback is a ledger flag
keyed by strategy + live_since, so pulling a new approval starts fresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from live.ledger.db import Ledger
from live.risk.limits import RiskLimits
from research.engine.backtest import run_backtest


@dataclass
class Entry:
    strategy: str
    allocation: float
    scale: float                 # allocation multiplier: 1.0 or the half-size factor
    live_since: pd.Timestamp | None = None
    previous: str | None = None
    rolled_back_from: str | None = None


def sizing(entries: list[Entry]) -> list[tuple[str, float]]:
    return sorted((e.strategy, round(e.allocation * e.scale, 9)) for e in entries)


def sizing_changed(approved: list[dict], ledger: Ledger, entries: list[Entry], last_run_date: str | None,
                   limits: RiskLimits) -> bool:
    """True if what trades, or at what size, differs from the last completed run (a scale-up
    after 4 weeks, a rollback): the engine must re-plan orders even on a non-rebalance day."""
    if not last_run_date:
        return False
    prev = effective_entries(approved, ReadOnlyLedger(ledger), pd.Timestamp(last_run_date), last_run_date, limits)
    return sizing(prev) != sizing(entries)


def rollback_key(e: dict) -> str:
    return f"rolled_back:{e['strategy']}:{e.get('live_since', '')}"


def effective_entries(approved: list[dict], ledger: Ledger, d: pd.Timestamp, ds: str,
                      limits: RiskLimits) -> list[Entry]:
    out = []
    for e in approved:
        since = pd.Timestamp(e["live_since"]) if e.get("live_since") else None
        if since is not None and ledger.get_flag(rollback_key(e)):
            out.append(Entry(e["previous"], e["allocation"], 1.0, rolled_back_from=e["strategy"]))
            continue
        half = bool(e.get("half_size"))
        if since is not None and d >= since:
            if d < since + timedelta(days=limits.half_size_days):
                half = True
            elif not _fills_and_ledger_matched(ledger, since, ds):
                half = True
                if not any(ev["kind"] == "scale_up_blocked" for ev in ledger.events(ds)):
                    ledger.log_event(ds, "warning", "scale_up_blocked",
                                     f"{e['strategy']} stays at half size: reconcile mismatches or failed "
                                     f"orders since {since.date()}; check them, then it scales up by itself")
        out.append(Entry(e["strategy"], e["allocation"], limits.half_size_factor if half else 1.0,
                         since, e.get("previous")))
    return out


def _fills_and_ledger_matched(ledger: Ledger, since: pd.Timestamp, ds: str) -> bool:
    bad = {"reconcile_mismatch", "order_failed"}
    return not any(ev["kind"] in bad for ev in ledger.events_between(str(since.date()), ds))


# ---------------------------------------------------------------------------
def drift(approved: list[dict], ledger: Ledger, panel: dict, registry: dict, since: pd.Timestamp, ds: str,
          limits: RiskLimits) -> dict | None:
    """Account vs paper since go-live, on SETTLED days only.

    For each day t after `since`: the account's return (deposits/withdrawals taken out)
    vs what the paper books predict, i.e. the sum of allocation x scale x book return,
    with sizes as the engine set them at the previous run. Days whose open had fills
    from the account's own orders are skipped: the 30% turnover cap phases trades in
    over several days on purpose, which the paper book (full trade at the next open)
    doesn't do, and in a fast market that alone moved an honest go-live 4 points
    (momentum, Feb 2020). What's left is pure tracking: missing or extra shares,
    wrong prices, data faults, trades that never happened. Wrong fills on trade
    days are reconcile's job (ledger vs broker)."""
    from live.gate3 import RecordedBook

    eq = pd.Series({pd.Timestamp(k): v for k, v in ledger.equity_history()}, dtype=float)
    eq = eq[(eq.index >= since) & (eq.index <= pd.Timestamp(ds))]
    if len(eq) < 2:
        return None
    days = eq.index
    flows = pd.Series(0.0, index=days)
    for day, amt in ledger.cash_flows():
        t = pd.Timestamp(day)
        if days[0] < t <= days[-1]:
            flows[days[days.searchsorted(t)]] += amt
    live_r = ((eq - flows) / eq.shift(1) - 1).iloc[1:]

    sizes = {t: [(x.strategy, x.allocation * x.scale)
                 for x in effective_entries(approved, ReadOnlyLedger(ledger), t, str(t.date()), limits)]
             for t in days}
    book_r = {}
    for name in {n for ents in sizes.values() for n, _ in ents}:
        rec = ledger.recorded_targets(name)
        if rec:
            beq = run_backtest(RecordedBook(registry[name], rec), panel, days[0], days[-1]).equity
            book_r[name] = beq.pct_change().reindex(days).fillna(0.0)
    exp_r = pd.Series({t: sum(w * book_r[n].get(t, 0.0) for n, w in sizes[days[i - 1]] if n in book_r)
                       for i, t in enumerate(days) if i > 0})

    traded = {o["run_date"] for o in ledger.orders_between(str(days[0].date()), ds)}
    settled = [t for i, t in enumerate(days) if i > 0 and str(days[i - 1].date()) not in traded]
    if not settled:
        return None
    live = float((1 + live_r[settled]).prod() - 1)
    exp = float((1 + exp_r[settled]).prod() - 1)
    return {"live": live, "paper": exp, "gap": live - exp, "settled_days": len(settled)}


def check_drift(approved: list[dict], ledger: Ledger, panel: dict, registry: dict, d: pd.Timestamp,
                ds: str, limits: RiskLimits) -> str | None:
    """Returns "rollback" or "pause" if an entry in its first months drifted from paper, else None.
    Acts on the first drifting entry: sets its rollback flag or the pause flag, logs a critical event."""
    for e in approved:
        if not e.get("live_since") or ledger.get_flag(rollback_key(e)):
            continue
        since = pd.Timestamp(e["live_since"])
        if not (since < d <= since + timedelta(days=limits.drift_window_days)):
            continue
        r = drift(approved, ledger, panel, registry, since, ds, limits)
        if r is None or abs(r["gap"]) <= limits.drift_limit:
            continue
        msg = (f"{e['strategy']} live since {since.date()}: account {r['live']:+.2%} vs paper {r['paper']:+.2%} "
               f"over {r['settled_days']} settled days (gap {r['gap']:+.2%}, limit {limits.drift_limit:.0%})")
        if e.get("previous"):
            ledger.set_flag(rollback_key(e), True)
            ledger.log_event(ds, "critical", "rollback", f"{msg}: switched back to {e['previous']}")
            return "rollback"
        ledger.set_flag("paused", True)
        ledger.log_event(ds, "critical", "drift_pause",
                         f"{msg}: no previous strategy, trading PAUSED; resume with python -m live.kill --resume")
        return "pause"
    return None


class ReadOnlyLedger:
    """Ledger view for replaying past sizing decisions without logging new events."""

    def __init__(self, ledger: Ledger):
        self._l = ledger

    def get_flag(self, key):
        return self._l.get_flag(key)

    def events(self, run_date=None):
        return [{"kind": "scale_up_blocked"}]          # suppress logging during the replay

    def events_between(self, start, end):
        return self._l.events_between(start, end)

    def log_event(self, *a, **k):
        pass
