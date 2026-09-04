"""Change classification.

Determines whether a pull/merge request contains only *whitespace / alignment*
changes (indentation, spacing, blank lines) versus real *code* changes.

Used by the auto-merge step: whitespace-only PRs can be merged automatically,
while anything with a semantic code change is left for human review.

Heuristic: for every modified file, strip all whitespace from the added and
removed diff lines and compare the resulting sequences. If they match exactly
(ignoring blank lines), the change is whitespace-only.

Caveat: in whitespace-significant languages (e.g. Python), re-indentation can
change program structure while still looking "whitespace-only" to this
heuristic. Because of that, auto-merge is opt-in (``AUTO_MERGE_ENABLED``) and
defaults to off.
"""
from __future__ import annotations
import re
from app.pr_pipeline.state import PRFileDiff

WHITESPACE_ONLY = "whitespace_only"
CODE_CHANGE = "code_change"
EMPTY = "empty"

_WS_RE = re.compile(r"\s+")


def _split_patch(patch: str) -> tuple[list[str], list[str]]:
    """Return ``(removed_lines, added_lines)`` for a unified-diff patch,
    excluding the ``+++`` / ``---`` file headers."""
    removed: list[str] = []
    added: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("-"):
            removed.append(line[1:])
    return removed, added


def _normalized_nonblank(lines: list[str]) -> list[str]:
    """Strip only leading whitespace (indentation) from each line and drop
    blank lines.

    Leading-whitespace-only stripping is intentional: it detects indentation
    changes as whitespace-only while preserving internal whitespace so that
    changes to string literals (e.g. 'hello world' -> 'helloworld') are
    correctly classified as code changes.
    """
    out = []
    for line in lines:
        stripped = line.lstrip()
        if stripped:
            out.append(stripped)
    return out


def classify_change(files: list[PRFileDiff]) -> str:
    """Classify a set of file diffs as :data:`WHITESPACE_ONLY`,
    :data:`CODE_CHANGE`, or :data:`EMPTY`.

    - Added / removed / renamed files always count as a code change.
    - A modified file is whitespace-only when its added and removed lines are
      identical after stripping all whitespace (ignoring blank lines).
    - When a patch is unavailable, the change is treated conservatively as a
      code change (we cannot prove it is safe to auto-merge).
    """
    if not files:
        return EMPTY

    saw_change = False
    for file in files:
        if file.status in {"added", "removed", "renamed"}:
            return CODE_CHANGE
        if not file.patch:
            return CODE_CHANGE

        removed, added = _split_patch(file.patch)
        if not removed and not added:
            continue

        saw_change = True
        if _normalized_nonblank(removed) != _normalized_nonblank(added):
            return CODE_CHANGE

    return WHITESPACE_ONLY if saw_change else EMPTY
