"""
D.0 row 22 (added 2026-05-23 session 6): dead-code resurrection guard.

The legacy ``execution/crypto_runner.py`` and ``execution/india_runner.py``
were deleted 2026-05-15 because their SELL paths recomputed shares as
``round(size_usd / entry_price, 6)`` — a 6-dp rounding that diverged from the
BUY-side rounding and would fire share-equality WARNs on every close. The
files are recoverable from git history but must NOT reappear in the tree.

Sister pattern: any new file that calls ``size_usd / entry_price`` to compute
SELL share counts (instead of reading the actual entry quantity from
positions DB) is the same bug. We grep for the literal expression text and
fail if any non-allowlisted match shows up.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

# Files where the pattern is doctrine-correct (post-mortem analyses,
# rollback baselines, the lint allow file itself, etc.). Add NEW
# entries here only after operator review.
ALLOWED_PATTERN_PATHS = {
    # Rollback baselines preserve the historical record verbatim and must
    # not be modified.
    ".rollback/",
    # Tests that DOCUMENT the dead pattern (this file, and any future
    # regression tests proving the SELL recomputation is buggy).
    "tests/test_dead_code_guard.py",
    # Diagnostic memos that quote the broken pattern.
    "docs/",
}


def _is_allowlisted(path: Path) -> bool:
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    return any(rel.startswith(prefix) or prefix in rel for prefix in ALLOWED_PATTERN_PATHS)


def test_dead_runner_files_not_resurrected() -> None:
    """execution/crypto_runner.py and execution/india_runner.py were
    deleted in commit b03ed11 (2026-05-15). They must NOT come back.
    A new runner needing crypto/india entry-points belongs in
    trading/live_paper_runner.py (the canonical engine)."""
    forbidden = [
        REPO_ROOT / "execution" / "crypto_runner.py",
        REPO_ROOT / "execution" / "india_runner.py",
    ]
    extant = [p for p in forbidden if p.exists()]
    assert not extant, (
        f"dead-code resurrection: {[str(p) for p in extant]} reappeared in "
        f"the tree. These were deleted 2026-05-15 because their SELL share "
        f"recomputation diverged from BUY rounding. If you genuinely need "
        f"this code path, route through trading/live_paper_runner.py instead."
    )


def test_sell_share_recompute_pattern_not_introduced() -> None:
    """Catches the exact failure mode that motivated the file deletions:
    ``round(size_usd / entry_price, 6)`` on a SELL path. The 6-dp rounding
    diverges from BUY-side share quantization (typically 8-dp via the
    exchange's lotSize step) and fires share-equality WARNs.

    Any new code that needs SELL share counts must read the entry quantity
    from positions DB / state files, not recompute from notional."""
    pattern = re.compile(
        r"round\s*\(\s*size_usd\s*/\s*entry_price\s*,\s*6\s*\)"
    )
    hits: list[tuple[Path, int, str]] = []
    for path in REPO_ROOT.rglob("*.py"):
        if _is_allowlisted(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append((path, lineno, line.strip()))
    assert not hits, (
        f"dead-code pattern resurrected:\n"
        + "\n".join(f"  {p.relative_to(REPO_ROOT)}:{ln}: {snip}" for p, ln, snip in hits)
        + "\n\nIf you need SELL share quantities, read them from positions DB; "
        "do NOT recompute from notional with 6-dp rounding."
    )
