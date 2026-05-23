"""
D.6 — Lint sweep for silent exception swallowing and loguru printf-format mistakes.

Two checks bundled (both AST-based, no runtime dependencies):

  1. silent-except: ``except <Type>: pass`` patterns that swallow errors with
     no logging and no propagation. Lines annotated with ``# noqa: silent-except``
     are exempt (the doctrine-correct audit/halt paths).

  2. loguru-printf: loguru log calls using printf-style ``%s`` placeholders
     instead of the structured ``{}`` form. Loguru silently formats wrong
     when given printf-style markers, which suppresses the actual values
     in production logs. The lint catches the printf form before it ships.

Usage:

    python -m tools.lint.silent_except [PATH ...]

Default PATH is the repo root. Exits 0 if no hits, 1 if any hit. The pytest
plugin at ``tests/test_lint_silent_except.py`` calls this on the whole repo
and asserts a fixed allowlist of remaining hits.

Suppression: append ``# noqa: silent-except`` to the ``except`` header line,
or ``# noqa: loguru-printf`` to the call line. The lint reads the whole line
for the marker, so multi-line statements can carry the marker on the line
the lint flags.
"""

from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".rollback",
    "logs",
    "runtime",
    "data",
    "node_modules",
    ".pytest_cache",
}


_LOGURU_METHOD_NAMES = {"trace", "debug", "info", "warning", "error", "critical", "exception", "log"}


@dataclass(frozen=True)
class LintHit:
    rule: str       # "silent-except" or "loguru-printf"
    path: Path
    line: int
    snippet: str

    def render(self, root: Path = REPO_ROOT) -> str:
        try:
            rel = self.path.relative_to(root)
        except ValueError:
            rel = self.path
        # Encode snippet ASCII-safely so Windows cp1252 terminals do not
        # crash on box log lines containing non-ASCII characters.
        snippet = self.snippet.strip().encode("ascii", "replace").decode("ascii")
        return f"{rel}:{self.line}: [{self.rule}] {snippet}"


def _read_source(path: Path) -> tuple[str, list[str]] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return text, text.splitlines()


def _line_has_marker(lines: list[str], lineno: int, marker: str) -> bool:
    """1-indexed line lookup, defensively returns False on out-of-range."""
    if not (1 <= lineno <= len(lines)):
        return False
    return marker in lines[lineno - 1]


def _is_silent_pass(handler: ast.ExceptHandler) -> bool:
    """True iff the except body is exactly `pass` (no logging, no propagation,
    no re-raise). A body containing logging calls is NOT flagged because the
    intent is observable. A body containing only `...` is also flagged."""
    body = handler.body
    if len(body) != 1:
        return False
    only = body[0]
    if isinstance(only, ast.Pass):
        return True
    if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant) and only.value.value is ...:
        return True
    return False


def _is_loguru_call_with_printf(node: ast.Call) -> bool:
    """True iff this is a call like ``log.info("user %s", name)`` with a
    string-literal first arg containing a printf marker. We skip f-strings
    (those are correctly formatted) and skip calls without string-literal
    first args."""
    func = node.func
    if isinstance(func, ast.Attribute):
        method = func.attr
    else:
        return False
    if method not in _LOGURU_METHOD_NAMES:
        return False
    if not node.args:
        return False
    first = node.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return False
    body = first.value
    # Common printf markers — keep the set tight to avoid false positives on
    # logs that legitimately mention "%s" as content.
    if any(tok in body for tok in ("%s", "%d", "%r", "%f", "%i")):
        # Only flag when there are also additional positional args (i.e. the
        # printf placeholders are meant to be substituted, not just mentioned).
        return len(node.args) > 1
    return False


def _walk_module(source: str, lines: list[str], path: Path) -> Iterable[LintHit]:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_silent_pass(node):
            if _line_has_marker(lines, node.lineno, "noqa: silent-except"):
                continue
            snippet = lines[node.lineno - 1] if 1 <= node.lineno <= len(lines) else ""
            yield LintHit(rule="silent-except", path=path, line=node.lineno, snippet=snippet)
        elif isinstance(node, ast.Call) and _is_loguru_call_with_printf(node):
            if _line_has_marker(lines, node.lineno, "noqa: loguru-printf"):
                continue
            snippet = lines[node.lineno - 1] if 1 <= node.lineno <= len(lines) else ""
            yield LintHit(rule="loguru-printf", path=path, line=node.lineno, snippet=snippet)


def iter_python_files(roots: list[Path]) -> Iterable[Path]:
    for root in roots:
        if root.is_file():
            if root.suffix == ".py":
                yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if name.endswith(".py"):
                    yield Path(dirpath) / name


def lint_paths(paths: list[Path]) -> list[LintHit]:
    hits: list[LintHit] = []
    for path in iter_python_files(paths):
        loaded = _read_source(path)
        if loaded is None:
            continue
        source, lines = loaded
        hits.extend(_walk_module(source, lines, path))
    hits.sort(key=lambda h: (str(h.path), h.line))
    return hits


def _main(argv: list[str]) -> int:
    paths = [Path(p) for p in argv[1:]] if len(argv) > 1 else [REPO_ROOT]
    hits = lint_paths(paths)
    for h in hits:
        print(h.render())
    if hits:
        print(f"\n{len(hits)} hit(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
