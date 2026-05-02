"""Tests for safety.live_safety_lock module."""

import json
import tempfile
from pathlib import Path

import pytest

from safety.live_safety_lock import LiveSafetyLock, SafetyLockStatus


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def safety_lock(temp_data_dir):
    """Create a LiveSafetyLock instance with temp directory."""
    return LiveSafetyLock(data_dir=temp_data_dir)


def test_safety_lock_initialization(safety_lock):
    """Test safety lock initializes correctly."""
    assert safety_lock.MIN_READINESS_SCORE == 85.0
    assert safety_lock.MIN_PAPER_TRADING_DAYS == 30
    assert safety_lock.MIN_PAPER_SHARPE == 1.0


def test_check_safety_lock_locked_by_default(safety_lock):
    """Test safety lock is locked by default (no approvals)."""
    decision = safety_lock.check_safety_lock("us")
    
    assert decision.status == SafetyLockStatus.LOCKED
    assert not decision.allowed
    assert "manual_approval" in decision.checks_passed
    assert not decision.checks_passed["manual_approval"]


def test_grant_manual_approval(safety_lock):
    """Test granting manual approval."""
    safety_lock.grant_manual_approval(
        market="us",
        approved_by="Test User",
        reason="Test approval",
    )
    
    # Check approval file was created
    approval_file = Path(safety_lock.data_dir) / "live_trading_approval.json"
    assert approval_file.exists()
    
    # Check approval data
    data = json.loads(approval_file.read_text())
    assert "us" in data
    assert data["us"]["approved"] is True
    assert data["us"]["approved_by"] == "Test User"
    assert data["us"]["reason"] == "Test approval"


def test_revoke_manual_approval(safety_lock):
    """Test revoking manual approval."""
    # First grant approval
    safety_lock.grant_manual_approval(
        market="us",
        approved_by="Test User",
        reason="Test approval",
    )
    
    # Then revoke it
    safety_lock.revoke_manual_approval(
        market="us",
        revoked_by="Test User",
        reason="Test revocation",
    )
    
    # Check approval was removed
    approval_file = Path(safety_lock.data_dir) / "live_trading_approval.json"
    data = json.loads(approval_file.read_text())
    assert "us" not in data


def test_set_override(safety_lock):
    """Test setting manual override."""
    safety_lock.set_override(
        reason="Emergency test",
        authorized_by="Test User",
    )
    
    # Check override file was created
    override_file = Path(safety_lock.data_dir) / "safety_override.json"
    assert override_file.exists()
    
    # Check override data
    data = json.loads(override_file.read_text())
    assert data["by"] == "Test User"
    assert data["reason"] == "Emergency test"
    assert "timestamp" in data


def test_clear_override(safety_lock):
    """Test clearing manual override."""
    # First set override
    safety_lock.set_override(
        reason="Emergency test",
        authorized_by="Test User",
    )
    
    # Then clear it
    safety_lock.clear_override()
    
    # Check override file was removed
    override_file = Path(safety_lock.data_dir) / "safety_override.json"
    assert not override_file.exists()


def test_override_allows_trading(safety_lock):
    """Test that override allows trading even without other approvals."""
    # Set override
    safety_lock.set_override(
        reason="Emergency test",
        authorized_by="Test User",
    )
    
    # Check safety lock
    decision = safety_lock.check_safety_lock("us")
    
    assert decision.status == SafetyLockStatus.OVERRIDE
    assert decision.allowed
    assert decision.override_by == "Test User"


def test_decision_saved_to_file(safety_lock):
    """Test that decisions are saved to file."""
    safety_lock.check_safety_lock("us")
    
    # Check decision file was created
    lock_file = Path(safety_lock.data_dir) / "safety_lock_state.json"
    assert lock_file.exists()
    
    # Check decision data
    data = json.loads(lock_file.read_text())
    assert "status" in data
    assert "allowed" in data
    assert "reason" in data
    assert "checks_passed" in data


def test_grant_approval_all_markets(safety_lock):
    """Test granting approval for all markets."""
    safety_lock.grant_manual_approval(
        market="all",
        approved_by="Test User",
        reason="Test approval",
    )
    
    # Check all markets were approved
    approval_file = Path(safety_lock.data_dir) / "live_trading_approval.json"
    data = json.loads(approval_file.read_text())
    
    for market in ["us", "india", "crypto"]:
        assert market in data
        assert data[market]["approved"] is True
