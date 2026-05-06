"""Invariant: reconciliation-before-close (κ1 req 5b).

A position close after a halt event must be preceded by at least one
reconciliation run for the market. This test exercises the structural
gate `must_reconcile_before_close()`.
"""

from __future__ import annotations

import pytest

from storage.dao import halt as halt_dao
from storage.dao import reconciliation


@pytest.mark.asyncio
async def test_no_halt_history_means_close_allowed(pg):
    ok = await reconciliation.must_reconcile_before_close("crypto")
    assert ok is True


@pytest.mark.asyncio
async def test_halt_without_recon_blocks(pg):
    await halt_dao.append_halt_event(
        market="crypto", action="halt", triggered_by="t", reason="r",
    )
    ok = await reconciliation.must_reconcile_before_close("crypto")
    assert ok is False


@pytest.mark.asyncio
async def test_recon_after_halt_unblocks(pg):
    await halt_dao.append_halt_event(
        market="crypto", action="halt", triggered_by="t", reason="r",
    )
    await reconciliation.record_run(
        market="crypto", db_count=3, broker_count=3,
        drift_symbols=[], warnings=[],
    )
    ok = await reconciliation.must_reconcile_before_close("crypto")
    assert ok is True


@pytest.mark.asyncio
async def test_recon_then_halt_blocks_again(pg):
    await reconciliation.record_run(
        market="crypto", db_count=3, broker_count=3,
        drift_symbols=[], warnings=[],
    )
    await halt_dao.append_halt_event(
        market="crypto", action="halt", triggered_by="t", reason="post-recon halt",
    )
    ok = await reconciliation.must_reconcile_before_close("crypto")
    assert ok is False, "halt after recon must require a fresh recon"


@pytest.mark.asyncio
async def test_market_isolation(pg):
    await halt_dao.append_halt_event(
        market="india", action="halt", triggered_by="t", reason="r",
    )
    # India halted, no recon. Crypto should still be open.
    crypto_ok = await reconciliation.must_reconcile_before_close("crypto")
    india_ok = await reconciliation.must_reconcile_before_close("india")
    assert crypto_ok is True
    assert india_ok is False
