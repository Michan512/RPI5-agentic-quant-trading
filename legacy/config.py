"""
Configuration and hyperparameter settings for the trading system.
"""

import os
from pathlib import Path

# ── Project paths ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
MODEL_SAVE_PATH = MODELS_DIR / "trading_model.pt"

# ── Data settings ──────────────────────────────────────────────────────────
DEFAULT_TICKERS = [
    "AAPL", "MSFT", "NVDA", "SPY", "GOOGL",
    "AMZN", "META", "TSLA", "JPM", "V",
    "JNJ", "WMT", "PG", "XOM", "UNH",
    "HD", "MA", "BAC", "DIS", "NFLX",
]
DATA_PERIOD_YEARS = 10

# ── Feature engineering ────────────────────────────────────────────────────
SMA_SHORT = 10
SMA_LONG = 50
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_PERIOD = 20
BB_STD = 2
ATR_PERIOD = 14
STOCH_K_PERIOD = 14
STOCH_D_PERIOD = 3

# ── Training hyperparameters ──────────────────────────────────────────────
TRAIN_SPLIT = 0.8
BATCH_SIZE = 128
LEARNING_RATE = 5e-4
EPOCHS = 60
HIDDEN_DIM_1 = 256
HIDDEN_DIM_2 = 128
HIDDEN_DIM_3 = 64
DROPOUT = 0.3

# ── Alpaca paper-trading ───────────────────────────────────────────────────
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
BUY_THRESHOLD = 0.55          # minimum P(UP) to trigger a buy
CASH_ALLOCATION = 1.0         # fraction of available cash to deploy (1.0 = 100%)

# ── Schedule (Eastern Time) ───────────────────────────────────────────────
MORNING_CUTOFF_HOUR = 10      # run buys if current ET hour < this
AFTERNOON_START_HOUR = 15     # run sells if current ET hour >= this
