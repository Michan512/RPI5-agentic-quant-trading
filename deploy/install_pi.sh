#!/usr/bin/env bash
# Set up (or refresh) the live side on the Raspberry Pi. Safe to run again.
#
#   bash deploy/install_pi.sh            # venv, packages, price data, tests, systemd units (timers OFF)
#   bash deploy/install_pi.sh --enable   # same, then switch the timers ON
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"
PY="$REPO/.venv/bin/python"
# Tests that matter on the Pi (the research-only tests need xgboost and aren't run here).
PI_TESTS="tests.test_strategy_interface tests.test_engine tests.test_live_failures tests.test_live_risk tests.test_live_ledger_calendar tests.test_live_parity tests.test_live_ops"

cd "$REPO"
echo "== repo: $REPO  user: $USER_NAME"

if [ ! -x "$PY" ]; then
  echo "== creating virtual environment"
  python3 -m venv .venv
fi
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r deploy/requirements-pi.txt

mkdir -p live/state
chmod 700 live/state
if [ -f .env ]; then chmod 600 .env; else echo "!! no .env yet: create it before running live (see deploy/README.md)"; fi

echo "== downloading price history for the tests (a few minutes)"
"$PY" -m research.data.fetcher > /dev/null

echo "== running the Pi test suite"
# shellcheck disable=SC2086
"$PY" -m unittest $PI_TESTS

echo "== installing systemd units"
for unit in deploy/systemd/*.service deploy/systemd/*.timer; do
  sed -e "s|@USER@|$USER_NAME|g" -e "s|@REPO@|$REPO|g" "$unit" \
    | sudo tee "/etc/systemd/system/$(basename "$unit")" > /dev/null
done
chmod +x deploy/update_pi.sh
sudo systemctl daemon-reload

if [ "${1:-}" = "--enable" ]; then
  sudo systemctl enable --now trading-daily.timer trading-weekly.timer trading-update.timer
  echo "== timers ON:"
  systemctl list-timers 'trading-*' --no-pager
else
  echo "== done. Timers are OFF. When the dry run looks right:  bash deploy/install_pi.sh --enable"
fi
