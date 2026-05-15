# AAATS — 48h Activation Sprint (2026-05-12) — UPDATED

**Goal:** Move from 6-symbol hardcoded watchlist (currently HOLD every cycle) to a scanner-first architecture that evaluates the top 50 most liquid Binance pairs each cycle, picks high-conviction candidates, applies portfolio + correlation + sentiment caps, and trades through C3 (mean reversion) and C6 (Bollinger range) — with C5b funding arb running underneath as the always-on backbone.

**Realistic 48h PnL on $120:** +$0.50 to +$15 best case, ‑$2 to ‑$8 worst. The PnL is small. The actual prize is **15–40 real fills** that produce the training data for the next iteration (real ML scoring, parameter tuning, regime correlation).

---

## What was built (11 files, 3,915 lines total)

### Strategy layer — tuned + new (4 files)

| File | Status | Change |
|---|---|---|
| `trading/funding_arb.py` | tuned | Entry threshold 0.0008 → 0.0004 + fixed missing `import os` + repo-relative state file |
| `trading/altcoin_reversion.py` | tuned + refactored | Z_ENTRY -2.0 → -1.6, Z_HARD_STOP -3.0 → -2.6, added DOT, accepts `symbols=` from scanner |
| `trading/bollinger_range.py` | **NEW** + refactored | Direct-execution mean reversion BTC/ETH/SOL, accepts `symbols=` from scanner |
| `trading/live_paper_runner.py` | rewired | Full scanner pipeline + sentiment gates + cluster guard wired into `run_crypto()` |

### Scanner pipeline — new (3 files)

| File | Lines | Purpose |
|---|---|---|
| `markets/crypto/universe.py` | 231 | Dynamic top-N Binance spot fetcher. Filters: $5M+ vol, ≤0.15% spread, no stablecoins, no leveraged tokens. 1h cache. Fallback to 15-symbol static list on API failure. |
| `markets/crypto/scanner.py` | 227 | Per-strategy candidate scorer. Computes z-score (C3), %B + RSI (C6) on every universe symbol. Returns ranked candidate list per strategy. |
| `markets/crypto/allocator.py` | 179 | Top-K selector with portfolio caps: MAX_OPEN=6, MAX_PER_STRATEGY=3, MAX_PER_SYMBOL=1, $25 reserved for C5b. |

### Safety overlays — new (3 files)

| File | Lines | Purpose |
|---|---|---|
| `markets/crypto/sentiment.py` | 147 | Fear & Greed gate. Skips C6 at F&G>75 (extreme greed), skips C3 at F&G>85 (euphoria). Size multiplier 0.0–1.3 based on regime. |
| `markets/crypto/correlation_guard.py` | 148 | Cluster cap. 9 clusters (MAJOR/L1_ALT/L2/DEFI/MEME/AI/GAMING/INFRA/OTHER). Max 3 positions per cluster. |
| `markets/crypto/confidence_scorer.py` | 288 | ML-ready scoring scaffold. Rule-based today; same interface accepts XGBoost.predict_proba() post-48h. Returns [0,1] confidence → size multiplier. |

### Validation

All 11 files compile clean in Python 3.10. End-to-end smoke test:
- 15-symbol synthetic universe (mix of oversold/overbought/neutral across clusters)
- Scanner picked 9 c3 + 9 c6 candidates
- Allocator capped to 6 total (3 per strategy)  ✓
- Cluster guard reduced L1_ALT overflow from 5 → 3  ✓
- Confidence scorer: strong-signal fixture → 0.63 (c3) / 0.61 (c6)  ✓
- All 9 cluster mappings correct  ✓
- Exit code 0

---

## Pipeline flow each cycle (15 min)

```
┌─────────────────────────────────────────────────────────────────┐
│  Cycle begins (T+0)                                             │
│  ────────────────                                               │
│                                                                 │
│  1.  run_crypto() — existing ensemble loop on legacy 6 syms     │
│      ↓                                                          │
│  2.  stat_arb_crypto (C1)         — BTC/ETH spread              │
│      ↓                                                          │
│  3.  funding_arb (C5b)            — delta-neutral on BTC/ETH    │
│      ↓                                                          │
│  4.  momentum_breakout (C2)       — BTC/ETH only                │
│      ↓                                                          │
│  ┌─────────────────── NEW: scanner pipeline ──────────────┐     │
│  │ 5. get_liquid_universe(top_n=50)                       │     │
│  │ 6. score_universe(c3, c6) → ranked candidates          │     │
│  │ 7. allocate() → top-K with portfolio caps              │     │
│  │ 8. filter_plan_by_clusters() → cluster caps            │     │
│  │ 9. get_fear_greed() → sentiment skip gates             │     │
│  └────────────────────────────────────────────────────────┘     │
│      ↓                                                          │
│  10. run_altcoin_reversion_crypto(symbols=c3_picks)             │
│  11. run_bollinger_range_crypto(symbols=c6_picks)               │
│      ↓                                                          │
│  12. save state + reconciliation worker (drift detector)        │
│  13. sleep 15 min                                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Deploy command

```powershell
cd C:\Users\udaym\OneDrive\Desktop\Puneeth
python deploy_to_contabo.py
```

The deploy script handles `docker compose down → upload tarball → build → up`. The `INCLUDE` list already covers `trading/`, `scripts/`, `markets/` so all 11 files ship automatically. **No manifest edit needed.**

---

## Post-deploy verification (do within 5 min)

```bash
ssh aaats@100.95.126.39
docker ps --format 'table {{.Names}}\t{{.Status}}'

# Confirm new modules are loaded
docker exec aaats-paper-crypto python -c "
from markets.crypto.universe import get_liquid_universe, MIN_VOLUME_USD
from markets.crypto.scanner import score_universe
from markets.crypto.allocator import allocate, MAX_OPEN_POSITIONS
from markets.crypto.correlation_guard import cluster_of, MAX_PER_CLUSTER
from markets.crypto.sentiment import get_fear_greed
from markets.crypto.confidence_scorer import score_candidate
print('Universe min vol filter:', MIN_VOLUME_USD)
print('Max open positions:', MAX_OPEN_POSITIONS)
print('Max per cluster:', MAX_PER_CLUSTER)
print('Live Binance universe (top 5):', get_liquid_universe(top_n=5))
print('Current F&G:', get_fear_greed())
"
# Expected output:
#   Universe min vol filter: 5000000
#   Max open positions: 6
#   Max per cluster: 3
#   Live Binance universe (top 5): ['BTC/USDT', 'ETH/USDT', ...]
#   Current F&G: <0-100>

# Tail logs for one full cycle (15 min)
docker logs aaats-paper-crypto -f --tail 200
# Look for:
#   [universe] fetched N raw tickers from Binance
#   [universe] kept=50 rejected_by={...} top3=[...]
#   [scanner] universe=50 fetched=48 skipped=2 candidates: c3=K c6=M
#   [scanner] c3 top3: SYM(z), SYM(z), SYM(z)
#   [allocator] capital=$... open=0/6 per_strategy_counts={}
#   [allocator] c3 picks: SYM, SYM
#   [corr_guard] allowed (post-cluster): [...] cluster_load={...}
#   [sentiment] F&G=N (Fear|Neutral|Greed|Extreme Greed)
#   [scanner] final plan: c3=[...] c6=[...] fg=N skip_c3=False skip_c6=False
#   [c3] SYM/USDT  z=... price=... regime=...
#   [c6] SYM/USDT  price=... %B=... RSI=... regime=...
```

---

## T+4h / T+12h / T+24h / T+48h checkpoints

**T+4h** — Is the scanner alive?
- Grep logs for `[universe] kept=`. Expect ≥40 (sometimes 30–50 after liquidity filter).
- Grep for `[allocator] c3 picks:` or `c6 picks:` — at least one should be non-empty within 4h unless the market is in absolute dead chop.

**T+12h** — Has anything entered?
- `docker exec aaats-paper-crypto sqlite3 /app/data/paper_trades.db "SELECT strategy, action, COUNT(*) FROM paper_trades GROUP BY strategy, action;"`
- Expect ≥1 entry across C3/C5b/C6. Zero entries = scanner is finding candidates but allocator/sentiment gates are blocking everything. Check `[allocator]` and `[sentiment]` log lines.

**T+24h** — PnL attribution + fee drag check
```sql
SELECT
  strategy,
  COUNT(*)              AS trades,
  SUM(CASE WHEN action='BUY' THEN size_usd ELSE 0 END)  AS deployed,
  SUM(pnl)              AS gross_pnl,
  AVG(pnl_pct)          AS avg_pnl_pct
FROM paper_trades
GROUP BY strategy;
```
Fee-drag rule: if any strategy has `|gross_pnl_pct - net_pnl_pct| > 40% × avg`, downsize 50%.

**T+48h** — Final report
- Per-strategy: trades, win rate, avg winner/loser, gross/net PnL, fee drag, max DD
- Per-cluster: what clusters fired most? Which had best WR?
- Sentiment correlation: did C6 entries during F&G<40 outperform F&G>60?
- **Phase 2 decision:** if all 9 proof-of-concept criteria are green AND net PnL > –$5, inject $1.5k tranche

---

## What gets built AFTER 48h (using the data this sprint produces)

| Build | Trigger | Estimated hours |
|---|---|---|
| Train XGBoost on ≥100 fills, swap into `_rule_score_*()` body | 100+ fills accumulated | 12–20h |
| Add a 2nd sentiment source (BTC.D rate of change, alt season index) | Day 4+ | 4–6h |
| Cross-cycle correlation tracker (rolling 30d return correlation matrix) | Day 5+ | 6–8h |
| Websocket prices replacing REST polling | When we add a momentum/scalping strategy | 8–12h |
| Multi-exchange (Bybit/OKX added to scanner) | Capital ≥ $1k | 12–15h |

---

## Rollback procedure (if scanner causes issues)

The scanner pipeline is wrapped in `try/except` — on ANY exception, it falls back to the strategies' hardcoded SYMBOLS. So a scanner bug doesn't kill the bot, it just disables the scanner for that cycle. To fully roll back:

```bash
ssh aaats@100.95.126.39
cd /home/aaats/aaats
docker compose down

# Remove scanner imports from live_paper_runner.py (sed surgical removal)
python3 -c "
import pathlib
src = pathlib.Path('trading/live_paper_runner.py').read_text()
# Find the scanner block and replace with no-op
# (Easier: just deploy the previous git revision of this file)
"
git checkout HEAD~1 trading/live_paper_runner.py   # or whichever previous commit
docker compose build aaats-paper-crypto && docker compose up -d
```

---

## Operational risks for the 48h window

1. **Scanner picks symbols with no historical OHLCV cache** — first time the bot sees DOGE2/USDT etc., it has to fetch 200 bars. If `fetch_crypto_hourly` is slow, cycle time bloats. Mitigation: cache is warm by T+4h.

2. **F&G API outage** — `get_fear_greed()` returns None on failure, sentiment gates "fail open" (allow trades). Acceptable degradation.

3. **Binance rate limits** — 50-symbol fetch is ~50–100 weight per cycle. Limit is 1200/min on public endpoints. Safe margin. If rate limited, fallback universe (15 hardcoded majors) kicks in.

4. **Cluster mapping drift** — new tokens listed daily won't be in my static cluster table. They map to "OTHER" → effectively no cluster cap. Acceptable for 48h, revisit weekly.

5. **OneDrive truncation** — local edits to >100-line files must use atomic Python write. See `outputs/repair_files.py` / `outputs/patch_dynamic_symbols.py` / `outputs/wire_overlays.py` as templates.

---

## Key log lines for live monitoring

```
✓ [universe] kept=N rejected_by={...}     ← scanner alive
✓ [scanner] c3 top3 / c6 top3              ← candidates found
✓ [allocator] c3 picks / c6 picks          ← allocator selects
✓ [corr_guard] allowed (post-cluster):     ← cluster guard culls
✓ [sentiment] F&G=N (...)                  ← sentiment fetched
✓ [c3] ENTRY / [c6] ENTRY                  ← real entries
✓ Reconciliation clean | checked=N         ← no drift
✗ Scanner pipeline error                   ← falls back to hardcoded; investigate
✗ RECONCILIATION HALTED                    ← STOP, investigate before resume
```
