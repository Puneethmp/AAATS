# Research Ledger — append-only

One line per registered harness run. The honest count of hypotheses tested.
Append with `python research/log_verdict.py <verdict.json>` (never edit prior rows).

Columns: date | thesis | verdict | pooled-OOS daily Sharpe | null empirical p | worst-fold maxDD | params-hash | verdict JSON

> **Trust note:** every row below was produced under the FLAT-FEE / daily-close
> fill model (asymmetric — false-positive-prone). No row is a trustworthy PASS
> until re-run under the realistic fill model (`basket_ledger.simulate_basket`,
> pending P0). A `verdict=PASS` here means "passed the gate," NOT "edge confirmed."

| date | thesis | verdict | pooled Sharpe | null p | worst DD | params-hash | json |
|---|---|---|---|---|---|---|---|
| 2026-06-06 | T2_xsect_momentum | FAIL | 0.8572 | 0.043 | 0.7388 | d3939b7bbb44 | data/graduation/T2_xsect_momentum_2026-06-06.json |
| 2026-06-06 | T1_funding_dispersion | ECONOMICALLY_VOID | n/a | n/a | n/a | da39837f5853 | data/graduation/T1_funding_dispersion_PRECHECK_2026-06-06.json |
| 2026-06-09 | T4a_funding_timing_contrarian | FAIL | -0.9575 | 0.676 | 0.5032 | 8fbc4fa4b64c | data/graduation/T4a_funding_timing_2026-06-09.json |
| 2026-06-09 | T4b_funding_timing_continuation | FAIL | 0.2502 | 0.05 | 0.3893 | c85ec3676de0 | data/graduation/T4b_funding_timing_2026-06-09.json |
