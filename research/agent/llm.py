"""
Model clients with a hard USD spend cap.

  AnthropicClient         the researcher (official `anthropic` SDK; research machine only)
  OpenAICompatibleClient  gate 2 reviewers from other providers (plain HTTPS chat API)
  ScriptedClient          tests: returns canned replies, costs nothing

Every call goes through a Ledger that refuses the call up front if its worst case
(input estimate + max output tokens) could cross the session cap or the monthly
cap, then records the real usage afterwards. Spend is appended to
research/agent/state/spend.jsonl so the monthly cap survives restarts.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from research.agent.config import MONTHLY_USD_CAP, ModelSpec

STATE_DIR = Path(__file__).resolve().parent / "state"
SPEND_LOG = STATE_DIR / "spend.jsonl"


class BudgetExceeded(RuntimeError):
    pass


class ModelUnavailable(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    usd: float
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""


class SpendLedger:
    def __init__(self, session_usd: float, monthly_usd: float = MONTHLY_USD_CAP, log: Path | None = SPEND_LOG,
                 session_id: str = ""):
        self.session_usd, self.monthly_usd, self.log, self.session_id = session_usd, monthly_usd, log, session_id
        self.spent = 0.0

    def month_spent(self) -> float:
        if not self.log or not self.log.exists():
            return 0.0
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return sum(r["usd"] for r in map(json.loads, self.log.read_text().splitlines())
                   if r["ts"].startswith(month))

    def reserve(self, worst_case_usd: float) -> None:
        if self.spent + worst_case_usd > self.session_usd:
            raise BudgetExceeded(f"session cap ${self.session_usd:.2f}: spent ${self.spent:.2f}, "
                                 f"next call could cost up to ${worst_case_usd:.2f}")
        if self.month_spent() + worst_case_usd > self.monthly_usd:
            raise BudgetExceeded(f"monthly cap ${self.monthly_usd:.2f} would be crossed")

    def record(self, spec: ModelSpec, reply: Reply, purpose: str) -> None:
        self.spent += reply.usd
        if self.log:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with self.log.open("a") as f:
                f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "session": self.session_id, "model": spec.model, "purpose": purpose,
                                    "usd": round(reply.usd, 6), "in": reply.input_tokens,
                                    "out": reply.output_tokens}) + "\n")


def _est_tokens(text: str) -> int:
    return len(text) // 3 + 50          # deliberately pessimistic (~3 chars per token)


class _Base:
    def __init__(self, spec: ModelSpec, ledger: SpendLedger):
        self.spec, self.ledger = spec, ledger

    def worst_case(self, system: str, user: str, max_tokens: int) -> float:
        s = self.spec
        return (_est_tokens(system + user) * s.usd_per_mtok_in + max_tokens * s.usd_per_mtok_out) / 1e6

    def ask(self, system: str, user: str, *, max_tokens: int, purpose: str, effort: str = "high") -> Reply:
        self.ledger.reserve(self.worst_case(system, user, max_tokens))
        reply = self._call(system, user, max_tokens, effort)
        self.ledger.record(self.spec, reply, purpose)
        return reply

    def _call(self, system, user, max_tokens, effort) -> Reply:
        raise NotImplementedError


class AnthropicClient(_Base):
    """Claude through the official SDK (`pip install anthropic` on the research machine)."""

    def __init__(self, spec: ModelSpec, ledger: SpendLedger):
        super().__init__(spec, ledger)
        if not os.environ.get(spec.key_env):
            raise ModelUnavailable(f"{spec.key_env} is not set")
        try:
            import anthropic
        except ImportError as e:
            raise ModelUnavailable("the anthropic SDK is not installed: pip install anthropic") from e
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=os.environ[spec.key_env], max_retries=3)

    def _call(self, system, user, max_tokens, effort) -> Reply:
        # Stable system prompt is cached; refusals fall back server-side to another model.
        resp = self._client.beta.messages.create(
            model=self.spec.model, max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        u = resp.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        s = self.spec
        usd = (u.input_tokens * s.usd_per_mtok_in + cache_write * s.usd_per_mtok_in * 1.25
               + cache_read * s.usd_per_mtok_in * 0.1 + u.output_tokens * s.usd_per_mtok_out) / 1e6
        if resp.stop_reason == "refusal":
            text = ""
        return Reply(text, usd, u.input_tokens + cache_read + cache_write, u.output_tokens, resp.stop_reason)


class OpenAICompatibleClient(_Base):
    """Any provider with an OpenAI-style /chat/completions endpoint (reviewers only)."""

    def __init__(self, spec: ModelSpec, ledger: SpendLedger):
        super().__init__(spec, ledger)
        if not os.environ.get(spec.key_env):
            raise ModelUnavailable(f"{spec.key_env} is not set")

    def _call(self, system, user, max_tokens, effort) -> Reply:
        import requests

        r = requests.post(f"{self.spec.base_url.rstrip('/')}/chat/completions", timeout=600,
                          headers={"Authorization": f"Bearer {os.environ[self.spec.key_env]}"},
                          json={"model": self.spec.model, self.spec.token_param: max_tokens,
                                "messages": [{"role": "system", "content": system},
                                             {"role": "user", "content": user}]})
        r.raise_for_status()
        data = r.json()
        u = data.get("usage") or {}
        i, o = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
        usd = (i * self.spec.usd_per_mtok_in + o * self.spec.usd_per_mtok_out) / 1e6
        choice = (data.get("choices") or [{}])[0]
        return Reply((choice.get("message") or {}).get("content") or "", usd, i, o,
                     choice.get("finish_reason", ""))


class ScriptedClient(_Base):
    """Tests: replies come from a list or a function(system, user) -> str. Free."""

    def __init__(self, spec: ModelSpec, ledger: SpendLedger, replies):
        super().__init__(spec, ledger)
        self.replies, self.calls = replies, []

    def _call(self, system, user, max_tokens, effort) -> Reply:
        self.calls.append((system, user))
        text = self.replies(system, user) if callable(self.replies) else self.replies.pop(0)
        return Reply(text, 0.0)


def make_client(spec: ModelSpec, ledger: SpendLedger):
    if spec.provider == "anthropic":
        return AnthropicClient(spec, ledger)
    if spec.provider == "openai_compatible":
        return OpenAICompatibleClient(spec, ledger)
    raise ValueError(f"unknown provider {spec.provider!r}")
