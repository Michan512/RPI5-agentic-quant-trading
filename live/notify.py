"""
Alerts (Telegram) and the heartbeat ping for the off-Pi watchdog.

Settings come from the Pi's environment (its own .env):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   alerts and weekly reports
    HEALTHCHECK_URL                         e.g. https://hc-ping.com/<uuid>

The watchdog runs OFF the Pi: a healthchecks.io check expects one ping per
trading day. If the Pi crashes, loses power or network, the ping never arrives
and healthchecks.io alerts you. Nothing is sent when a setting is missing
(the laptop has none), so this never fails a trading run.
"""

from __future__ import annotations

import os

TIMEOUT = 10


class Notifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "")

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        if not self.enabled:
            print(f"[notify] alerts disabled (no Telegram token); message was:\n{text}")
            return False
        import requests

        try:
            r = requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                              json={"chat_id": self.chat_id, "text": text[:4000]}, timeout=TIMEOUT)
            return r.ok
        except Exception as e:                       # an alert failure must never stop trading logic
            print(f"[notify] could not send alert: {type(e).__name__}")
            return False


def ping_heartbeat(ok: bool, url: str | None = None) -> bool:
    url = url if url is not None else os.environ.get("HEALTHCHECK_URL", "")
    if not url:
        return False
    import requests

    try:
        return requests.get(url if ok else url.rstrip("/") + "/fail", timeout=TIMEOUT).ok
    except Exception:
        return False


def summarize_run(result, events: list[dict], problems: list[str]) -> str | None:
    """Text for an alert, or None if the run was routine and needs no message."""
    bad_events = [e for e in events if e["level"] in ("error", "critical")]
    warn_events = [e for e in events if e["level"] == "warning"]
    if result.status in ("completed", "duplicate", "skipped") and not bad_events and not problems \
            and not warn_events:
        return None
    lines = [f"Trading run {result.run_date}: {result.status.upper()}", result.message]
    lines += [f"- {e['level']}: {e['kind']}: {e['message']}" for e in bad_events + warn_events]
    lines += [f"- reconcile: {p}" for p in problems]
    return "\n".join(l for l in lines if l)
