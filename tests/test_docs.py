"""The docs make executable claims, so they are executed.

A verification tool whose own front page overstates what it does is not a small
irony — it is the same failure it exists to prevent, and it happened: the status
line asserted the backends were unimplemented for three phases after they
shipped. A written rule did not catch that. These do.

**What belongs here is a claim that can be RUN**: the skills' worked examples
build and satisfy what they advertise, the README's example is the contract that
actually executes, the catalogue's reproducible entry reproduces. What does not
belong is a search for a phrase. `assert "five defect classes in" in README`
passes when the README says "five defect classes in 2019, all of which failed" —
it reports that a string is present, which is not the claim anyone wanted to
make. Seven such tests were deleted in #150; do not reintroduce the shape.

Nor does an enumeration belong here. The vocabulary table, the unit table,
`DIMENSIONAL_KINDS`, the backend protocol block and the exit codes are
projections of the code, and six tests used to hold those second copies in step.
They are generated now (`scripts/gen_docs.py`, enforced by `just check`), so
there is one copy and nothing to compare. If you find yourself writing a test
that reads markdown and reads code and diffs them, generate the markdown
instead.

Some of these need a CAD engine — executing a skill's build123d example means
building it — and are marked accordingly.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from support import OPENSCAD, measured, needs_openscad, needs_scad_tier

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
README = ROOT / "README.md"
EXAMPLE = ROOT / "examples" / "spacer" / "spec.py"
SPACER_SCAD = ROOT / "examples" / "spacer" / "spacer.scad"


def _check_calls(source: str) -> list[str]:
    """The sequence of `p.<check>(...)` calls inside `spacer()`, normalised.

    Compares the call *shape* rather than the source text, so reformatting or
    inlining a constant does not fail the test but adding, dropping or
    reordering a check does.
    """
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "spacer")
    calls = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            args = [ast.unparse(a) for a in node.args]
            kwargs = [f"{k.arg}=" for k in node.keywords]
            calls.append(f"{node.func.attr}({', '.join(args + kwargs)})")
    return calls


def _first_python_block(markdown: str) -> str:
    match = re.search(r"```python\n(.*?)```", markdown, re.S)
    assert match is not None, "the README no longer contains a python example"
    return match.group(1)


def test_the_readme_example_is_the_real_contract():
    """The front-page example must be the contract that actually runs.

    It previously showed a `bayonet_lock.scad` call that would not have worked —
    the library needs `method=`, which the example omitted. An example nobody can
    run is a claim nobody can check.
    """
    assert _check_calls(_first_python_block(README.read_text())) == _check_calls(
        EXAMPLE.read_text()
    )


def test_the_readme_console_output_matches_the_contract():
    """Every check the example declares appears in the transcript, and the tally
    agrees. `builds` is added by the tool, hence the +1."""
    readme = README.read_text()
    transcript = re.search(r"```console\n\$ partspec check.*?```", readme, re.S)
    assert transcript is not None, "the README no longer shows a check transcript"
    body = transcript.group(0)

    declared = len(_check_calls(EXAMPLE.read_text()))
    shown = len(re.findall(r"^\s+ok\s+\S+", body, re.M))
    assert shown == declared + 1, "transcript check count disagrees with the contract"
    assert f"PASS: {shown} pass" in body, "the transcript's tally disagrees with its own lines"


def _verbs_named(text: str) -> set[str]:
    """Verbs a document mentions, in either form the docs use: `partspec
    render` or a bare `` `vdiff` ``."""
    return set(re.findall(r"partspec (\w+)", text)) | set(re.findall(r"`(\w+)`", text))


def test_the_front_page_describes_the_surface_that_exists():
    """Two guards: the claim it made, and the surface it denied.

    The regression: README and AGENTS both asserted the contract API and
    geometry backends did not exist, for three phases after they shipped.

    The first guard is the negation denylist that caught it — kept, because
    substring absence pins a specific historical claim perfectly well. What
    rotted was matching RAW text: one pattern contained a hard newline at a
    wrap position, so rewrapping the paragraph silently retired it. Joining
    whitespace first fixes the actual cause, and PR #154's review proved the
    point by showing that replacing this guard with verb-derivation alone let
    the original sentence back in — a repair that was a coverage regression.

    The second guard is derivable and catches the wider failure: a front page
    describing a smaller tool than the one installed. Both documents must name
    every verb the parser serves.
    """
    import argparse

    from partspec.cli import build_parser

    subparsers = [
        action
        for action in build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert subparsers, "the CLI must still have subcommands"
    verbs = set(subparsers[0].choices)

    for doc in (README, ROOT / "AGENTS.md"):
        prose = " ".join(doc.read_text().lower().split())
        for claim in ("backends are not implemented", "nothing useful to run yet"):
            assert claim not in prose, f"{doc.name} claims {claim!r}"
        named = _verbs_named(doc.read_text()) & verbs
        assert named == verbs, f"{doc.name} does not mention: {sorted(verbs - named)}"


def test_readme_links_survive_pypi():
    """pyproject embeds README.md verbatim as the wheel's long description, so
    a repo-relative link 404s on pypi.org. Absolute blob URLs or nothing (#61).
    """
    text = README.read_text()
    # Positive invariant, not banned prefixes: `](./docs/`, a root-file link
    # (`](LICENSE)`) or a reference-style definition would evade a denylist
    # while 404ing identically. Every markdown link target must be absolute
    # or an in-page anchor.
    for target in re.findall(r"\]\(([^)]+)\)", text):
        assert re.match(r"^(https?://|#)", target), f"README link would 404 on PyPI: {target}"
    assert "<a href=" not in text
    assert not re.search(r"^\[[^\]]+\]:", text, re.MULTILINE), "reference-style link definition"


# --------------------------------------------------------------------------
# docs/FAILURE-MODES.md — the catalogue's [repo] claims are executable
#
# Only the executable one survives. Three sibling tests asserted that phrases
# appeared in the catalogue, in source comments, and in another test file
# (`assert "would be silently dropped" in engines/openscad.py`). A substring
# search cannot tell a true claim from a false one — it reports that a string
# is PRESENT — so they enforced wording, not correctness, and rewording a
# comment broke them while a wrong catalogue passed. Executing the claim is
# the only form of this that carries information.
# --------------------------------------------------------------------------


@needs_scad_tier
def test_the_hole_becomes_notch_essence_is_reproducible_here(tmp_path: Path):
    """Catalogue entry 3's [repo] claim, executed: a slot swept across the
    plate edge drops the genus while every other check holds still — the
    failure mode visual review is worst at, in eight lines of scad."""
    from partspec.backends.mesh import MeshBackend
    from partspec.engines.openscad import OpenSCADSource

    scad = tmp_path / "plate.scad"
    scad.write_text(
        "slot_l = 20;\n"
        "difference() {\n"
        "    cube([40, 30, 4]);\n"
        "    translate([10, 12, -1]) cube([slot_l, 6, 6]);\n"
        "}\n"
    )

    def measure(slot_l: float):
        backend = MeshBackend()
        artifact = backend.build(
            OpenSCADSource(path=scad, params={"slot_l": slot_l}), tmp_path / f"o{slot_l:g}"
        )
        return backend, artifact

    backend, hole = measure(20.0)  # slot ends at x=30: an interior through-hole
    backend2, notch = measure(35.0)  # slot reaches x=45 > 40: breaches the edge

    assert measured(backend.genus(hole)).value == 1
    assert measured(backend2.genus(notch)).value == 0, (
        "the hole that reached the boundary is a notch"
    )
    for b, a in ((backend, hole), (backend2, notch)):
        assert b.watertight(a).value is True
        assert measured(b.solid_count(a)).value == 1
        assert b.bbox(a).value == (40.0, 30.0, 4.0)


@needs_openscad
def test_the_background_modifier_entry_is_reproducible_here(tmp_path: Path):
    """Catalogue entry 9a's [repo] claims, executed (#336).

    Three claims, one source each, and the entry stands or falls on all three:
    `%` is EVALUATED and NOT EXPORTED, so its diagnostic reaches partspec over
    a byte-identical mesh; `*` is not evaluated, so it is free; `#` is
    exported, so its diagnostic is about the mesh. Byte identity is the load
    bearing half -- it is why the refusal is a cost rather than a catch.
    """
    from partspec.backend import BuildError
    from partspec.engines.openscad import OpenSCADSource, render

    def build(name: str, body: str) -> tuple[bytes, list[str]]:
        src = tmp_path / name
        src.write_text(body)
        seen: list[str] = []
        out = render(OpenSCADSource(path=src), tmp_path / f"{src.stem}.stl", unresolved_out=seen)
        assert not isinstance(out, BuildError), out
        return out.read_bytes(), seen

    fault = "translate([undef, 0, 0]) cube(2);\n"
    plain, quiet = build("plain.scad", "cube([40,30,6]);\n")
    assert quiet == [], "premise: the part on its own is clean"

    ghost, refused = build("ghost.scad", f"cube([40,30,6]);\n%{fault}")
    assert ghost == plain, "a `%` subtree contributes nothing to the export"
    assert refused, "and its diagnostic is read anyway — the deliberate cost, #336"

    disabled, silent = build("disabled.scad", f"cube([40,30,6]);\n*{fault}")
    assert disabled == plain, "`*` contributes nothing either"
    assert silent == [], "and is never evaluated, so it costs nothing"

    highlit, read = build("highlit.scad", f"cube([40,30,6]);\n#{fault}")
    assert highlit != plain, "`#` IS exported, so its warning is about the mesh"
    assert read, "and is refused for that reason, not as a cost"


# --------------------------------------------------------------------------
# skills/contract-authoring — the skill's executable claims
# --------------------------------------------------------------------------

SKILL = (ROOT / "skills" / "contract-authoring" / "SKILL.md").read_text()


def test_the_skill_names_only_real_contract_methods():
    """Every `p.method` the skill teaches must exist on Part — a skill naming
    a method that was renamed teaches a call that raises."""
    from partspec import Part

    methods = set(re.findall(r"`p\.(\w+)", SKILL)) | set(re.findall(r"^p\.(\w+)\(", SKILL, re.M))
    assert methods, "the skill must actually name methods"
    for name in methods:
        assert hasattr(Part, name), f"skill teaches p.{name}, which Part does not have"


def test_the_skills_worked_example_executes():
    """The before/after block is code an agent will paste; both halves must
    declare real checks on a real Part."""
    from partspec import Part, openscad

    blocks = re.findall(r"```python\n(.*?)```", SKILL, re.S)
    assert blocks, "the worked before/after must be a fenced python block"
    # Selected by CONTENT, not by position. `blocks[0]` meant "whichever
    # python block happens to come first", so adding the region example
    # earlier in the file broke this test with a message about a missing
    # "# After" delimiter — pointing at the wrong block entirely (#200).
    matching = [b for b in blocks if "# After" in b]
    assert len(matching) == 1, "exactly one block carries the before/after halves"
    before_half, _, after_half = matching[0].partition("# After")
    assert after_half, "the block must carry both halves, delimited by '# After'"
    for half in (before_half, after_half):
        code = "\n".join(line for line in half.splitlines() if line.startswith("p."))
        p = Part("skill-subject", openscad("m.scad", wall=2.4, bore_d=8.0, plate_y=30.0))
        exec(code, {"p": p})  # noqa: S102 - executing the doc is the point
        assert len(p.checks) == 3, "each half declares exactly three checks"
    # The AFTER half must actually be the structured form it advertises.
    assert sorted(c.kind for c in p.checks) == ["param_range", "param_range", "requires"]


def test_the_skills_region_example_executes():
    """The region block is code an agent will paste, so it gets the same
    treatment as the before/after one (#200).

    It exists because `keep_out`/`keep_in` are the only checks whose argument
    is a shape you construct, and no worked call appeared anywhere in the tree
    — two fleet agents on different engines guessed `axis=(0, 0, 1)`, which is
    refused.

    Executed WHOLE, imports included. An earlier draft filtered out every
    `from ...` line and injected the modules into globals, so a typo in the
    block's own imports — exactly the part an agent pastes first — passed
    unnoticed (round 1 of #200's review).
    """
    from partspec import Part, openscad, region
    from partspec.status import ContractError

    blocks = re.findall(r"```python\n(.*?)```", SKILL, re.S)
    matching = [b for b in blocks if "p.keep_out(" in b]
    assert len(matching) == 1, "exactly one block shows the region calls"

    p = Part("skill-region-subject", openscad("m.scad"))
    namespace: dict = {"p": p}
    exec(matching[0], namespace)  # noqa: S102 - executing the doc is the point

    assert [c.kind for c in p.checks] == ["keep_out", "keep_in", "keep_in"]
    boss = p.checks[0].region
    assert isinstance(boss, region.CylinderRegion)
    assert boss.axis == "y", "a spelled-out axis, not a vector"
    assert all(c.shell for c in p.checks), "every region carries the anti-vacuity shell"

    # The two keep_ins must enter DIFFERENT members, or they say one thing
    # twice. The plate box climbs in z, the base box runs out in y.
    plate_web, base_web = (c.region for c in p.checks[1:])
    assert isinstance(plate_web, region.BoxRegion) and isinstance(base_web, region.BoxRegion)
    assert plate_web.max[2] > base_web.max[2], "the plate box must climb further in z"
    assert base_web.max[1] > plate_web.max[1], "the base box must run further in y"

    # And the thing the example warns about is really refused.
    with pytest.raises(ContractError):
        region.cylinder(d=22.0, h=2.0, at=(0.0, 0.0, 0.0), axis=(0, 0, 1))  # type: ignore[arg-type]


@needs_scad_tier
def test_the_skills_retrofit_probe_measures(tmp_path: Path):
    """Step 1 of the retrofit path, executed.

    The skill's first retrofit instruction used to be
    `partspec measure model.py:factory`, which cannot work: both verbs resolve
    a target that must return a `partspec.Part`, so naming the model exits 64
    (#282). The replacement instruction is to write a checkless contract and
    measure THAT, and the claim worth pinning is that such a contract is
    accepted at all — a `Part` with an id and a source and nothing else is the
    smallest input `measure` takes.

    Selected by CONTENT, following the lesson recorded above: the block is the
    one that names probe.py, not whichever block happens to come first.

    BOTH copies are executed. The skill's is the one an agent pastes, but
    `SPEC-contract.md` §7's is the NORMATIVE one, and nothing else in this
    suite executes a fence from that file — so running only the skill's would
    leave the copy that carries the MUST unguarded (PR #340 review).
    """
    import subprocess

    sources = {
        "skills/contract-authoring/SKILL.md": SKILL,
        "docs/SPEC-contract.md": (DOCS / "SPEC-contract.md").read_text(),
    }
    for where, text in sources.items():
        blocks = re.findall(r"```python\n(.*?)```", text, re.S)
        matching = [b for b in blocks if "# probe.py" in b]
        assert len(matching) == 1, f"{where} must show the retrofit probe exactly once"

        # The block cites a stand-in vendor path; point it at a source that
        # exists. Dedented: the skill's copy sits inside a numbered list, so
        # its fence and body carry the list's indentation and will not
        # compile as written.
        body = textwrap.dedent(matching[0]).replace("../vendor/bracket.scad", str(SPACER_SCAD))
        probe = tmp_path / "probe.py"
        probe.write_text(body)

        namespace: dict = {}
        exec(body, namespace)  # noqa: S102 - executing the doc is the point
        part = namespace["probe"]()
        assert not part.checks, f"{where}: the probe declares no checks — that is the point"
        assert part.source.path.name == SPACER_SCAD.name

        result = subprocess.run(
            [sys.executable, "-m", "partspec", "measure", f"{probe}:probe", "--out", str(tmp_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{where}: {result.stdout}{result.stderr}"
        payload = json.loads(result.stdout)
        # A checkless contract still yields the numbers the retrofit reads.
        assert {"bbox", "volume", "genus"} <= set(payload["measurements"]), where


def test_the_skills_pointers_resolve():
    for path in (
        "docs/PLAN.md",
        "docs/FAILURE-MODES.md",
        "docs/AGENT-CONTRACT.md",
        "examples/stepper-bracket/spec.py",
        "examples/bearing-block/claims.py",
        "examples/enclosure",
    ):
        assert path in SKILL, f"the skill must cite {path} by its full path"
        assert (ROOT / path).exists(), f"{path} is cited by the skill and must exist"


# --------------------------------------------------------------------------
# skills/openscad-authoring — the skill's examples build and mean what they say
# --------------------------------------------------------------------------

SCAD_SKILL = (ROOT / "skills" / "openscad-authoring" / "SKILL.md").read_text()


def _scad_blocks() -> dict[str, str]:
    blocks = {}
    for body in re.findall(r"```scad\n(.*?)```", SCAD_SKILL, re.S):
        first = body.splitlines()[0]
        m = re.match(r"// (rule-\d+-(?:before|after))", first)
        assert m, f"every scad block carries a rule marker, got: {first!r}"
        blocks[m.group(1)] = body
    return blocks


@needs_scad_tier
def test_the_scad_skills_examples_build_and_satisfy_their_claims(tmp_path: Path):
    """Acceptance (#22): the examples in the skill actually build and satisfy
    what they claim — executed, per rule, not asserted in prose."""
    from partspec.backend import BuildError
    from partspec.backends.mesh import MeshBackend
    from partspec.engines.openscad import OpenSCADSource

    blocks = _scad_blocks()
    assert set(blocks) >= {
        "rule-1-before",
        "rule-1-after",
        "rule-2-before",
        "rule-2-after",
        "rule-4-before",
        "rule-4-after",
        "rule-5-after",
        "rule-7-before",
        "rule-7-after",
    }
    # Rule 3's overshoot idiom is taught THROUGH the after-blocks it points
    # at; an exact-face cutter slipped every measurement (review mutation M4),
    # so the idiom itself is pinned textually.
    for name in ("rule-2-after", "rule-5-after"):
        assert "-1" in blocks[name] and "+ 2" in blocks[name], f"{name} lost the overshoot"

    def build(name: str):
        scad = tmp_path / f"{name}.scad"
        scad.write_text(blocks[name])
        backend = MeshBackend()
        return backend, backend.build(OpenSCADSource(path=scad), tmp_path / name)

    # Rule 1: both build; the after-form has drivable top-level parameters.
    for name in ("rule-1-before", "rule-1-after"):
        _, artifact = build(name)
        assert not isinstance(artifact, BuildError), name
    from partspec.engines.openscad import top_level_variables

    scad = tmp_path / "rule-1-after.scad"
    assert {"plate_w", "plate_d", "plate_t"} <= top_level_variables(scad)

    # Rule 4: pinned facets are a measurable property of the artifact — a
    # 48-gon cylinder exports exactly 50 distinct face normals; the unpinned
    # form follows $fa/$fs and must NOT equal it.
    backend4, pinned = build("rule-4-after")
    assert not isinstance(pinned, BuildError)
    assert backend4.provenance(pinned)["distinct_normals"] == 50
    backend4b, unpinned = build("rule-4-before")
    assert not isinstance(unpinned, BuildError)
    assert backend4b.provenance(unpinned)["distinct_normals"] != 50
    assert "facets" in top_level_variables(tmp_path / "rule-4-after.scad")

    # Rule 2: the fully-empty wrong order is refused by the engine itself and
    # relayed by partspec as a build failure; the right order is a genuine
    # through-hole, genus 1. (The exit-0 hazard is the PARTIAL wrong order,
    # which no fixed fixture can pin — the skill's prose carries it.)
    _, before = build("rule-2-before")
    assert isinstance(before, BuildError), "hole-minus-plate must fail as empty geometry"
    backend, after = build("rule-2-after")
    assert not isinstance(after, BuildError)
    assert measured(backend.genus(after)).value == 1
    assert backend.watertight(after).value is True

    # Rule 5: the decomposed form produces the same part as rule 2's after.
    backend5, decomposed = build("rule-5-after")
    assert not isinstance(decomposed, BuildError)
    assert measured(backend5.genus(decomposed)).value == 1
    assert measured(backend5.volume(decomposed)).value == pytest.approx(
        measured(backend.volume(after)).value, rel=1e-9
    )


@needs_scad_tier
def test_the_scad_skills_loop_guard_holds_on_whichever_engine_is_pinned(tmp_path: Path):
    """Rule 7's claim, executed: the guarded loop builds one part on every
    engine, and the unguarded one does not (#356).

    The divergence needs two binaries and a run has one, so the unguarded
    half is keyed to `engine.version` — CI pins 2021.01 and 2026.08.01 and
    runs the whole suite under each, so both rows below are executed, one per
    matrix leg. An unpinned third version is not skipped: it still has to land
    on one of the two measured outcomes, which is what makes a NEW divergence
    a failure here rather than a silence.
    """
    from partspec.backends.mesh import MeshBackend
    from partspec.engines.openscad import OpenSCADSource, version

    blocks = _scad_blocks()

    def bbox(name: str, stud_n: float) -> tuple[float, ...]:
        scad = tmp_path / f"{name}.scad"
        scad.write_text(blocks[name])
        backend = MeshBackend()
        artifact = backend.build(
            OpenSCADSource(path=scad, params={"stud_n": stud_n}),
            tmp_path / f"{name}{stud_n:g}",
        )
        return backend.bbox(artifact).value

    rail = (40.0, 8.0, 6.0)
    studded = (40.0, 8.0, 6.0 - 0.01 + 4.0)

    # The guard is the claim: no count reaches the range that the source has
    # not already said is non-empty, so zero and negative counts are the bare
    # rail on any engine, and a real count still places its studs.
    for stud_n in (0.0, -1.0):
        assert bbox("rule-7-after", stud_n) == pytest.approx(rail, abs=1e-6), stud_n
    assert bbox("rule-7-after", 2.0) == pytest.approx(studded, abs=1e-6)

    # Unguarded, `[1 : 0]` is engine-defined. 2021.01 normalises it and
    # iterates ASCENDING — i = 0 and i = 1, two studs the source did not ask
    # for; 2026.08.01 iterates nothing.
    unguarded = bbox("rule-7-before", 0.0)
    expected = {"2021.01": studded, "2026.08.01": rail}.get(version())
    if expected is not None:
        assert unguarded == pytest.approx(expected, abs=1e-6), version()
    else:
        assert unguarded == pytest.approx(rail, abs=1e-6) or unguarded == pytest.approx(
            studded, abs=1e-6
        ), f"{version()} reads a backwards range a third way: {unguarded}"

    # A real count is the same part either way — the divergence is confined to
    # the empty case, which is why it survives review.
    assert bbox("rule-7-before", 2.0) == pytest.approx(studded, abs=1e-6)


@needs_scad_tier
def test_the_scad_skills_undef_dimension_is_the_engines_number(tmp_path: Path):
    """Rule 8's claim, executed: the two blocks build to the two heights it
    quotes, and the silent one is the taller.

    Rule 8 is a measured claim with no gate until here (#308). Its before-form
    lets `undef` reach `linear_extrude()`, which substitutes a default of its
    own: a 40 x 30 x **100** part where the author wrote no 100 anywhere, and
    the after-form names the number instead at 40 x 30 x **6**. Both measured
    on 2021.01 and 2026.08.01 for this test, not taken from the table.

    Unlike rule 7 there is no branch on `engine.version`: the two engines agree
    here, and that agreement is half the point — a second binary catches rule
    7's divergence and cannot catch this one.

    The rest of the assertions are the hazard rather than the height. The
    before-form builds at all -- partspec's own success-path guard reads
    stderr for a name that did not resolve and a value the engine defaulted,
    and neither fires, because nothing failed to resolve and nothing failed to
    convert -- and what it builds is clean: watertight, one solid. A silent,
    plausible, wrong part is what makes this worth a rule.
    """
    from partspec.backend import BuildError
    from partspec.backends.mesh import MeshBackend
    from partspec.engines.openscad import OpenSCADSource, top_level_variables

    blocks = _scad_blocks()
    assert {"rule-8-before", "rule-8-after"} <= set(blocks), (
        "rule 8's worked blocks have been renamed; this gate has lost its subject"
    )

    def build(name: str, **params: float):
        scad = tmp_path / f"{name}.scad"
        scad.write_text(blocks[name])
        backend = MeshBackend()
        suffix = "".join(f"-{k}{v:g}" for k, v in params.items())
        artifact = backend.build(
            OpenSCADSource(path=scad, params=params), tmp_path / f"{name}{suffix}"
        )
        assert not isinstance(artifact, BuildError), f"{name}: {artifact}"
        return backend, artifact

    # The engine's number, not the author's: 100 mm of height nobody wrote.
    silent, defaulted = build("rule-8-before")
    assert silent.bbox(defaulted).value == pytest.approx((40.0, 30.0, 100.0), abs=1e-6)
    assert silent.watertight(defaulted).value is True
    assert measured(silent.solid_count(defaulted)).value == 1

    named, plate = build("rule-8-after")
    assert named.bbox(plate).value == pytest.approx((40.0, 30.0, 6.0), abs=1e-6)
    assert named.watertight(plate).value is True
    assert measured(named.solid_count(plate)).value == 1

    # "a real number a -D can drive and a contract can name" — both halves.
    assert "plate_t" in top_level_variables(tmp_path / "rule-8-after.scad")
    driven, thicker = build("rule-8-after", plate_t=9.0)
    assert driven.bbox(thicker).value == pytest.approx((40.0, 30.0, 9.0), abs=1e-6)


# --------------------------------------------------------------------------
# skills/build123d-authoring — the skill's examples build and mean what they say
# --------------------------------------------------------------------------

BD_SKILL = (ROOT / "skills" / "build123d-authoring" / "SKILL.md").read_text()


def _bd_blocks() -> dict[str, str]:
    blocks = {}
    for body in re.findall(r"```python\n(.*?)```", BD_SKILL, re.S):
        m = re.match(r"# (bd-rule-\d+-(?:before|after))", body.splitlines()[0])
        assert m, f"every python block carries a marker: {body.splitlines()[0]!r}"
        blocks[m.group(1)] = body
    return blocks


def test_the_bd_skills_examples_build_and_satisfy_their_claims(tmp_path: Path):
    pytest.importorskip("build123d", reason="occt extra not installed")
    import sys

    from partspec.backends.occt import OcctBackend
    from partspec.engines import pycad

    blocks = _bd_blocks()
    assert set(blocks) >= {
        "bd-rule-1-after",
        "bd-rule-2-after",
        "bd-rule-3-before",
        "bd-rule-5-after",
    }
    backend = OcctBackend("build123d")

    def factory_of(name: str):
        ns: dict = {}
        exec(blocks[name], ns)  # noqa: S102 - executing the doc is the point
        return ns["make_part"]

    # Rule 1: the factory shape builds a genuine through-bored plate, and
    # the parameters MEAN something — a hardcoded body passed this test
    # until the review's mutation showed it (PR #117, F3).
    factory = factory_of("bd-rule-1-after")
    part = pycad.adopt(factory())
    assert measured(backend.genus(part)).value == 1
    assert measured(backend.watertight(part)).value is True
    widened = pycad.adopt(factory(plate_w=50.0))
    assert measured(backend.bbox(widened)).value == (50.0, 30.0, 4.0)

    # Rule 2: the three-line adapter drives an untouched community class.
    (tmp_path / "cq_gridfinity_like.py").write_text(
        "from build123d import Box\n\n\n"
        "class GridfinityBox:\n"
        "    def __init__(self, w, d, h):\n"
        "        self.w, self.d, self.h = w, d, h\n\n"
        "    def render(self):\n"
        "        return Box(42 * self.w, 42 * self.d, 7 * self.h)\n"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        adapted = pycad.adopt(factory_of("bd-rule-2-after")(2, 1))
        assert measured(backend.solid_count(adapted)).value == 1
        assert measured(backend.bbox(adapted)).value == (84.0, 42.0, 21.0)
        assert "cq_gridfinity_like" in sys.modules, (
            "the adapter must DRIVE the community class, not replace it"
        )
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("cq_gridfinity_like", None)

    # Rule 3: both selector variants build watertight — that is the trap —
    # and the chamfer measurably moved: the boss rim sheds less material
    # than the plate rim it silently abandoned.
    make = factory_of("bd-rule-3-before")
    flat, bossed = pycad.adopt(make(0.0)), pycad.adopt(make(2.0))
    for shape in (flat, bossed):
        assert measured(backend.watertight(shape)).value is True
    removed_flat = 40 * 30 * 4 - measured(backend.volume(flat)).value
    removed_bossed = (40 * 30 * 4 + 10 * 10 * 2) - measured(backend.volume(bossed)).value
    assert removed_bossed < removed_flat * 0.5, (
        "the chamfer must have silently moved to the smaller boss rim"
    )

    # Rule 5: the CadQuery factory drives the SAME kernel to the same part.
    cadquery = pytest.importorskip("cadquery", reason="cadquery extra not installed")
    assert cadquery
    cq_part = pycad.adopt(factory_of("bd-rule-5-after")())
    assert measured(backend.genus(cq_part)).value == 1
    assert measured(backend.watertight(cq_part)).value is True
    assert measured(backend.bbox(cq_part)).value == (40.0, 30.0, 4.0)


def test_every_repo_path_the_specs_cite_can_be_opened():
    """Two normative specs listed `investigations/03`, `investigations/04` and
    `DIRECTION.md` under **Backing:** — files in an unpublished survey
    workspace that no reader of this repository could open, while
    `notes/README.md` argues at length that exactly this is a loss worth
    preventing. They are vendored under `notes/survey/` now.

    Scoped to paths that look like in-repo files, so prose naming an external
    project is unaffected.
    """
    import subprocess

    # `git ls-files` needs a checkout. Without this guard the test ERRORS in an
    # unpacked sdist (`CalledProcessError`, exit 128) — and `pyproject.toml`'s
    # sdist `exclude` list argues that `tests/` ships "because a downstream
    # packager runs the suite from an sdist, and that claim only holds if the
    # suite actually passes there". It did not, from #151 until now. Same guard
    # `test_packaging.py` and `test_lint_config.py` use. Part of #150.
    if not (ROOT / ".git").exists():
        pytest.skip("asks what this checkout TRACKS; an unpacked sdist has no git")

    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
    )
    pattern = re.compile(r"`((?:docs|notes|src|tests|examples|skills|evals|scripts)/[\w./-]+)`")
    missing = []
    for doc in [*sorted(DOCS.glob("*.md")), README]:
        for cited in pattern.findall(doc.read_text()):
            # Tracked, not merely present. `notes/upstream/` is a gitignored
            # vendored clone: DECISIONS cited a path inside it, the file existed
            # on the machine that vendored it, and this test passed locally and
            # failed in CI — the citation was unreachable for every reader but
            # one, which is the exact loss the test is for.
            prefix = cited.rstrip("/")
            if prefix in tracked or any(t.startswith(prefix + "/") for t in tracked):
                continue
            missing.append(f"{doc.name} -> {cited}")
    assert not missing, "cited paths no reader can open:\n  " + "\n  ".join(missing)


def shipped_markdown() -> list[Path]:
    """Every markdown file the sdist carries.

    Recursive, and derived from one list rather than three. The first version
    of this used depth-fixed globs (`skills/*/*.md`), which silently stopped
    scanning the moment anyone nested a document one level deeper — a hole in a
    test whose whole job is noticing unreachable references (PR #162 review,
    LOW-H).
    """
    trees = ("docs", "skills", "examples")
    found = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "CHANGELOG.md"]
    for tree in trees:
        found.extend(sorted((ROOT / tree).rglob("*.md")))
    return [p for p in found if p.is_file()]


def prose_of(text: str) -> str:
    """`text` with fenced code blocks blanked out, line numbering preserved.

    A citation inside a ```sh fence is a command someone types, not a reference
    a reader follows, and a link definition inside one defines nothing. Both
    directions bit the first version of these guards: a shell example produced
    a false positive, and a definition moved into a fence let a heading render
    as literal text while the test passed (PR #162 review, LOW-D and LOW-E).

    Blanked rather than removed so reported line numbers still point at the
    right line.
    """
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line)
    return "\n".join(out)


def test_every_repo_url_the_docs_link_to_can_be_opened():
    """The same question as the test above, asked of absolute repo URLs.

    `notes/` stopped shipping in the sdist at #150, so the citations naming it
    dangled for anyone reading these files from PyPI rather than a checkout —
    the reader `notes/README.md` argues hardest about. They are reference-style
    links to `blob/main` now, which resolve from anywhere.

    Not a duplicate of it. The link form writes the path down TWICE — once as
    the backticked display text that test reads, once in a URL that nothing
    read — so the two copies could drift apart and only one was checked. Both
    halves need a reader: mutate the display text and the test above fails;
    mutate the URL and, before this, nothing did.

    Scans every shipped markdown surface, not just `docs/`. `skills/`,
    `examples/`, `AGENTS.md` and `CHANGELOG.md` all ride in the sdist for the
    same reason `docs/` does, and no test looked at any of them (PR #162
    review, MEDIUM-1).
    """
    import subprocess

    if not (ROOT / ".git").exists():
        pytest.skip("asks what this checkout TRACKS; an unpacked sdist has no git")

    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
    )
    url = re.compile(r"https://github\.com/heibench/partspec/(?:blob|tree)/main/([\w./-]+)")
    missing = []
    for doc in shipped_markdown():
        for cited in url.findall(prose_of(doc.read_text())):
            prefix = cited.rstrip("/")
            if prefix in tracked or any(t.startswith(prefix + "/") for t in tracked):
                continue
            missing.append(f"{doc.relative_to(ROOT)} -> {cited}")
    assert not missing, "linked paths no reader can open:\n  " + "\n  ".join(missing)


def test_no_shipped_doc_cites_a_non_shipping_file_as_a_bare_path():
    """The defect the two tests above do not catch, stated directly.

    Both of them ask "is this path tracked?". Nothing asked "does it ship?" —
    and `notes/` and `evals/` are tracked *and* excluded from the sdist, so a
    bare `` `notes/GAPS.md` `` passes both while being unopenable for every
    reader who came from PyPI. That is the whole of #162, and it survived one
    line away from the citations that were fixed (`AGENTS.md`, PR #162 review
    HIGH-2).

    A citation of an excluded tree must therefore be a LINK, which resolves
    from anywhere. Bare directory mentions (`` `notes/` ``) and prose naming
    the tree are unaffected: this matches paths that name a file.

    The excluded trees are read from `pyproject.toml` rather than listed here,
    so shipping `notes/` again — or excluding a new tree — moves this test
    with the packaging rather than leaving it asserting last year's layout.

    A directory exclude is one with no dot in it. That heuristic would stop
    policing a dotted directory silently, so `assert trees` at least refuses to
    pass vacuously if the whole list ever becomes dotted.
    """
    import tomllib

    excludes = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"][
        "targets"
    ]["sdist"]["exclude"]
    # `re.escape`, because these are packaging globs, not a regex the author of
    # this test controls: `notes/**` compiled straight in raises "multiple
    # repeat" and fails the suite with an unrelated message (review LOW-G).
    trees = sorted(
        re.escape(e.strip("/").rstrip("*").rstrip("/")) for e in excludes if "." not in e
    )
    assert trees, "no excluded trees in the sdist config; this test has nothing to police"

    cite = re.compile(r"`((?:" + "|".join(trees) + r")/[\w./-]*\.\w+)`")
    # `[`path`][label]` and `[`path`](url)` are links; a lone code span is not.
    # Whitespace is allowed between the two halves of a reference link because
    # CommonMark allows it and this repo hard-wraps at ~90 columns, so a wrap
    # landing there is a matter of time — and it would have failed the suite
    # with a wrong diagnosis (review LOW-C).
    closes = re.compile(r"\s*[(\[]")
    bare = []
    for doc in shipped_markdown():
        text = prose_of(doc.read_text())
        for m in cite.finditer(text):
            after = text[m.end() : m.end() + 40]
            linked = (
                m.start() > 0
                and text[m.start() - 1] == "["
                and after.startswith("]")
                and closes.match(after[1:]) is not None
            )
            if not linked:
                line = text[: m.start()].count("\n") + 1
                bare.append(f"{doc.relative_to(ROOT)}:{line} -> {m.group(1)}")
    assert not bare, (
        "these name a file the sdist does not carry, as a bare path rather than a link, "
        "so a reader from PyPI cannot open them:\n  " + "\n  ".join(bare)
    )


def test_the_generated_doc_blocks_are_current():
    """`scripts/gen_docs.py --check`, run from the test suite.

    This is NOT the pattern the module docstring forbids. It does not read a
    doc, read the code and diff two copies — it asks whether the one copy is
    current, the same question `ruff format --check` asks. There is no second
    source of truth for it to disagree with.

    It lives here rather than only in `just check` because of where CI runs
    each. `check` is gated on `needs.changes.outputs.code == 'true'`, and that
    filter is `['**', '!**/*.md']`, so a markdown-only PR skips it and `ok`
    passes on skipped jobs. The `test` job is deliberately ungated — its comment
    says "a docs-only change can genuinely break it". Moving this enforcement
    into `check` alone would therefore have let exactly the change it polices
    through: hand-editing a generated table in `docs/SPEC-contract.md`, touching
    no other file, merges green. Found in PR #156's review; the six tests this
    machinery replaced all ran in the ungated job, so this restores the coverage
    rather than adding new.
    """
    import subprocess
    import sys

    # Asserted, not skipped. A skip here would be silent in the one place it
    # matters: `scripts/` is in the sdist today, and a later tarball-shrinking
    # PR that excluded it would leave this test reporting a reassuring SKIP
    # rather than a failure. `test_the_sdist_carries_everything_the_suite_reads`
    # names this path for the same reason, so the two hold each other up
    # (PR #156 review, finding B).
    script = ROOT / "scripts" / "gen_docs.py"
    assert script.exists(), (
        f"{script} is missing, so nothing here checks the generated doc blocks. "
        "If the sdist stopped shipping scripts/, that is the bug."
    )
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "a generated doc block is stale or misplaced; run `just fmt`.\n"
        f"{result.stdout}{result.stderr}"
    )


def _gen_docs():
    """`scripts/gen_docs.py`, imported rather than shelled out to.

    The test above runs it as a subprocess because it asks one yes/no question
    about this tree. This one has to hand a function an input the tree does not
    contain.
    """
    import importlib.util

    path = ROOT / "scripts" / "gen_docs.py"
    spec = importlib.util.spec_from_file_location("partspec_gen_docs", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_layout_generator_counts_an_async_mcp_tool():
    """`async def` is the idiomatic form for an MCP tool, and
    `ast.AsyncFunctionDef` is **not** a subclass of `ast.FunctionDef`.

    So a generator matching only the latter drops an async tool from
    AGENTS.md's `mcp.py` row — and the drop is not inert. The prescribed remedy
    is `just fmt`, which would then WRITE the shortened row: character for
    character the falsehood #299 was filed about, with `gen-docs --check` green
    afterwards and nothing left to notice. A guard whose failure mode is to
    author its own defect class is worse than no guard, which is why the shape
    is pinned here rather than left to the generator's own docstring
    (PR #331 review, F2).

    This is not the doc-versus-code diff the module docstring forbids: it
    executes the generator against a fixed input and asserts what it returns.
    There is no second copy of anything.
    """
    tool_names = _gen_docs().tool_names
    source = (
        "@server.tool()\n"
        "def check(target): ...\n"
        "@server.tool()\n"
        "async def vdiff(old, new): ...\n"
        "@server.tool\n"
        "async def render(target): ...\n"
        "@tool()\n"
        "def measure(target): ...\n"
        "@staticmethod\n"
        "def not_a_tool(): ...\n"
        "async def also_not_a_tool(): ...\n"
        # The near-misses fence the LOOSENING direction, which the rest of this
        # fixture does not: `call_tool` and `list_tools` are the low-level MCP
        # SDK's own decorators, and a substring match would write both into the
        # row as verbs. `toolset` is the prefix case — needed because the name
        # matched is the decorator's TRAILING one, so `call_tool` does not
        # start with "tool" and leaves `startswith` alive (PR #331 review, R2-3).
        "@server.call_tool()\n"
        "def ct(): ...\n"
        "@server.list_tools()\n"
        "def lt(): ...\n"
        "@server.toolset()\n"
        "def ts(): ...\n"
    )
    assert tool_names(source) == ["check", "vdiff", "render", "measure"]


def test_every_spec_a_diagnostic_cites_is_locatable_from_the_tool():
    """A citation an installed user cannot follow is not a citation.

    Diagnostics cite the specs by section — `(SPEC-report.md 7.1)`,
    `SPEC-contract.md 10` — and the wheel used to ship the package and nothing
    else, so for anyone who installed rather than cloned the tool named
    documents it gave no way to reach. Found by dropping an agent on a cold
    install with an objective and no other context: it went looking for
    SPEC-contract.md after the attribution advisory named it, did not find it,
    and inferred the contract API from `inspect.getdoc` instead. The wheel
    carries the documents since #349, which changes where `--help` should send
    that agent but not whether this test has a subject.

    Two halves, both derived rather than matched: every spec the source names
    must exist, and `--help` must say where the specs are. Neither is a phrase
    search — the first fails on a citation to a document that does not exist,
    the second on a tool that cites documents and never locates them.
    """
    import re

    cited = {
        m.group(0)
        for path in (ROOT / "src" / "partspec").rglob("*.py")
        for m in re.finditer(r"SPEC-[a-z]+\.md", path.read_text())
    }
    assert cited, "no spec citations at all — this guard has lost its subject"
    missing = sorted(name for name in cited if not (DOCS / name).exists())
    assert not missing, f"diagnostics cite specs that do not exist: {missing}"

    from partspec.cli import build_parser

    epilog = build_parser().epilog or ""
    assert "docs" in epilog, (
        "the CLI cites specs by section but never says where they live; an "
        "installed user has no docs/ directory to look in"
    )

    # And since #349 the answer can be a local one, so the weaker half above
    # is no longer the whole assertion: where this copy carries the documents,
    # `--help` must name THAT directory rather than only the URL. A phrase
    # search would not have caught the epilog going stale against a moved
    # bundle, because the word "docs" survives every such move.
    #
    # The entry point is opened UNDERNEATH the named directory rather than
    # compared to `docs_root()`. Asserting the two agree pins consistency, not
    # correctness: pointed at a plausible wrong root, `docs_root()` and the
    # epilog move together and this stayed green (PR #350 review, mutation 2).
    from partspec.docs import docs_root

    root = docs_root()
    assert root is not None, "the checkout should locate its own documents"
    named = [line.strip() for line in epilog.splitlines() if line.startswith("  /")]
    assert named, f"--help names no directory:\n{epilog}"
    assert any(Path(line, "docs", "AGENT-CONTRACT.md").is_file() for line in named), (
        f"--help names {named}, and the contract is under none of them"
    )


def test_every_engine_factory_documents_how_it_finds_the_part():
    """`openscad` had a docstring; `build123d` and `cadquery` had none.

    Those two are the entry point for both Python engines, and the thing they
    do not say is the thing that bites: partspec calls a NAMED CALLABLE,
    defaulting to `make_part`, with the contract's params as keyword
    arguments. An agent evaluating a CadQuery library assumed CQGI's
    module-level `result` — the convention that library's own shims use — and
    was corrected only by the build failing.

    Scoped to the property, not to the two functions that were missing one: a
    fourth engine added tomorrow is covered without touching this test. That
    is the lesson of the `--no-config` guard, which searched the justfile
    because the justfile is where its bug was found, and so missed the same
    bug in the release workflow.
    """
    import inspect

    import partspec
    from partspec.contract import Source

    # `isfunction` first: `__all__` also carries exception classes, and
    # `inspect.signature` raises outright on some builtin types.
    factories = {
        name: obj
        for name in partspec.__all__
        if inspect.isfunction(obj := getattr(partspec, name))
        and inspect.signature(obj).return_annotation in (Source, "Source")
    }
    assert len(factories) >= 3, f"expected one factory per engine, found {sorted(factories)}"
    undocumented = sorted(name for name, obj in factories.items() if not inspect.getdoc(obj))
    assert not undocumented, (
        f"engine factories with no docstring: {undocumented} — `inspect.getdoc` is "
        "where an installed user learns the API, because the wheel ships no docs"
    )


@needs_scad_tier
def test_the_readme_console_block_is_what_the_console_prints():
    """The front page quotes a run. The run must still say that.

    `test_the_readme_example_is_the_real_contract` compares the *contract*
    shape and never looks at the transcript below it, so the quoted output
    drifted the moment a message changed — which is exactly what happened when
    the attribution advisory gained its escape hatch: the README went on
    showing the previous sentence, and nothing failed.

    This is not a phrase search. The phrases come from the README and the
    assertion is that the tool PRODUCES them — an executable claim about the
    front page, which is what this module is for. Path and version lines are
    skipped because they are environment, not claim.
    """
    import subprocess
    import sys

    block = re.search(
        r"```console\n\$ (partspec check examples/spacer/spec\.py:spacer)\n(.*?)```",
        README.read_text(),
        re.S,
    )
    assert block is not None, "the README no longer shows a spacer run"

    result = subprocess.run(
        [sys.executable, "-m", "partspec", *block.group(1).split()[1:]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    actual = result.stdout + result.stderr
    quoted = [
        line.strip() for line in block.group(2).splitlines() if line.strip() and "/" not in line
    ]
    assert quoted, "nothing quoted to check"
    missing = [line for line in quoted if line not in actual]
    assert not missing, (
        "the README quotes console output the tool no longer prints:\n  "
        + "\n  ".join(missing)
        + f"\n--- actual ---\n{actual}"
    )


@needs_scad_tier
def test_the_spacer_exemplars_diff_transcript_is_what_the_console_prints(tmp_path: Path):
    """The exemplar quotes a `diff` run. The run must still say that.

    #361: PR #351 committed this transcript, PR #353 changed what the summary
    line can say, and the README kept the old text through three green gates —
    `test_the_readme_console_block_is_what_the_console_prints` reads the ROOT
    README, nothing in the suite read `examples/spacer/README.md` at all, and
    `just example-spacer` runs `check --expect` and never `diff`. A falsified
    document with `just check`, `just test` and a CI job all green over it.

    The recipe was the issue's own preferred remedy and is the wrong half by
    itself: `just example-spacer` gates the console contract by PRINTING it for
    a human, so a `diff` step added there would have exited 1 over the very
    summary line that had drifted and CI would still have been green. What
    kills that mutation is comparing the quoted text to the produced text,
    which is what this module is for.

    So the transcript is REPLAYED rather than read: every `$` line is executed,
    the narrative `# ... now edit BORE_D ...` line is applied as the edit it
    describes, every quoted output line must appear in what the tool printed,
    and every `echo $?` must match the exit code that came back. A command
    shape the replay does not know fails loudly instead of being skipped —
    silence must not read as success here either.

    Run against a COPY. The transcript's second half edits the contract, and
    the checkout's own `examples/spacer/spec.py` is the exemplar under `--pin`.
    """
    import shlex
    import shutil

    readme = ROOT / "examples" / "spacer" / "README.md"
    text = readme.read_text()
    block = next(
        (
            m.group(1)
            for m in re.finditer(r"```console\n(.*?)```", text, re.S)
            if "partspec diff" in m.group(1)
        ),
        None,
    )
    assert block is not None, "the exemplar no longer shows a diff run"

    work = tmp_path / "examples" / "spacer"
    work.mkdir(parents=True)
    for name in ("spec.py", "spacer.scad", "claims.lock"):
        shutil.copy(ROOT / "examples" / "spacer" / name, work / name)

    steps: list[tuple[str, str, list[str]]] = []
    for line in block.splitlines():
        if line.startswith("$ "):
            steps.append(("cmd", line[2:], []))
        elif line.startswith("#"):
            steps.append(("note", line, []))
        elif line.strip():
            assert steps, "the transcript opens with output and no command"
            steps[-1][2].append(line)

    edits = 0
    last: subprocess.CompletedProcess[str] | None = None
    for kind, line, quoted in steps:
        if kind == "note":
            edit = re.search(r"edit (\w+): ([\d.]+) -> ([\d.]+)", line)
            if edit is None:
                continue
            name, before_v, after_v = edit.groups()
            spec = work / "spec.py"
            before, after = spec.read_text(), None
            after = before.replace(f"{name} = {before_v}", f"{name} = {after_v}", 1)
            assert after != before, f"the transcript says {line!r}; the contract has no such line"
            spec.write_text(after)
            edits += 1
            continue

        argv = shlex.split(line, comments=True)
        redirect = None
        if ">" in argv:
            cut = argv.index(">")
            redirect, argv = tmp_path / argv[cut + 1], argv[:cut]

        if argv[0] == "partspec":
            last = subprocess.run(
                [sys.executable, "-m", "partspec", *argv[1:]],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                check=False,
            )
            if redirect is not None:
                redirect.write_text(last.stdout)
                printed = last.stderr
            else:
                printed = last.stdout + last.stderr
            # Per produced LINE, not a substring of the whole blob: #353
            # falsified this README by APPENDING to the summary line, and the
            # stale line is a substring of the line that replaced it.
            produced = {ln.strip() for ln in printed.splitlines()}
            # A floor, because `quoted <= produced` is vacuous when `quoted` is
            # empty: without it the README's whole console contract for this
            # command can be DELETED and the gate stays green. A `--quiet` step
            # legitimately prints nothing, so there the emptiness is the claim
            # and is asserted in the other direction.
            if "--quiet" in argv:
                assert not quoted and not printed.strip(), (
                    f"`{line}` is --quiet; the exemplar shows {quoted!r} and it printed {printed!r}"
                )
            else:
                assert quoted, (
                    f"the exemplar runs `{line}` and quotes nothing it printed; "
                    "a step with no expected output asserts nothing"
                )
            missing = [q for q in quoted if q.strip() not in produced]
            assert not missing, (
                f"the exemplar quotes console output `{line}` no longer prints:\n  "
                + "\n  ".join(missing)
                + f"\n--- actual ---\n{printed}"
            )
        elif argv[0] == "cp":
            shutil.copy(tmp_path / argv[1], tmp_path / argv[2])
        elif argv[:2] == ["echo", "$?"]:
            assert last is not None, "`echo $?` with nothing run before it"
            assert [q.split()[0] for q in quoted] == [str(last.returncode)], (
                f"the exemplar quotes {[q.split()[0] for q in quoted]} for the exit code and "
                f"the run exited {last.returncode}\n--- stderr ---\n{last.stderr}"
            )
        else:
            pytest.fail(f"the transcript grew a command this replay cannot run: {line!r}")

    assert edits == 1, "the transcript no longer says which edit produces the drift it shows"

    # The entry quoted below the transcript is the same artifact, so it is the
    # same claim: `drift.json` must carry it verbatim, not merely resemble it.
    fences = re.findall(r"```json\n(.*?)```", text, re.S)
    assert len(fences) == 1, "the exemplar's quoted drift entry has moved; this test lost it"
    entry = json.loads(fences[0])
    produced = json.loads((tmp_path / "drift.json").read_text())["checks"]
    match = [c for c in produced if c["id"] == entry["id"]]
    assert match == [entry], (
        f"the exemplar quotes a drift entry `diff` no longer produces:\n"
        f"  quoted:   {entry}\n  produced: {match}"
    )


def test_the_spec_samples_show_the_version_the_tool_actually_emits():
    """A sample is what a consumer copies, so its values must be real.

    `SPEC-diff.md` showed `"version": "0.2.0"` for `partspec-diff`, which emits
    the **partspec** version and has never had one of its own — not a stale
    value but a fictional one (#219). Correcting it to a real number fixed that
    instance and left the mechanism: `SPEC-report.md`'s sample had drifted the
    same way, `0.1.0` against a shipped 0.7.x, and the corrected literals would
    have gone stale again at the next bump with nothing to notice (adversarial
    review of #231).

    So the literal is pinned rather than trusted. The cost is one line in each
    spec per release, and the failure names both files and the value to use;
    the alternative is a normative document quietly describing a version its
    reader cannot get.
    """
    from partspec.report import tool_version

    installed = tool_version()
    for name in ("SPEC-report.md", "SPEC-diff.md"):
        text = (DOCS / name).read_text()
        shown = re.findall(r'"tool":\s*\{\s*"name":\s*"[\w-]+",\s*"version":\s*"([^"]+)"', text)
        assert shown, f"{name} no longer shows a tool block; this test has lost its subject"
        assert all(v == installed for v in shown), (
            f"{name} samples a tool version of {sorted(set(shown))} and the package is "
            f"{installed}. A sample is what a consumer copies: update the literal."
        )


@needs_openscad
def test_every_openscad_fence_in_the_docs_parses():
    """A fenced example a reader copies must at least be OpenSCAD, and must
    build the part it is written to show.

    A mechanical rewrap of `SPEC-contract.md` once pushed the trailing word of
    a `//` comment onto its own line *inside* the fence, so the flagship
    example of §4.12 -- the clearance pattern the section exists to recommend
    -- stopped parsing, while `skills/`' copy of the same block stayed intact.
    Nothing caught it: `just check` does not read fenced code, and the two
    documents silently disagreed (review of PR #313).

    Covers ```openscad and ```scad alike -- `skills/openscad-authoring`
    uses the short form, and a guard that misses the document teaching
    OpenSCAD would be the wrong half.

    `examples/**` is globbed for the same reason and it is the half that was
    missing (#366): an exemplar README is where a snippet is most likely to be
    copied verbatim, and PR #364 shipped one broken fence into `docs/` and an
    identical one into `examples/clearance/README.md`. The `docs/` copy turned
    this suite red; the `examples/` copy was invisible to it.

    Exit status alone is not the assertion, and used to be. Measured on both
    pinned engines: delete the `CLEAR = 1.5;` line a fence depends on and both
    export rc 0 with `WARNING: Ignoring unknown variable 'CLEAR'` -- a sphere
    at the default radius instead of the prescribed one, which is precisely the
    defect this guard exists to catch. So an unresolved NAME fails the fence,
    using the engine guard's own vocabulary (`_UNRESOLVED_NAME_MARKERS`) so the
    two cannot drift apart.

    Three NAMES are exempted, not the module marker: the blocks are fragments
    and two of them legitimately call modules they do not define
    (`SPEC-contract.md` §4.12 and `skills/contract-authoring/SKILL.md`,
    `a`/`b`/`grown_b`). An unknown MODULE renders nothing where it is called,
    which a reader of a fragment expects; an unknown VARIABLE substitutes
    `undef` into a dimension, which nobody does. Exempting the marker would
    have exempted the typo too: a fence that calls the module it defines and
    misspells the call renders nothing and used to pass.
    """
    import re
    import subprocess
    import tempfile

    from partspec.engines.openscad import _UNRESOLVED_NAME_MARKERS

    exempt = "Ignoring unknown module"
    exempt_names = {"a", "b", "grown_b"}
    assert exempt in _UNRESOLVED_NAME_MARKERS, (
        "the engine guard no longer spells the module marker this way; the fence "
        "exemption is now silently wider or narrower than it was measured to be"
    )
    fatal = tuple(m for m in _UNRESOLVED_NAME_MARKERS if m != exempt)
    assert fatal, "every name marker was exempted; this guard asserts nothing"

    fences: list[tuple[str, str]] = []
    for md in (
        sorted(ROOT.glob("docs/*.md"))
        + sorted(ROOT.glob("skills/**/*.md"))
        + sorted(ROOT.glob("examples/**/*.md"))
    ):
        for block in re.findall(r"```(?:openscad|scad)\n(.*?)```", md.read_text(), re.S):
            fences.append((md.relative_to(ROOT).as_posix(), block))
    assert fences, "no openscad fences found; the query is wrong, not the docs"
    assert any(name.startswith("examples/") for name, _ in fences), (
        "no fence under examples/ -- the glob widened in #366 has lost its subject"
    )
    assert OPENSCAD is not None  # guaranteed by @needs_openscad

    with tempfile.TemporaryDirectory(prefix="partspec-fence-") as tmp:
        for name, block in fences:
            src = Path(tmp) / "fence.scad"
            src.write_text(block)
            proc = subprocess.run(
                [OPENSCAD, "-o", str(Path(tmp) / "fence.csg"), str(src)],
                capture_output=True,
                text=True,
                check=False,
            )
            # returncode, not just the absence of "Parser error": a fence can
            # be syntactically valid and still fail to export, and the
            # docstring claims the export succeeds.
            assert proc.returncode == 0, (
                f"{name}: fenced openscad did not export\n{proc.stderr}\n---\n{block}"
            )
            unresolved = [
                line
                for line in proc.stderr.splitlines()
                if any(marker in line for marker in fatal)
                or (
                    exempt in line
                    # A name the pattern cannot read is NOT exempt: both engines
                    # print `Ignoring unknown module '$weird'`, and `\w+` would
                    # return None, drop the line, and say nothing -- a guard
                    # degrading to silence, which is the shape this file refuses.
                    and (named := re.search(rf"{re.escape(exempt)} '([\w$]+)'", line)) is not None
                    and named.group(1) not in exempt_names
                )
                or (exempt in line and re.search(rf"{re.escape(exempt)} '", line) is None)
            ]
            assert not unresolved, (
                f"{name}: the fence exported, and the engine could not resolve a name in "
                f"it -- so what it built is not what it shows\n"
                + "\n".join(unresolved)
                + f"\n---\n{block}"
            )


def test_the_agents_project_section_stays_an_orientation_not_an_archive():
    """#280: release narrative accreted here because nothing evicted it.

    Measured per tag with this function's own metric, `## Project` ran
    36 → 40 → 43 → 50 → 57 → 72 → 90 across v0.7.0..v0.7.6 while the file grew
    97 lines, so 56% of everything AGENTS.md gained in six releases was
    reverse-chronological prose about those releases, each one prepending a
    paragraph and demoting the last. The cost was not length. It was that
    `docs/AGENT-CONTRACT.md`, the document telling an agent how to drive this
    tool, was named exactly once in the whole file: a parenthetical inside the
    v0.7.0 paragraph, reachable only by reading the archaeology.

    The bound is the eviction rule the section never had, not a style rule
    about how much orientation is right. It is set so that ONE unevicted
    release trips it: the largest single-release growth in that series is +18
    (v0.7.6), and the section is 25 lines, so 43 > 40 fails. An earlier draft
    said 45 and claimed the same property; 25 + 18 = 43 passes 45, so that
    bound needed two releases and the justification was never run.
    """
    lines = (ROOT / "AGENTS.md").read_text().splitlines()
    start = lines.index("## Project")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
    section = end - start

    assert section <= 40, (
        f"AGENTS.md '## Project' is {section} lines. Release history belongs in "
        f"CHANGELOG.md; this section says what partspec is, what property it "
        f"holds, and where to start reading"
    )


def test_the_readme_trust_transcript_is_what_actually_happens(tmp_path: Path):
    """#278: the README's own demonstration, executed rather than transcribed.

    The section exists to say that a contract is code and runs before anything
    validates it, so the transcript under it is the whole argument. Two drafts
    of it were written by hand and both were wrong -- the first dropped the
    traceback and misquoted the diagnostic; the second listed the directory
    afterwards as `EVIDENCE.txt  handed_to_me.py` and missed `outputs`, which
    `check` creates for its placeholder report on exactly this failure path.

    Nothing gated it, which is why it shipped twice. This runs the scenario and
    holds the README to it: the side effect happened, the exit code is what is
    printed, and the listing is the listing.
    """
    readme = README.read_text()
    block = re.search(r"```console\n\$ ls\nhanded_to_me\.py\n(.*?)```", readme, re.S)
    assert block is not None, "the README no longer shows the trust-boundary transcript"
    body = block.group(1)

    contract = tmp_path / "handed_to_me.py"
    contract.write_text(
        "from pathlib import Path\n"
        "from partspec import Part\n\n"
        'Path("EVIDENCE.txt").write_text("import-scope code ran\\n")\n\n'
        "def widget() -> Part:\n"
        '    return Part("widget", model="nope")\n'
    )
    proc = subprocess.run(
        [sys.executable, "-m", "partspec", "check", f"{contract}:widget"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )

    shown_exit = re.search(r"\$ echo \$\?\n(\d+)", body)
    assert shown_exit is not None, "the transcript no longer shows its exit code"
    assert proc.returncode == int(shown_exit.group(1)), (
        f"the README shows exit {shown_exit.group(1)}, the run exits {proc.returncode}"
    )

    # The point of the section: it ran before the contract was rejected.
    assert (tmp_path / "EVIDENCE.txt").read_text() == "import-scope code ran\n"

    # EVERY line the transcript shows as output, taken FROM the transcript --
    # hardcoding them here would only check this file against itself, which is
    # how a misquote survives. The one exemption is the elision marker: the
    # traceback's middle carries absolute paths that cannot be reproduced.
    #
    # A first version filtered to lines starting `partspec:` or `  the `, and
    # its comment claimed to check every quoted line. It did not: a bogus
    # traceback header, an invented `warning:` line, and deleting the traceback
    # outright all passed.
    def is_elision(line: str) -> bool:
        """Any marker that visibly says something was cut, not one spelling."""
        stripped = line.strip()
        return stripped.startswith("...") or "elided" in stripped

    shown = body.split("$ echo $?")[0].splitlines()
    quoted = [line for line in shown[1:] if line and not is_elision(line)]
    assert quoted, "the transcript no longer quotes any output"

    # Membership among the printed LINES, not a substring of the whole blob.
    # `in proc.stderr` accepted any fragment of any line, so a hand-wrapped
    # copy of the diagnostic passed -- and that line is 99 characters against
    # this repo's 100-column wrap, so the next word added to the message
    # invites exactly that wrap. Hand-transcription drift is the only thing
    # this test exists to catch.
    printed = proc.stderr.splitlines()
    for line in quoted:
        assert line in printed, f"the README quotes {line!r}; the run does not print it"

    # Eliding is fine; eliding silently is not. Deleting the traceback and its
    # marker leaves a transcript that reads as the whole of what was printed,
    # and every remaining line still checks out -- so completeness needs its
    # own assertion rather than falling out of the per-line one.
    if len(quoted) < len([line for line in printed if line.strip()]):
        assert any(is_elision(line) for line in shown), (
            f"the transcript shows {len(quoted)} of "
            f"{len([x for x in printed if x.strip()])} printed lines "
            f"without marking the cut"
        )

    # And the command it shows is the command that was run. Recorded as
    # `partspec check <file>:widget`, invoked as `python -m partspec check
    # <abs>:widget`, so the verb and the target's tail are what can be compared
    # -- but they are what the section rests on.
    invocation = shown[0]
    assert invocation.startswith("$ partspec "), (
        f"transcript no longer opens on a command: {invocation!r}"
    )
    verb, target = invocation.removeprefix("$ partspec ").split()
    assert verb == "check", f"the transcript shows `{verb}`; the test runs `check`"
    assert target == f"{contract.name}:widget", (
        f"the transcript checks {target!r}; the test checks {contract.name}:widget"
    )

    shown_listing = re.search(r"\$ ls\n([^\n]+)\n?\Z", body)
    assert shown_listing is not None, "the transcript no longer ends with a listing"
    assert sorted(shown_listing.group(1).split()) == sorted(p.name for p in tmp_path.iterdir()), (
        "the README's listing is not what the run leaves behind"
    )


def test_the_docs_index_routes_to_every_document_beside_it():
    """#279: `docs/` is the URL both PyPI and `partspec --help` advertise.

    Without an index GitHub renders that as a bare listing of ten filenames
    over five thousand lines, where AGENT-CONTRACT.md -- 260 lines, and the
    one to start with -- is indistinguishable from SPEC-contract's 1313.

    The index is only worth having if it stays complete, and the failure it
    prevents already happened once: AGENT-CONTRACT.md, LINT.md and
    FAILURE-MODES.md were all added on 2026-08-08, and only FAILURE-MODES
    was added to README's Documentation list. The other two stayed reachable
    -- AGENT-CONTRACT.md from two places in README's prose, LINT.md from one
    -- so nothing was unreachable; what was missing was any enumeration a
    reader could use to find out what exists. That is the gap an index
    closes and a link in a paragraph does not.

    Both directions. A document the index does not route to is invisible at the
    entry point; a route to a target that does not exist is a dead link at it.
    Neither is a claim about what the index SAYS: the label is never compared
    to the target, so an index sending every reader to the wrong file would
    satisfy this. What it checks is which files are reachable, which is what a
    router is for.

    Fenced links do not count. GitHub renders them as literal text, so a
    document mentioned only inside a fenced block reaches nobody -- and the
    first version of this test read the raw bytes and passed exactly that.
    Fenced specifically: a four-space indented block is also a code block and
    is NOT stripped here, so a link buried in one still counts. Every code
    block in these docs is fenced, so that hole is unreached rather than
    closed.
    """
    index = DOCS / "README.md"
    assert index.is_file(), "docs/ has no index; both advertised URLs land on a bare listing"

    text = re.sub(r"```.*?```", "", index.read_text(), flags=re.S)

    targets = set()
    for match in re.finditer(r"\]\((?!https?://|#)([^)]+)\)", text):
        # `./LINT.md`, `LINT.md#tiers` and `LINT.md "title"` are all ordinary
        # Markdown that GitHub resolves. The first version rejected all three,
        # which forbade the index from deep-linking -- the thing a router most
        # wants to do.
        target = match.group(1).split()[0].split("#")[0].removeprefix("./")
        if target:
            targets.add(target)

    present = {p.name for p in DOCS.glob("*.md")} - {"README.md"}
    missing = present - targets
    assert missing == set(), (
        f"docs/README.md routes to nothing for: {sorted(missing)} — "
        f"a reader landing on the advertised URL cannot tell they exist"
    )

    # Links out of docs/ are allowed and resolved against the tree, so the index
    # can point at what it recommends rather than naming it in backticks.
    dead = sorted(t for t in targets if not (index.parent / t).exists())
    assert dead == [], f"docs/README.md links targets that are not there: {dead}"


def test_every_citation_of_a_bundled_tree_resolves_where_the_reader_is_sent():
    """The regression #349 was, stated as a property of the corpus.

    `docs/` and `skills/` ship in the wheel and the citations inside them are
    repo-relative, so each one has to open against the directory
    `partspec --docs` returns — which is the repository root here and the
    bundled copy in an install, by construction of the same layout.

    Scoped to those two trees on purpose. A citation of `examples/`, `tests/`
    or the source tree names something the wheel does not carry, and
    `docs/README.md` says so rather than pretending otherwise; policing those
    here would demand churn this test cannot justify. What it does police is
    the class that routes a reader between the shipped documents, which is the
    one that was silently dead.
    """
    from partspec.docs import docs_root

    root = docs_root()
    assert root is not None, "the checkout should locate its own documents"

    cite = re.compile(r"`((?:docs|skills)/[\w./-]*\.\w+)`")
    bundled = [p for p in shipped_markdown() if p.is_relative_to(DOCS) or "skills" in p.parts]
    assert bundled, "no bundled documents scanned — this guard has lost its subject"

    checked, dangling = 0, []
    for doc in bundled:
        text = prose_of(doc.read_text())
        for m in cite.finditer(text):
            checked += 1
            if not (root / m.group(1)).is_file():
                line = text[: m.start()].count("\n") + 1
                dangling.append(f"{doc.relative_to(ROOT)}:{line} -> {m.group(1)}")
    assert checked, "matched no citations at all; the regex has stopped reaching them"
    assert not dangling, (
        "these route a reader to a path that does not exist under "
        f"{root}:\n  " + "\n  ".join(dangling)
    )
