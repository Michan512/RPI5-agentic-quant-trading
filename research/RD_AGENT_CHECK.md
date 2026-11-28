# RD-Agent check (Step 0, item 4): report only, nothing installed

Date: 2026-11-27. Proposal, "Verify in week 1": *Read RD-Agent's requirements: operating system, Docker, supported model providers, and whether it can target US data. If it can't, stage B uses a custom agent on Qlib instead.*

Sources: [GitHub README](https://github.com/microsoft/RD-Agent), [PyPI](https://pypi.org/project/rdagent/), [installation and configuration](https://rdagent.readthedocs.io/en/latest/installation_and_configuration.html), [Finance Quant Agent](https://rdagent.readthedocs.io/en/latest/scens/quant_agent_fin.html), [Finance Data Agent](https://rdagent.readthedocs.io/en/latest/scens/data_agent_fin.html), [R&D-Agent-Quant paper](https://arxiv.org/abs/2505.15155).

## Answers

| Question | Answer | Fit for this project |
|---|---|---|
| Operating system | Linux only; Windows users are pointed to WSL2. | OK: WSL2 Ubuntu 24.04 is already on the laptop. |
| Python | 3.10 and 3.11 are tested in CI. | Needs a separate environment: the Qlib venv is 3.12.3. |
| Docker | Needed for "most scenarios" and must run without sudo. The model/quant path can use a local Conda env instead (`MODEL_COSTEER_ENV_TYPE=conda`). | Docker 29.3 is already installed in WSL. Docker is also what the proposal's sandbox needs. |
| Model providers | LiteLLM backend, so any LiteLLM provider. Set in `.env` with `CHAT_MODEL`, `EMBEDDING_MODEL` and keys. Needs chat with JSON mode **plus an embedding model**. The docs only show OpenAI, Azure and DeepSeek; Claude isn't mentioned but should work through LiteLLM (untested). | Anthropic has no embedding model, so a second provider (e.g. OpenAI embeddings) is needed anyway. That fits the proposal's "each from a different provider". |
| US data | **Not documented.** The quant templates hard-code `provider_uri: ~/.qlib/qlib_data/cn_data`, `market: csi300`, `benchmark: SH000300`, and the data must already exist locally. Train/valid/test dates can be set by env vars (`QLIB_FACTOR_*`, `QLIB_MODEL_*`). | Possible only by editing its templates to point at our own Qlib export (`research/data/qlib_export.py`, which already leaves out the holdout). Unsupported territory. |
| Hardware / cost | No GPU or RAM requirement stated (uses GPU 0 if present; `n_jobs: 20`). The paper claims its results cost "under $10"; there's no per-session figure. | The laptop is likely enough for factor runs; deep models would be slow without the 4080. |

## The bigger mismatch: what RD-Agent searches for

RD-Agent(Q) mines **factors and ML models for ranking a wide stock universe** (CSI 300, top-50 TopkDropout). This project's evidence points the other way:
- The universe is 19 hand-picked stocks + 18 ETFs. Cross-sectional factor mining needs hundreds of stocks, ideally without survivorship bias, which free data doesn't give us.
- Trial 1 (XGBoost on the 19 stocks) showed no skill beyond the hindsight universe. Every rule that came close was a simple, low-turnover ETF rule.
- RD-Agent judges its own work with **Qlib's** backtest. The proposal requires a fixed engine the agent can't edit, and our gates use our own engine, so every RD-Agent idea would still have to be rewritten in the `Strategy` interface and go through the trial log and gate 1.

## Recommendation (the owner decides before stage B)

1. **Stage B should use a custom agent loop on our own engine, not RD-Agent.** The agent writes `shared.strategy.Strategy` classes in a Docker sandbox (no network, read-only data, time and memory caps). Every run goes through `research.engine.backtest` and `research.trials.log`, and candidates are judged by `research/gates/gate1.py`, now including the data-access scan. This reuses everything already built and tested, and enforces the proposal's rules by construction.
2. **Optional and cheap: try RD-Agent once on its own default China data**, only to learn from its loop design. It would go in a separate Python 3.11 environment in WSL, using the API keys and spend cap of the owner's choosing. It shouldn't be wired into this project.
3. **Still open before stage B** (proposal checklist):
   - Research and reviewer models, each from a different provider. LiteLLM makes switching easy; an embedding provider is needed only if we use RD-Agent.
   - Research frequency and budget. At $5k the target is $250/yr, so quarterly sessions with hard spend caps, or wait until the account is bigger.
   - Whether B is worth building at all, given that nothing has beaten SPY out-of-sample (the proposal's stop-early rule).
