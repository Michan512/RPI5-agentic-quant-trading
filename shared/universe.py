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

# Broad asset-class ETFs, looked up by role so strategies never hard-code tickers.
# All have traded continuously since 2006 or earlier, so this part of the universe
# has no survivorship bias. Added 2026-11-26 (owner approved). May be held up to 100%.
ETF_ROLES: dict[str, str] = {
    "broad_index": "SPY",       # US large caps (S&P 500)
    "intl_developed": "EFA",    # developed markets outside North America
    "emerging": "EEM",          # emerging markets
    "mid_bond": "IEF",          # 7-10 year US Treasuries
    "long_bond": "TLT",         # 20+ year US Treasuries
    "short_bond": "SHY",        # 1-3 year US Treasuries (the "safe" asset)
    "gold": "GLD",
    "real_estate": "VNQ",       # US REITs
    "commodities": "DBC",       # broad commodity futures
}

# US sector ETFs (Select Sector SPDRs, all since 1998). One sector is a concentrated
# bet, so each is capped like a single stock (owner decision 2026-11-26).
SECTOR_ETFS: tuple[str, ...] = (
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU",
)

ETFS: tuple[str, ...] = tuple(ETF_ROLES.values()) + SECTOR_ETFS

# Tradable = stocks + ETFs.
TRADABLE: tuple[str, ...] = STOCKS + ETFS

# Data-only series (used as features, never traded).
REFERENCE: tuple[str, ...] = ("^VIX",)

ALL_SYMBOLS: tuple[str, ...] = TRADABLE + REFERENCE

SURVIVORSHIP_NOTE = (
    "Survivorship bias: the 19 single stocks are today's large-cap winners picked in 2026 "
    "(free data has no delisted stocks), so stock-picking results are biased upwards. "
    "The ETF part of the universe has traded continuously since 2006 and is not affected."
)


def etf(role: str) -> str:
    """Return the ticker for an ETF role, e.g. etf('broad_index') -> 'SPY'."""
    return ETF_ROLES[role]


def is_stock(ticker: str) -> bool:
    return ticker in STOCKS


def is_sector_etf(ticker: str) -> bool:
    return ticker in SECTOR_ETFS


def etfs(*roles: str) -> list[str]:
    """Tickers for several roles, in order."""
    return [ETF_ROLES[r] for r in roles]
