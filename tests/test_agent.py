"""
Stage B research agent: static checks, spend caps, the session loop (scripted model),
gate 2 reviewers, the promotion pipeline, and the sandbox itself (real Docker runs,
skipped if the sandbox image isn't built).
"""

import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research.agent import pipeline, reviewers, sandbox
from research.agent.checks import check_source, strip_comments
from research.agent.config import RESEARCHER, ModelSpec, SessionBudget
from research.agent.llm import BudgetExceeded, ScriptedClient, SpendLedger
from research.agent.session import Session, parse_proposal

import research.strategies.vol_target as VT

GOOD = inspect.getsource(VT).replace('name = "vol_target_15"', 'name = "vol_target_test"')
REVIEWER = ModelSpec("openai_compatible", "rev-a", "X", 0, 0, label="openai")
REVIEWER_B = ModelSpec("openai_compatible", "rev-b", "Y", 0, 0, label="google")
HAS_DOCKER = sandbox.docker_available()


def proposal(code: str, hyp: str = "Volatility persists, so cutting exposure in wild markets helps.") -> str:
    return f"<hypothesis>{hyp}</hypothesis>\n<code>\n```python\n{code}\n```\n</code>"


def free_ledger(cap=100.0):
    return SpendLedger(cap, log=None)


class StaticChecks(unittest.TestCase):
    def test_existing_strategies_pass(self):
        from research.strategies import BENCHMARKS, ETF_ROUND1, ETF_ROUND2
        for cls in list(BENCHMARKS.values()) + list(ETF_ROUND1.values()) + list(ETF_ROUND2.values()):
            r = check_source(inspect.getsource(inspect.getmodule(cls)))
            if cls.name in ("combo_t1_t2_t3",):          # imports other strategy modules: not allowed for agents
                self.assertFalse(r.ok)
                continue
            self.assertTrue(r.ok, (cls.name, r.problems))

    def test_cheats_are_caught(self):
        cheats = {
            "file": "open('x')", "import": "import os", "reflection": "getattr(data, 'close')",
            "dunder": "data.__class__", "private": "data._panel", "print": "print(1)",
            "monkeypatch": "pd.Series.sum = None", "ticker": "x = 'SPY'", "pandas_read": "pd.read_pickle('x')",
            "eval": "pd.eval('1+1')",
        }
        for label, stmt in cheats.items():
            src = GOOD.replace("        index = etf(\"broad_index\")", f"        {stmt}\n        index = etf(\"broad_index\")")
            if label == "import":
                src = stmt + "\n" + GOOD
            with self.subTest(label):
                self.assertFalse(check_source(src).ok, label)

    def test_memorised_history_is_refused(self):
        # Found by the first real drill round: hard-coded crash years passed checks, sandbox and screen.
        for stmt in ("x = data.asof.year == 2008", "x = data.asof.year in (2020, 2022)",
                     "x = 2019 < data.asof.year", "x = data.close.loc['2020-03-01':]"):
            src = GOOD.replace('        index = etf("broad_index")', f'        {stmt}\n        index = etf("broad_index")')
            with self.subTest(stmt):
                self.assertFalse(check_source(src).ok, stmt)
        seasonal = GOOD.replace('        index = etf("broad_index")',
                                '        x = data.asof.month in (5, 6)\n        index = etf("broad_index")')
        self.assertTrue(check_source(seasonal).ok)               # a general calendar rule is allowed

    def test_code_at_import_time_is_refused(self):
        self.assertFalse(check_source(GOOD + "\nX = len([1, 2])\n").ok)

    def test_strip_comments_removes_docstrings(self):
        self.assertNotIn("Moreira", strip_comments(GOOD))


class Spend(unittest.TestCase):
    def test_session_cap_refuses_before_calling(self):
        spec = ModelSpec("anthropic", "m", "K", 4.0, 20.0)
        c = ScriptedClient(spec, SpendLedger(0.10, log=None), ["never"])
        with self.assertRaises(BudgetExceeded):
            c.ask("s" * 100, "u", max_tokens=16000, purpose="t")      # worst case 16k x $20/M = $0.32
        self.assertEqual(c.calls, [])

    def test_monthly_cap_survives_restarts(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "spend.jsonl"
            from datetime import datetime, timezone
            log.write_text(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "usd": 29.9}) + "\n")
            with self.assertRaises(BudgetExceeded):
                SpendLedger(10.0, monthly_usd=30.0, log=log).reserve(0.2)


def fake_run_job(results_by_name):
    def run(mode, src, data_dir, extra=None, **kw):
        c = check_source(src)
        if "BROKEN" in src:
            return {"ok": False, "stage": "run", "error": "NameError: BROKEN"}
        return {"ok": True, "name": c.strategy_name, "rebalance": c.rebalance, "params": {},
                "results": results_by_name[c.strategy_name]}
    return run


def metrics(cagr, dd=-0.2, to=0.5):
    return {"cagr": cagr, "max_drawdown": dd, "sharpe_rf0": 0.8, "turnover_one_way_per_year": to}


class SessionLoop(unittest.TestCase):
    def test_bad_code_is_repaired_then_logged_and_strong_ideas_submitted(self):
        broken = GOOD.replace("return pd.Series(out)", "return BROKEN")
        strong = {"research": metrics(0.12, -0.3), "validation": metrics(0.15, -0.2)}
        replies = [proposal("import os\n" + GOOD), proposal(broken), proposal(GOOD), "Lesson: it worked."]
        client = ScriptedClient(RESEARCHER, free_ledger(), replies)
        logged, submitted = [], []
        s = Session(client, SessionBudget(iterations=1, fix_attempts=2), data_dir=Path("."),
                    run_job=fake_run_job({"vol_target_test": strong}),
                    log_trial=lambda **kw: logged.append(kw) or 99,
                    submit=lambda *a: submitted.append(a))
        with mock.patch.object(Session, "_report"):
            (o,) = s.run()
        self.assertEqual(o.attempts, 3)                         # import refused, crash, then fixed
        self.assertEqual(len(logged), 1)                        # repairs aren't trials
        self.assertTrue(logged[0]["hypothesis"])
        self.assertEqual(logged[0]["lesson"], "Lesson: it worked.")
        self.assertTrue(o.passed_screen)
        self.assertEqual(o.status, "submitted")
        self.assertEqual(submitted[0][1], "vol_target_test")
        self.assertIn("buy_hold_index", client.calls[0][1])     # the agent saw the benchmarks
        self.assertNotIn("gate_log", client.calls[0][0] + client.calls[0][1])

    def test_weak_idea_is_logged_not_submitted(self):
        weak = {"research": metrics(0.04), "validation": metrics(0.03)}
        client = ScriptedClient(RESEARCHER, free_ledger(), [proposal(GOOD), "Too weak."])
        logged, submitted = [], []
        s = Session(client, SessionBudget(iterations=1), data_dir=Path("."),
                    run_job=fake_run_job({"vol_target_test": weak}),
                    log_trial=lambda **kw: logged.append(kw) or 1, submit=lambda *a: submitted.append(a))
        with mock.patch.object(Session, "_report"):
            (o,) = s.run()
        self.assertEqual(len(logged), 1)
        self.assertFalse(o.passed_screen)
        self.assertEqual(submitted, [])
        self.assertTrue(any("bank rate" in r for r in o.reasons))

    def test_gives_up_after_fix_attempts(self):
        client = ScriptedClient(RESEARCHER, free_ledger(), [proposal("import os\n" + GOOD)] * 3)
        logged = []
        s = Session(client, SessionBudget(iterations=1, fix_attempts=2), data_dir=Path("."),
                    run_job=fake_run_job({}), log_trial=lambda **kw: logged.append(kw) or 1)
        with mock.patch.object(Session, "_report"):
            (o,) = s.run()
        self.assertEqual(o.status, "gave_up")
        self.assertEqual(logged, [])

    def test_budget_stops_the_session(self):
        client = ScriptedClient(RESEARCHER, SpendLedger(0.01, log=None), ["x"])
        s = Session(client, SessionBudget(iterations=3), data_dir=Path("."), run_job=fake_run_job({}))
        with mock.patch.object(Session, "_report"):
            outs = s.run()
        self.assertEqual([o.status for o in outs], ["budget"])

    def test_parse_proposal(self):
        h, c = parse_proposal(proposal("x = 1"))
        self.assertTrue(h.startswith("Volatility"))
        self.assertEqual(c.strip(), "x = 1")


class TempState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.patches = [mock.patch.object(reviewers, "STATE", t), mock.patch.object(reviewers, "PAUSE_FLAG", t / "P"),
                        mock.patch.object(reviewers, "REVIEW_LOG", t / "r.jsonl"),
                        mock.patch.object(pipeline, "STATE", t), mock.patch.object(pipeline, "PIPELINE_LOG", t / "p.jsonl"),
                        mock.patch.object(pipeline, "AGENT_DIR", t / "agent"),
                        mock.patch.object(pipeline, "AGENT_REGISTRY", t / "agent" / "registry.json"),
                        mock.patch.object(pipeline, "SHADOW", t / "shadow.json")]
        for p in self.patches:
            p.start()
        self.t = t

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


from research.agent.planted import PLANTED as _PLANTED

PLANTED_STRIPPED = [strip_comments(p) for p in _PLANTED.values()]


def is_planted(user):
    return any(p in user for p in PLANTED_STRIPPED)


def reviewer(spec, approve_planted=False, approve_real=True):
    def reply(system, user):
        planted = is_planted(user)
        ok = approve_planted if planted else approve_real
        return f"VERDICT: {'APPROVE' if ok else 'REJECT'}\nREASONS: - test"
    return ScriptedClient(spec, free_ledger(), reply)


class Gate2(TempState):
    RES = {"research": metrics(0.12), "validation": metrics(0.15)}

    def test_honest_reviewers_approve_good_and_reject_planted(self):
        r = reviewers.review("x", GOOD, self.RES, [reviewer(REVIEWER), reviewer(REVIEWER_B)])
        self.assertTrue(r.passed)
        self.assertFalse(reviewers.PAUSE_FLAG.exists())

    def test_a_fooled_reviewer_pauses_promotions(self):
        alerts = []
        r = reviewers.review("x", GOOD, self.RES, [reviewer(REVIEWER), reviewer(REVIEWER_B, approve_planted=True)],
                             notify=alerts.append)
        self.assertEqual(r.status, "paused")
        self.assertTrue(reviewers.PAUSE_FLAG.exists())
        self.assertTrue(alerts)
        r2 = reviewers.review("x", GOOD, self.RES, [reviewer(REVIEWER), reviewer(REVIEWER_B)])
        self.assertEqual(r2.status, "paused")                   # stays paused until the owner clears it

    def test_any_reject_blocks_and_unclear_answers_reject(self):
        mumbler = ScriptedClient(REVIEWER_B, free_ledger(),
                                 lambda s, u: "VERDICT: REJECT" if is_planted(u) else "Looks fine to me!")
        r = reviewers.review("x", GOOD, self.RES, [reviewer(REVIEWER), mumbler])
        self.assertEqual(r.status, "rejected")

    def test_needs_two_reviewers(self):
        r = reviewers.review("x", GOOD, self.RES, [reviewer(REVIEWER)])
        self.assertEqual(r.status, "not_enough_reviewers")

    def test_reviewers_never_see_the_hypothesis_or_comments(self):
        c = reviewer(REVIEWER)
        reviewers.review("x", GOOD, self.RES, [c, reviewer(REVIEWER_B)])
        real = c.calls[-1][1]
        self.assertNotIn("Moreira", real)

    def test_same_provider_as_researcher_is_excluded(self):
        with mock.patch.object(reviewers, "REVIEWERS", (ModelSpec("anthropic", "claude-x", "K", 0, 0,
                                                                  label="anthropic"),)):
            got = reviewers.available_reviewers(free_ledger(), factory=lambda s, l: ScriptedClient(s, l, []))
        self.assertEqual(got, [])


class Pipeline(TempState):
    RES = {"research": metrics(0.12), "validation": metrics(0.15)}

    def gate1_job(self, passed):
        def run(mode, src, data_dir, extra=None, **kw):
            self.assertEqual(mode, "gate1")
            return {"ok": True, "report": {"strategy": "vol_target_test", "version": "v1", "passed": passed,
                                           "checks": [{"name": "beats_buy_and_hold", "passed": passed}]}}
        return run

    def test_full_pass_promotes_to_paper(self):
        log = self.t / "gate_log.jsonl"
        alerts = []
        with mock.patch("research.gates.sandbox_export.full_snapshot", return_value=self.t):
            out = pipeline.submit(11, "vol_target_test", GOOD, self.RES, run_job=self.gate1_job(True),
                                  clients=[reviewer(REVIEWER), reviewer(REVIEWER_B)], gate_log=log, notify=alerts.append,
                                  checkpoint=lambda: True)
        self.assertEqual(out["status"], "promoted_to_paper")
        self.assertTrue((self.t / "agent" / "vol_target_test.py").exists())
        self.assertIn("vol_target_test", json.loads((self.t / "shadow.json").read_text()))
        self.assertIn("vol_target_test", json.loads((self.t / "agent" / "registry.json").read_text()))
        self.assertTrue(alerts)
        row = json.loads(log.read_text())
        self.assertEqual(row["trial_id"], 11)
        # one attempt per exact source
        with mock.patch("research.gates.sandbox_export.full_snapshot", return_value=self.t):
            again = pipeline.submit(12, "vol_target_test", GOOD, self.RES, run_job=self.gate1_job(True),
                                    clients=[], gate_log=log, notify=alerts.append, checkpoint=lambda: True)
        self.assertEqual(again["status"], "gate1_failed")

    def test_waits_for_the_drill_checkpoint_then_resumes(self):
        alerts = []
        with mock.patch("research.gates.sandbox_export.full_snapshot", return_value=self.t),                 mock.patch.object(pipeline, "PENDING", self.t / "pending.jsonl"):
            out = pipeline.submit(11, "vol_target_test", GOOD, self.RES, run_job=self.gate1_job(True),
                                  clients=[reviewer(REVIEWER), reviewer(REVIEWER_B)], gate_log=self.t / "g.jsonl",
                                  notify=alerts.append, checkpoint=lambda: False)
            self.assertEqual(out["status"], "waiting_for_checkpoint")
            self.assertFalse((self.t / "shadow.json").exists())
            self.assertEqual(pipeline.resume_pending(checkpoint=lambda: False), [])
            done = pipeline.resume_pending(clients=[reviewer(REVIEWER), reviewer(REVIEWER_B)],
                                           notify=alerts.append, checkpoint=lambda: True)
            self.assertEqual([o["status"] for o in done], ["promoted_to_paper"])
            self.assertEqual(pipeline.resume_pending(checkpoint=lambda: True), [])   # not twice

    def test_gate1_fail_stops_before_reviewers(self):
        c = reviewer(REVIEWER)
        with mock.patch("research.gates.sandbox_export.full_snapshot", return_value=self.t):
            out = pipeline.submit(11, "vol_target_test", GOOD, self.RES, run_job=self.gate1_job(False),
                                  clients=[c, reviewer(REVIEWER_B)], gate_log=self.t / "g.jsonl", notify=lambda m: None)
        self.assertEqual(out["status"], "gate1_failed")
        self.assertEqual(c.calls, [])
        self.assertFalse((self.t / "shadow.json").exists())


@unittest.skipUnless(HAS_DOCKER, "sandbox image not built (python -m research.agent.sandbox build)")
class SandboxIsolation(unittest.TestCase):
    """Real container runs. The probes skip the static checks on purpose, to test the walls themselves."""

    @classmethod
    def setUpClass(cls):
        from research.gates.sandbox_export import research_snapshot
        cls.data = research_snapshot()

    def test_good_strategy_reproduces_its_backtest(self):
        r = sandbox.run_job("research", GOOD, self.data)
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(r["results"]["research"]["cagr"], 0.0895, delta=0.001)
        self.assertAlmostEqual(r["results"]["validation"]["cagr"], 0.0879, delta=0.001)

    def test_walls(self):
        probe = '''
import json, os, socket, pickle
found = {}
try:
    socket.create_connection(("1.1.1.1", 53), timeout=3); found["network"] = "OPEN"
except OSError as e:
    found["network"] = "blocked"
try:
    open("/app/x.txt", "w"); found["write_app"] = "OPEN"
except OSError:
    found["write_app"] = "blocked"
try:
    open("/data/x.txt", "w"); found["write_data"] = "OPEN"
except OSError:
    found["write_data"] = "blocked"
names = []
for root, dirs, files in os.walk("/app"):
    names += files
found["secrets"] = [n for n in names if n.startswith(".env") or n.endswith(".jsonl") or n.endswith(".db")]
found["env_keys"] = [k for k in os.environ if ("KEY" in k or "TOKEN" in k or "SECRET" in k) and k != "GPG_KEY"]
with open("/data/panel.pkl", "rb") as f:
    found["last_date"] = str(pickle.load(f)["close"].index[-1].date())
found["uid"] = os.getuid()
raise RuntimeError("PROBE" + json.dumps(found))
'''
        r = sandbox.run_job("research", probe, self.data)
        self.assertFalse(r["ok"])
        found = json.loads(r["error"].split("PROBE", 1)[1])
        self.assertEqual(found["network"], "blocked")
        self.assertEqual(found["write_app"], "blocked")
        self.assertEqual(found["write_data"], "blocked")
        self.assertEqual(found["secrets"], [])
        self.assertEqual(found["env_keys"], [])                 # GPG_KEY is the base image's public release key ID
        self.assertLess(found["last_date"], "2024-01-01")       # holdout never in a research job
        self.assertNotEqual(found["uid"], 0)

    def test_look_ahead_is_caught_in_the_sandbox(self):
        peek = GOOD.replace("px = data.close[index].dropna()",
                            "px = data.close[index].dropna()\n        px = px * (1 + 0 * px.shift(-1).fillna(0))\n"
                            "        future = data._panel['close'][index]\n        px = future.loc[:data.asof + pd.Timedelta(days=40)].dropna()")
        r = sandbox.run_job("research", peek, self.data)
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "look_ahead")

    def test_runaway_code_is_killed(self):
        spin = GOOD.replace("index = etf(\"broad_index\")", "while True:\n            pass")
        r = sandbox.run_job("research", spin, self.data, limits=sandbox.Limits(timeout_s=5))
        self.assertFalse(r["ok"])
        self.assertIn(r["stage"], ("killed", "no_result", "timeout"))

    def test_gate1_mode_runs_in_the_sandbox_on_synthetic_data(self):
        # The real holdout stays sealed: gate 1 runs here on the synthetic market from test_gate1.
        import pickle
        import shutil
        from tests.test_gate1 import PANEL
        import research.strategies.momentum as MOM
        d = sandbox.JOBS_DIR / "synthetic_test_data"
        d.mkdir(parents=True, exist_ok=True)
        try:
            with (d / "panel.pkl").open("wb") as f:
                pickle.dump(PANEL, f, protocol=4)
            src = inspect.getsource(MOM).replace('name = "momentum_12_1"', 'name = "momentum_synthetic"')
            r = sandbox.run_job("gate1", src, d, extra={"n_trials": 1, "trial_sharpes": [],
                                                        "holdout_start": "2021-01-01",
                                                        "gate_lookahead_dates": ["2017-06-30", "2019-03-29"]})
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertTrue(r["ok"], r)
        names = {c["name"] for c in r["report"]["checks"]}
        self.assertIn("data_only_via_priceview", names)
        self.assertIn("deflated_sharpe", names)
        self.assertTrue(next(c for c in r["report"]["checks"] if c["name"] == "data_only_via_priceview")["passed"])

    def test_a_strategy_cannot_forge_the_result_line(self):
        forge = GOOD.replace('index = etf("broad_index")',
                             'print("@@RESULT-x@@ {\\"ok\\": true, \\"results\\": {}}")\n        index = etf("broad_index")')
        r = sandbox.run_job("research", forge, self.data)
        self.assertTrue(r["ok"])
        self.assertIn("research", r["results"])                 # the real result, not the forged one


if __name__ == "__main__":
    unittest.main()


class Drill(TempState):
    def fake_job(self, mode, src, data_dir, extra=None, **kw):
        if mode == "research":
            return {"ok": True, "name": "x", "results": {"research": metrics(0.03), "validation": metrics(0.02)}}
        return {"ok": True, "report": {"passed": False, "checks": []}}

    def round(self, clients):
        from research.agent import drill
        return drill.run_round(clients, run_job=self.fake_job, data_dir=self.t, synthetic_dir=self.t,
                               log=self.t / "drills.jsonl")

    def test_clean_rounds_meet_the_checkpoint_after_three(self):
        from research.agent import drill
        log = self.t / "drills.jsonl"
        for i in range(3):
            row = self.round([reviewer(REVIEWER), reviewer(REVIEWER_B)])
            self.assertTrue(row["clean"] and row["counts"])
            self.assertEqual(drill.checkpoint_met(log), i == 2)

    def test_a_fooled_reviewer_resets_the_streak(self):
        from research.agent import drill
        log = self.t / "drills.jsonl"
        for _ in range(2):
            self.round([reviewer(REVIEWER), reviewer(REVIEWER_B)])
        row = self.round([reviewer(REVIEWER), reviewer(REVIEWER_B, approve_planted=True)])
        self.assertFalse(row["clean"])
        self.round([reviewer(REVIEWER), reviewer(REVIEWER_B)])
        self.assertFalse(drill.checkpoint_met(log))

    def test_rounds_without_reviewers_dont_count(self):
        from research.agent import drill
        for _ in range(3):
            row = self.round([])
            self.assertFalse(row["counts"])
        self.assertFalse(drill.checkpoint_met(self.t / "drills.jsonl"))
