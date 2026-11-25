"""
THE single definition of the research / validation / holdout periods.

- DATA_START .. RESEARCH_START is warm-up history only (strategies may look back
  into it, but no returns are measured there).
- Research:    where ideas are developed and backtested freely.
- Validation:  checked only after something looks promising on research.
- Holdout:     the most recent ~3 years. Locked: research/data/loader.py refuses
               to return any row on or after HOLDOUT_START unless the caller is
               code inside research/gates/. Nothing else may read it.

Changing these dates after results have been seen defeats the purpose.
Do not edit them to "fit" a result.
"""

import pandas as pd

DATA_START = pd.Timestamp("2006-01-01")

RESEARCH_START = pd.Timestamp("2007-01-01")
RESEARCH_END = pd.Timestamp("2019-12-31")

VALIDATION_START = pd.Timestamp("2020-01-01")
VALIDATION_END = pd.Timestamp("2023-12-31")

HOLDOUT_START = pd.Timestamp("2024-01-01")   # open-ended: runs to the latest data

PERIODS: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {
    "research": (RESEARCH_START, RESEARCH_END),
    "validation": (VALIDATION_START, VALIDATION_END),
}

# The latest date non-gate code is allowed to see.
LAST_VISIBLE_DATE = VALIDATION_END

assert DATA_START < RESEARCH_START <= RESEARCH_END < VALIDATION_START <= VALIDATION_END < HOLDOUT_START
