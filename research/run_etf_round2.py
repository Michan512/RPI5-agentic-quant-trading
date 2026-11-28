"""
Stage D research, round 2 (trials 6-10): new low-turnover ideas on the ETF universe.

Same procedure as round 1: research and validation only (never holdout), compared
with buy-and-hold SPY and 60/40 over the same windows, each run logged as a trial.

Decision rule, fixed BEFORE the results were seen (2026-11-26): a rule earns a
gate 1 attempt only if, on BOTH research and validation, it beats 60/40 after
costs, beats 5%/yr, its worst fall is no deeper than SPY's (round 1's rule), AND
its turnover is within gate 1's 300%/yr limit.

Running this again with unchanged code does not add duplicate trials.

Usage (from the repo root):
    python -m research.run_etf_round2
"""

from __future__ import annotations

from pathlib import Path

from research.data.loader import load_panel
from research.data.splits import PERIODS
from research.engine.backtest import run_backtest
from research.gates.thresholds import MAX_TURNOVER_ONE_WAY_PER_YEAR
from research.run_etf_round1 import decide as decide_round1
from research.strategies import ETF_ROUND2
from research.strategies.buy_hold import BuyHold
from research.strategies.sixty_forty import SixtyForty
from research.trials.log import _source_hash, log_trial, read_trials, trial_count
from shared.universe import SURVIVORSHIP_NOTE

OUT = Path(__file__).resolve().parent / "trials" / "etf_round2.md"

IDEAS = {
    "inverse_vol_7": "Risk parity lite: the 7 asset-class ETFs weighted by 1/3-month volatility, monthly, always invested.",
    "trend_sixty_forty": "60/40 where the 60% stock slice moves to short Treasuries while SPY is below its 200-day average.",
    "vol_target_15": "Moreira & Muir volatility management: SPY at min(1, 15% / last month's volatility), rest short Treasuries.",
    "sector_momentum_buffer": "Trial 4's sector momentum with a holding buffer: keep a sector while it ranks top 5, to cut turnover.",
    "sector_low_vol": "3 lowest-volatility US sectors over the past year, 25% each, rest short Treasuries.",
}


def decide(res: dict, bench: dict) -> tuple[bool, list[str]]:
    ok, reasons = decide_round1(res, bench)
    for p in PERIODS:
        to = res[p]["turnover_one_way_per_year"]
        if to > MAX_TURNOVER_ONE_WAY_PER_YEAR:
            reasons.append(f"{p}: turnover {to:.0%}/yr above the {MAX_TURNOVER_ONE_WAY_PER_YEAR:.0%} limit")
    return not reasons, reasons


def main() -> None:
    panel = load_panel()
    bench = {p: {b.name: run_backtest(b(), panel, s, e).metrics for b in (BuyHold, SixtyForty)}
             for p, (s, e) in PERIODS.items()}
    logged = {(t["strategy"], t["code_version"]["strategy_source_sha256"]) for t in read_trials()}
    rows = {}
    for name, cls in ETF_ROUND2.items():
        res = {p: run_backtest(cls(), panel, s, e).metrics for p, (s, e) in PERIODS.items()}
        for p in PERIODS:
            res[p]["excess_cagr_vs_sixty_forty"] = res[p]["cagr"] - bench[p]["sixty_forty"]["cagr"]
            res[p]["excess_cagr_vs_buy_hold"] = res[p]["cagr"] - bench[p]["buy_hold_index"]["cagr"]
        ok, reasons = decide(res, bench)
        key = (cls.name, _source_hash(cls))
        if key in logged:
            tid = "already logged"
        else:
            tid = log_trial(cls(), IDEAS[name], res,
                            notes="ETF round 2; decision rule fixed before results: beat 60/40 and 5%/yr, "
                                  "worst fall no deeper than SPY, turnover <= 300%/yr, in both periods.",
                            extra={"earns_gate_attempt": ok, "reasons": reasons})
        rows[name] = (res, ok, reasons, tid)

    pct = lambda x: f"{x:+.1%}"
    lines = ["# Stage D, ETF round 2", "",
             "Research and validation only (holdout sealed). Costs included. Signals at the close, fills at the next open.",
             "", f"Caveat: {SURVIVORSHIP_NOTE}", ""]
    for p, (s, e) in PERIODS.items():
        lines += [f"## {p.capitalize()} ({s.date()} to {e.date()})", "",
                  "| Strategy | CAGR | vs 60/40 | vs SPY | Worst fall | Sharpe | Turnover/yr |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for b in ("buy_hold_index", "sixty_forty"):
            m = bench[p][b]
            lines.append(f"| *{b}* | {pct(m['cagr'])} | | | {m['max_drawdown']:.1%} | {m['sharpe_rf0']:.2f} | "
                         f"{m['turnover_one_way_per_year']:.0%} |")
        for name, (res, ok, reasons, tid) in rows.items():
            m = res[p]
            lines.append(f"| {name} | {pct(m['cagr'])} | {pct(m['excess_cagr_vs_sixty_forty'])} | "
                         f"{pct(m['excess_cagr_vs_buy_hold'])} | {m['max_drawdown']:.1%} | {m['sharpe_rf0']:.2f} | "
                         f"{m['turnover_one_way_per_year']:.0%} |")
        lines.append("")
    lines += ["## Decision (rule fixed before results)", ""]
    for name, (res, ok, reasons, tid) in rows.items():
        lines.append(f"- **{name}** (trial {tid}): {'EARNS a gate 1 attempt' if ok else 'does not qualify'}"
                     + ("" if ok else ": " + "; ".join(reasons)))
    lines += ["", f"Total trials so far: {trial_count()}"]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
