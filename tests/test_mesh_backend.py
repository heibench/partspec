"""The mesh backend, verified against analytically-known geometry.

Two tiers of test, deliberately separated:

* Measurement tests build their input with trimesh, so they run anywhere the
  mesh extra is installed — `needs_mesh`.
* Engine tests shell out to OpenSCAD *and then measure what it exported*, so
  they need the binary and the mesh extra both — `needs_scad_tier`. They skip
  when either is absent, but CI sets `PARTSPEC_REQUIRE_ENGINES=1`, which turns
  the binary half of that skip into a hard failure, so "absent" is a local
  convenience and never a silent gap in the gate. Their fixtures are chosen so
  every expected number has a closed form; asserting against whatever the tool
  produced would test nothing.

The gate is per test rather than on the module: `test_topology_is_not_in_
capabilities` reads a declaration and needs neither (#165).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from support import (
    measured,
    needs_mesh,
    needs_scad_tier,
    openscad_supports_backend_flag,
    optional_module,
    refused,
)

from partspec.backend import BuildError, Tier, Unsupported, Vec3
from partspec.backends.mesh import MeshBackend
from partspec.engines.openscad import OpenSCADSource

trimesh = optional_module("trimesh")

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def backend() -> MeshBackend:
    return MeshBackend()


# --------------------------------------------------------------------------
# measurement — analytic, engine-free
# --------------------------------------------------------------------------


@needs_mesh
def test_cube_measures_exactly(backend: MeshBackend):
    """A polyhedron's volume and area are closed-form. Under D15 the mesh *is*
    the part, so these are exact — not approximations of anything."""
    mesh = trimesh.creation.box(extents=(10, 20, 30))

    volume = measured(backend.volume(mesh))
    assert volume.value == pytest.approx(6000.0)
    assert volume.exact and volume.bounds is None

    area = backend.area(mesh)
    assert area.value == pytest.approx(2 * (10 * 20 + 20 * 30 + 10 * 30))
    assert area.exact


@needs_mesh
def test_bbox_is_a_named_vector(backend: MeshBackend):
    mesh = trimesh.creation.box(extents=(10, 20, 30))
    bbox = backend.bbox(mesh)
    assert bbox.value == pytest.approx((10.0, 20.0, 30.0))
    assert bbox.axes == ("x", "y", "z")
    assert bbox.exact


@needs_mesh
def test_bbox_is_translation_invariant(backend: MeshBackend):
    """`envelope` bounds EXTENTS, not corners (SPEC-contract.md 4.2.3).

    The whole envelope-versus-`region.box` trap rests on this. The same API
    spells min/max two ways — a region takes CORNERS, an envelope bounds
    EXTENTS — and an author who carries the corner reading across writes a
    bound far looser than intended: measured, `envelope(max=(140, 230, 306))`
    written from the far corner of a 40x30x6 part at (100, 200, 300) passes on
    that part and passes again on one 120 mm wide. Nothing downstream can catch
    it, because the position never reaches the measurement.

    Which is exactly why the invariance has to be pinned here — but not
    because the test above cannot tell an extent from a corner. It can: a
    `bounds[1]` mutation gives `(5, 10, 15)` against its `(10, 20, 30)` and it
    fails. What it cannot tell is an extent from any quantity that COINCIDES
    with the extent at the origin, because it measures one box at one position.
    `2.0 * bounds[1]` is such a quantity — correct for every origin-centred
    part, wrong the moment one is displaced — and it passes every bbox
    assertion that predates this test while failing this one. (It does not
    pass the SUITE: measured, that mutation fails 12 tests, most of them
    end-to-end ones that compare a report against a fixture. What no
    pre-existing *bbox* test does is say why.) One size, two positions, is
    what closes that.
    """
    at_origin = trimesh.creation.box(extents=(10, 20, 30))
    displaced = trimesh.creation.box(extents=(10, 20, 30))
    displaced.apply_translation((100.0, 200.0, 300.0))

    assert backend.bbox(at_origin).value == pytest.approx((10.0, 20.0, 30.0))
    assert backend.bbox(displaced).value == pytest.approx(backend.bbox(at_origin).value)


@needs_mesh
def test_bbox_is_axis_aligned_not_fitted(backend: MeshBackend):
    """The other half of what §4.2.3 says `envelope` measures.

    The box is axis-aligned to the model's own frame, so it is the part's own
    size only when the part is square to that frame — a rotated part measures
    the space it occupies, not its dimensions. An author who reads `envelope`
    as "how big is this part" and then rotates the model gets a bound that
    fails for a reason the part did not change.

    Pinned because the honest-looking substitute is one attribute away:
    `bounding_box_oriented.primitive.extents` FITS the box to the part and
    returns (20, 20, 20) here — the part's own size, and not what `envelope`
    claims. This fixture is ROTATED, so the two genuinely disagree about what
    the measurement means, and this is the assertion that fails on that
    property.

    Other assertions do break under the same substitution, and none of them
    breaks on the property. trimesh returns fitted extents in ASCENDING order
    rather than in model-frame x/y/z, so any fixture whose extents are not
    already ascending disagrees on axis ORDER alone: measured, (30, 20, 10)
    comes back (10, 20, 30) and (100, 50, 2) comes back (2, 50, 100), which
    is what fails `test_block_with_hole_matches_closed_form` and
    `test_parameters_reach_the_engine`. An axis-aligned fixture whose extents
    are already ascending — this file's (10, 20, 30) — agrees with the fitted
    box exactly and catches nothing either way.

    Watch the attribute, not the property name: `bounding_box_oriented.extents`
    is the AABB *of* the fitted box, and measured it returns the same
    (21.213203, 21.213203, 30.0) as the plain AABB for a rotated 10x20x30 box
    while `.volume` correctly reads 6000. Only `.primitive.extents` is the
    fitted measurement.
    """
    rotated = trimesh.creation.box(extents=(20, 20, 20))
    rotated.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 4, (0, 0, 1)))

    side = 20.0 * math.sqrt(2.0)
    assert backend.bbox(rotated).value == pytest.approx((side, side, 20.0))


@needs_mesh
def test_watertight_and_validity(backend: MeshBackend):
    mesh = trimesh.creation.box(extents=(1, 1, 1))
    assert backend.watertight(mesh).value is True
    assert backend.is_valid(mesh).value is True


@needs_mesh
def test_open_shell_is_not_watertight(backend: MeshBackend):
    """The case OpenSCAD's own --summary gets wrong: it omits the validity key
    entirely and exits 0, so `.get("simple", True)` passes a broken part."""
    mesh = trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        faces=[[0, 1, 2], [0, 1, 3], [0, 2, 3]],  # one face short of closed
    )
    assert backend.watertight(mesh).value is False


@needs_mesh
def test_watertight_detail_distinguishes_the_two_defects(backend: MeshBackend):
    """ "Not watertight" conflates a hole with a non-manifold junction.

    trimesh's `is_watertight` means "every edge used by exactly two faces". An
    edge used **once** is a hole; an edge used **more than twice** is a place
    where surfaces touch. Different causes, different fixes — and dogfooding hit
    the second on a community gridfinity bin whose mesh has 0 boundary edges and
    4 non-manifold ones, where "not watertight" alone reads as "it has holes".
    """
    open_shell = trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        faces=[[0, 1, 2], [0, 1, 3], [0, 2, 3]],
    )
    detail = backend.watertight_detail(open_shell)
    assert detail is not None and "boundary edge" in detail

    # Two tetrahedra sharing a single edge: closed, but non-manifold along it.
    verts = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [-1, 0, 0], [0, -1, 0]]
    faces = [
        [0, 1, 2],
        [0, 1, 3],
        [0, 2, 3],
        [1, 2, 3],
        [0, 4, 5],
        [0, 4, 3],
        [0, 5, 3],
        [4, 5, 3],
    ]
    touching = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    detail = backend.watertight_detail(touching)
    assert detail is not None and "non-manifold" in detail


@needs_mesh
def test_watertight_detail_is_none_when_fine(backend: MeshBackend):
    assert backend.watertight_detail(trimesh.creation.box(extents=(1, 1, 1))) is None


@needs_mesh
def test_solid_count_without_scipy(backend: MeshBackend):
    """trimesh's `body_count` needs scipy, which the mesh extra does not install."""
    a = trimesh.creation.box(extents=(5, 5, 5))
    b = trimesh.creation.box(extents=(5, 5, 5))
    b.apply_translation((20, 0, 0))
    assert measured(backend.solid_count(a)).value == 1
    assert measured(backend.solid_count(trimesh.util.concatenate([a, b]))).value == 2


def _block_with_sealed_cavity(body: float = 20.0, core: float = 10.0):
    """A solid block enclosing a sealed cubic void.

    Built by hand rather than with a boolean, so the fixture does not depend on
    manifold3d or blinkenlights: the inner cube's winding is inverted, which is
    exactly what makes it a cavity rather than a second body.
    """
    outer = trimesh.creation.box(extents=(body, body, body))
    inner = trimesh.creation.box(extents=(core, core, core))
    inner.invert()
    return trimesh.util.concatenate([outer, inner])


@needs_mesh
def test_a_sealed_cavity_is_one_solid_not_two(backend: MeshBackend):
    """The finding from the T0 agent-convergence baseline (`evals/BASELINE.md`).

    Counting boundary components said 2, which has no model-side remedy: the
    agent under test could not reach green with the correct part, so it drilled
    a vent bore the design never asked for. Orientation is the discriminator —
    the void's shell is wound inward and encloses negative volume.
    """
    mesh = _block_with_sealed_cavity()
    assert measured(backend.solid_count(mesh)).value == 1
    assert measured(backend.cavities(mesh)).value == 1


@needs_mesh
def test_a_sealed_cavity_is_not_a_handle(backend: MeshBackend):
    """`(2 - X)/2` assumes a single shell, so it was wrong by exactly the cavity
    count: X = 4 here, reporting genus -1 — a handle that does not exist. The
    shell-aware `S - X/2` is the form the OCCT tier already used."""
    assert measured(backend.genus(_block_with_sealed_cavity())).value == 0


@needs_mesh
def test_two_disjoint_bodies_are_not_cavities(backend: MeshBackend):
    """The counterpart the orientation rule has to keep getting right."""
    a = trimesh.creation.box(extents=(5, 5, 5))
    b = trimesh.creation.box(extents=(5, 5, 5))
    b.apply_translation((20, 0, 0))
    both = trimesh.util.concatenate([a, b])
    assert measured(backend.solid_count(both)).value == 2
    assert measured(backend.cavities(both)).value == 0


@needs_mesh
def test_genus_counts_through_holes(backend: MeshBackend):
    assert measured(backend.genus(trimesh.creation.box(extents=(2, 2, 2)))).value == 0
    torus = trimesh.creation.torus(major_radius=10, minor_radius=3)
    assert measured(backend.genus(torus)).value == 1


@needs_mesh
def test_genus_counts_two_separate_through_holes(backend: MeshBackend):
    """Genus 2 — the case separating a real Euler characteristic from anything
    that merely detects "has a hole".

    A block drilled twice, mirroring the OCCT tier's parametrisation so the two
    backends are checked against the same claim. Two disjoint bores through one
    body are two independent handles by construction, which is why this is
    asserted from theory rather than from what the tool returned.
    """
    block = trimesh.creation.box(extents=(30, 20, 10))
    holes = [
        trimesh.creation.cylinder(radius=2, height=40, transform=t)
        for t in (
            trimesh.transformations.translation_matrix((8, 0, 0)),
            trimesh.transformations.translation_matrix((-8, 0, 0)),
        )
    ]
    drilled = block.difference(holes[0]).difference(holes[1])

    assert drilled.is_watertight, "premise: the boolean produced a sound mesh"
    assert measured(backend.solid_count(drilled)).value == 1
    assert measured(backend.genus(drilled)).value == 2


@needs_mesh
def test_genus_is_refused_for_multi_body_parts(backend: MeshBackend):
    """Genus is defined per body; the Euler characteristic of a complex is a
    different number. Two disjoint boxes give -1 — mathematically correct, and
    an answer to a question nobody asked. Refusing beats returning it."""
    a = trimesh.creation.box(extents=(5, 5, 5))
    b = trimesh.creation.box(extents=(5, 5, 5))
    b.apply_translation((20, 0, 0))

    result = refused(backend.genus(trimesh.util.concatenate([a, b])))
    assert "per body" in result.reason
    assert "2 solids" in result.reason


# --------------------------------------------------------------------------
# refusal — the preconditions each measurement presumes (dogfood F14)
#
# Until 2026-08-05 every one of these returned a confident number flagged
# `exact`. None of the 169 tests then in the suite covered it, because all of
# them measured meshes that were already sound — which is why the probe that
# found it built a deliberately broken one.
# --------------------------------------------------------------------------


@pytest.fixture
def open_cube():
    """A cube with one face (2 triangles) removed. Encloses nothing."""
    cube = trimesh.creation.box(extents=(10, 10, 10))
    return trimesh.Trimesh(
        vertices=cube.vertices.copy(), faces=cube.faces[:-2].copy(), process=False
    )


@pytest.fixture
def touching_tets():
    """Two tetrahedra sharing one edge: closed, but non-manifold along it."""
    return trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [-1, 0, 0], [0, -1, 0]],
        faces=[
            [0, 1, 2],
            [0, 1, 3],
            [0, 2, 3],
            [1, 2, 3],
            [0, 4, 5],
            [0, 4, 3],
            [0, 5, 3],
            [4, 5, 3],
        ],
        process=False,
    )


@needs_mesh
def test_volume_is_refused_on_an_open_mesh(backend: MeshBackend, open_cube):
    """The headline case. trimesh does not raise or return NaN — it returns half
    the volume of the closed cube, which reads as an ordinary measurement."""
    assert open_cube.volume == pytest.approx(500.0), "premise: the raw property answers"
    reason = refused(backend.volume(open_cube)).reason
    assert "closed surface" in reason
    assert "boundary edge" in reason, "the refusal names the actual defect"


@needs_mesh
def test_center_of_mass_is_refused_on_an_open_mesh(backend: MeshBackend, open_cube):
    """It previously reported (-2.5, 0, 0) — a point outside the material."""
    assert "closed surface" in refused(backend.center_of_mass(open_cube)).reason


@needs_mesh
def test_genus_is_refused_on_an_open_mesh(backend: MeshBackend, open_cube):
    """It previously reported genus 1: a through-hole that does not exist."""
    assert "closed surface" in refused(backend.genus(open_cube)).reason


def _sphere_pinched_at(*pairs: tuple[str, str]):
    """An icosphere with each named pair of poles identified as one vertex.

    Every edge keeps its two faces and the faces stay one component, so the
    result is watertight and one solid — and at each identified vertex two
    separate fans of faces meet, which no edge test can see.
    """
    sphere = trimesh.creation.icosphere(subdivisions=2)
    v = sphere.vertices
    pole = {
        "north": int(v[:, 2].argmax()),
        "south": int(v[:, 2].argmin()),
        "east": int(v[:, 0].argmax()),
        "west": int(v[:, 0].argmin()),
    }
    faces = sphere.faces.copy()
    for keep, drop in pairs:
        faces[faces == pole[drop]] = pole[keep]
    return trimesh.Trimesh(vertices=v.copy(), faces=faces, process=False)


@needs_mesh
def test_genus_is_refused_where_the_surface_touches_itself_at_a_vertex(backend: MeshBackend):
    """It previously reported genus 1, exact, on a pinched sphere (#437): X is
    1 there, `S - X/2` is a half, and floor division made it a whole number."""
    pinched = _sphere_pinched_at(("north", "south"))
    assert pinched.is_watertight, "premise: no edge test sees the defect"
    assert pinched.euler_number == 1, "premise: X is odd"
    assert measured(backend.solid_count(pinched)).value == 1

    assert "1 vertex" in refused(backend.genus(pinched)).reason


@needs_mesh
def test_genus_is_refused_at_two_pinches_though_the_characteristic_is_even(
    backend: MeshBackend,
):
    """Why the precondition is on the vertices and not on the parity of X: two
    pinches make X even again, and the formula then answers 1 without a
    remainder to give it away."""
    pinched = _sphere_pinched_at(("north", "south"), ("east", "west"))
    assert pinched.is_watertight
    assert pinched.euler_number == 0, "premise: X is even, so parity is silent"

    assert "2 vertices" in refused(backend.genus(pinched)).reason


@pytest.fixture
def zero_thickness_sheet():
    """Closed, consistently wound, and enclosing nothing.

    The exact topology OpenSCAD exports for `intersection()` of two cubes
    meeting on a face: four facets, taken off the binstl that 2021.01 and
    2026.08.01 both produce for that source. The two sides split the rectangle
    on opposite diagonals, so every edge is used exactly twice — the mesh is
    watertight and passes the volume gate, and still encloses 0.0.
    """
    return trimesh.Trimesh(
        vertices=[[0, 12, 10], [20, 0, 10], [20, 12, 10], [0, 0, 10]],
        faces=[[0, 1, 2], [1, 0, 3], [3, 2, 1], [2, 3, 0]],
        process=False,
    )


@needs_mesh
def test_center_of_mass_is_refused_on_a_mesh_enclosing_no_volume(
    backend: MeshBackend, zero_thickness_sheet
):
    """Closedness is necessary and not sufficient (#365).

    The centroid is the same integral as `volume` *divided by* the volume, so a
    closed surface enclosing none has no centre of mass. trimesh divides in
    numpy and returns `nan` rather than raising, and `Measurement` refuses a
    non-finite value by raising — which, out of a backend, ended the entire
    `measure` run and emitted nothing at all.
    """
    assert zero_thickness_sheet.is_watertight, "premise: it clears the closedness gate"
    assert zero_thickness_sheet.is_winding_consistent, "premise: and the winding gate"

    reason = refused(backend.center_of_mass(zero_thickness_sheet)).reason
    assert "no volume" in reason, "the refusal names the part's defect"
    assert "centre of mass" in reason


@needs_mesh
def test_a_sheet_still_answers_everything_that_needs_no_volume(
    backend: MeshBackend, zero_thickness_sheet
):
    """D17's other half: do not refuse more than the mathematics requires.

    A degenerate solid has no centroid, but it has an area, a bounding box and
    an enclosed volume — 0.0 is the answer, not the absence of one.
    """
    assert measured(backend.volume(zero_thickness_sheet)).value == 0.0
    assert measured(backend.area(zero_thickness_sheet)).value == pytest.approx(480.0)
    assert measured(backend.bbox(zero_thickness_sheet)).value == pytest.approx((20.0, 12.0, 0.0))


@needs_mesh
def test_volume_is_refused_when_the_winding_is_inconsistent(backend: MeshBackend):
    """Closed is not sufficient. The divergence theorem sums *signed*
    contributions, so a flipped triangle subtracts where it should add. Edge use
    is unchanged by winding, so `is_watertight` cannot see this."""
    cube = trimesh.creation.box(extents=(10, 10, 10))
    faces = cube.faces.copy()
    faces[0] = faces[0][::-1]
    flipped = trimesh.Trimesh(vertices=cube.vertices.copy(), faces=faces, process=False)

    assert flipped.is_watertight, "premise: still closed"
    assert not flipped.is_winding_consistent
    assert "winding" in refused(backend.volume(flipped)).reason


@needs_mesh
def test_body_count_is_refused_where_the_geometry_does_not_fix_it(
    backend: MeshBackend, touching_tets
):
    """A non-manifold edge leaves the count genuinely undetermined: counting
    through the junction gives 1 and counting across it gives 2. On the F10
    gridfinity bin manifold3d welds and says 1 while the exported triangles say
    3. Both are defensible, so neither may be reported as exact."""
    assert "non-manifold" in refused(backend.solid_count(touching_tets)).reason


@needs_mesh
def test_an_open_mesh_bounds_no_solid(backend: MeshBackend, open_cube):
    """Still an answer, not a refusal — over-refusal inflates `incomplete` and is
    its own way of dodging an answerable question. But the answer is 0: an open
    shell bounds no solid. This used to say 1, where `OcctBackend.solid_count`
    on an open shell says 0, so the two tiers disagreed about the same word."""
    assert measured(backend.solid_count(open_cube)).value == 0
    assert measured(backend.cavities(open_cube)).value == 0


@needs_mesh
def test_area_and_bbox_survive_an_open_mesh(backend: MeshBackend, open_cube):
    """Both are statements about the triangles as exported, not about what they
    enclose. Five faces of a 10mm cube: 500mm2."""
    assert backend.area(open_cube).value == pytest.approx(500.0)
    assert backend.bbox(open_cube).value == pytest.approx((10.0, 10.0, 10.0))
    assert backend.watertight(open_cube).value is False


@needs_mesh
def test_a_rejected_manifold_is_never_read(open_cube):
    """Pins the dependency behaviour that caused the bug.

    Handed an open mesh, manifold3d returns an object reporting
    `Error.NotManifold` with zero triangles — and `.decompose()` on that empty
    object still returns a one-element list while `.genus()` still returns 1.
    Reading those without checking `status()` is exactly how this backend came
    to report a through-hole in an open shell.
    """
    import numpy as np
    from manifold3d import Error, Manifold, Mesh

    raw = Manifold(
        Mesh(
            vert_properties=np.asarray(open_cube.vertices, dtype=np.float32),
            tri_verts=np.asarray(open_cube.faces, dtype=np.uint32),
        )
    )
    assert raw.status() != Error.NoError, "premise: manifold3d knows"
    assert raw.is_empty() and raw.num_tri() == 0
    assert len(raw.decompose()) == 1, "premise: the empty object still answers"
    assert raw.genus() == 1, "premise: and answers wrongly"

    from partspec.backends.mesh import _manifold

    assert isinstance(_manifold(open_cube), Unsupported), "so the wrapper must refuse"


@needs_mesh
def test_an_inside_out_mesh_has_no_volume(backend: MeshBackend):
    """Consistent winding is not correct winding. A uniformly inverted mesh is
    perfectly consistent and encloses *negative* volume: an inside-out cube
    measured -1000.0 mm3, flagged exact, and `volume(max=...)` passed on it
    because every negative number is below every positive bound.

    Refused rather than corrected with abs(): the sign is information. It says
    the normals point inward, which is a real defect in the exported artifact
    that a silent absolute value would hide.
    """
    inverted = trimesh.creation.box(extents=(10, 10, 10))
    inverted.invert()
    assert "inside-out" in refused(backend.volume(inverted)).reason
    assert "inside-out" in refused(backend.center_of_mass(inverted)).reason


@needs_mesh
def test_a_sealed_cavity_still_has_a_volume(backend: MeshBackend):
    """The counterpart: an inward-wound *component* is normal in a solid with a
    void, so the orientation gate must look at the part, not at any one shell."""
    assert measured(backend.volume(_block_with_sealed_cavity())).value == pytest.approx(7000.0)


# --------------------------------------------------------------------------
# D15 — measuring the artifact as exported, not a library's rebuild of it
# --------------------------------------------------------------------------


@needs_mesh
def test_measurements_do_not_route_through_manifold3d(backend: MeshBackend):
    """manifold3d rebuilds the mesh it is handed, so nothing absolute may be
    read from it.

    Measured on the clean CGAL-rendered gridfinity bin: same 5,330 vertices,
    none moved, yet it retriangulated 55 of 10,688 triangles and moved the
    enclosed volume by 25.31 mm3 (0.078%). An independent divergence-theorem sum
    agrees with trimesh, not with manifold3d. Reporting genus and body count
    from that rebuild described a solid the engine never exported.
    """
    torus = trimesh.creation.torus(major_radius=10, minor_radius=3)
    calls: list[str] = []

    def tripwire(mesh):
        calls.append("manifold3d")
        raise AssertionError("no absolute measurement may go through manifold3d")

    import partspec.backends.mesh as mesh_mod

    original = mesh_mod._manifold
    mesh_mod._manifold = tripwire
    try:
        assert measured(backend.volume(torus)).value > 0
        assert measured(backend.solid_count(torus)).value == 1
        assert measured(backend.genus(torus)).value == 1
        assert measured(backend.center_of_mass(torus)).value is not None
    finally:
        mesh_mod._manifold = original
    assert calls == []


@needs_mesh
@pytest.mark.parametrize(
    ("name", "build"),
    [
        ("box", lambda: trimesh.creation.box(extents=(5, 5, 5))),
        ("torus", lambda: trimesh.creation.torus(major_radius=10, minor_radius=3)),
        ("cylinder", lambda: trimesh.creation.cylinder(radius=4, height=9, sections=24)),
    ],
)
def test_the_replacement_agrees_with_manifold3d_on_sound_meshes(backend: MeshBackend, name, build):
    """The equivalence claim behind dropping manifold3d: on input it accepts,
    the direct computation gives the same answer. It is only on input manifold3d
    silently repairs that the two part company — and there the direct one is
    right, because it measures what was exported."""
    import numpy as np
    from manifold3d import Manifold, Mesh

    mesh = build()
    reference = Manifold(
        Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        )
    )
    assert measured(backend.solid_count(mesh)).value == len(reference.decompose()), name
    assert measured(backend.genus(mesh)).value == reference.genus(), name


@needs_mesh
def test_topology_counts_are_always_refused(backend: MeshBackend):
    """The PartCAD failure, prevented structurally: a triangle count is not a
    face count, so the query is refused rather than answered wrongly."""
    result = backend.topology_counts(trimesh.creation.box(extents=(1, 1, 1)))
    assert isinstance(result, Unsupported)
    assert result.requires == Tier.OCCT


def test_topology_is_not_in_capabilities(backend: MeshBackend):
    assert "topology_counts" not in backend.capabilities()
    assert "volume" in backend.capabilities()


@needs_mesh
def test_min_distance_is_exact_on_polyhedra(backend: MeshBackend):
    a = trimesh.creation.box(extents=(10, 10, 10))
    b = trimesh.creation.box(extents=(10, 10, 10))
    b.apply_translation((20, 0, 0))  # 10mm gap between facing walls
    gap = measured(backend.min_distance(a, b))
    assert gap.value == pytest.approx(10.0, abs=1e-4)
    assert gap.exact


@needs_mesh
def test_intersect_volume_is_exact_on_polyhedra(backend: MeshBackend):
    a = trimesh.creation.box(extents=(10, 10, 10))
    b = trimesh.creation.box(extents=(10, 10, 10))
    b.apply_translation((5, 0, 0))  # half overlap
    assert measured(backend.intersect_volume(a, b)).value == pytest.approx(500.0, rel=1e-3)


@needs_mesh
def test_the_mesh_tier_does_not_declare_a_capability_it_cannot_honour():
    """`raycast` was in `CAPABILITIES` while `trimesh`'s default ray path
    indexes through `rtree`, which the `mesh` extra does not carry — so the
    primitive raised `ModuleNotFoundError` on the smallest install that
    declares it. SPEC-backend §3.2 exists to prevent exactly that, and
    nothing in the suite referenced `raycast` at all, so re-declaring it
    would have restored the defect with every test green.

    The method stays: undeclared-and-works-when-available is honest.
    """
    from partspec.backends.mesh import CAPABILITIES

    assert "raycast" not in CAPABILITIES

    trimesh = pytest.importorskip("trimesh", reason="mesh extra not installed")
    box = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    outcome = MeshBackend().raycast(box, Vec3(0.0, 0.0, -5.0), Vec3(0.0, 0.0, 1.0))
    # Either it answers (rtree present) or it refuses by name. Never raises.
    assert isinstance(outcome, list | Unsupported)
    if isinstance(outcome, Unsupported):
        assert "ray engine is unavailable" in outcome.reason


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------


@needs_mesh
def test_distinct_normals_track_facet_resolution(backend: MeshBackend):
    """The identity signal: a cylinder at $fn=n has n+2 distinct normals."""
    for sections in (16, 32, 64):
        mesh = trimesh.creation.cylinder(radius=5, height=10, sections=sections)
        assert backend.provenance(mesh)["distinct_normals"] == sections + 2


@needs_mesh
def test_distinct_normals_survive_retriangulation(backend: MeshBackend):
    """Why it is the identity signal and `triangles` is not: subdividing changes
    the triangle count without changing the design."""
    cube = trimesh.creation.box(extents=(10, 20, 30))
    coarse = backend.provenance(cube)
    fine = backend.provenance(cube.subdivide())

    assert fine["triangles"] > coarse["triangles"]
    assert fine["distinct_normals"] == coarse["distinct_normals"] == 6


# --------------------------------------------------------------------------
# engine — needs the OpenSCAD binary
# --------------------------------------------------------------------------


@needs_scad_tier
def test_block_with_hole_matches_closed_form(backend: MeshBackend, tmp_path: Path):
    """The P1 exit criterion, on a shape whose every quantity has a closed form.

    30x20x10 block with a 6x6 square through-hole along Z.
    """
    source = OpenSCADSource(path=FIXTURES / "block_with_hole.scad")
    mesh = backend.build(source, tmp_path)
    assert not isinstance(mesh, BuildError), mesh

    expected_volume = 30 * 20 * 10 - 6 * 6 * 10
    outer = 2 * (30 * 20) + 2 * (30 * 10) + 2 * (20 * 10)
    expected_area = outer - 2 * (6 * 6) + 4 * (6 * 10)

    assert measured(backend.volume(mesh)).value == pytest.approx(expected_volume)
    assert backend.area(mesh).value == pytest.approx(expected_area)
    assert backend.bbox(mesh).value == pytest.approx((30.0, 20.0, 10.0))
    assert backend.watertight(mesh).value is True
    assert measured(backend.solid_count(mesh)).value == 1
    com = measured(backend.center_of_mass(mesh))
    assert com.value == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    assert measured(backend.genus(mesh)).value == 1, "a through-hole is genus 1"


@needs_scad_tier
def test_every_measured_quantity_is_flagged_exact(backend: MeshBackend, tmp_path: Path):
    """Under D15 nothing on this tier is approximate, and each measurement must
    say so rather than leaving a consumer to assume it."""
    mesh = backend.build(OpenSCADSource(path=FIXTURES / "block_with_hole.scad"), tmp_path)
    assert not isinstance(mesh, BuildError)
    for measure in (backend.volume, backend.area, backend.bbox, backend.center_of_mass):
        result = measured(measure(mesh))
        assert result.exact, measure.__name__
        assert result.bounds is None, measure.__name__


@needs_scad_tier
def test_render_backend_is_passed_through_when_set(backend: MeshBackend, tmp_path: Path):
    """The backend changes the artifact, not just the speed: on a community
    gridfinity bin, Manifold produced 4 non-manifold edges where CGAL produced
    a clean mesh from identical source. So it must be selectable and recorded.

    Both sides are asserted, because `--backend` did not exist in 2021.01 and
    2021.01 is what Debian and Ubuntu ship. A contract written against a newer
    engine must not quietly render with the old default on an older one — that
    would substitute a different artifact for the requested one, silently. It
    fails, and the message has to carry the engine's own words.
    """
    src = OpenSCADSource(path=FIXTURES / "block_with_hole.scad", backend="CGAL")
    mesh = backend.build(src, tmp_path)

    if not openscad_supports_backend_flag():
        assert isinstance(mesh, BuildError)
        assert "backend" in (mesh.hint or ""), (
            f"the refusal must name what the engine rejected, not just the exit code: {mesh}"
        )
        return

    assert not isinstance(mesh, BuildError), mesh
    assert measured(backend.volume(mesh)).value == pytest.approx(30 * 20 * 10 - 6 * 6 * 10)


@needs_scad_tier
def test_two_bodies(backend: MeshBackend, tmp_path: Path):
    mesh = backend.build(OpenSCADSource(path=FIXTURES / "two_bodies.scad"), tmp_path)
    assert not isinstance(mesh, BuildError)
    assert measured(backend.solid_count(mesh)).value == 2
    assert measured(backend.volume(mesh)).value == pytest.approx(2 * 5**3)
    assert isinstance(backend.genus(mesh), Unsupported)


@needs_scad_tier
def test_parameters_reach_the_engine(backend: MeshBackend, tmp_path: Path):
    """-D overrides actually change the geometry — the thing every parametric
    contract depends on."""
    source = OpenSCADSource(
        path=FIXTURES / "parametric_plate.scad",
        params={"plate_x": 100, "plate_y": 50, "plate_z": 2},
    )
    mesh = backend.build(source, tmp_path)
    assert not isinstance(mesh, BuildError)
    assert backend.bbox(mesh).value == pytest.approx((100.0, 50.0, 2.0))
    assert measured(backend.volume(mesh)).value == pytest.approx(100 * 50 * 2)


@needs_scad_tier
def test_curved_geometry_is_still_exact_for_the_polyhedron(backend: MeshBackend, tmp_path: Path):
    """A $fn=16 cylinder is a 16-gon prism, and partspec measures the prism.

    The volume is the prism's closed form, NOT pi*r^2*h. That difference is the
    whole of D15: the smooth cylinder was never the part.
    """
    scad = tmp_path / "cyl.scad"
    scad.write_text("cylinder(h = 10, r = 5, $fn = 16);\n")
    mesh = backend.build(OpenSCADSource(path=scad), tmp_path)
    assert not isinstance(mesh, BuildError)

    n, r, h = 16, 5.0, 10.0
    prism_volume = 0.5 * n * r**2 * math.sin(2 * math.pi / n) * h
    volume = measured(backend.volume(mesh))
    assert volume.value == pytest.approx(prism_volume, rel=1e-4)
    assert volume.value < math.pi * r**2 * h, "inscribed prism reads low"
    assert volume.exact


@needs_scad_tier
def test_a_contact_sheet_reads_twice_its_patch_and_volume_does_not_refuse_it(
    backend: MeshBackend, tmp_path: Path
):
    """The number `skills/contract-authoring/SKILL.md` tells an author to expect
    from an interference probe, executed rather than asserted (#238).

    `intersection()` of two boxes meeting on a face is a zero-thickness sheet.
    Both of its sides are exported, so `area` is TWICE the 10 x 10 patch — the
    trap the skill exists to name, because 100.0 and 200.0 are both plausible
    and nothing distinguishes them after the fact.

    `volume` is asserted NOT to refuse here, which is the half #238 was filed
    without: four triangles meeting two-per-edge are watertight, so the
    precondition holds and the integral is exactly zero. The refusal the issue
    reports needs a mesh that is genuinely non-manifold — see the annular case
    below.
    """
    scad = tmp_path / "contact.scad"
    scad.write_text(
        "intersection() {\n  cube([10, 10, 10]);\n  translate([0, 0, 10]) cube([10, 10, 10]);\n}\n"
    )
    mesh = backend.build(OpenSCADSource(path=scad), tmp_path)
    assert not isinstance(mesh, BuildError), mesh

    patch = 10.0 * 10.0
    area = measured(backend.area(mesh))
    assert area.value == pytest.approx(2 * patch, rel=1e-9), (
        "both sides of the sheet are exported; a bound written against the "
        "patch alone is out by exactly 2x"
    )

    # Volume answers, and answers zero — it does not refuse this shape.
    volume = measured(backend.volume(mesh))
    assert volume.value == pytest.approx(0.0, abs=1e-9)


@needs_scad_tier
def test_an_annular_contact_refuses_volume_while_area_still_answers(
    backend: MeshBackend, tmp_path: Path
):
    """The other half of the same table: where `volume` legitimately refuses,
    `area` is what the author has left (#238).

    An annular contact — a plate resting on a tube's end face — exports a mesh
    that is not closed, so the volume precondition fails and the check is `n/a`.
    Refusing is correct; integrating over an open surface is meaningless. `area`
    is ungated for the mirror reason and still reports, which is what makes the
    resting-on case gradeable at all.
    """
    from partspec.backend import Unsupported

    scad = tmp_path / "annular.scad"
    scad.write_text(
        "$fn = 48;\n"
        "intersection() {\n"
        "  difference() {\n"
        "    cylinder(d = 20, h = 10);\n"
        "    translate([0, 0, -1]) cylinder(d = 12, h = 12);\n"
        "  }\n"
        "  translate([-15, -15, 10]) cube([30, 30, 5]);\n"
        "}\n"
    )
    mesh = backend.build(OpenSCADSource(path=scad), tmp_path)
    assert not isinstance(mesh, BuildError), mesh

    assert isinstance(backend.volume(mesh), Unsupported), (
        "premise: this is the shape that makes volume refuse"
    )
    area = measured(backend.area(mesh))
    assert area.value > 0.0
