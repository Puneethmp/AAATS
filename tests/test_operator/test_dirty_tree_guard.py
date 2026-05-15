"""Pytest coverage for tools/operator/_dirty_tree_guard.py."""
from __future__ import annotations

import pathlib
import subprocess
from unittest import mock

import pytest

from tools.operator import _dirty_tree_guard as guard


def _fake_check_output(porcelain_out: str):
    """Return a function that mimics subprocess.check_output for git calls."""
    def _runner(args, **kwargs):
        if args[:2] == ["git", "rev-parse"]:
            return "/fake/repo\n"
        if args[:2] == ["git", "status"]:
            return porcelain_out
        raise AssertionError(f"unexpected subprocess call: {args}")
    return _runner


def test_clean_tree_does_not_raise():
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output("")):
        guard.check_clean(["trading/live_paper_runner.py", "scripts/"])  # no raise


def test_dirty_file_in_manifest_raises():
    porcelain = " M trading/live_paper_runner.py\n"
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output(porcelain)):
        with pytest.raises(guard.DirtyTreeError) as exc:
            guard.check_clean(["trading/live_paper_runner.py"])
    assert "trading/live_paper_runner.py" in str(exc.value)
    assert "--allow-dirty" in str(exc.value)


def test_dirty_file_outside_manifest_does_not_raise():
    # Auto-cron paths under runtime/ must NOT trigger the guard.
    porcelain = " M runtime/log.txt\n M data/cache.json\n"
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output(porcelain)):
        guard.check_clean(["trading/live_paper_runner.py", "execution/paper_trader.py"])


def test_allow_dirty_warns_but_does_not_raise(capsys):
    porcelain = " M trading/live_paper_runner.py\n"
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output(porcelain)):
        guard.check_clean(["trading/live_paper_runner.py"], allow_dirty=True)
    captured = capsys.readouterr()
    assert "drift between local repo and the box" in captured.err
    assert "trading/live_paper_runner.py" in captured.err


def test_directory_prefix_match():
    porcelain = " M trading/nested/foo.py\n"
    with mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output(porcelain)):
        with pytest.raises(guard.DirtyTreeError):
            guard.check_clean(["trading/"])


def test_not_a_git_repo_raises():
    def _boom(args, **kwargs):
        raise subprocess.CalledProcessError(128, args)
    with mock.patch.object(subprocess, "check_output", side_effect=_boom):
        with pytest.raises(guard.DirtyTreeError, match="not a git repo"):
            guard.check_clean(["trading/live_paper_runner.py"])
