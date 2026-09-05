"""Where the documents this copy carries actually are.

Every diagnostic cites a spec by section ("SPEC-report.md 7.1"), and
`AGENT-CONTRACT.md` opens by routing the reader to
`skills/contract-authoring/SKILL.md`. Both are repo-relative, and until #349
neither resolved for anyone who installed rather than cloned: the wheel was the
package and nothing else. Measured against an installed 0.7.6, not inferred
from the build config --

    $ find ~/.local/share/uv/tools/partspec -name 'AGENT-CONTRACT.md'
    $                                        # nothing

-- so the whole agent-facing corpus was reachable only over the network, which
an agent without it cannot do at all.

The wheel now force-includes `docs/` and `skills/` under `_bundled/`, and that
directory is deliberately shaped like the repository root rather than like a
docs folder: a citation reads `docs/SPEC-contract.md` or
`skills/contract-authoring/SKILL.md`, and both resolve verbatim against what
`docs_root()` returns, in an install and in a checkout alike. No citation gets
rewritten for the install, and there is no second spelling of a path to keep in
sync with the first.

Nothing here searches. There are two candidate roots, each confirmed by opening
the entry points rather than by finding a directory of the right name, and
`None` when neither answers. A locator that guessed would be this project's own
thesis failing one level up: `cd "$(partspec --docs)"` must not land somewhere
plausible.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["DOCS_URL", "docs_root"]

DOCS_URL = "https://github.com/heibench/partspec/tree/main/docs"
"""Where the documents are when this copy does not carry them."""

_ENTRY_POINTS = ("docs/AGENT-CONTRACT.md", "skills/contract-authoring/SKILL.md")
"""One per shipped tree, and both are the file a reader is sent to first.

Presence of the directories would not answer the question: `docs/` exists in a
checkout whose `skills/` does not, and a truncated copy of either tree is the
case where a confident path is worse than none.
"""


def _carries_the_documents(root: Path) -> bool:
    return all((root / name).is_file() for name in _ENTRY_POINTS)


def docs_root() -> Path | None:
    """The directory the documents' own relative citations resolve against.

    `None` when this copy carries no documents, which is the caller's cue to
    print `DOCS_URL` and say so rather than to fall back to a guess.
    """
    package = Path(__file__).resolve().parent
    bundled = package / "_bundled"
    if _carries_the_documents(bundled):
        return bundled
    # A checkout, or an editable install of one -- where nothing was copied,
    # because `force-include` runs at build time. This file is
    # `<root>/src/partspec/docs.py`, so the root is two levels up: derived,
    # not searched. Walking parents until something matched would accept an
    # unrelated ancestor that happened to hold both names, and site-packages
    # has a great many ancestors.
    if package.parent.name == "src" and _carries_the_documents(package.parent.parent):
        return package.parent.parent
    return None
