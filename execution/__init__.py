"""
Execution module.

The live trading path imports submodules directly (e.g.
`from execution.paper_trader import record_trade`); this package exposes no
top-level re-exports. The institutional execution cluster (smart order router,
adaptive engine, quality tracker, OMS, fill_model, etc.) was removed
2026-06-13 as never-wired dead code (AUDIT/repo_audit_2026-06-13.md).
"""
