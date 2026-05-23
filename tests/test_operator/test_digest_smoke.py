"""
Tests for the deploy-time digest drift assertion (tools/operator/_digest_smoke.py).

The check should:
  - Pass vacuously when the in-container state file is missing.
  - Pass when the state file exists AND the digest renders a real equity number.
  - FAIL with a specific diagnostic when the state file exists but the digest
    renders N/A (the session-5 volume-mount-gap drift it is built to catch).
  - Robust to docker-exec returncode 1 (test -s returns 1 on missing file).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from tools.operator._digest_smoke import (
    assert_digest_renders_equity,
    equity_line_is_na,
    parse_equity_line,
)


@dataclass
class _StubResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _runner(script: dict[str, _StubResult]) -> Callable[[str], _StubResult]:
    """Build a runner that looks up the substring of a command and returns
    the matched stub result. Last-defined key wins on overlap."""
    def _run(cmd: str) -> _StubResult:
        for key, val in script.items():
            if key in cmd:
                return val
        raise AssertionError(f"unexpected command: {cmd!r}")
    return _run


# ── Equity-line parser ──────────────────────────────────────────────────────


def test_parse_equity_line_finds_real_value() -> None:
    body = (
        "AAATS daily digest -- 2026-05-23\n"
        "\n"
        "P&L (24h)\n"
        "  Realized:   $+1.20\n"
        "  Unrealized: $+0.00\n"
        "  Equity:     $110.50  (peak $131.32, dd -15.9%)\n"
    )
    assert parse_equity_line(body) == "$110.50  (peak $131.32, dd -15.9%)"


def test_parse_equity_line_finds_na() -> None:
    body = (
        "P&L (24h)\n"
        "  Equity:     N/A  (peak N/A, dd N/A)\n"
    )
    assert parse_equity_line(body) == "N/A  (peak N/A, dd N/A)"
    assert equity_line_is_na(parse_equity_line(body) or "")


def test_parse_equity_line_returns_none_when_missing() -> None:
    assert parse_equity_line("no equity line here") is None


# ── End-to-end smoke ────────────────────────────────────────────────────────


_GOOD_DIGEST = (
    "AAATS daily digest -- 2026-05-23\n\n"
    "P&L (24h)\n"
    "  Realized:   $+1.20\n"
    "  Unrealized: $+0.00\n"
    "  Equity:     $87.45  (peak $131.32, dd -33.4%)\n"
)

_NA_DIGEST = (
    "AAATS daily digest -- 2026-05-23\n\n"
    "P&L (24h)\n"
    "  Realized:   $+0.00\n"
    "  Unrealized: $+0.00\n"
    "  Equity:     N/A  (peak N/A, dd N/A)\n"
)


def test_smoke_passes_when_state_missing_and_digest_is_na() -> None:
    run = _runner({
        "test -s": _StubResult(returncode=1, stdout="STATE_MISSING\n"),
    })
    res = assert_digest_renders_equity(run)
    assert res.ok
    assert "STATE_MISSING".lower() in res.message.lower() or "does not exist" in res.message


def test_smoke_passes_when_state_present_and_digest_renders_equity() -> None:
    run = _runner({
        "test -s": _StubResult(returncode=0, stdout="STATE_PRESENT\n"),
        "monitoring.daily_digest": _StubResult(returncode=0, stdout=_GOOD_DIGEST),
    })
    res = assert_digest_renders_equity(run)
    assert res.ok
    assert "$87.45" in res.equity_line


def test_smoke_fails_when_state_present_but_digest_is_na() -> None:
    """This is THE bug session 5 hit. The smoke check MUST flag it."""
    run = _runner({
        "test -s": _StubResult(returncode=0, stdout="STATE_PRESENT\n"),
        "monitoring.daily_digest": _StubResult(returncode=0, stdout=_NA_DIGEST),
    })
    res = assert_digest_renders_equity(run)
    assert not res.ok
    assert "volume-mount" in res.message or "mount" in res.message
    assert res.equity_line.startswith("N/A")


def test_smoke_fails_on_digest_nonzero_exit() -> None:
    run = _runner({
        "test -s": _StubResult(returncode=0, stdout="STATE_PRESENT\n"),
        "monitoring.daily_digest": _StubResult(
            returncode=2, stdout="", stderr="ImportError: monitoring.daily_digest",
        ),
    })
    res = assert_digest_renders_equity(run)
    assert not res.ok
    assert "non-zero" in res.message
    assert "ImportError" in res.message


def test_smoke_fails_when_digest_lacks_equity_line() -> None:
    """If the digest's render format ever changes such that 'Equity:' is
    no longer in the body, the smoke check fails loudly rather than
    silently letting the deploy through."""
    run = _runner({
        "test -s": _StubResult(returncode=0, stdout="STATE_PRESENT\n"),
        "monitoring.daily_digest": _StubResult(
            returncode=0, stdout="some unexpected output without the marker",
        ),
    })
    res = assert_digest_renders_equity(run)
    assert not res.ok
    assert "Equity:" in res.message or "render format" in res.message


def test_smoke_custom_mode_and_path() -> None:
    """Live mode uses a different state-file path."""
    received: list[str] = []

    def _capture_run(cmd: str) -> _StubResult:
        received.append(cmd)
        if "test -s" in cmd:
            return _StubResult(returncode=0, stdout="STATE_PRESENT\n")
        return _StubResult(returncode=0, stdout=_GOOD_DIGEST)

    res = assert_digest_renders_equity(_capture_run, mode="live")
    assert res.ok
    assert any("state-live/risk_engine_state.live.json" in c for c in received), (
        f"expected the probe to reference the live state file path; saw: {received}"
    )
