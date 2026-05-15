# Dust-filter log lines use printf-style placeholders against a loguru sink

**Filed:** 2026-05-15
**Severity:** mixed — two DEBUG-level lines were silent; one INFO-level line was emitting literal `%d %.2f` to operators.
**Status:** FIXED 2026-05-15 in the dust-threshold hotfix (`.rollback/2026-05-15_dust_threshold_hotfix/MANIFEST.txt`).
**Related:** P1.4 (same root cause, fixed earlier for the deny-list summary line).

## Update 2026-05-15 — scope expansion

During hotfix validation a *third* instance of the same bug was caught at
[scripts/reconcile_intracycle.py:475-476](scripts/reconcile_intracycle.py#L475-L476) (the `_log.info("reconciler: filtered %d dust drift entries ...")` line). This is INFO-level, so operators *were* seeing literal `%d %.2f` in production logs. It was not in the original filing because the file was grepped only for the dust-filter `_log.debug` calls. All three are now fixed in the same atomic deploy and converted to f-strings.

## Locations (all fixed)

- [scripts/reconcile_intracycle.py:420-423](scripts/reconcile_intracycle.py#L420-L423) — DEBUG, dust filter (residual)
- [scripts/reconcile_intracycle.py:445-448](scripts/reconcile_intracycle.py#L445-L448) — DEBUG, dust filter (drift)
- [scripts/reconcile_intracycle.py:475-476](scripts/reconcile_intracycle.py#L475-L476) — INFO, dust-filtered count summary

```python
_log.debug(
    "dust filter: %s residual_shares=%.6f notional<$%.2f — skip",
    symbol, residual, DUST_TOLERANCE_USD,
)
```

`_log` is `foundation.logger.get_logger(...)`, which returns a **loguru** logger ([foundation/logger.py:42](foundation/logger.py#L42)). Loguru uses `{}` (str.format) placeholders, not `%s`/printf. The positional args after the format string are ignored; the literal `%s/%.6f/%.2f` is what gets emitted if the line is enabled.

## Repro

```python
from foundation.logger import get_logger
log = get_logger("scripts", "reconcile_intracycle")
log.debug("dust filter: %s residual_shares=%.6f notional<$%.2f — skip", "TON/USDT", 0.072, 0.10)
# emits the literal format string with placeholders intact, no values substituted
```

## Fix

Replace `%s/%.6f/%.2f` with `{}` and pass args either positionally or by name:

```python
_log.debug(
    "dust filter: {} residual_shares={:.6f} notional<${:.2f} — skip",
    symbol, residual, DUST_TOLERANCE_USD,
)
```

Same edit at line 445.

## Why this didn't break operations

Both call sites are `_log.debug`; production runs at INFO or higher, so the broken lines never serialize. P1.4 fixed an equivalent bug on the INFO-level deny-list summary; these two debug lines were missed because they don't show up in normal logs.
