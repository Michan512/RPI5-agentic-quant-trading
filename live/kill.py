"""
Manual controls. One command stops all trading.

    python -m live.kill                 # turn the kill switch ON (no orders at all)
    python -m live.kill --clear         # turn it OFF
    python -m live.kill --resume        # clear a drawdown pause (after you've reviewed)
    python -m live.kill --reset-hard-stop --confirm   # re-enable after a hard stop
    python -m live.kill --clear-promotion   # undo an automatic promotion (approved.json applies again)
    python -m live.kill --status
"""

import argparse

from live import config
from live.ledger.db import Ledger


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Live trading controls")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--reset-hard-stop", action="store_true")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--clear-promotion", action="store_true")
    ap.add_argument("--fake", action="store_true", help="act on the simulated (laptop) ledger")
    a = ap.parse_args(argv)

    config.STATE_DIR.mkdir(exist_ok=True)
    ledger = Ledger(config.FAKE_LEDGER_PATH if a.fake else config.LEDGER_PATH)
    if a.clear_promotion:
        p = ledger.get_value("promotion")
        ledger.set_value("promotion", None)
        print(f"promotion cleared ({p['strategy'] if p else 'none active'}); approved.json applies")
    elif a.resume:
        ledger.set_flag("paused", False)
        print("drawdown pause cleared")
    elif a.reset_hard_stop:
        if not a.confirm:
            raise SystemExit("refusing: add --confirm to re-enable trading after a hard stop")
        ledger.set_flag("disabled", False)
        print("hard stop reset; trading re-enabled")
    elif a.clear:
        config.KILL_SWITCH.unlink(missing_ok=True)
        print("kill switch OFF")
    elif not a.status:
        config.KILL_SWITCH.write_text("trading stopped manually\n")
        print("kill switch ON: no orders will be sent")
    print(f"status: kill={'ON' if config.KILL_SWITCH.exists() else 'off'}  "
          f"paused={ledger.get_flag('paused')}  disabled={ledger.get_flag('disabled')}")
    p = ledger.get_value("promotion")
    if p:
        print(f"promotion: {p['strategy']} live since {p['live_since']} (replaced {p['previous']}, promoted {p['promoted_on']})")


if __name__ == "__main__":
    main()
