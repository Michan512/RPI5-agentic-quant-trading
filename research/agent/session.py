"""
Stage B research session: the LLM agent as a quant researcher (proposal, stage B).

Loop per idea (RD-Agent's hypothesis -> experiment -> feedback shape):
  1. propose   the researcher model reads the brief + every past trial and returns a
               hypothesis and a complete strategy module
  2. check     static checks on the source (research/agent/checks.py); nothing executes
  3. run       sandbox container: look-ahead test, then research + validation backtests
     (2-3 failing = a code problem: the errors go back for up to `fix_attempts` repairs.
      Repairs don't count as trials: no backtest result exists yet)
  4. screen    the fixed pre-gate rule (research/agent/rules.py)
  5. lesson    the researcher writes what the result taught (cheap call)
  6. log       every backtest becomes a trial in the trial log, pass or fail
  7. submit    ideas that pass the screen go to the promotion pipeline (gate 1 in the
               sandbox on the holdout, then gate 2 reviewers). The agent never sees the
               outcome.

Budgets: a hard USD cap per session and per month (research/agent/llm.py), a time cap,
an idea cap. A session report is written to research/agent/state/sessions/.

Usage (research machine; needs ANTHROPIC_API_KEY and `pip install anthropic`):
    python -m research.agent.session --ideas 5 --budget-usd 3
    python -m research.agent.session --ideas 5 --budget-usd 3 --no-submit
"""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from research.agent import knowledge, sandbox
from research.agent.checks import check_source
from research.agent.config import DEFAULT_BUDGET, RESEARCHER, SessionBudget
from research.agent.llm import BudgetExceeded, SpendLedger, make_client
from research.agent.rules import screen
from research.trials.log import log_trial_record, read_trials
from shared.universe import STOCKS

SESSIONS_DIR = Path(__file__).resolve().parent / "state" / "sessions"
CODE_RE = re.compile(r"<code>\s*```(?:python)?\s*\n(.*?)```\s*</code>", re.S)
HYP_RE = re.compile(r"<hypothesis>(.*?)</hypothesis>", re.S)


@dataclass
class IdeaOutcome:
    hypothesis: str = ""
    name: str = ""
    status: str = ""          # logged | submitted | gave_up | budget
    trial_id: int | None = None
    passed_screen: bool = False
    reasons: list = field(default_factory=list)
    lesson: str = ""
    attempts: int = 0


def parse_proposal(text: str) -> tuple[str, str]:
    h, c = HYP_RE.search(text or ""), CODE_RE.search(text or "")
    return (h.group(1).strip() if h else ""), (c.group(1) if c else "")


def _holds_stocks(src: str) -> bool:
    return "STOCKS" in src


class Session:
    def __init__(self, researcher, budget: SessionBudget = DEFAULT_BUDGET, submit=None,
                 run_job=sandbox.run_job, data_dir: Path | None = None, log_trial=log_trial_record,
                 session_id: str | None = None):
        self.researcher, self.budget, self.submit = researcher, budget, submit
        self.run_job, self.log_trial = run_job, log_trial
        self.data_dir = data_dir
        self.session_id = session_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.outcomes: list[IdeaOutcome] = []

    # ------------------------------------------------------------------
    def run(self) -> list[IdeaOutcome]:
        if self.data_dir is None:
            from research.gates.sandbox_export import research_snapshot
            self.data_dir = research_snapshot()
        deadline = time.time() + self.budget.hours * 3600
        brief = knowledge.system_brief()
        for _ in range(self.budget.iterations):
            if time.time() > deadline:
                break
            try:
                out = self._one_idea(brief)
            except BudgetExceeded as e:
                self.outcomes.append(IdeaOutcome(status="budget", reasons=[str(e)]))
                break
            self.outcomes.append(out)
        self._report()
        return self.outcomes

    # ------------------------------------------------------------------
    def _one_idea(self, brief: str) -> IdeaOutcome:
        o = IdeaOutcome()
        bench = knowledge.benchmarks()
        taken = {t["strategy"] for t in read_trials()}
        ask = (knowledge.research_state() + "\n\nPropose ONE new idea, different from every past trial. "
               "Use a strategy name that hasn't been used.")
        reply = self.researcher.ask(brief, ask, max_tokens=self.budget.max_output_tokens, purpose="propose")
        o.hypothesis, src = parse_proposal(reply.text)
        for attempt in range(self.budget.fix_attempts + 1):
            o.attempts = attempt + 1
            problems = self._check(src, o.hypothesis, taken)
            result = None
            if not problems:
                result = self.run_job("research", src, self.data_dir)
                if not result.get("ok"):
                    problems = [f"{result.get('stage')}: {result.get('error')}"]
            if not problems:
                break
            if attempt == self.budget.fix_attempts:
                o.status, o.reasons = "gave_up", problems
                return o
            fix = (f"Your strategy can't run yet. Problems:\n- " + "\n- ".join(problems)[:4000] +
                   "\n\nReply in the same format with the corrected complete module (same hypothesis).")
            reply = self.researcher.ask(brief, ask + "\n\nYOUR PREVIOUS ANSWER:\n" + reply.text[:20000] + "\n\n" + fix,
                                        max_tokens=self.budget.max_output_tokens, purpose="fix")
            h2, src = parse_proposal(reply.text)
            o.hypothesis = h2 or o.hypothesis

        chk = check_source(src)
        o.name = result["name"]
        results = result["results"]
        o.passed_screen, o.reasons = screen(results, bench, _holds_stocks(src))
        o.lesson = self._lesson(brief, o, results, bench)
        o.trial_id = self.log_trial(
            name=o.name, class_path=f"agent:{self.session_id}:{chk.class_name}", idea=o.hypothesis[:300],
            params=result.get("params") or {}, source_sha=chk.source_sha, results=results,
            notes="stage B agent; screen = beat buy-and-hold and 5%/yr, fall no deeper, turnover <= 300%, "
                  "stock pickers beat equal-weight, in both periods",
            extra={"earns_gate_attempt": o.passed_screen, "reasons": o.reasons, "session": self.session_id,
                   "source": src},
            hypothesis=o.hypothesis, lesson=o.lesson, author=f"agent:{RESEARCHER.model}")
        o.status = "logged"
        if o.passed_screen and self.submit:
            self.submit(o.trial_id, o.name, src, results)
            o.status = "submitted"
        return o

    def _check(self, src: str, hypothesis: str, taken: set) -> list[str]:
        if not src:
            return ["no code found: reply with <hypothesis>...</hypothesis> and <code>```python ...```</code>"]
        if not hypothesis:
            return ["no hypothesis found inside <hypothesis>...</hypothesis>"]
        c = check_source(src)
        problems = list(c.problems)
        if c.strategy_name in taken:
            problems.append(f"strategy name {c.strategy_name!r} is already used; pick a new one")
        return problems

    def _lesson(self, brief, o: IdeaOutcome, results, bench) -> str:
        def f(m):
            return f"CAGR {m['cagr']:+.1%}, fall {m['max_drawdown']:.1%}, turnover {m['turnover_one_way_per_year']:.0%}"
        text = (f"Your idea: {o.hypothesis}\n\nResults: research {f(results['research'])}; validation "
                f"{f(results['validation'])}.\nBuy-and-hold: research {f(bench['research']['buy_hold_index'])}; "
                f"validation {f(bench['validation']['buy_hold_index'])}.\n"
                f"Screen: {'PASSED' if o.passed_screen else 'failed: ' + '; '.join(o.reasons)}\n\n"
                "In 2-3 plain sentences: what did this result teach about the hypothesis, and what should future "
                "ideas do differently? Reply with the sentences only.")
        try:
            return self.researcher.ask(brief, text, max_tokens=800, purpose="lesson", effort="low").text.strip()[:1200]
        except BudgetExceeded:
            raise
        except Exception as e:  # a missing lesson must never lose the trial
            return f"(lesson not written: {type(e).__name__})"

    def _report(self) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        spent = self.researcher.ledger.spent
        lines = [f"# Research session {self.session_id}", "",
                 f"Model {RESEARCHER.model}; spent ${spent:.2f} of ${self.budget.usd:.2f}; "
                 f"{len([o for o in self.outcomes if o.trial_id])} trials logged.", ""]
        for o in self.outcomes:
            lines.append(f"- **{o.name or '(none)'}**: {o.status}" + (f", trial {o.trial_id}" if o.trial_id else "")
                         + (" (passed the screen, submitted)" if o.status == "submitted" else ""))
            if o.hypothesis:
                lines.append(f"  - hypothesis: {o.hypothesis[:300]}")
            if o.reasons:
                lines.append(f"  - {'; '.join(o.reasons)[:400]}")
            if o.lesson:
                lines.append(f"  - lesson: {o.lesson[:400]}")
        (SESSIONS_DIR / f"{self.session_id}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        with (SESSIONS_DIR / "sessions.jsonl").open("a") as fh:
            fh.write(json.dumps({"session": self.session_id, "spent_usd": round(spent, 4),
                                 "outcomes": [o.__dict__ for o in self.outcomes]}, default=str) + "\n")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Stage B research session")
    ap.add_argument("--ideas", type=int, default=DEFAULT_BUDGET.iterations)
    ap.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET.usd)
    ap.add_argument("--hours", type=float, default=DEFAULT_BUDGET.hours)
    ap.add_argument("--no-submit", action="store_true", help="log trials but don't submit to the gates")
    args = ap.parse_args(argv)
    if not sandbox.docker_available():
        raise SystemExit("sandbox image missing: python -m research.agent.sandbox build")
    budget = SessionBudget(usd=args.budget_usd, hours=args.hours, iterations=args.ideas)
    sid = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    researcher = make_client(RESEARCHER, SpendLedger(budget.usd, session_id=sid))
    submit = None
    if not args.no_submit:
        from research.agent.pipeline import submit as submit_fn
        submit = submit_fn
    s = Session(researcher, budget, submit=submit, session_id=sid)
    outs = s.run()
    summary = (f"Stage B session {sid}: {len([o for o in outs if o.trial_id])} trials, "
               f"{len([o for o in outs if o.status == 'submitted'])} submitted to the gates, "
               f"spent ${researcher.ledger.spent:.2f} of ${budget.usd:.2f}. Report: {SESSIONS_DIR / (sid + '.md')}")
    print(summary)
    try:
        from live.notify import Notifier
        Notifier().send(summary)
    except Exception:
        pass


if __name__ == "__main__":
    main()
