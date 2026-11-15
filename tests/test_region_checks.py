"""The runner path for `keep_out` / `keep_in`, both tiers.

Split out of `test_runner.py` (#153), and named for its subject rather than its
method: it was `test_regions_e2e.py` until #159. Counting is what settled it —
of the 18 tests it held then, only 7 drove `run()`; the other 11 attack the
adjudication through `_BoxWorld`, the honest one-box stub, with no kernel at
all, so a reader filtering `_e2e` for end-to-end coverage was over-counting by
eleven. After the four attribution tests left for `test_attribution.py` the
ratio is starker still — **3 of the 14 here drive `run()`** — because the ones
that left were among the end-to-end ones. `test_region_checks` is true of every
test in this file and claims no tier.

The four per-component attribution tests that came along in the original split
have moved to `test_attribution.py`; they were #84's subject, not this one's.
`test_region_clauses_appear_as_components` stays, because a region clause
appearing as a component IS a claim about the region check.

`test_region.py` holds the region *data* (the canonical polyhedron both tiers
materialize); this file holds the runner path that consumes it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support import needs_scad_tier

from partspec import Measurement, Part, Status, Unsupported, Verdict, openscad, run

FIXTURES = Path(__file__).parent / "fixtures"
PLATE = FIXTURES / "parametric_plate.scad"


# --------------------------------------------------------------------------
# keep_out / keep_in — the paired region-and-shell adjudication (#49)
# --------------------------------------------------------------------------

# The stub is an honest one-box world, not a canned answer sequence: parts and
# materialized regions are all axis-aligned boxes, and intersect_volume is real
# AABB overlap arithmetic. The adjudication logic is then tested against true
# geometry without an engine in sight.


class _BoxWorld:
    kind = "stub"

    def capabilities(self):
        return frozenset({"region_solid", "intersect_volume"})

    def region_solid(self, region):
        # The AABB of the region's own mesh, which is exactly `min`/`max` for a
        # box and the polygon's extent for a cylinder. Via `mesh()` so the stub
        # accepts both kinds: a cylinder region is the only one with a non-zero
        # facet floor, so the branch that sets a depth beside that floor is
        # unreachable from a box-only stub (round-2 review of #207).
        verts = region.mesh()[0]
        return (
            tuple(min(v[i] for v in verts) for i in range(3)),
            tuple(max(v[i] for v in verts) for i in range(3)),
        )

    def intersect_volume(self, a, b) -> Measurement | Unsupported:
        from partspec.status import Measurement

        (alo, ahi), (blo, bhi) = a, b
        v = 1.0
        for lo1, hi1, lo2, hi2 in zip(alo, ahi, blo, bhi, strict=True):
            v *= max(0.0, min(hi1, hi2) - max(lo1, lo2))
        return Measurement(v, "mm3", exact=True)


def _region_result(part_box, kind, region, shell):
    from partspec.contract import CheckSpec
    from partspec.runner import _run_geometry_check

    spec = CheckSpec(id="r", kind=kind, phase="geometry", region=region, shell=shell)
    return _run_geometry_check(spec, _BoxWorld(), part_box)


def _box_part(lo, hi):
    return (lo, hi)


def test_keep_out_passes_when_the_region_is_empty_and_something_surrounds_it():
    from partspec.region import box

    part = _box_part((0, 0, 0), (10, 10, 10))
    result = _region_result(part, "keep_out", box(min=(12, 0, 0), max=(14, 10, 10)), shell=3.0)
    assert result.status is Status.PASS
    assert result.measurement is not None
    in_region, in_shell = result.measurement.value
    assert in_region == 0.0
    assert in_shell > 0.0  # the 9..10 slab of the part lies inside the shell
    assert result.limit is None
    assert result.region == {
        "shape": "box",
        "min": [12.0, 0.0, 0.0],
        "max": [14.0, 10.0, 10.0],
        "shell": 3.0,
    }


def test_keep_out_fails_on_intruding_material_and_names_the_volume():
    from partspec.region import box

    part = _box_part((0, 0, 0), (10, 10, 10))
    result = _region_result(part, "keep_out", box(min=(9, 0, 0), max=(11, 10, 10)), shell=2.0)
    assert result.status is Status.FAIL
    assert result.detail is not None and "100 mm3" in result.detail


def test_keep_out_fails_when_nothing_surrounds_the_region():
    """The mandatory-shell acceptance in #49: a part with the material deleted
    satisfies the naive claim perfectly, and must not pass."""
    from partspec.region import box

    part = _box_part((100, 100, 100), (110, 110, 110))
    result = _region_result(part, "keep_out", box(min=(0, 0, 0), max=(5, 5, 5)), shell=2.0)
    assert result.status is Status.FAIL
    assert result.detail is not None and "absent part satisfies the bare emptiness" in result.detail
    # The remedy, not only the problem (#458): a region set inside a larger void
    # fails the same way, and its fix is to reach the void's edge.
    assert "extend the region to an edge of the void" in result.detail


def test_keep_in_passes_when_solid_and_bounded():
    from partspec.region import box

    part = _box_part((0, 0, 0), (10, 10, 10))
    result = _region_result(part, "keep_in", box(min=(7, 1, 1), max=(9, 9, 9)), shell=2.0)
    assert result.status is Status.PASS
    assert result.measurement is not None
    in_region, in_shell = result.measurement.value
    assert in_region == pytest.approx(2 * 8 * 8)
    # 500 mm3 of the part lies inside the outer box; the shell figure must be
    # the difference, not the raw outer intersection (a mutation that reported
    # in_outer here survived every other engine-free test).
    assert in_shell == pytest.approx(500.0 - 128.0)


def test_keep_in_fails_on_missing_material_and_names_the_deficit():
    from partspec.region import box

    part = _box_part((0, 0, 0), (10, 10, 10))
    result = _region_result(part, "keep_in", box(min=(8, 0, 0), max=(12, 10, 10)), shell=1.0)
    assert result.status is Status.FAIL
    assert result.detail is not None and "missing 200 mm3" in result.detail


def test_keep_in_fails_inside_an_unbounded_block():
    """The mirror vacuity: every keep-in is satisfied by a brick, so a shell
    that is entirely solid must fail the check."""
    from partspec.region import box

    part = _box_part((0, 0, 0), (20, 20, 20))
    result = _region_result(part, "keep_in", box(min=(8, 8, 8), max=(12, 12, 12)), shell=2.0)
    assert result.status is Status.FAIL
    assert (
        result.detail is not None and "unbounded block satisfies the bare solidity" in result.detail
    )
    assert "extend the region to a face of the feature" in result.detail


def test_a_backend_refusal_propagates_to_the_region_check():
    from partspec.backend import Unsupported
    from partspec.region import box

    class _Refusing(_BoxWorld):
        def intersect_volume(self, a, b):
            return Unsupported("manifold3d rejected this mesh: NotManifold")

    from partspec.contract import CheckSpec
    from partspec.runner import _run_geometry_check

    spec = CheckSpec(
        id="r",
        kind="keep_out",
        phase="geometry",
        region=box(min=(0, 0, 0), max=(1, 1, 1)),
        shell=1.0,
    )
    result = _run_geometry_check(spec, _Refusing(), _box_part((0, 0, 0), (1, 1, 1)))
    assert result.status is Status.UNSUPPORTED
    assert result.detail is not None and "rejected" in result.detail


def test_a_skipped_region_check_still_records_its_claim(tmp_path: Path):
    """Short-circuited by a failing parameter check, the report must still say
    what the region check would have claimed — an absent claim is the
    vacuous-green failure wearing a different hat."""
    from partspec.region import box

    p = Part("s", openscad(PLATE, plate_x=-1.0, plate_y=30.0, plate_z=4.0))
    p.requires("plate_x > 0")
    p.keep_out(box(min=(0, 0, 0), max=(1, 1, 1)), shell=1.0)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "keep_out")
    assert check.status is Status.SKIPPED
    assert check.region == {
        "shape": "box",
        "min": [0.0, 0.0, 0.0],
        "max": [1.0, 1.0, 1.0],
        "shell": 1.0,
    }


@needs_scad_tier
def test_region_checks_run_end_to_end_on_the_mesh_tier(tmp_path: Path):
    """A clearance hole passes its keep_out and a boss its keep_in, and the
    written report carries the declared regions (#49 acceptance, mesh side)."""
    from partspec.region import box, cylinder

    scad = tmp_path / "bracket.scad"
    scad.write_text(
        "difference() {\n"
        "  union() {\n"
        "    cube([40, 30, 6]);\n"
        "    translate([27.5, 17.5, 6]) cube([5, 5, 4]);\n"
        "  }\n"
        "  translate([10, 10, -1]) cylinder(d=5.4, h=8, $fn=64);\n"
        "}\n"
    )
    p = Part("bracket", openscad(scad))
    p.keep_out(cylinder(d=5.0, h=8.0, at=(10, 10, -1)), shell=2.0, id="bolt_clearance")
    p.keep_in(box(min=(28.5, 18.5, 6.5), max=(31.5, 21.5, 9.5)), shell=1.0, id="boss_core")
    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.PASS, [c.to_json() for c in report.checks]

    written = json.loads((report.write(tmp_path / "out")).read_text())
    bolt = next(c for c in written["checks"] if c["id"] == "bolt_clearance")
    assert bolt["region"]["shape"] == "cylinder"
    assert bolt["region"]["shell"] == 2.0
    assert bolt["limit"] is None
    assert bolt["measurement"]["axes"] == ["region", "shell"]
    assert bolt["measurement"]["value"][0] == 0.0


@needs_scad_tier
def test_an_oversize_hole_fails_its_keep_out_on_the_mesh_tier(tmp_path: Path):
    """The region is empty — the naive check would pass — but the clearance
    exceeds the shell everywhere, so nothing surrounds the declared hole."""
    from partspec.region import cylinder

    scad = tmp_path / "oversize.scad"
    scad.write_text(
        "difference() {\n"
        "  cube([40, 30, 6]);\n"
        "  translate([10, 10, -1]) cylinder(d=10, h=8, $fn=64);\n"
        "}\n"
    )
    p = Part("oversize", openscad(scad))
    p.keep_out(cylinder(d=5.0, h=8.0, at=(10, 10, -1)), shell=2.0, id="bolt_clearance")
    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.FAIL
    check = next(c for c in report.checks if c.id == "bolt_clearance")
    assert check.detail is not None and "shell" in check.detail


def test_both_region_clauses_can_fail_and_neither_message_contradicts_the_other():
    """A lone crumb inside the region of an otherwise-deleted part fails the
    core claim AND the shell claim. Each message must describe only what its
    own clause measured — the first cut of this code said 'the region is
    empty' in a detail string that also reported the intrusion volume."""
    from partspec.region import box

    part = _box_part((1, 1, 1), (2, 2, 2))
    result = _region_result(part, "keep_out", box(min=(0, 0, 0), max=(5, 5, 5)), shell=1.0)
    assert result.status is Status.FAIL
    assert result.detail is not None
    assert "1 mm3 of material intrudes" in result.detail
    assert "no material lies within the 1 mm shell" in result.detail
    assert "region is empty" not in result.detail


def test_a_sub_epsilon_intrusion_is_tolerated_but_still_recorded():
    """epsilon(0.0) = 1e-6 mm3 — a ~10 um cube. Below it the verdict tolerates
    boolean dust; the measurement still shows the true figure, so the report
    never hides what the verdict forgave."""
    from partspec.region import box

    part = _box_part((0, 0, 0), (10, 10, 10))
    result = _region_result(part, "keep_out", box(min=(10 - 1e-8, 0, 0), max=(12, 1, 1)), shell=2.0)
    assert result.status is Status.PASS
    assert result.measurement is not None
    assert result.measurement.value[0] == pytest.approx(1e-8, rel=0.01)


def test_keep_in_tolerance_scales_with_region_volume():
    """The relative epsilon term is load-bearing on large regions: a 10 L
    region missing 0.5 mm3 to float accumulation must pass, and would fail
    under a flat epsilon(0.0)."""
    from partspec.region import box

    part = _box_part((0, 0, 0), (200, 200, 250))
    result = _region_result(
        part, "keep_in", box(min=(0, 0, 0), max=(200, 200, 250 + 1.25e-5)), shell=2.0
    )
    assert result.status is Status.PASS
    assert result.measurement is not None
    assert result.measurement.value[0] == pytest.approx(200 * 200 * 250)


# --------------------------------------------------------------------------
# per-component attribution (#84)
# --------------------------------------------------------------------------


def test_region_clauses_appear_as_components():
    from partspec.region import box

    part = _box_part((1, 1, 1), (2, 2, 2))
    both = _region_result(part, "keep_out", box(min=(0, 0, 0), max=(5, 5, 5)), shell=1.0)
    assert both.components == {"region": Status.FAIL, "shell": Status.FAIL}

    ok = _region_result(
        _box_part((0, 0, 0), (10, 10, 10)),
        "keep_out",
        box(min=(12, 0, 0), max=(14, 10, 10)),
        shell=3.0,
    )
    assert ok.components == {"region": Status.PASS, "shell": Status.PASS}

    # The asymmetric cases are what pin WHICH clause each entry reports: with
    # the two swapped, a report would blame the shell for the region's
    # intrusion — and the symmetric cases above cannot see it.
    intruded = _region_result(
        _box_part((4, 4, 4), (6, 6, 6)), "keep_out", box(min=(0, 0, 0), max=(5, 5, 5)), shell=2.0
    )
    assert intruded.components == {"region": Status.FAIL, "shell": Status.PASS}

    nothing_around = _region_result(
        _box_part((100, 100, 100), (110, 110, 110)),
        "keep_out",
        box(min=(0, 0, 0), max=(5, 5, 5)),
        shell=2.0,
    )
    assert nothing_around.components == {"region": Status.PASS, "shell": Status.FAIL}


# --------------------------------------------------------------------------
# intrusion depth (#207): the number that tells faceting from interference
# --------------------------------------------------------------------------


def test_a_failing_keep_out_says_how_deep_the_material_reaches():
    """Volume alone cannot separate the two situations an engineer most needs
    told apart: it scales with the AREA of the contact and only linearly with
    depth, so a hair-thin film over a large face outweighs a deep local spike
    (#207).

    Exact by construction here. The region is a 10 mm box; the part reaches
    1.5 mm past its `x = 0` face and stands 2 mm clear of every other face, so
    the deepest point of the overlap is 1.5 mm inside — `min` over the faces,
    which is what depth means.
    """
    from partspec.region import box

    region = box(min=(0, 0, 0), max=(10, 10, 10))
    result = _region_result(_box_part((-5, 2, 2), (1.5, 8, 8)), "keep_out", region, 1.0)

    assert result.status is Status.FAIL
    assert result.intrusion is not None
    proven = result.intrusion["min_depth_mm"]
    assert proven == pytest.approx(1.5, abs=1e-2), f"1.5 mm by construction, proven {proven}"
    assert proven <= 1.5, "a LOWER bound: it may never claim more than the part reaches"
    assert result.intrusion["volume_mm3"] == pytest.approx(1.5 * 6 * 6)
    assert "reaching at least 1.5 mm past its boundary" in (result.detail or ""), result.detail


def test_the_depth_is_a_lower_bound_and_is_not_dressed_up_as_a_bracket():
    """The search stops when the eroded intersection falls below a VOLUME
    threshold, not when it empties — so its upper end is not an upper bound.

    Measured on this stub's exact AABB arithmetic: a 2 mm cube centred in a
    10 mm keep-out is 5.0 mm deep and the search reports 4.995, an error 8400x
    the search interval. Calling that pair "the bracket the depth was proven
    within" was false in the only direction that matters (adversarial review of
    #207), so only the proven side is reported, and it is named `min_depth_mm`.
    """
    from partspec.region import box

    region = box(min=(0, 0, 0), max=(10, 10, 10))
    result = _region_result(_box_part((4, 4, 4), (6, 6, 6)), "keep_out", region, 1.0)

    assert result.intrusion is not None
    proven = result.intrusion["min_depth_mm"]
    assert proven <= 5.0, "a cube centred in the region is 5 mm deep; never claim more"
    assert proven > 4.9, "and the bound is still worth printing"
    assert "max_depth_mm" not in result.intrusion, "no upper bound is available to name"
    assert result.intrusion["detected_above_mm3"] > 0, (
        "the stopping threshold is stated, since it is what makes this a bound"
    )
    assert "at least" in (result.detail or "")


def test_a_passing_keep_out_pays_nothing_for_the_depth():
    """Each bisection step is a boolean. A region with nothing in it has no
    depth to find, and a passing check must not buy one."""
    from partspec.region import box

    region = box(min=(0, 0, 0), max=(10, 10, 10))
    # Clear of the region, inside the shell: both clauses pass.
    result = _region_result(_box_part((11, 0, 0), (14, 10, 10)), "keep_out", region, 2.0)

    assert result.status is Status.PASS
    assert result.intrusion is None, "no breach, no bisection"


def test_keep_in_carries_no_intrusion():
    """A failing `keep_in` is a DEFICIT of material, not a breach. "How deep"
    is not the question, and answering it would cost booleans for a number
    describing the wrong direction."""
    from partspec.region import box

    region = box(min=(0, 0, 0), max=(10, 10, 10))
    result = _region_result(_box_part((0, 0, 0), (10, 10, 5)), "keep_in", region, 1.0)

    assert result.status is Status.FAIL
    assert result.intrusion is None


def test_a_box_region_has_no_facet_floor():
    """A box's faces ARE the declared planes: nothing is discretised, so there
    is no circumscription to explain an intrusion away with."""
    from partspec.region import box

    region = box(min=(0, 0, 0), max=(10, 10, 10))
    result = _region_result(_box_part((-5, 2, 2), (1.5, 8, 8)), "keep_out", region, 1.0)

    assert result.intrusion is not None
    assert result.intrusion["facet_floor_mm"] == 0.0
    assert "circumscription" not in (result.detail or "")


@needs_scad_tier
def test_faceting_noise_and_real_interference_no_longer_read_alike(tmp_path: Path):
    """#207's whole complaint, on the geometry it was filed with.

    A nominal 41 mm bore checked against a 41 mm keep-out column fails, and so
    does the same plate with a rib genuinely 1.5 mm into it. Both said
    `N mm3 of material intrudes` and nothing else, so the reporter had to
    bisect the region diameter by hand to find out which they had.

    The depth separates them by sixty times where the volumes differ by six,
    and the noise case now has something to be read against: a floor derived
    from the declaration rather than guessed at. Read against, not explained
    by — the tool prints both numbers and draws no conclusion (§4.4).
    """
    from partspec.region import cylinder

    bore = (
        "difference() {\n"
        "  cylinder(r = 80, h = 8, $fn = 180);\n"
        "  translate([0,0,-1]) cylinder(d = 41, h = 10, $fn = 128);\n"
        "}\n"
    )
    (tmp_path / "plain.scad").write_text(bore)
    # A rib crossing the bore wall: its inner face sits at r = 19.0, so it
    # reaches exactly 1.5 mm inside the declared 41 mm circle.
    (tmp_path / "rib.scad").write_text(
        f"union() {{\n{bore}  translate([19.0, -3, 0]) cube([4, 6, 8]);\n}}\n"
    )

    depths = {}
    for name in ("plain", "rib"):
        p = Part(name, openscad(tmp_path / f"{name}.scad"))
        p.keep_out(cylinder(d=41.0, h=18.0, at=(0, 0, -5)), shell=0.5, id="bore")
        check = next(c for c in run(p, out_dir=tmp_path / f"out-{name}").checks if c.id == "bore")
        assert check.status is Status.FAIL, f"{name}: both cases fail; that is the complaint"
        assert check.intrusion is not None
        depths[name] = check.intrusion

    assert depths["rib"]["min_depth_mm"] == pytest.approx(1.5, abs=1e-4), (
        "the rib reaches 1.5 mm past the boundary by construction"
    )
    assert depths["plain"]["min_depth_mm"] < depths["rib"]["min_depth_mm"] / 20, (
        f"faceting {depths['plain']['min_depth_mm']} vs interference "
        f"{depths['rib']['min_depth_mm']} — the two must not read alike"
    )
    # And the volumes, which is what the reporter had: the SAME order of
    # magnitude, which is why volume alone could not decide.
    assert depths["plain"]["volume_mm3"] > 12.0


@needs_scad_tier
def test_the_facet_floor_is_derived_and_explains_the_noise_case(tmp_path: Path):
    """The floor is closed-form, not a threshold someone picked.

    A `keep_out` region CIRCUMSCRIBES the declared cylinder, so its corners
    stand `r·(sec(pi/n) - 1)` proud of it — but the erosion measures the
    SAGITTA `r·(1 - cos(pi/n))`, smaller by `sec(pi/n)`, because `expand(-t)`
    moves those corners by `t·sec(pi/n)` rather than by `t`. #207 attributes the noise to the BORE's
    faceting (~0.006 mm at $fn=128); the region's own floor at the default 64
    segments is four times larger and is what actually sets it.
    """
    from partspec.region import cylinder

    (tmp_path / "m.scad").write_text(
        "difference() {\n"
        "  cylinder(r = 80, h = 8, $fn = 180);\n"
        "  translate([0,0,-1]) cylinder(d = 41, h = 10, $fn = 128);\n"
        "}\n"
    )
    region = cylinder(d=41.0, h=18.0, at=(0, 0, -5))
    p = Part("plain", openscad(tmp_path / "m.scad"))
    p.keep_out(region, shell=0.5, id="bore")
    check = next(c for c in run(p, out_dir=tmp_path / "out").checks if c.id == "bore")

    assert check.intrusion is not None
    assert check.intrusion["facet_floor_mm"] == pytest.approx(region.facet_floor())
    assert check.intrusion["min_depth_mm"] == pytest.approx(region.facet_floor(), rel=2e-3), (
        "the measured noise IS the region's own faceting, to three figures"
    )
    # And at 8 segments, where the sagitta and the radial excess are 8.2%
    # apart, the measurement picks the sagitta: 1.560399 against 1.560470 and
    # 1.689040. Executed, because it is the whole reason the formula changed.
    coarse_region = cylinder(d=41.0, h=18.0, at=(0, 0, -5), segments=8)
    q = Part("plain8", openscad(tmp_path / "m.scad"))
    q.keep_out(coarse_region, shell=0.5, id="bore")
    coarse_check = next(c for c in run(q, out_dir=tmp_path / "out8").checks if c.id == "bore")
    assert coarse_check.intrusion is not None
    assert coarse_check.intrusion["min_depth_mm"] == pytest.approx(1.5604, abs=5e-4)
    assert coarse_check.intrusion["min_depth_mm"] == pytest.approx(
        coarse_region.facet_floor(), abs=1e-4
    ), "the erosion measures the sagitta; the radial excess is 1.689, out by 8%"
    # A SCALE, not a decomposition. Two drafts asserted a cause and both were
    # measured false: "so the intrusion is its discretisation rather than the
    # part" (the floor covers the region's term only), and "...accounts for up
    # to X of that, and the modelled feature's tessellation for more" (the
    # terms select rather than sum, there is no tessellation at all on an exact
    # backend, and "of that" is incoherent whenever the floor exceeds the whole
    # depth — as it does on this very case, 0.024693 against 0.024684).
    detail = check.detail or ""
    assert "would show 0.02469 mm against a perfectly circular feature" in detail
    for conclusion in (
        "discretisation rather than the part",
        "accounts for up to",
        "tessellation for more",
    ):
        assert conclusion not in detail, (
            f"{conclusion!r}: the tool prints both numbers; the reader draws the conclusion"
        )
    assert check.intrusion["facet_floor_mm"] > check.intrusion["min_depth_mm"], (
        "0.024693 vs 0.024684 — the floor EXCEEDS the depth here, because the "
        "reported depth is a lower bound on it, which is why no wording may "
        "present the floor as a share of the depth"
    )

    # Quadratic in the segment count, which is the author's lever.
    coarse = cylinder(d=41.0, h=18.0, at=(0, 0, -5), segments=16)
    fine = cylinder(d=41.0, h=18.0, at=(0, 0, -5), segments=128)
    # Quadratic: halving the segment size quarters the floor. The ratios are
    # asserted, since `a > 16b > 16c` is satisfied by any decreasing function.
    assert coarse.facet_floor() / region.facet_floor() == pytest.approx(16.0, rel=0.02)
    assert region.facet_floor() / fine.facet_floor() == pytest.approx(4.0, rel=0.02)

    # The SAGITTA, not the radial excess `sec(x) - 1`. Both equal `x^2/2` to
    # leading order, so at 64 segments they agree to 0.12% and every assertion
    # above passes for either — which is how the wrong one shipped for three
    # review rounds while the resulting mismatch was explained away as the
    # bore's faceting. Only a coarse polygon separates them: at 8 segments the
    # radial excess is 8.2% larger, and it is the SAGITTA that the erosion
    # measures, because `expand(-t)` moves the corners by `t·sec(pi/n)` rather
    # than by `t` (round-4 review of #207).
    coarsest = cylinder(d=41.0, h=18.0, at=(0, 0, -5), segments=8)
    import math

    radial_excess = (41.0 / 2) * (1 / math.cos(math.pi / 8) - 1)
    assert coarsest.facet_floor() == pytest.approx((41.0 / 2) * (1 - math.cos(math.pi / 8)))
    assert radial_excess / coarsest.facet_floor() == pytest.approx(1.0824, rel=1e-3), (
        "8.2% apart at 8 segments against 0.12% at 64 — which is why the "
        "assertions above could not tell the two formulas apart"
    )


@needs_scad_tier
def test_the_vertex_maximum_the_issue_suggested_understates_the_depth(tmp_path: Path):
    """Executed, because it is the reason the implementation departs from what
    #207 asked for.

    The issue suggests "the largest distance any intruding VERTEX sits inside
    the region boundary". Depth is a min of linear functions, so it is concave,
    and a concave function's maximum over a polytope is generally interior —
    the deepest point of a rib's inner face is the middle of that face, which
    is not a vertex of anything. The intersection is non-convex in general, so
    there is no vertex guarantee to fall back on either.
    """
    import numpy as np

    from partspec.backends.mesh import MeshBackend, _manifold
    from partspec.region import cylinder

    (tmp_path / "rib.scad").write_text(
        "union() {\n"
        "  difference() {\n"
        "    cylinder(r = 80, h = 8, $fn = 180);\n"
        "    translate([0,0,-1]) cylinder(d = 41, h = 10, $fn = 128);\n"
        "  }\n"
        "  translate([19.0, -3, 0]) cube([4, 6, 8]);\n"
        "}\n"
    )
    region = cylinder(d=41.0, h=18.0, at=(0, 0, -5))
    p = Part("rib", openscad(tmp_path / "rib.scad"))
    p.keep_out(region, shell=0.5, id="bore")
    check = next(c for c in run(p, out_dir=tmp_path / "out").checks if c.id == "bore")
    assert check.intrusion is not None

    backend = MeshBackend()
    artifact = backend.load(tmp_path / "out" / "rib.stl")
    part_manifold = _manifold(artifact)
    region_manifold = _manifold(backend.region_solid(region))
    assert not isinstance(part_manifold, Unsupported)
    assert not isinstance(region_manifold, Unsupported)
    common = part_manifold ^ region_manifold
    verts = np.asarray(common.to_mesh().vert_properties)[:, :3].astype(float)
    # Depth to the region's own side planes, which is all the suggested metric
    # can see. The caps are far away here, so the sides decide.
    # Distance to the polygon's SIDE PLANES, which is what depth means here —
    # not to the declared circle. The apothem is d/2 and the planes face the
    # even half-angles; using the circle instead gave 1.2646 where the real
    # vertex maximum is 1.2798 (adversarial review of #207).
    n = region.segments
    angles = 2 * np.pi * np.arange(n) / n
    normals = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    vertex_max = float((20.5 - (verts[:, :2] @ normals.T).max(axis=1)).max())

    assert check.intrusion["min_depth_mm"] == pytest.approx(1.5, abs=1e-3)
    assert vertex_max == pytest.approx(1.2798, abs=2e-3), (
        f"the vertex maximum is {vertex_max:.4f} against a rib built at 1.500 — "
        f"which is why the erosion form is used instead"
    )


def test_a_region_is_eroded_by_its_smallest_half_extent_not_its_largest():
    """`inradius()` is the erosion at which the region vanishes, and dropping
    the `min` from either kind survives the rest of the suite.

    It is the only thing standing between `_max_intrusion_depth` and calling
    `expand(-r)` on a degenerate region, which raises `ContractError` with no
    handler — so the mutation that survives is the one that crashes (adversarial
    review of #207). A long thin cylinder erodes axially; a flat box erodes
    through its thinnest axis.
    """
    from partspec.region import box, cylinder
    from partspec.status import ContractError

    tall = cylinder(d=5.0, h=100.0, at=(0, 0, 0))
    assert tall.inradius() == 2.5, "radial, not axial"
    flat = box(min=(0, 0, 0), max=(10, 10, 0.4))
    assert flat.inradius() == pytest.approx(0.2), "the thinnest axis, not the widest"

    # Past the inradius there is no region left, which is why the search stops
    # there rather than discovering it by exception.
    for region in (tall, flat):
        with pytest.raises(ContractError):
            region.expand(-(region.inradius() + 0.5))


def test_the_reported_search_parameters_are_the_ones_the_search_used():
    """`search_resolution_mm` and `detected_above_mm3` are what make
    `min_depth_mm` readable as a bound; unpinned, they are decoration.

    Both were: multiplying the reported resolution by 1000 and reporting a
    threshold of `1e-30` beside a loop still using `epsilon(0.0)` each survived
    the whole suite (round-2 review of #207).
    """
    from partspec.region import box
    from partspec.status import epsilon

    region = box(min=(0, 0, 0), max=(20, 20, 20))
    got = _region_result(
        _box_part((-50, -50, -50), (50, 50, 1.5)), "keep_out", region, 1.0
    ).intrusion
    assert got is not None

    # The interval 24 halvings of the INRADIUS actually leave, and the true
    # depth — 1.5 mm by construction — inside `[proven, proven + resolution]`.
    assert got["search_resolution_mm"] == pytest.approx(region.inradius() / 2**24, rel=1e-9)
    assert got["min_depth_mm"] <= 1.5 <= got["min_depth_mm"] + got["search_resolution_mm"]

    # And the reported threshold is the one the loop compares against: at the
    # proven depth the region still held more than it, and one resolution
    # deeper it did not. Asserted against the region's own volume, since this
    # part fills it entirely at that depth.
    buried = _region_result(
        _box_part((-50, -50, -50), (50, 50, 50)), "keep_out", region, 1.0
    ).intrusion
    assert buried is not None
    threshold = buried["detected_above_mm3"]
    assert threshold == epsilon(0.0)
    assert region.expand(-buried["min_depth_mm"]).volume() > threshold
    assert (
        region.expand(-(buried["min_depth_mm"] + buried["search_resolution_mm"])).volume()
        <= threshold
    )


def test_the_bisection_is_paid_only_on_a_failing_clause_and_is_capped():
    """The costs `_DEPTH_BISECTIONS` documents, counted.

    Raising the cap to 40 and removing the early break both survived the whole
    suite, so the docstring's numbers were prose (round-3 review of #207). Each
    step is a backend boolean, and on OCCT that is ~0.13 s.
    """
    from partspec.region import box

    class _Counting(_BoxWorld):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.calls = 0

        def intersect_volume(self, a, b):
            self.calls += 1
            return super().intersect_volume(a, b)

    def count(part, region):
        from partspec.contract import CheckSpec
        from partspec.runner import _run_geometry_check

        world = _Counting()
        spec = CheckSpec(id="r", kind="keep_out", phase="geometry", region=region, shell=1.0)
        _run_geometry_check(spec, world, part)
        return world.calls

    # Inradius 50 mm, so 24 halvings land at 3e-6 and never reach
    # `_DEPTH_TOLERANCE`: the CAP is what stops this one. At 20 mm across the
    # tolerance stops it first, and raising the cap to 40 changes nothing —
    # that mutation survived the suite.
    big = box(min=(0, 0, 0), max=(100, 100, 100))
    assert count(_box_part((-500, -500, -500), (500, 500, -10)), big) == 4, (
        "a passing clause pays the region and shell measurements and no search"
    )
    assert count(_box_part((-500, -500, -500), (500, 500, 1.5)), big) == 4 + 24, (
        "a failing one pays the cap on top, and the cap is 24"
    )
    # Fewer once the interval closes to `_DEPTH_TOLERANCE` first, which is the
    # early break: 0.15 mm needs only 18 halvings to get there.
    small = box(min=(0, 0, 0), max=(0.3, 0.3, 0.3))
    assert count(_box_part((-50, -50, -50), (50, 50, 0.1)), small) == 22


def test_the_saturation_slack_is_one_search_interval_and_not_a_margin():
    """Doubling it, multiplying it by 100 and by 1000 all passed the whole
    suite (round-5 review of #207), and an earlier draft of this test excused
    them as unreachable on a fixture that could not reach them.

    They ARE reachable. On a 400x400x8 plate a genuine partial intrusion sits
    two intervals short of the ceiling, and every multiple above one withholds
    its comparison.
    """
    from partspec.region import box
    from partspec.runner import _search_ceiling

    region = box(min=(0, 0, 0), max=(400, 400, 8))
    ceiling = _search_ceiling(region)

    def probe(z):
        got = _region_result(_box_part((-500, -500, -500), (500, 500, z)), "keep_out", region, 1.0)
        assert got.intrusion is not None
        i = got.intrusion
        return (ceiling - i["min_depth_mm"]) / i["search_resolution_mm"], i[
            "depth_limited_by_region"
        ]

    # Buried: under one interval, and flagged.
    gap, flagged = probe(500.0)
    assert gap < 1.0, f"buried sits {gap:.3f} intervals short"
    assert flagged is True

    # A genuine partial intrusion two intervals short: NOT flagged, and it is
    # what separates a slack of one interval from two, a hundred or a thousand.
    gap, flagged = probe(3.999999)
    assert gap == pytest.approx(2.0, abs=0.25), f"premise: {gap:.2f} intervals short"
    assert flagged is False, "two intervals short is a depth the part chose"

    # And further out still, so the ordinary case is nowhere near the boundary.
    for z in (3.0, 3.99, 3.9999):
        gap, flagged = probe(z)
        assert gap > 2.0 and flagged is False, f"z={z}: {gap:.1f} intervals"


def test_the_sub_resolution_and_region_limited_branches_never_both_apply():
    """`_intrusion_sentence` picks ONE branch, so if both can hold the order
    decides what the reader is told — and one order prints "at least 0 mm".

    Round 4 argued the two are disjoint and DELETED the assertions that pinned
    the order. The argument conflated two ceilings: the guard keyed on
    `inradius()` while saturation compares against `_search_ceiling()`, and for
    a region whose volume barely clears `epsilon(0.0)` those differ by a factor
    of 250 — a 200 mm x 33 nm plate passed the guard with a search ceiling of
    0.0675 nm and satisfied both branches at once (round-5 review of #207).
    They are keyed on the same ceiling now, which is what makes the claim true;
    this is the claim, tested.
    """
    from partspec.region import box
    from partspec.runner import _search_ceiling

    solid = _box_part((-500, -500, -500), (500, 500, 500))
    both = []
    # The degenerate corner the argument missed: volume just over the
    # threshold, so the search ceiling collapses while the inradius does not.
    for thickness in (1e-5, 3.3e-5, 1e-4, 1e-3):
        for scale in (1.005, 1.5, 4.0, 40.0):
            width = scale * 1e-6 / (200.0 * thickness)
            region = box(min=(0, 0, 0), max=(200.0, width, thickness))
            got = _region_result(solid, "keep_out", region, 1.0).intrusion
            if got is None:
                continue
            if got["min_depth_mm"] <= 0.0 and got["depth_limited_by_region"]:
                both.append((thickness, scale, _search_ceiling(region)))
    assert not both, f"both branches apply for {both}"

    # A region small enough to reach a zero depth reports no intrusion at all,
    # which is the mechanism: the guard fires before the branches are chosen.
    tiny = box(min=(0, 0, 0), max=(200.0, 1.005e-6 / (200.0 * 3.3e-5), 3.3e-5))
    assert _search_ceiling(tiny) < tiny.inradius() / 200, "premise: the two ceilings differ"
    assert _region_result(solid, "keep_out", tiny, 1.0).intrusion is None


def test_a_region_too_small_for_the_search_to_resolve_reports_no_depth():
    """Under a few halvings the interval is a sizeable fraction of the ceiling
    and every number the search returns overstates.

    Measured: a 3e-6 mm-thick region breached to a THIRD of its depth reported
    "the whole depth of the region", and a 1e-6 mm-thick one reported the same
    after zero bisections — the break test runs before the first halving
    (round-4 review of #207). Both now report a volume and no depth.
    """
    from partspec.region import box

    solid = _box_part((-500, -500, -500), (500, 500, 500))
    for name, part, region in (
        (
            "breached a third",
            _box_part((-500, -500, -500), (500, 500, 1e-6)),
            box(min=(0, 0, 0), max=(400, 400, 3e-6)),
        ),
        ("zero bisections", solid, box(min=(0, 0, 0), max=(400, 400, 1e-6))),
    ):
        got = _region_result(part, "keep_out", region, 1.0)
        assert got.status is Status.FAIL, name
        assert got.intrusion is None, f"{name}: the search resolved nothing, so it says nothing"
        assert "the whole depth of the region" not in (got.detail or ""), name
        assert (got.detail or "").endswith("intrudes into the keep-out region"), name

    # And the threshold is not so high that ordinary small regions lose theirs.
    fine = _region_result(solid, "keep_out", box(min=(0, 0, 0), max=(0.1, 0.1, 0.1)), 1.0)
    assert fine.intrusion is not None
    assert fine.intrusion["depth_limited_by_region"] is True

    # The constant itself. The equality below is what pins the VALUE — every
    # value from 1 to 15 survived the suite without it, and the cube block
    # cannot help there because it derives its threshold FROM the constant and
    # so is scale-invariant in it (round-6 review of #207). What the cube block
    # pins is the guard's EXPRESSION: doubling it, halving it, or making it
    # linear in the tolerance all move the boundary those two fixtures straddle.
    from partspec.runner import _DEPTH_TOLERANCE, _MIN_RESOLVING_HALVINGS, _search_ceiling

    assert _MIN_RESOLVING_HALVINGS == 4
    threshold = _DEPTH_TOLERANCE * 2**_MIN_RESOLVING_HALVINGS

    def cube_with_ceiling_near(target):
        # For a cube of side s the ceiling is s/2 - (eps/8)**(1/3)/1 ... solved
        # numerically, since the closed form is a cubic.
        lo, hi = 2 * target, 2 * target + 1.0
        for _ in range(200):
            mid = (lo + hi) / 2
            if _search_ceiling(box(min=(0, 0, 0), max=(mid, mid, mid))) < target:
                lo = mid
            else:
                hi = mid
        return hi

    just_over = cube_with_ceiling_near(threshold * 1.5)
    just_under = cube_with_ceiling_near(threshold / 1.5)
    assert _region_result(
        solid, "keep_out", box(min=(0, 0, 0), max=(just_over, just_over, just_over)), 1.0
    ).intrusion
    assert (
        _region_result(
            solid, "keep_out", box(min=(0, 0, 0), max=(just_under, just_under, just_under)), 1.0
        ).intrusion
        is None
    )


def test_a_depth_below_the_searchs_resolution_is_not_reported_as_zero():
    """ "reaching at least 0 mm past its boundary" is not a statement.

    The hair-thin film over a large face is the case that motivates reporting a
    depth at all — volume scales with contact AREA, so the film's volume can
    exceed a deep spike's. Its depth is below what 24 halvings resolve, and the
    honest answer is to say so rather than print a zero the reader will read as
    a measurement (round-2 review of #207).
    """
    from partspec.region import box
    from partspec.status import epsilon

    region = box(min=(0, 0, 0), max=(20, 20, 20))
    film = _region_result(_box_part((-50, -50, -50), (50, 50, 1e-8)), "keep_out", region, 1.0)

    assert film.intrusion is not None
    assert film.intrusion["volume_mm3"] > epsilon(0.0), (
        "premise: the film is detected — that is why it has a fail line at all"
    )
    assert film.intrusion["min_depth_mm"] == 0.0
    detail = film.detail or ""
    # The RESOLUTION, not the volume threshold beside it: the sentence is about
    # how finely the depth was searched, and printing `detected_above_mm3`
    # there — a mm3 quantity labelled mm — survived the whole suite.
    assert f"below the {film.intrusion['search_resolution_mm']:.3g} mm" in detail
    assert "this search resolves" in detail
    assert "at least 0 mm" not in detail
    assert "reaching" not in detail

    # This branch and the region-limited one are DISJOINT, so their order no
    # longer matters. Saturation needs `lo` within one interval of the ceiling
    # and a zero depth needs `lo == 0`, which together need the ceiling under
    # one interval — and `_MIN_RESOLVING_HALVINGS` puts the interval at a
    # sixteenth of the ceiling at worst. Before that guard they overlapped,
    # and the wrong order printed "at least 0 mm".
    assert film.intrusion["depth_limited_by_region"] is False


def test_a_sub_threshold_volume_earns_no_intrusion_block():
    """The check passes there, and a passing check must carry no breach.

    The entry guard and the fail-line guard are the same comparison, so
    loosening one to `> 0.0` attaches an `intrusion` object — a breach, in the
    artifact that IS the product surface — to a check that reported PASS, and
    pays 24 booleans to do it (round-2 review of #207).
    """
    from partspec.region import box
    from partspec.status import epsilon

    # A film thin enough that the intersection is under the threshold entirely.
    region = box(min=(0, 0, 0), max=(20, 20, 20))
    got = _region_result(_box_part((-50, -50, -50), (50, 50, 1e-12)), "keep_out", region, 1.0)

    assert 0.0 < 400 * 1e-12 <= epsilon(0.0), "premise: detected volume is under the threshold"
    assert got.status is Status.PASS
    assert got.intrusion is None, "no breach block on a check that passed"


def test_a_depth_the_region_itself_limits_withholds_the_comparison():
    """A region eroded to nothing cannot measure past its own half-extent, so
    the number stops describing the breach and starts describing the
    declaration.

    Measured: a rib genuinely 1.5 mm into a bore, checked against a 0.6 mm-tall
    region, reported 0.3 mm — the region's half-height — and the first version
    compared that to a 0.3939 mm facet floor and called a real interference
    discretisation (adversarial review of #207). The comparison is withheld now.

    A CYLINDER region, because a box's floor is 0.0 and `_intrusion_sentence`
    returns before the comparison either way: the box version of this test
    passed with the fix reverted (round-2 review of #207). Here the floor is
    1.5605 mm — five times the depth — so the branch is genuinely load-bearing.
    """
    from partspec.region import cylinder

    region = cylinder(d=41.0, h=0.6, at=(0, 0, -0.3), segments=8)
    assert region.facet_floor() > region.inradius(), (
        "the floor must exceed the ceiling, or this test cannot see the branch"
    )
    result = _region_result(_box_part((-50, -50, -50), (50, 50, 50)), "keep_out", region, 1.0)

    assert result.intrusion is not None
    assert result.intrusion["depth_limited_by_region"] is True
    assert result.intrusion["facet_floor_mm"] == pytest.approx(1.5605, rel=1e-3)
    # The DEPTH, not the floor: printing the floor there survived the suite,
    # and here the floor is five times the depth.
    assert f"at least {result.intrusion['min_depth_mm']:.4g} mm" in (result.detail or "")
    assert "not measurable against a region this size" in (result.detail or "")
    assert "against a perfectly circular feature" not in (result.detail or ""), (
        "a region-limited depth must not be set beside anything"
    )


def test_a_region_declared_far_from_the_origin_still_reports_a_depth():
    """The ceiling is a function of the region's EXTENTS, not its coordinates.

    `_search_ceiling` halves 60 times, which drives its probe to within
    `inradius * 2**-60` of the erosion limit. Building the eroded region there
    fails at a large offset — `min + t` and `max - t` round to the same double
    long before the extent does — so the constructor rejected its own eroded
    copy and a legal declaration died with `ContractError`, blaming the author,
    after every backend boolean had been paid (round-3 review of #207).
    """
    from partspec.region import box, cylinder
    from partspec.runner import _search_ceiling

    # 8 mm thin, 100 m from the origin: legal, and it raised.
    far = box(min=(1e5, 0, 0), max=(1e5 + 8, 400, 400))
    near = box(min=(0, 0, 0), max=(8, 400, 400))
    assert _search_ceiling(far) == pytest.approx(_search_ceiling(near), rel=1e-12)

    got = _region_result(_box_part((-1e6, -1e6, -1e6), (1e6, 1e6, 1e6)), "keep_out", far, 1.0)
    assert got.intrusion is not None
    assert got.intrusion["depth_limited_by_region"] is True

    # Both kinds, and both terms of the cylinder: `d` sets the inradius here,
    # so a ceiling that erodes only `h` would still look plausible.
    wide = cylinder(d=41.0, h=100.0, at=(0, 0, -50))
    assert _search_ceiling(wide) == pytest.approx(20.4998, abs=1e-3)
    assert _search_ceiling(wide) < wide.inradius() == 20.5
    tall = cylinder(d=100.0, h=41.0, at=(0, 0, -20.5))
    assert _search_ceiling(tall) == pytest.approx(20.4998, abs=1e-3)
    assert _search_ceiling(tall) < tall.inradius() == 20.5


def test_a_region_too_far_from_the_origin_for_the_search_reports_no_depth():
    """No depth, and above all no `ContractError` blaming the author (#245).

    The residue of the case above, five orders of magnitude further out. It
    takes BOTH conditions, which is why #245's own reproduction understates it:

    * The loop brackets `[0, inradius()]` and halves `_DEPTH_BISECTIONS` times,
      but `hi` collapses toward `_search_ceiling` because the predicate is False
      above it. So the deepest probe is `ceiling - inradius * 2**-24`, and only
      a region whose ceiling sits AT its inradius — an elongated one, where the
      erosion collapses one axis and not three — probes near the degeneracy at
      all. The 8x8x8 case stops 1e-2 mm short of it and is fine at any offset.
    * The coordinate's ulp then has to exceed the extent left at that probe,
      `inradius * 2**-23`. Measured: 8x400x400 is fine at x=1e9 and raises at
      x=1e10, an ulp of 1.9e-6 against an extent of 4.8e-7.

    Bounding the probe at the ceiling — the other remedy #245 offers — is what
    the elongated case defeats: its ceiling IS its inradius to within 3e-12.

    `None` is the honest answer rather than a depth of zero: the erosion is not
    representable at these coordinates, which is what this function's other
    `None` branches already mean.
    """
    from partspec.region import box

    surround = _box_part((-1e12, -1e12, -1e12), (1e12, 1e12, 1e12))

    # Elongated: the ceiling sits at the inradius, so the search probes into
    # the degeneracy. This raised.
    far = box(min=(1e10, 0.0, 0.0), max=(1e10 + 8.0, 400.0, 400.0))
    got = _region_result(surround, "keep_out", far, 1.0)
    assert got.status is Status.FAIL  # material fills it; that much is still decided
    assert got.intrusion is None, got.intrusion

    # Equilateral at the same offset still reports its depth — the fix must not
    # buy safety by going blind on every distant region.
    equilateral = box(min=(1e10, 0.0, 0.0), max=(1e10 + 8.0, 8.0, 8.0))
    got = _region_result(surround, "keep_out", equilateral, 1.0)
    assert got.intrusion is not None
    assert got.intrusion["min_depth_mm"] == pytest.approx(3.995, abs=1e-3)

    # And the elongated region is fine one order of magnitude in, which is what
    # makes this the residue of the case above rather than a wider regression.
    near = box(min=(1e9, 0.0, 0.0), max=(1e9 + 8.0, 400.0, 400.0))
    got = _region_result(surround, "keep_out", near, 1.0)
    assert got.intrusion is not None
    assert got.intrusion["min_depth_mm"] == pytest.approx(4.0, abs=1e-5)


def test_eroded_volume_refuses_a_non_finite_offset_as_expand_does():
    """`max(0.0, nan)` is `0.0` in Python, so a NaN offset reported a volume of
    zero — an answer — where `expand(-nan)` raises. It was the only region entry
    point that accepted a non-finite argument (#245, round-4 review of #207).

    Not reachable from the search, whose `mid` is a midpoint of two finite
    bounds. Pinned because a public method that quietly grades `nan` as "erodes
    to nothing" is the silent-wrong-answer channel, in the one place the codebase
    already decided against it one method over.
    """
    from partspec.region import box, cylinder
    from partspec.status import ContractError

    for region in (
        box(min=(0, 0, 0), max=(8, 400, 400)),
        cylinder(d=41.0, h=18.0, at=(0, 0, -5)),
    ):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ContractError, match="not a number"):
                region.eroded_volume(bad)


def test_eroded_volume_is_expand_then_volume_without_the_coordinates():
    """Its whole contract, and it was unpinned: dropping the `sec(pi/n)` factor
    from the cylinder form put it 0.24% out and survived the suite (round-4
    review of #207).
    """
    from partspec.region import box, cylinder

    for region in (
        box(min=(0, 0, 0), max=(8, 400, 400)),
        box(min=(-3, -3, -3), max=(3, 9, 21)),
        cylinder(d=41.0, h=18.0, at=(0, 0, -5)),
        cylinder(d=6.0, h=60.0, at=(1, 2, 3), axis="x", segments=8),
        cylinder(d=60.0, h=6.0, at=(0, 0, 0), axis="y", segments=200),
    ):
        for t in (-2.0, 0.0, region.inradius() / 3, region.inradius() * 0.999):
            assert region.eroded_volume(t) == pytest.approx(region.expand(-t).volume(), rel=1e-9), (
                f"{region} at t={t}"
            )

        # Past the inradius there is nothing left, and `expand(-t)` refuses to
        # say so rather than saying zero. Zero, not the positive number a
        # product of two negative extents gives — dropping either clamp
        # survives every other assertion here, because the search never probes
        # past its own ceiling.
        for t in (region.inradius(), region.inradius() * 1.5, region.inradius() * 40):
            assert region.eroded_volume(t) == 0.0, f"{region} at t={t}"


def test_the_saturation_ceiling_is_the_searchs_own_limit_not_the_inradius():
    """What the flag compares against, pinned — three mutations survived without it.

    The erosion stops when the region holds less than `epsilon(0.0)` mm3, and a
    region eroded near its inradius holds almost nothing WHATEVER the part
    does. So the deepest reportable depth is set by the region's shape, not by
    its inradius, and the shortfall between them is not a fixed fraction: an
    equilateral region collapses all three dimensions at once (~5e-3 mm short),
    an elongated one collapses fewer (3e-12 mm short for the plate below, and
    3e-4 for a thin pin). Judging `lo` against
    `inradius * (1 - 1e-3)` therefore made the flag a discontinuous function of
    the DECLARATION, and judging it against `hi` missed the buried case
    entirely (round-2 review of #207).
    """
    from partspec.region import box
    from partspec.runner import _search_ceiling

    solid = _box_part((-500, -500, -500), (500, 500, 500))

    # The shortfall is not a fixed fraction of the inradius: two shapes with
    # the SAME inradius, four million times apart.
    cube = box(min=(0, 0, 0), max=(8, 8, 8))
    slab = box(min=(0, 0, 0), max=(400, 400, 8))
    assert cube.inradius() == slab.inradius() == 4.0
    assert cube.inradius() - _search_ceiling(cube) == pytest.approx(5e-3, rel=0.02)
    assert slab.inradius() - _search_ceiling(slab) == pytest.approx(3.25e-12, rel=0.05)

    # Every one of these is FULLY BURIED in solid material — a total breach —
    # so every one must be flagged. Four of the six were not.
    for name, region in (
        ("cube 4", box(min=(0, 0, 0), max=(4, 4, 4))),
        ("cube 8", box(min=(0, 0, 0), max=(8, 8, 8))),
        ("box 8x8x7.99", box(min=(0, 0, 0), max=(8, 8, 7.99))),
        ("cube 20", box(min=(0, 0, 0), max=(20, 20, 20))),
        ("nut pocket 7", box(min=(0, 0, 0), max=(7, 7, 7))),
        # Above 33.6 mm across, the search's own resolution exceeds
        # `_DEPTH_TOLERANCE`, so a fixed 1e-6 slack stops firing. Every fixture
        # above is under that, which is how the regression got through: most
        # buried cubes over 34 mm went unflagged — 51% of integer sides in
        # 34..100, 88% in 34..1000 — non-monotonically, 50 fired,
        # 60 did not, 100 did, 120 did not (round-3 review of #207).
        ("cube 50", box(min=(0, 0, 0), max=(50, 50, 50))),
        ("cube 60", box(min=(0, 0, 0), max=(60, 60, 60))),
        ("cube 100", box(min=(0, 0, 0), max=(100, 100, 100))),
        ("cube 120", box(min=(0, 0, 0), max=(120, 120, 120))),
        ("cube 250", box(min=(0, 0, 0), max=(250, 250, 250))),
    ):
        got = _region_result(solid, "keep_out", region, 1.0)
        assert got.intrusion is not None, name
        assert got.intrusion["depth_limited_by_region"] is True, (
            f"{name}: buried in solid material, so the depth is the region's, not the part's"
        )
        assert got.intrusion["min_depth_mm"] == pytest.approx(
            _search_ceiling(region), abs=got.intrusion["search_resolution_mm"]
        ), f"{name}: the search returns its own ceiling when nothing stops it"

    # The pair that made the old rule discontinuous: the same material and the
    # same total breach, 0.01 mm apart in the DECLARATION, disagreeing.
    same = [
        _region_result(solid, "keep_out", box(min=(0, 0, 0), max=(8, 8, h)), 1.0).intrusion
        for h in (8.0, 7.99)
    ]
    assert all(i is not None for i in same)
    assert {i["depth_limited_by_region"] for i in same if i is not None} == {True}

    # A genuine intrusion that stops just SHORT of the ceiling is not flagged.
    # The slack is the search tolerance, not a margin: at 0.1 mm this material,
    # 0.045 mm short of the deepest measurable depth, reads as region-limited
    # and loses its comparison. That mutation survived the whole suite.
    near = _region_result(
        _box_part((-50, -50, -50), (50, 50, 9.95)),
        "keep_out",
        box(min=(0, 0, 0), max=(20, 20, 20)),
        1.0,
    ).intrusion
    assert near is not None
    # 1e-3, not the search resolution: the sliver left at this depth falls
    # under the volume threshold slightly early, which is exactly why the
    # number is reported as a lower bound.
    assert near["min_depth_mm"] == pytest.approx(9.95, abs=1e-3)
    assert near["min_depth_mm"] <= 9.95
    assert _search_ceiling(box(min=(0, 0, 0), max=(20, 20, 20))) - near["min_depth_mm"] < 0.05
    assert near["depth_limited_by_region"] is False, (
        "0.045 mm short of the ceiling is a real depth the part chose, not the region running out"
    )

    # And a genuine partial intrusion is still not flagged, or the flag would
    # withhold the comparison on every failing check.
    # A box has no faceting, so its line carries no scale clause. The guard is
    # `floor <= 0.0`; at `< 0.0` every box fail line gains "stands 0 mm proud
    # of the circle it declares", about a region that declares no circle.
    plain_box = _region_result(
        _box_part((-500, -500, -500), (500, 500, 1.5)),
        "keep_out",
        box(min=(0, 0, 0), max=(20, 20, 20)),
        1.0,
    )
    assert plain_box.intrusion is not None
    assert plain_box.intrusion["facet_floor_mm"] == 0.0
    assert "against a perfectly circular feature" not in (plain_box.detail or "")

    real = _region_result(
        _box_part((-500, -500, -500), (50, 50, 1.5)),
        "keep_out",
        box(min=(0, 0, 0), max=(20, 20, 20)),
        1.0,
    ).intrusion
    assert real is not None
    assert real["min_depth_mm"] == pytest.approx(1.5, abs=1e-5)
    assert real["depth_limited_by_region"] is False
