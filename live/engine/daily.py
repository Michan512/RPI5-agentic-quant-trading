"""
The daily live engine. Run once after the US close; orders queue for the next open.

Each run, for trading day D:
  1. Same day already completed?            -> do nothing (duplicate-run safe)
  2. Same day started but not finished?     -> resume: reconcile saved orders with
                                               the broker by client_order_id and
                                               send only the missing ones
  3. Risk guards: kill switch, disabled, hard stop, drawdown pause, daily loss halt
  4. Fresh data for D?                      -> otherwise no trade
  5. Strategy targets (only on each strategy's rebalance day; else keep the last)
  6. Combine by allocation, risk layer -> orders; save the plan BEFORE sending
  7. Send orders (timeouts: look the order up before retrying once)
  8. Record everything, write the heartbeat

Every failure path ends in "no trade" or "the correct trade", never a duplicate.

CLI (laptop, no keys):
    python -m live.engine.daily --broker fake --dry-run
    python -m live.engine.daily --broker fake            # simulated account in live/state/
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from live import config
from live.broker.base import BrokerTimeout, DuplicateOrder, OrderRejected
from live.engine.calendar import is_trading_day, trading_days
from live.engine.data import StaleData, check_fresh
from live.ledger.db import Ledger
from live.risk.layer import guard, plan_orders, sell_everything
from live.risk.limits import DEFAULT_LIMITS, RiskLimits
from research.engine import settings as S
from shared.strategy import InvalidWeights, PriceView, is_rebalance_day, validate_weights


@dataclass
class RunResult:
    run_date: str
    status: str                  # completed | duplicate | skipped | failed | halted
    message: str = ""
    targets: dict = field(default_factory=dict)
    orders: list = field(default_factory=list)


class DailyEngine:
    def __init__(self, broker, ledger: Ledger, provider, approved: list[dict],
                 registry: dict | None = None, limits: RiskLimits = DEFAULT_LIMITS,
                 kill_switch_path: Path | None = config.KILL_SWITCH,
                 heartbeat_path: Path | None = None, cap_turnover: bool = True):
        self.broker, self.ledger, self.provider = broker, ledger, provider
        self.approved, self.limits = approved, limits
        self.registry = registry or config.strategy_registry()
        unknown = [e["strategy"] for e in approved if e["strategy"] not in self.registry]
        if unknown:
            raise ValueError(f"approved strategies not in the registry: {unknown}")
        self.kill_switch_path, self.heartbeat_path = kill_switch_path, heartbeat_path
        self.cap_turnover = cap_turnover
        self.cost_rate = (S.FEE_BPS + S.SLIPPAGE_BPS) / 1e4
        self._instances: dict = {}

    # ------------------------------------------------------------------
    def run(self, run_date) -> RunResult:
        d = pd.Timestamp(run_date).normalize()
        ds = str(d.date())
        if not is_trading_day(d):
            return RunResult(ds, "skipped", "market closed")
        prior = self.ledger.get_run(ds)
        if prior and prior["status"] == "completed":
            return RunResult(ds, "duplicate", "already completed today; nothing sent")
        self.ledger.start_run(ds)
        try:
            if self.ledger.has_plan(ds):          # a previous attempt saved a plan: finish it
                return self._send(ds, "resumed after an interrupted run")
            return self._fresh_run(d, ds)
        finally:
            self._heartbeat(ds)

    # ------------------------------------------------------------------
    def _fresh_run(self, d: pd.Timestamp, ds: str) -> RunResult:
        L = self.ledger
        acct, positions = self.broker.account(), self.broker.positions()
        history = [e for day, e in L.equity_history() if day < ds]
        g = guard(kill_switch=bool(self.kill_switch_path and self.kill_switch_path.exists()),
                  disabled=L.get_flag("disabled"), paused=L.get_flag("paused"),
                  equity=acct.equity, equity_history=history,
                  net_deposits=L.net_deposits(), limits=self.limits)
        L.record_equity(ds, acct.equity, acct.cash)

        if g.action in ("kill", "disabled", "paused"):
            return self._stop(ds, "skipped", g.reason, level="warning", kind=g.action)
        if g.action == "hard_stop":
            L.set_flag("disabled", True)
            L.log_event(ds, "critical", "hard_stop", g.reason)
            orders = sell_everything(positions, ds)
            L.save_plan(ds, {"__hard_stop__": {}}, orders, False)
            return self._send(ds, g.reason)
        if g.action == "pause":
            L.set_flag("paused", True)
            return self._stop(ds, "halted", g.reason, level="critical", kind="drawdown_pause")
        if g.action == "halt_today":
            return self._stop(ds, "halted", g.reason, level="warning", kind="daily_loss_halt", completed=True)

        try:
            panel = self.provider.panel(d)
            check_fresh(panel, d)
        except StaleData as e:
            return self._stop(ds, "failed", f"no trade: {e}", level="error", kind="stale_data")

        view = PriceView(panel, d)
        days = trading_days(d - timedelta(days=20), d + timedelta(days=20))
        i = days.get_loc(d)
        targets, rebalanced = {}, False
        try:
            for e in self.approved:
                name = e["strategy"]
                strat = self._instances.setdefault(name, self.registry[name]())
                prev = L.latest_targets(name, before=ds)
                if prev is None or is_rebalance_day(days, i, strat.rebalance):
                    targets[name] = validate_weights(strat.target_weights(view)).to_dict()
                    rebalanced = True
                else:
                    targets[name] = prev
        except InvalidWeights as e:
            return self._stop(ds, "failed", f"no trade: invalid strategy output: {e}", level="error",
                              kind="invalid_weights")

        last = L.last_completed_run(before=ds)
        pending = bool(last and last["transition_pending"])
        if not rebalanced and not pending:
            L.save_plan(ds, targets, [], False)
            L.finish_run(ds, "completed", "not a rebalance day")
            return RunResult(ds, "completed", "not a rebalance day", targets)

        combined = pd.Series(dtype=float)
        for e in self.approved:
            scale = e["allocation"] * (self.limits.half_size_factor if e.get("half_size") else 1.0)
            combined = combined.add(pd.Series(targets[e["strategy"]], dtype=float) * scale, fill_value=0.0)
        prices = panel["close"].iloc[-1]
        try:
            orders, capped = plan_orders(target=combined, positions=positions, prices=prices,
                                         equity=acct.equity, cash=acct.cash, cost_rate=self.cost_rate,
                                         limits=self.limits, run_date=ds, cap_turnover=self.cap_turnover)
        except InvalidWeights as e:
            return self._stop(ds, "failed", f"no trade: combined portfolio invalid: {e}", level="error",
                              kind="invalid_weights")
        if capped:
            L.log_event(ds, "info", "turnover_cap", "target only partly reached; continuing next trading day")
        L.save_plan(ds, targets, orders, capped)
        result = self._send(ds, "rebalanced" + (" (turnover capped)" if capped else ""))
        result.targets = targets
        return result

    # ------------------------------------------------------------------
    def _send(self, ds: str, note: str) -> RunResult:
        L, sent, errors = self.ledger, [], []
        for o in L.orders_for(ds):
            if o["status"] == "submitted":
                continue
            cid = o["client_order_id"]
            found = self.broker.get_order(cid)            # did an earlier attempt get through?
            if found:
                L.mark_order(cid, "submitted", found["id"])
                continue
            ok, err = self._submit_once_with_retry(o)
            if ok:
                sent.append(cid)
            else:
                errors.append(f"{cid}: {err}")
        if errors:
            for e in errors:
                L.log_event(ds, "error", "order_failed", e)
            L.finish_run(ds, "failed", f"{note}; {len(errors)} order(s) failed; rerun to retry")
            return RunResult(ds, "failed", "; ".join(errors), orders=sent)
        L.finish_run(ds, "completed", note)
        return RunResult(ds, "completed", note, orders=sent)

    def _submit_once_with_retry(self, o: dict) -> tuple[bool, str]:
        cid = o["client_order_id"]
        kwargs = {"notional": o["notional"]} if o["notional"] is not None else {"qty": o["qty"]}
        for attempt in (1, 2):
            try:
                ack = self.broker.submit_order(o["ticker"], o["side"], cid, **kwargs)
                self.ledger.mark_order(cid, "submitted", ack.get("id"))
                return True, ""
            except DuplicateOrder:
                found = self.broker.get_order(cid)
                self.ledger.mark_order(cid, "submitted", found["id"] if found else None)
                return True, ""
            except BrokerTimeout as e:
                found = self.broker.get_order(cid)      # timed out, but did it arrive?
                if found:
                    self.ledger.mark_order(cid, "submitted", found["id"])
                    return True, ""
                last = f"timeout ({e})"
            except OrderRejected as e:
                self.ledger.mark_order(cid, "failed")
                return False, f"rejected ({e})"
        self.ledger.mark_order(cid, "failed")
        return False, last

    def _stop(self, ds, status, reason, *, level, kind, completed=False) -> RunResult:
        self.ledger.log_event(ds, level, kind, reason)
        self.ledger.finish_run(ds, "completed" if completed else status, reason)
        return RunResult(ds, status, reason)

    def _heartbeat(self, ds: str) -> None:
        if self.heartbeat_path:
            r = self.ledger.get_run(ds) or {}
            self.heartbeat_path.write_text(json.dumps({
                "run_date": ds, "status": r.get("status"),
                "written_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}))


# ---------------------------------------------------------------------------
class DryRunBroker:
    """Wraps a broker: reads pass through, orders are only printed."""

    def __init__(self, inner):
        self.inner = inner

    def account(self):
        return self.inner.account()

    def positions(self):
        return self.inner.positions()

    def get_order(self, cid):
        return self.inner.get_order(cid)

    def submit_order(self, symbol, side, client_order_id, notional=None, qty=None):
        amount = f"${notional:,.2f}" if notional is not None else f"{qty:.6f} sh"
        print(f"  [dry-run] would {side.upper():4s} {symbol:6s} {amount:>14s}  id={client_order_id}")
        return {"id": "dry-run", "client_order_id": client_order_id, "status": "dry-run"}


def _default_run_date() -> pd.Timestamp:
    now = datetime.now(ZoneInfo("America/New_York"))
    d = pd.Timestamp(now.date())
    if (now.hour, now.minute) < (16, 30) or not is_trading_day(d):
        d -= timedelta(days=1)
        while not is_trading_day(d):
            d -= timedelta(days=1)
    return d


def market_is_open(now: datetime | None = None) -> bool:
    """True during regular NYSE hours (09:30-16:00 ET on a trading day)."""
    now = now or datetime.now(ZoneInfo("America/New_York"))
    return is_trading_day(pd.Timestamp(now.date())) and (9, 30) <= (now.hour, now.minute) < (16, 0)


def main(argv=None) -> None:
    from live.engine.data import YFinanceProvider

    ap = argparse.ArgumentParser(description="Daily live engine")
    ap.add_argument("--broker", choices=["fake", "alpaca"], required=True)
    ap.add_argument("--date", help="run date YYYY-MM-DD (default: latest finished session)")
    ap.add_argument("--dry-run", action="store_true", help="plan and print orders; change nothing")
    args = ap.parse_args(argv)

    config.STATE_DIR.mkdir(exist_ok=True)
    run_date = pd.Timestamp(args.date) if args.date else _default_run_date()
    provider = YFinanceProvider()

    if args.broker == "fake":
        from live.broker.fake import FakeBroker

        broker = FakeBroker.load(config.FAKE_BROKER_PATH)
        ledger_path = config.FAKE_LEDGER_PATH
        if not config.FAKE_BROKER_PATH.exists():
            print(f"[live] new simulated account with ${broker.cash:,.2f}")
        # Simulate the market: fill yesterday's queued orders at today's open, mark at the close.
        panel = provider.panel(run_date)
        if panel["close"].index[-1] == run_date:
            broker.open_session(panel["open"].iloc[-1].dropna().to_dict(), session=str(run_date.date()))
        broker.mark(panel["close"].iloc[-1].dropna().to_dict())
    else:
        from live.check_broker import pi_broker

        broker = pi_broker()                              # Pi only: loads the Pi's own .env
        ledger_path = config.LEDGER_PATH

    if args.dry_run:
        tmp = config.STATE_DIR / "_dry_run.db"
        if ledger_path.exists():
            shutil.copyfile(ledger_path, tmp)
        elif tmp.exists():
            tmp.unlink()
        ledger, broker_used = Ledger(tmp), DryRunBroker(broker)
    else:
        ledger, broker_used = Ledger(ledger_path), broker
        if not ledger.equity_history() and ledger.net_deposits() == 0:
            ledger.add_cash_flow(str(run_date.date()), broker.account().equity, "initial deposit")

    from live.notify import Notifier, ping_heartbeat, summarize_run
    from live.reconcile import reconcile

    notifier = Notifier()
    if args.broker == "alpaca" and not args.dry_run and market_is_open():
        # A catch-up run (e.g. the Pi was off at the scheduled time) must not send
        # orders into an open market: they would fill intraday, not at the open.
        msg = f"Trading run {run_date.date()} skipped: started during market hours; will run after the close."
        print(f"[live] {msg}")
        notifier.send(msg)
        ping_heartbeat(False)
        return
    print(f"[live] run date {run_date.date()}  broker={args.broker}{'  (dry run)' if args.dry_run else ''}")
    try:
        problems = reconcile(ledger, broker, str(run_date.date()))
        for p in problems:
            print(f"[live] RECONCILE: {p}")
        engine = DailyEngine(broker_used, ledger, provider, config.load_approved(),
                             heartbeat_path=None if args.dry_run else config.HEARTBEAT)
        res = engine.run(run_date)
    except Exception as e:
        if not args.dry_run:
            notifier.send(f"Trading run {run_date.date()} CRASHED: {type(e).__name__}: {e}")
            ping_heartbeat(False)
        raise
    print(f"[live] {res.status}: {res.message}")
    if not args.dry_run:
        alert = summarize_run(res, ledger.events(str(run_date.date())), problems)
        if alert:
            notifier.send(alert)
        ping_heartbeat(res.status in ("completed", "duplicate", "skipped", "halted") and not problems)
    for name, w in res.targets.items():
        print(f"  target {name}: " + (", ".join(f"{t} {x:.1%}" for t, x in sorted(w.items())) or "cash"))
    a = broker.account()
    print(f"[live] account equity ${a.equity:,.2f}  cash ${a.cash:,.2f}")
    if args.broker == "fake" and not args.dry_run:
        broker.save(config.FAKE_BROKER_PATH)


if __name__ == "__main__":
    main()
