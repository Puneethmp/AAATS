# κ2 — Replay determinism notes

Catalogued as κ2 progresses. Each entry: what was found, its surface, the mitigation.

---

## Known going in (from MIGRATION_PLAN Appendix D + κ1 inventory)

| # | Source | Surface | Mitigation in κ2 |
|---|---|---|---|
| 1 | `random.uniform(0.8, 1.2)` in `execution/adaptive_execution_engine.py` (unseeded) | slippage simulation | `replay.injector` calls `random.seed(42)` inside context; restores state on exit. v5 production behaviour unchanged. |
| 2 | `random.uniform(0.95, 1.0)` in same module (fill_rate) | slippage simulation | same as above |
| 3 | Wall-clock reads | not on the κ2 hot path (regime + features only); deferred to κ5 if needed | `replay.clock` exists for future use |
| 4 | NumPy reduction order | float aggregation | inputs traced via `repr()` of each scalar; no aggregate in baseline today |
| 5 | Python dict iteration order | guaranteed insertion order on 3.7+ | no mitigation needed |

---

## Discovered during κ2 (filled as work proceeds)

(none yet — §8.1 only delivered files, no execution)

---

## Sources NOT yet exercised

- `intelligence/regime/`              — empty placeholders per κ-ι analysis
- `intelligence/strategies/*`         — empty placeholders
- `learning/optimizer.py`             — uses `np.random.default_rng(seed=42)`, already deterministic
- `ml/xgboost_ensemble.py`            — `random_state=42`, already deterministic

These will be folded in once the κ2 framework is proven (§8.4+).

---

## Network-egress surfaces NOT yet patched (§8.2)

The §8.2 injector hardening covers `socket.socket.connect`,
`socket.create_connection`, `requests.adapters.HTTPAdapter.send`,
`requests.get/post`, `urllib.request.urlopen`, sync + async
`ccxt.base.exchange.Exchange.request`, and the v5 entry point
`markets.crypto.fetcher.fetch_ohlcv`. The following surfaces are
**known and intentionally NOT patched yet** — fold in if a future
trace surfaces them:

- `socket.socket.connect_ex` — non-raising variant of `connect`. Returns
  errno instead of raising. Anything probing reachability via `connect_ex`
  bypasses `_socket_guard`.
- `asyncio.open_connection` / `asyncio.BaseEventLoop.create_connection` —
  the asyncio transport layer. Async libraries (aiohttp, async ccxt's
  underlying transport, asyncpg) reach the network through this path,
  not through `socket.socket.connect`. Sync ccxt is covered at the
  Exchange.request layer; async ccxt is also covered at that layer, so
  the practical exposure today is limited.

Discovered or required by §8.4? Add the patches and re-capture the baseline.
