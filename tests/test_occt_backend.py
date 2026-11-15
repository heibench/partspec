"""The OCCT backend, and the claim that one implementation serves both engines.

Fixtures are built in-process with build123d and CadQuery rather than loaded from
files, so these run wherever the occt extra is installed and assert against
closed-form geometry.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support import measured, refused

from partspec.backend import BuildError, Tier, Unsupported
from partspec.backends.occt import OcctBackend
from partspec.engines.pycad import PyCADSource, adopt, build

bd = pytest.importorskip("build123d", reason="occt extra not installed")


@pytest.fixture
def backend() -> OcctBackend:
    return OcctBackend("build123d")


# --------------------------------------------------------------------------
# adoption — the D3 claim
# --------------------------------------------------------------------------


def test_build123d_shape_is_adopted():
    adopted = adopt(bd.Box(10, 20, 30))
    assert not isinstance(adopted, BuildError)
    assert adopted.volume == pytest.approx(6000.0)


def test_an_empty_compound_is_a_build_error_not_an_assert(tmp_path):
    """#128: build123d's `.wrapped` asserts on `Compound()` with no children,
    and the AssertionError escaped adopt as a traceback with empty stdout —
    for measure and render alike, both of which promise an identity artifact
    on any failure after the target resolves."""
    result = adopt(bd.Compound())
    assert isinstance(result, BuildError)
    assert "no geometry" in result.message

    # Through the verb: the artifact, never the shrug (the #47/#103 shape).
    import json

    from partspec.cli import main

    (tmp_path / "m.py").write_text(
        "from build123d import Compound\n\n\ndef make_part():\n    return Compound()\n"
    )
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["measure", f"{tmp_path / 'spec.py'}:make"])
    assert code == 4
    doc = json.loads(out.getvalue())
    assert doc["part"]["id"] == "subject"
    assert "no geometry" in doc["error"]


def test_a_none_handle_is_named_not_misdescribed():
    """PR #133 review, F4: a wrapper whose .wrapped is None (CadQuery can
    produce one) must get the no-geometry message, not the misleading
    'not a build123d or CadQuery shape'."""

    class _Hollow:
        wrapped = None

    result = adopt(_Hollow())
    assert isinstance(result, BuildError)
    assert "no underlying handle" in result.message


def test_cadquery_shape_is_adopted_losslessly():
    """The whole basis for 'two backends, not three': a CadQuery result is a
    handle rewrap away from a build123d one, with no conversion."""
    cq = pytest.importorskip("cadquery", reason="cadquery extra not installed")
    adopted = adopt(cq.Workplane("XY").box(10, 20, 30))
    assert not isinstance(adopted, BuildError)
    assert adopted.volume == pytest.approx(6000.0)
    assert len(adopted.faces()) == 6, "real topology, not triangles"


def test_cadquery_multi_solid_adopts_as_a_compound():
    """Replaced, not adjusted. The old fixture used the default `combine=True`,
    so its stack was already a single Compound and it stayed green against the
    bug below. It has to be a stack of *separate* Solids to test anything."""
    cq = pytest.importorskip("cadquery", reason="cadquery extra not installed")
    w = cq.Workplane("XY").rect(20, 20, forConstruction=True).vertices().box(5, 5, 5, combine=False)
    assert len(w.vals()) == 4, "premise: four separate solids on the stack"

    adopted = adopt(w)
    assert not isinstance(adopted, BuildError)
    assert len(adopted.solids()) == 4, "`.val()` kept one and discarded three"
    assert adopted.volume == pytest.approx(500.0)


def test_a_single_body_workplane_is_unchanged():
    """The default combine=True path must not grow a Compound wrapper."""
    cq = pytest.importorskip("cadquery", reason="cadquery extra not installed")
    adopted = adopt(cq.Workplane("XY").box(10, 10, 10))
    assert not isinstance(adopted, BuildError)
    assert adopted.volume == pytest.approx(1000.0)
    assert len(adopted.solids()) == 1


def test_wrong_wrapper_would_have_been_worse_than_failing():
    """Guards the reason adoption dispatches on ShapeType rather than using
    Shape.cast (which returns None) or a single wrapper: Compound(solid)
    constructs happily and reports volume 0."""
    solid = bd.Box(10, 20, 30).solids()[0]
    assert bd.Compound(solid.wrapped).volume == 0, "premise: the wrong wrapper lies"

    adopted = adopt(solid)
    assert not isinstance(adopted, BuildError)
    assert adopted.volume == pytest.approx(6000.0), "adoption picks the right one"


def test_is_valid_uses_the_property_not_the_method(backend: OcctBackend):
    """build123d exposes `is_valid` as a property; CadQuery as `isValid()`.
    Calling it as a method here raised `TypeError: 'bool' object is not
    callable` — the exact divergence SPEC-backend section 4 names as the reason
    the adopt shim exists."""
    assert backend.is_valid(bd.Box(1, 1, 1)).value is True


def test_a_non_shape_is_a_build_error():
    result = adopt("not a shape")
    assert isinstance(result, BuildError)
    assert "not a build123d or CadQuery shape" in result.message


# --------------------------------------------------------------------------
# measurement
# --------------------------------------------------------------------------


def test_closed_form_measurements(backend: OcctBackend):
    box = bd.Box(10, 20, 30)
    assert measured(backend.volume(box)).value == pytest.approx(6000.0)
    assert measured(backend.area(box)).value == pytest.approx(2 * (200 + 600 + 300))
    assert measured(backend.bbox(box)).value == pytest.approx((10.0, 20.0, 30.0))
    com = measured(backend.center_of_mass(box))
    assert com.value == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    assert measured(backend.watertight(box)).value is True
    assert backend.solid_count(box).value == 1


def test_bbox_is_translation_invariant(backend: OcctBackend):
    """`envelope` bounds EXTENTS, not corners (SPEC-contract.md 4.2.3).

    §4.2.3 is about the measurements both tiers carry, and states the
    invariance without qualifying it by tier, so both tiers pin it — the mesh
    tier's copy is `test_bbox_is_translation_invariant` there. The claim is
    what the whole envelope-versus-`region.box` trap rests on: a bound written
    from a part's far CORNER is satisfied by parts far larger than the one it
    was written for, and the position never reaches the measurement, so nothing
    downstream can catch it.

    `test_closed_form_measurements` above measures one box at one position,
    which cannot separate an extent from a quantity that coincides with it at
    the origin. One size at two positions can.
    """
    at_origin = bd.Box(10, 20, 30)
    displaced = at_origin.moved(bd.Location((100.0, 200.0, 300.0)))

    assert measured(backend.bbox(at_origin)).value == pytest.approx((10.0, 20.0, 30.0))
    assert measured(backend.bbox(displaced)).value == pytest.approx(
        measured(backend.bbox(at_origin)).value
    )


def test_a_sealed_cavity_is_one_solid_with_one_void(backend: OcctBackend):
    """This tier was always right about the solid count — a block enclosing a
    sealed void is 1 solid and 2 shells. What was missing is that the void had
    no name, so a contract could not say "one block, one cavity" and the mesh
    tier's miscount had nothing to be checked against.

    The mesh tier reaches the same three numbers from triangle orientation; see
    `test_a_sealed_cavity_is_one_solid_not_two` there, and `evals/BASELINE.md`
    for the agent-loop failure that made this load-bearing.
    """
    block = bd.Box(20, 20, 20) - bd.Box(10, 10, 10)
    assert backend.solid_count(block).value == 1
    assert measured(backend.cavities(block)).value == 1
    assert measured(backend.genus(block)).value == 0
    assert measured(backend.volume(block)).value == pytest.approx(7000.0)


def test_a_plain_solid_has_no_cavities(backend: OcctBackend):
    assert measured(backend.cavities(bd.Box(10, 10, 10))).value == 0


# Every case is a `lambda` that constructs its shapes fresh inside the
# `Compound(...)` call, and that is load-bearing, not clutter (#337).
# `Compound(children=[...])` REPARENTS what it is given: hand the same object to
# a second compound and the first is left holding nothing, silently. Measured,
# with one Box shared as a `children=` entry by two cases built at collection
# time:
#
#     plain solid + stray sheet   solids 1 | shells 2   before the second exists
#     plain solid + stray sheet   solids 0 | shells 1   after
#
# The row still wants `cavities == 0`, and an emptied compound answers 0 — green,
# and measuring nothing. The `lambda` is what makes sharing survivable: each case
# is built and measured before the next constructor can claim its children. Two
# things that are safe on their own and are not the property to preserve: taking
# the `lambda`s off while every case still builds its own shapes, and hoisting a
# Box that is a `children=` entry in one case only. Both were executed and the
# table stayed correct. Keep the shapes inside the builders.
@pytest.mark.parametrize(
    ("name", "builder", "cavities"),
    [
        ("an open shell alone", lambda: bd.Shell(bd.Box(10, 10, 10).faces()[1:]), 0),
        (
            "a plain solid beside a stray sheet body",
            lambda: bd.Compound(
                children=[
                    bd.Box(10, 10, 10),
                    bd.Pos(60, 0, 0) * bd.Shell(bd.Box(10, 10, 10).faces()[1:]),
                ]
            ),
            0,
        ),
        (
            "a cavity solid beside a stray sheet body",
            lambda: bd.Compound(
                children=[
                    bd.Box(20, 20, 20) - bd.Box(10, 10, 10),
                    bd.Pos(60, 0, 0) * bd.Shell(bd.Box(10, 10, 10).faces()[1:]),
                ]
            ),
            1,
        ),
        (
            "two cavity solids",
            lambda: bd.Compound(
                children=[
                    bd.Box(20, 20, 20) - bd.Box(10, 10, 10),
                    bd.Pos(60, 0, 0) * (bd.Box(20, 20, 20) - bd.Box(10, 10, 10)),
                ]
            ),
            2,
        ),
    ],
)
def test_a_stray_shell_is_not_a_sealed_void(
    backend: OcctBackend, name: str, builder, cavities: int
):
    """The deslop audit's headline defect, and the deeper version its own
    review found. `cavities` was a global `shells - solids`, so an OPEN
    shell answered 1 - 0 = 1 and the tool certified `cavities = 1, exact`,
    `verdict: pass`, exit 0 on a shape with no material at all.

    The first fix gated on `not a.solids()` and was still wrong: the formula
    assumes every shell belongs to a solid, and nothing enforces that. One
    plain block beside a stray sheet body is 1 solid and 2 shells, so the
    same false pass came straight back through the CLI on a part that does
    build. Counting each solid's own shells minus its outer one is right by
    construction for every arrangement here, and needs no precondition.
    """
    shape = builder()
    assert measured(backend.cavities(shape)).value == cavities, name


def test_the_two_tiers_agree_about_a_shape_with_no_material(backend: OcctBackend):
    """The other half of the defect, which the first fix moved rather than
    closed: OCCT refused where the mesh tier answered 0, so one contract
    still adjudicated two ways depending on the engine. Zero is the honest
    answer — a shape with no solid encloses no sealed void — and both tiers
    give it now."""
    trimesh = pytest.importorskip("trimesh", reason="mesh extra not installed")
    import tempfile
    from pathlib import Path

    from partspec.backends.mesh import MeshBackend

    shell = bd.Shell(bd.Box(10, 10, 10).faces()[1:])
    assert measured(backend.solid_count(shell)).value == 0, "the fixture really has no solid"
    assert measured(backend.cavities(shell)).value == 0

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "shell.stl"
        bd.export_stl(shell, str(path))
        mesh = trimesh.load(str(path))
        assert measured(MeshBackend().cavities(mesh)).value == 0, "and the mesh tier agrees"


def test_a_cut_that_consumes_the_part_does_not_build():
    """`Box(s) - Box(2s)` is an ordinary slip and yields a non-null but empty
    Compound, which `IsNull()` does not catch. It used to be adopted as a
    legitimate artifact and then measured: bbox (0,0,0), area 0.0, watertight
    False, all exact, so a contract asserting those three passed green on a part
    that does not exist."""
    result = adopt(bd.Box(10, 10, 10) - bd.Box(20, 20, 20))
    assert isinstance(result, BuildError)
    assert "no geometry" in result.message


def test_geometry_without_faces_is_still_measurable(backend: OcctBackend):
    """The gate is "no vertices", not "no faces". A wire has no faces and no
    solids, and its bounding box and area are honest answers about it — refusing
    there would be the over-refusal D17 part 2 forbids."""
    wire = bd.Wire.make_circle(5)
    # `adopt` never returns None on any path, and calling it twice measured
    # nothing the first call did not.
    assert not isinstance(adopt(wire), BuildError)
    assert measured(backend.bbox(wire)).value == pytest.approx((10.0, 10.0, 0.0))
    assert measured(backend.area(wire)).value == pytest.approx(0.0)
    assert measured(backend.watertight(wire)).value is False


def test_everything_on_this_tier_is_exact(backend: OcctBackend):
    """No tessellation anywhere, so nothing carries an error bound."""
    box = bd.Box(10, 20, 30)
    for measure in (backend.volume, backend.area, backend.bbox, backend.center_of_mass):
        result = measured(measure(box))
        assert result.exact and result.bounds is None


def test_curved_geometry_is_analytic_not_faceted(backend: OcctBackend):
    """The tier difference in one assertion: OCCT gives pi*r^2*h exactly, where
    the mesh tier would give an inscribed prism."""
    import math

    cyl = bd.Cylinder(radius=5, height=10)
    volume = measured(backend.volume(cyl))
    assert volume.value == pytest.approx(math.pi * 25 * 10, rel=1e-9)
    assert volume.exact


# --------------------------------------------------------------------------
# topology — the reason this tier exists
# --------------------------------------------------------------------------


def test_topology_counts_are_answered_here(backend: OcctBackend):
    """Refused on mesh, answered here. That asymmetry is the point of tiers."""
    result = backend.topology_counts(bd.Box(10, 20, 30))
    assert not isinstance(result, Unsupported)
    assert result.value == (6, 12, 8), "faces, edges, vertices of a box"
    assert result.axes == ("faces", "edges", "vertices")


def test_a_cylinder_has_analytic_faces_not_facets(backend: OcctBackend):
    """3 faces (top, bottom, one cylindrical), never $fn of them."""
    assert backend.topology_counts(bd.Cylinder(radius=5, height=10)).value[0] == 3


def test_a_topology_contract_is_answered_on_this_tier(tmp_path):
    """The counterpart of `test_a_tier_that_cannot_answer_says_which_one_can`:
    the identical check that reports `unsupported` on OpenSCAD passes here.

    That asymmetry, reachable from one contract, is the whole claim of having
    tiers — the check means the same thing on both, and says so where it cannot
    be evaluated rather than inventing an answer.
    """
    from partspec import Part, Status, Verdict, build123d
    from partspec.runner import run

    model = tmp_path / "m.py"
    model.write_text("import build123d as bd\ndef make_part():\n    return bd.Box(10, 20, 30)\n")

    p = Part("topo-box", build123d(model))
    p.topology(faces=6, edges=12, vertices=8)

    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "topology")
    assert check.status is Status.PASS
    assert check.measurement is not None
    assert check.measurement.value == (6, 12, 8)
    assert report.verdict is Verdict.PASS


def test_a_wrong_topology_claim_fails(tmp_path):
    from partspec import Part, Status, build123d
    from partspec.runner import run

    model = tmp_path / "m.py"
    model.write_text("import build123d as bd\ndef make_part():\n    return bd.Box(10, 20, 30)\n")

    p = Part("topo-box", build123d(model)).topology(faces=7)
    report = run(p, out_dir=tmp_path)
    assert next(c for c in report.checks if c.id == "topology").status is Status.FAIL


# --------------------------------------------------------------------------
# genus — where the naive formula is wrong
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "shape", "expected"),
    [
        ("box", bd.Box(30, 20, 10), 0),
        ("one through-hole", bd.Box(30, 20, 10) - bd.Cylinder(3, 20), 1),
        (
            "two through-holes",
            bd.Box(30, 20, 10)
            - bd.Cylinder(2, 20).moved(bd.Location((8, 0, 0)))
            - bd.Cylinder(2, 20).moved(bd.Location((-8, 0, 0))),
            2,
        ),
        ("blind hole", bd.Box(30, 20, 10) - bd.Cylinder(3, 5).moved(bd.Location((0, 0, 3))), 0),
        ("tube", bd.Cylinder(10, 5) - bd.Cylinder(5, 20), 1),
    ],
)
def test_genus_via_euler_poincare(backend: OcctBackend, name, shape, expected):
    """The naive V - E + F is wrong on a BREP and quietly so.

    OCCT faces carry inner wires, so a face with a hole is an annulus rather
    than a disc. Measured, the naive form calls a through-hole genus 0 and a
    *blind* hole genus -1. Including the wire count fixes both.
    """
    result = backend.genus(shape)
    assert not isinstance(result, Unsupported), result
    assert result.value == expected, name


def test_the_naive_euler_formula_would_be_wrong():
    """Pins the premise of the test above, so a future simplification fails."""
    part = bd.Box(30, 20, 10) - bd.Cylinder(3, 20)
    v, e, f = len(part.vertices()), len(part.edges()), len(part.faces())
    naive_genus = (2 - (v - e + f)) // 2
    assert naive_genus == 0, "the naive formula reports a through-hole as genus 0"


def test_genus_is_refused_for_multi_body_parts(backend: OcctBackend):
    two = bd.Box(5, 5, 5) + bd.Box(5, 5, 5).moved(bd.Location((20, 0, 0)))
    assert "per body" in refused(backend.genus(two)).reason


def _bored_cube():
    """A 20 mm cube bored 6 mm through — one closed body, honestly genus 1."""
    return bd.Box(20, 20, 20) - bd.Cylinder(radius=3, height=40)


def _cube_beside_a_shell_over_its_own_faces():
    """The stray that moves ONLY the shell count: a Shell built over the
    solid's own faces shares their TShapes, so V, E, F and W are unmoved and
    `shells` goes 1 -> 2. Measured, this is the member of the class that
    inflates genus *upward* — the old code reported 2 on a part with one hole,
    with `watertight` true and `cavities` 0."""
    part = _bored_cube()
    return bd.Compound(children=[part, bd.Shell(part.faces())])


def _cube_beside_a_wire_over_its_own_edges():
    """The stray that moves ONLY the wire count. The characteristic goes odd
    and the old code's `int()` truncated the half — `int(1.5)`, which happens
    to land on the honest 1. A rounded corruption is still a corruption: it is
    the same arithmetic that reported 0 and 2 on the rows above."""
    part = _bored_cube()
    top = part.faces().sort_by(bd.Axis.Z)[-1]
    return bd.Compound(children=[part, bd.Wire(top.edges().filter_by(bd.GeomType.LINE))])


# Each case builds its shapes fresh inside the `Compound(...)` call, behind a
# `lambda` — the discipline #337 records, for the reason given at the `cavities`
# table above.
@pytest.mark.parametrize(
    ("name", "builder", "stray", "watertight"),
    [
        (
            "a disjoint face",
            lambda: bd.Compound(
                children=[_bored_cube(), bd.Pos(60, 0, 0) * bd.Rectangle(10, 10).face()]
            ),
            "4 vertices, 4 edges, 1 wire, 1 face",
            False,
        ),
        (
            "a bodiless edge",
            lambda: bd.Compound(
                children=[_bored_cube(), bd.Pos(60, 0, 0) * bd.Line((0, 0, 0), (10, 0, 0)).edge()]
            ),
            "1 edge",
            False,
        ),
        (
            "a lone vertex",
            lambda: bd.Compound(children=[_bored_cube(), bd.Vertex(60, 0, 0)]),
            "1 vertex",
            True,
        ),
        (
            "a shell over the solid's own faces",
            _cube_beside_a_shell_over_its_own_faces,
            "1 shell",
            True,
        ),
        (
            "a wire over the solid's own edges",
            _cube_beside_a_wire_over_its_own_edges,
            "1 wire",
            False,
        ),
    ],
)
def test_genus_is_refused_when_the_shape_carries_more_than_its_one_solid(
    backend: OcctBackend, name, builder, stray, watertight
):
    """#334: the solid count is not the precondition the formula needs.

    Anything that is not itself a solid rides beside one without moving
    `len(a.solids())`, and was then summed into the Euler-Poincare
    characteristic anyway. Measured on the bored cube — genus 1 — the five
    strays below reported `0`, `0`, `0`, `2` and a truncated `int(1.5)`, every
    one of them `exact`.

    `watertight` cannot stand in for the guard: two of the five leave
    `is_manifold` true, which is why the precondition is "one solid and
    nothing else" and not "one solid and it is manifold".

    The expected fragment is the refusal's whole enumeration for the first row
    and the entity in question for the rest — a guard that stopped counting one
    of the five kinds would still refuse some of these, and would stop naming
    what it found.
    """
    shape = builder()
    assert measured(backend.genus(_bored_cube())).value == 1, "the solid alone is genus 1"
    assert backend.solid_count(shape).value == 1, name
    assert measured(backend.watertight(shape)).value is watertight, name

    reason = refused(backend.genus(shape)).reason
    assert "one closed body" in reason, name
    assert stray in reason, name


@pytest.mark.parametrize(
    ("name", "builder", "boundary"),
    [
        ("a shell missing one face", lambda: bd.Solid(bd.Shell(bd.Box(20, 20, 20).faces()[1:])), 4),
        (
            "a shell missing two opposite faces",
            lambda: bd.Solid(
                bd.Shell(
                    bd.ShapeList(f for f in bd.Box(20, 20, 20).faces() if abs(f.center().Z) < 9)
                )
            ),
            8,
        ),
    ],
)
def test_genus_is_refused_for_a_solid_built_over_an_open_shell(
    backend: OcctBackend, name, builder, boundary
):
    """One solid, nothing beside it — and no closed body to have a genus.

    `Solid(Shell(...))` over an open shell is two lines of public API, and a
    STEP import reaches the same state. The stray-geometry guard cannot see it:
    the solid IS the whole shape. Measured, the formula answered 0 for the
    first and 1 for the second, both `exact`, on a shape with no genus at all.

    The second is why an integrality test is not enough on its own: its
    characteristic is even (V - E + 2F - W = 0), so the genus comes out a whole
    number and nothing about the arithmetic looks wrong. Counting the edges that
    are not bounded by exactly two faces catches both, and says how many, as the
    mesh tier does.
    """
    reason = refused(backend.genus(builder())).reason
    assert "one closed body" in reason, name
    assert f"it is not closed: {boundary} edge(s) not bounded by exactly two faces" in reason, name


def _non_manifold_solid():
    """One solid whose interface edges are bounded by FOUR faces.

    Two stacked boxes sewn WITH the internal partition kept. The default
    `SetNonManifoldMode(False)` yields a compound of shells and cannot reach
    this; `True` yields one shell, and the solid over it is 2000 mm3 with four
    such edges and no boundary edges at all. It reported `genus -1, exact`
    before the closedness guard counted uses `!= 2` rather than `< 2`.
    """
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeSolid,  # type: ignore[attr-defined]
        BRepBuilderAPI_Sewing,  # type: ignore[attr-defined]
    )
    from OCP.TopoDS import TopoDS

    sew = BRepBuilderAPI_Sewing(1e-6)
    sew.SetNonManifoldMode(True)
    for box in (bd.Box(10, 10, 10), bd.Box(10, 10, 10).moved(bd.Location((0, 0, 10)))):
        for face in box.faces():
            sew.Add(face.wrapped)
    sew.Perform()
    return bd.Solid(BRepBuilderAPI_MakeSolid(TopoDS.Shell(sew.SewedShape())).Solid())  # pyright: ignore[reportAttributeAccessIssue]


def _one_shell_holding_two_disjoint_boxes():
    """One solid, one shell, two boxes 40 mm apart inside it.

    Every edge is bounded by exactly two faces and nothing sits beside the
    solid, so both preconditions above are satisfied and the arithmetic still
    corrupts: the characteristic of two components is twice one component's,
    while the shell count says one. `bd.Shell` refuses the input (TypeError),
    so it takes `BRep_Builder` -- but a STEP import is under no such
    obligation.
    """
    from OCP.BRep import BRep_Builder  # type: ignore[attr-defined]
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid  # type: ignore[attr-defined]
    from OCP.TopoDS import TopoDS_Shell  # type: ignore[attr-defined]

    shell = TopoDS_Shell()
    builder = BRep_Builder()
    builder.MakeShell(shell)
    for box in (bd.Box(10, 10, 10), bd.Box(10, 10, 10).moved(bd.Location((40, 0, 0)))):
        for face in box.faces():
            builder.Add(shell, face.wrapped)
    return bd.Solid(BRepBuilderAPI_MakeSolid(shell).Solid())


def test_genus_is_refused_for_a_solid_with_a_non_manifold_edge(backend: OcctBackend):
    """The other half of "not bounded by exactly two faces" — used MORE than
    twice, not fewer. One solid, 2000 mm3, no boundary edge anywhere."""
    solid = _non_manifold_solid()
    assert backend.solid_count(solid).value == 1
    assert measured(backend.volume(solid)).value == pytest.approx(2000.0)

    reason = refused(backend.genus(solid)).reason
    assert "one closed body" in reason
    assert "it is not closed: 4 edge(s) not bounded by exactly two faces" in reason


def test_genus_is_refused_when_one_shell_encloses_two_bodies(backend: OcctBackend):
    """Both preconditions pass and the answer is still not a genus.

    Nothing sits beside the solid and every edge is bounded by exactly two
    faces — the shape is two closed boxes sharing one shell. The formula
    reports the shells' genera SUMMED, so a legitimate closed body can never
    reach a negative number; this one measured `-1, exact` at 2000 mm3.
    """
    solid = _one_shell_holding_two_disjoint_boxes()
    assert backend.solid_count(solid).value == 1
    assert measured(backend.volume(solid)).value == pytest.approx(2000.0)

    reason = refused(backend.genus(solid)).reason
    assert "one closed body" in reason
    assert "the Euler-Poincare formula gives -1" in reason


@pytest.mark.parametrize(
    ("name", "shape"),
    [
        ("sphere", bd.Sphere(10)),
        ("cone", bd.Cone(10, 0, 20)),
        ("filleted box", bd.fillet(bd.Box(20, 20, 20).edges(), 2)),
    ],
)
def test_genus_answers_for_closed_bodies_that_is_manifold_calls_open(
    backend: OcctBackend, name, shape
):
    """Why the closedness guard is not `is_manifold`, and what it does instead.

    `is_manifold` applies the same "used by exactly two faces" rule; it differs
    only in which edges it skips as degenerate, and its test never fires on a
    solid's boundary.
    Measured, a sphere carries 2 degenerate edges, a cone 1 and a filleted box
    8, each used once, so it reads False on all three — every one of them
    closed and genus 0. Building the precondition on it would have refused a
    sphere.

    The uses-versus-distinct-faces distinction is the other half and is pinned
    by a mutant, not by this test: a seam edge is used twice by one face, so
    counting distinct faces refuses a sphere too, for a different reason.
    """
    assert shape.is_manifold is False, f"{name}: the premise of this test"
    assert measured(backend.genus(shape)).value == 0, name


def test_genus_still_answers_for_a_compound_holding_nothing_but_its_solid(backend: OcctBackend):
    """The other half of D17: an unnecessary refusal is also a failure to
    answer. A part arrives from `BuildPart` as a Compound around one solid,
    and a sealed cavity gives that solid a second shell — neither is stray
    geometry, and both are still measured."""
    with bd.BuildPart() as bp:
        bd.Box(20, 20, 20)
        bd.Cylinder(radius=3, height=40, mode=bd.Mode.SUBTRACT)
    assert measured(backend.genus(bp.part)).value == 1

    cavity = bd.Compound(children=[bd.Box(20, 20, 20) - bd.Box(10, 10, 10)])
    assert measured(backend.genus(cavity)).value == 0


# --------------------------------------------------------------------------
# refusal — a shape that bounds no solid
# --------------------------------------------------------------------------


@pytest.fixture
def open_shell():
    """A box with one face removed: valid as a shape, but encloses nothing."""
    return bd.Shell(bd.Box(10, 10, 10).faces()[:-1])


def test_volume_is_refused_when_no_solid_is_bounded(backend: OcctBackend, open_shell):
    """`is_valid` does not catch this — an open shell reports True — and the raw
    `volume` is 0.0, which `volume(max=...)` would happily pass."""
    assert backend.is_valid(open_shell).value is True, "premise: validity does not catch it"
    assert open_shell.volume == 0.0, "premise: the raw property answers anyway"
    assert "bounds no solid" in refused(backend.volume(open_shell)).reason


def test_center_of_mass_is_refused_when_no_solid_is_bounded(backend: OcctBackend, open_shell):
    """build123d's `center()` still answers here, with the centroid of the
    *surface* — a different quantity under the same name."""
    assert pytest.approx(-1.0) == open_shell.center().Z, "premise: it answers, wrongly"
    assert "bounds no solid" in refused(backend.center_of_mass(open_shell)).reason


def test_area_and_solid_count_stay_answerable(backend: OcctBackend, open_shell):
    """Refuse the undefined, not the merely unusual: five faces of a 10mm cube
    have an area whatever they enclose, and `0 solids` is a true answer."""
    assert measured(backend.area(open_shell)).value == pytest.approx(500.0)
    assert backend.solid_count(open_shell).value == 0


# --------------------------------------------------------------------------
# relational primitives
# --------------------------------------------------------------------------


def test_min_distance_and_intersection(backend: OcctBackend):
    a = bd.Box(10, 10, 10)
    far = bd.Box(10, 10, 10).moved(bd.Location((20, 0, 0)))
    assert backend.min_distance(a, far).value == pytest.approx(10.0)

    half = bd.Box(10, 10, 10).moved(bd.Location((5, 0, 0)))
    assert backend.intersect_volume(a, half).value == pytest.approx(500.0)


def test_provenance_is_empty_on_this_tier(backend: OcctBackend):
    """triangles/distinct_normals describe a tessellation this tier does not
    have; emitting one would invite a meaningless cross-tier comparison."""
    assert backend.provenance(bd.Box(1, 1, 1)) == {}


def test_capabilities_include_topology(backend: OcctBackend):
    assert "topology_counts" in backend.capabilities()
    assert backend.kind == Tier.OCCT


# --------------------------------------------------------------------------
# the engine adapter
# --------------------------------------------------------------------------


def test_model_is_called_with_params(backend: OcctBackend, tmp_path: Path):
    model = tmp_path / "m.py"
    model.write_text(
        "import build123d as bd\ndef make_part(w: float, h: float):\n    return bd.Box(w, w, h)\n"
    )
    source = PyCADSource(path=model, engine="build123d", params={"w": 4.0, "h": 5.0})
    shape = backend.build(source, tmp_path)
    assert not isinstance(shape, BuildError), shape
    assert measured(backend.volume(shape)).value == pytest.approx(80.0)


def test_a_signature_mismatch_explains_the_calling_convention(backend: OcctBackend, tmp_path: Path):
    """The convention is deliberately dumb — method(**params), no inspection —
    so the failure has to say so."""
    model = tmp_path / "m.py"
    model.write_text("import build123d as bd\ndef make_part(spec):\n    return bd.Box(1, 1, 1)\n")
    result = backend.build(PyCADSource(path=model, engine="build123d", params={"w": 1}), tmp_path)
    assert isinstance(result, BuildError)
    assert "method(**params)" in (result.hint or "")


def test_a_missing_callable_lists_what_is_available(backend: OcctBackend, tmp_path: Path):
    model = tmp_path / "m.py"
    model.write_text("import build123d as bd\ndef other():\n    return bd.Box(1, 1, 1)\n")
    result = backend.build(PyCADSource(path=model, engine="build123d", method="nope"), tmp_path)
    assert isinstance(result, BuildError)
    assert "other" in (result.hint or "")


def test_a_model_raising_is_a_build_error(backend: OcctBackend, tmp_path: Path):
    model = tmp_path / "m.py"
    model.write_text("def make_part():\n    raise ValueError('bad geometry')\n")
    result = backend.build(PyCADSource(path=model, engine="build123d"), tmp_path)
    assert isinstance(result, BuildError)
    assert "bad geometry" in result.message


def test_a_missing_engine_is_an_environment_fault_not_a_failing_part(tmp_path: Path):
    """An engine that will not import says nothing about the design.

    The case this guards is silent until it is fatal: `cadquery-ocp` and
    `cadquery-ocp-novtk` both install the same top-level `OCP/` package, neither
    pip nor uv detects the conflict, and when the novtk build wins CadQuery
    cannot import at all. This repo drops novtk with a `[tool.uv]` override, but
    that is a workspace setting and is not carried in wheel metadata -- a plain
    `pip install partspec[occt,cadquery]` reproduces it with no override in
    scope, so the guard has to be in the code.

    Which is why the exact wording is NOT pinned here. `_engine_import_error`
    picks its branch from the OCP providers it finds installed, and a plain
    `pip install partspec[cadquery]` really does land two of them (measured:
    cadquery-ocp 7.9.3.1.1 alongside cadquery-ocp-novtk 7.9.3.1.1, pulled in
    by cadquery and by build123d's proxy respectively). Asserting "not
    importable" made this test fail in the one install its own docstring is
    about. The three branch wordings are pinned individually in
    `test_import_origin.py`; what belongs here is what every branch owes a
    reader — this is the environment's fault, it names what would not load,
    and it says what to do next.
    """
    model = tmp_path / "m.py"
    model.write_text("def part():\n    return None\n")
    result = build(PyCADSource(path=model, engine="definitely_not_installed", method="part"))
    assert isinstance(result, BuildError)
    assert result.origin == "environment", "not a verdict on the part"
    assert "definitely_not_installed" in result.message, "it names what would not load"
    assert result.hint, "an environment fault owes the reader a next step"


# --------------------------------------------------------------------------
# region materialization (#49)
# --------------------------------------------------------------------------


def test_region_solid_realises_the_canonical_polyhedron(backend: OcctBackend):
    """The materialized solid must match the region's own closed form — which is
    computed from the same vertex list the mesh tier triangulates. A true OCCT
    cylinder here would be a different (larger-by-zero, rounder) region than the
    other tier adjudicates, so exact volume agreement is the pin."""
    from partspec.region import box, cylinder

    b = backend.region_solid(box(min=(1, 2, 3), max=(4, 6, 9)))
    assert b.volume == pytest.approx(72.0, abs=1e-9)

    for axis in ("x", "y", "z"):
        r = cylinder(d=5, h=6, at=(1, 2, 3), axis=axis)
        s = backend.region_solid(r)
        assert s.volume == pytest.approx(r.volume(), abs=1e-9)


def test_intersect_volume_of_disjoint_shapes_is_zero_not_a_crash(backend: OcctBackend):
    """build123d's `&` returns None for disjoint shapes, and the naive
    `.volume` read crashed on it — found by this primitive's first caller,
    whose conforming case (an empty keep-out) is exactly two disjoint shapes."""
    a = bd.Box(2, 2, 2)
    b = bd.Pos(10, 10, 10) * bd.Box(2, 2, 2)
    m = measured(backend.intersect_volume(a, b))
    assert m.value == 0.0
    assert m.unit == "mm3"


# --------------------------------------------------------------------------
# bore enumeration (#80)
# --------------------------------------------------------------------------


def _plate_with_features():
    """60x40x10 plate: two Ø8 through bores, one Ø12 counterbore over the
    first, a Ø6 boss on top, a Ø5 blind hole. Every classification branch of
    SPEC-contract.md 4.5 on one part."""
    from build123d import Align, Box, Cylinder, Location

    a = (Align.CENTER, Align.CENTER, Align.MIN)
    plate = Box(60, 40, 10, align=(Align.MIN, Align.MIN, Align.MIN))
    return (
        plate
        - (Location((15, 20, -1)) * Cylinder(4, 12, align=a))
        - (Location((30, 20, -1)) * Cylinder(4, 12, align=a))
        - (Location((15, 20, 6)) * Cylinder(6, 5, align=a))
        + (Location((50, 20, 10)) * Cylinder(3, 5, align=a))
        - (Location((50, 8, 4)) * Cylinder(2.5, 7, align=a))
    )


def test_bores_enumerates_bores_and_only_bores(backend: OcctBackend):
    m = measured(backend.bores(_plate_with_features()))
    assert m.value == (12.0, 8.0, 8.0, 5.0), "counterbore per diameter; boss Ø6 absent"
    assert m.unit == "mm" and m.exact
    assert m.axes == ("bore_1", "bore_2", "bore_3", "bore_4")


def test_a_concave_fillet_is_not_a_bore(backend: OcctBackend):
    """The fillet's surface is inward-facing and cylindrical — everything a
    bore is except full-wrap. Counting it would report a hole that a drill
    never made."""
    from build123d import Align, Box, Location

    step = Box(20, 20, 20, align=(Align.MIN, Align.MIN, Align.MIN)) - Location((10, -1, 10)) * Box(
        11, 22, 11, align=(Align.MIN, Align.MIN, Align.MIN)
    )
    edges = [
        e for e in step.edges() if abs(e.center().X - 10) < 1e-6 and abs(e.center().Z - 10) < 1e-6
    ]
    filleted = step.fillet(radius=3, edge_list=edges)
    assert measured(backend.bores(filleted)).value == ()


def test_two_clevis_lugs_carry_two_bores(backend: OcctBackend):
    """Same axis, same radius, disjoint axial spans: the drawing says 2x Ø8
    and so must the enumeration — an (axis, radius) key alone merges them."""
    from build123d import Align, Box, Cylinder, Location

    lugs = Box(5, 30, 30, align=(Align.MIN, Align.MIN, Align.MIN)) + Location((20, 0, 0)) * Box(
        5, 30, 30, align=(Align.MIN, Align.MIN, Align.MIN)
    )
    clevis = lugs - Location((12.5, 15, 15)) * Cylinder(4, 60, rotation=(0, 90, 0))
    assert measured(backend.bores(clevis)).value == (8.0, 8.0)


def test_bores_refuses_an_empty_shape(backend: OcctBackend):
    from build123d import Compound

    refused(backend.bores(Compound()))


def test_a_trimmed_cylindrical_face_does_not_crash_the_enumeration(backend: OcctBackend):
    """A planar cut part-way around a cylinder — a slit clamp, an obround
    slot — wraps the surface in Geom_RectangularTrimmedSurface. The GeomType
    filter sees through the wrapper; the raw-surface extractor did not, and
    `bores` raised AttributeError on ordinary geometry (PR #87 review
    blocker). The slit clamp's severed bore also must not count as full-wrap."""
    from build123d import Align, Box, Cylinder, Location

    a = (Align.CENTER, Align.CENTER, Align.MIN)
    clamp = (
        Box(30, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN))
        - (Location((15, 15, -1)) * Cylinder(4, 12, align=a))
        - (Location((15, 27, -1)) * Box(2, 26, 12, align=a))
    )
    m = measured(backend.bores(clamp))
    assert 8.0 not in m.value, "a slit bore is not a full circle a pin can bear on"


def test_an_obround_slot_is_not_a_bore(backend: OcctBackend):
    """Two half-cylinders joined by planes: each wraps half the circle on its
    own axis, so neither reaches full-wrap. Also pins the 2π threshold — a
    mutant accepting half-wraps counts this slot twice."""
    from build123d import Align, Box, Cylinder, Location

    a = (Align.CENTER, Align.CENTER, Align.MIN)
    slot = (
        Location((10, 15, -1)) * Cylinder(4, 12, align=a)
        + Location((20, 15, -1)) * Cylinder(4, 12, align=a)
        + Location((15, 15, -1)) * Box(10, 8, 12, align=a)
    )
    part = Box(40, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN)) - slot
    assert measured(backend.bores(part)).value == ()


def test_the_reported_diameter_is_the_surface_parameter_not_the_grouping_key(
    backend: OcctBackend,
):
    """Grouping rounds to 1e-6 to absorb kernel noise; the *measurement* must
    be the un-rounded radius. Reporting the key produced a demonstrated false
    pass at tol below the quantum, with the true value nowhere in the report."""
    from build123d import Align, Box, Cylinder, Location

    a = (Align.CENTER, Align.CENTER, Align.MIN)
    part = Box(30, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN)) - (
        Location((15, 15, -1)) * Cylinder(4.0000004, 12, align=a)
    )
    m = measured(backend.bores(part))
    assert m.value == (8.0000008,), "the exact modelled diameter, not its quantisation"


def test_axis_sign_normalisation_agrees_with_its_own_rounding():
    """The flip threshold must sit at the rounding quantum: deciding the sign
    on a component the rounding then erases keys one axis line two ways,
    splitting a bore into sub-2pi groups — a hole that exists, reported
    absent."""
    from partspec.backends.occt import _axis_key

    noisy_pos, _ = _axis_key((0, 0, 0), (2e-9, -1.0, 0.0), 4.0)
    noisy_neg, _ = _axis_key((0, 0, 0), (-2e-9, -1.0, 0.0), 4.0)
    clean, _ = _axis_key((0, 0, 0), (0.0, -1.0, 0.0), 4.0)
    assert noisy_pos == noisy_neg == clean


def test_the_grouping_quantum_is_a_micrometre():
    """1e-6 rounding absorbs kernel noise without merging real features: radii
    a nanometre apart share a key, radii ten micrometres apart do not."""
    from partspec.backends.occt import _axis_key

    same_a, _ = _axis_key((0, 0, 0), (0, 0, 1.0), 4.0)
    same_b, _ = _axis_key((0, 0, 0), (0, 0, 1.0), 4.00000001)
    distinct, _ = _axis_key((0, 0, 0), (0, 0, 1.0), 4.00001)
    assert same_a == same_b
    assert same_a != distinct


# --------------------------------------------------------------------------
# volume / area / centre of mass measure the MATERIAL (#344, #347)
#
# Two corruptions of one solid, found sweeping PR #339's guard: a stray shell
# beside it, and the solid nested three compound wrappings deep. Every builder
# constructs its shapes fresh inside the call, behind a `lambda` where it is
# parametrized -- the #337 discipline.
# --------------------------------------------------------------------------


def _cube_beside_a_shell_100mm_away():
    """The stray that MOVES the centroid. #344's shell sits on the solid's own
    faces, so it drags the centre of mass by nothing and the issue records it
    unmoved; a closed shell 100 mm off drags it to x = 11.856 mm."""
    return bd.Compound(
        children=[_bored_cube(), bd.Pos(100, 0, 0) * bd.Shell(bd.Box(10, 10, 10).faces())]
    )


def _nested(shape, depth: int):
    """`shape` inside `depth` further TopoDS_Compound wrappings.

    Built at the TopoDS level rather than with `Compound(children=[...])` so
    the depth in the name is the depth in the shape: `Box(...)` is already a
    compound over its solid, so one `children=` wrapping is depth 2, not 1.

    `depth == 0` returns the shape UNWRAPPED. Wrapping a bare `TopoDS_SOLID` in
    a `bd.Compound` is not level 0 of anything a build produces: `Compound.volume`
    iterates `compounds()`, which is empty for a solid handle, so it would read
    0.0 and the parametrization would measure a helper artifact instead of the
    rule. `adopt` maps a real level-0 solid to `bd.Solid`, where it reads
    999.99 -- which is what this returns.
    """
    from OCP.TopoDS import (
        TopoDS_Builder,  # pyright: ignore[reportAttributeAccessIssue]
        TopoDS_Compound,  # pyright: ignore[reportAttributeAccessIssue]
    )

    if depth == 0:
        return shape
    raw = shape.wrapped
    for _ in range(depth):
        wrapper = TopoDS_Compound()
        builder = TopoDS_Builder()
        builder.MakeCompound(wrapper)
        builder.Add(wrapper, raw)
        raw = wrapper
    return bd.Compound(raw)


def _deeply_nested_cube():
    """A bored cube three compound wrappings deep -- `Compound.compounds()`
    reaches self and its DIRECT compound children only, so `get_type(Solid)`
    finds nothing and `a.volume` reads 0.0 (#347)."""
    return _nested(_bored_cube().solids()[0], 3)


def test_volume_ignores_a_stray_shell_beside_the_solid(backend: OcctBackend):
    """#344: a `Shell` over the solid's own faces is closed, so OCCT encloses a
    volume for it, and build123d's `.volume` sums shells alongside solids --
    exactly twice the part, flagged exact."""
    shape = _cube_beside_a_shell_over_its_own_faces()
    assert shape.volume == pytest.approx(14869.026644707672), "premise: the raw property doubles"
    assert backend.solid_count(shape).value == 1, "premise: the solid count does not move"
    assert measured(backend.volume(shape)).value == pytest.approx(7434.513322353836)


def test_volume_is_the_material_however_deeply_the_solid_is_nested(backend: OcctBackend):
    """#347: 7434 mm3 of material reported as 0.0, flagged exact -- which
    `volume(max=...)` passes on any part."""
    shape = _deeply_nested_cube()
    assert shape.volume == 0.0, "premise: the raw property collapses"
    assert backend.solid_count(shape).value == 1, "premise: the solid count does not move"
    assert measured(backend.volume(shape)).value == pytest.approx(7434.513322353836)


@pytest.mark.parametrize("depth", [0, 1, 2, 3, 4, 6])
def test_volume_does_not_depend_on_nesting_depth(backend: OcctBackend, depth: int):
    """The raw property is correct to depth 2 and 0.0 from depth 3 on, so a
    test at one depth proves nothing about the rule. Depth 3 is one ordinary
    `Compound(children=[...])` past an already-compound `Box`."""
    shape = _nested(bd.Box(10, 10, 10).solids()[0], depth)
    assert measured(backend.volume(shape)).value == pytest.approx(1000.0)


def test_area_ignores_a_stray_shell_beside_the_solid(backend: OcctBackend):
    """`SurfaceProperties_s` visits every face OCCURRENCE in the compound, so
    the shell's duplicate references to the solid's own faces are summed again
    (#344)."""
    shape = _cube_beside_a_shell_over_its_own_faces()
    assert shape.area == pytest.approx(5440.884901332316), "premise: the raw property doubles"
    assert measured(backend.area(shape)).value == pytest.approx(2720.4424506661585)


def test_area_falls_back_to_the_shape_when_there_is_no_solid(backend: OcctBackend):
    """The other half of the rule, and the reason `area` does not take
    `volume`'s single form. A sum over `solids()` alone reports a shell-only
    part as 0.0, exact -- a new confident wrong number of the class this fixes.
    A closed 10 mm box shell has an area whatever it bounds."""
    shell = bd.Shell(bd.Box(10, 10, 10).faces())
    assert shell.solids() == [], "premise: a shell is not a solid"
    assert sum(s.area for s in shell.solids()) == 0.0, "premise: the naive sum reports nothing"
    assert measured(backend.area(shell)).value == pytest.approx(600.0)


def test_center_of_mass_ignores_a_stray_shell_beside_the_solid(backend: OcctBackend):
    """Found by the sweep, not filed: `center()` reads volume properties over
    the whole shape, and a closed stray shell encloses a volume, so it drags
    the centroid 11.856 mm off a part centred on the origin."""
    shape = _cube_beside_a_shell_100mm_away()
    assert pytest.approx(11.856, abs=1e-3) == shape.center().X, "premise: the raw call is dragged"
    assert backend.solid_count(shape).value == 1, "premise: the solid count does not move"
    x, y, z = measured(backend.center_of_mass(shape)).value
    assert (x, y, z) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


def test_center_of_mass_weights_the_bodies_by_their_volume(backend: OcctBackend):
    """A multi-body part still answers, and the answer is the material's
    centroid -- not the midpoint of the bodies. A 10 mm cube at the origin and
    a 20 mm cube centred at x = 50 put it at 50 * 8000 / 9000."""
    shape = bd.Compound(children=[bd.Box(10, 10, 10), bd.Pos(50, 0, 0) * bd.Box(20, 20, 20)])
    assert backend.solid_count(shape).value == 2
    x, _, _ = measured(backend.center_of_mass(shape)).value
    assert x == pytest.approx(50.0 * 8000.0 / 9000.0)


def test_a_multi_body_shape_still_answers_volume_and_area(backend: OcctBackend):
    """The decision is what the quantity MEANS on a multi-body shape, not a
    refusal copied from `genus` (#344). Two disjoint 10 mm boxes hold 2000 mm3
    of material bounded by 1200 mm2 of surface, and both are defensible
    totals -- D17's second half forbids refusing them."""
    two = bd.Compound(children=[bd.Box(10, 10, 10), bd.Pos(30, 0, 0) * bd.Box(10, 10, 10)])
    assert measured(backend.volume(two)).value == pytest.approx(2000.0)
    assert measured(backend.area(two)).value == pytest.approx(1200.0)
    assert "per body" in refused(backend.genus(two)).reason, "genus still refuses; these do not"


@pytest.mark.parametrize(
    ("name", "shape", "volume", "area"),
    [
        ("box", lambda: bd.Box(10, 10, 10), 1000.0, 600.0),
        ("bored cube", _bored_cube, 7434.513322353836, 2720.4424506661585),
        (
            "blind hole",
            lambda: bd.Box(20, 20, 20) - (bd.Pos(0, 0, 5) * bd.Cylinder(3, 12)),
            7688.982236504618,
            2607.345175426583,
        ),
        (
            "tube",
            lambda: bd.Cylinder(10, 20) - bd.Cylinder(5, 20),
            4712.388980384691,
            2356.1944901923457,
        ),
        ("sphere", lambda: bd.Sphere(10), 4188.790204786391, 1256.6370614359173),
        ("torus", lambda: bd.Torus(10, 3), 1776.5287921960845, 1184.3525281307231),
        (
            "sealed cavity block",
            lambda: bd.Solid(bd.Box(20, 20, 20).solids()[0].wrapped).cut(
                bd.Solid(bd.Box(10, 10, 10).solids()[0].wrapped)
            ),
            7000.0,
            3000.0,
        ),
        ("solids()[0]", lambda: bd.Box(10, 10, 10).solids()[0], 1000.0, 600.0),
        (
            "compound of one solid",
            lambda: bd.Compound(children=[bd.Box(10, 10, 10)]),
            1000.0,
            600.0,
        ),
        (
            "two disjoint solids",
            lambda: bd.Compound(
                children=[bd.Box(10, 10, 10), bd.Pos(30, 0, 0) * bd.Box(10, 10, 10)]
            ),
            2000.0,
            1200.0,
        ),
    ],
)
def test_honest_shapes_measure_exactly_as_before(
    backend: OcctBackend, name: str, shape, volume: float, area: float
):
    """D17's second half: the narrowing must not move an honest answer. Every
    row was measured under `float(a.volume)` / `float(a.area)` before the
    change and is identical after it."""
    a = shape()
    assert measured(backend.volume(a)).value == pytest.approx(volume), name
    assert measured(backend.area(a)).value == pytest.approx(area), name


def test_step_roundtrip_compares_material_not_the_collapsed_property(backend: OcctBackend):
    """The same broken read, one method down. `a.volume` is 0.0 on the nested
    shape and the round-tripped shape comes back shallow, so the comparison
    reported `volume_rel 7.4e15` -- total degradation fabricated on an exchange
    that preserved the part exactly."""
    shape = _deeply_nested_cube()
    assert shape.volume == 0.0, "premise: the raw property collapses"
    result = backend.step_roundtrip(shape)
    assert not isinstance(result, Unsupported)
    assert result["volume_rel"] < 1e-9
    assert result["solids"] == (1, 1)


def test_center_of_mass_is_refused_when_the_solids_enclose_no_net_volume(backend: OcctBackend):
    """The weighting divides by the total, and a reversed solid contributes a
    NEGATIVE volume, so the total is reachable at exactly zero. Python floats
    raise `ZeroDivisionError` there rather than producing a `nan` -- so the
    guard prevents a crash, not a fabricated number, and the refusal is owed
    either way: solids enclosing no net volume have no centre of mass.

    Nothing adjacent catches it: `solid_count` reads 2 and `is_valid` True.
    """
    a1, a2 = bd.Box(10, 10, 10), bd.Box(10, 10, 10)
    shape = bd.Compound(children=[a1, bd.Solid(a2.solids()[0].wrapped.Reversed())])
    assert [round(float(s.volume), 6) for s in shape.solids()] == [1000.0, -1000.0], (
        "premise: the reversed solid encloses a negative volume"
    )
    assert backend.solid_count(shape).value == 2, "premise: the solid count reads normal"
    assert backend.is_valid(shape).value is True, "premise: validity does not catch it"
    assert "no net volume" in refused(backend.center_of_mass(shape)).reason


def test_a_sheet_beside_a_solid_contributes_nothing_to_area(backend: OcctBackend):
    """The accepted cost of measuring area over the solids, pinned so it stays
    a decision rather than a discovery.

    The same 20 mm square face is measured when it stands alone and dropped
    once a solid is beside it. `area(max=700)` therefore passes on a shape
    carrying 1000 mm2 of surface -- the unsafe direction, accepted because the
    alternative is #344's doubling. `watertight` is the primitive that names
    such a shape.
    """
    sheet = bd.Pos(0, 0, 30) * bd.Rectangle(20, 20).faces()[0]
    assert measured(backend.area(sheet)).value == pytest.approx(400.0)

    mixed = bd.Compound(
        children=[bd.Box(10, 10, 10), bd.Pos(0, 0, 30) * bd.Rectangle(20, 20).faces()[0]]
    )
    assert mixed.area == pytest.approx(1000.0), "premise: the shape does carry 1000 mm2"
    assert measured(backend.area(mixed)).value == pytest.approx(600.0)
    assert backend.solid_count(mixed).value == 1
    assert backend.is_valid(mixed).value is True
    assert measured(backend.watertight(mixed)).value is False, "an OPEN sheet: false"


def test_a_closed_stray_shell_is_dropped_from_area_with_watertight_still_true(
    backend: OcctBackend,
):
    """`watertight` is NOT the primitive that names a dropped sheet, and this
    is the row that proves it.

    An open sheet leaves an edge bounded by one face, so `is_manifold` reads
    false. A CLOSED stray shell leaves every edge bounded by two, so it reads
    **true** while `area` silently drops the shell's whole 600 mm2. Every
    adjacent boolean reads normal. What catches it is `genus`, which refuses
    any stray beside its one solid, and `bbox` / `topology_counts`, which move
    because the shell is a separate body.
    """
    mixed = bd.Compound(
        children=[bd.Box(10, 10, 10), bd.Pos(100, 0, 0) * bd.Shell(bd.Box(10, 10, 10).faces())]
    )
    assert mixed.area == pytest.approx(1200.0), "premise: the shape carries 1200 mm2"
    assert measured(backend.area(mixed)).value == pytest.approx(600.0), "600 mm2 dropped"

    assert measured(backend.watertight(mixed)).value is True, "a CLOSED shell: still true"
    assert backend.is_valid(mixed).value is True
    assert backend.solid_count(mixed).value == 1

    assert "one closed body" in refused(backend.genus(mixed)).reason
    assert measured(backend.bbox(mixed)).value == pytest.approx((110.0, 10.0, 10.0))
    assert backend.topology_counts(mixed).value == (12, 24, 16)


def test_step_roundtrip_fails_the_stray_shell_that_the_accessors_cannot_see(
    backend: OcctBackend,
):
    """The second detector for #344's stray, and the stronger one.

    The shell shares the solid's TShapes, so every deduplicating accessor is
    unmoved -- `topology_counts` reads the honest (7, 15, 10). The STEP writer
    expands those shared TShapes into distinct entities, so the round-trip
    counts move where nothing else does. `genus` refuses this shape at exit 2;
    this FAILS it at exit 1, which is a verdict rather than a refusal.

    **The deduplication is what makes the drift visible, not what threatens
    it.** An earlier revision of this docstring and of SPEC-backend said the
    opposite -- that a refactor must not deduplicate these counts -- which is
    the rule inverted: obeying it deletes the detector. Measured on this shape,
    the two refactors that lose the detection are raw occurrence counting and
    reduction to the solids' own, and the accessor the code uses is the only
    one of the three that sees anything:

        .faces() both sides            (7, 14)   drift -> FAIL
        raw TopExp occurrences        (14, 14)   no drift, detector gone
        summed over a.solids()         (7,  7)   no drift, detector gone

    Both losing forms are pinned below, so neither can be introduced silently.
    """
    honest = backend.step_roundtrip(_bored_cube())
    assert not isinstance(honest, Unsupported)
    assert honest["faces"] == (7, 7)
    assert honest["edges"] == (15, 15)

    stray = _cube_beside_a_shell_over_its_own_faces()
    assert backend.topology_counts(stray).value == (7, 15, 10), (
        "premise: the accessors cannot see this stray at all"
    )

    # The mechanism, executed rather than described: the `a` side must stay
    # deduplicated for the round-trip's expansion to show up as drift.
    from OCP.TopAbs import TopAbs_ShapeEnum  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopExp import TopExp_Explorer  # pyright: ignore[reportAttributeAccessIssue]

    explorer = TopExp_Explorer(stray.wrapped, TopAbs_ShapeEnum.TopAbs_FACE)
    occurrences = 0
    while explorer.More():
        occurrences += 1
        explorer.Next()
    assert occurrences == 14, "premise: raw occurrence counting already reads 14 before"
    assert len(stray.faces()) == 7, "premise: the deduplicating accessor reads 7"
    assert sum(len(solid.faces()) for solid in stray.solids()) == 7, (
        "premise: reducing to the solids' own also reads 7"
    )
    result = backend.step_roundtrip(stray)
    assert not isinstance(result, Unsupported)
    assert result["faces"] == (7, 14), "the writer expands the shared TShapes"
    assert result["edges"] == (15, 30)
    assert result["solids"] == (1, 1)
    assert result["volume_rel"] < 1e-9, "the MATERIAL survives; only the topology moves"
