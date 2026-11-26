"""
Weekly report from the ledger and broker (proposal: "alerts and weekly reports").

    python -m live.report            # Pi: real ledger + Alpaca paper account
    python -m live.report --fake     # laptop: simulated account
    python -m live.report --send     # also send it via Telegram
"""

from __future__ import annotations

import argparse
from datetime import timedelta

import pandas as pd

from live import config
from live.ledger.db import Ledger


def build_report(ledger: Ledger, broker, asof: pd.Timestamp, days: int = 7) -> str:
    asof = pd.Timestamp(asof).normalize()
    start = asof - timedelta(days=days)
    s, e = str(start.date()), str(asof.date())
    hist = ledger.equity_history()
    acct = broker.account()
    deposits = ledger.net_deposits()

    lines = [f"Weekly report {s} to {e}", ""]
    week = [v for d, v in hist if d >= s]
    before = [v for d, v in hist if d < s]
    base = before[-1] if before else (week[0] if week else acct.equity)
    lines.append(f"Equity      ${acct.equity:,.2f} (cash ${acct.cash:,.2f})")
    lines.append(f"This week   {acct.equity / base - 1:+.2%}" if base else "This week   n/a")
    if deposits:
        lines.append(f"Since start {acct.equity / deposits - 1:+.2%} on ${deposits:,.2f} deposited")
    if hist:
        peak = max(v for _, v in hist)
        lines.append(f"From peak   {acct.equity / peak - 1:+.2%}")
    lines.append("")

    pos = broker.positions()
    lines.append("Positions:" if pos else "Positions: none (all cash)")
    for t, q in sorted(pos.items()):
        lines.append(f"  {t:6s} {q:12.4f} sh")
    lines.append("")

    orders = ledger.orders_between(s, e)
    lines.append(f"Orders this week: {len(orders)}")
    for o in orders:
        size = f"${o['notional']:,.2f}" if o["notional"] is not None else f"{o['qty']:.4f} sh"
        fill = f" filled {o['filled_qty']:.4f} @ {o['filled_price']:.2f}" if o.get("filled_qty") else ""
        lines.append(f"  {o['run_date']} {o['side']:4s} {o['ticker']:6s} {size:>12s} "
                     f"[{o['broker_status'] or o['status']}]{fill}")
    lines.append("")

    ev = [x for x in ledger.events_between(s, e) if x["level"] != "info"]
    lines.append(f"Warnings/errors this week: {len(ev)}")
    for x in ev:
        lines.append(f"  {x['run_date']} {x['level']}: {x['kind']}: {x['message']}")
    lines.append("")
    lines.append(f"Risk state: kill={'ON' if config.KILL_SWITCH.exists() else 'off'}  "
                 f"paused={ledger.get_flag('paused')}  disabled={ledger.get_flag('disabled')}")
    return "\n".join(lines)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Weekly report")
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args(argv)
    if a.fake:
        from live.broker.fake import FakeBroker

        broker, ledger = FakeBroker.load(config.FAKE_BROKER_PATH), Ledger(config.FAKE_LEDGER_PATH)
    else:
        from live.check_broker import pi_broker

        broker, ledger = pi_broker(), Ledger(config.LEDGER_PATH)
    text = build_report(ledger, broker, pd.Timestamp.today())
    print(text)
    if a.send:
        from live.notify import Notifier

        Notifier().send(text)


if __name__ == "__main__":
    main()
