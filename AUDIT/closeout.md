# AAATS Closeout — one page (2026-06-11)

**Book status:** FLAT since 2026-06-11T08:58Z. Entries disabled everywhere
and tripwired. All Phase A deploy verifications PASS with captured evidence
(`AUDIT/deploy_verification.md`); security incident closed except the
operator's rotation/visibility items (`AUDIT/security_closeout.md`).

## Final equity

| | |
|---|---|
| Paper book baseline (2026-05-23 reset) | $200.00 |
| Final equity (flat, 2026-06-11) | **$190.03** |
| Paper PnL of the live program since reset | **−$9.97** (~19 days) |
| No-trade baseline over the same window | $0.00 |
| Honest repriced view (audit window, net of all costs) | gross −$2.27 → net −$13.01 — losses were SIGNAL-dominated, not cost-dominated |
| Live money at any point | $0 traded by the bot (paper only). Ongoing: $25/mo BTC DCA, independent of this system |

**Total cost of the research program:** −$9.97 paper PnL (zero real trading
loss) + infra: one Contabo VPS (≈2.5 months, subscription price not recorded
in-repo) + operator/Claude session time. The remaining asset bought with
that spend: a falsified-hypothesis ledger, a reusable null-controlled
validation harness, and an OI dataset accruing toward the only open thesis.

## The three falsified verdicts

1. **Research engagement (the edge itself), 2026-05-30 → 2026-06-09:** every
   strategy family on free, point-in-time-clean crypto data failed an honest,
   null-controlled, out-of-sample gate — C1/C2/C3/C5b/C6/C7, TSMOM, the
   ensemble (final arbiter: 15-fold walk-forward, indistinguishable from
   random signs), then the reactivation portfolio (T1 economically void, T2
   fail, T4a/b fail, B1 fail) and the Stage-2 information screens (sentiment
   p=0.79, stablecoin flows p=0.26). Terminal; `research/falsified.md`.
2. **Methodology-as-product, 2026-06-09:** no willing-to-pay market for
   third-party strategy falsification — pay-to-hear-"no" exists only where an
   external accountable party (LP, board, regulator) forces the spend, and
   the reachable segment (solo traders) is the one that structurally won't
   buy a verdict on its own ideas. `validation_product_falsification_2026-06-09.md`.
3. **This audit (the live system), 2026-06-10:** the running bot's losses
   were signal-dominated — gross PnL was already negative before a single
   cent of costs, and the ledger had been hiding the costs. The honest
   posture (no-trade) beats every strategy that ever ran. `AUDIT/loss_attribution.md`.

## Current system posture

Unattended research bed in zero-touch maintenance (contract appended to
CLAUDE.md): exit-only runner with a flat book, net-of-cost ledger, three-
condition alert surface (entry tripwire / OI gap / health red), Monday
weekly report on origin/main as the only contact surface, gitleaks gating
every push. The single live research thread is the **T3 OI-positioning
thesis** — hourly collection since 2026-06-06, earliest valid test
**≈ 2027-03-06**, executed per `docs/closeout/T3_REOPEN_CHECKLIST.md` or not
at all. Open operator items: make the repo private; re-key the Angel TOTP
seed, Cloudflare tunnel token, Grafana admin password.

## The sentence

**Every mechanism tried lost to doing nothing — until the T3 data matures
in 2027, the flat book IS the alpha, and every tinker before then can only
spend it.**
