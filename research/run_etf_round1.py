"""
Stage D research, round 1: published low-turnover rules on the ETF universe.

For each rule (T1-T4): backtest on research and validation (never holdout),
compare with buy-and-hold SPY and 60/40 over the same windows, apply the
decision rule fixed BEFORE the results were seen, and log the run as a trial.

Decision rule (plan, 2026-11-26): a rule earns a gate 1 attempt only if, on BOTH
research and validation, it beats 60/40 after costs, beats 5%/yr, and its worst
fall is no deeper than SPY's.

Running this again with unchanged code does not add duplicate trials.

Usage (from the repo root):
    python -m research.run_etf_round1
"""

from __future__ import annotations

import json
from pathlib import Path

from research.data.loader import load_panel
from research.data.splits import PERIODS
from research.engine.backtest import run_backtest
from research.strategies import ETF_ROUND1
from research.strategies.buy_hold import BuyHold
from research.strategies.sixty_forty import SixtyForty
from research.trials.log import _source_hash, log_trial, read_trials, trial_count
from shared.universe import SURVIVORSHIP_NOTE

OUT = Path(__file__).resolve().parent / "trials" / "etf_round1.md"
BANK_RATE = 0.05

IDEAS = {
    "asset_trend_10m": "Faber (2007) GTAA: 7 asset-class ETFs equal weight, each only above its 10-month average, else short Treasuries.",
    "dual_momentum_gem": "Antonacci GEM: hold the stronger of US/international stocks by 12-month return if it beat T-bills, else 7-10y Treasuries.",
    "sector_momentum_top3": "Top 3 US sectors by 12-1 month momentum (25% each, rest short Treasuries) while SPY > 200-day average, else 7-10y Treasuries.",
    "combo_t1_t2_t3": "One third each of asset trend, dual momentum and sector momentum.",
}


def decide(res: dict, bench: dict) -> tuple[bool, list[str]]:
    reasons = []
    for p in PERIODS:
        m, sf, spy = res[p], bench[p]["sixty_forty"], bench[p]["buy_hold_index"]
        if m["cagr"] <= sf["cagr"]:
            reasons.append(f"{p}: CAGR {m['cagr']:.1%} not above 60/40 {sf['cagr']:.1%}")
        if m["cagr"] <= BANK_RATE:
            reasons.append(f"{p}: CAGR {m['cagr']:.1%} not above the 5% bank rate")
        if m["max_drawdown"] < spy["max_drawdown"]:
            reasons.append(f"{p}: worst fall {m['max_drawdown']:.1%} deeper than SPY's {spy['max_drawdown']:.1%}")
    return not reasons, reasons


def main() -> None:
    panel = load_panel()
    bench = {p: {b.name: run_backtest(b(), panel, s, e).metrics for b in (BuyHold, SixtyForty)}
             for p, (s, e) in PERIODS.items()}
    logged = {(t["strategy"], t["code_version"]["strategy_source_sha256"]) for t in read_trials()}
    rows = {}
    for name, cls in ETF_ROUND1.items():
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
                            notes="ETF round 1; decision rule fixed before results: beat 60/40 and 5%/yr, "
                                  "worst fall no deeper than SPY, in both periods.",
                            extra={"earns_gate_attempt": ok, "reasons": reasons})
        rows[name] = (res, ok, reasons, tid)

    pct = lambda x: f"{x:+.1%}"
    lines = ["# Stage D, ETF round 1", "",
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
