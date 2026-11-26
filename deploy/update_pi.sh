#!/usr/bin/env bash
# One-way update channel: the Pi PULLS the newest approved release; nothing pushes to it.
#
# A release is a git tag named live-v<N> that you create on the research machine
# after reviewing the change (git tag live-v2 && git push origin live-v2).
# The new version is tested in a separate copy first; the Pi switches only if
# every test passes. Otherwise it stays on the current version and alerts you.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
PI_TESTS="tests.test_strategy_interface tests.test_engine tests.test_live_failures tests.test_live_risk tests.test_live_ledger_calendar tests.test_live_parity tests.test_live_ops"
cd "$REPO"

notify() { "$PY" -c "import sys; from live.check_broker import load_pi_env; load_pi_env(); from live.notify import Notifier; Notifier().send(sys.argv[1])" "$1" || true; }

git fetch --tags --quiet origin
latest="$(git tag -l 'live-v*' --sort=-v:refname | head -n 1)"
current="$(git describe --tags --exact-match 2>/dev/null || echo none)"
if [ -z "$latest" ] || [ "$latest" = "$current" ]; then
  echo "up to date ($current)"
  exit 0
fi

echo "testing $latest (current: $current)"
STAGE="$(mktemp -d)"
cleanup() { git worktree remove --force "$STAGE" 2>/dev/null || rm -rf "$STAGE"; }
trap cleanup EXIT
git worktree add --detach --quiet "$STAGE" "$latest"
# Reuse the downloaded price files for the tests instead of downloading again.
rm -rf "$STAGE/research/data/raw"
ln -s "$REPO/research/data/raw" "$STAGE/research/data/raw"

# shellcheck disable=SC2086
if (cd "$STAGE" && "$PY" -m unittest $PI_TESTS); then
  git checkout --detach --quiet "$latest"
  "$PY" -m pip install --quiet -r deploy/requirements-pi.txt
  notify "Pi updated: $current -> $latest (all tests passed)."
  echo "switched to $latest"
else
  notify "Pi update to $latest REFUSED: tests failed. Still running $current."
  echo "tests failed; staying on $current" >&2
  exit 1
fi
