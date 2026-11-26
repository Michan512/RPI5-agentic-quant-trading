# Mistakes log

Proposal, Stage D item 5: "Keep a list of the mistakes you and the assistant make; it becomes the reviewer agents' checklist in stage B."

Each entry: what went wrong, how it was caught, and the check a reviewer should apply.

| # | Mistake | Caught by | Reviewer check |
|---|---|---|---|
| 1 | **Untradable label** (legacy): "close today > close yesterday" includes the overnight gap, which happens before you can buy at the open. | Step 1 audit | Does the label start at a price you could actually trade at (the next open)? |
| 2 | **Judged by accuracy** (legacy): 55% accuracy said nothing about profit after costs. | Step 1 audit | Is the result returns after costs vs benchmarks, not a prediction score? |
| 3 | **Early stopping on the evaluation set** (legacy): the reported validation score was tuned on itself. | Step 1 audit | Is any data used both to tune and to report? |
| 4 | **Silent model overwrite** (legacy): weekly retraining replaced the live model with no check. | Step 1 audit | Can anything change what trades without a human approval? |
| 5 | **Spliced price adjustments** (legacy fetcher): appending new adjusted bars to old ones mixes adjustment bases after each dividend or split. | Step 4 design | When prices are adjusted, is the history re-checked after corporate actions? |
| 6 | **Raw price levels as features** (legacy): adjusted prices drift over time, so price-level features mean nothing across stocks or years. | Step 7 design | Are features scale-free (ratios, returns, ranks)? |
| 7 | **Comparing with the wrong benchmark**: XGBoost and momentum "beat SPY" only because the universe is hindsight-picked winners. | Step 7 result | For stock pickers: beat equal-weight of the same universe, not just the index. |
| 8 | **Wrong performance assumption** (assistant): estimated the XGBoost run at a few minutes; it took more than 10. Profiling found pandas `stack()` was 95% of the time. | Run was stopped; cProfile | Profile before optimising or promising run times. |
| 9 | **Misleading metric** (assistant): "costs as % of starting cash" looked huge for a strategy that grew 18×. Replaced with annual cost drag. | Reading the report | Is each metric scaled so it can be compared across strategies? |
| 10 | **Test compared the wrong things** (assistant): the parity test compared carried-forward targets with fresh calculations, then compared rebalance days with trade days. Both were test bugs, not engine bugs. | Failing test, investigated before "fixing" the engine | When a test fails, check the test's assumption before changing the code under test. |
| 11 | **Guard false positive** (assistant): a comment mentioning the raw data folder tripped the holdout scan. The comment was reworded; the guard was kept strict. | Holdout scan test | Never loosen a safety check to make a test pass; fix the cause. |
| 12 | **A safety stop looked like a bug**: the live replay "missed" momentum rebalances because the risk layer had correctly paused trading after a 17.6% drawdown. | Investigating the parity failure | Check risk-layer events before assuming the strategy pipeline is broken. |
