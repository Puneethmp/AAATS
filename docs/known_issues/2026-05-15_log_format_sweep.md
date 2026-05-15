# Loguru printf-format bug sweep — 2026-05-15

**Status:** filed + patched in the same atomic deploy (`.rollback/2026-05-15_record_fix/`)
**Related:** [2026-05-15_dust_filter_loguru.md](2026-05-15_dust_filter_loguru.md) — the original re-grep that turned up `_log.info("... %d %.2f")` on line 478 of `scripts/reconcile_intracycle.py`; that fix shipped earlier the same day.

## Why this sweep happened

`reconcile_intracycle.py:478` was caught only because the operator re-grepped the file after the first fix. The original audit grepped for the dust-filter `_log.debug` lines specifically and missed an unrelated `_log.info` literal `%d %.2f` line in the same file. Operator concluded the sweep needed to be widened across the whole codebase before assuming it was a one-file problem.

## Logger background

`get_logger(...)` in [foundation/logger.py:15](../../foundation/logger.py#L15) wraps **loguru**. Loguru uses `{}`-style formatting; `%s %d %.2f` placeholders are emitted **verbatim** in the log line. Stdlib `logging.getLogger(__name__)` uses `%`-style formatting and is unaffected. Both conventions co-exist in this codebase, so the sweep had to disambiguate by which factory the logger came from.

## Grep methodology

```bash
# Loguru-bound logger names in this codebase
grep -rn "^_log\s*=\s*get_logger\|^log\s*=\s*get_logger" .

# Then: multiline match of `<loguru_name>.<level>(...%[sdfx])`
grep -rnU -P '_log\.(debug|info|warning|error|critical)\s*\([\s\S]{0,300}?%[sdfx]' . --include='*.py'
```

The `{0,300}` window catches calls that span 5–8 lines (typical for the dust-filter shape and the paper_trader trade-log shape). Anything wider is unusual and unlikely.

## Real bugs found (3 hits, all in execution/paper_trader.py)

| File:line | Level | Message | Operator impact |
|-----------|-------|---------|-----------------|
| [execution/paper_trader.py:169-174](../../execution/paper_trader.py#L169-L174) | WARNING | `"PAPER duplicate suppressed \| cli_id=%s \| prior_trade=%s \| %s %s @ %.4f x%.6f strat=%s"` | YES — fires on every duplicate-suppressed client_order_id |
| [execution/paper_trader.py:212-215](../../execution/paper_trader.py#L212-L215) | WARNING | `"PAPER duplicate race resolved by UNIQUE INDEX \| cli_id=%s \| winner=%s"` | YES — fires on every UNIQUE-INDEX race |
| [execution/paper_trader.py:218-222](../../execution/paper_trader.py#L218-L222) | INFO | `"PAPER %s %s @ %.4f x%.6f \| strat=%s \| regime=%s \| cli=%s \| corr=%s"` | **YES — fires on every successful paper trade.** Trade logs have been emitting literal `%s %s @ %.4f x%.6f` since this file was last touched. |

All three converted to `{}`-style in the 2026-05-15_record_fix deploy. Positional args unchanged (loguru consumes them).

## False positives (confirmed)

| File:line | Why it's not a bug |
|-----------|--------------------|
| [scripts/continuous_runner.py:107](../../scripts/continuous_runner.py#L107) | `%Y-%m-%d %H:%M:%S` inside `strftime()` inside an f-string. `%` is consumed by strftime; loguru never sees it. |
| [scripts/phase1_runner.py:141](../../scripts/phase1_runner.py#L141) | Same shape as above. |
| `logging.getLogger(__name__)` callers (e.g. [execution/smart_order_router.py:20](../../execution/smart_order_router.py#L20), `trading/altcoin_reversion.py:32`, `trading/bollinger_range.py:78`) | Stdlib logging. `%s`-style is the correct convention; loguru is not involved. |

## DEBUG-level hits

None found. (No fixed-deferred backlog from this sweep.)

## Total INFO+ hits

3 — below the operator-set threshold of 10 above which this becomes a logging-discipline conversation rather than a one-shot fix. All three patched in the same atomic SCP as the strategy SELL-shares fix.

## Why this bug class keeps recurring

Most loguru calls in the codebase use the conventional `_log.info(f"... {x} ...")` f-string form, which is unambiguous. The buggy shape — `_log.info("... %s ...", arg)` — looks like stdlib-`logging` style and is the natural shape for anyone who learned Python logging before loguru. Mixed-convention codebase + no linter rule = this will reappear.

**Possible follow-up (not done this session):** add a ruff rule or pre-commit hook that flags `<loguru_name>.<level>(<str-with-%[sdfx]>, ...)` patterns. Not in scope for the 2026-05-15 sprint, but worth a small task in the next planning round.
