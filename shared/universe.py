"""
The fixed trading universe. Both research and live read this list.

Strategies are rules over this list; they must never name individual tickers
(except the role-based ETFs below, which strategies look up by role).

SURVIVORSHIP / HINDSIGHT WARNING
--------------------------------
These 19 stocks are today's large, successful US companies, chosen in 2026.
Free Yahoo data has no delisted companies, so we cannot rebuild what the
"largest 20 stocks" were in, say, 2007. Any backtest over this list is biased
upwards (we already know these companies survived and grew). Every result
must carry this note until a point-in-time universe is available.
"""

# Single stocks: subject to the per-stock weight cap in shared/limits.py.
STOCKS: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "JPM", "V", "JNJ",
    "WMT", "PG", "XOM", "UNH", "HD",
    "MA", "BAC", "DIS", "NFLX",
)

# ETFs, looked up by role so strategies never hard-code tickers.
ETF_ROLES: dict[str, str] = {
    "broad_index": "SPY",       # S&P 500 ETF: buy-and-hold and trend benchmarks
    "short_bond": "SHY",        # 1-3 year US Treasury ETF: trend strategy's "off" asset
}
ETFS: tuple[str, ...] = tuple(ETF_ROLES.values())

# Tradable = stocks + ETFs.
TRADABLE: tuple[str, ...] = STOCKS + ETFS

# Data-only series (used as features, never traded).
REFERENCE: tuple[str, ...] = ("^VIX",)

ALL_SYMBOLS: tuple[str, ...] = TRADABLE + REFERENCE

SURVIVORSHIP_NOTE = (
    "Survivorship bias: universe is 19 of today's large-cap winners picked in 2026; "
    "free data has no delisted stocks, so stock-picking results are biased upwards."
)


def etf(role: str) -> str:
    """Return the ticker for an ETF role, e.g. etf('broad_index') -> 'SPY'."""
    return ETF_ROLES[role]


def is_stock(ticker: str) -> bool:
    return ticker in STOCKS
