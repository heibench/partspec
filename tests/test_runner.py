"""The runner: contract in, report out — and the internals that path relies on.

Most of this file is end-to-end. Those are the tests that would catch the tool
lying, and each asserts a claim from `SPEC-report.md` that the rest of the
design depends on.

The last section is not. `# runner internals, exercised directly` drives
`_run_geometry_check` with a stub, no engine and no report. It is here because
`runner.py` owns that helper.

This docstring says so because the #153 split added that section while the
first line still read "End-to-end" — the same false module docstring #158
retracted one file over, committed in the commit that retracted it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support import needs_build123d, needs_openscad, needs_scad_tier

from partspec import Part, Status, Verdict, openscad, run
from partspec.runner import _run_parameter_check, _unresolved_diagnosis

FIXTURES = Path(__file__).parent / "fixtures"

# 30x20x10 block with a 6x6 square through-hole.
BLOCK = FIXTURES / "block_with_hole.scad"
PLATE = FIXTURES / "parametric_plate.scad"
TWO = FIXTURES / "two_bodies.scad"


def _status(report, check_id: str) -> Status:
    return next(c.status for c in report.checks if c.id == check_id)


# --------------------------------------------------------------------------
# the happy path
# --------------------------------------------------------------------------


@needs_scad_tier
def test_a_satisfied_contract_passes(tmp_path: Path):
    p = Part("block", openscad(BLOCK))
    p.envelope(max=(30, 20, 10))
    p.watertight()
    p.solid_count(1)
    p.genus(1)

    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.PASS
    assert report.exit_code == 0
    assert _status(report, "builds") is Status.PASS


@needs_scad_tier
def test_a_violated_geometry_check_fails(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).envelope(max=(5, 5, 5))
    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.FAIL
    assert report.exit_code == 1


@needs_scad_tier
def test_measurements_are_recorded_on_pass(tmp_path: Path):
    """What lets a future diff report drift on a check that still passes."""
    p = Part("block", openscad(BLOCK)).envelope(max=(30, 20, 10))
    report = run(p, out_dir=tmp_path)
    envelope = next(c for c in report.checks if c.id == "envelope")
    assert envelope.status is Status.PASS
    assert envelope.measurement is not None
    assert envelope.measurement.value == pytest.approx((30.0, 20.0, 10.0))


@needs_scad_tier
def test_provenance_is_recorded(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).watertight()
    report = run(p, out_dir=tmp_path)
    assert report.geometry["triangles"] > 0
    assert report.geometry["distinct_normals"] > 0
    assert report.engine["kind"] == "openscad"
    assert report.engine["backend"] == "mesh"


# --------------------------------------------------------------------------
# the guards
# --------------------------------------------------------------------------


@needs_scad_tier
def test_a_contract_that_asserts_nothing_is_empty_not_pass(tmp_path: Path):
    """Vacuous green. The implicit `builds` check must not satisfy the emptiness
    test — otherwise the tool defeats its own most important guard."""
    report = run(Part("vacuous", openscad(BLOCK)), out_dir=tmp_path)
    assert report.verdict is Verdict.EMPTY
    assert report.exit_code == 3
    assert _status(report, "builds") is Status.PASS, "builds itself still ran and passed"


@needs_scad_tier
def test_unsupported_does_not_read_as_green(tmp_path: Path):
    """genus is refused for multi-body parts; the part must not pass anyway."""
    p = Part("two", openscad(TWO))
    p.solid_count(2)
    p.genus(0)

    report = run(p, out_dir=tmp_path)
    assert _status(report, "solid_count") is Status.PASS
    assert _status(report, "genus") is Status.UNSUPPORTED
    assert report.verdict is Verdict.INCOMPLETE
    assert report.exit_code == 2, "not proven is not the same as fine"


# --------------------------------------------------------------------------
# provenance — the closure, not just the entry file
# --------------------------------------------------------------------------


def _closure_of(source) -> dict:
    from partspec.runner import _closure

    result = _closure(source)
    assert result is not None
    return result


def test_a_transitive_edit_is_visible_where_source_digest_is_blind(tmp_path: Path):
    """The reason the closure exists.

    An OpenSCAD entry file is routinely a small fraction of its own build — the
    gridfinity bin in the dogfood corpus is one file of sixteen. Editing a helper
    three levels down changes the part and leaves `source_digest` identical, so
    two genuinely different builds compare as the same inputs.
    """
    (tmp_path / "helper.scad").write_text("W = 10;\n")
    (tmp_path / "mid.scad").write_text("include <helper.scad>\n")
    entry = tmp_path / "a.scad"
    entry.write_text("include <mid.scad>\ncube([W, W, W]);\n")

    source = openscad(entry)
    before = _closure_of(source)
    entry_digest_before = entry.read_bytes()

    (tmp_path / "helper.scad").write_text("W = 20;\n")  # a different part
    after = _closure_of(source)

    assert entry.read_bytes() == entry_digest_before, "premise: the entry file is untouched"
    assert before["files"] == after["files"] == 3
    assert before["digest"] != after["digest"], "the closure must see it"


def test_the_closure_digest_does_not_depend_on_where_the_tree_lives(tmp_path: Path):
    """Digested over sorted content hashes rather than paths, because the whole
    point of a comparator is comparing a CI run against a laptop run, and a
    path-sensitive digest would differ on every one of them."""
    import shutil

    a = tmp_path / "one"
    a.mkdir()
    (a / "lib.scad").write_text("X = 1;\n")
    (a / "top.scad").write_text("include <lib.scad>\n")
    b = tmp_path / "two"
    shutil.copytree(a, b)

    assert (
        _closure_of(openscad(a / "top.scad"))["digest"]
        == (_closure_of(openscad(b / "top.scad"))["digest"])
    )


def test_a_partial_closure_says_so_in_the_report(tmp_path: Path):
    entry = tmp_path / "a.scad"
    entry.write_text("include <gone.scad>\n")
    closure = _closure_of(openscad(entry))
    assert closure["partial"] is True
    assert closure["unresolved"] == ["gone.scad"]


def test_a_complete_closure_carries_no_partial_flag(tmp_path: Path):
    entry = tmp_path / "a.scad"
    entry.write_text("cube([1,2,3]);\n")
    assert "partial" not in _closure_of(openscad(entry))


@pytest.mark.parametrize(
    ("body", "unseen"),
    [
        ("cube([1,2,3]);\n", []),
        ("include <gone.scad>\n", ["unresolved_includes"]),
        ('import("part.stl");\n', ["external_data_reads"]),
        ('import_stl("part.stl");\n', ["external_data_reads"]),
        ('surface("h.dat");\n', ["external_data_reads"]),
        (
            'include <gone.scad>\nsurface("h.dat");\n',
            ["external_data_reads", "unresolved_includes"],
        ),
    ],
)
def test_partial_is_exactly_whether_anything_was_left_unseen(
    tmp_path: Path, body: str, unseen: list[str]
):
    """`partial == bool(unseen)`, in every case the OpenSCAD tier can reach.

    `partial` used to be `bool(unresolved) or reads_external_data` and is now
    derived from the named gaps. The two must agree exactly, or #190's stage 3
    inherits a `diff` whose verdicts moved under it: `_closure_state` keys on
    this boolean and on nothing else in the closure.
    """
    entry = tmp_path / "a.scad"
    entry.write_text(body)
    closure = _closure_of(openscad(entry))
    assert closure["unseen"] == unseen
    assert closure.get("partial", False) is bool(unseen)


def test_the_openscad_tier_records_an_empty_imports_map_not_a_missing_one(tmp_path: Path):
    """This tier renders in a subprocess and imports nothing, which is a
    different statement from "not recorded" — the reading an absent `imports`
    carries in a report written before 0.7.5."""
    entry = tmp_path / "a.scad"
    entry.write_text("cube([1,2,3]);\n")
    assert _closure_of(openscad(entry))["imports"] == {}


def test_the_python_tier_is_partial_because_of_reads_no_python_can_see(tmp_path: Path):
    """The irreducible gap, and the reason `partial` cannot become false here:
    `OCP.StlAPI_Reader().Read()` read an STL off disk and produced zero `open`
    audit events. A closure on this tier is never complete, whatever it
    covers."""
    from partspec import build123d
    from partspec.runner import _python_closure

    model = tmp_path / "m.py"
    model.write_text("def make_part():\n    pass\n")
    closure = _python_closure(build123d(model), None)
    assert "native_reads" in closure["unseen"]
    assert closure["partial"] is True
    assert closure["partial"] is bool(closure["unseen"])


def test_the_python_closure_is_not_computed_before_the_build(tmp_path: Path):
    """A Python model's imports are not knowable until it has run.

    So `_closure` — which runs while the report is being constructed — declines,
    and the runner fills the field in after a successful build instead.
    """
    from partspec import build123d
    from partspec.runner import _closure

    model = tmp_path / "m.py"
    model.write_text("def make_part():\n    pass\n")
    assert _closure(build123d(model)) is None


@needs_build123d
def test_a_helper_beside_a_python_model_is_part_of_the_build(tmp_path: Path):
    """The same gap the OpenSCAD closure closed, on the other tier.

    `engines/pycad.py` puts the model's directory on `sys.path` specifically so
    a model can import helpers beside it, which makes those helpers build
    inputs by design. Editing one changed the part and left `source_digest`
    byte-identical, so two different builds compared as the same input.
    """
    (tmp_path / "dims.py").write_text("SIZE = 10.0\n")
    model = tmp_path / "m.py"
    model.write_text(
        "from build123d import Box\nfrom dims import SIZE\n\n\n"
        "def make_part():\n    return Box(SIZE, SIZE, SIZE)\n"
    )

    from partspec import build123d

    def closure_of() -> dict:
        report = run(Part("m", build123d(model)).watertight(), out_dir=tmp_path)
        assert report.verdict is Verdict.PASS, report.error
        assert report.source_closure is not None
        return report.source_closure

    model_before = model.read_bytes()
    before = closure_of()

    (tmp_path / "dims.py").write_text("SIZE = 20.0\n")  # a different part
    after = closure_of()

    assert model.read_bytes() == model_before, "premise: the model file is untouched"
    assert before["files"] == after["files"] == 2
    assert before["digest"] != after["digest"], "the closure must see the helper"
    assert after["partial"] is True, "Python can import from anywhere; never claim completeness"
    assert after["scope"] == "model_directory"


def test_the_contract_is_not_folded_into_the_source_closure(tmp_path: Path):
    """`contract_digest` already covers it, and a source closure that moved
    whenever a *claim* changed would answer a different question than the one
    it is named for."""
    from partspec.runner import _python_closure

    contract = tmp_path / "spec.py"
    contract.write_text("# a claim\n")
    model = tmp_path / "m.py"
    model.write_text("def make_part():\n    pass\n")

    from partspec import build123d

    closure = _python_closure(build123d(model), contract)
    assert closure["files"] == 0, "nothing imported yet, and the contract does not count"


@needs_scad_tier
def test_a_tier_that_cannot_answer_says_which_one_can(tmp_path: Path):
    """The capability-refusal path, which no contract could reach until
    `topology` existed: every other v0 check maps to a primitive both backends
    declare, so `requires` was never populated in a real report.

    A triangle mesh has no modelled faces, so this is refused *before* dispatch
    — the mesh backend does not declare the capability — rather than answered
    with a triangle count, which is the PartCAD failure (D12).
    """
    p = Part("block", openscad(BLOCK))
    p.topology(faces=6)

    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "topology")
    assert check.status is Status.UNSUPPORTED
    assert check.requires == "occt"
    assert check.measurement is None, "a refusal must not carry a number"
    assert report.verdict is Verdict.INCOMPLETE
    assert report.exit_code == 2


@needs_openscad
def test_a_failing_parameter_check_short_circuits_the_engine(tmp_path: Path):
    """Building geometry from inputs already rejected wastes time and produces a
    shape describing something the contract has ruled out."""
    p = Part("plate", openscad(PLATE, plate_x=40.0, plate_y=30.0, plate_z=4.0))
    p.requires("plate_x < plate_y")  # false
    p.envelope(max=(40, 30, 4))
    p.watertight()

    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.FAIL
    assert _status(report, "plate_x_lt_plate_y") is Status.FAIL
    assert _status(report, "builds") is Status.SKIPPED
    assert _status(report, "envelope") is Status.SKIPPED
    assert not (tmp_path / "parametric_plate.stl").exists(), "the engine must not have run"


@needs_openscad
def test_short_circuited_checks_are_present_not_omitted(tmp_path: Path):
    """An absent check is indistinguishable from one never declared."""
    p = Part("plate", openscad(PLATE, plate_x=1.0))
    p.requires("plate_x > 100")
    p.watertight()
    p.solid_count(1)

    report = run(p, out_dir=tmp_path)
    assert {c.id for c in report.checks} == {
        "plate_x_gt_100",
        "builds",
        "watertight",
        "solid_count",
    }
    assert report.counts()["total"] == 4


@needs_openscad
def test_a_failing_parameter_check_names_the_blocker(tmp_path: Path):
    p = Part("plate", openscad(PLATE, plate_x=1.0)).requires("plate_x > 100").watertight()
    report = run(p, out_dir=tmp_path)
    detail = next(c.detail for c in report.checks if c.id == "watertight")
    assert "plate_x_gt_100" in (detail or "")


@needs_openscad
def test_operands_are_recorded_on_a_failed_predicate(tmp_path: Path):
    p = Part("plate", openscad(PLATE, plate_x=40.0, plate_y=30.0)).requires("plate_x < plate_y")
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "requires")
    assert check.operands == {"plate_x": 40.0, "plate_y": 30.0}
    assert check.measurement is None and check.limit is None, "predicates are not measurements"


# --------------------------------------------------------------------------
# build failure
# --------------------------------------------------------------------------


@needs_openscad
def test_a_build_the_environment_prevented_is_not_a_failing_part(tmp_path: Path):
    """A missing source file is a fact about the machine, not about the design.

    This used to be `builds: fail` / `verdict: fail` / exit 1 -- the code that
    means "the part failed its contract". So a CI run on a box with no OpenSCAD
    installed reported every design as disproven, and exit 1 is the one an agent
    is most likely to answer by editing the model.
    """
    p = Part("missing", openscad(tmp_path / "nope.scad")).watertight()
    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.ERROR
    assert report.build_origin == "environment"
    assert _status(report, "builds") is Status.SKIPPED, "never reported as a failing check"
    assert _status(report, "watertight") is Status.SKIPPED


@needs_openscad
def test_a_design_that_does_not_compile_does_fail_builds(tmp_path: Path):
    """The other half of the split: this one *is* a statement about the part."""
    source = tmp_path / "bad.scad"
    source.write_text("this is not openscad;\n")
    p = Part("broken", openscad(source)).watertight()
    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.FAIL
    assert report.build_origin == "model"
    assert _status(report, "builds") is Status.FAIL
    assert _status(report, "watertight") is Status.SKIPPED
    # `build_stderr` exists so the #37 hint filter can never lose the
    # diagnosis, and nothing asserted the value survived the hop into the
    # report — `report.build_stderr = None` passed the whole suite.
    assert report.build_stderr, "the unabridged diagnosis must reach the report"
    assert "bad.scad" in report.build_stderr


def test_an_unknown_engine_errors_rather_than_pretending(tmp_path: Path):
    """A backend that pretended to measure would defeat the point of the tool."""
    from partspec.contract import Source

    p = Part("later", Source(engine="freecad", path=Path("model.py"))).watertight()
    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.ERROR
    assert report.exit_code == 4
    assert "unknown engine" in (report.error or "")
    assert all(c.status is Status.SKIPPED for c in report.checks)


def test_a_contract_error_skips_every_check(tmp_path: Path):
    """A malformed question has no answer, so nothing is reported as failed."""
    p = Part("bad", openscad(BLOCK)).requires("undeclared_name > 0")
    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.ERROR
    assert all(c.status is Status.SKIPPED for c in report.checks)
    assert "undeclared" in (report.error or "")


# --------------------------------------------------------------------------
# the artifact
# --------------------------------------------------------------------------


@needs_scad_tier
def test_the_report_written_to_disk_is_schema_shaped(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).watertight()
    report = run(p, out_dir=tmp_path, argv=["check", "x"])
    path = report.write(tmp_path)

    doc = json.loads(path.read_text())
    assert doc["schema_version"] == 1
    assert doc["counts"]["total"] == len(doc["checks"])
    assert sum(v for k, v in doc["counts"].items() if k != "total") == doc["counts"]["total"]
    assert doc["part"]["source_digest"].startswith("sha256:")
    assert doc["engine"]["backend"] == "mesh"
    # `argv` is passed in and was never read back, so emitting `[]` instead
    # passed the suite — and the invocation block exists so a reader can tell
    # what produced the artifact.
    assert doc["invocation"]["argv"] == ["check", "x"]
    assert doc["counts"] == {
        "total": 2,
        "pass": 2,
        "fail": 0,
        "approximate": 0,
        "unsupported": 0,
        "skipped": 0,
    }, "the per-status tally, not just its sum"


@needs_openscad
def test_digests_change_with_content(tmp_path: Path):
    scad = tmp_path / "m.scad"
    scad.write_text("cube(10);\n")
    first = run(Part("m", openscad(scad)).watertight(), out_dir=tmp_path).source_digest

    scad.write_text("cube(11);\n")
    second = run(Part("m", openscad(scad)).watertight(), out_dir=tmp_path).source_digest

    assert first != second


def test_the_part_block_carries_no_absolute_path(tmp_path: Path):
    """Two checkouts of the same tree at different locations must produce
    byte-identical `part` blocks.

    `part.source` was absolute after `_anchor` resolved it, so the committed
    example report leaked a developer home directory — undoing at the path layer
    exactly the machine-independence `source_closure` was built to have.
    """
    for location in ("checkout-a", "checkout-b"):
        root = tmp_path / location
        root.mkdir()
        (root / "box.scad").write_text("x = 10;\ncube([x, x, x]);\n")
        p = Part("paths", openscad(root / "box.scad", x=10.0)).watertight()
        report = run(p, out_dir=root / "out", contract_path=root / "spec.py")
        doc = report.to_json()["part"]
        assert doc["source"] == "box.scad"
        assert doc["contract"] == "spec.py"
        assert not any(str(v).startswith("/") or "\\" in str(v) for v in doc.values())


def test_the_contract_records_which_factory_was_invoked(tmp_path: Path):
    """#297. Two factories in one module returning parts with the same id
    produced BYTE-IDENTICAL `part` blocks, and `partspec diff` called them
    identical at exit 0.

    The distinguishing case is the digest, asserted here rather than assumed:
    it is module-scoped by design (§7.1), so it is EQUAL on both sides and
    cannot be what separates them. Asserting only that the two blocks differ
    would pass on a fixture where anything else differed too.
    """
    (tmp_path / "box.scad").write_text("cube([10, 10, 10]);\n")
    (tmp_path / "same.py").write_text("# two factories, one module\n")

    def block(factory: str | None) -> dict:
        part = Part("widget", openscad(tmp_path / "box.scad")).watertight()
        report = run(
            part,
            out_dir=tmp_path / "out",
            contract_path=tmp_path / "same.py",
            factory=factory,
        )
        return report.to_json()["part"]

    imperial, metric = block("imperial"), block("metric")
    assert imperial["contract"] == "same.py:imperial"
    assert metric["contract"] == "same.py:metric"
    assert imperial["contract_digest"] == metric["contract_digest"], (
        "module-scoped by design — so it is not what tells the two apart"
    )
    assert imperial != metric, "and the symbol is what does"
    assert block(None)["contract"] == "same.py", (
        "`run(factory=None)` records none — the library path. The CLI resolves the "
        "symbol and passes it even when the invocation named none (#343)"
    )


def test_a_parameter_unit_does_not_depend_on_the_python_literal(tmp_path: Path):
    """`40` and `40.0` are the same dimension. `_unit_for` used to give the first
    "count" and the second "mm", so editing a declared parameter between the two
    changed the recorded unit without changing the design — spurious drift in the
    field SPEC-report.md 7.2 exists to keep stable."""
    p = Part("units", openscad(tmp_path / "x.scad", a=40, b=40.0))
    p.param("a", min=1.0)
    p.param("b", min=1.0)
    results = [_run_parameter_check(s, p.source.params) for s in p.checks]
    assert {r.measurement.unit for r in results if r.measurement} == {"mm"}


def test_a_genuine_count_says_so(tmp_path: Path):
    p = Part("units", openscad(tmp_path / "x.scad", teeth=24))
    p.param("teeth", min=1, unit="count")
    result = _run_parameter_check(p.checks[0], p.source.params)
    assert result.measurement is not None
    assert result.measurement.unit == "count"


def test_the_report_records_the_invoked_method_and_param_mode(tmp_path: Path):
    # A method= build and a plain build were indistinguishable in the
    # artifact (#40); a reader of a SINGLE report must see which happened.
    (tmp_path / "lib.scad").write_text("module block(s = 5) { cube(s); }\n")
    p = Part("m", openscad(tmp_path / "lib.scad", method="block", s=8.0))
    p.watertight()
    report = run(p, out_dir=tmp_path / "out")
    assert report.engine["method"] == "block"
    assert report.engine["param_mode"] == "call"
    assert report.engine["source_rendered"] == "derived"


def test_a_define_build_states_the_default_entry(tmp_path: Path):
    p = Part("d", openscad(PLATE, plate_x=40.0, plate_y=30.0, plate_z=4.0))
    p.watertight()
    report = run(p, out_dir=tmp_path / "out")
    assert report.engine["method"] is None
    assert report.engine["param_mode"] == "define"
    assert "source_rendered" not in report.engine


@needs_build123d
def test_a_python_build_records_its_named_factory(tmp_path: Path):
    model = tmp_path / "m.py"
    model.write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(1, 1, 1)\n\n\n"
        "def wide():\n    return Box(20, 5, 2)\n"
    )
    from partspec import build123d

    p = Part("w", build123d(model, method="wide"))
    p.watertight()
    report = run(p, out_dir=tmp_path / "out")
    assert report.engine["method"] == "wide"
    # param_mode is the OpenSCAD -D/call distinction; a Python factory call
    # has no such split and must not pretend to.
    assert "param_mode" not in report.engine

    q = Part("d", build123d(model))
    q.watertight()
    default = run(q, out_dir=tmp_path / "out2")
    assert default.engine["method"] is None


def test_an_unpinned_run_still_carries_the_render_backend_key(tmp_path: Path):
    # Null = "the engine's default, whichever this version chose" — the run a
    # reader cannot infer, which is why omission was backwards (#41).
    p = Part("u", openscad(PLATE, plate_x=40.0, plate_y=30.0, plate_z=4.0))
    p.watertight()
    report = run(p, out_dir=tmp_path / "out")
    assert "render_backend" in report.engine
    assert report.engine["render_backend"] is None


def test_a_pinned_render_backend_reaches_the_report(tmp_path: Path):
    # The engine block is written before the build, so the pinned string is
    # assertable even where --backend would fail the render itself.
    p = Part("pin", openscad(PLATE, backend="CGAL", plate_x=40.0, plate_y=30.0, plate_z=4.0))
    p.watertight()
    report = run(p, out_dir=tmp_path / "out")
    assert report.engine["render_backend"] == "CGAL"


# --------------------------------------------------------------------------
# runner internals, exercised directly
#
# One test, filed here because `runner.py` owns the helper it drives. It runs
# no engine and touches no check: it hands `_run_geometry_check` a stub backend
# that DECLARES a primitive and then refuses it per-call, which no shipped
# backend does, so it is the only way `_refused`'s `requires=` field is
# exercised at all.
#
# It arrived here in #158 from `test_fillet_radius.py`, where the #153 split had
# filed it by the banner it sat under rather than by its subject. Two others
# arrived with it and have since gone on to `test_attribution.py` (#159), which
# is where the reader asking "which component failed?" now finds all six.
# --------------------------------------------------------------------------


def test_a_declared_primitive_that_refuses_still_names_the_tier():
    """`_refused` exists to guarantee `requires=` reaches the report, and PR
    #152's review proved that guarantee was untested: deleting the field from
    the helper passed all 770 tests.

    The reason is structural. Every `requires`-bearing refusal in the shipped
    backends belongs to a primitive that tier does not declare, so the
    capability gate intercepts first and sets `requires` itself — the helper's
    path is only reached when a backend DECLARES a primitive and then refuses
    per-call, which no shipped backend does today. A stub does, so the field
    the helper exists for is finally exercised.
    """
    from partspec.backend import Unsupported
    from partspec.contract import Part, build123d
    from partspec.runner import _run_geometry_check

    class _RefusesWhatItDeclares:
        kind = "stub"

        def capabilities(self):
            return frozenset({"volume"})

        def volume(self, a):
            return Unsupported("this stub cannot integrate", requires="occt")

    part = Part("subject", build123d("m.py"))
    part.volume(min=1.0)
    result = _run_geometry_check(part.checks[0], _RefusesWhatItDeclares(), None)

    assert result.status is Status.UNSUPPORTED
    assert result.detail == "this stub cannot integrate"
    assert result.requires == "occt", "the tier that would answer must survive into the report"


# --------------------------------------------------------------------------
# `p.empty()` — declaring that nothing is the intended result (#237, §4.12)
# --------------------------------------------------------------------------

_INTERFERENCE_PROBE = (
    "intersection() {{ cube([10, 10, 10]); translate([0, 0, {z}]) cube([10, 10, 10]); }}\n"
)


@needs_openscad
def test_a_declared_empty_part_passes_and_never_reaches_a_measurement(tmp_path: Path):
    """The interference probe's good answer, which had no way to be stated (#237).

    Two parts sharing no space render nothing. That is a real result and, for a
    probe, the passing one — but an empty build is a hard failure before any
    claim is evaluated, so `volume(max=0)` was SKIPPED rather than satisfied and
    the only gradeable outcome was the bad one.

    `builds` passes here: the engine ran, completed, and produced what the
    contract asked for. No `needs_scad_tier` on purpose — there is no mesh, so
    this never reaches the backend, which is the whole point.
    """
    scad = tmp_path / "clear.scad"
    scad.write_text(_INTERFERENCE_PROBE.format(z=15))
    p = Part("clear", openscad(scad))
    p.empty(id="no-shared-space")

    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.PASS, [c.to_json() for c in report.checks]

    builds = next(c for c in report.checks if c.kind == "builds")
    assert builds.status is Status.PASS
    assert next(c for c in report.checks if c.id == "no-shared-space").status is Status.PASS


@needs_build123d
def test_a_declared_empty_part_passes_on_the_occt_tier_too(tmp_path: Path):
    """#271: it could not pass there for ANY input, and §4.12 said it could.

    `a & b` on two disjoint solids returns an **empty Compound**, not a null
    shape and not an empty CadQuery stack — and those two were the only null
    results `produced_nothing` reached. So the natural spelling of a clearance
    probe on this tier landed in the ordinary build-failure branch, and the
    check that exists to grade the good outcome graded it as the bad one.

    Written as the probe rather than as `Compound()` on purpose: the constructed
    empty was already pinned (`test_an_empty_compound_is_a_build_error_not_an_assert`)
    and passed throughout, because what it pins is that a BuildError comes back
    at all. What nothing exercised was a real model arriving there.
    """
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text(
        "from build123d import Box, Pos\n\n\n"
        "def make_part():\n"
        "    return Box(40, 12, 8) & (Pos(0, 0, 18) * Box(16, 10, 3))\n"
    )
    p = Part("clear", build123d(model))
    p.empty(id="no-shared-space")

    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.PASS, [c.to_json() for c in report.checks]
    assert next(c for c in report.checks if c.kind == "builds").status is Status.PASS
    assert next(c for c in report.checks if c.id == "no-shared-space").status is Status.PASS


@needs_build123d
def test_an_undeclared_empty_result_still_fails_its_build_on_the_occt_tier(tmp_path: Path):
    """The half #271's fix must not have moved, and the reason it is safe.

    `produced_nothing` is read in exactly one place and only inside
    `if empty_specs`, so marking the empty-Compound path changes nothing for a
    contract that did not declare `empty`. For an ordinary part contract a null
    render is a real fault, and #237 asked for a way to declare the intent, not
    for the default to soften.
    """
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text(
        "from build123d import Box, Pos\n\n\n"
        "def make_part():\n"
        "    return Box(40, 12, 8) & (Pos(0, 0, 18) * Box(16, 10, 3))\n"
    )
    p = Part("oops", build123d(model))
    p.watertight()

    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.FAIL, [c.to_json() for c in report.checks]
    builds = next(c for c in report.checks if c.kind == "builds")
    assert builds.status is Status.FAIL
    assert "no geometry" in (builds.detail or "")


@needs_openscad
def test_an_empty_result_caused_by_an_unresolved_name_cannot_satisfy_it(tmp_path: Path):
    """The laundering guard, and the reason this check needed one (#237).

    An empty result means two different things and OpenSCAD 2021.01 reports them
    identically: a genuinely null intersection and a model whose geometry never
    existed both exit 1 with `Current top level object is empty.` and write no
    STL. Measured — the only difference is the WARNING lines above it.

    Without the guard this is the failure that matters: a misspelt module makes
    every interference probe pass, and the greener the run the more broken the
    contract. The detail names the line, because "declared empty, and it was"
    would be true and useless.
    """
    scad = tmp_path / "typo.scad"
    scad.write_text("include <no_such_lib.scad>\nintersection() { lib_a(); lib_b(); }\n")
    p = Part("typo", openscad(scad))
    p.empty(id="no-shared-space")

    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.FAIL, [c.to_json() for c in report.checks]

    result = next(c for c in report.checks if c.id == "no-shared-space")
    assert result.status is Status.FAIL
    assert result.detail is not None
    assert "could not resolve a name" in result.detail
    assert "lib_a" in result.detail or "no_such_lib" in result.detail


@needs_scad_tier
def test_a_part_that_builds_geometry_fails_its_declared_empty(tmp_path: Path):
    """The other direction: the parts DO share space, so the claim is disproven.

    This is the outcome an interference probe is written to catch, and it must read
    as a failed claim rather than as a passing build with nothing said about it.
    """
    scad = tmp_path / "overlap.scad"
    scad.write_text(_INTERFERENCE_PROBE.format(z=8))
    p = Part("overlap", openscad(scad))
    p.empty(id="no-shared-space")

    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.FAIL, [c.to_json() for c in report.checks]

    result = next(c for c in report.checks if c.id == "no-shared-space")
    assert result.status is Status.FAIL
    assert result.detail == "declared empty, but the part built geometry"
    assert next(c for c in report.checks if c.kind == "builds").status is Status.PASS


@needs_openscad
def test_the_empty_VERDICT_and_the_empty_CHECK_are_not_the_same_thing(tmp_path: Path):
    """One word, two unrelated meanings, and they meet in one contract.

    The verdict `empty` means a contract that declared NOTHING — the vacuous-green
    guard above, exit 3. The check `empty` means a contract that declared nothing
    was the RESULT. A part carrying only `p.empty()` is the case where both could
    plausibly apply, and it must take the second: it asserted something, and the
    assertion held.

    Nothing in the code can confuse them — a `Verdict` member and a `kind` string
    live in different namespaces and are never compared — so this pins the
    distinction that a READER can conflate, and that `SPEC-contract.md` §4.2 now
    spells out because `p.empty()` made the collision reachable (#237).
    """
    scad = tmp_path / "clear.scad"
    scad.write_text(_INTERFERENCE_PROBE.format(z=15))

    declared_nothing_is_the_result = Part("probe", openscad(scad))
    declared_nothing_is_the_result.empty()
    report = run(declared_nothing_is_the_result, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.PASS
    assert report.exit_code == 0

    # And the default id is the kind, which must not be mistaken for the verdict.
    assert [c.id for c in report.checks if c.kind == "empty"] == ["empty"]


@needs_openscad
def test_an_undeclared_empty_build_still_fails_exactly_as_before(tmp_path: Path):
    """`empty` is opt-in, and nothing else moves.

    For an ordinary part contract a null render IS a real fault, and #237 says
    so explicitly — it asks for a way to declare the intent, not for the default
    to soften. Pinned because the change touches the shared build-failure path,
    where a relaxation would be invisible until someone's broken part went green.
    """
    scad = tmp_path / "clear.scad"
    scad.write_text(_INTERFERENCE_PROBE.format(z=15))
    p = Part("clear", openscad(scad))
    p.volume(max=0.001)

    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.FAIL
    assert next(c for c in report.checks if c.kind == "builds").status is Status.FAIL
    assert next(c for c in report.checks if c.kind == "volume").status is Status.SKIPPED


# ---------------------------------------------------------------------------
# what the engine reported reading (#226)
# ---------------------------------------------------------------------------


def _external_data_part(tmp_path: Path) -> tuple[Path, Path]:
    """A model whose data-file path is COMPUTED, plus the file it reads.

    Computed deliberately: a literal `import("x.stl")` is findable with a
    regex, and `_EXTERNAL_DATA_RE` roughly is one. `import(names[0])` is the
    case `reads_external_data`'s docstring admits defeat on, so it is the case
    that has to be closed for the claim to mean anything.
    """
    data = tmp_path / "input.stl"
    data.write_bytes(b"solid x\nendsolid x\n")
    entry = tmp_path / "part.scad"
    entry.write_text('names = ["input.stl"];\nimport(names[0]);\ncube([2, 2, 2]);\n')
    return entry, data


@needs_scad_tier
def test_a_complete_engine_report_closes_the_external_data_gap(tmp_path: Path):
    """The point of #226, at the level `diff` reads.

    `external_data_reads` was an UNCONDITIONAL gap for any model containing
    `import()`/`surface()`, so such a model was permanently `partial` and
    `diff` permanently indeterminate on it — the complaint #190 was filed for,
    still live on the other engine. The engine knew all along; nothing asked.
    """
    entry, data = _external_data_part(tmp_path)
    report = run(Part("p", openscad(entry)), out_dir=tmp_path / "out")
    closure = report.source_closure
    assert closure is not None, report.error

    assert closure["reads_external_data"] is True, "premise: it does read external data"
    assert closure["engine_inputs"]["state"] == "complete"
    assert data.name in " ".join(closure["engine_inputs"]["data_files"])
    assert "external_data_reads" not in closure["unseen"]
    assert "partial" not in closure, "no gap left, so no partial — SPEC-report §8.3"


@needs_scad_tier
def test_the_data_file_is_hashed_not_merely_named(tmp_path: Path):
    """Naming a file while leaving it out of the digest would claim a coverage
    the digest does not have: edit the STL, and a closure that only LISTED it
    still answers `identical`. That is the gap re-opened one field over, which
    is the shape every fix in this area has taken."""
    entry, data = _external_data_part(tmp_path)
    out = tmp_path / "out"

    before = run(Part("p", openscad(entry)), out_dir=out).source_closure
    entry_bytes = entry.read_bytes()
    data.write_bytes(b"solid y\nendsolid y\n")  # a different build input
    after = run(Part("p", openscad(entry)), out_dir=out).source_closure

    assert before is not None and after is not None
    assert entry.read_bytes() == entry_bytes, "premise: the model itself is untouched"
    assert before["digest"] != after["digest"], "the closure must see the data file move"


@needs_scad_tier
@pytest.mark.parametrize("state", ["absent", "partial"])
def test_only_a_complete_report_may_close_the_gap(tmp_path: Path, state: str):
    """`absent` is not "the render read nothing" and `partial` is a floor, not
    a set. Treating either as closure is silence reading as success in the one
    field built to prevent it — so both must leave the gap exactly where an
    engine that never answered would."""
    from partspec.engines.openscad import RenderDeps
    from partspec.runner import _closure

    entry, _ = _external_data_part(tmp_path)
    closure = _closure(openscad(entry), RenderDeps(state=state))

    assert closure is not None
    assert closure["engine_inputs"]["state"] == state
    assert "external_data_reads" in closure["unseen"], f"{state} must not read as complete"
    assert closure["partial"] is True


@needs_build123d
def test_a_declared_build_input_that_never_loaded_is_a_run_level_error(tmp_path: Path):
    """SPEC-contract §10.2 rule 2, and the silence it refuses.

    A declaration naming something that never loaded means the contract
    described a build it did not get — a contract-versus-reality mismatch, not
    a geometry claim, so `verdict: error` rather than a failing check. It
    cannot be judged at the call site: nothing is imported when a contract is
    being declared, so the distribution may simply not be installed *yet*.

    Accepting it silently is the option that is clearly wrong. The
    declaration's whole purpose is to strengthen coverage, so a typo would
    quietly WEAKEN coverage while looking exactly like it had been asked for —
    the §8.3 rule 5 mistake made a second time in a new place.
    """
    from partspec import build123d

    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(1, 1, 1)\n"
    )
    part = Part("p", build123d(tmp_path / "m.py")).watertight()
    part.build_inputs.append("no-such-distribution-215")

    report = run(part, out_dir=tmp_path / "out")

    assert report.verdict is Verdict.ERROR
    assert "never imported" in (report.error or "")
    assert "no-such-distribution-215" in (report.error or "")
    statuses = {c.kind: c.status for c in report.checks}
    assert statuses["watertight"] is Status.SKIPPED, "a claim was not disproven, only unevaluated"
    assert statuses["builds"] is Status.SKIPPED


@needs_build123d
def test_a_declaration_the_build_met_is_recorded_and_does_not_error(tmp_path: Path):
    """The other half, so the test above cannot pass by erroring on everything."""
    from partspec import build123d

    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(1, 1, 1)\n"
    )
    part = Part("p", build123d(tmp_path / "m.py")).watertight()
    part.build_inputs.append("build123d")

    report = run(part, out_dir=tmp_path / "out")

    assert report.verdict is Verdict.PASS, report.error
    closure = report.source_closure
    assert closure is not None
    assert closure["declared"] == ["build123d"], "recorded as the author spelled it"
    assert closure["imports"]["build123d"]["identity"] == "content"
    assert closure["imports"]["build123d"]["declared"] is True


# --------------------------------------------------------------------------
# names the engine could not resolve, on a build that SUCCEEDED (#286)
# --------------------------------------------------------------------------
#
# OpenSCAD renders an unresolved call's children not at all and still exits 0
# with a well-formed mesh. The geometry measured is then not the geometry the
# source describes, so no geometry check can be honestly evaluated -- and until
# #286 every one of them reported PASS, because stderr was read only on the
# failure path. `docs/FAILURE-MODES.md` §1 is this exact shape.


def _unresolved_part(tmp_path: Path, body: str, name: str = "probe") -> Part:
    """A model that builds, but whose stderr names something unresolved."""
    src = tmp_path / f"{name}.scad"
    src.write_text(body)
    p = Part(name, openscad(src))
    p.envelope(max=(40, 30, 6))
    p.watertight()
    p.solid_count(1)
    return p


@needs_scad_tier
def test_an_unknown_module_on_a_successful_build_is_not_a_pass(tmp_path: Path):
    # No missing include: the name is simply not defined. The engine drops the
    # difference()'s second child, exports a bare cube, and exits 0.
    p = _unresolved_part(
        tmp_path,
        "difference() {\n  cube([40,30,6], center=true);\n  bore_hole(d=8);\n}\n",
    )
    report = run(p, out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR
    assert report.exit_code == 4
    assert _status(report, "builds") is Status.SKIPPED
    assert _status(report, "watertight") is Status.SKIPPED
    assert report.error is not None
    assert "bore_hole" in report.error


@needs_scad_tier
def test_an_unresolved_include_on_a_successful_build_is_not_a_pass(tmp_path: Path):
    p = _unresolved_part(
        tmp_path,
        "include <nowhere/absent.scad>\n"
        "difference() {\n  cube([40,30,6], center=true);\n  bore_hole(d=8);\n}\n",
    )
    report = run(p, out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR
    assert report.exit_code == 4
    assert report.error is not None
    assert "absent.scad" in report.error


@needs_scad_tier
def test_the_fault_is_not_a_statement_about_the_part(tmp_path: Path):
    # `builds` must not be emitted FAILING: the source compiled. Whose fault the
    # unresolved name is -- a misspelt module, or a library absent from this
    # machine -- partspec cannot tell, so it claims neither. SPEC-report §6.1.
    p = _unresolved_part(tmp_path, "cube([40,30,6], center=true);\nnope_module();\n")
    report = run(p, out_dir=tmp_path)

    assert _status(report, "builds") is not Status.FAIL
    assert report.build_origin is None
    assert all(c.status is not Status.PASS for c in report.checks if c.phase == "geometry")


@needs_scad_tier
def test_a_parameter_check_still_answers_when_a_name_did_not_resolve(tmp_path: Path):
    # Arithmetic over the contract's own inputs needs no engine, so it is still
    # honest and is still reported. Only the geometry is unmeasurable.
    src = tmp_path / "probe.scad"
    src.write_text("wall = 2.0;\ncube([40,30,6], center=true);\nnope_module();\n")
    p = Part("probe", openscad(src, wall=2.0))
    p.requires("wall > 0")
    p.watertight()

    report = run(p, out_dir=tmp_path)
    assert _status(report, "wall_gt_0") is Status.PASS
    assert report.verdict is Verdict.ERROR


@needs_scad_tier
@pytest.mark.parametrize(
    ("body", "named"),
    [
        # One per marker in `_UNRESOLVED_NAME_MARKERS`, so an implementation
        # that guards on a subset cannot pass this file. Each of these BUILDS:
        # the engine drops the unresolved call and exports a well-formed mesh.
        ("cube([40,30,6], center=true);\nnope_module();\n", "nope_module"),
        ("include <nowhere/absent.scad>\ncube([40,30,6], center=true);\n", "absent.scad"),
        ("echo(nofunc(3));\ncube([40,30,6], center=true);\n", "nofunc"),
        (
            "cube([40,30,6], center=true);\ntranslate([nope,0,0]) cube([1,1,1]);\n",
            "nope",
        ),
    ],
    ids=["module", "include", "function", "variable"],
)
def test_every_unresolved_name_marker_is_read_on_the_success_path(
    tmp_path: Path, body: str, named: str
):
    report = run(_unresolved_part(tmp_path, body), out_dir=tmp_path)
    assert report.verdict is Verdict.ERROR
    assert report.error is not None
    assert named in report.error


def test_a_value_that_would_not_convert_gets_a_different_diagnosis_than_a_name():
    """Two causes reach one guard, and they must not reach it as one sentence.

    #286's refusal had one message, and #308 gave the guard a second cause: a
    value the engine could not convert, so it substituted the module's own
    default into a dimension. Told to check `OPENSCADPATH` for that, a reader
    goes hunting for a library that is not missing -- which is the shape that
    got `undefined operation` reverted in PR #306, one cause over.

    Both directions are pinned, because merging them back is a one-line edit
    in either file and would be invisible on the path that stayed correct.
    Engine-free: `_unresolved_diagnosis` reads a string.
    """
    name_cause, name_hint = _unresolved_diagnosis(
        "WARNING: Ignoring unknown module 'nope_module' in file q.scad, line 2"
    )
    convert_cause, convert_hint = _unresolved_diagnosis(
        "WARNING: Unable to convert cube(size=[undef, 30, 6], ...) parameter to a"
        " number or a vec3 of numbers in file q.scad, line 2"
    )

    # The name text is unchanged by #308, to the byte, and still carries the
    # only advice that is any use for it.
    assert name_cause == "the engine could not resolve a name and rendered without it"
    assert "OPENSCADPATH" in name_hint

    # The conversion text names the substitution, and says neither of the two
    # things that would be false of it.
    assert convert_cause != name_cause
    assert "resolve a name" not in convert_cause
    assert "built its own default" in convert_hint
    assert "OPENSCADPATH" not in convert_hint


def test_an_over_long_rotate_vector_is_not_diagnosed_as_a_substitution():
    """A third cause, because the second one asserts a mechanism (#360).

    `Problem converting rotate(` joined the substitution markers in #333, and
    the substitution SENTENCE went with it: "built a default in place of it",
    printed over `rotate([90,0,0,0]) cube([10,5,2])` -- whose export is
    byte-identical to `rotate([90,0,0]) cube([10,5,2])` on both pinned engines,
    because 2021.01's `transform.cc` reads
    `default: ok &= false; /* fallthrough */ case 3:` and applies the first
    three components. Nothing is substituted, and the message said one was.

    Both directions are pinned. `Unable to convert` keeps the substitution text
    unchanged to the byte -- that marker really is always a default, and
    weakening it to cover this one would have cost the precision that makes it
    actionable -- while the rotate line gets a cause that claims only what
    stderr supports. Engine-free: `_unresolved_diagnosis` reads a string.
    """
    rotate_cause, rotate_hint = _unresolved_diagnosis(
        "WARNING: Problem converting rotate(a=[90, 0, 0, 0]) parameter in file q.scad, line 1"
    )
    convert_cause, convert_hint = _unresolved_diagnosis(
        "WARNING: Unable to convert cube(size=[undef, 30, 6], ...) parameter to a"
        " number or a vec3 of numbers in file q.scad, line 2"
    )

    assert "default" not in rotate_cause, "no default is taken for an over-long vector"
    assert rotate_cause == "the engine could not use a value as written"
    assert "OPENSCADPATH" not in rotate_hint, "still not the include path"

    # Unchanged for the marker it was measured on, and the two are not merged.
    assert convert_cause == (
        "the engine could not convert a value and built a default in place of it"
    )
    assert "built its own default" in convert_hint
    assert rotate_hint != convert_hint

    # Anchored, so a model cannot pick its own diagnosis by echoing the marker
    # back: OpenSCAD prints string literals into the warning verbatim.
    literal, _ = _unresolved_diagnosis(
        'WARNING: Problem converting rotate(a=["Unable to convert", 0, 0]) parameter'
        " in file q.scad, line 1"
    )
    assert literal == rotate_cause


@needs_scad_tier
def test_a_defaulted_dimension_is_refused_with_the_conversion_diagnosis(tmp_path: Path):
    """The conversion message out of a real build, rather than off a literal.

    The test above pins the two texts against each other and needs no engine;
    this one holds the wiring, which a passing classifier does not -- reading
    `_UNRESOLVED_NAME_MARKERS` at the call site again would leave that test
    green and this build unrefused.

    `cube(size=[o, 30, 6])` with `o = undef` exports a 1x1x1 unit cube at exit
    0 on both pinned engines -- clean, watertight, one solid -- and every check
    downstream passed until #308. It is refused now, and the sentence it is
    refused with is the conversion one, quoting the engine's own line.
    """
    src = tmp_path / "probe.scad"
    src.write_text("o = undef;\ncube(size=[o, 30, 6]);\n")
    p = Part("probe", openscad(src))
    p.watertight()
    p.solid_count(1)

    report = run(p, out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR
    assert report.error is not None
    assert report.error.startswith(
        "the engine could not convert a value and built a default in place of it"
    )
    assert "Unable to convert" in report.error, "the engine's own line, quoted"
    assert "OPENSCADPATH" not in (report.hint or "")


@needs_scad_tier
def test_a_probe_emptied_by_a_conversion_failure_cannot_satisfy_empty(tmp_path: Path):
    """`empty()` is the third surface, and a null result is its passing answer.

    A conversion failure can empty a probe as thoroughly as a misspelt module:
    `scale(undef)` drops the scale, so the second child stays where
    `translate([50,0,0])` put it and the intersection is genuinely null --
    exit 1, `Current top level object is empty.`, no STL. Measured on both
    pinned engines. Without the marker in the WIDE set, `p.empty()` reads that
    as its passing answer and the probe reports `PASS: 2 pass` at exit 0 on
    geometry that never existed, which is the laundered pass §4.12 exists to
    refuse.

    Round-1 review found this surface defended by nothing: reverting
    `_UNRESOLVED_MARKERS` to the name set alone left all 267 tests in the three
    relevant files green. The detail is asserted too, not just the status --
    the empty path had its own hardcoded copy of the name sentence (#308).
    """
    src = tmp_path / "probe.scad"
    src.write_text(
        "o = undef;\nintersection() {\n  cube([10,10,10]);\n"
        "  translate([50,0,0]) scale(o) cube([10,10,10]);\n}\n"
    )
    p = Part("probe", openscad(src))
    p.empty(id="no-shared-space")

    report = run(p, out_dir=tmp_path / "out")

    result = next(c for c in report.checks if c.id == "no-shared-space")
    assert result.status is Status.FAIL, "a probe the engine emptied is not a clearance"
    assert result.detail is not None
    assert "could not convert a value and built a default in place of it" in result.detail
    assert "resolve a name" not in result.detail, "the wrong cause, and the wrong remedy"
    assert "Unable to convert" in result.detail, "the engine's own line, quoted"


@needs_scad_tier
def test_an_undefined_operation_on_a_successful_build_is_not_an_unresolved_name(
    tmp_path: Path,
):
    """A type error in an expression is not a name that failed to resolve.

    `echo("holes: " + holes)` -- `+` where `str()` was meant, and among the most
    common things in a real .scad -- prints `undefined operation` and renders a
    completely correct part. Guarding on that marker (it is in the wider
    `_UNRESOLVED_MARKERS`, for the empty-result path) errored this part at exit
    4 while telling the reader a name had not resolved and to check
    `OPENSCADPATH`, which was false in every clause. Caught reviewing PR #306.
    """
    src = tmp_path / "probe.scad"
    src.write_text(
        'holes = 4;\necho("holes: " + holes);\n'
        "difference() {\n  cube([40,30,6], center=true);\n"
        "  cylinder(d=8, h=20, center=true, $fn=64);\n}\n"
    )
    p = Part("probe", openscad(src))
    p.watertight()
    p.solid_count(1)
    p.genus(1)  # the bore is really there -- this is not a hollowed part

    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.PASS
    assert report.error is None


@needs_scad_tier
def test_the_is_undef_idiom_is_not_an_unresolved_name(tmp_path: Path):
    # The false-positive bound, measured rather than assumed: `is_undef()` is
    # how an OpenSCAD source legitimately probes for a name it does not require,
    # and it emits no warning. Reading an undefined variable DIRECTLY does warn
    # -- and silently renders a default cube -- which is why that one is caught.
    src = tmp_path / "probe.scad"
    src.write_text("w = is_undef(nope) ? 40 : nope;\ncube([w, 30, 6], center=true);\n")
    p = Part("probe", openscad(src))
    p.envelope(max=(40, 30, 6))
    p.watertight()
    p.solid_count(1)

    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.PASS
    assert report.error is None


@needs_scad_tier
def test_a_declared_empty_part_is_not_laundered_by_an_unresolved_name(tmp_path: Path):
    """#237's rule, on the branch #286 added.

    `p.empty()` declares that the result is legitimately nothing. An unresolved
    name must never satisfy it: "the intersection is genuinely null" and "the
    geometry never existed to intersect" are opposite facts with one exit code.
    The BuildError branch has enforced that since #237. This pins the other
    side, where the render SUCCEEDS and the two paths are mutually exclusive by
    construction -- the empty arm lives inside `isinstance(artifact, BuildError)`
    and the #286 arm strictly after it, so neither can reach the other.
    """
    src = tmp_path / "probe.scad"
    # Builds something, and lost a name doing it: `empty` is declared and false,
    # but the evidence for "false" is not trustworthy either.
    src.write_text("cube([40,30,6], center=true);\nnope_module();\n")
    p = Part("probe", openscad(src))
    p.empty()

    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.ERROR
    assert _status(report, "empty") is not Status.PASS
    assert report.error is not None and "nope_module" in report.error


@needs_scad_tier
def test_an_unread_include_is_named_rather_than_the_contract_blamed(tmp_path: Path):
    """A false error is the mirror image of a false pass (#287).

    Refusing on `unbound_parameters` when an include did not open told the
    author their contract named a parameter that does not exist -- a claim
    partspec cannot make, since the file that would declare it was never read,
    and one the engine contradicts: the `-D` values do reach the geometry.
    A cold agent believing it deletes a correct declaration, while the real
    fault goes unmentioned.

    The refusal stands -- skipping it traded a loud false error for a silent
    false pass (review of PR #310) -- but it now names the include it could not
    open and does not claim to have read "its includes", and the fault is
    `environment` rather than the contract's.
    """
    src = tmp_path / "inc.scad"
    src.write_text("include <missing_lib.scad>\nplate_z = 3;\ncube([lib_x, lib_y, plate_z]);\n")
    p = Part("thing", openscad(src, lib_x=20.0, lib_y=10.0, plate_z=3.0))
    p.watertight()

    report = run(p, out_dir=tmp_path)

    assert report.error is not None
    assert "missing_lib.scad" in report.error
    assert "or its includes" not in report.error, "the claim partspec cannot make"
    assert report.build_origin == "environment"
    assert _status(report, "builds") is not Status.FAIL, "not a statement about the part"


# --------------------------------------------------------------------------
# a data file the engine asked for and did not get (#309)
# --------------------------------------------------------------------------
#
# #286's failure through a different channel. `import()`/`surface()` of an
# absent target renders as nothing and the engine still exits 0, so the mesh is
# well-formed and it is not the part. The depfile names the file -- and `unseen`
# is empty precisely BECAUSE `engine_inputs.state` is `complete`: the engine
# answered in full, and the full answer is that the file is absent.


def _absent_data_part(tmp_path: Path, body: str, name: str = "probe") -> Part:
    src = tmp_path / f"{name}.scad"
    src.write_text(body)
    p = Part(name, openscad(src))
    p.envelope(max=(40, 30, 6))
    p.watertight()
    return p


@needs_scad_tier
def test_a_missing_import_target_on_a_successful_build_is_not_a_pass(tmp_path: Path):
    p = _absent_data_part(
        tmp_path,
        'cube([40,30,6], center=true);\ntranslate([0,0,10]) import("missing.stl");\n',
    )
    report = run(p, out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR
    assert report.exit_code == 4
    assert _status(report, "builds") is Status.SKIPPED
    assert _status(report, "watertight") is Status.SKIPPED
    assert report.error is not None and "missing.stl" in report.error


@needs_scad_tier
def test_a_missing_surface_target_on_a_successful_build_is_not_a_pass(tmp_path: Path):
    # The second file-reading construct, whose stderr wording shares nothing
    # with `import()`'s. The depfile covers both uniformly, which is why this
    # is read off `engine_inputs.missing` and not off prose.
    p = _absent_data_part(
        tmp_path,
        'cube([40,30,6], center=true);\ntranslate([0,0,10]) surface(file="heights.dat");\n',
    )
    report = run(p, out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR
    assert report.error is not None and "heights.dat" in report.error


@needs_scad_tier
def test_the_absent_input_is_not_a_statement_about_the_part(tmp_path: Path):
    # SPEC-report §6.1, same reasoning as the unresolved-name arm: the source
    # compiled, and whether the path is a typo or the file has simply not been
    # generated yet is not something partspec can tell.
    p = _absent_data_part(
        tmp_path,
        'cube([40,30,6], center=true);\ntranslate([0,0,10]) import("missing.stl");\n',
    )
    report = run(p, out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR, "the premise: the run WAS refused"
    assert _status(report, "builds") is not Status.FAIL
    assert report.build_origin is None


@needs_scad_tier
def test_the_report_still_names_the_file_it_refused_over(tmp_path: Path):
    # The refusal happens AFTER the closure is upgraded from the depfile, so the
    # evidence for it survives in the artifact rather than being replaced by the
    # static walk. Before #309 this block was the whole report of the problem
    # and nothing read it.
    p = _absent_data_part(
        tmp_path,
        'cube([40,30,6], center=true);\ntranslate([0,0,10]) import("missing.stl");\n',
    )
    report = run(p, out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR, "the premise: the run WAS refused"
    closure = report.source_closure
    assert closure is not None
    assert closure["engine_inputs"]["missing"] == ["missing.stl"]
    assert closure["engine_inputs"]["state"] == "complete"
    assert closure["unseen"] == [], "the trap: a complete answer leaves no gap to name"


@needs_scad_tier
def test_a_data_file_that_is_present_is_still_judged(tmp_path: Path):
    # The guard must not fire on the ordinary case. `heights.dat` exists, the
    # engine reads it, `missing` is empty and the envelope decides.
    (tmp_path / "heights.dat").write_text("1 2 3\n4 5 6\n7 8 9\n")
    p = _absent_data_part(
        tmp_path,
        'cube([40,30,6], center=true);\ntranslate([0,0,10]) surface(file="heights.dat");\n',
    )
    report = run(p, out_dir=tmp_path)

    assert report.verdict is not Verdict.ERROR
    assert _status(report, "builds") is Status.PASS


# --------------------------------------------------------------------------
# an origin partspec cannot attribute (#307)
# --------------------------------------------------------------------------


@needs_openscad
def test_an_unattributable_build_error_is_not_adjudicated_as_the_model(tmp_path: Path, monkeypatch):
    """`BuildError.origin is None` MUST NOT reach the `builds: fail` arm.

    The branch this pins is the whole reason widening the type was not a
    one-liner. `runner.py` adjudicated `if origin == "environment": … else:
    builds fail`, so a `None` fell through to the arm that says the DESIGN is
    disproven — the exact misattribution `origin` exists to prevent
    (SPEC-report §6.1).

    Monkeypatched because the only producer today is `_hollowed_views`, inside
    `render_views`, which the runner never calls: the branch is otherwise
    unreachable from here and its mutant survives the whole suite. What is
    asserted is the adjudication, not the producer — reverting the branch to
    `== "environment"` turns this red with `FAIL is not ERROR`.
    """
    from partspec.backend import BuildError
    from partspec.backends.mesh import MeshBackend

    monkeypatch.setattr(
        MeshBackend,
        "build",
        lambda *a, **k: BuildError("cannot say whose fault this is", origin=None),
    )

    src = tmp_path / "probe.scad"
    src.write_text("cube([40,30,6], center=true);\n")
    p = Part("probe", openscad(src))
    p.watertight()
    p.solid_count(1)

    report = run(p, out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR, "an unattributable fault is not a failing part"
    assert report.exit_code == 4
    assert report.build_origin is None, "the null must survive into the report"
    assert _status(report, "builds") is Status.SKIPPED, "`builds: fail` would blame the design"
    assert _status(report, "watertight") is Status.SKIPPED
    assert report.error == "cannot say whose fault this is"


@needs_openscad
def test_the_environment_arm_is_unchanged_by_the_widening(tmp_path: Path, monkeypatch):
    """The control for the branch above: `"environment"` still lands the same
    way, and `"model"` still fails `builds`. Without these two the negation
    could be replaced by an unconditional skip and nothing would notice."""
    from partspec.backend import BuildError
    from partspec.backends.mesh import MeshBackend

    src = tmp_path / "probe.scad"
    src.write_text("cube([40,30,6], center=true);\n")

    def _report(origin):
        monkeypatch.setattr(MeshBackend, "build", lambda *a, **k: BuildError("nope", origin=origin))
        p = Part("probe", openscad(src))
        p.watertight()
        return run(p, out_dir=tmp_path)

    env = _report("environment")
    assert env.verdict is Verdict.ERROR
    assert _status(env, "builds") is Status.SKIPPED
    assert env.build_origin == "environment"

    model = _report("model")
    assert model.verdict is Verdict.FAIL, "a design that does not compile IS a statement"
    assert _status(model, "builds") is Status.FAIL
    assert model.build_origin == "model"


# --------------------------------------------------------------------------
# the guard is narrowed to files the export actually depended on (#354 B1)
# --------------------------------------------------------------------------
#
# OpenSCAD EVALUATES a `%` subtree -- so the reference resolves, the engine warns,
# and the depfile records the file -- and then excludes it from the export. The
# bytes are identical whether or not the file is there, so refusing is refusing
# more than the mathematics requires. `*` never evaluates and never reaches the
# depfile. `#` is exported, so it stays a catch.


def _bare_part(tmp_path: Path, body: str, name: str = "probe") -> Part:
    src = tmp_path / f"{name}.scad"
    src.write_text(body)
    p = Part(name, openscad(src))
    p.watertight()
    return p


_MODIFIER_SHAPES = [
    # (name, body, refuses)
    ("plain_import", 'cube([10,10,10]);\nimport("gone.stl");\n', True),
    ("surface_absent", 'cube([10,10,10]);\nsurface(file="h.dat");\n', True),
    ("hash_import", 'cube([10,10,10]);\n#import("hash.stl");\n', True),
    ("pct_and_plain", 'cube([10,10,10]);\n%import("bg.stl");\nimport("fg.stl");\n', True),
    ("pct_import", 'cube([10,10,10]);\n%import("mate.stl");\n', False),
    ("pct_surface", 'cube([10,10,10]);\n%surface(file="bg.dat");\n', False),
    ("star_import", 'cube([10,10,10]);\n*import("star.stl");\n', False),
]


@needs_scad_tier
@pytest.mark.parametrize(
    ("name", "body", "refuses"), _MODIFIER_SHAPES, ids=[s[0] for s in _MODIFIER_SHAPES]
)
def test_only_a_file_the_export_depended_on_holds_the_verdict(
    tmp_path: Path, name: str, body: str, refuses: bool
):
    """All seven shapes, because the boundary is the whole claim.

    `%` and `*` are excluded from the export, so a file named only from one of
    them is not a build input and a missing one proves nothing about the part.
    `#` IS exported — the source asked for that geometry and did not get it —
    so it is a true positive and stays refused, the same `%`/`#` asymmetry
    `FAILURE-MODES.md` entry 9a draws.
    """
    report = run(_bare_part(tmp_path, body, name), out_dir=tmp_path)

    if refuses:
        assert report.verdict is Verdict.ERROR, "an exported input is missing"
        assert report.exit_code == 4
    else:
        assert report.verdict is not Verdict.ERROR, (
            "the export does not depend on this file; refusing it is a false red"
        )
        assert _status(report, "builds") is Status.PASS


@needs_scad_tier
def test_the_refusal_names_the_exported_file_and_not_the_dropped_one(tmp_path: Path):
    """The case a naive implementation gets wrong.

    One file has both a `%` reference and a real one; another has only the `%`.
    Refusing the run is right, and naming `bg.stl` in the sentence — or counting
    it in the `(and N more)` suffix — would send a reader to a reference that
    costs the export nothing. The closure still records BOTH under
    `engine_inputs.missing`: that field reports what the engine said, and the
    narrowing is a judgement laid over it, not an edit of it.
    """
    body = 'cube([10,10,10]);\n%import("bg.stl");\nimport("fg.stl");\n'
    report = run(_bare_part(tmp_path, body), out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR
    assert report.error is not None
    assert "fg.stl" in report.error
    assert "bg.stl" not in report.error
    assert "more" not in report.error, "one file is missing from the export, not two"

    closure = report.source_closure
    assert closure is not None
    assert closure["engine_inputs"]["missing"] == ["bg.stl", "fg.stl"]


@needs_scad_tier
def test_an_unreadable_csg_export_keeps_the_refusal(tmp_path: Path):
    """Fail closed, on the failure that is real rather than hypothetical.

    The `.csg` format prints string contents raw, so a quote inside one breaks
    the parse — `CsgError: unexpected identifier in value position: 'hi'`,
    measured on this exact source. A `%`-only reference would otherwise be
    exonerated; it is not, because a false refusal here is the behaviour that
    already shipped while a false pass would be the founding-property failure
    #309 exists to close.
    """
    body = 'cube([10,10,10]);\n%import("q.stl");\nlinear_extrude(1) text("say \\"hi\\"");\n'
    report = run(_bare_part(tmp_path, body), out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR, "unreadable evidence may not exonerate"
    assert report.error is not None and "q.stl" in report.error


@needs_scad_tier
def test_a_reference_from_an_included_file_is_joined_to_its_depfile_entry(tmp_path: Path):
    """The `.csg` literal is ENTRY-relative even when the reference is not.

    This test used to claim the join had to be a suffix match, because an
    `import()` inside an included file resolves against that file's directory.
    The premise was false and the join it justified was unsound (#354 round-2,
    B3): OpenSCAD re-expresses the literal relative to the **entry** file's
    directory before writing the `.csg`. Measured on this exact shape, where
    the two engines do not even agree on where the reference resolves —
    2021.01 writes `"deep.stl"` and the 2026.08.01 snapshot `"sub/deep.stl"` —
    and each engine's literal, resolved against the entry's parent, reproduces
    that same engine's own depfile entry. So `(base / literal).resolve()` is
    exact on both, which is what the guard now relies on.
    """
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "helper.scad").write_text('module h() { import("deep.stl"); }\n')
    body = "include <sub/helper.scad>\ncube([10,10,10]);\nh();\n"
    report = run(_bare_part(tmp_path, body), out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR
    assert report.error is not None and "deep.stl" in report.error


@needs_scad_tier
def test_two_files_of_the_same_name_in_different_directories_are_told_apart(tmp_path: Path):
    """The join is by path suffix, and a basename match is not good enough.

    `a/x.stl` is referenced only from a `%` subtree and is absent; `b/x.stl` is
    referenced for real and is there. Only the first is in `missing`, and the
    export does not depend on it. Matching on the bare name instead would see
    the missing file's name in the KEPT set too — because `b/x.stl` shares it —
    and refuse a run whose export is complete.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "x.stl").write_text("solid s\nendsolid s\n")
    body = 'cube([10,10,10]);\n%import("a/x.stl");\nimport("b/x.stl");\n'
    report = run(_bare_part(tmp_path, body), out_dir=tmp_path)

    closure = report.source_closure
    assert closure is not None
    assert closure["engine_inputs"]["missing"] == ["a/x.stl"], "only the %-ed one is absent"
    assert report.verdict is not Verdict.ERROR, "the export depends on b/x.stl, which is there"


# --------------------------------------------------------------------------
# the narrowing must not fail OPEN (#354 round-2, B3 and B4)
# --------------------------------------------------------------------------
#
# Both defects passed a run whose exported geometry was provably short of what
# the source asked for, which is the founding-property failure #309 exists to
# close. B3: the join was by path suffix, and neither half of its premise held
# -- the depfile entry is `.resolve()`d and the `.csg` literal is rewritten
# entry-relative -- so a kept literal carrying `../` could not match its own
# resolved path while a shorter dropped literal matched it by accident. B4: the
# discriminating export was taken at the model's DEFAULTS, so a modifier behind
# a parameter or a method wrapper adjudicated a different tree than the one the
# depfile came from.


def _nested_part(root: Path, body: str, name: str = "probe") -> Part:
    """An entry file one directory DOWN, so `../` is expressible."""
    (root / "m").mkdir(exist_ok=True)
    src = root / "m" / f"{name}.scad"
    src.write_text(body)
    p = Part(name, openscad(src))
    p.watertight()
    return p


@needs_scad_tier
def test_a_dotdot_reference_the_export_used_still_holds_the_verdict(tmp_path: Path):
    """`../mate.stl` is imported for real; `mate.stl` is only `%`-ed.

    Two different files. The exported mesh goes from 12 triangles to 24 when
    `../mate.stl` is present, so it is a build input by any definition, and the
    same model without the `%` line exits 4. Under the suffix join the resolved
    `.../mate.stl` could not match the kept literal `"../mate.stl"` and matched
    the dropped `"mate.stl"` instead, and the run passed at exit 0.
    """
    body = 'cube([10,10,10]);\nimport("../mate.stl");\n%import("mate.stl");\n'
    report = run(_nested_part(tmp_path, body, "dd"), out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR, "an exported build input is missing"
    assert report.error is not None and "mate.stl" in report.error


@needs_scad_tier
def test_a_symlinked_reference_the_export_used_still_holds_the_verdict(tmp_path: Path):
    """Same defect through the other half of `.resolve()`.

    The depfile entry has its symlink resolved, so it cannot end with the
    literal the source wrote either.
    """
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    body = 'cube([10,10,10]);\nimport("../link/mate.stl");\n%import("mate.stl");\n'
    report = run(_nested_part(tmp_path, body, "sym"), out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR


@needs_scad_tier
def test_a_dropped_reference_through_a_symlink_is_still_exonerated(tmp_path: Path):
    """The mirror: the same unsoundness left false REDS behind too.

    A `%`-ed reference whose resolved path does not end with its literal was
    unaccounted for and refused, on an export that does not depend on it.
    """
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    body = 'cube([10,10,10]);\n%import("../link/mate.stl");\n'
    report = run(_nested_part(tmp_path, body, "fr1"), out_dir=tmp_path)

    assert report.verdict is not Verdict.ERROR
    assert _status(report, "builds") is Status.PASS


@needs_scad_tier
def test_a_dropped_reference_by_absolute_path_is_exonerated(tmp_path: Path):
    """An absolute literal never had a `/`-prefixed suffix to match either."""
    body = f'cube([10,10,10]);\n%import("{(tmp_path / "nowhere" / "abs.stl").as_posix()}");\n'
    report = run(_nested_part(tmp_path, body, "fr2"), out_dir=tmp_path)

    assert report.verdict is not Verdict.ERROR
    assert _status(report, "builds") is Status.PASS


@needs_scad_tier
def test_the_export_is_taken_with_the_parameters_the_build_used(tmp_path: Path):
    """B4: a modifier behind a `-D` value.

    At the model's defaults `ghost` is true and the reference is `%`-ed; the
    contract overrides it to false, so the BUILT tree imports the file for real
    — 24 triangles against 12. An export taken without the overrides sees only
    the `%` branch and exonerates a file the run actually needed.
    """
    body = (
        "ghost = true;\ncube([10,10,10]);\n"
        'if (ghost) { %import("mate.stl"); } else { import("mate.stl"); }\n'
    )
    src = tmp_path / "g.scad"
    src.write_text(body)

    real = Part("g", openscad(src, ghost=False))
    real.watertight()
    assert run(real, out_dir=tmp_path).verdict is Verdict.ERROR, (
        "with ghost=false the import is real and the file is absent"
    )

    ghosted = Part("g", openscad(src, ghost=True))
    ghosted.watertight()
    report = run(ghosted, out_dir=tmp_path)
    assert report.verdict is not Verdict.ERROR, (
        "with ghost=true it really is scaffolding — the override decides, both ways"
    )


@needs_scad_tier
def test_the_export_is_taken_through_the_method_wrapper(tmp_path: Path):
    """B4 again, by the other route into a different tree.

    `mate.stl` is `%`-ed at the top level and imported for real inside the
    method the contract names. Exporting the bare file sees only the `%` and
    exonerates it; exporting through the same scratch entry `render()` builds
    sees both, and a reference named anywhere outside a dropped subtree is a
    build input.
    """
    src = tmp_path / "mm.scad"
    src.write_text(
        '%import("mate.stl");\nmodule make() {\n  cube([10,10,10]);\n  import("mate.stl");\n}\n'
    )
    p = Part("mm", openscad(src, method="make"))
    p.watertight()

    report = run(p, out_dir=tmp_path)

    assert report.verdict is Verdict.ERROR
    assert not list(tmp_path.glob(".partspec-*.scad")), "the method scratch must be cleaned up"


@needs_scad_tier
def test_the_discriminating_export_honours_the_contracts_timeout(tmp_path: Path):
    """L8: it is the one subprocess in the runner that ignored the budget.

    It ran with a hardcoded `timeout=120` while the call site passed nothing,
    so `--timeout 1` could still spend two minutes here. Asserted on the
    argument rather than on a stopwatch: a wall-clock test needs a model slow
    enough to fold, which is a different thing to be flaky about.
    """
    import subprocess as sp

    seen: list[float | None] = []
    real_run = sp.run

    def _recording(cmd, **kwargs):
        if any(str(a).endswith(".csg") for a in cmd):
            seen.append(kwargs.get("timeout"))
        return real_run(cmd, **kwargs)

    body = 'cube([10,10,10]);\n%import("mate.stl");\n'
    p = _bare_part(tmp_path, body)
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(sp, "run", _recording)
        run(p, out_dir=tmp_path, timeout_s=7.0)
    finally:
        monkey.undo()

    assert seen == [7.0], f"the .csg export ran with {seen}, not the contract's budget"


@needs_openscad
def test_a_method_scratch_that_failed_refuses_rather_than_exporting_the_bare_file(
    tmp_path: Path, monkeypatch
):
    """B4's other half, and the one arm nothing else reaches (#362).

    `_only_in_dropped_subtrees` refuses when `_method_scratch` returns a
    `BuildError` instead of falling back to `source.path`. That refusal is
    load-bearing -- the control below exports the bare file and exonerates a
    real build input -- and it is unreachable through the runner's own
    ordering: the build called `_method_scratch` moments earlier, and a genuine
    failure becomes an environment refusal (`could not write the method scratch
    file in ...`, `build_origin: "environment"`) before the guard is reached.
    So deleting the branch changes no test, while forcing it changes behaviour
    in the unsafe direction, which is what the monkeypatch pins.

    Same route as `test_an_unattributable_build_error_is_not_adjudicated_as_the_model`,
    for the same reason: what is asserted is the adjudication, not the producer.
    """
    from partspec.backend import BuildError
    from partspec.engines import openscad as engine
    from partspec.runner import _engine_source, _only_in_dropped_subtrees

    src = tmp_path / "ms.scad"
    src.write_text(
        '%import("mate.stl");\nmodule make() {\n  cube([10,10,10]);\n  import("mate.stl");\n}\n'
    )
    missing = ((tmp_path / "mate.stl").resolve(),)
    out = tmp_path / "out"
    out.mkdir()

    # The control, and the whole reason the branch matters: the BARE file's top
    # level carries only the `%`-ed reference, so an export of it exonerates
    # `mate.stl` -- while the method the contract names imports it plainly.
    bare = _engine_source(Part("bare", openscad(src)))
    assert _only_in_dropped_subtrees(bare, missing, out, None) == set(missing)

    monkeypatch.setattr(
        engine,
        "_method_scratch",
        lambda source, out_dir: BuildError("no scratch here", origin="environment"),
    )
    wrapped = _engine_source(Part("ms", openscad(src, method="make")))
    assert _only_in_dropped_subtrees(wrapped, missing, out, None) == set(), (
        "no usable entry is no evidence; falling back to source.path fails OPEN"
    )


# -- one engine fact, one diagnosis, whichever verb meets it (#355) ---------------------


def _verb_target(tmp_path: Path, body: str, name: str) -> str:
    (tmp_path / f"{name}.scad").write_text(body)
    spec = tmp_path / f"spec_{name}.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        f"    return Part({name!r}, openscad({name + '.scad'!r}))\n"
    )
    return f"{spec}:make"


@needs_scad_tier
@pytest.mark.parametrize(
    ("name", "body", "refuses"), _MODIFIER_SHAPES, ids=[s[0] for s in _MODIFIER_SHAPES]
)
def test_measure_refuses_exactly_what_check_refuses(
    tmp_path: Path, name: str, body: str, refuses: bool, capsys
):
    """`measure` was the hazard, not `check`.

    A number taken off a part that is missing a piece gets written into a
    contract, and that contract then passes forever (#286, #309). Before #355
    `check` exited 4 here while `measure` exited 0 and printed the volume of a
    bare plate.

    The `%`/`*` rows are the half a naive fix gets wrong: those files reach
    `engine_inputs.missing` exactly as a real dependency does, so refusing on
    that field alone refuses a correct part.
    """
    from partspec.cli import main

    code = main(["measure", _verb_target(tmp_path, body, f"m_{name}")])
    err = capsys.readouterr().err
    if refuses:
        assert code == 4, "measure must not answer off a part missing a build input"
        assert "build input that is not on disk" in err, (
            "the exit code alone would pass for any refusal; this asserts the reason"
        )
    else:
        assert code == 0, "the export does not depend on this file; refusing it is a false red"


@needs_scad_tier
@pytest.mark.parametrize(
    ("name", "body", "refuses"), _MODIFIER_SHAPES, ids=[s[0] for s in _MODIFIER_SHAPES]
)
def test_render_refuses_exactly_what_check_refuses(
    tmp_path: Path, name: str, body: str, refuses: bool, capsys
):
    """A picture is the one output a reader trusts without checking (#307).

    Asserts the REASON, not just the code. On an engine with no offscreen path --
    apt 2021.01 without a display, which is what CI's mesh-only job has -- every
    row exits 4 for a reason that has nothing to do with this issue. Reading only
    the code there would have passed the refusing rows for the wrong reason while
    failing the others, which is how the first draft of this test behaved.
    """
    from partspec.cli import main

    out = tmp_path / f"out_{name}"
    code = main(["render", _verb_target(tmp_path, body, f"r_{name}"), "--out", str(out)])
    err = capsys.readouterr().err
    if "without a display" in err:
        pytest.skip("this OpenSCAD cannot render PNG here; the question is unanswerable")

    pngs = list(out.rglob("*.png"))
    if refuses:
        assert code == 4, "render must not draw a part missing a build input"
        assert "build input that is not on disk" in err
        assert not pngs, "the refusal must land before any view moves"
    else:
        assert code == 0
        assert pngs, "a dropped subtree is not a missing input; this part is renderable"


@needs_scad_tier
def test_the_three_verbs_give_one_diagnosis_for_one_engine_fact(tmp_path: Path):
    """#308's rule. The cause and the hint are shared, so a reader who met this
    through one verb recognises it through another."""
    from partspec.cli import _absent_input_refusal
    from partspec.engines.openscad import _absent_input_views
    from partspec.runner import _ABSENT_INPUT_CAUSE, _ABSENT_INPUT_HINT

    for refusal in (_absent_input_refusal(["gone.stl"]), _absent_input_views(["gone.stl"])):
        assert refusal.message.startswith(_ABSENT_INPUT_CAUSE)
        assert refusal.hint == _ABSENT_INPUT_HINT
        assert refusal.origin is None, (
            "a typo and a not-yet-generated file are indistinguishable here, "
            "so neither 'model' nor 'environment' may be claimed"
        )
