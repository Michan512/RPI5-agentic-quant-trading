# Algorithmic Trading System

## Project Structure

```
trading_system/
├── CLAUDE.md              # This file – project overview
├── config.py              # Central configuration & hyperparameters
├── requirements.txt       # Python dependencies
├── data/
│   ├── fetcher.py         # Download OHLCV data via yfinance
│   └── *.csv              # Raw price data (generated)
├── models/
│   └── trading_model_xgb.json  # Saved XGBoost model (generated)
├── training/
│   ├── dataset.py         # Feature engineering & train/val split
│   ├── train_model.py     # XGBoost training loop
│   └── retrain.py         # Incremental data refresh + re-training
└── execution/
    └── alpaca_client.py   # Alpaca paper-trading skeleton
```

## Setup

```bash
cd trading_system
pip install -r requirements.txt
```

For Alpaca integration, create a `.env` file with:
```
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
```

## Running the Training Pipeline

### 1. Fetch historical data
```bash
python data/fetcher.py              # Downloads all default tickers
python data/fetcher.py AAPL         # Download a single ticker
```

### 2. Train the model
```bash
python training/train_model.py          # Train on all available tickers
python training/train_model.py AAPL     # Train on AAPL only
```

The training script fits an XGBoost classifier on CPU with early stopping.
Progress (validation log-loss per round, accuracy, and the top feature
importances) is printed to the terminal.
The trained model is saved to `models/trading_model_xgb.json`.

## Maintenance

Markets only produce new bars on trading days, so the database and model are
best refreshed at the end of the trading week — run the re-training pipeline
**after the market close on Friday (or over the weekend)**:

```bash
python training/retrain.py
```

This script:

1. Reads the last date in each existing CSV under `data/` (the 20 stocks,
   SPY, and VIX) and downloads any missing daily bars up to today, appending
   them to the historical CSVs.
2. Regenerates the strictly-causal features over the expanded dataset.
3. Re-trains the XGBoost model and overwrites `models/trading_model_xgb.json`
   with the updated version.

It is safe to re-run: tickers that are already current are skipped, and
duplicate dates are de-duplicated on append.

## Key Configuration

XGBoost hyperparameters (set in `training/train_model.py`):

| Parameter               | Default | Description                          |
|-------------------------|---------|--------------------------------------|
| `n_estimators`          | 300     | Maximum number of boosting rounds    |
| `max_depth`             | 5       | Maximum tree depth                   |
| `learning_rate`         | 0.05    | Boosting step size (shrinkage)       |
| `subsample`             | 0.8     | Row sampling fraction per tree       |
| `colsample_bytree`      | 0.8     | Feature sampling fraction per tree   |
| `min_child_weight`      | 5       | Minimum child weight (regularization)|
| `early_stopping_rounds` | 20      | Stop if val log-loss stalls          |

Data split (set in `config.py`):

| Parameter     | Default | Description                     |
|---------------|---------|---------------------------------|
| `TRAIN_SPLIT` | 0.8     | Fraction of data used for train |

## Notes

- The target variable is binary: 1 if today's close > yesterday's close, else 0.
- All features are strictly causal: indicators are computed as-of the prior
  day's close and shifted forward, so row T uses only information available
  before the market opens on day T (see `training/dataset.py`).
- Features are scaled with `StandardScaler` (fitted on the training set only).
