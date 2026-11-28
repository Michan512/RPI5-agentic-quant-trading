"""
Stage B settings: models, prices, budgets, sandbox limits.

Keys come from environment variables on the RESEARCH machine only (proposal: "LLM
provider keys live only here, with monthly spend caps"). Never on the Pi. Nothing
here reads or prints a key's value.

The researcher and each reviewer must come from different providers (proposal:
"two or three models from providers other than the author's").
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSpec:
    provider: str                  # "anthropic" | "openai_compatible"
    model: str
    key_env: str                   # environment variable holding the API key
    usd_per_mtok_in: float
    usd_per_mtok_out: float
    base_url: str = ""             # openai_compatible only, e.g. https://api.openai.com/v1
    label: str = ""                # provider name used for the different-provider rule
    token_param: str = "max_tokens"  # OpenAI's reasoning models only accept "max_completion_tokens"

    @property
    def vendor(self) -> str:
        return self.label or self.provider


# Researcher: Claude Opus 5.5 ($4 / $20 per million tokens, cache reads $0.20).
RESEARCHER = ModelSpec("anthropic", "claude-opus-5-5", "ANTHROPIC_API_KEY", 4.0, 20.0, label="anthropic")

# Gate 2 reviewers: other providers, any OpenAI-compatible chat API. Reviewers whose
# key variable is unset are skipped, and promotion waits until at least MIN_REVIEWERS
# are available.
# 2026-11-28: OpenAI + DeepSeek model ids confirmed from each account's /models list
# and a test call. Prices come from third-party listings (Nov 2026), using the highest
# figure found (safe for the spend caps); check them against the providers' pricing pages.
# DeepSeek's off-peak hours are half price, which these figures ignore. Gemini is unused (no key).
REVIEWERS: tuple[ModelSpec, ...] = (
    ModelSpec("openai_compatible", "gpt-6.2-sol", "OPENAI_API_KEY", 2.0, 10.0,
              base_url="https://api.openai.com/v1", label="openai", token_param="max_completion_tokens"),
    ModelSpec("openai_compatible", "gemini-2.5-pro", "GEMINI_API_KEY", 1.25, 10.0,
              base_url="https://generativelanguage.googleapis.com/v1beta/openai", label="google"),
    ModelSpec("openai_compatible", "deepseek-v4-pro", "DEEPSEEK_API_KEY", 1.32, 3.96,
              base_url="https://api.deepseek.com/v1", label="deepseek"),
)
MIN_REVIEWERS = 2


@dataclass(frozen=True)
class SessionBudget:
    usd: float = 5.0               # hard cap on model spend for one session
    hours: float = 12.0            # proposal: "each with a time cap (for example 12 hours)"
    iterations: int = 20           # ideas per session
    fix_attempts: int = 2          # repairs per idea when code fails checks or crashes (not trials)
    max_output_tokens: int = 16000


DEFAULT_BUDGET = SessionBudget()
# Ceiling across all sessions in a calendar month (the break-even problem: at $5k the
# 5% target is $250/yr, so research has to stay cheap).
MONTHLY_USD_CAP = 30.0
