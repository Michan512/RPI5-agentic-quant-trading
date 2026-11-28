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

    @property
    def vendor(self) -> str:
        return self.label or self.provider


# Researcher: Claude Opus 5.5 ($4 / $20 per million tokens, cache reads $0.20).
RESEARCHER = ModelSpec("anthropic", "claude-opus-5-5", "ANTHROPIC_API_KEY", 4.0, 20.0, label="anthropic")

# Gate 2 reviewers: other providers, any OpenAI-compatible chat API. The model names,
# endpoints and prices below are EXAMPLES, not verified: replace them with the models
# and current prices of the accounts you open. Reviewers whose key variable is unset
# are skipped, and promotion waits until at least MIN_REVIEWERS are available.
REVIEWERS: tuple[ModelSpec, ...] = (
    ModelSpec("openai_compatible", "gpt-5", "OPENAI_API_KEY", 1.25, 10.0,
              base_url="https://api.openai.com/v1", label="openai"),
    ModelSpec("openai_compatible", "gemini-2.5-pro", "GEMINI_API_KEY", 1.25, 10.0,
              base_url="https://generativelanguage.googleapis.com/v1beta/openai", label="google"),
    ModelSpec("openai_compatible", "deepseek-chat", "DEEPSEEK_API_KEY", 0.27, 1.10,
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
