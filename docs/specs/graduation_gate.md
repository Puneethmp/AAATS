# Graduation Gate — research→live promotion criteria (canonical)

Status: CANONICAL
Authored: 2026-05-27

## Purpose

A strategy validated in a NautilusTrader backtest must clear all seven criteria
(G1–G7) below **on out-of-sample data** before it earns live capital. The gate
is all-or-nothing: failing any single criterion keeps the strategy paper-only,
and the report names exactly which criterion failed and what to fix. This is the
one decision point between research and real money — the PASS report is the only
artifact that authorizes a live-flip.

## Criteria

| Criterion | Threshold | Rationale |
|---|---|---|
| **G1** net PnL after fees | `> 0` | If realistic fees eat the edge, there is no edge — the most basic survival test (see B.1.5 Phase 3: C1 lost on every trade at 50bps). |
| **G2** Sharpe ratio | `>= 1.0` | Risk-adjusted return must justify capital at risk; below 1.0 the return is not reliably distinguishable from noise. |
| **G3** max drawdown | `abs <= 0.20` | Aligns with the -20% portfolio kill threshold; a strategy that breaches its own halt level in backtest will breach it live. |
| **G4** closed trades | `>= 30` | Statistical-significance floor. C6 showed a +8.41 Sharpe on too few trades that proved to be a small-sample artifact (9.7-unit divergence from the 60d harness). |
| **G5** profit factor | `>= 1.3` | Gross profit must exceed gross loss with margin, so a handful of bad fills or a fee uptick does not flip the strategy negative. |
| **G6** OOS/IS degradation | `OOS Sharpe >= 0.5 * IS Sharpe` | Detects overfitting: an edge that halves (or worse) out-of-sample was largely curve-fit. If IS Sharpe ≤ 0 there is no positive edge to degrade from, so G6 passes only when OOS Sharpe ≥ 0. |
| **G7** maker-fill robustness | `net PnL > 0 at prob_fill_on_limit=0.5` | A maker strategy that only profits when every limit fills is fragile; the edge must survive a halving of fill probability. |

## How it's computed

Metrics come from a single NautilusTrader backtest over the out-of-sample
window. `sharpe` and `profit_factor` are read directly from the run's
`PortfolioAnalyzer` (both are built-in statistics). `net_pnl_usd` and
`max_drawdown_pct` come from the engine account / equity curve. The G6 inputs
(`in_sample_sharpe`, `oos_sharpe`) come from two separate runs over the
in-sample and out-of-sample windows. The G7 number (`pnl_at_maker_0_5`) is the
net PnL from re-running the same backtest under `FillModel(prob_fill_on_limit=0.5)`;
the strategy is swept at fill probabilities {1.0, 0.5, 0.2} and the 0.5 level is
the gating point.

## Output

On evaluation, `tools/graduation/gate.py:emit_report` writes
`data/graduation/{strategy}_{YYYY-MM-DD}.json` containing the verdict
(`PASS`/`FAIL`), the full metrics dict, and a per-criterion breakdown
(`actual` / `threshold` / `detail`). A `PASS` report is the **single artifact
authorizing a live-flip decision**; a `FAIL` report documents precisely what
blocked promotion so the next research iteration is targeted.

## Tuning

These thresholds are deliberately conventional starting values and may be tuned
once real graduations accumulate and we can calibrate against live outcomes.
