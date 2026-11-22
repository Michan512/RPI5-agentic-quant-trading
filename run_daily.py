"""
Daily trading orchestrator.

Determines whether to run morning buys or afternoon sells based on the
current Eastern Time, then delegates to the Alpaca execution engine.

Usage:
    python run_daily.py              # auto-detect morning vs afternoon
    python run_daily.py --morning    # force morning buy mode
    python run_daily.py --afternoon  # force afternoon sell mode
    python run_daily.py --dry-run    # show signals without placing orders
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config


def _eastern_now() -> datetime:
    return datetime.now(ZoneInfo("America/New_York"))


def run_morning():
    """Generate signals and execute buy orders."""
    from live_predict import get_signals, print_report
    from execution.alpaca_client import execute_morning_buys

    print("=" * 55)
    print("  MORNING RUN - Signal Generation & Buy Execution")
    print("=" * 55)
    print()

    signals = get_signals()
    print_report(signals)

    buys = signals[signals["P(UP)"] > config.BUY_THRESHOLD]
    if buys.empty:
        print("\n[daily] No qualifying signals. Staying in cash.")
        return

    print(f"\n[daily] {len(buys)} stock(s) qualify. Submitting buy orders ...")
    execute_morning_buys(signals_df=signals)


def run_afternoon():
    """Liquidate all open positions."""
    from execution.alpaca_client import execute_afternoon_sells

    print("=" * 55)
    print("  AFTERNOON RUN - Portfolio Liquidation")
    print("=" * 55)
    print()

    execute_afternoon_sells()


def run_dry():
    """Show signals without placing any orders."""
    from live_predict import get_signals, print_report

    print("=" * 55)
    print("  DRY RUN - Signals Only (no orders)")
    print("=" * 55)
    print()

    signals = get_signals()
    print_report(signals)

    buys = signals[signals["P(UP)"] > config.BUY_THRESHOLD]
    if buys.empty:
        print("\n[dry-run] No stocks above threshold. Would stay in cash.")
    else:
        print(f"\n[dry-run] Would buy {len(buys)} stock(s):")
        for _, row in buys.iterrows():
            print(f"  -> {row['Ticker']:<6}  P(UP) = {row['P(UP)']:.2%}")


def main():
    parser = argparse.ArgumentParser(description="Daily trading orchestrator")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--morning", action="store_true",
                       help="Force morning buy mode")
    group.add_argument("--afternoon", action="store_true",
                       help="Force afternoon sell mode")
    group.add_argument("--dry-run", action="store_true",
                       help="Show signals without placing orders")
    args = parser.parse_args()

    now_et = _eastern_now()
    print(f"[daily] Current time (ET): {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")

    if args.dry_run:
        run_dry()
    elif args.morning:
        run_morning()
    elif args.afternoon:
        run_afternoon()
    else:
        # Auto-detect based on Eastern Time
        hour = now_et.hour
        if hour < config.MORNING_CUTOFF_HOUR:
            print(f"[daily] Before {config.MORNING_CUTOFF_HOUR}:00 ET "
                  f"-> MORNING mode\n")
            run_morning()
        elif hour >= config.AFTERNOON_START_HOUR:
            print(f"[daily] After {config.AFTERNOON_START_HOUR}:00 ET "
                  f"-> AFTERNOON mode\n")
            run_afternoon()
        else:
            print(f"[daily] Between {config.MORNING_CUTOFF_HOUR}:00 and "
                  f"{config.AFTERNOON_START_HOUR}:00 ET -> market hours, "
                  f"no action.\n")
            print("  Use --morning or --afternoon to force a mode,")
            print("  or --dry-run to view signals without trading.")


if __name__ == "__main__":
    main()
