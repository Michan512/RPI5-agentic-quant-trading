# legacy/

The original XGBoost day-trader, retired during Stage E Step 3 (2026-11-24). Kept for reference. Nothing here is used by `research/` or `live/`.

| File | Why it was retired |
| --- | --- |
| `CLAUDE.md` | Describes the old project; replaced by the root `CLAUDE.md`. |
| `config.py` | Mixes research, training and broker settings in one file; the proposal splits these into `shared/`, `research/engine/` and `live/`. |
| `live_predict.py` | Daily signal script tied to the old untradable close-to-close label; the live engine is rebuilt later on the Pi. |
| `run_daily.py` | Buy-at-open / sell-everything-at-close orchestrator; conflicts with the target-weights strategy interface. |
| `run_morning.bat`, `run_afternoon.bat` | Windows Task Scheduler wrappers for the old bot; they point at `C:\Users\30939\trading_system`, which no longer exists. |
| `strategy/backtest.py` | Backtester with no next-open execution, no slippage and no holdout; replaced by `research/engine/` (Step 5). |
| `training/dataset.py` | Features + close-vs-previous-close label (includes the overnight gap that can't be traded). Step 7 reuses its feature code with a fixed label. |
| `training/train_model.py` | Judges the model by accuracy/log-loss and early-stops on the validation set it reports on. Step 7 replaces it. |
| `training/retrain.py` | Overwrites the model with no versioning or check. Step 4 reuses its incremental-download logic (`update_ticker`); Step 7 adds versioned models. |
| `models/trading_model_xgb.json` | Model trained on the old label (not committed). |
| `logs/` | Run logs from the old scheduled tasks (not committed). |

`config.py` was changed in one place only: `DATA_DIR` now points to `research/data/raw/`, so the legacy scripts can still find the price CSVs.

Moved out of the old project instead of retired:

- `data/fetcher.py` → `research/data/fetcher.py` (reused with changes in Step 4)
- `execution/alpaca_client.py` → `live/broker/alpaca_client.py`, then retired to `legacy/execution/alpaca_client.py` on 2026-11-25. Its buy-at-open / sell-everything-at-close logic doesn't fit the target-weights design; it was replaced by `live/broker/alpaca_adapter.py`.
