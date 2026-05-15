#!/usr/bin/env python3
"""
safe_write.py — Atomic file writer for AAATS dev workflow.

Replaces the bash heredoc pattern which causes truncation + duplicate-append
bugs on OneDrive-synced folders.

HOW IT WORKS
------------
1. Content is written to a sibling temp file first.
2. For .py files: ast.parse() validates syntax before touching the target.
3. os.replace() atomically swaps temp → target (single syscall, no partial state).
4. A second syntax check verifies the final file on disk.

USAGE
-----
This script is called by Claude (sandbox) — you do NOT need to run it manually.
Claude uses it internally via a Python write-script pattern:

    # Claude writes a temp script, then calls it:
    python3 /tmp/write_foo.py   # generates content + calls safe_write()

If you ever need to call it yourself from PowerShell (here-string syntax):
    @"
    ...full file content...
    "@ | python scripts/safe_write.py path/to/file.py

From Python (importable):
    from scripts.safe_write import safe_write
    safe_write("trading/stat_arb.py", content_string)

All paths validate Python syntax and refuse to write broken code.
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path


def safe_write(dest: str | Path, content: str, validate_python: bool | None = None) -> None:
    """
    Write `content` to `dest` atomically with optional Python syntax validation.

    Args:
        dest:             Target file path.
        content:          Full file content as a string.
        validate_python:  True = always validate, False = skip, None = auto (validate .py files).

    Raises:
        SyntaxError:  If validate_python is True and content doesn't parse.
        OSError:      If the atomic replace fails.
    """
    dest = Path(dest)
    do_validate = (dest.suffix == ".py") if validate_python is None else validate_python

    # 1. Validate BEFORE touching anything on disk
    if do_validate:
        try:
            ast.parse(content)
        except SyntaxError as e:
            raise SyntaxError(
                f"safe_write: syntax error in content for {dest} — "
                f"file NOT written.\n{e}"
            ) from e

    # 2. Write to a temp file in the same directory (same filesystem = atomic rename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dest.parent, prefix=".sw_", suffix=dest.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(content)

        # 3. Atomic replace
        os.replace(tmp_path, dest)

    except Exception:
        # Clean up temp file if something went wrong before/during replace
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # 4. Verify final file on disk
    if do_validate:
        final = dest.read_text(encoding="utf-8")
        try:
            ast.parse(final)
        except SyntaxError as e:
            raise RuntimeError(
                f"safe_write: post-write syntax check FAILED for {dest}. "
                f"File may be corrupt.\n{e}"
            ) from e

    lines = content.count("\n")
    print(f"[safe_write] OK  {dest}  ({lines} lines)", file=sys.stderr)


def main() -> None:
    """CLI entry: python scripts/safe_write.py <dest_path> < content"""
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(
            "Usage: python scripts/safe_write.py <dest_path> < content\n"
            "       (reads full file content from stdin)\n"
            "\n"
            "Example replacing a heredoc:\n"
            "    python scripts/safe_write.py trading/stat_arb.py << 'EOF'\n"
            "    ...full python content...\n"
            "    EOF\n",
            file=sys.stderr,
        )
        sys.exit(1 if len(sys.argv) != 2 else 0)

    dest = sys.argv[1]
    content = sys.stdin.read()

    if not content.strip():
        print(f"[safe_write] ERROR: stdin was empty — refusing to write {dest}", file=sys.stderr)
        sys.exit(1)

    try:
        safe_write(dest, content)
    except (SyntaxError, RuntimeError, OSError) as e:
        print(f"[safe_write] FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
