"""
Promotion gate 2: reviewer agents (proposal, stage B item 7 and "Promotion gates").

- 2-3 models from providers OTHER than the researcher's.
- They see the code with comments and docstrings removed, and the backtest numbers.
  Never the author's hypothesis or explanation, never holdout numbers.
- Each reviews independently against the project's mistakes checklist and answers
  APPROVE or REJECT. Any reject, or any unclear answer, blocks.
- They can only approve or reject; they never edit anything.

Reviewer checks: every review round first shows each reviewer the planted bad
strategies (research/agent/planted.py). A reviewer that approves any of them
pauses ALL promotions and raises an alert, until the owner clears
research/agent/state/PROMOTIONS_PAUSED. A reviewer approving at least 90% of real
submissions (10 or more) is flagged as not working.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from research.agent import knowledge
from research.agent.checks import strip_comments
from research.agent.config import MIN_REVIEWERS, RESEARCHER, REVIEWERS
from research.agent.llm import ModelUnavailable, make_client
from research.agent.planted import FAKE_RESULTS, PLANTED

STATE = Path(__file__).resolve().parent / "state"
PAUSE_FLAG = STATE / "PROMOTIONS_PAUSED"
REVIEW_LOG = STATE / "reviews.jsonl"
VERDICT_RE = re.compile(r"^\s*VERDICT:\s*(APPROVE|REJECT)\b", re.I | re.M)

REVIEWER_SYSTEM = """You are an independent reviewer at a small quant fund. You did not write the strategy below
and you have no stake in it. Your only job is to stop strategies that would lose money live for reasons
the backtest hides. You can only approve or reject.

Reject if you find ANY of these:
- look-ahead: using information not available at the close of day T (shift(-1), future rows, centred windows,
  anything indexed past data.asof)
- memorised history: conditions on specific dates, years, months or events instead of a general rule
- curve fitting: oddly precise constants, many tuned thresholds, rules with no economic reason
- hidden concentration or leverage, ignoring costs or turnover, fragile code (NaN handling, empty data)
- anything in the project's checklist below
Approve only if the rule is general, explainable, uses only past data and the numbers are plausible for it.

PROJECT CHECKLIST (mistakes made before):
{checklist}

Answer format, exactly:
VERDICT: APPROVE or VERDICT: REJECT
REASONS: one to five short bullet points"""


@dataclass
class Review:
    reviewer: str
    approve: bool
    reasons: str
    raw_ok: bool = True


@dataclass
class Gate2Result:
    passed: bool
    status: str                     # approved | rejected | paused | not_enough_reviewers
    reviews: list = field(default_factory=list)
    detail: str = ""


def available_reviewers(ledger, factory=make_client) -> list:
    out = []
    for spec in REVIEWERS:
        if spec.vendor == RESEARCHER.vendor:
            continue                                     # must be a different provider
        try:
            out.append(factory(spec, ledger))
        except ModelUnavailable:
            continue
    return out


def _numbers(results: dict) -> str:
    return "\n".join(f"{p}: CAGR {m['cagr']:+.1%}, worst fall {m['max_drawdown']:.1%}, Sharpe "
                     f"{m.get('sharpe_rf0', float('nan')):.2f}, turnover {m['turnover_one_way_per_year']:.0%}/yr"
                     for p, m in results.items())


def _ask(client, code: str, results: dict, purpose: str) -> Review:
    system = REVIEWER_SYSTEM.format(checklist=knowledge._mistakes_checklist())
    user = (f"STRATEGY CODE (comments removed):\n```python\n{strip_comments(code)}\n```\n\n"
            f"BACKTEST AFTER COSTS (signals at the close, fills at the next open):\n{_numbers(results)}")
    try:
        text = client.ask(system, user, max_tokens=1500, purpose=purpose).text
    except Exception as e:
        return Review(client.spec.model, False, f"review failed: {type(e).__name__}", raw_ok=False)
    m = VERDICT_RE.search(text or "")
    if not m:
        return Review(client.spec.model, False, "no clear verdict (counts as reject)", raw_ok=False)
    return Review(client.spec.model, m.group(1).upper() == "APPROVE", text.strip()[:1500])


def _log(kind: str, name: str, reviews: list) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with REVIEW_LOG.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind,
                            "strategy": name, "reviews": [r.__dict__ for r in reviews]}) + "\n")


def rubber_stamps(min_reviews: int = 10, max_rate: float = 0.9) -> list[str]:
    if not REVIEW_LOG.exists():
        return []
    stats: dict = {}
    for row in map(json.loads, REVIEW_LOG.read_text().splitlines()):
        if row["kind"] != "real":
            continue
        for r in row["reviews"]:
            a, n = stats.get(r["reviewer"], (0, 0))
            stats[r["reviewer"]] = (a + int(r["approve"]), n + 1)
    return [k for k, (a, n) in stats.items() if n >= min_reviews and a / n >= max_rate]


def review(name: str, code: str, results: dict, clients: list, notify=None) -> Gate2Result:
    if PAUSE_FLAG.exists():
        return Gate2Result(False, "paused", detail=f"promotions paused: {PAUSE_FLAG.read_text()[:300]}")
    if len(clients) < MIN_REVIEWERS:
        return Gate2Result(False, "not_enough_reviewers",
                           detail=f"{len(clients)} reviewer(s) available, need {MIN_REVIEWERS} from other providers")
    # 1. reviewer checks: planted bad strategies first
    for pname, pcode in PLANTED.items():
        rs = [_ask(c, pcode, FAKE_RESULTS, "review_planted") for c in clients]
        _log("planted", pname, rs)
        fooled = [r.reviewer for r in rs if r.approve]
        if fooled:
            msg = f"reviewer(s) {fooled} approved planted bad strategy {pname!r}; promotions paused"
            STATE.mkdir(parents=True, exist_ok=True)
            PAUSE_FLAG.write_text(msg)
            if notify:
                notify(f"Stage B: {msg}. Check research/agent/state/reviews.jsonl, then delete {PAUSE_FLAG.name}.")
            return Gate2Result(False, "paused", rs, msg)
    # 2. the real submission
    rs = [_ask(c, code, results, "review_real") for c in clients]
    _log("real", name, rs)
    flagged = rubber_stamps()
    if flagged and notify:
        notify(f"Stage B: reviewer(s) {flagged} approve nearly everything; check them.")
    ok = all(r.approve for r in rs)
    return Gate2Result(ok, "approved" if ok else "rejected", rs)
