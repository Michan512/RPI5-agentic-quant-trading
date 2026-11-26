# Agentic Quant Trading System

A research project exploring whether LLM agents can do useful quantitative research: writing, backtesting and refining trading strategies, while only plain, tested code ever makes trading decisions.

> **Status:** early development, Stage E (see below). Paper trading only. No live money is traded by this code, and no performance claims are made.

> **Disclaimer:** this is a personal learning project, not financial advice. Nothing here is a recommendation to buy or sell any security. Use at your own risk.

## Idea

Most "AI trading bot" projects let a language model decide trades directly. This project takes a different approach:

- **LLMs act as quant researchers, not traders.** They write strategy code and test it; they never place or choose trades.
- **Every strategy must pass three gates** before it can trade: fixed statistical checks (including a locked holdout period and a penalty for the number of strategies tried), independent reviewer agents, and a forward paper-trading period.
- **Research and trading are separated by machine.** Research runs on a PC with no broker access; a Raspberry Pi 5 runs only approved strategies, with a fixed risk layer and hard loss limit.

## Staged plan

| Stage | Who researches | Goal |
| --- | --- | --- |
| **E** | Nobody: published rules | Build the platform; implement benchmark strategies (momentum, trend, low volatility, buy-and-hold) |
| **D** | Me, with AI coding help | Build the research workflow, trial log and first promotion gate |
| **B** | Autonomous research agent | Automate research; reviewer agents and fixed gates decide what's promoted |

Each stage works on its own, so if a later stage never beats an earlier one, the system still runs.

## Architecture

```
PC (research, sandboxed, no broker keys)
  researcher → backtests → candidate strategy
        ↓
  Gate 1: fixed checks → Gate 2: reviewer agents
        ↓
Raspberry Pi 5 (live, broker keys, no LLM access)
  Gate 3: paper period → live engine + risk layer → broker (paper)
```

## Design principles

- **No look-ahead.** Features for day T use only data available before day T's open, and every strategy is tested for this automatically.
- **Costs always included.** Backtests apply fees, slippage and next-open execution.
- **Honest evaluation.** Strategies are judged by returns after costs against buy-and-hold, not by prediction accuracy.
- **Safety outside the model.** Position limits, turnover caps, drawdown pauses and a hard loss limit are enforced in code that no agent can change.

## Repository layout

```
research/     # PC: data, fixed backtest engine, strategies, trial log, gates
live/         # Pi: live engine, risk layer, broker adapter, ledger
shared/       # strategy interface and config used by both
legacy/       # earlier XGBoost prototype, kept for reference
tests/
```

*Layout is being built during Stage E and may change.*

## Setup

Requires Python 3.11+.

```bash
git clone <this repo>
cd <repo>
pip install -r requirements.txt
cp .env.example .env   # add Alpaca PAPER keys only
```

Price data is downloaded locally and is not included in this repository.

## Tech

Python, pandas/numpy, XGBoost, Qlib, alpaca-py (paper trading), SQLite, Raspberry Pi 5. See [TECH_STACK.md](TECH_STACK.md) for what each piece does, the key design decisions and results.

## Built with AI assistance

Planning and much of the code were developed with Claude and Claude Code. Design decisions, review and testing are my own.

## License

MIT. See [LICENSE](LICENSE).
