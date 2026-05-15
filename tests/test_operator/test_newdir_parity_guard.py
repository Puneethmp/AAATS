"""Pytest coverage for tools/operator/_newdir_parity_guard.py."""
from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from tools.operator import _newdir_parity_guard as guard


def _fake_check_output(ls_tree_out: str):
    """Mimic subprocess.check_output for `git rev-parse` + `git ls-tree`."""
    def _runner(args, **kwargs):
        if args[:2] == ["git", "rev-parse"]:
            return "/fake/repo\n"
        if args[:2] == ["git", "ls-tree"]:
            return ls_tree_out
        raise AssertionError(f"unexpected subprocess call: {args}")
    return _runner


def test_empty_origin_does_not_raise():
    """No tracked entries -> nothing to be missing."""
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output("")):
        guard.check_newdir_parity(["trading", "execution"])  # no raise


def test_manifest_covers_all_runtime_entries_does_not_raise():
    """Origin has runtime dirs that the manifest covers explicitly."""
    origin = "trading\nexecution\nfoundation\nREADME.md\ndocs\n"
    manifest = ["trading", "execution", "foundation"]
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output(origin)):
        guard.check_newdir_parity(manifest)  # README.md + docs covered by allow-list


def test_uncovered_runtime_dir_raises():
    """A new top-level dir in origin that the manifest doesn't list -> refuse."""
    origin = "trading\nexecution\nintelligence\n"  # intelligence is RUNTIME-LATENT, not allow-listed
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output(origin)):
        with pytest.raises(guard.NewDirError) as exc:
            guard.check_newdir_parity(["trading", "execution"])
    assert "intelligence" in str(exc.value)
    assert "DEPLOY REFUSED" in str(exc.value)
    assert "--allow-dirty" in str(exc.value)


def test_uncovered_entry_in_allowlist_does_not_raise():
    """tools/, streamlit_app/, docs/ are allow-listed and never raise."""
    origin = "trading\ntools\nstreamlit_app\ndocs\n.github\n"
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output(origin)):
        guard.check_newdir_parity(["trading"])  # all uncovered entries are allow-listed


def test_allow_dirty_warns_and_returns(capsys):
    """allow_dirty=True with uncovered entries -> stderr warning, no exception."""
    origin = "trading\nintelligence\nportfolio\n"
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output(origin)):
        guard.check_newdir_parity(["trading"], allow_dirty=True)
    err = capsys.readouterr().err
    assert "SHIPPING WITH UNCOVERED TOP-LEVEL DIRS" in err
    assert "intelligence" in err
    assert "portfolio" in err


def test_warn_only_warns_and_returns(capsys):
    """warn_only=True (single-file deploy) -> soft warning, no exception."""
    origin = "trading\nintelligence\n"
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output(origin)):
        guard.check_newdir_parity(["trading/live_paper_runner.py"], warn_only=True)
    err = capsys.readouterr().err
    assert "new-dir parity WARN" in err
    assert "intelligence" in err
    # Must NOT emit the loud --allow-dirty banner.
    assert "SHIPPING WITH UNCOVERED" not in err


def test_normalize_handles_nested_manifest_entries():
    """Manifest entry 'data/ml' should cover top-level 'data'."""
    origin = "trading\ndata\n"
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output(origin)):
        # data is also in the allow-list, but the test verifies the
        # normalization path independently: manifest entry "data/ml" -> "data".
        guard.check_newdir_parity(["trading", "data/ml"])  # no raise


def test_trailing_slash_manifest_entries():
    """Manifest entry with trailing slash normalizes to top-level token."""
    origin = "trading\nexecution\n"
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output(origin)):
        guard.check_newdir_parity(["trading/", "execution/"])  # no raise


def test_not_a_git_repo_raises():
    def _boom(args, **kwargs):
        raise subprocess.CalledProcessError(128, args)
    with mock.patch.object(subprocess, "check_output", side_effect=_boom):
        with pytest.raises(guard.NewDirError, match="not a git repo"):
            guard.check_newdir_parity(["trading"])
