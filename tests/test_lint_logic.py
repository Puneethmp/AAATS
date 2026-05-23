"""
Unit tests for tools/lint/silent_except.py's AST checks.

Separate from test_lint_silent_except.py (the repo-wide CI gate) — this
file exercises the rule logic itself on synthetic tmp_path fixtures.
"""

from __future__ import annotations

from pathlib import Path

from tools.lint.silent_except import lint_paths


def _hits_for(tmp_path: Path, source: str) -> list[tuple[str, int]]:
    f = tmp_path / "sample.py"
    f.write_text(source, encoding="utf-8")
    return [(h.rule, h.line) for h in lint_paths([f])]


# ── silent-except detection ─────────────────────────────────────────────────


def test_flags_bare_except_pass(tmp_path: Path) -> None:
    hits = _hits_for(tmp_path, "try:\n    pass\nexcept Exception:\n    pass\n")
    assert ("silent-except", 3) in hits


def test_flags_ellipsis_body(tmp_path: Path) -> None:
    hits = _hits_for(tmp_path, "try:\n    pass\nexcept Exception:\n    ...\n")
    assert ("silent-except", 3) in hits


def test_does_not_flag_logged_except(tmp_path: Path) -> None:
    hits = _hits_for(
        tmp_path,
        "import logging\n"
        "try:\n"
        "    pass\n"
        "except Exception as exc:\n"
        "    logging.warning('boom')\n",
    )
    assert all(r != "silent-except" for r, _ in hits)


def test_does_not_flag_reraise(tmp_path: Path) -> None:
    hits = _hits_for(
        tmp_path,
        "try:\n    pass\nexcept Exception:\n    raise\n",
    )
    assert all(r != "silent-except" for r, _ in hits)


def test_noqa_marker_suppresses_silent_except(tmp_path: Path) -> None:
    hits = _hits_for(
        tmp_path,
        "try:\n    pass\nexcept Exception:  # noqa: silent-except\n    pass\n",
    )
    assert all(r != "silent-except" for r, _ in hits)


# ── loguru-printf detection ─────────────────────────────────────────────────


def test_flags_loguru_printf_with_arg(tmp_path: Path) -> None:
    hits = _hits_for(
        tmp_path,
        "from loguru import logger as log\n"
        "log.info('user %s logged in', 'alice')\n",
    )
    assert ("loguru-printf", 2) in hits


def test_does_not_flag_loguru_brace_format(tmp_path: Path) -> None:
    hits = _hits_for(
        tmp_path,
        "from loguru import logger as log\n"
        "log.info('user {} logged in', 'alice')\n",
    )
    assert all(r != "loguru-printf" for r, _ in hits)


def test_does_not_flag_loguru_fstring(tmp_path: Path) -> None:
    hits = _hits_for(
        tmp_path,
        "from loguru import logger as log\n"
        "name = 'alice'\n"
        "log.info(f'user {name} logged in')\n",
    )
    assert all(r != "loguru-printf" for r, _ in hits)


def test_does_not_flag_string_mentioning_printf_token_no_arg(tmp_path: Path) -> None:
    """A literal '%s' in the message with no extra args is a content mention,
    not a substitution attempt."""
    hits = _hits_for(
        tmp_path,
        "from loguru import logger as log\n"
        "log.info('valid format markers are %s and {} but only one substitutes')\n",
    )
    assert all(r != "loguru-printf" for r, _ in hits)


def test_noqa_marker_suppresses_loguru_printf(tmp_path: Path) -> None:
    hits = _hits_for(
        tmp_path,
        "from loguru import logger as log\n"
        "log.info('user %s', 'alice')  # noqa: loguru-printf\n",
    )
    assert all(r != "loguru-printf" for r, _ in hits)
