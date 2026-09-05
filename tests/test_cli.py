"""The CLI surface: `measure`'s output shape and `check`'s exit code.

D5 makes the report schema plus the exit code the product contract, not the
verbs — which is precisely why the verbs need tests. Everything below asserts
something a consumer would break on.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest
from support import (
    decode_png,
    needs_build123d,
    needs_openscad,
    needs_scad_tier,
    py_target,
    report_of,
    scad_target,
)

from partspec import cli
from partspec.cli import main
from partspec.status import EXIT_USAGE, Verdict, exit_code

FIXTURES = Path(__file__).parent / "fixtures"


def _measure(target: str, capsys) -> dict:
    assert main(["measure", target]) == 0, "measure never produces a verdict"
    return json.loads(capsys.readouterr().out)


def _accounted_names(doc: dict) -> set[str]:
    """Every name the measure payload accounts for, asserting the partition.

    Read with `.get` on both optional blocks, which is the rule SPEC-report
    §7.3 states and not a defensive tic: `refused` is absent on a part that
    defeated nothing, and `unavailable` is absent on a tier that can answer
    everything asked — which is the whole OCCT tier, so subscripting it here
    would make this helper `KeyError` on exactly the tier it least covers.

    `measurements` IS subscripted, and deliberately: §7.3 lets it be absent
    too, but only from the failure shape, which carries `error` and reaches
    this helper from nowhere — every caller measures a run that exited 0. A
    successful measure that carried no `measurements` would be the silence
    this project exists to prevent, so it should raise here rather than
    default to empty and read as "nothing to report".
    """
    blocks = [
        set(doc["measurements"]),
        set(doc.get("refused", {})),
        set(doc.get("unavailable", ())),
    ]
    union: set[str] = set().union(*blocks)
    assert sum(len(b) for b in blocks) == len(union), (
        "a name in two blocks at once says two different things about it"
    )
    return union


# --------------------------------------------------------------------------
# the payload discriminator (#295)
# --------------------------------------------------------------------------


@needs_scad_tier
def test_each_payload_says_which_artifact_it_is(tmp_path: Path, capsys):
    """#295. `check`, `measure` and `render` emit `schema_version: 1` under
    `tool.name: "partspec"` and share the whole identity prefix, so a consumer
    holding one of the three could not tell which it had — it had to guess from
    the keys further down, and `diff` accepting a `render` payload at
    `identical`/exit 0 is what that guessing costs.

    Asserted as a SET of four distinct values, not four independent equalities:
    the failure this guards against is two verbs agreeing, and four `==` checks
    that each pass individually cannot see that.
    """
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="    p.watertight()\n")
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 0
    capsys.readouterr()

    seen = {"check": report_of(out)["payload"], "measure": _measure(target, capsys)["payload"]}
    assert main(["render", target, "--out", str(tmp_path / "r")]) in (0, exit_code(Verdict.ERROR))
    seen["render"] = json.loads(capsys.readouterr().out)["payload"]
    assert main(["lint", str(tmp_path / "block_with_hole.scad")]) == 0
    seen["lint"] = json.loads(capsys.readouterr().out)["payload"]

    assert seen == {
        "check": "report",
        "measure": "measure",
        "render": "render",
        "lint": "lint",
    }
    assert len(set(seen.values())) == 4, "a discriminator that repeats discriminates nothing"


@needs_scad_tier
def test_every_verb_records_which_target_it_ran(tmp_path: Path, capsys):
    """#297. The CLI knew the factory all along — it is in the `--out` slug,
    and naming two colliding slugs is a refusal — but it reached neither the
    report nor the `measure`/`render` payloads. Three verbs, three call sites,
    and threading it through only one leaves the other two identity-blind.
    """
    shutil.copy(FIXTURES / "block_with_hole.scad", tmp_path / "block_with_hole.scad")
    module = tmp_path / "same.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\n"
        "def imperial() -> Part:\n"
        "    return Part('widget', openscad('block_with_hole.scad')).watertight()\n\n\n"
        "def metric() -> Part:\n"
        "    return Part('widget', openscad('block_with_hole.scad')).watertight()\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{module}:imperial", "--quiet", "--out", str(out)]) == 0
    capsys.readouterr()

    seen = {"check": report_of(out)["part"]["contract"]}
    seen["measure"] = _measure(f"{module}:imperial", capsys)["part"]["contract"]
    assert main(["render", f"{module}:imperial", "--out", str(tmp_path / "r")]) in (
        0,
        exit_code(Verdict.ERROR),
    )
    seen["render"] = json.loads(capsys.readouterr().out)["part"]["contract"]
    assert set(seen.values()) == {"same.py:imperial"}, seen

    # The sibling factory is the whole point: same id, same source, same
    # module-scoped digest, so the symbol is the only thing left to tell the
    # two artifacts apart.
    other = tmp_path / "out2"
    assert main(["check", f"{module}:metric", "--quiet", "--out", str(other)]) == 0
    capsys.readouterr()
    first, second = report_of(out)["part"], report_of(other)["part"]
    assert first["contract_digest"] == second["contract_digest"], "module-scoped (§7.1)"
    assert first != second, "and the part blocks were byte-identical before #297"


# --------------------------------------------------------------------------
# measure — the adoption path
# --------------------------------------------------------------------------


@needs_scad_tier
def test_measure_reports_the_quantities_it_can_answer(tmp_path: Path, capsys):
    doc = _measure(scad_target(tmp_path, source="block_with_hole.scad", claims=""), capsys)
    assert doc["engine"]["backend"] == "mesh"
    assert doc["measurements"]["volume"]["value"] == pytest.approx(30 * 20 * 10 - 6 * 6 * 10)
    assert "refused" not in doc, "a sound part refuses nothing"


@needs_scad_tier
def test_measure_says_why_it_refused_rather_than_omitting_the_quantity(tmp_path: Path, capsys):
    """The bug this replaced, and the reason it mattered.

    `measure` dropped every `Unsupported` silently. That was honest while a
    refusal only ever meant "this tier cannot answer this quantity" — a static
    fact, the same for every part. Since D17 it also means "this part is
    broken, and here is the defect", and the two arrived identically: absent.

    On an open box that leaves a reader looking at area, bbox and solid_count
    with no volume line, in the verb whose whole job is showing you the numbers
    before you decide which are intent. They would write a contract that
    declines to claim a volume, and the omission would have taught them that.
    """
    doc = _measure(scad_target(tmp_path, source="open_box.scad", claims=""), capsys)

    assert set(doc["refused"]) == {"volume", "center_of_mass", "genus"}
    for name, reason in doc["refused"].items():
        assert "boundary edge" in reason, f"{name} must name the defect, not just decline"
        assert name not in doc["measurements"], "a refusal must not also carry a number"

    assert doc["measurements"]["watertight"]["value"] is False
    assert doc["measurements"]["area"]["value"] == pytest.approx(500.0)


@needs_scad_tier
def test_measure_shows_cavities(tmp_path: Path, capsys):
    """#113: the number distinguishing a sealed enclosure from an open tray
    was absent from the verb whose job is showing every claimable number."""
    doc = _measure(scad_target(tmp_path, source="block_with_hole.scad", claims=""), capsys)
    assert doc["measurements"]["cavities"]["value"] == 0


@needs_scad_tier
def test_measure_separates_a_tier_gap_from_a_broken_part(tmp_path: Path, capsys):
    """Two different silences, and conflating them is what went wrong before.

    `unavailable` is a property of the backend and identical for every part it
    will ever see. `refused` is a property of *this* part. A reader deciding
    what to assert needs to tell "you need the OCCT tier for that" apart from
    "fix your model".
    """
    doc = _measure(scad_target(tmp_path, source="open_box.scad", claims=""), capsys)
    assert doc["unavailable"] == [
        "self_intersection_free",
        "min_wall",
        "topology_counts",
        "bores",
        "blend_radii",
    ]
    assert "topology_counts" not in doc["refused"]


@needs_scad_tier
def test_the_three_measure_blocks_account_for_every_name(tmp_path: Path, capsys):
    """SPEC-report §7.3: every name the verb asks about lands in exactly one of
    `measurements`, `refused` and `unavailable`.

    That is the property the three-block shape exists for — a name absent from
    all three is a silence about a quantity the tool asked for, which is the
    one thing this project says must never happen. Asserted over a sound part
    AND a broken one on the same tier, because the partition is only
    interesting if the SAME vocabulary is accounted for both times: `refused`
    grows and `measurements` shrinks, and the union may not move.
    """
    docs = {}
    for name, source in (("sound", "block_with_hole.scad"), ("broken", "open_box.scad")):
        root = tmp_path / name
        root.mkdir()
        docs[name] = _measure(scad_target(root, source=source, claims=""), capsys)

    unions = {name: _accounted_names(doc) for name, doc in docs.items()}
    assert docs["sound"].get("refused") is None and docs["broken"]["refused"]
    assert unions["sound"] == unions["broken"], (
        "the vocabulary asked is the tier's, not the part's — so a name that "
        "went missing from all three would show up here as a shrunken union"
    )


@needs_scad_tier
def test_one_unmeasurable_quantity_does_not_suppress_the_other_thirteen(tmp_path: Path, capsys):
    """#365. `measure` emitted NOTHING on a zero-thickness part.

    `intersection()` of two cubes meeting on a face exports a closed,
    consistently-wound sheet enclosing no volume. It has no centre of mass, and
    the backend's `nan` reached `Measurement`, which refused it by raising —
    out of the per-name loop, through the verb, to exit 4 with an empty stdout.
    `area` and `bbox` need no volume and the same part answers both through
    `check`, so the verb whose job is dumping every honest quantity produced
    strictly less than the verb that decides.
    """
    doc = _measure(scad_target(tmp_path, source="zero_thickness.scad", claims=""), capsys)

    assert doc["measurements"]["area"]["value"] == pytest.approx(480.0)
    assert doc["measurements"]["bbox"]["value"] == pytest.approx([20.0, 12.0, 0.0])
    assert doc["measurements"]["volume"]["value"] == 0.0, "0.0 is an answer, not an absence"
    assert "no volume" in doc["refused"]["center_of_mass"]
    assert "center_of_mass" not in doc["measurements"]
    assert _accounted_names(doc), "the partition still covers the whole vocabulary"


@needs_scad_tier
def test_a_backend_that_raises_costs_one_name_and_not_the_run(tmp_path: Path, capsys, monkeypatch):
    """The bound on the next backend that slips a non-finite value through.

    The mesh tier's own case is fixed in the backend, where the inability to
    answer is known. This pins what a backend fault may cost when the next one
    is not: exactly the name that raised, recorded in `refused` — a property of
    THIS artifact, where `unavailable` is a property of the tier
    (SPEC-report.md §7.3) — with every other name still emitted, and no verdict.
    """
    from partspec.backends.mesh import MeshBackend
    from partspec.status import ContractError

    def explode(self, a):
        raise ContractError("measurement value is nan, which is not a number")

    monkeypatch.setattr(MeshBackend, "area", explode)
    doc = _measure(scad_target(tmp_path, source="block_with_hole.scad", claims=""), capsys)

    assert "nan" in doc["refused"]["area"] and "mesh" in doc["refused"]["area"]
    assert "area" not in doc["measurements"]
    assert doc["measurements"]["volume"]["value"] == pytest.approx(30 * 20 * 10 - 6 * 6 * 10)
    assert "verdict" not in doc, "measure decides nothing, including here"
    # SPEC-report 7.3's partition, on the backstop path as well as the
    # fixture one: a name lost to a raise must still land in exactly one
    # of the three blocks, or the payload stops accounting for the
    # vocabulary (PR #369 review, N3).
    assert _accounted_names(doc)


@needs_build123d
def test_a_tier_that_answers_everything_omits_both_optional_blocks(tmp_path: Path, capsys):
    """SPEC-report §7.3, the OCCT half — and the reason it is a MUST that a
    consumer read the two optional blocks with a default.

    The OCCT capability set covers all fourteen names the verb asks, so a
    build123d payload carries neither `refused` nor `unavailable`: a consumer
    following "read all three" by subscript gets a `KeyError` on its first
    build123d part. That is the defect class #302 fixed for `partial`, and
    §7.3 was written from mesh-tier runs alone, where `unavailable` is never
    empty. The partition property itself is tier-independent, which is why it
    is asserted here too rather than only on the tier that exercises all three.
    """
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 5)\n"
    )
    doc = _measure(py_target(tmp_path), capsys)

    assert "unavailable" not in doc and "refused" not in doc
    assert list(doc) == [
        "schema_version",
        "payload",
        "tool",
        "part",
        "engine",
        "params",
        "geometry",
        "measurements",
    ]
    assert _accounted_names(doc) == set(doc["measurements"]), (
        "with both optional blocks absent, `measurements` accounts for the whole ask"
    )

    # And the same eight keys are the MINIMAL shape, not a key set to validate
    # against: §7.3 says `refused` and `artifact` each extend it, and both are
    # reachable on THIS tier. Pinned here because the sentence above reads as
    # an exact enumeration and would otherwise licence a strict validator that
    # rejects valid payloads.
    assert main(["measure", py_target(tmp_path), "--out", str(tmp_path / "art")]) == 0
    with_out = json.loads(capsys.readouterr().out)
    assert list(with_out) == [*doc, "artifact"], "`--out` extends the minimal shape"

    (tmp_path / "two.py").write_text(
        "from build123d import Box, Compound, Location\n\n\ndef make_part():\n"
        "    return Compound(children=[Box(10, 10, 10), Location((50, 0, 0)) * Box(10, 10, 10)])\n"
    )
    two = _measure(py_target(tmp_path, model="two.py", part_id="two"), capsys)
    assert list(two) == [*doc, "refused"], "a part that defeats a measurement extends it too"
    assert "genus" in two["refused"] and "genus" not in two["measurements"]


@needs_build123d
def test_an_empty_vector_measurement_still_names_its_axes(tmp_path: Path, capsys):
    """SPEC-report §2.1: `axes` is REQUIRED on vector measurements.

    A measurement is vector iff `value` is an array, so an empty array is a
    vector. `measure` gated the field on truthiness, so a plain box — no bores,
    no blends — emitted `{"value": []}` with no `axes`, while the same part
    with two bores carried it. The field's presence tracked the PART rather
    than the shape, and it went missing on exactly the parts that are simplest
    (#346). `report.py` was already presence-based; this is the payload
    catching up.
    """
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 5)\n"
    )
    doc = _measure(py_target(tmp_path), capsys)

    empty = {n: m for n, m in doc["measurements"].items() if m["value"] == []}
    assert set(empty) == {"bores", "blend_radii"}, "the box defeats neither, it has none"
    for name, m in doc["measurements"].items():
        if isinstance(m["value"], list):
            assert "axes" in m, f"{name} is a vector measurement with no axes"
            assert len(m["axes"]) == len(m["value"])


@needs_scad_tier
def test_measure_produces_no_verdict_on_a_broken_part(tmp_path: Path, capsys):
    """Exit 0 on an open box is correct here and would be a bug in `check`.

    `measure` asks no question, so it cannot answer one wrongly. The verdict
    machinery deliberately does not run.
    """
    doc = _measure(scad_target(tmp_path, source="open_box.scad", claims=""), capsys)
    assert "verdict" not in doc and "checks" not in doc


@needs_scad_tier
def test_measure_refuses_a_part_the_engine_hollowed_out(tmp_path: Path, capsys):
    """`measure` is where numbers become claims, so a wrong one outlives the run.

    Exit 0 on a broken part is correct for this verb (see above) -- it asks no
    question. This is not that. The engine dropped a call it could not resolve
    and exported a mesh of something the source does not describe, so the
    quantities are real measurements of the wrong object. An author reading
    `volume: 7200.0 exact` off a hollowed part writes it into a contract that
    then passes forever (#286).
    """
    src = tmp_path / "hollow.scad"
    src.write_text("difference() {\n  cube([40,30,6], center=true);\n  bore_hole(d=8);\n}\n")
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('hollow', openscad('hollow.scad'))\n"
    )

    assert main(["measure", f"{spec}:make"]) == 4
    captured = capsys.readouterr()

    # The JSON, not the console: SPEC-report's Scope requires the identity
    # prefix plus error/hint on any failure after the target resolves, and an
    # implementation printing to stderr alone would satisfy a stderr-only
    # assertion while being machine-invisible -- the exact defect #47 fixed.
    doc = json.loads(captured.out)
    assert doc["part"]["id"] == "hollow"
    assert "measurements" not in doc, "no quantity may be offered off a hollowed part"
    assert "bore_hole" in doc["error"]
    assert "something other than what this source describes" in doc["error"]
    assert doc["hint"]
    assert "bore_hole" in captured.err


@needs_scad_tier
def test_measure_names_the_conversion_cause_and_not_the_include_path(tmp_path: Path, capsys):
    """`measure` must diagnose a defaulted value the way `check` does.

    The verb matters here more than anywhere: `measure` is what an author turns
    into a contract, so a refusal that sends them to `OPENSCADPATH` costs them
    the search before they find the expression that was never bound. Every name
    in this source resolves; nothing is missing from the machine.

    Round-1 review found this surface defended by nothing -- reverting the call
    to the hardcoded name pair left all 267 tests in these three files green
    while `measure` went back to printing the include-path hint on a value that
    would not convert (#308).
    """
    src = tmp_path / "defaulted.scad"
    src.write_text("o = undef;\ncube(size=[o, 30, 6]);\n")
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('defaulted', openscad('defaulted.scad'))\n"
    )

    assert main(["measure", f"{spec}:make"]) == 4
    doc = json.loads(capsys.readouterr().out)

    assert "measurements" not in doc, "a 1x1x1 unit cube is not this part"
    assert doc["error"].startswith(
        "the engine could not convert a value and built a default in place of it"
    )
    assert "Unable to convert" in doc["error"], "the engine's own line, quoted"
    assert "resolve a name" not in doc["error"]
    assert "OPENSCADPATH" not in doc["hint"], "nothing here is missing from the machine"


@needs_scad_tier
def test_measure_out_file_refuses_without_touching_the_destination(tmp_path: Path, capsys):
    """A refusal must leave `--out FILE` exactly as the caller left it.

    Asked after the rename, the refusal replaced a good artifact with the
    hollowed one and then declined to measure it -- a documented refusal that
    destroys the destination, which is worse than the silence it replaced.
    Round-2 review of PR #306; the rule is `_build_to_file`'s own docstring.
    """
    # A bore the hollowed build cannot reproduce. A bare cube here would make
    # this test VACUOUS: `bad.scad` degenerates to exactly a bare cube, so the
    # two artifacts came out byte-identical and the assertion below held whether
    # the guard ran before the rename or after it -- round-3 review of PR #306
    # caught it standing over the very bug it was written for.
    good = tmp_path / "good.scad"
    good.write_text(
        "difference() {\n  cube([40,30,6], center=true);\n"
        "  cylinder(d=8, h=20, center=true, $fn=64);\n}\n"
    )
    bad = tmp_path / "bad.scad"
    bad.write_text("difference() {\n  cube([40,30,6], center=true);\n  bore_hole(d=8);\n}\n")
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\n"
        "def good():\n    return Part('good', openscad('good.scad'))\n\n\n"
        "def bad():\n    return Part('bad', openscad('bad.scad'))\n"
    )
    dest = tmp_path / "dst" / "thing.stl"

    assert main(["measure", f"{spec}:good", "--out", str(dest)]) == 0
    before = dest.read_bytes()
    capsys.readouterr()

    hollowed = tmp_path / "hollowed.stl"
    assert main(["measure", f"{spec}:bad", "--out", str(hollowed)]) == 4
    assert not hollowed.exists(), "the refusal wrote its artifact anyway"

    assert main(["measure", f"{spec}:bad", "--out", str(dest)]) == 4
    after = dest.read_bytes()
    assert after == before, "the refusal overwrote the caller's artifact"
    # And the two are genuinely distinguishable, so the assertion above is not
    # satisfied by the parts happening to render the same bytes.
    assert len(before) > 1000, "the good artifact must not degenerate to a bare cube"


# --------------------------------------------------------------------------
# measure --out (#187): the flag means what a reader passes
# --------------------------------------------------------------------------


@needs_scad_tier
def test_measure_writes_the_artifact_at_the_filename_it_was_given(tmp_path: Path, capsys):
    """An `.stl` path is honoured as the artifact.

    Found by an adoption agent, four times in a row: `--out .../a.stl` made a
    DIRECTORY called `a.stl` holding `block_with_hole.stl`, and exited 0. A
    run that reports success having written something else, somewhere else,
    is the silent success this tool is built to refuse.
    """
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    dest = tmp_path / "art" / "a.stl"
    assert main(["measure", target, "--out", str(dest)]) == 0
    assert dest.is_file(), "the path named a file, so the artifact is that file"
    assert dest.stat().st_size > 0
    assert list(dest.parent.iterdir()) == [dest], "and nothing else was left beside it"
    json.loads(capsys.readouterr().out)


@needs_scad_tier
def test_measure_overwrites_a_path_that_already_exists_as_a_file(tmp_path: Path, capsys):
    """The second case of #187: the same command exited 4 ("could not create
    the output directory ...: File exists") purely because the path already
    existed. Prior state decided what the flag meant; now the flag does."""
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    dest = tmp_path / "a.stl"
    dest.write_text("stale")
    assert main(["measure", target, "--out", str(dest)]) == 0
    assert dest.is_file()
    assert dest.read_bytes() != b"stale"
    json.loads(capsys.readouterr().out)


@needs_scad_tier
@pytest.mark.parametrize(
    "name",
    [
        "out",  # the documented shape
        "run.2026-08-13",  # a dated directory is not a filename
        "v1.2",  # nor a versioned one
        "renders.d/",  # a trailing separator is directory intent, stated
        "a.stl/",  # even when the name is one the engine could write
        "UP.STL",  # partspec never writes this spelling, so it is not output
    ],
)
def test_measure_out_takes_a_directory_unless_the_name_is_an_stl(tmp_path: Path, capsys, name: str):
    """Only `.stl` — the one format the OpenSCAD tier exports — makes `--out`
    a filename. "Any suffix" was the first attempt at #187 and it turned
    `--out run.2026-08-13/` into a mesh FILE with that name: exit 0, wrong
    noun, which is case 1 of the bug mirrored. A trailing separator settles it
    outright, which is why the flag keeps the raw string rather than a Path.
    """
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    assert main(["measure", target, "--out", f"{tmp_path}/{name}"]) == 0
    out = tmp_path / name
    assert out.is_dir(), "a directory was asked for"
    assert (out / "block_with_hole.stl").stat().st_size > 0
    json.loads(capsys.readouterr().out)


@needs_scad_tier
def test_measure_out_leaves_an_existing_directory_a_directory(tmp_path: Path, capsys):
    """Whatever it is called. `--out a.stl` where `a.stl/` is already a
    directory writes into it rather than trying to replace it."""
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    out = tmp_path / "a.stl"
    out.mkdir()
    assert main(["measure", target, "--out", str(out)]) == 0
    assert (out / "block_with_hole.stl").stat().st_size > 0
    json.loads(capsys.readouterr().out)


@needs_scad_tier
@pytest.mark.parametrize("victim", ["block_with_hole.scad", "spec.py"])
def test_measure_out_never_overwrites_a_path_the_engine_could_not_have_written(
    tmp_path: Path, capsys, victim: str
):
    """The fix's own worst failure mode, caught in review before it shipped.

    While `--out` honoured *any* suffix, `--out ds/spacer.scad` replaced the
    run's own source with 13 KB of binary STL and exited 0 — printing a
    complete, correct measurement payload for a part whose source no longer
    existed. `--out ds/spec.py` did the same to the contract. One tab
    completion in a models directory was the whole trigger. A name the engine
    cannot produce is not a filename this flag understands, so it falls
    through to the directory rule and is refused there, exactly as it was
    before #187 was touched.
    """
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    dest = tmp_path / victim
    before = dest.read_bytes()
    assert main(["measure", target, "--out", str(dest)]) == exit_code(Verdict.ERROR)
    assert dest.read_bytes() == before, "the source of the run is not an output path"
    assert "File exists" in json.loads(capsys.readouterr().out)["error"]


@needs_scad_tier
def test_measure_out_does_not_overwrite_a_neighbour_of_the_file_it_was_given(
    tmp_path: Path, capsys
):
    """The engine names its export after the source, so building straight into
    the destination's directory would unlink the caller's own
    `block_with_hole.stl` on the way to writing `a.stl`."""
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    neighbour = tmp_path / "art" / "block_with_hole.stl"
    neighbour.parent.mkdir()
    neighbour.write_text("mine")
    assert main(["measure", target, "--out", str(neighbour.parent / "a.stl")]) == 0
    assert neighbour.read_text() == "mine"
    json.loads(capsys.readouterr().out)


@needs_scad_tier
def test_measure_out_leaves_the_destination_alone_when_the_build_fails(tmp_path: Path, capsys):
    """Nothing touches the destination until there is an artifact for it.

    A revision of this fix unlinked the destination up front, to match the
    target unlink in `openscad.render`. Two things were wrong with that.
    `notes/FINDINGS.md` W9 offers the unlink *or* a temp path moved into place
    — this is the second, and the staleness W9 describes cannot arise here
    anyway, since the build runs in a fresh scratch directory and the
    measurement is read from there, never from `dest`. What the unlink did
    reach was the caller's file: a blown timeout, a build error or a Ctrl-C
    deleted it for nothing. `os.replace` gives the whole guarantee — the old
    file or the new one, never neither, never half of one.
    """
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    dest = tmp_path / "a.stl"
    assert main(["measure", target, "--out", str(dest)]) == 0
    before = dest.read_bytes()
    capsys.readouterr()

    code = main(["measure", target, "--out", str(dest), "--timeout", "0.001"])
    assert code == exit_code(Verdict.ERROR)
    assert dest.read_bytes() == before, "a failed run may not consume the file it was given"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".partspec-build-")]
    json.loads(capsys.readouterr().out)


@needs_scad_tier
@pytest.mark.parametrize(
    ("source", "grounds"),
    [
        ("imports_data.scad", ("one of its own inputs",)),
        ("imports_stl_data.scad", ("one of its own inputs", "contradicts the source")),
    ],
)
def test_measure_out_refuses_a_file_when_the_model_reads_external_data(
    tmp_path: Path, capsys, source: str, grounds: tuple[str, ...]
):
    """`.stl` is an input extension as well as an output one.

    `import()` reads one, and SPEC-report §8.3 says so — those paths "genuinely
    are build inputs", and may be computed at render time, so no static reader
    can resolve them. Writing the artifact over one changes what the NEXT run
    measures: with the destination consumed, the model built without its
    import and reported a confident `[5, 5, 5]` for a part that measures
    `[10, 10, 10]`, at exit 0. That is the defect #187 exists to abolish,
    reached through its own fix.

    Both spellings, because the first fix only closed one. `import_stl()` is
    deprecated and 2021.01 still runs it, and the guard's `import(` pattern
    demanded the paren straight after the name — so three consecutive runs of
    the `import_stl` model ate their own input and answered `[30,10,10]`,
    `[50,10,10]`, `[70,10,10]`, each at exit 0, with nothing on stderr.

    **The refusal is exact since #263 and the exit code is not.** It used to
    fire before the render on the mere presence of `import()`; it now fires
    after it, on the engine's own dependency list, and names the file that was
    actually read rather than the fact that some file was. `EXIT_USAGE` is
    pinned here deliberately: the same invocation was refused at 64 when the
    answer was a guess, the caller's remedy is still a different `--out`, and a
    script reading the exit code must not see a build failure where an argument
    is what is wrong.

    **`grounds` is a list because `import_stl` gets a different one per
    engine, and that is F13 rather than a choice.** 2021.01 executes the
    deprecated spelling, so the depfile names the file and the refusal is the
    exact one; the 2026.08.01 snapshot ignores it, so the render reads no data
    at all, the two accounts of the source contradict each other, and the
    refusal is the conservative one. Asserting the 2021.01 phrasing as
    universal is what the first cut of #263 did, and the matrix caught it.
    What holds on both is what a caller reads: exit 64, the donor untouched,
    and a refusal that names the file at stake.
    """
    (tmp_path / "input.stl").write_bytes(b"donor")
    target = scad_target(tmp_path, source=source, claims="")
    dest = tmp_path / "input.stl"
    assert main(["measure", target, "--out", str(dest)]) == 64
    assert dest.read_bytes() == b"donor", "an input is not an output path"
    doc = json.loads(capsys.readouterr().out)
    assert "input.stl" in doc["error"], "the refusal names the file at stake"
    assert any(g in doc["error"] for g in grounds), doc["error"]
    assert "cannot be reading" in doc["hint"] or "took a render to find out" in doc["hint"], (
        "the caller could not have known, and the hint must not imply they could"
    )


@needs_scad_tier
def test_the_remedy_for_a_refused_out_file_actually_works(tmp_path: Path, capsys):
    """A hint is a claim, and this one is executed rather than read.

    "pass a directory" was true until #223 gave the DIRECTORY spelling of the
    same request its own refusal on the same grounds. The v0.7.6 pre-tag audit
    read that as the remedy routing straight into a second refusal; measured,
    it was worse than that. The old guard required `<stem>.stl` to already
    EXIST, so the obvious directory — the model's own — **worked on the first
    run and was refused from the second**, at a different exit code with a
    different message. A remedy that works once is harder to diagnose than one
    that never works.

    **#263 removed the trap rather than routing around it.** The hint says to
    name a destination the model does not read, and every such destination now
    works repeatedly — the model's own directory included, because the engine's
    dependency list proves `imports_data.stl` is not `input.stl` rather than
    guessing that it might be. This test executes both: the ruled-out
    directory, which is no longer ruled out, and somewhere else.
    """
    (tmp_path / "input.stl").write_bytes(b"donor")
    target = scad_target(tmp_path, source="imports_data.scad", claims="")

    assert main(["measure", target, "--out", str(tmp_path / "input.stl")]) == 64
    hint = json.loads(capsys.readouterr().out)["hint"]
    assert "does not read" in hint, hint

    # The directory the old hint had to rule out. Now fine, and fine again.
    for run in (1, 2):
        assert main(["measure", target, "--out", str(tmp_path)]) == 0, (
            f"run {run}: the model's own directory is a destination it does not read"
        )
        capsys.readouterr()

    # Somewhere else, which is what the hint leaves. Following it must work.
    elsewhere = tmp_path / "artifacts"
    for run in (1, 2, 3):
        assert main(["measure", target, "--out", str(elsewhere)]) == 0, (
            f"the remedy did not work on run {run}: {hint}"
        )
        doc = json.loads(capsys.readouterr().out)
        assert doc["artifact"]["written"] is True
        assert Path(doc["artifact"]["path"]).stat().st_size > 0
    assert (tmp_path / "input.stl").read_bytes() == b"donor", "and the input survived"


@needs_scad_tier
def test_measure_out_refuses_a_file_when_an_include_cannot_be_resolved(tmp_path: Path, capsys):
    """A closure that cannot read one of its members cannot say what that
    member imports either — and nothing later will tell it, because the
    depfile names what the render OPENED and never what it asked for. So this
    is the one arm that still refuses before the render (#263 moved the other),
    and the refusal has to name the include rather than the data."""
    (tmp_path / "a.stl").write_bytes(b"mine")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.scad").write_text("include <nowhere/missing.scad>\ncube([2, 2, 2]);\n")
    target = scad_target(tmp_path, source=tmp_path / "src" / "m.scad", claims="")
    dest = tmp_path / "a.stl"
    assert main(["measure", target, "--out", str(dest)]) == 64
    assert dest.read_bytes() == b"mine"
    doc = json.loads(capsys.readouterr().out)
    assert "could not resolve" in doc["error"]
    assert "nowhere/missing.scad" in doc["error"]


@needs_scad_tier
def test_measure_still_takes_a_directory_for_a_model_that_reads_external_data(
    tmp_path: Path, capsys
):
    """The refusal is about the destination, not the model. A directory has a
    derived name the caller did not type, so the ambiguity does not arise."""
    (tmp_path / "input.stl").write_bytes(b"donor")
    target = scad_target(tmp_path, source="imports_data.scad", claims="")
    out = tmp_path / "out"
    assert main(["measure", target, "--out", str(out)]) == 0
    assert (out / "imports_data.stl").stat().st_size > 0
    assert (tmp_path / "input.stl").read_bytes() == b"donor"
    json.loads(capsys.readouterr().out)


@needs_scad_tier
def test_measure_out_replaces_a_symlink_rather_than_what_it_points_at(tmp_path: Path, capsys):
    """`--out link.stl` is a statement about `link.stl`. Following the link
    would write through to a file the caller did not name."""
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    pointee = tmp_path / "pointee.stl"
    pointee.write_text("theirs")
    link = tmp_path / "link.stl"
    link.symlink_to(pointee)
    assert main(["measure", target, "--out", str(link)]) == 0
    assert not link.is_symlink(), "the link itself is what was named"
    assert link.stat().st_size > 0
    assert pointee.read_text() == "theirs"
    json.loads(capsys.readouterr().out)


@needs_scad_tier
def test_measure_out_reports_a_destination_it_cannot_write(tmp_path: Path, capsys):
    """The filesystem refusing is an environment fault, and it arrives as the
    identity-prefixed artifact rather than as a traceback."""
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    try:
        assert main(["measure", target, "--out", str(locked / "a.stl")]) == exit_code(Verdict.ERROR)
    finally:
        locked.chmod(0o700)
    doc = json.loads(capsys.readouterr().out)
    assert "could not write the build artifact" in doc["error"]
    assert doc["geometry"] == {}


def _occt_target(tmp_path: Path, engine: str, model: str) -> str:
    (tmp_path / "m.py").write_text(model)
    module = tmp_path / "spec.py"
    module.write_text(
        f"from partspec import Part, {engine}\n\n\ndef make():\n"
        f"    return Part('subject', {engine}('m.py'))\n"
    )
    return f"{module}:make"


OCCT_MODELS = [
    ("build123d", "from build123d import Box\n\n\ndef make_part():\n    return Box(2, 1, 1)\n"),
    (
        "cadquery",
        "import cadquery\n\n\ndef make_part():\n    return cadquery.Workplane().box(2, 1, 1)\n",
    ),
]


@pytest.mark.parametrize(("engine", "model"), OCCT_MODELS)
def test_measure_refuses_a_filename_on_the_tier_that_exports_nothing(
    tmp_path: Path, capsys, engine: str, model: str
):
    """The OCCT tier builds in memory, on both its engines. Accepting a
    filename there would exit 0 with nothing at the path the caller named —
    the same silent success, one tier over — so the invocation is refused
    before anything builds, and the refusal is an artifact (#47): SPEC-report
    §Scope requires identity + `error`/`hint` on any failure after the target
    resolves, and a machine passing `--out` is exactly who hits this one.
    """
    pytest.importorskip(engine, reason=f"{engine} extra not installed")
    target = _occt_target(tmp_path, engine, model)
    dest = tmp_path / "a.stl"
    assert main(["measure", target, "--out", str(dest)]) == 64
    assert not dest.exists()
    doc = json.loads(capsys.readouterr().out)
    assert doc["part"]["id"] == "subject", "the refusal says which part it refused"
    assert "names a file" in doc["error"]
    assert engine in doc["error"]
    # EQUALITY, against a literal copy written out here on purpose — do not
    # import `cli.REFUSED_OUT_HINT` and compare it to itself, which would pass
    # for any wording at all.
    #
    # The hint used to offer "pass a directory" as the alternative. It appeared
    # to work while a directory was silently accepted; #204 makes that same
    # request report that nothing was written, so the old advice routes the
    # reader into the state one line of output complains about — a remedy a
    # reader can follow into a complaint is not a remedy.
    #
    # The first attempt at pinning that asserted `"pass a directory" not in
    # hint`, which pins one SPELLING of the advice and not the advice. Measured
    # in adversarial review: restoring "use a directory instead, or drop --out"
    # left the whole suite green at 950 passed. A synonym walks through any
    # substring rule anyone can write here — "a folder", "a dir", "some other
    # path" — so the whole string is the claim.
    assert doc["hint"] == (
        "only the OpenSCAD tier writes a build artifact — drop --out; on this tier "
        "no --out path receives one, whatever its shape, and the measurements go to stdout"
    )


@pytest.mark.parametrize(("engine", "model"), OCCT_MODELS)
def test_measure_out_directory_says_nothing_was_written_on_a_tier_with_no_artifact(
    tmp_path: Path, capsys, engine: str, model: str
):
    """The other spelling of the request the line above refuses (#204).

    A filename destination on this tier exits 64 and names the problem; a
    directory accepted the path, wrote nothing, said nothing and exited 0 —
    two spellings of "put the artifact here" on a tier that has no artifact,
    one named and one silent.

    Exit 0 stays, because the measurement succeeded and IS this verb's
    product; what changes is that the unfulfilled half is stated. In both
    channels: stderr for the reader, and the payload for the machine, because
    a fact living only on stderr is invisible exactly where a machine is the
    audience (#47). One `reason` string feeds both, so they cannot drift.
    """
    pytest.importorskip(engine, reason=f"{engine} extra not installed")
    target = _occt_target(tmp_path, engine, model)
    out = tmp_path / "somedir"
    assert main(["measure", target, "--out", str(out)]) == 0
    assert not out.exists(), "and no empty directory is left to be wondered about"

    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert doc["measurements"]["bbox"]["value"] == [2.0, 1.0, 1.0], "the measurement is the product"
    assert doc["artifact"] == {
        "requested": str(out),
        "written": False,
        "reason": f"the {engine} tier builds in memory and exports nothing to put there",
    }
    assert "names a directory for the build artifact" in captured.err
    assert doc["artifact"]["reason"] in captured.err, "one reason, both channels"
    assert f"nothing was created at {out}" in captured.err


@pytest.mark.parametrize(("engine", "model"), OCCT_MODELS)
def test_measure_says_nothing_about_an_artifact_when_none_was_asked_for(
    tmp_path: Path, capsys, engine: str, model: str
):
    """No `--out` is no request, and a report of a request nobody made is
    noise in a payload whose whole value is that everything in it was
    asked."""
    pytest.importorskip(engine, reason=f"{engine} extra not installed")
    target = _occt_target(tmp_path, engine, model)
    assert main(["measure", target]) == 0
    captured = capsys.readouterr()
    assert "artifact" not in json.loads(captured.out)
    assert captured.err == ""


@needs_scad_tier
def test_measure_out_says_where_the_artifact_landed(tmp_path: Path, capsys):
    """The inverse of what this test asserted until #225, deliberately.

    It required the payload to gain NO key when the artifact WAS written, on
    the reading that `artifact` means "your --out could not be honoured". That
    reading was an artefact of `false` being the only case #204 shipped. The
    key means what happened to your `--out`, and on the one tier that writes
    something the interesting half is where: the caller chose the directory and
    partspec chose the name inside it, so a consumer reading only `requested`
    is still re-deriving `<source stem>.stl` — a rule this tool owns and has
    already moved once (#187).

    `path` is compared against a file this test independently locates and
    stats, so the payload cannot pass by naming somewhere nothing was written.

    stderr stays empty. The notice #204 added is about a request that could not
    be met, and nothing here fell short.
    """
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    out = tmp_path / "art"
    assert main(["measure", target, "--out", str(out)]) == 0
    landed = out / "block_with_hole.stl"
    assert landed.stat().st_size > 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["artifact"] == {
        "requested": str(out),
        "written": True,
        "path": str(landed),
    }
    assert captured.err == ""


@needs_scad_tier
def test_the_filename_form_reports_its_artifact_through_the_same_key(
    tmp_path: Path, capsys, monkeypatch
):
    """One key, both spellings.

    `path` is the NORMALISED destination, not an echo of `requested` — the
    docstring here said "merely echoes" and this test could not see the
    difference, because `tmp_path / "named.stl"` is already absolute and
    normalised (adversarial review of #230). `--out ./x.stl` reports
    `requested: "./x.stl"` and `path: "x.stl"`, which is the more useful of
    the two and the reason to read `path` rather than assume.

    Redundant-looking on purpose all the same: a consumer reads the same field
    whichever spelling it used, instead of branching on a distinction that is
    about the caller's phrasing rather than about where the file is.
    """
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    dest = tmp_path / "named.stl"
    assert main(["measure", target, "--out", str(dest)]) == 0
    assert dest.stat().st_size > 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["artifact"] == {
        "requested": str(dest),
        "written": True,
        "path": str(dest),
    }
    assert captured.err == ""

    # The unnormalised spelling, which the absolute path above cannot show.
    # `path` is where the file is; `requested` is what the caller typed.
    scruffy = f".{os.sep}{dest.name}"
    monkeypatch.chdir(tmp_path)
    assert main(["measure", target, "--out", scruffy]) == 0
    artifact = json.loads(capsys.readouterr().out)["artifact"]
    assert artifact == {"requested": scruffy, "written": True, "path": dest.name}
    assert Path(artifact["path"]).stat().st_size > 0, "and it names a file that is there"


# --------------------------------------------------------------------------
# measure/check --out DIR (#208): the DERIVED artifact path may be an input
# --------------------------------------------------------------------------


def _donor_stl(tmp_path: Path, dest: Path) -> bytes:
    """Build a real 3x7x11 mesh at `dest`, for a model to `import()`.

    A real one, rendered by the engine that will read it back, because these
    tests turn on whether the import was resolved at all: the `b"donor"`
    placeholder the file-mode tests use never reaches OpenSCAD, and a model
    that imports it measures the same either way.
    """
    from partspec.engines import openscad

    source = tmp_path / "donor.scad"
    source.write_text("cube([3, 7, 11]);\n")
    built = openscad.render(openscad.OpenSCADSource(path=source), tmp_path / "donor-out")
    assert isinstance(built, Path), built
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(built, dest)
    return dest.read_bytes()


@needs_openscad
def test_measure_out_refuses_the_model_s_own_directory_over_a_colliding_input(
    tmp_path: Path, capsys
):
    """`--out .` derived `<stem>.stl`, and the model imported that file.

    Filed as a `measure` bug and reproduced at exit 0 with a complete payload:
    `part.scad` imports `part.stl`, the run unlinked `part.stl` before invoking
    the engine, and the model then built without its import — `[5, 5, 5]` for a
    part that measures `[8, 7, 11]`, with the input gone. Building in a scratch
    directory fixes the number; it does not stop `os.replace` from putting the
    output on top of the input afterwards, which is what this refusal is for.

    This is the case #263 made exact rather than removed, and the distinction
    is the whole of the fix: `self_named_import.scad` genuinely reads the file
    the derived name lands on, so the engine's dependency list refuses it —
    where `imports_data.scad`, whose import is a different file in the same
    directory, is now allowed through the same guard.
    """
    donor = _donor_stl(tmp_path, tmp_path / "self_named_import.stl")
    target = scad_target(tmp_path, source="self_named_import.scad", claims="")
    assert main(["measure", target, "--out", str(tmp_path)]) == exit_code(Verdict.ERROR)
    assert (tmp_path / "self_named_import.stl").read_bytes() == donor
    doc = json.loads(capsys.readouterr().out)
    assert "self_named_import.stl" in doc["error"], "the refusal names the file at stake"
    assert "one of its own inputs" in doc["error"]
    assert "does not read" in doc["hint"]


@needs_openscad
def test_check_out_refuses_rather_than_passing_a_part_it_would_have_consumed(tmp_path: Path):
    """The half the issue did not file, and the worse one.

    `check --out .` reached the same unlink, so the same consumed import
    produced `PASS: 2 pass` — a verdict on geometry that was not the part,
    with the input gone. The refusal is `origin="environment"`, so `builds`
    is skipped rather than failed: nothing here disproves the design
    (SPEC-report §6.1).
    """
    donor = _donor_stl(tmp_path, tmp_path / "self_named_import.stl")
    target = scad_target(
        tmp_path,
        source="self_named_import.scad",
        claims="    p.envelope(max=(20.0, 20.0, 20.0))\n",
    )
    assert main(["check", target, "--quiet", "--out", str(tmp_path)]) == exit_code(Verdict.ERROR)
    assert (tmp_path / "self_named_import.stl").read_bytes() == donor
    report = report_of(tmp_path)
    assert report["verdict"] == "error"
    assert report["build_origin"] == "environment"
    assert [c["status"] for c in report["checks"]] == ["skipped", "skipped"]
    assert "self_named_import.stl" in report["error"]


@needs_scad_tier
def test_measure_out_measures_the_import_and_a_repeat_run_is_not_refused(tmp_path: Path, capsys):
    """The condition that must NOT fire, run twice.

    A guard of the form "the artifact path exists and the closure is partial"
    catches the filed repro and regresses every second run of any external-data
    model, because run 2 finds run 1's own artifact waiting for it. So the
    refusal also requires the destination to be the model's OWN directory,
    which an output directory never is — and both runs measure the imported
    solid, `[8, 7, 11]` rather than the bare `[5, 5, 5]` cube.
    """
    _donor_stl(tmp_path, tmp_path / "self_named_import.stl")
    target = scad_target(tmp_path, source="self_named_import.scad", claims="")
    out = tmp_path / "art"
    for run in ("first", "second"):
        assert main(["measure", target, "--out", str(out)]) == 0, run
        doc = json.loads(capsys.readouterr().out)
        assert doc["measurements"]["bbox"]["value"] == [8.0, 7.0, 11.0], run
    assert (out / "self_named_import.stl").stat().st_size > 0


@needs_scad_tier
def test_measure_out_refuses_when_the_import_is_below_the_out_dir(tmp_path: Path, capsys):
    """The residue #223 shipped knowingly, and the run that ends it.

    #223's guard covered the model's own directory and nothing else, because
    no signal distinguished the two files anywhere else: `reads_external_data`
    is a bool by design, since a data path may be computed at render time. So
    `--out sub` for a model importing `sub/<stem>.stl` wrote the artifact over
    that import, and the artifact REPLACED it rather than deleting it — the
    import still resolved and the model ate its own output. Measured then:
    `[8, 7, 11]`, `[13, 7, 11]`, `[18, 7, 11]`, every one at exit 0, and a
    `check` claim that is false of the real part passing from run 2 onward.
    That was #208's own headline symptom surviving in a narrower case.

    An earlier revision of this test pinned that residue and said so: "if a
    later change closes it, this test fails and says so, which is the whole
    point of writing the residue down where it can be executed." It did, and
    the change is #263 — the engine's dependency list names a subdirectory
    import by full resolved path, so where the destination sits stops
    mattering. The refusal is now the same one wherever the collision is.

    The widening #223 warned must not happen quietly did not happen at all:
    `test_measure_still_takes_a_directory_for_a_model_that_reads_external_data`
    and the runs in `test_the_remedy_for_a_refused_out_file_actually_works`
    are the legitimate output directories, and they are not refused. Nothing
    here is conservative — the guard refuses the file the render read, and
    only that one.
    """
    donor = _donor_stl(tmp_path, tmp_path / "sub" / "subdir_import.stl")
    target = scad_target(tmp_path, source="subdir_import.scad", claims="")
    out = tmp_path / "sub"

    for run in (1, 2):
        assert main(["measure", target, "--out", str(out)]) == exit_code(Verdict.ERROR), (
            f"run {run}: the destination is an input wherever it sits"
        )
        doc = json.loads(capsys.readouterr().out)
        assert "subdir_import.stl" in doc["error"]
        assert "one of its own inputs" in doc["error"]

    assert (out / "subdir_import.stl").read_bytes() == donor, (
        "and the import is byte-identical, so run 2 could only have measured the part"
    )


# --------------------------------------------------------------------------
# measure — identity (#47): as identifiable as a report
# --------------------------------------------------------------------------


@needs_scad_tier
def test_measure_carries_the_same_identity_as_the_report(tmp_path: Path, capsys):
    """One builder serves both verbs, and this pin is what keeps them from
    drifting apart again (#73 was exactly that drift, in the engine block).
    A consumer turning measure output into checks must be able to say which
    file, which revision, and which parameters produced the numbers."""
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="    p.watertight()\n")
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 0
    report = report_of(out)

    doc = _measure(target, capsys)
    assert doc["schema_version"] == report["schema_version"]
    assert doc["part"] == report["part"]
    assert doc["params"] == report["params"]
    # Presence, not just sameness: the equality pin alone cannot see a field
    # both sides lost together (PR #102 review, mutant survivor).
    assert doc["part"]["contract_digest"].startswith("sha256:")
    assert doc["part"]["source_digest"].startswith("sha256:")
    assert doc["payload"] == "measure" and report["payload"] == "report", (
        "the shared prefix is what makes the two indistinguishable without it (#295)"
    )
    assert list(doc)[:8] == [
        "schema_version",
        "payload",
        "tool",
        "part",
        "engine",
        "params",
        "geometry",
        "measurements",
    ]


@needs_scad_tier
def test_measure_records_the_parameters_that_produced_the_numbers(tmp_path: Path, capsys):
    shutil.copy(FIXTURES / "block_with_hole.scad", tmp_path / "block_with_hole.scad")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('block_with_hole.scad', hole=4))\n"
    )
    doc = _measure(f"{module}:make", capsys)
    assert doc["params"] == {"hole": 4}


@needs_build123d
@needs_openscad
def test_the_measure_failure_payload_carries_exactly_these_keys(tmp_path: Path, capsys):
    """`AGENT-CONTRACT.md` §2.4 enumerates this key set as *Measured*, and an
    agent reads that enumeration to learn there is no `origin` to branch on.

    The list is hand-maintained and nothing gated it, so it went stale the
    moment #295 added `payload` to the same payload — two PRs each correct
    alone, a false composition, and a green CI because no test read the list.
    That is #299's class, one document over. This is the gate: an enumeration
    labelled "Measured" now has something that measures it.

    Asserted as the exact SET, in BOTH failure modes, because the doc says
    "exactly" and says "both". Not by parsing the document — that is the
    doc-vs-code diff `AGENTS.md` forbids, and it would only prove two copies
    of a list agree. This states the payload's shape directly; the doc cites
    this test by name, so a reader who distrusts the prose has somewhere to
    look.
    """
    expected = {
        "engine",
        "error",
        "geometry",
        "hint",
        "params",
        "part",
        "payload",
        "schema_version",
        "tool",
    }

    # Mode 1: the build failed (exit 4). A `.scad` that is not there.
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('missing.scad'))\n"
    )
    assert main(["measure", f"{module}:make"]) == exit_code(Verdict.ERROR)
    built = json.loads(capsys.readouterr().out)

    # Mode 2: the ask was refused (exit 64). A filename `--out` on a tier that
    # exports no artifact — a different code path to the same shape.
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 5)\n"
    )
    assert main(["measure", py_target(tmp_path), "--out", str(tmp_path / "x.stl")]) == 64
    refused = json.loads(capsys.readouterr().out)

    assert set(built) == expected, "the exit-4 failure payload"
    assert set(refused) == expected, "the exit-64 refusal payload"

    # The SET is what §2.4 claims, and the ORDER is what §8 rule 1 makes a MUST
    # — "object keys MUST be emitted in the order given in §7" — with Scope
    # fixing the identity prefix these payloads share. Nothing executed that
    # second rule on this payload: moving `payload` to sit after `params`
    # passes the whole suite. Both assertions stay, because neither implies the
    # other.
    prefix = ["schema_version", "payload", "tool", "part", "engine", "params"]
    assert list(built)[:6] == prefix, "the identity prefix, in Scope's order"
    assert list(refused)[:6] == prefix, "and the same order on the refusal path"
    assert "origin" not in built and "origin" not in refused, (
        "absent, not null — §2.4 tells an agent it cannot even read it as 'unknown'"
    )
    assert "measurements" not in built and "measurements" not in refused, (
        "a run that measured nothing states no measurements (SPEC-report §7.3)"
    )


@needs_openscad
def test_measure_failure_is_an_artifact_not_a_shrug(tmp_path: Path, capsys):
    """A caller parsing stdout used to get an empty string and a bare exit
    code, with the reason on stderr only — machine-invisible exactly where a
    machine is the audience (#47)."""
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('missing.scad', bore_diamter=8))\n"
    )
    assert main(["measure", f"{module}:make"]) == exit_code(Verdict.ERROR)
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert doc["schema_version"] == 1
    assert doc["part"]["id"] == "subject"
    assert doc["part"]["contract"] == "spec.py:make", "the invoked symbol, not just the file"
    assert doc["engine"]["kind"] == "openscad"
    # The payload records what was ASKED; `error` says what happened. A
    # typo'd parameter stays visible rather than vanishing with the build.
    assert doc["params"] == {"bore_diamter": 8}
    assert doc["geometry"] == {}
    assert "not found" in doc["error"]
    assert "hint" in doc
    assert "not found" in captured.err, "the console courtesy line survives"


def test_measure_python_closure_appears_after_the_build(tmp_path: Path, capsys):
    """A Python model's inputs are only knowable once it has run; measure's
    identity must carry the same imports-derived closure the report does."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "helper47.py").write_text("SIZE = 2\n")
    (tmp_path / "model.py").write_text(
        "import helper47\nfrom build123d import Box\n\n\ndef make_part():\n"
        "    return Box(helper47.SIZE, 1, 1)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('model.py'))\n"
    )
    doc = _measure(f"{module}:make", capsys)
    closure = doc["part"]["source_closure"]
    assert closure["scope"] == "model_directory"
    assert closure["partial"] is True
    assert closure["files"] >= 2, "the helper the model imported is a build input"


# --------------------------------------------------------------------------
# check — the exit code is half the contract
# --------------------------------------------------------------------------


@needs_scad_tier
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("    p.watertight()\n", Verdict.PASS),
        ("    p.envelope(max=(1, 1, 1))\n", Verdict.FAIL),
        ("    p.topology(faces=6)\n", Verdict.INCOMPLETE),
        ("", Verdict.EMPTY),
    ],
)
def test_check_exits_with_the_verdicts_code(tmp_path: Path, body: str, expected: Verdict):
    """Every verdict, through `main`, on a real render.

    The exit code is the only thing a CI job reads, so a report that is right
    while the process exits 0 anyway would defeat all of it.
    """
    target = scad_target(tmp_path, source="block_with_hole.scad", claims=body)
    assert main(["check", target, "--quiet"]) == exit_code(expected)


@needs_scad_tier
def test_an_empty_contract_says_so_on_the_console(tmp_path: Path, capsys):
    """The human-facing half of the vacuous-green thesis, and it had no test:
    every EMPTY-verdict case ran with `--quiet`, so `if report.verdict is
    Verdict.EMPTY` could be neutered and all 725 tests still passed.

    Note the asymmetry the deslop audit found — the *attribution* warning has
    three dedicated tests asserting on capsys, while the more important one
    had none. A contract that asserts nothing is the failure this whole tool
    is built around; the operator has to be told in words, not just by an
    exit code they may not be reading.
    """
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="")
    assert main(["check", target, "--out", str(tmp_path / "out")]) == exit_code(Verdict.EMPTY)
    err = capsys.readouterr().err
    assert "declares no checks" in err
    assert "not a passing design" in err


@needs_scad_tier
def test_check_writes_the_report_where_it_says_it_did(tmp_path: Path, capsys):
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="    p.watertight()\n")
    assert main(["check", target]) == 0
    printed = capsys.readouterr().err.strip().splitlines()[-1].strip()
    doc = json.loads(Path(printed).read_text())
    assert doc["verdict"] == "pass"


def test_an_unresolvable_target_is_a_usage_error_not_a_crash(tmp_path: Path):
    assert main(["check", str(tmp_path / "nope.py")]) == 64
    assert main(["measure", str(tmp_path / "nope.py")]) == 64


def test_the_refusal_locates_the_type_it_got(tmp_path: Path, capsys):
    """A factory returning some OTHER library's `Part` is told which one.

    build123d and CadQuery each export a `Part`, and `_load` compiles and
    execs, which leaves every annotation a string — so a MODEL annotated
    `-> Part` is discovered as a factory, called, and refused only on what it
    returned. Unqualified, that refusal read `returned Part, not a Part`: the
    same word twice, naming no way forward (#282).

    Asserted as a PROPERTY, not as wording: the message must contain the
    returned class's own `__module__`, read off the class rather than typed
    in. Rephrase the sentence and this still passes; drop the qualifier and it
    does not. `SPEC-contract.md` §7 states the obligation; this is what holds
    the code to it.
    """
    import importlib

    # (a) a foreign LIBRARY class — the build123d/CadQuery collision, stood in
    #     for locally so this needs no engine extra. The module is named so it
    #     cannot appear incidentally in the message: a first draft called it
    #     `lib` inside a contract called `uses_lib.py`, and the substring was
    #     satisfied by the PATH, so the unqualified message passed (PR #340
    #     review, F2). The assertion is the full dotted form.
    (tmp_path / "vendorpkg.py").write_text("class Part:\n    pass\n")
    consumer = tmp_path / "consumer.py"
    consumer.write_text("from vendorpkg import Part\n\n\ndef thing() -> Part:\n    return Part()\n")

    sys.path.insert(0, str(tmp_path))
    try:
        assert main(["measure", f"{consumer}:thing"]) == 64
        # Imported dynamically: this test writes the module, so a static
        # import statement is unresolvable to the type checker.
        klass = importlib.import_module("vendorpkg").Part
        qualified = f"{klass.__module__}.{klass.__qualname__}"
        message = capsys.readouterr().err
        assert qualified in message, (
            f"the refusal must locate the returned type; expected {qualified!r} in {message!r}"
        )
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("vendorpkg", None)

    # (b) a class defined in the CONTRACT itself — #282's own `ann2.py`
    #     reproduction. There `__module__` is `_load`'s synthesised name,
    #     which embeds a per-process hash, so the locus must be the file.
    own = tmp_path / "ann2.py"
    own.write_text("class Part:\n    pass\n\n\ndef thing() -> Part:\n    return Part()\n")
    assert main(["measure", f"{own}:thing"]) == 64
    message = capsys.readouterr().err
    assert "ann2.py" in message, "the locus for a contract-defined class is the file"
    assert "_partspec_contract_" not in message, (
        "the synthesised module name is per-process; printing it promises a locus "
        "and delivers a different string every run"
    )


@pytest.mark.parametrize("verb", ["check", "measure"])
def test_a_contract_that_raises_does_not_exit_as_a_failing_part(tmp_path: Path, verb: str):
    """Found by mistyping a keyword argument while writing a real contract.

    The traceback escaped `main` and the interpreter exited 1, which is this
    tool's code for *the part failed its contract*. A malformed question would
    have been recorded in CI as a wrong answer about the design, and the two
    are indistinguishable from the outside. Exit 4: nothing was evaluated, so
    nothing may be said about the part.
    """
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\n"
        "def make() -> Part:\n"
        "    return Part('x', openscad('x.scad')).envelope(max=(1, 1, 1), tol=0.05)\n"
    )
    assert main([verb, f"{module}:make"]) == exit_code(Verdict.ERROR)


def test_no_arguments_prints_help(capsys):
    assert main([]) == 64
    assert "usage:" in capsys.readouterr().out


@needs_scad_tier
def test_a_contract_that_raises_does_not_leave_the_previous_verdict(tmp_path: Path):
    """The regression this ordering exists to prevent.

    `write_placeholder` used to run *after* the contract resolved, so a contract
    that raised returned exit 4 without touching the output directory — leaving
    the previous run's `verdict: "pass"` at the deterministic path. The exit code
    said error and the artifact said the part was fine, and the artifact is what
    a later reader trusts.
    """
    scad = tmp_path / "box.scad"
    scad.write_text("x = 10;\ncube([x, x, x]);\n")
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n"
        "def part() -> Part:\n"
        "    p = Part('stale', openscad('box.scad', x=10.0))\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{spec}:part", "--out", str(out), "--quiet"]) == 0
    report = out / "report.json"
    assert json.loads(report.read_text())["verdict"] == "pass", "premise: a green run on disk"

    spec.write_text(
        "from partspec import Part\ndef part() -> Part:\n    raise RuntimeError('boom')\n"
    )
    assert main(["check", f"{spec}:part", "--out", str(out), "--quiet"]) == 4
    assert json.loads(report.read_text())["verdict"] == "error", (
        "the previous run's pass survived a contract that raised"
    )


@needs_scad_tier
def test_a_usage_refusal_after_the_placeholder_leaves_an_undiagnosed_report(tmp_path, capsys):
    """Exit 64 does NOT mean nothing was written, which `EXIT_USAGE` said until #358.

    The placeholder goes down for every target before any target runs, and
    `--expect` is read after it, so a refused lock exits 64 over a report that
    is already on disk. That is the correct behaviour — it is exactly what the
    placeholder exists to do — and the docstring on the constant encoding the
    exit-code contract denied it, in a project whose thesis is that the tool
    must not claim more than it has established.

    The second half is the part a consumer has to plan for: the placeholder
    carries the generic "run did not complete" sentence and NOT the reason for
    the refusal, which reaches stderr only. An agent that reads the artifact
    and not the exit code gets an `error` document it cannot act on
    (`AGENT-CONTRACT.md` §4).
    """
    scad = tmp_path / "box.scad"
    scad.write_text("x = 10;\ncube([x, x, x]);\n")
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n"
        "def part() -> Part:\n"
        "    p = Part('refused', openscad('box.scad', x=10.0))\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{spec}:part", "--out", str(out), "--quiet"]) == 0
    assert report_of(out)["verdict"] == "pass", "premise: a green run on disk"
    capsys.readouterr()

    missing = tmp_path / "nosuch.lock"
    code = main(["check", f"{spec}:part", "--out", str(out), "--expect", str(missing), "--quiet"])
    assert code == EXIT_USAGE

    written = (out / "report.json").read_text()
    doc = json.loads(written)
    assert doc["verdict"] == "error", "the refused run left the previous pass on disk"
    assert doc["counts"]["total"] == 0
    assert doc["checks"] == []
    # The lock PATH is in the artifact, echoed inside `invocation.argv`; the
    # sentence saying what went wrong with it is not, and that is the half a
    # reader needs.
    assert "no claims pin" not in written, (
        "the refusal's diagnosis reached the artifact; the docstring says stderr only"
    )
    assert "no claims pin at" in capsys.readouterr().err


def test_a_contract_calling_sys_exit_is_not_a_green_run(tmp_path: Path):
    """`sys.exit(0)` raises SystemExit, which sailed past `except Exception` and
    exited the process 0 — green, silent, zero checks evaluated. The exit code
    was the contract's to choose: `sys.exit(2)` read as incomplete."""
    spec = tmp_path / "spec.py"
    spec.write_text("import sys\nfrom partspec import Part\ndef part() -> Part:\n    sys.exit(0)\n")
    out = tmp_path / "out"
    assert main(["check", f"{spec}:part", "--out", str(out), "--quiet"]) == 4
    assert report_of(out)["verdict"] == "error"


def test_argparse_still_owns_its_own_exits():
    """The BaseException guard is scoped to contract resolution, so argparse's
    SystemExit for `--version` and usage errors is untouched."""
    with pytest.raises(SystemExit):
        main(["--version"])


# --------------------------------------------------------------------------
# what a contract failure prints (#188)
# --------------------------------------------------------------------------

SOURCE_ROOT = str(Path(cli.__file__).parent)
"""partspec's own source directory: what must not appear in a filtered
traceback, asserted by path rather than by module name so a message that
merely mentions `cli.py` cannot pass for a frame."""


def _markers(err: str) -> list[tuple[int, int]]:
    """Every `[N frames hidden]` marker as `(position, count)`, in order.

    Counts and positions rather than literal strings, because the claim is
    "every gap is announced where it is" — not how deep partspec's own call
    path happens to be this week.
    """
    return [(m.start(), int(m.group(1))) for m in re.finditer(r"\[(\d+) frames? hidden\]", err)]


def _markers_around(err: str, position: int) -> tuple[list[int], list[int]]:
    found = _markers(err)
    return ([n for at, n in found if at < position], [n for at, n in found if at > position])


def _raising_contract(tmp_path: Path, body: str) -> str:
    spec = tmp_path / "spec.py"
    spec.write_text(f"from partspec import Part, openscad\n\n\ndef make() -> Part:\n{body}")
    return f"{spec}:make"


def test_a_contract_error_prints_the_contract_frame_and_not_partspec_s(tmp_path: Path, capsys):
    """#188: a `ContractError` is partspec's own, deliberately raised, with a
    message written for the reader — so the six internal frames it travelled
    through are never the answer. The one useful frame is the contract's own
    line, and it stays."""
    target = _raising_contract(tmp_path, "    return Part('', openscad('x.scad'))\n")
    assert main(["check", target, "--out", str(tmp_path / "out")]) == exit_code(Verdict.ERROR)
    err = capsys.readouterr().err
    assert "spec.py" in err and "line 5" in err, "the reader's own line still says where"
    assert "ContractError: a part needs an id" in err
    assert SOURCE_ROOT not in err, "partspec's internals are not the answer"
    assert "<string>" not in err, "nor is a dataclass's generated __init__"
    assert "the contract is wrong, not the part" in err, "the classification is unchanged"


def test_a_type_error_in_a_contract_keeps_the_line_that_raised_it(tmp_path: Path, capsys):
    """The reason the traceback is printed at all: a contract is arbitrary
    Python, and for a mistyped keyword argument the frame is the only thing
    that says *where*. Filtering partspec's frames must not cost that."""
    target = _raising_contract(
        tmp_path, "    return Part('x', openscad('x.scad')).envelope(maks=(1, 1, 1), tol=0.05)\n"
    )
    assert main(["check", target, "--out", str(tmp_path / "out")]) == exit_code(Verdict.ERROR)
    err = capsys.readouterr().err
    assert "spec.py" in err and "line 5" in err
    assert "envelope(maks=" in err, "the source line that raised is quoted"
    assert SOURCE_ROOT not in err


def test_a_library_the_contract_called_keeps_its_frames(tmp_path: Path, capsys):
    """A third-party library (CadQuery, say) that raises four calls deep is
    genuinely where the failure happened, and those frames are not partspec
    explaining itself. Only partspec's own are dropped."""
    (tmp_path / "lib188.py").write_text("def bore(d):\n    raise ValueError(f'no bore at {d}')\n")
    spec = tmp_path / "spec.py"
    spec.write_text(
        "import lib188\n\nfrom partspec import Part, openscad\n\n\ndef make() -> Part:\n"
        "    lib188.bore(7.5)\n    return Part('x', openscad('x.scad'))\n"
    )
    assert main(["check", f"{spec}:make", "--out", str(tmp_path / "out")]) == exit_code(
        Verdict.ERROR
    )
    err = capsys.readouterr().err
    assert "lib188.py" in err and "raise ValueError" in err, "the library's frame is kept"
    assert "spec.py" in err, "and so is the contract line that called it"
    assert SOURCE_ROOT not in err


def test_the_dropped_frames_are_announced_where_they_were(tmp_path: Path, capsys):
    """A reprint with frames silently removed reads as a direct call chain that
    never happened, and the reader most likely to be misled by that is an agent.
    Every gap says how many frames are in it."""
    target = _raising_contract(tmp_path, "    return Part('', openscad('x.scad'))\n")
    assert main(["check", target, "--out", str(tmp_path / "out")]) == exit_code(Verdict.ERROR)
    err = capsys.readouterr().err
    before, after = _markers_around(err, err.index("spec.py"))
    assert len(before) == 1 and before[0] >= 1, "the frames that only reached the contract"
    assert len(after) == 1 and after[0] >= 1, "and the ones between it and the raise"


def test_generated_contract_frames_are_hidden_but_not_silently(tmp_path: Path, capsys):
    """A `<string>` frame — exec'd contract code, or a dataclass's generated
    `__init__` — has no source to show and is filtered with partspec's own. It
    is still a frame that ran, so the marker counts it rather than the reprint
    quietly closing the gap."""
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\ndef make() -> Part:\n"
        "    ns = {}\n"
        "    exec(compile(\"def inner():\\n    return Part('', openscad('x.scad'))\\n\","
        ' "<contract-generated>", "exec"), {"Part": Part, "openscad": openscad}, ns)\n'
        "    return ns['inner']()\n"
    )
    assert main(["check", f"{spec}:make", "--out", str(tmp_path / "out")]) == exit_code(
        Verdict.ERROR
    )
    err = capsys.readouterr().err
    assert "ContractError: a part needs an id" in err
    assert "<contract-generated>" not in err, "a generated frame has no source to show"
    _, after = _markers_around(err, err.index("spec.py"))
    assert after == [2], "the generated frame is counted with the raise site, not dropped silently"


def test_a_failure_with_no_contract_frames_still_prints_the_whole_traceback(tmp_path: Path, capsys):
    """The fallback that keeps silence from reading as success. A contract
    naming a partspec callable as its factory never contributes a frame of its
    own, so filtering would leave an empty traceback; partspec's frames are then
    all there is to say, and they are printed."""
    spec = tmp_path / "spec.py"
    spec.write_text("from partspec import Part as make\n")
    assert main(["check", f"{spec}:make", "--out", str(tmp_path / "out")]) == exit_code(
        Verdict.ERROR
    )
    err = capsys.readouterr().err
    assert SOURCE_ROOT in err, "with no contract frame, partspec's own are the diagnosis"
    assert "TypeError" in err
    assert "hidden]" not in err, "nothing was filtered, so nothing claims to have been"


def test_a_partspec_frame_inside_the_failure_is_never_dropped(tmp_path: Path, capsys):
    """The invariant that matters more than the noise: a partspec frame *below*
    the contract's own means partspec code took part in the failure rather than
    merely reaching the contract. `openscad(3)` fails in `pathlib` through
    `contract.py`, which is the shape of #191 — and if that middle frame can be
    dropped, a genuine partspec bug reaches the reader as "the contract is
    wrong, not the part" with nothing to contradict it."""
    target = _raising_contract(tmp_path, "    return Part('x', openscad(3))\n")
    assert main(["check", target, "--out", str(tmp_path / "out")]) == exit_code(Verdict.ERROR)
    err = capsys.readouterr().err
    assert "contract.py" in err, "the partspec frame that made the failing call"
    assert "pathlib" in err and "spec.py" in err, "and both ends of the stack around it"


def test_an_exception_group_keeps_every_sub_exception(tmp_path: Path, capsys):
    """A contract reporting several problems at once raises an `ExceptionGroup`,
    and a group rendered header-only says "2 sub-exceptions" and nothing about
    what or where. Each sub-exception's own contract lines are exactly what #188
    exists to preserve."""
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\n"
        "def _a():\n    raise ValueError('bore too small')\n\n\n"
        "def _b():\n    raise TypeError('wall not a number')\n\n\n"
        "def make() -> Part:\n"
        "    errs = []\n"
        "    for fn in (_a, _b):\n"
        "        try:\n            fn()\n"
        "        except Exception as exc:\n            errs.append(exc)\n"
        "    raise ExceptionGroup('two contract problems', errs)\n"
    )
    assert main(["check", f"{spec}:make", "--out", str(tmp_path / "out")]) == exit_code(
        Verdict.ERROR
    )
    err = capsys.readouterr().err
    assert "ValueError: bore too small" in err and "TypeError: wall not a number" in err
    assert "line 5" in err and "line 9" in err, "each sub-exception's own contract line"


def test_a_chained_failure_keeps_its_chain(tmp_path: Path, capsys):
    """`try/except` around a partspec call, re-raised as a `ContractError`, is
    an idiomatic contract — and the implicit `__context__` it carries is why
    this case prints unfiltered. A filtered reprint would show the last
    exception of a chain and drop what actually went wrong."""
    target = _raising_contract(
        tmp_path,
        "    try:\n        float('not a number')\n"
        "    except ValueError as exc:\n"
        "        from partspec.status import ContractError\n\n"
        "        raise ContractError('wall_mm must be a number') from exc\n",
    )
    assert main(["check", target, "--out", str(tmp_path / "out")]) == exit_code(Verdict.ERROR)
    err = capsys.readouterr().err
    assert "could not convert string to float" in err, "the cause survives"
    assert "direct cause" in err
    assert "ContractError: wall_mm must be a number" in err


def test_a_chain_the_contract_suppressed_stays_suppressed(tmp_path: Path, capsys):
    """`raise ... from None` is an author saying the cause is not the reader's
    business, and `__suppress_context__` is how they said it. That is not a
    chain, so it filters like any other single exception."""
    target = _raising_contract(
        tmp_path,
        "    try:\n        float('not a number')\n"
        "    except ValueError:\n"
        "        from partspec.status import ContractError\n\n"
        "        raise ContractError('wall_mm must be a number') from None\n",
    )
    assert main(["check", target, "--out", str(tmp_path / "out")]) == exit_code(Verdict.ERROR)
    err = capsys.readouterr().err
    assert "could not convert string to float" not in err, "the author suppressed the cause"
    assert "During handling" not in err and "direct cause" not in err
    assert "raise ContractError" in err, "the contract's own line still says where"
    assert SOURCE_ROOT not in err, "and it is filtered like any other single exception"


def test_a_recursive_contract_keeps_the_repeated_frame_collapse(tmp_path: Path, capsys):
    """`[Previous line repeated N more times]` is something `format_list` can
    only see across a LIST of frames, so formatting the survivors one at a time
    deleted it: 1995 stderr lines where the unfiltered traceback printed 20. A
    125x amplification out of a change whose purpose is removing six lines —
    and `mcp.py`'s stderr tail would carry nothing but identical frames."""
    target = _raising_contract(
        tmp_path, "    def down(n):\n        return down(n + 1)\n\n    down(0)\n"
    )
    assert main(["check", target, "--out", str(tmp_path / "out")]) == exit_code(Verdict.ERROR)
    err = capsys.readouterr().err
    assert "[Previous line repeated" in err, "the collapse survives filtering"
    assert "RecursionError" in err
    assert err.count("\n") < 60, "a thousand identical frames are not a diagnosis"


def test_a_gap_between_two_kept_frames_is_announced_too(tmp_path: Path, capsys):
    """The interleaved shape, which one gap before and one gap after cannot
    pin: partspec's `openscad()` calls `pathlib`, which calls back into the
    contract's own `__fspath__`. The contract's two frames are kept with a
    marker BETWEEN them, and the stdlib frame in the middle is kept as any
    third party's would be."""
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\nfrom partspec.status import ContractError\n\n\n"
        "class Bad:\n    def __fspath__(self) -> str:\n"
        "        raise ContractError('the source path is not decided yet')\n\n\n"
        "def make() -> Part:\n    return Part('x', openscad(Bad()))\n"
    )
    assert main(["check", f"{spec}:make", "--out", str(tmp_path / "out")]) == exit_code(
        Verdict.ERROR
    )
    err = capsys.readouterr().err
    assert "pathlib" in err, "the stdlib frame between them is not partspec's to hide"
    assert "in make" in err and "in __fspath__" in err, "both contract frames survive"
    markers = _markers(err)
    assert len(markers) == 2, "one marker per gap, and the second is not at either end"
    assert markers[0][0] < err.index("in make") < markers[1][0] < err.index("pathlib")
    assert SOURCE_ROOT not in err


def test_a_contract_calling_sys_exit_still_says_where(tmp_path: Path, capsys):
    """`SystemExit` is caught here rather than allowed to choose the process's
    exit code (see above), so it goes through the same printing. It is not
    partspec's exception and nothing of partspec's is in the failure, so the
    contract's own line is what shows."""
    target = _raising_contract(tmp_path, "    import sys\n\n    sys.exit(0)\n")
    assert main(["check", target, "--out", str(tmp_path / "out")]) == exit_code(Verdict.ERROR)
    err = capsys.readouterr().err
    assert "sys.exit(0)" in err and "SystemExit" in err
    assert SOURCE_ROOT not in err


@needs_scad_tier
def test_a_contract_that_raises_under_measure_out_prints_only_the_traceback(tmp_path: Path, capsys):
    """Where #188's filtering and #187's `--out` meet, which is nowhere.

    Both landed in `measure`'s path in the same week, one printing tracebacks
    and one printing a JSON failure artifact, and neither had been run against
    the other. They cannot collide: the traceback belongs to a target that
    never resolved, and SPEC-report's Scope gives that case stderr and an exit
    code only — there is no identity to emit and no `--out` yet to honour. So
    the assertion is that each stays on its own side, and that a `--out` file
    named by a run that never built is not created.
    """
    target = _raising_contract(
        tmp_path,
        "    from partspec.status import ContractError\n\n"
        "    raise ContractError('the bore diameter is not declared')\n",
    )
    dest = tmp_path / "a.stl"
    assert main(["measure", target, "--out", str(dest)]) == exit_code(Verdict.ERROR)
    captured = capsys.readouterr()
    assert _markers(captured.err), "the filtered traceback is intact"
    assert "ContractError: the bore diameter is not declared" in captured.err
    assert SOURCE_ROOT not in captured.err
    assert captured.out == "", "an unresolved target has no identity to print"
    assert not dest.exists(), "and nothing was written where it never got to build"


def test_render_on_the_occt_tier_from_the_same_verb(tmp_path: Path, capsys):
    """#18: same verb, same view names, and the payload carries what this
    tier uniquely knows — the backend that ran, the build-derived closure,
    and the tessellation that is what was actually shown (D15)."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "helper18.py").write_text("SIZE = 20\n")
    (tmp_path / "model.py").write_text(
        "import helper18\nfrom build123d import Box\n\n\ndef make_part():\n"
        "    return Box(helper18.SIZE, 10, 5)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('model.py'))\n"
    )
    assert main(["render", f"{module}:make", "--out", str(tmp_path / "out")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["renders"]) == {"iso", "front", "top", "right"}
    for path in payload["renders"].values():
        assert Path(path).stat().st_size > 0
    assert payload["engine"]["kind"] == "build123d"
    assert payload["engine"]["backend"] == "occt", "the tier that ran is named"
    assert payload["render_tessellation"]["tolerance_mm"] == 0.1
    assert payload["render_tessellation"]["triangles"] > 0
    # built=True identity: the helper the model imported is a build input,
    # knowable only because this verb actually built the part.
    assert payload["part"]["source_closure"]["files"] >= 2


def test_a_failed_build_never_reaches_the_rasterizer(tmp_path: Path, capsys, monkeypatch):
    """PR #127 review, F1: the raster import (which pulls numpy) sat before
    the build, so with the occt extra missing the verb died as a raw numpy
    traceback — empty stdout — instead of the build's honest environment
    artifact. The import order is the fix; this hook is the pin: a failing
    build must produce the #103 artifact without partspec.raster ever
    loading."""
    pytest.importorskip("build123d", reason="occt extra not installed")

    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name == "partspec.raster":
                raise ImportError("partspec.raster must not load before the build succeeds")
            return None

    import partspec

    # Both evictions, or the pin is vacuous (the reviewer demonstrated it):
    # another test file's import binds `raster` as an attribute on the
    # package object, and `from . import raster` is satisfied by hasattr
    # without the import machinery — the hook would never fire in-suite.
    monkeypatch.delitem(sys.modules, "partspec.raster", raising=False)
    monkeypatch.delattr(partspec, "raster", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Block(), *sys.meta_path])
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('missing.py'))\n"
    )
    assert main(["render", f"{module}:make"]) == exit_code(Verdict.ERROR)
    doc = json.loads(capsys.readouterr().out)
    assert doc["part"]["id"] == "subject"
    assert doc["renders"] == {}
    assert doc["error"]


def test_render_on_a_broken_python_model_is_an_artifact(tmp_path: Path, capsys):
    """This target used to be refused as usage (64) when the tier had no
    render; now the tier renders, a model with no factory is a build failure
    — an identifiable artifact at exit 4, like every resolved-target failure."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text("")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    assert main(["render", f"{module}:make"]) == exit_code(Verdict.ERROR)
    doc = json.loads(capsys.readouterr().out)
    assert doc["part"]["id"] == "subject"
    assert doc["engine"]["backend"] == "occt"
    assert doc["renders"] == {}
    assert doc["error"]


@needs_openscad
def test_render_writes_the_views_or_reports_the_display(tmp_path: Path, capsys):
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="    p.watertight()\n")
    code = main(["render", target])
    captured = capsys.readouterr()
    if code == 0:
        payload = json.loads(captured.out)
        assert set(payload["renders"]) == {"iso", "front", "top", "right"}
        for path in payload["renders"].values():
            assert Path(path).stat().st_size > 0
    else:
        assert code == 4
        assert "display" in captured.err


@needs_scad_tier
def test_check_render_records_the_views_in_the_report_or_fails_the_run(tmp_path: Path):
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="    p.watertight()\n")
    out = tmp_path / "out"
    code = main(["check", target, "--quiet", "--render", "--out", str(out)])
    report = report_of(out)
    if code == 0:
        # Relative POSIX paths keyed by view, resolving against the report's
        # own directory (SPEC-report.md section 8.4).
        assert set(report["renders"]) == {"iso", "front", "top", "right"}
        for rel in report["renders"].values():
            assert not Path(rel).is_absolute()
            assert (out / rel).stat().st_size > 0
    else:
        # No display: the run fails loudly and the key is absent — the report
        # speaks for the part, the exit code for the run.
        assert code == 4
        assert "renders" not in report
        assert report["verdict"] == "pass"


@needs_scad_tier
def test_a_report_without_render_carries_no_renders_key(tmp_path: Path):
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="    p.watertight()\n")
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 0
    assert "renders" not in report_of(out)


def test_check_render_on_the_occt_tier_records_the_views(tmp_path: Path):
    """The same-verb half of #18: `check --render` on a Python part records
    the views and the tessellation in the report, exactly as the OpenSCAD
    tier does — no display in the loop, so this branch has no refusal arm."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 5)\n"
    )
    target = py_target(tmp_path, claims="    p.volume(min=0.0)\n")
    out = tmp_path / "out"
    assert main(["check", target, "--render", "--quiet", "--out", str(out)]) == 0
    report = report_of(out)
    assert set(report["renders"]) == {"iso", "front", "top", "right"}
    for rel in report["renders"].values():
        assert not Path(rel).is_absolute()
        assert (out / rel).stat().st_size > 0
    assert report["render_tessellation"]["triangles"] > 0


def test_a_section_shows_the_bore_the_outside_views_cannot(tmp_path: Path, capsys):
    """#19: F16's bore is invisible from outside; the section makes it a
    void in the cut face. The payload records the resolved plane and offset
    — never implicit — and the cut-facet count."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box, Cylinder, Location\n\n\ndef make_part():\n"
        "    return Box(20, 10, 6) - Location((5, 0, 0)) * Cylinder(2, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "out"), "--section", "xy"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["renders"]) == {"iso", "front", "top", "right", "section_xy"}
    assert Path(payload["renders"]["section_xy"]).stat().st_size > 0
    assert payload["section"]["plane"] == "xy"
    assert payload["section"]["offset_mm"] == 0.0, "default: the bbox centre, resolved"
    assert payload["section"]["cut_triangles"] > 0


def test_a_section_offset_is_recorded_as_given(tmp_path: Path, capsys):
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "out"), "--section", "xz:1.5"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["section"] == {
        "plane": "xz",
        "offset_mm": 1.5,
        "cut_triangles": payload["section"]["cut_triangles"],
    }
    assert "section_xz" in payload["renders"]


def test_a_section_that_misses_the_part_is_refused_with_the_range(tmp_path: Path, capsys):
    """A plane outside the part would render the uncut part — an image that
    looks fine, which is this project's documented failure. Refused, with
    the span the caller needs to aim again."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "o"), "--section", "xy:99"])
    assert code == exit_code(Verdict.ERROR)
    doc = json.loads(capsys.readouterr().out)
    assert doc["renders"] == {}
    assert "misses the part" in doc["error"]
    assert "z spans" in doc["error"]


def test_a_malformed_section_is_usage_before_any_work(tmp_path: Path, capsys):
    module = tmp_path / "spec.py"
    module.write_text("def make():\n    raise AssertionError('must not resolve')\n")
    for bad in ("ab", "xy:abc", "xy:inf", "zz:1"):
        assert main(["render", f"{module}:make", "--section", bad]) == 64, bad
        assert "--section takes" in capsys.readouterr().err


def _cut_pixels(path: Path) -> int:
    """Pixels wearing the exact shaded cut colour — the deterministic value
    the rasterizer produces for a cap facing its camera head-on."""
    import math

    np = pytest.importorskip("numpy")
    width, height, rgb = decode_png(path)
    img = np.frombuffer(rgb, np.uint8).reshape(height, width, 3)
    lz = 0.89 / math.sqrt(0.35**2 + 0.30**2 + 0.89**2)
    shade = 0.35 + 0.65 * lz
    cut = tuple(int(c * shade) for c in (204, 92, 63))
    return int((img == cut).all(axis=2).sum())


@pytest.mark.parametrize(
    ("plane", "kept", "discarded"),
    [
        ("xy", "Location((0, 0, -3)) * Box(20, 10, 6)", "Location((0, 0, 3)) * Box(6, 6, 6)"),
        ("xz", "Location((0, 3, 0)) * Box(20, 6, 10)", "Location((0, -3, 0)) * Box(6, 6, 6)"),
        ("yz", "Location((-3, 0, 0)) * Box(6, 20, 10)", "Location((3, 0, 0)) * Box(6, 6, 6)"),
    ],
)
def test_the_section_keeps_the_half_the_camera_faces(
    tmp_path: Path, capsys, plane: str, kept: str, discarded: str
):
    """PR #130 review, F2: every earlier section test cut a part symmetric
    about the plane, so flipping the discard side changed the images and
    failed nothing. Here the KEPT side carries a wide slab whose cap fills
    the frame with the cut colour; the discard side a narrow post whose own
    faces would occlude every cut pixel. A flipped half renders ZERO
    cut-coloured pixels — per plane, since each plane's sign is separate."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box, Location\n\n\ndef make_part():\n"
        f"    return {kept} + {discarded}\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    code = main(
        ["render", f"{module}:make", "--out", str(tmp_path / "out"), "--section", f"{plane}:0"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    section = Path(payload["renders"][f"section_{plane}"])
    assert _cut_pixels(section) > 10_000, (
        f"the {plane} section shows no cut face where the kept slab's cap "
        "should fill the frame — the discard side is flipped"
    )


@needs_openscad
def test_the_scad_tier_keeps_the_same_half(tmp_path: Path, capsys):
    """The discard side is decided independently in openscad.py — a flip
    there would break cross-tier agreement silently. Same construction as
    the OCCT xz case (the plane whose sign differs from the other two)."""
    pytest.importorskip("numpy", reason="no extra installed")
    (tmp_path / "part.scad").write_text(
        "union() { translate([0, 3, 0]) cube([20, 6, 10], center = true);"
        " translate([0, -3, 0]) cube([6, 6, 6], center = true); }\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('part.scad'))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "out"), "--section", "xz:0"])
    payload = json.loads(capsys.readouterr().out)
    if code == 0:
        assert _cut_pixels(Path(payload["renders"]["section_xz"])) > 10_000
    else:
        assert code == 4
        assert "display" in payload["error"]


def test_render_leaves_its_payload_on_disk_for_a_later_vdiff(tmp_path: Path, capsys):
    """#21: stdout serves the invoker, but a visual diff needs the engine
    version and framing bbox of a PAST run. render.json mirrors the payload
    with renders relativized to its own directory (the report's portability
    rule), and the bbox rides with every render — the only scale witness a
    framed image leaves."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    out = tmp_path / "out"
    assert main(["render", f"{module}:make", "--out", str(out)]) == 0
    payload = json.loads(capsys.readouterr().out)
    disk = json.loads((out / "render.json").read_text())
    assert payload["render_bbox"] == {"min": [-10.0, -5.0, -3.0], "max": [10.0, 5.0, 3.0]}
    # Same document, save for the paths: relative on disk, absolute on stdout.
    assert disk["renders"] == {v: f"renders/{v}.png" for v in ("iso", "front", "top", "right")}
    assert {k: v for k, v in disk.items() if k != "renders"} == {
        k: v for k, v in payload.items() if k != "renders"
    }

    # The stale-artifact rule: a failing run clears the previous payload.
    (tmp_path / "m.py").write_text("broken\n")
    assert main(["render", f"{module}:make", "--out", str(out)]) == 4
    capsys.readouterr()
    assert not (out / "render.json").exists()


@needs_openscad
def test_check_render_records_the_bbox_in_the_report(tmp_path: Path):
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="    p.watertight()\n")
    out = tmp_path / "out"
    code = main(["check", target, "--quiet", "--render", "--out", str(out)])
    report = report_of(out)
    if code == 0:
        span = [
            b - a
            for a, b in zip(report["render_bbox"]["min"], report["render_bbox"]["max"], strict=True)
        ]
        assert span == pytest.approx([30.0, 20.0, 10.0]), "the block's real extents"
    else:
        assert "render_bbox" not in report, "no images, no framing record"


def test_a_failing_section_leaves_no_stale_image(tmp_path: Path, capsys):
    """PR #130 review, F1: a refused section returned before the rasterizer's
    unlink, leaving the previous run's section_xy.png to be read as this
    run's — the exact stale-artifact class render() documents."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    out = tmp_path / "out"
    assert main(["render", f"{module}:make", "--out", str(out), "--section", "xy"]) == 0
    capsys.readouterr()
    section = out / "renders" / "section_xy.png"
    assert section.is_file()
    assert main(["render", f"{module}:make", "--out", str(out), "--section", "xy:99"]) == 4
    capsys.readouterr()
    assert not section.exists(), "the refused run must not leave the old image"
    assert (out / "renders" / "iso.png").is_file(), "the canonical views still render"


@needs_openscad
def test_a_section_works_on_the_openscad_tier_too(tmp_path: Path, capsys):
    """#19's both-tiers acceptance: the engine cuts its own exported STL
    (kernel-capped), the shared rasterizer draws it. Needs a display only
    for the canonical views that ride along."""
    pytest.importorskip("numpy", reason="no extra installed")
    (tmp_path / "part.scad").write_text(
        "difference() { cube([20, 10, 6], center = true);"
        " translate([5, 0, 0]) cylinder(h = 8, r = 2, center = true, $fn = 32); }\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('part.scad'))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "out"), "--section", "xy"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    if code == 0:
        assert "section_xy" in payload["renders"]
        assert Path(payload["renders"]["section_xy"]).stat().st_size > 0
        assert payload["section"]["offset_mm"] == 0.0
        assert payload["section"]["cut_triangles"] > 0
    else:
        # No display: the canonical views fail first, and the artifact says so.
        assert code == 4
        assert "display" in payload["error"]


def test_check_render_builds_the_model_exactly_once(tmp_path: Path):
    """#129: check --render rebuilt the model its run had just built —
    doubling side effects, doubling --timeout exposure, and letting a
    nondeterministic model's renders silently disagree with the measured
    geometry. The run now hands its artifact to the render step."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from pathlib import Path\n\nfrom build123d import Box\n\n"
        "COUNTER = Path(__file__).parent / 'builds.txt'\n\n\n"
        "def make_part():\n"
        "    n = int(COUNTER.read_text()) if COUNTER.exists() else 0\n"
        "    COUNTER.write_text(str(n + 1))\n"
        "    return Box(20, 10, 6)\n"
    )
    target = py_target(tmp_path, claims="    p.watertight()\n")
    out = tmp_path / "out"
    assert main(["check", target, "--render", "--quiet", "--out", str(out)]) == 0
    assert (tmp_path / "builds.txt").read_text() == "1", "one run, one build"
    report = report_of(out)
    assert set(report["renders"]) == {"iso", "front", "top", "right"}


def test_check_render_never_rebuilds_a_failing_build_for_pictures(tmp_path: Path):
    """PR #133 review, F1: a model-origin build failure left artifact_out
    empty while report.error stayed None, so the render branch rebuilt the
    model — twice the side effects, and exit 4 where plain check says 1.
    Renders depict the run's own successful build, or nothing."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from pathlib import Path\n\nfrom build123d import Box\n\n"
        "COUNTER = Path(__file__).parent / 'builds.txt'\n\n\n"
        "def make_part():\n"
        "    n = int(COUNTER.read_text()) if COUNTER.exists() else 0\n"
        "    COUNTER.write_text(str(n + 1))\n"
        "    return Box(2, 2, 2) - Box(8, 8, 8)\n"
    )
    target = py_target(tmp_path, claims="    p.watertight()\n")
    out = tmp_path / "out"
    code = main(["check", target, "--render", "--quiet", "--out", str(out)])
    assert (tmp_path / "builds.txt").read_text() == "1", (
        "a failed build is not retried for pictures"
    )
    report = report_of(out)
    assert "renders" not in report
    # The exit is the report's own, not a render-failure 4 layered on top.
    (tmp_path / "builds.txt").unlink()
    assert main(["check", target, "--quiet", "--out", str(tmp_path / "o2")]) == code


def test_check_render_does_not_build_past_a_parameter_blocker(tmp_path: Path):
    """PR #133 review, F2: a failing `requires` check skips the build — and
    --render used to build anyway, shipping images of a build the report
    says was never evaluated. The artifact must not contradict itself."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from pathlib import Path\n\nfrom build123d import Box\n\n"
        "COUNTER = Path(__file__).parent / 'builds.txt'\n\n\n"
        "def make_part(w=5):\n"
        "    n = int(COUNTER.read_text()) if COUNTER.exists() else 0\n"
        "    COUNTER.write_text(str(n + 1))\n"
        "    return Box(w, 2, 2)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('m.py', w=5))\n"
        "    p.requires('w > 10')\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{module}:make", "--render", "--quiet", "--out", str(out)]) == 1
    assert not (tmp_path / "builds.txt").exists(), (
        "rejected inputs are never built, even for pictures"
    )
    report = report_of(out)
    assert "renders" not in report


def test_the_two_python_engines_render_comparable_images(tmp_path: Path):
    """#18's differential arm: the same nominal box through build123d and
    CadQuery must produce near-identical images — same tessellator, same
    framing, same rasterizer, so a disagreement is a real geometry change."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    pytest.importorskip("cadquery", reason="cadquery extra not installed")
    (tmp_path / "bd.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 5)\n"
    )
    (tmp_path / "cq.py").write_text(
        "import cadquery\n\n\ndef make_part():\n    return cadquery.Workplane().box(20, 10, 5)\n"
    )
    for name, engine in (("bd", "build123d"), ("cq", "cadquery")):
        module = tmp_path / f"spec_{name}.py"
        module.write_text(
            f"from partspec import Part, {engine}\n\n\ndef make():\n"
            f"    return Part('subject', {engine}('{name}.py'))\n"
        )
        code = main(["render", f"{module}:make", "--out", str(tmp_path / name)])
        assert code == 0
    for view in ("iso", "front", "top", "right"):
        a = (tmp_path / "bd" / "renders" / f"{view}.png").read_bytes()
        b = (tmp_path / "cq" / "renders" / f"{view}.png").read_bytes()
        assert a == b, f"the {view} view differs between engines"


@needs_scad_tier
def test_measure_engine_block_matches_the_report_shape(tmp_path: Path, capsys):
    # measure and check had drifted (#73): wrong key order, no method. One
    # constructor now serves both, so a measure artifact answers the same
    # provenance questions a report does.
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="    p.watertight()\n")
    payload = _measure(target, capsys)
    assert list(payload["engine"]) == [
        "kind",
        "version",
        "backend",
        "render_backend",
        "adopted_via",
        "method",
        "param_mode",
    ]
    assert payload["engine"]["method"] is None
    assert payload["engine"]["param_mode"] == "define"


@needs_openscad
def test_render_engine_block_states_the_method(tmp_path: Path, capsys):
    (tmp_path / "lib.scad").write_text("module block(s = 5) { cube(s); }\n")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('lib.scad', method='block', s=8.0))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "out")])
    captured = capsys.readouterr()
    if code == 0:
        payload = json.loads(captured.out)
        assert payload["engine"]["method"] == "block"
        assert payload["engine"]["param_mode"] == "call"
    else:
        assert code == 4  # no display; the refusal path is asserted elsewhere


@needs_scad_tier
def test_render_carries_the_same_identity_as_the_report(tmp_path: Path, capsys):
    """render was the last verb whose payload named its part with a bare id
    string (#103): no digests, no closure — its images could not be tied to
    the revision that produced them. Same pin as measure's (#47)."""
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="    p.watertight()\n")
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 0
    report = report_of(out)
    capsys.readouterr()

    code = main(["render", target, "--out", str(tmp_path / "r")])
    payload = json.loads(capsys.readouterr().out)
    # With or without a display: the failure artifact carries the same
    # identity prefix as the success payload, so both branches pin here.
    assert code in (0, exit_code(Verdict.ERROR))
    assert payload["schema_version"] == report["schema_version"]
    assert payload["part"] == report["part"]
    assert payload["params"] == report["params"]
    # Presence, not just sameness: the equality pin alone cannot see a field
    # both sides lost together (PR #102 review, mutant survivor).
    assert payload["part"]["contract_digest"].startswith("sha256:")
    assert payload["part"]["source_digest"].startswith("sha256:")
    assert payload["payload"] == "render" and report["payload"] == "report", (
        "the shared prefix is what makes the two indistinguishable without it (#295)"
    )
    assert list(payload)[:7] == [
        "schema_version",
        "payload",
        "tool",
        "part",
        "engine",
        "params",
        "renders",
    ]


@needs_openscad
def test_render_failure_is_an_artifact_not_a_shrug(tmp_path: Path, capsys):
    """The render failure path printed to stderr and returned a bare 4 —
    machine-invisible exactly where a machine is the audience (#103, the
    hole #47 closed for measure)."""
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('missing.scad', bore_diamter=8))\n"
    )
    assert main(["render", f"{module}:make"]) == exit_code(Verdict.ERROR)
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert doc["schema_version"] == 1
    assert doc["part"]["id"] == "subject"
    assert doc["part"]["contract"] == "spec.py:make", "the invoked symbol, not just the file"
    assert doc["engine"]["kind"] == "openscad"
    # The payload records what was ASKED; `error` says what happened. A
    # typo'd parameter stays visible rather than vanishing with the build.
    assert doc["params"] == {"bore_diamter": 8}
    assert doc["renders"] == {}
    assert "not found" in doc["error"]
    assert "hint" in doc
    assert "not found" in captured.err, "the console courtesy line survives"


def test_the_out_default_is_anchored_to_the_contract_and_every_out_says_so(tmp_path: Path):
    """#277: three verbs default beside the CONTRACT, and none of them said so.

    `--out` absent means `<contract dir>/outputs/<part-slug>`, anchored to the
    contract file rather than to the working directory -- so the same command
    run from two places writes to one place, and running it from somewhere
    unrelated creates an `outputs/` inside a project the caller may not have
    meant to touch. That rule lived only in `_out_dir`; `check --help` and
    `measure --help` described the DIR layout without ever naming the default,
    `render --out` carried no help text at all, and SPEC-report declared the
    whole question out of scope.

    Two claims, both executable. The path is what `_out_dir` builds -- the only
    place the rule is decided. And every `--out` in the parser carries help,
    which is the structural fact `render` violated, not a statement about what
    that help says.

    Deliberately NOT asserted: that the help text contains the default. An
    earlier draft did exactly that, and AGENTS.md forbids it -- a substring
    search reports a string is present, which is not a claim anyone wanted to
    make. Proven, not assumed: with `assert "outputs/<part-slug>" in help` in
    place, inverting all three sentences to "in the working directory rather
    than beside the contract" -- #277's exact error -- still passed.

    Interpolating the three helps from one `OUT_DEFAULT_DOC` removes the drift
    between them but not the drift from behaviour: a second draft claimed there
    was "nothing left to check", and setting that constant to "the current
    working directory" passed the whole suite. So the constant is pinned here:
    its middle component is derived from the directory `_out_dir` builds, and
    its "beside the contract" claim is cross-checked against
    `built.parent.parent` by a separate assertion -- that clause is retyped in
    the expected string below, not computed from anything.

    A third draft then named the two MCP docstrings as the whole of what stayed
    unpinned. Also wrong: each help interpolated the constant into a sentence
    restating the same fact in its own words, and mutating only that sentence
    to "in the working directory rather than beside the contract" -- #277's
    exact error, rendered into a self-contradicting help string -- passed all
    1170 tests. That clause now lives inside the constant, where an exact-match
    pin reaches it.

    What that buys is narrower than three drafts of this paragraph claimed, and
    was measured rather than reasoned about: the pin reads the constant and
    nothing else. Appending a second telling of the anchor to a help passes,
    and so does appending a sentence that contradicts it -- both tried, both
    green across all 1170. The helps are asserted non-empty and no more.

    Every other statement of the default -- the MCP docstrings, both docs,
    other prose, this docstring -- is unpinned. No list of them here: four
    drafts gave one and each was short by a copy the next reviewer found with
    `grep -rn "outputs/"`, which is the answer that does not go stale.
    """
    contract = tmp_path / "widget.py"
    contract.write_text("")

    built = cli._out_dir(f"{contract}:thing", None)
    assert built == tmp_path / "outputs" / "widget-thing"
    assert cli._out_dir(str(contract), None) == tmp_path / "outputs" / "widget"

    # The advertised spelling, derived from the path the code built rather than
    # retyped: `<contract dir>` is the contract's own directory, and the middle
    # component is whatever `_out_dir` puts there.
    assert built.parent.parent == contract.parent
    assert (
        f"<contract dir>/{built.parent.name}/<part-slug>, beside the contract rather "
        f"than in the working directory"
    ) == cli.OUT_DEFAULT_DOC
    # An explicit --out is taken as given, from any working directory.
    assert cli._out_dir(f"{contract}:thing", Path("elsewhere")) == Path("elsewhere")

    parser = cli.build_parser()
    subparsers = next(
        action.choices
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    for verb, subparser in subparsers.items():
        for action in subparser._actions:
            if "--out" in action.option_strings:
                assert action.help, (
                    f"{verb} --out carries no help at all; a caller who omits it has no "
                    f"way to learn where the artifact went short of reading _out_dir"
                )


def test_the_docs_flag_prints_a_directory_the_citations_actually_resolve_against(capsys):
    """#349: `--docs` exists so the documents' own paths can be followed.

    Not "it prints a path" — the assertion is that the two files the corpus
    routes to first open UNDERNEATH what it printed. A directory named `docs`
    holding neither would satisfy any spelling-based check, and an installed
    0.7.6 had no such directory at all: `find` over the uv tool tree for
    `AGENT-CONTRACT.md` returned nothing, which is the whole of the issue.

    One line on stdout, because the documented use is `cd "$(partspec --docs)"`.
    """
    assert main(["--docs"]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert len(printed) == 1, f"stdout must carry the path alone, got {printed}"
    root = Path(printed[0])
    assert (root / "docs" / "AGENT-CONTRACT.md").is_file(), f"{root} carries no contract"
    assert (root / "skills" / "contract-authoring" / "SKILL.md").is_file(), (
        f"{root} does not answer AGENT-CONTRACT's own first-paragraph route"
    )


def test_a_copy_carrying_no_documents_refuses_rather_than_naming_the_url_as_a_path(
    capsys, monkeypatch
):
    """The refusal branch, which no checkout and no wheel reaches on its own.

    A locator's failure mode is answering anyway. Here the failure is narrower
    and worth pinning separately: printing the URL to STDOUT would put a string
    no shell can enter where the caller reads a path, so `cd "$(partspec
    --docs)"` would fail on a nonexistent directory named after a URL instead
    of on the non-zero exit. Stdout stays empty; the pointer goes to stderr.

    `ERROR`, not `EXIT_USAGE`: the arguments were fine and the tool could not
    answer them.
    """
    monkeypatch.setattr(cli, "docs_root", lambda: None)
    assert main(["--docs"]) == exit_code(Verdict.ERROR)
    captured = capsys.readouterr()
    assert captured.out == "", f"stdout must stay empty, got {captured.out!r}"
    assert "https://github.com/heibench/partspec" in captured.err


def test_the_locator_refuses_a_tree_that_holds_only_half_the_corpus(tmp_path: Path):
    """Directory presence is not the question; the entry points are.

    A partially-copied install — `docs/` there, `skills/` missing — is exactly
    where a confident path is worse than none, because the reader following
    `skills/contract-authoring/SKILL.md` gets a plausible root and a missing
    file rather than a refusal that names the URL.
    """
    from partspec.docs import _carries_the_documents

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "AGENT-CONTRACT.md").write_text("")
    assert not _carries_the_documents(tmp_path)

    (tmp_path / "skills" / "contract-authoring").mkdir(parents=True)
    (tmp_path / "skills" / "contract-authoring" / "SKILL.md").write_text("")
    assert _carries_the_documents(tmp_path)


def test_the_locator_answers_each_layout_it_can_meet(tmp_path: Path, monkeypatch):
    """`docs_root()`'s refusal, executed rather than stood in for.

    The CLI test above monkeypatches `cli.docs_root`, so it exercises the
    refusal MESSAGE and not the decision behind it — coverage showed the
    `return None` line unexecuted by the whole suite (PR #350 review, finding
    9). The locator reads `__file__` at call time, so a package directory that
    carries neither a `_bundled/` nor a `src/` parent is the real thing: a
    partial copy, or an install this project did not build.
    """
    from partspec import docs as docs_module

    package = tmp_path / "site-packages" / "partspec"
    package.mkdir(parents=True)
    monkeypatch.setattr(docs_module, "__file__", str(package / "docs.py"))
    assert docs_module.docs_root() is None

    # And the checkout branch, from the same probe: `src/` above the package,
    # with both entry points under its parent.
    checkout = tmp_path / "checkout"
    (checkout / "src" / "partspec").mkdir(parents=True)
    (checkout / "docs").mkdir()
    (checkout / "docs" / "AGENT-CONTRACT.md").write_text("")
    (checkout / "skills" / "contract-authoring").mkdir(parents=True)
    (checkout / "skills" / "contract-authoring" / "SKILL.md").write_text("")
    monkeypatch.setattr(docs_module, "__file__", str(checkout / "src" / "partspec" / "docs.py"))
    assert docs_module.docs_root() == checkout

    # And the INSTALLED branch, which the suite otherwise reaches only through
    # a subprocess (`test_the_installed_wheel_locates_the_documents_it_carries`
    # runs a real venv's entry point, so nothing in-process executes this
    # line).
    #
    # The order is a preference, not a tie-break: no shipped layout presents
    # both candidates. An editable install does put a `_bundled/` in
    # site-packages, but its `.pth` redirects the import to `src/`, so
    # `__file__` — which is what the locator reads — only ever sees one of
    # them. Claiming it disambiguated an editable-then-built checkout was
    # invented; `src/partspec/_bundled` is never created by a build (PR #350
    # review, NEW-C).
    bundled = tmp_path / "site-packages2" / "partspec" / "_bundled"
    (bundled / "docs").mkdir(parents=True)
    (bundled / "docs" / "AGENT-CONTRACT.md").write_text("")
    (bundled / "skills" / "contract-authoring").mkdir(parents=True)
    (bundled / "skills" / "contract-authoring" / "SKILL.md").write_text("")
    monkeypatch.setattr(docs_module, "__file__", str(bundled.parent / "docs.py"))
    assert docs_module.docs_root() == bundled


def test_the_docs_flag_refuses_to_stand_in_for_a_verb(capsys):
    """`partspec --docs check part.py` printed a path and exited 0.

    It ran no check. Exit 0 on a check the caller asked for is the one reading
    this tool exists to refuse, and the same command without a target already
    exited 64 — so the two spellings of one mistake disagreed (PR #350 review,
    finding 10). `--version` discards a command the same way, which is the
    argument this followed until the exit code was looked at.
    """
    assert main(["--docs", "check", "part.py"]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == "", "a path on stdout would read as a check that ran"
    assert "check" in captured.err


# --------------------------------------------------------------------------
# the `render` verb refuses a hollowed part; `check --render` is unaffected (#307)
# --------------------------------------------------------------------------


def _hollowed_scad_target(tmp_path: Path, claims: str = "") -> str:
    (tmp_path / "um.scad").write_text(
        "difference() { cube([40,30,6], center=true); bore_hole(d=8); }\n"
    )
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    p = Part('subject', openscad('um.scad'))\n"
        f"{claims}"
        "    return p\n"
    )
    return f"{spec}:make"


@needs_openscad
def test_render_refuses_a_hollowed_part_and_says_it_cannot_attribute_it(tmp_path: Path, capsys):
    """#307. `render` wrote four PNGs of the wrong part at exit 0.

    `origin` is the field #191 added so a consumer can tell a degenerate solid
    from a library that would not load. It had two spellings, so this refusal
    would have published the default `"model"` -- asserting the design is at
    fault on the one failure partspec is certain it cannot attribute. It is
    `null`, matching `report.build_origin` on `check`'s path (SPEC-report §6.1).
    """
    out = tmp_path / "out"
    assert main(["render", _hollowed_scad_target(tmp_path), "--out", str(out)]) == exit_code(
        Verdict.ERROR
    )
    doc = json.loads(capsys.readouterr().out)

    assert doc["renders"] == {}
    assert doc["origin"] is None
    assert "bore_hole" in doc["error"]
    assert not list(out.glob("renders/*.png")), "no view of a part the source does not describe"

    # What a refusing `render` DOES leave, pinned because the first draft said
    # "nothing is written" and that is false (#354 review, M4). The STL export
    # is how the fault is detected, so it lands; `render.json` is removed as it
    # is on every failing render (#21), and a consumer reads its absence as
    # "this run wrote no payload" rather than as the last one surviving.
    assert (out / "um.stl").is_file()
    assert not (out / "render.json").exists()


@needs_scad_tier
def test_check_render_is_unaffected_by_the_render_refusal(tmp_path: Path):
    """The note on #307: `check --render` never reached the render path.

    `cli.py` gates the views on `report.error is None`, so a run #286 already
    refused never got as far as drawing anything. Pinned because the fix lands
    in `render_views`, which both verbs share -- a regression here would look
    like a `check` bug and be a `render` one.

    `needs_scad_tier`, not `needs_openscad`: this drives a `check` through the
    runner, so without the mesh extra the build fails for an ENVIRONMENT reason
    first and the run errors on a different path entirely -- `build_origin`
    reads `"environment"` there rather than the `null` #286's refusal leaves.
    Caught by `just test-no-extras`, which is the job that exists for exactly
    this (see `support.needs_scad_tier`).
    """
    out = tmp_path / "out"
    target = _hollowed_scad_target(tmp_path, claims="    p.watertight()\n")
    assert main(["check", "--render", target, "--out", str(out), "--quiet"]) == exit_code(
        Verdict.ERROR
    )

    report = report_of(out)
    assert report["verdict"] == "error"
    assert report["build_origin"] is None
    assert "renders" not in report
    assert not out.joinpath("renders").exists()
