"""AGENT-CONTRACT.md makes executable claims; this holds them to the code.

The document tells an agent what each exit code means, quotes the tool's own
message fragments, and names flags and fields. A contract document that
drifts from the tool teaches the agent wrong behaviour with full confidence —
the same defect class as a spec drifting from its own example, guarded the
same way.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from support import needs_scad_tier

from partspec.status import EXIT_USAGE, Verdict, exit_code

DOC = (Path(__file__).resolve().parents[1] / "docs" / "AGENT-CONTRACT.md").read_text()
DOC_FLAT = re.sub(r"\s+", " ", DOC)
"""Prose wraps at the margin; claims are checked against flattened text."""
SRC = Path(__file__).resolve().parents[1] / "src" / "partspec"


def test_the_exit_table_matches_the_status_module():
    rows = {
        code: word.strip().strip("`") for code, word in re.findall(r"\| `(\d+)` \| ([^|]+) \|", DOC)
    }
    for verdict in Verdict:
        assert rows.get(str(exit_code(verdict))) == str(verdict), (
            f"the doc's row for exit {exit_code(verdict)} disagrees with {verdict!r}"
        )
    assert rows.get(str(EXIT_USAGE)) == "—", "the usage exit is part of the action map"
    assert rows.get("130") == "—", "the interrupt exit is part of the action map"


FIRST_SCREEN_END = "<!-- END FIRST SCREEN -->"
PREVIEW_CHARS = 2000
"""What an agent harness shows of a tool output it judges too large.

Measured on the harness that drives partspec most: a 31,921-byte `cat` of this
file comes back as a preview cut at the last line break within 2000 characters
and a pointer to a saved copy. Of 27 such reads on one machine, 5 agents went
on from the preview alone, which ended 3,700 bytes before the exit table
(#441).
"""
LONGEST_LINE = 100
"""The cut falls on a line break, so it can land this far short of the limit."""


def _first_screen() -> str:
    return DOC[: DOC.index(FIRST_SCREEN_END)]


def test_the_first_screen_survives_the_preview_cut():
    """The bound is on the document's head, so that nothing can be prepended
    to it or grown inside it without the last line leaving the preview."""
    screen = _first_screen()
    assert max(map(len, screen.splitlines())) <= LONGEST_LINE
    assert len(screen) <= PREVIEW_CHARS - LONGEST_LINE


def test_the_first_screen_maps_every_exit_by_itself():
    """`test_the_exit_table_matches_the_status_module`, asked of the part an
    agent is sure to have read. The whole-document test cannot stand in: it
    reads every table in the file, so section 2's rows would answer for a
    first screen that had lost its own."""
    rows = {
        code: word.strip().strip("`")
        for code, word in re.findall(r"\| `(\d+)` \| ([^|]+) \|", _first_screen())
    }
    for verdict in Verdict:
        assert rows.get(str(exit_code(verdict))) == str(verdict)
    assert rows.get(str(EXIT_USAGE)) == "—"
    assert rows.get("130") == "—"


def test_quoted_tool_fragments_exist_in_the_code():
    """Every message fragment the doc teaches an agent to look for must be a
    string the tool actually emits."""
    fragments = {
        "run did not complete": SRC / "report.py",
        "the contract is wrong, not the part": SRC / "runner.py",
        "not evaluated:": SRC / "runner.py",
    }
    for fragment, path in fragments.items():
        assert fragment in DOC_FLAT, f"doc no longer teaches {fragment!r}"
        assert fragment in path.read_text(), f"{path.name} no longer emits {fragment!r}"


def test_named_flags_and_fields_exist():
    cli = (SRC / "cli.py").read_text()
    for flag in ("--expect", "--pin", "--timeout", "--quiet"):
        assert flag in DOC and flag in cli
    report = (SRC / "report.py").read_text()
    for field in ("expectation", "attribution", "build_origin", "source_closure"):
        assert field in DOC and field in report


def test_the_escalation_format_is_stated_exactly_and_greppable():
    """Acceptance (#28): the format is specified exactly. The doc must carry
    the literal template AND a conforming example the template's own regex
    accepts — a format whose example doesn't match teaches two formats."""
    assert (
        "HUMAN_REVIEW: <why in one clause> — last failure: <check id>: <detail or error text>"
        in DOC
    )
    pattern = re.compile(r"^HUMAN_REVIEW: .+ — last failure: .+: .+$", re.M)
    examples = [
        m
        for m in pattern.findall(DOC)
        if "<why" not in m  # skip the template itself
    ]
    assert examples, "the doc must show at least one conforming escalation example"


def test_the_attempt_bound_is_stated_exactly():
    assert "At most 5 attempts per part" in DOC


def test_weakening_is_forbidden_and_the_guard_is_named():
    """Acceptance (#28): forbids weakening and names the guard detecting it."""
    assert "Never weaken the contract" in DOC
    assert "claims pin" in DOC and "--expect" in DOC
    assert "diff" in DOC and "attribution" in DOC


def test_incomplete_and_fail_prescribe_different_actions():
    """Acceptance (#28): exit 1 says edit the model; exit 2 says don't —
    anchored to their own table rows, so swapping the two actions between
    rows fails rather than passing on mere presence (PR #106 review, F9a)."""
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| `(\d+)` \|.*$", DOC, re.M)}
    assert "edit the **model**" in rows["1"]
    assert "Do not edit geometry" in rows["2"]


def test_the_requires_tier_token_matches_the_runner():
    """The doc teaches `requires: \"occt\"` as the routing token; hold it to
    the string the runner actually emits (PR #106 review, F9b)."""
    assert "`requires` names the tier" in DOC
    assert '"occt"' in DOC
    assert 'requires="occt"' in (SRC / "runner.py").read_text()


def test_the_mcp_surface_is_the_four_tools_the_doc_says_it_is():
    """The doc's §0 caveat rests on a property of `mcp.py`: the surface is
    four tools, and `diff` and `lint` are not among them.

    Asserted against the CODE, not against the doc's sentence — a test that
    read both and compared them would be two copies of one fact. What is
    pinned here is the fact the sentence depends on: add a `lint` or `diff`
    tool and this fails, which is the moment the caveat stops being true.

    `tool_names` is `scripts/gen_docs.py`'s, reused rather than reimplemented
    — it already counts `async def`, which a second parser written here would
    be free to forget (PR #331 review, F2).
    """
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "gen_docs.py"
    spec = importlib.util.spec_from_file_location("partspec_gen_docs", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    gen_docs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen_docs)

    registered = gen_docs.tool_names((SRC / "mcp.py").read_text())
    assert registered == ["check", "measure", "render", "vdiff"], (
        "the MCP surface moved; AGENT-CONTRACT's caveat and mcp.py's "
        "instructions both describe the old one"
    )
    for absent in ("diff", "lint"):
        assert absent not in registered, (
            f"`{absent}` is now an MCP tool, so the doc is wrong to say it is CLI-only"
        )


def test_the_mcp_instructions_carry_a_doc_pointer():
    """The MCP client is the one consumer that cannot reach the CLI epilog.

    Not a phrase search: the assertion is that the instructions string
    contains a URL that actually resolves to a path in this repository, so a
    reorganisation that moves `docs/` fails here rather than shipping an
    agent a dead pointer (#298).
    """
    from partspec.mcp import _INSTRUCTIONS

    urls = re.findall(r"https://github\.com/[\w./-]*partspec/tree/main/([\w./-]+)", _INSTRUCTIONS)
    assert urls, "the MCP instructions ship no pointer to the documents"
    root = Path(__file__).resolve().parents[1]
    for path in urls:
        assert (root / path).is_dir(), f"the instructions point at {path}, which does not exist"


@needs_scad_tier
def test_measure_and_render_exit_4_on_a_model_origin_failure(tmp_path: Path):
    """§2.4's two claims, executed.

    The table in §2 governs `check`, and its exit-3 row sends the agent to
    `measure` — where a model-origin build failure lands on exit 4, the one
    case the table has no row for. §2.4 exists to cover that, and it rests on
    two properties of the payloads: `render` carries an `origin` to branch on
    and `measure` does not carry one at all.

    Pinned because both are silent if they drift. If `measure` gains the
    field — which §2.4 says is the real fix — this fails, and the paragraph
    saying "there is nothing to branch on" is what has to change.
    """
    (tmp_path / "broken.scad").write_text("cube([1,1,\n")
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, openscad\n\n\n"
        'def thing() -> Part:\n    return Part("thing", openscad("broken.scad"))\n'
    )

    def run(verb: str) -> tuple[int, dict]:
        result = subprocess.run(
            [sys.executable, "-m", "partspec", verb, "spec.py:thing", "--out", verb],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, json.loads(result.stdout)

    code, payload = run("render")
    assert code == 4, "render exits 4 on a build failure, model-origin included"
    assert payload["origin"] == "model", "render's payload is what §2.4 says to branch on"

    code, payload = run("measure")
    assert code == 4, "measure exits 4 on a build failure, model-origin included"
    assert "origin" not in payload, (
        "measure's failure payload gained an origin; §2.4 tells the agent there is "
        "none and to read the hint prose instead, so that paragraph is now wrong"
    )
    assert payload["error"] and payload["hint"], "the prose §2.4 falls back on must exist"


def test_a_raising_contract_gives_measure_and_render_exit_4_and_no_payload(tmp_path: Path):
    """§2.4's third state: exit 4 with nothing on stdout.

    The section offers two branches — `render`'s `origin`, `measure`'s
    `error`/`hint` — and a contract that RAISES satisfies neither: there is no
    payload to read either from. It is neither the model nor the machine, and
    §2.3's last bullet is the diagnosis, which §2.4 now says explicitly
    (PR #340 review, F3).

    Pinned because the clause is only true while the payload really is empty:
    if either verb starts emitting one on this path, the sentence telling the
    agent to read stderr becomes the wrong advice.
    """
    (tmp_path / "raises.py").write_text(
        "from partspec import Part\n\n\n"
        'def thing() -> Part:\n    raise RuntimeError("the contract itself is broken")\n'
    )

    for verb in ("measure", "render"):
        result = subprocess.run(
            [sys.executable, "-m", "partspec", verb, "raises.py:thing", "--out", verb],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 4, f"{verb} on a raising contract exits 4"
        assert result.stdout.strip() == "", (
            f"{verb} emitted a payload on a raising contract; §2.4 tells the agent "
            f"an empty stdout is how this state is recognised"
        )
        assert "the contract is wrong, not the part" in result.stderr, (
            f"{verb} must put the diagnosis on stderr, which is where §2.4 sends the agent"
        )


def test_quiet_is_a_check_only_flag():
    """`mcp.py`'s instructions tell the agent that `check` runs `--quiet` and
    the other three return their payload directly.

    The first draft of that paragraph said it of all four, and `--quiet` is
    not merely unpassed elsewhere — `partspec measure ... --quiet` is exit 64,
    unrecognized. A sentence generalising over a tool list is worth pinning
    against the parser that defines the list (PR #340 review, F1).

    Asserted through parsing rather than argparse internals: what the agent
    would hit is the refusal, so that is what is checked.
    """
    import contextlib
    import io

    from partspec.cli import build_parser

    def accepts(argv: list[str]) -> bool:
        parser = build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                parser.parse_args(argv)
            except SystemExit:
                return False
        return True

    assert accepts(["check", "spec.py", "--quiet"]), "check must accept --quiet; mcp.py passes it"
    for verb, argv in (
        ("measure", ["measure", "spec.py", "--quiet"]),
        ("render", ["render", "spec.py", "--quiet"]),
        ("vdiff", ["vdiff", "a", "b", "--quiet"]),
    ):
        assert not accepts(argv), (
            f"{verb} now accepts --quiet, so mcp.py's instructions — which say only "
            f"check passes it — understate the surface"
        )
