---
name: AAATS Locked Doctrine 2026-05-14 (CURRENT TRUTH)
description: Final doctrine — $100 initial live, $50/mo conditional injection, 5 gates, kill triggers, BTC DCA companion. Supersedes 2026-05-10 personal-business framing.
type: project
originSessionId: 886226a1-3cb4-4e12-a8e2-6340b049c64e
snapshot_from_cowork_memory: 2026-05-21
---
# AAATS Doctrine — Locked 2026-05-14

**Supersedes:** `aaats_personal_business_framing.md` (2026-05-10).
The earlier "one-time $500-2000 injection after 9 proof criteria" framing is OBSOLETE.

## Capital plan (locked)

- Total monthly capital available to allocate: **$50/mo**
- Recommended split: **$25/mo BTC DCA + $25/mo bot injection** (hybrid)
- Bot starting capital: **$110** (already committed paper)
- Initial live capital after Phase 0 passes: **$100**

## Phase 0 — Foundation (PREREQUISITE, NOT OPTIONAL)

Must complete before ANY live trading.
- Source-of-truth fix: pick canonical state, reconcile DB / state files / OMS
- Bind-mount `scripts/` into container (no more `docker cp` hot-fixes)
- Unify the two compose projects (`/home/aaats/aaats/deployment/` vs `/srv/aaats/compose/`)
- Verify C5b funding arb actually runs (currently invisible in logs)
- Build walk-forward backtest harness against actual DB
- Integration tests for cleanup scripts and reconciler
- ML model offline calibration (precision/recall curve, walk-forward)

## Paper success criteria (locked, must ALL pass to enter Phase 1)

- ≥ 30 closed trades
- Trailing 30-day Sharpe > 0
- Max drawdown < 15%
- C5b carry sleeve net-positive over the period

## Phase 1 — Live shadow ($100 capital, 90+ days)

- Live $100 + paper running in parallel for same 90 days
- End condition: 90 days **AND** ≥ 30 closed live trades (whichever comes later)
- Live vs paper PnL must track within 10% (>10% divergence = execution problem)

### Phase 1 exit gates
- **Scale**: trailing 90-day Sharpe > 0.8 AND divergence < 10% → start $25/mo bot injection (per gates below)
- **Continue at $100**: Sharpe 0-0.8 → another 90 days at $100, no injection
- **Kill**: Sharpe < 0 OR live drawdown > 25% OR live/paper divergence > 20%

## Monthly injection gates (Phase 2+)

ALL must pass each month for injection to fire:
1. ≥ 90 days live trading completed
2. ≥ 30 total closed trades
3. Trailing 3-month Sharpe-based multiplier:
   - Sharpe > 1.5 AND positive → 1.5× baseline ($37.50)
   - Sharpe 0.5–1.5 AND positive → 1.0× baseline ($25)
   - Sharpe 0.0–0.5 OR flat ±2% → 0.5× baseline ($12.50)
   - Return -5% to 0% → 0.25× baseline ($6.25)
   - Return < -5% → ZERO
4. Portfolio within 10% of all-time high water mark (else ZERO)
5. Cap: max 1.5× baseline per month

## Kill triggers (apply at any phase, halt and investigate, no injection)

- Portfolio drawdown > 25% from peak
- 60 days with zero net positive closed trades
- Live PnL > 15% below paper PnL over rolling 30 days
- C5b funding arb sleeve net-negative over 90 days

## Architecture scope (calibrated to $50/mo)

### IN (year 1)
- Foundation work (Phase 0)
- C5b funding arbitrage (carry sleeve, 60% gross)
- C3 → C5a perpetual mean reversion at maker fees (alpha sleeve, 30%)
- ML confidence scorer (probability-weighted sizing per locked schedule)
- Regime classifier (HMM, simple 4-state)

### DEFERRED (year 2+, portfolio > $1k)
- C1 BTC/ETH stat-arb (needs $1k+ for clean minimum order sizes)
- Per-sleeve drawdown circuit breakers

### LIKELY NEVER (wrong tools for capital tier)
- Multi-venue routing (Binance + OKX + Bybit)
- C2 momentum
- C4 listings
- Options sleeve
- Cross-chain DeFi yield

## Operational caps

- **Opex**: $15/mo max until portfolio > $2k (Contabo current ~$6-15/mo)
- **Time investment**: 2-4 hours/week max (Phase 0 excepted — one-time investment)
- **Bot's job at this scale**: beat BTC DCA on Sharpe over 3-5 years, not maximize raw return

## Critical operational rules

- NEVER go live until source-of-truth fix verified
- NEVER override the 5 injection gates (especially Gate 4 — drawdown)
- NEVER inject during a >10% drawdown
- NEVER use the old `deploy_to_contabo.py` — only the v2 patched version
- Use Tailscale IP 100.95.126.39 only — public ports stay closed
- Paper bot only until Phase 1; no real money on broken foundation
