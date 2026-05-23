"""
D.6 — Ratchet CI gate for silent-except + loguru-printf lints.

The repo has 273 historical hits across these two rules (counted 2026-05-23).
Rather than block this session on fixing all of them, the gate records the
current count in ``tools/lint/silent_except_baseline.txt`` and fails only if
the live count INCREASES. That gives the future sessions a forcing function:
new violations get caught at PR time; cleanup is encouraged (when a count
drops, the baseline file is updated downward).

To suppress a single line: append ``# noqa: silent-except`` or
``# noqa: loguru-printf`` to the offending line. The doctrine-correct
audit/alert paths are already annotated.
"""

from __future__ import annotations

import re
from pathlib import Path

from tools.lint.silent_except import REPO_ROOT, lint_paths


_BASELINE_PATH = REPO_ROOT / "tools" / "lint" / "silent_except_baseline.txt"


def _parse_baseline() -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in _BASELINE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([\w-]+)\s*:\s*(\d+)$", line)
        assert m, f"bad baseline line: {line!r}"
        counts[m.group(1)] = int(m.group(2))
    return counts


def test_lint_baseline_not_exceeded() -> None:
    """Hit counts per rule must be <= the baseline. New violations fail.
    Cleanup (lower count) prints a friendly message asking you to lower
    the baseline; it does not fail the test."""
    hits = lint_paths([REPO_ROOT])
    live: dict[str, int] = {}
    for h in hits:
        live[h.rule] = live.get(h.rule, 0) + 1

    baseline = _parse_baseline()
    failures = []
    suggested_downgrades = []
    for rule, ceiling in baseline.items():
        current = live.get(rule, 0)
        if current > ceiling:
            # Show up to 10 offending lines so the diff fix is obvious.
            offenders = [h for h in hits if h.rule == rule]
            offenders.sort(key=lambda h: (str(h.path), h.line))
            offender_list = "\n  ".join(h.render() for h in offenders[-10:])
            failures.append(
                f"[{rule}] {current} hits live, baseline locked at {ceiling}.\n"
                f"  Add `# noqa: {rule}` if doctrine-correct, otherwise fix.\n"
                f"  Most recent (sorted) offenders:\n  {offender_list}"
            )
        elif current < ceiling:
            suggested_downgrades.append(
                f"[{rule}] live={current} < baseline={ceiling} — "
                f"please lower the baseline in tools/lint/silent_except_baseline.txt"
            )

    # Surface unknown rules (someone added a new rule without baseline-ing it).
    for rule, count in live.items():
        if rule not in baseline:
            failures.append(
                f"[{rule}] {count} hits but no baseline entry. Add a line to "
                f"tools/lint/silent_except_baseline.txt with the current count."
            )

    if failures:
        raise AssertionError("\n\n".join(failures))

    if suggested_downgrades:
        # Print, don't fail — cleanup should be celebrated, not punished.
        print("\n".join(suggested_downgrades))
