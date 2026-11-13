"""Multi-target check (#29): one interpreter start, N reports, honest exits.

The batch rules are SPEC-report §5 rule 4 and §6.2: no early abort, one report
per part, exit by the highest-precedence verdict — and the hazard the slice
owns, POST-V0 §8: `sys.modules` must not serve a later build a stale helper.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from support import needs_scad_tier, py_target, report_of

from partspec.cli import main
from partspec.status import Verdict, exit_code

FIXTURES = Path(__file__).parent / "fixtures"


def _scad_target(tmp_path: Path, name: str, body: str) -> str:
    d = tmp_path / name
    d.mkdir()
    shutil.copy(FIXTURES / "block_with_hole.scad", d / "block_with_hole.scad")
    module = d / f"{name}.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        f"    p = Part({name!r}, openscad('block_with_hole.scad'))\n"
        f"{body}"
        "    return p\n"
    )
    return f"{module}:make"


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        ([1, 2], 1),
        ([2, 1], 1),
        ([3, 1], 3),
        ([1, 3], 3),
        ([3, 4], 4),
        ([4, 3], 4),
        ([0, 2], 2),
        ([0, 1], 1),
        ([2, 4], 4),
        ([64, 4], 64),
        ([130, 64, 4], 130),
        ([0, 0], 0),
    ],
)
def test_the_batch_exit_is_the_specs_precedence_pairwise(codes, expected):
    """SPEC-report §6.2's order — error > empty > fail > incomplete > pass,
    with interrupt and usage above all — held pairwise rather than sampled.

    The deslop audit found only three of the ten ordered pairs covered, and
    two mutants of `_EXIT_PRECEDENCE` survived the whole suite. One of them
    swaps fail and incomplete, so a batch holding a genuinely FAILING part
    beside an incomplete one exits 2 — the code AGENT-CONTRACT row 2 reads as
    'do not edit geometry'. The tool would tell an agent to leave a disproven
    design alone. `_batch_exit` is pure, so this costs nothing to hold.
    """
    from partspec.cli import _batch_exit

    assert _batch_exit(codes) == expected


def _report(target: str) -> dict:
    module, _, _ = target.rpartition(":")
    path = Path(module)
    return report_of(path.parent / "outputs" / f"{path.stem}-make")


# --------------------------------------------------------------------------
# exits and no-early-abort
# --------------------------------------------------------------------------


@needs_scad_tier
def test_a_batch_writes_every_report_and_exits_the_worst_verdict(tmp_path: Path):
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    bad = _scad_target(tmp_path, "bad", "    p.envelope(max=(1, 1, 1))\n")
    assert main(["check", good, bad, "--quiet"]) == exit_code(Verdict.FAIL)
    assert _report(good)["verdict"] == "pass", "the passing part still got its fresh report"
    assert _report(bad)["verdict"] == "fail"


@needs_scad_tier
def test_an_erroring_part_does_not_stop_the_rest(tmp_path: Path):
    raising = tmp_path / "raising.py"
    raising.write_text("def make():\n    raise TypeError('broken contract')\n")
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    assert main(["check", f"{raising}:make", good, "--quiet"]) == exit_code(Verdict.ERROR)
    assert _report(good)["verdict"] == "pass", "SPEC-report 5.4: failures must not abort the batch"


@needs_scad_tier
def test_an_unresolvable_target_is_usage_and_the_rest_still_run(tmp_path: Path):
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    assert main(["check", str(tmp_path / "nowhere.py") + ":make", good, "--quiet"]) == 64
    assert _report(good)["verdict"] == "pass"


@needs_scad_tier
def test_empty_outranks_fail_in_the_batch_exit(tmp_path: Path):
    """SPEC-report 6.1 precedence, pinned: the vacuous-green case is the more
    dangerous signal and must not hide behind a mere failure."""
    empty = _scad_target(tmp_path, "empty", "")
    bad = _scad_target(tmp_path, "bad", "    p.envelope(max=(1, 1, 1))\n")
    assert main(["check", empty, bad, "--quiet"]) == exit_code(Verdict.EMPTY)


@needs_scad_tier
def test_the_summary_names_the_tally_and_quiet_suppresses_it(tmp_path: Path, capsys):
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    bad = _scad_target(tmp_path, "bad", "    p.envelope(max=(1, 1, 1))\n")
    main(["check", good, bad])
    out = capsys.readouterr().out
    assert "BATCH: 2 parts" in out and "1 pass" in out and "1 fail" in out

    main(["check", good, bad, "--quiet"])
    assert "BATCH" not in capsys.readouterr().out


@needs_scad_tier
def test_a_single_target_emits_no_batch_summary(tmp_path: Path, capsys):
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    assert main(["check", good]) == 0
    assert "BATCH" not in capsys.readouterr().out


# --------------------------------------------------------------------------
# --out in a batch
# --------------------------------------------------------------------------


@needs_scad_tier
def test_explicit_out_gets_a_subdirectory_per_part(tmp_path: Path):
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    bad = _scad_target(tmp_path, "bad", "    p.envelope(max=(1, 1, 1))\n")
    out = tmp_path / "reports"
    main(["check", good, bad, "--quiet", "--out", str(out)])
    assert report_of(out / "good-make")["verdict"] == "pass"
    assert report_of(out / "bad-make")["verdict"] == "fail"


def test_colliding_slugs_under_one_out_dir_are_refused(tmp_path: Path, capsys):
    """Two targets named spec.py:make in different directories share a slug;
    letting the second silently overwrite the first's report under one
    deterministic path is the stale-artifact failure, chosen on purpose."""
    for name in ("a", "b"):
        d = tmp_path / name
        d.mkdir()
        (d / "spec.py").write_text("def make():\n    pass\n")
    code = main(
        [
            "check",
            f"{tmp_path / 'a' / 'spec.py'}:make",
            f"{tmp_path / 'b' / 'spec.py'}:make",
            "--quiet",
            "--out",
            str(tmp_path / "reports"),
        ]
    )
    assert code == 64
    assert "collide" in capsys.readouterr().err
    # And the refusal touched no disk. This assertion moved here from
    # `test_render_refuses_a_batch`, which #189 deleted along with the refusal
    # it pinned — leaving the "shape refusals precede the placeholder fan-out"
    # rule (PR #104 re-review, finding 7) with nothing holding it, in the
    # comment's own words "or the fan-out itself performs the shared-path
    # overwrite the guard exists to refuse". Moving the guard below the
    # fan-out passed the whole suite (round 1 of #189's review).
    assert not (tmp_path / "reports").exists(), "a refused shape touches no disk"


_TWO_PART_SPEC = (
    "from partspec import Part, openscad\n\n\n"
    "def a():\n"
    '    return Part("stud-a", openscad("m.scad")).volume(min=1.0)\n\n\n'
    "def b():\n"
    '    return Part("stud-b", openscad("m.scad")).volume(min=1.0)\n'
)


def _two_part_contract(tmp_path: Path) -> None:
    (tmp_path / "m.scad").write_text("cube([20, 20, 10], center = true);\n")
    (tmp_path / "spec.py").write_text(_TWO_PART_SPEC)


def _rendered(tmp_path: Path, slug: str) -> dict:
    """That target's `renders` block, or `{}` if the key is absent.

    `.get(key, {})` rather than `.get(key) or {}`: SPEC-report §8.4 says the
    key MUST be absent rather than an empty object, so the `or` form would
    quietly accept the shape the spec forbids.
    """
    report = json.loads((tmp_path / "out" / slug / "report.json").read_text())
    assert report.get("renders") != {}, "SPEC-report §8.4: absent, never an empty object"
    return report.get("renders", {})


@needs_scad_tier
def test_render_covers_every_target_in_a_batch(tmp_path: Path, monkeypatch, capsys):
    """`check` takes N targets and `--render` used to refuse them (#189).

    "single-target for now" was the message, and the "for now" was right:
    nothing under the refusal was load-bearing. Each target already resolves
    its own `out` through `_out_dir_for`, so the views land beside that
    target's own report and are recorded relative to it.

    Both arms of the display branch are asserted, because the mesh-only CI job
    keeps no xvfb on purpose and OpenSCAD 2021.01 cannot export PNG without
    one. An earlier draft asserted success unconditionally and went red there
    while `main` stayed green — the repo's other OPENSCAD-TIER `--render`
    tests both carry this arm and it was simply missed (round 1 of #189's
    review). The OCCT-tier ones do not, and do not need to: no display is in
    that loop, as one of their docstrings says.
    """
    monkeypatch.chdir(tmp_path)
    _two_part_contract(tmp_path)
    code = main(["check", "spec.py:a", "spec.py:b", "--render", "--quiet", "--out", "out"])
    err = capsys.readouterr().err

    if code != 0:
        # No display: every target says so, each under its own name, and no
        # report claims views it does not have.
        assert "cannot render PNG without a display" in err
        for spec, slug in (("spec.py:a", "spec-a"), ("spec.py:b", "spec-b")):
            assert f"partspec: {spec}: " in err
            assert _rendered(tmp_path, slug) == {}
        return

    for slug in ("spec-a", "spec-b"):
        renders = _rendered(tmp_path, slug)
        assert set(renders) == {"iso", "front", "top", "right"}
        for view, rel in renders.items():
            # Relative to that report's OWN directory, so two parts' renders
            # cannot name each other (SPEC-report §8).
            assert rel == f"renders/{view}.png"
            assert (tmp_path / "out" / slug / rel).is_file()

    # Two directories written, not one written twice. `a_iso != b_iso`
    # compares two literals and can never be false; what carries the assertion
    # is that both paths hold bytes.
    a_iso = tmp_path / "out" / "spec-a" / "renders" / "iso.png"
    b_iso = tmp_path / "out" / "spec-b" / "renders" / "iso.png"
    assert a_iso.read_bytes() and b_iso.read_bytes()


@needs_scad_tier
def test_a_failing_render_in_a_batch_names_the_target(tmp_path: Path, monkeypatch, capsys):
    """One message and N parts: without the target it says nothing.

    The message was unambiguous only because this path was single-target, so
    opening `--render` to a batch is what made naming it necessary (#189).

    Asserted as a correspondence rather than as "only one target is named": an
    earlier draft asserted the target that succeeded was absent from stderr,
    which is the single-failure assumption this feature exists to remove, and
    it duly failed where BOTH targets fail for want of a display (round 1 of
    #189's review). Every target that failed is named; every target that did
    not is not.
    """
    monkeypatch.chdir(tmp_path)
    _two_part_contract(tmp_path)
    # `renders` is a FILE where the first target needs a directory, so its
    # render fails whatever the display situation is.
    blocked = tmp_path / "out" / "spec-a" / "renders"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("not a directory\n")

    code = main(["check", "spec.py:a", "spec.py:b", "--render", "--quiet", "--out", "out"])
    assert code == 4
    err = capsys.readouterr().err

    # Scoped to targets that reached the render at all. A report can lack
    # `renders` without anything having failed — a parameter blocker leaves
    # `builds` unproven, so no render is attempted and none is owed — and the
    # correspondence would then accuse the attribution code of a bug it does
    # not have. Both parts here build, which is what makes it exact.
    for spec, slug in (("spec.py:a", "spec-a"), ("spec.py:b", "spec-b")):
        report = json.loads((tmp_path / "out" / slug / "report.json").read_text())
        assert any(c["kind"] == "builds" and c["status"] == "pass" for c in report["checks"]), (
            f"{spec}: premise — a part that never built is owed no render"
        )
        named = f"partspec: {spec}: " in err
        assert named == (_rendered(tmp_path, slug) == {}), (
            f"{spec}: named on stderr={named}, but its report "
            f"{'has' if _rendered(tmp_path, slug) else 'has no'} renders"
        )
    # The first target is the one this fixture breaks, whatever the tier.
    assert "partspec: spec.py:a: " in err
    assert _rendered(tmp_path, "spec-a") == {}


@needs_scad_tier
def test_a_single_target_render_failure_carries_no_target_prefix(
    tmp_path: Path, monkeypatch, capsys
):
    """`AGENT-CONTRACT.md` §2 says the target is named "when several were
    given", and nothing held the tool to the second half.

    Dropping the `if batch` conditional — making every render failure
    prefixed — passed the entire suite (round 1 of #189's review). One target
    needs no disambiguation and the bare message is the older, calmer one.
    """
    monkeypatch.chdir(tmp_path)
    _two_part_contract(tmp_path)
    blocked = tmp_path / "out" / "renders"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("not a directory\n")

    code = main(["check", "spec.py:a", "--render", "--quiet", "--out", "out"])
    assert code == 4
    err = capsys.readouterr().err
    assert "partspec: spec.py:a: " not in err, "one target needs no disambiguation"
    assert err.startswith("partspec: ")


# --------------------------------------------------------------------------
# the POST-V0 §8 hazard: stale modules across builds in one process
# --------------------------------------------------------------------------


def _closure_target(d: Path, size: float) -> str:
    """A build123d part whose size comes from a sibling module it imports.

    The helper and the model are the fixture — the import is what these tests
    are about — so only the contract is boilerplate, and that goes through
    `py_target`. Renamed off `_py_target` when that helper landed in
    `support.py`: two names one underscore apart doing different things is a
    reading hazard, and this one is named for the thing it sets up.
    """
    d.mkdir(exist_ok=True)
    (d / "helper29.py").write_text(f"SIZE = {size}\n")
    (d / "model.py").write_text(
        "import helper29\nfrom build123d import Box\n\n\ndef make_part():\n"
        "    return Box(helper29.SIZE, 1, 1)\n"
    )
    return py_target(d, model="model.py", claims="    p.volume(min=0.0)\n")


def _measured_volume(out: Path) -> float:
    report = report_of(out)
    (check,) = [c for c in report["checks"] if c["kind"] == "volume"]
    return check["measurement"]["value"]


def test_an_edited_helper_reaches_the_second_run_in_one_process(tmp_path: Path):
    """The acceptance test of POST-V0 §8: before invalidation, the second run
    measured the FIRST run's geometry — a stale build reported as fresh, with
    a closure digest taken from the edited file that never got imported."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    target = _closure_target(tmp_path / "m", 1.0)
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    assert main(["check", target, "--quiet", "--out", str(out1)]) == 0
    assert _measured_volume(out1) == pytest.approx(1.0)

    # A different-LENGTH value on purpose: CPython validates a cached .pyc by
    # (mtime seconds, size), so a same-length edit within one second serves
    # stale bytecode to any interpreter — a ceiling beneath this tool's reach,
    # noted on `invalidate_model_modules`.
    _closure_target(tmp_path / "m", 12.5)
    assert main(["check", target, "--quiet", "--out", str(out2)]) == 0
    assert _measured_volume(out2) == pytest.approx(12.5), "the edited helper must be re-imported"


def test_a_helper_the_contract_imports_is_invalidated_too(tmp_path: Path):
    """PR #104's review blocker: a helper the CONTRACT imports top-level
    enters sys.modules during resolve, before the build's snapshot — so it
    was never recorded, never evicted, and an edit produced POST-V0 §8's
    worst case verbatim: a stale build with a closure digest of the edited
    file that never reached the interpreter. Resolution is snapshot now."""
    pytest.importorskip("build123d", reason="occt extra not installed")

    def write(size: float) -> str:
        d = tmp_path / "m"
        d.mkdir(exist_ok=True)
        (d / "contract_helper.py").write_text(f"SIZE = {size}\n")
        (d / "model.py").write_text(
            "from build123d import Box\n\n\ndef make_part(size=1.0):\n    return Box(size, 1, 1)\n"
        )
        spec = d / "spec.py"
        spec.write_text(
            "from contract_helper import SIZE\n"
            "from partspec import Part, build123d\n\n\ndef make():\n"
            "    p = Part('subject', build123d('model.py', size=SIZE))\n"
            "    p.volume(min=0.0)\n"
            "    return p\n"
        )
        return f"{spec}:make"

    target = write(1.0)
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    assert main(["check", target, "--quiet", "--out", str(out1)]) == 0
    assert _measured_volume(out1) == pytest.approx(1.0)

    write(12.5)  # different length: sidestep the .pyc mtime-second ceiling
    assert main(["check", target, "--quiet", "--out", str(out2)]) == 0
    assert _measured_volume(out2) == pytest.approx(12.5), (
        "the contract's own import must be re-read, not served from sys.modules"
    )


@needs_scad_tier
def test_garbage_timeout_env_still_placeholders_every_target(tmp_path: Path, monkeypatch):
    """The fan-out exists so an invocation that dies at the door leaves every
    target's artifact saying the run died — never a previous verdict."""
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    bad = _scad_target(tmp_path, "bad", "    p.watertight()\n")
    assert main(["check", good, bad, "--quiet"]) == 0

    monkeypatch.setenv("PARTSPEC_TIMEOUT", "soon")
    assert main(["check", good, bad, "--quiet"]) == 64
    assert _report(good)["verdict"] == "error", "the stale pass must not survive"
    assert _report(bad)["verdict"] == "error"


def test_an_interrupt_leaves_no_stale_pass_behind_it(tmp_path: Path):
    """A batch interrupted at part two meant to re-check part three; part
    three's previous pass sitting untouched would be a stale artifact reading
    as current. Placeholders for every target go down before any runs."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    calm = _closure_target(tmp_path / "calm", 1.0)
    assert main(["check", calm, "--quiet"]) == 0

    interrupting = tmp_path / "interrupting.py"
    interrupting.write_text("def make():\n    raise KeyboardInterrupt\n")
    assert main(["check", f"{interrupting}:make", calm, "--quiet"]) == 130
    report = report_of(tmp_path / "calm" / "outputs" / "spec-make")
    assert report["verdict"] == "error", "the never-reached target's artifact says the run died"


def test_batch_of_two_python_models_each_measures_its_own(tmp_path: Path):
    """PR #101's review demonstrated the cross live: model B built with model
    A's cached helper. In one batch invocation each part must measure its own."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    a = _closure_target(tmp_path / "a", 1.0)
    b = _closure_target(tmp_path / "b", 3.0)
    assert main(["check", a, b, "--quiet"]) == 0
    vol_a = _measured_volume(tmp_path / "a" / "outputs" / "spec-make")
    vol_b = _measured_volume(tmp_path / "b" / "outputs" / "spec-make")
    assert vol_a == pytest.approx(1.0)
    assert vol_b == pytest.approx(3.0), "model B must not build with model A's cached helper"


@needs_scad_tier
def test_a_batch_records_one_environment_for_every_target(tmp_path: Path):
    """`environment.packages` must not depend on batch position.

    The targets share one interpreter, so a field derived from `sys.modules`
    makes a part's recorded environment a function of what ran before it. The
    first cut of #211 did exactly that and the OpenSCAD part's report claimed
    `build123d` and `cadquery-ocp` as inputs to a build that never touched
    them — 6 distributions run alone, 41 run behind a build123d part, from
    identical inputs on one machine, which SPEC-report §8 rule 2 forbids and
    which `diff` then reported as 35 packages appearing between two runs of
    the same part.

    Deliberately cross-tier and in that order: an OpenSCAD part behind a
    build123d part is the case where the contamination is both largest and
    most obviously wrong. The equality is over the whole map, not a
    spot-check, because the failure was 35 extra entries and not a wrong one.
    """
    pytest.importorskip("build123d", reason="occt extra not installed")
    heavy = _closure_target(tmp_path / "heavy", 1.0)
    light = _scad_target(tmp_path, "light", "    p.watertight()\n")
    assert main(["check", heavy, light, "--quiet"]) == 0

    heavy_env = report_of(tmp_path / "heavy" / "outputs" / "spec-make")["environment"]
    light_env = _report(light)["environment"]
    assert light_env["packages"] == heavy_env["packages"]
    assert light_env["packages"], "an empty map on both sides would satisfy equality"


def _install(site: Path, distribution: str, module: str) -> None:
    """A distribution whose NAME differs from the module it installs.

    `imports` keys a RECORD-owned entry by DISTRIBUTION and an unowned one by
    module, and `preloaded` is intersected with it, so a snapshot taken over
    raw `sys.modules` names silently drops every entry whose two names differ
    — 7 of 39 in this repo's own venv (`cadquery-ocp`, `Pygments`,
    `charset-normalizer`, …), each then claimed as this part's own. A
    single-file module named for its distribution is the one shape that
    cannot tell the two apart, which is why this fixture exists.

    The RECORD's digests are never verified against the files; ownership is
    the row's path, which is what this is here to exercise.
    """
    site.mkdir(parents=True, exist_ok=True)
    (site / f"{module}.py").write_text("VALUE = 29\n")
    info = site / f"{distribution.replace('-', '_')}-1.0.dist-info"
    info.mkdir(exist_ok=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 1.0\n")
    (info / "RECORD").write_text(f"{module}.py,sha256=0000,12\n")


def _inheriting_target(d: Path, part_id: str, imports: dict[str, Path], model: str) -> str:
    """A build123d part whose CONTRACT imports modules from other directories.

    Other, because `_invalidate_after` evicts what was loaded from beside the
    contract and beside the model, and a leader's imports must survive into
    the next target — that survival is the subject. Imported by the contract
    rather than by the model so the name is in `sys.modules` however the build
    goes, and so the FOLLOWER's own contract import lands after the snapshot
    the runner takes for it.
    """
    d.mkdir(exist_ok=True)
    (d / "model.py").write_text(model)
    spec = d / "spec.py"
    paths = "".join(f"sys.path.insert(0, {str(p)!r})\n" for p in imports.values())
    names = "".join(f"import {name}\n" for name in imports)
    spec.write_text(
        f"import sys\n\n{paths}{names}"
        "from partspec import Part, build123d\n\n\n"
        "def make():\n"
        f"    p = Part({part_id!r}, build123d('model.py'))\n"
        "    p.volume(min=0.0)\n"
        "    return p\n"
    )
    return f"{spec}:make"


def _cold(*argv: str) -> None:
    """One `partspec` invocation in a fresh interpreter.

    This process has imported engines and libraries for other tests, and
    `imports._BASELINE` is captured when partspec is — under pytest that is
    after the runner is loaded and before most of the suite, so an in-process
    run cannot tell an inherited import from a pre-existing one. The claim
    here is about what a user's `partspec check` records, so it is measured in
    the shape a user runs it (the pattern `test_refs_import_pulls_no_engine`
    uses, for the same reason).
    """
    proc = subprocess.run(
        [sys.executable, "-m", "partspec", *argv], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


def test_a_batch_says_which_imports_it_did_not_load_itself(tmp_path: Path):
    """`source_closure.imports` must not read as a per-part fact either.

    The same hazard as the test above, one field down and one release later:
    `imports` is read from `sys.modules`, so a Python part behind another one
    inherits every distribution the earlier target loaded. Measured on the
    v0.7.5 pre-tag audit, a build123d cube recorded 38 imports alone and 44
    behind a CadQuery target, `cadquery` among them — and `diff` over those
    two reports of one part said `inputs appeared: cadquery 2.8.0, casadi
    3.7.2, +4 more` at exit 0, which is a positive finding built out of the
    batch order.

    Two PYTHON-tier targets, deliberately: the guard above pairs an OpenSCAD
    part with a build123d one, and OpenSCAD emits `imports: {}`
    unconditionally, so that combination is the one that cannot catch this.

    The map itself stays wide — over-reporting never turns a real build input
    into silence, and a `sys.modules` delta would drop a library the second
    target genuinely uses because the first loaded it first. What must not be
    wide is the claim, so the closure names what it inherited.

    Three decisions inside that claim are pinned here, each of which survived
    the whole suite when mutated during review: the snapshot's boundary, the
    name it is keyed by, and its scope.
    """
    pytest.importorskip("build123d", reason="occt extra not installed")
    site = tmp_path / "site"
    _install(site, "batch-lib-29", "batchlib29")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "followerlib29.py").write_text("VALUE = 1\n")

    follower_dir = tmp_path / "follower"
    follower_dir.mkdir()
    (follower_dir / "fhelper29.py").write_text("SIZE = 1.0\n")
    follower = _inheriting_target(
        follower_dir,
        "follower",
        {"followerlib29": elsewhere},
        "import fhelper29\nfrom build123d import Box\n\n\n"
        "def make_part():\n    return Box(fhelper29.SIZE, 1, 1)\n",
    )
    # The leader loads all three: an installed distribution, and the
    # follower's OWN model-directory helper, which the follower's map
    # excludes because its closure digest already covers it.
    leader = _inheriting_target(
        tmp_path / "leader",
        "leader",
        {"batchlib29": site, "fhelper29": follower_dir},
        "from build123d import Box\n\n\ndef make_part():\n    return Box(2, 1, 1)\n",
    )

    _cold("check", follower, "--quiet", "--out", str(tmp_path / "alone"))
    alone = report_of(tmp_path / "alone")["part"]["source_closure"]
    assert alone["preloaded"] == [], "one target in a process inherits nothing"
    assert "batch-lib-29" not in alone["imports"]

    _cold("check", leader, follower, "--quiet")
    behind = _report(follower)["part"]["source_closure"]
    assert "batch-lib-29" in behind["imports"], "the map over-reports on purpose"
    assert set(behind["imports"]) - set(alone["imports"]) <= set(behind["preloaded"]), (
        "every entry the batch position added must be named as unattributable"
    )

    # Keyed the way `imports` is, by distribution — a snapshot of raw
    # `sys.modules` names would drop this entry and claim it as the part's.
    assert "batch-lib-29" in behind["preloaded"]
    assert "batchlib29" not in behind["preloaded"]
    # Taken BEFORE the contract is resolved: this part's contract imported
    # `followerlib29` itself, and a snapshot taken after resolution would
    # report the part's own import as inherited.
    assert "followerlib29" in behind["imports"]
    assert "followerlib29" not in behind["preloaded"]
    # Scoped to entries of `imports` (SPEC-report §8.3 rule 7). The leader
    # loaded the follower's model-directory helper, which the map excludes,
    # so naming it here would be a claim about an entry the map does not have.
    assert "fhelper29" not in behind["imports"]
    assert set(behind["preloaded"]) <= set(behind["imports"])


def test_resolving_a_contract_records_its_sibling_imports(tmp_path: Path):
    """PR #147's review, major 5: the recording in `target.resolve()` was
    held only by running the suite in reverse file order — which CI does not
    do, and no justfile recipe offers. Deleting the call passed 742 tests in
    the order that actually runs. Bound directly here instead.

    The `finally` half matters more than the success half: a contract that
    imports its sibling and THEN raises is issue #114's path 1, and an
    unrecorded leak there is exactly what outlives the run.
    """
    import sys

    from partspec.engines.pycad import _LOADED_MODEL_MODULES, invalidate_model_modules
    from partspec.target import resolve

    d = tmp_path / "recorded"
    d.mkdir()
    (d / "helper_mod.py").write_text("VALUE = 1\n")
    spec = d / "spec.py"
    spec.write_text(
        "from helper_mod import VALUE\n"
        "from partspec import Part, openscad\n\n\n"
        "def make():\n"
        "    return Part('p', openscad('x.scad'))\n"
    )
    resolve(f"{spec}:make")
    assert "helper_mod" in _LOADED_MODEL_MODULES.get(str(d), set()), (
        "a contract's sibling import must be tracked for eviction"
    )

    # The payoff of recording, and the reason the registry exists: the name
    # can now be evicted, so the NEXT directory's same-named helper is read
    # from disk instead of served from cache.
    invalidate_model_modules(spec)
    assert "helper_mod" not in sys.modules

    raiser = tmp_path / "raising"
    raiser.mkdir()
    (raiser / "helper_mod.py").write_text("VALUE = 2\n")
    bad = raiser / "spec.py"
    bad.write_text("from helper_mod import VALUE\n\nraise TypeError('after the import')\n")
    with pytest.raises(Exception, match="after the import"):
        resolve(f"{bad}:make")
    assert "helper_mod" in _LOADED_MODEL_MODULES.get(str(raiser), set()), (
        "the raise path is the one that most needs the record (#114 path 1)"
    )
    invalidate_model_modules(bad)


def test_running_a_part_evicts_the_models_own_siblings(tmp_path: Path):
    """`runner.py`'s eviction call site had no binding test in the order CI
    actually runs — deleting it passed all 749. PR #147's review found it
    while proving that an autouse conftest fixture (since removed) would
    have masked it permanently.

    This is the library-caller path: `run()` without the CLI around it, which
    is what `test_differential` does and what any embedder does.
    """
    import sys

    pytest.importorskip("build123d", reason="occt extra not installed")
    from partspec.runner import run
    from partspec.target import resolve

    d = tmp_path / "modeldir"
    d.mkdir()
    (d / "geo_helper.py").write_text("SIZE = 4.0\n")
    (d / "model.py").write_text(
        "from build123d import Box\nfrom geo_helper import SIZE\n\n\n"
        "def make_part():\n    return Box(SIZE, SIZE, SIZE)\n"
    )
    spec = py_target(d, model="model.py", part_id="m", claims="    p.watertight()\n")
    part, target = resolve(spec)
    report = run(part, out_dir=tmp_path / "out")
    # The build succeeding IS the proof that `geo_helper` was imported: the
    # model reads SIZE from it. So an absent module after the run means it
    # was imported and then evicted, not that it was never there.
    assert report.verdict is Verdict.PASS, "the model must actually build from its sibling"
    assert "geo_helper" not in sys.modules, (
        "run() must evict the model's siblings, or the next build in this "
        "process gets a stale helper and reports it as fresh"
    )
    from partspec.engines.pycad import invalidate_model_modules

    invalidate_model_modules(target.path)


@needs_scad_tier
def test_a_contracts_shared_claims_module_does_not_cross_directories(tmp_path: Path):
    """PR #112's review: the taught `from claims import shared_claims`
    pattern, copied into two directories and batched, served directory A's
    cached claims module to directory B's contract — part B green under part
    A's checks. The eviction registry now covers contract-sibling imports on
    every engine."""
    for name, body in (("a", "p.watertight()"), ("b", "p.solid_count(1)")):
        d = tmp_path / name
        d.mkdir()
        (d / "m.scad").write_text("cube([2, 2, 2]);\n")
        (d / "claims.py").write_text(f"def shared_claims(p):\n    {body}\n    return p\n")
        (d / "spec.py").write_text(
            "from claims import shared_claims\n\n"
            "from partspec import Part, openscad\n\n\ndef make():\n"
            f"    return shared_claims(Part('{name}', openscad('m.scad')))\n"
        )
    targets = [f"{tmp_path / 'a' / 'spec.py'}:make", f"{tmp_path / 'b' / 'spec.py'}:make"]
    assert main(["check", *targets, "--quiet"]) == 0

    def kinds(d: Path) -> set[str]:
        report = report_of(d / "outputs" / "spec-make")
        return {c["kind"] for c in report["checks"]} - {"builds"}

    assert kinds(tmp_path / "a") == {"watertight"}
    assert kinds(tmp_path / "b") == {"solid_count"}, (
        "part B must be checked by ITS claims module, not directory A's cached one"
    )


@needs_scad_tier
def test_a_contract_that_raises_after_its_sibling_import_does_not_poison_the_next_run(
    tmp_path: Path,
):
    """#114 path 1: the sibling import succeeded, THEN the contract raised —
    the record now lands in _resolve_or_report's finally and the failed
    resolve evicts, so directory B still gets its own module."""
    a, b = tmp_path / "a", tmp_path / "b"
    for d, body in ((a, "p.watertight()"), (b, "p.solid_count(1)")):
        d.mkdir()
        (d / "m.scad").write_text("cube([2, 2, 2]);\n")
        (d / "claims.py").write_text(f"def shared_claims(p):\n    {body}\n    return p\n")
    (a / "spec.py").write_text(
        "from claims import shared_claims\n\nraise TypeError('broken after the import')\n"
    )
    (b / "spec.py").write_text(
        "from claims import shared_claims\n\n"
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return shared_claims(Part('b', openscad('m.scad')))\n"
    )
    # An import-time raise is a contract error, exit 4 (#438); it still fails resolve.
    assert main(["check", f"{a / 'spec.py'}:make", "--quiet"]) == 4
    assert main(["check", f"{b / 'spec.py'}:make", "--quiet"]) == 0
    report = report_of(b / "outputs" / "spec-make")
    kinds = {c["kind"] for c in report["checks"]} - {"builds"}
    assert kinds == {"solid_count"}, "B must not inherit A's cached claims module"


def test_a_check_render_run_does_not_leave_the_sibling_cached(tmp_path: Path):
    """#114 path 2, as evolved by #18: this used to pin the --render-on-OCCT
    usage refusal; that refusal no longer exists, so the pin is now on the
    full check-with-renders run — the render build must not re-cache what
    the check's eviction already cleared."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    a, b = tmp_path / "a", tmp_path / "b"
    for d, size in ((a, "1.0"), (b, "3.0")):
        d.mkdir()
        (d / "claims.py").write_text(f"SIZE = {size}\n")
        (d / "model.py").write_text(
            "from claims import SIZE\nfrom build123d import Box\n\n\ndef make_part():\n"
            "    return Box(SIZE, 1, 1)\n"
        )
        (d / "spec.py").write_text(
            # The CONTRACT imports the sibling: the refusal path caches it
            # during resolve, which is what must be evicted (PR #124
            # re-review — without this import the test bound nothing).
            "from claims import SIZE\n\n"
            "from partspec import Part, build123d\n\n\ndef make():\n"
            "    p = Part('subject', build123d('model.py'))\n"
            "    p.volume(min=0.0)\n"
            "    return p\n"
        )
    # The run on A caches A's claims module during resolve and build...
    assert main(["check", f"{a / 'spec.py'}:make", "--render", "--quiet"]) == 0
    # ...which must not answer for B's model in the same process.
    assert main(["check", f"{b / 'spec.py'}:make", "--quiet", "--out", str(tmp_path / "o")]) == 0
    vol = _measured_volume(tmp_path / "o")
    assert vol == pytest.approx(3.0), "B built with A's cached SIZE"


def _sibling_pair(tmp_path: Path, raise_in_a: bool = False):
    """Two directories with same-named claims.py siblings; A's contract
    imports its sibling (and optionally raises), B's check must see its own."""
    dirs = {}
    for name, size in (("a", "1.0"), ("b", "3.0")):
        d = tmp_path / name
        d.mkdir()
        (d / "claims.py").write_text(f"SIZE = {size}\n")
        (d / "model.py").write_text(
            "from claims import SIZE\nfrom build123d import Box\n\n\ndef make_part():\n"
            "    return Box(SIZE, 1, 1)\n"
        )
        body = (
            "raise TypeError('after the import')\n"
            if raise_in_a and name == "a"
            else (
                "from partspec import Part, build123d\n\n\ndef make():\n"
                "    p = Part('subject', build123d('model.py'))\n"
                "    p.volume(min=0.0)\n"
                "    return p\n"
            )
        )
        (d / "spec.py").write_text(f"from claims import SIZE\n\n{body}")
        dirs[name] = d
    return dirs


def _b_is_clean(tmp_path: Path, dirs) -> None:
    out = tmp_path / "o"
    assert main(["check", f"{dirs['b'] / 'spec.py'}:make", "--quiet", "--out", str(out)]) == 0
    assert _measured_volume(out) == pytest.approx(3.0), "B built with A's cached SIZE"


def test_the_render_verbs_exits_evict_the_sibling(tmp_path: Path):
    """PR #124 re-review residual: the render verb's eviction call sites had
    no binding test — reverting them passed the suite. Both exits bound: the
    successful OCCT render (#18 replaced the old refusal on this path; the
    try/finally must survive the build) and the failed resolve."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    dirs = _sibling_pair(tmp_path)
    assert main(["render", f"{dirs['a'] / 'spec.py'}:make"]) == 0
    _b_is_clean(tmp_path, dirs)

    (tmp_path / "second").mkdir()
    dirs2 = _sibling_pair(tmp_path / "second", raise_in_a=True)
    assert main(["render", f"{dirs2['a'] / 'spec.py'}:make"]) == 4  # failed resolve (#438)
    _b_is_clean(tmp_path / "second", dirs2)


def test_the_measure_verbs_failed_resolve_evicts_the_sibling(tmp_path: Path):
    pytest.importorskip("build123d", reason="occt extra not installed")
    dirs = _sibling_pair(tmp_path, raise_in_a=True)
    assert main(["measure", f"{dirs['a'] / 'spec.py'}:make"]) == 4  # failed resolve (#438)
    _b_is_clean(tmp_path, dirs)


def test_a_library_the_model_itself_reaches_is_attributed_to_that_target(tmp_path: Path):
    """`preloaded` records an inability; `reached` settles the part of it that
    can be settled (#216).

    `imports` is read from one `sys.modules`, so a follower inherits the
    leader's libraries and `preloaded` has to name all of them — it cannot tell
    an inherited import from one the follower genuinely uses. That is the right
    bound and the wrong answer for the case that matters: a follower whose own
    model imports the shared library really does have it as a build input, and
    silencing it is the under-report §8.3 refuses.

    The object graph can settle it. Walked from the MODEL's modules, so the
    library the follower's model imports is reached while a library only the
    leader loaded is not — whoever imported it first.

    Deliberately imported by the MODEL rather than the contract: the walk
    starts at the model, and the contract is excluded from this closure
    entirely (its digest is `contract_digest`).
    """
    pytest.importorskip("build123d", reason="occt extra not installed")
    site = tmp_path / "site"
    _install(site, "shared-lib-30", "sharedlib30")
    _install(site, "leader-only-30", "leaderonly30")

    follower_dir = tmp_path / "follower"
    follower_dir.mkdir()
    (follower_dir / "model.py").write_text(
        f"import sys\n\nsys.path.insert(0, {str(site)!r})\nimport sharedlib30\n"
        "from build123d import Box\n\n\n"
        "def make_part():\n    return Box(sharedlib30.VALUE / 29, 1, 1)\n"
    )
    (follower_dir / "spec.py").write_text(
        "from partspec import Part, build123d\n\n\n"
        "def make():\n"
        "    p = Part('follower', build123d('model.py'))\n"
        "    p.volume(min=0.0)\n"
        "    return p\n"
    )
    follower = f"{follower_dir / 'spec.py'}:make"

    # The leader loads BOTH, so both are preloaded for the follower and
    # `preloaded` alone cannot tell them apart.
    leader = _inheriting_target(
        tmp_path / "leader",
        "leader",
        {"sharedlib30": site, "leaderonly30": site},
        "from build123d import Box\n\n\ndef make_part():\n    return Box(2, 1, 1)\n",
    )

    _cold("check", leader, follower, "--quiet")
    closure = _report(follower)["part"]["source_closure"]

    assert "shared-lib-30" in closure["preloaded"], "premise: the leader loaded it first"
    assert "leader-only-30" in closure["preloaded"], "premise: inherited, and only that"

    assert "shared-lib-30" in closure["reached"], (
        "the follower's own model imports it, so it is this target's build input"
    )
    assert "leader-only-30" not in closure["reached"], (
        "reaching everything would manufacture findings, which is what preloaded prevents"
    )
    assert set(closure["reached"]) <= set(closure["imports"]), "reached is a subset of imports"
