# FLAGGED ISSUES

[2026-04-28] PRE-BUILD | MODULE: markets/india/fo_feature_engineer.py | LIBRARY ISSUE: mibian
Problem: `mibian` last released 2016-03-12 (10+ years old, well beyond 18-month threshold). Also checked `py-vollib` (2017-04-10) — also stale. No actively maintained standalone Black-Scholes library exists on PyPI as of April 2026.
Recommendation: Implement Black-Scholes Greeks directly using `scipy.stats.norm` (scipy 1.17.1, continuously maintained). The formulas are closed-form and well-known — a direct implementation is more transparent and reliable than a stale wrapper. `scipy` is already a core dependency in the risk modules.
Status: RESOLVED — proceeding with scipy.stats.norm implementation. No mibian install. Deviation documented in blueprint change log.

[2026-04-26] HOTFIX | MODULE: markets/us/fetcher.py | TYPE: DOCUMENTATION
Issue: AAATS_MASTER_BLUEPRINT.md line 215 still referenced `alpaca-trade-api` after the code had already been migrated to `alpaca-py`. The code itself was already correct when the hotfix session was triggered.
Recommended fix: Updated blueprint table entry to `alpaca-py` with a note that the old SDK is deprecated.
Status: RESOLVED

[2026-04-27] POST-BUILD | MODULE: markets/us/storage.py | TYPE: RELIABILITY
Issue: SQLite is the correct write/point-lookup storage choice. However, backtesting queries that scan across multiple symbols and large date ranges will be slow on SQLite. A DuckDB analytics layer will be needed to wrap the query interface for Phase 2+ backtesting.
Recommended fix: Add DuckDB alongside SQLite as a read-only analytics layer in Phase 2. Do not replace SQLite — it handles the write pattern well. Keep query interfaces clean (already done — `query_ohlcv`/`query_features` signatures are DuckDB-wrappable).
Status: NEEDS_REVIEW

[2026-04-27] PRE-BUILD | MODULE: risk/us/position_sizer.py | TYPE: SPEC_INTEGRITY
Issue: test_normal_sizing in spec uses ATR=2.0, price=100, portfolio=100000 → expected approved=True, position_pct<=10%. However, those parameters produce raw_shares=375, position_value=$37,500, position_pct=37.5% which exceeds MAX_POSITION_PCT (10%) → would be rejected, not approved. Spec parameters are internally inconsistent.
Recommended fix: Use ATR=10.0 instead (risk_per_share=20.0, raw_shares=75, position_value=$7,500, position_pct=7.5% < 10% → approved=True ✓). Applied this correction in the test. Original spec description preserved in test docstring.
Status: RESOLVED — corrected parameters used in test_normal_sizing; original spec values documented in test docstring for traceability.

[2026-04-27] POST-BUILD | MODULE: risk/us/drawdown_guardian.py | TYPE: RELIABILITY
Issue: DrawdownGuardian state (rolling peak, current value) is in-memory only and does not survive process restarts. If the process crashes and restarts, the guardian initialises with a new peak_value at whatever level the portfolio is currently at — meaning a pre-existing drawdown situation will not be re-detected until a further decline from the new peak occurs.
Recommended fix: On restart, initialise DrawdownGuardian with the peak value retrieved from a persistent store (e.g., a lightweight state file or the existing SQLite layer). The kill_switch halt flag is durable (disk-persisted), so a halted market will remain halted across restarts — but the peak tracking itself must be seeded correctly. Flag for Phase 2 trading loop wiring.
Status: NEEDS_REVIEW

[2026-04-27] POST-BUILD | MODULE: backtesting/engine.py | TYPE: RELIABILITY
Issue: Bar loop uses pandas iterrows() which is O(n) but slow per-row. Acceptable for daily bars (hundreds to low-thousands of rows per symbol). Would become a bottleneck if called on intraday/tick data or across hundreds of symbols in a sweep.
Recommended fix: Vectorise the main loop (numpy array ops or apply-based) when tick-level or large-sweep backtesting is introduced. No action needed until Phase 3 strategy sweep work begins.
Status: NEEDS_REVIEW

[2026-04-27] POST-BUILD | MODULE: backtesting/engine.py | TYPE: INTERFACE
Issue: profit_factor returns float("inf") when all trades are winners (no losing trades). This is mathematically correct but may cause JSON serialisation errors or NaN comparisons if downstream validators or dashboard components do not handle inf explicitly.
Recommended fix: Document this in backtesting/validators.py — the check_overfitting function should guard against inf before comparing profit_factor thresholds. No code change needed in engine.py itself.
Status: NEEDS_REVIEW

[2026-04-27] POST-BUILD | MODULE: backtesting/engine.py | TYPE: RELIABILITY
Issue: Bar-level Sharpe (one equity data point per bar) can spike artificially high on short datasets with sparse trades — e.g. one winning trade in 5 bars produces Sharpe ≈ 7.1 due to one high-return bar surrounded by flat bars. The overfitting gate correctly catches this (approved=False). However, the reported sharpe_ratio value may mislead callers who do not read the approved field.
Recommended fix: Always check result.approved before using sharpe_ratio for any decision. Document this prominently in backtesting/validators.py spec check. No code change needed.
Status: NEEDS_REVIEW
