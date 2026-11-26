"""
NYSE trading-day calendar, without extra packages.

Rules: weekends; New Year's Day, MLK Day (from 1998), Presidents' Day, Good
Friday, Memorial Day, Juneteenth (from 2022), Independence Day, Labor Day,
Thanksgiving, Christmas. Saturday holidays move to Friday, Sunday holidays to
Monday, except New Year's Day on a Saturday, which isn't observed. Plus a list
of one-off closures. tests/test_live_calendar.py checks this against real SPY
trading days.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

SPECIAL_CLOSURES = {
    date(2001, 9, 11), date(2001, 9, 12), date(2001, 9, 13), date(2001, 9, 14),
    date(2004, 6, 11),   # Reagan funeral
    date(2007, 1, 2),    # Ford funeral
    date(2012, 10, 29), date(2012, 10, 30),   # Hurricane Sandy
    date(2018, 12, 5),   # G.H.W. Bush funeral
    date(2025, 1, 9),    # Carter funeral
}


def _easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(y, month, day)


def _nth_weekday(y, month, weekday, n):
    d = date(y, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y, month, weekday):
    d = date(y, month + 1, 1) - timedelta(days=1) if month < 12 else date(y, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date | None:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def holidays(y: int) -> set[date]:
    h = set()
    ny = date(y, 1, 1)
    if ny.weekday() != 5:                       # Saturday New Year's isn't observed
        h.add(_observed(ny))
    if y >= 1998:
        h.add(_nth_weekday(y, 1, 0, 3))         # MLK Day
    h.add(_nth_weekday(y, 2, 0, 3))             # Presidents' Day
    h.add(_easter(y) - timedelta(days=2))       # Good Friday
    h.add(_last_weekday(y, 5, 0))               # Memorial Day
    if y >= 2022:
        h.add(_observed(date(y, 6, 19)))        # Juneteenth
    h.add(_observed(date(y, 7, 4)))             # Independence Day
    h.add(_nth_weekday(y, 9, 0, 1))             # Labor Day
    h.add(_nth_weekday(y, 11, 3, 4))            # Thanksgiving
    h.add(_observed(date(y, 12, 25)))           # Christmas
    return h


def is_trading_day(d) -> bool:
    d = pd.Timestamp(d).date()
    return d.weekday() < 5 and d not in holidays(d.year) and d not in SPECIAL_CLOSURES


def trading_days(start, end) -> pd.DatetimeIndex:
    days = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    return pd.DatetimeIndex([d for d in days if is_trading_day(d)])
