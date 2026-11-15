"""The OCCT backend: measures a BREP shape.

Serves **build123d and CadQuery from one implementation** (D3). Verified: both
expose a `TopoDS_Shape` from the same OCP module, and a CadQuery result is
adopted by rewrapping the handle — no conversion, no copy, no loss. There is no
second code path to keep in sync, which is why CadQuery costs an afternoon
rather than a parallel backend.

This is the tier where topology is real. `topology_counts` is answered here and
refused on mesh, and that asymmetry is the whole point of having tiers.

Spec: SPEC-backend.md section 4.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..backend import BuildError, Tier, Unsupported, Vec3, effective_timeout
from ..engines import pycad
from ..status import Measurement

__all__ = ["CAPABILITIES", "OcctBackend"]

CAPABILITIES = frozenset(
    {
        "bbox",
        "volume",
        "area",
        "center_of_mass",
        "is_valid",
        "watertight",
        "solid_count",
        "cavities",
        "genus",
        "topology_counts",
        "triangles",
        "min_distance",
        "intersect_volume",
        "region_solid",
        "bores",
        "bore_table",
        "blend_radii",
        "draft_angle",
        "self_intersection_free",
        "step_roundtrip",
        "min_wall",
    }
)


_EMPTY_REASON = "this shape contains no geometry, so there is nothing to measure"


def _radial(
    point: tuple[float, float, float],
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
) -> tuple[float, float, float]:
    """The outward radial vector from a cylinder's axis to a surface point."""
    rel = tuple(p - o for p, o in zip(point, origin, strict=True))
    along = sum(r * d for r, d in zip(rel, direction, strict=True))
    return tuple(r - along * d for r, d in zip(rel, direction, strict=True))  # type: ignore[return-value]


def _axis_key(
    origin: tuple[float, float, float], direction: tuple[float, float, float], radius: float
) -> tuple[tuple, tuple[float, ...]]:
    """A grouping key identifying (axis line, radius) up to representation,
    plus the canonical direction it chose.

    Two faces of one bore can carry the axis with opposite directions and
    different origin points along the same line; the key must not care. The
    direction is sign-normalised on its first non-negligible component, and the
    origin is replaced by the axis line's foot of perpendicular from the world
    origin — the one point every representation of the line agrees on. Rounding
    to 6 decimals absorbs kernel noise; two genuinely distinct axes closer than
    a micrometre are a modelling pathology this deliberately merges rather than
    guesses about.
    """
    # The sign threshold matches the rounding quantum below: deciding the flip
    # on a component the rounding then erases would give two representations
    # of one axis line different keys, splitting a bore's faces into sub-2π
    # groups and reporting a hole that exists as absent.
    canonical = direction
    if next((c for c in canonical if abs(c) > 5e-7), 1.0) < 0:
        canonical = tuple(-c for c in canonical)
    along = sum(o * d for o, d in zip(origin, canonical, strict=True))
    foot = tuple(o - along * d for o, d in zip(origin, canonical, strict=True))
    key = (
        tuple(round(c, 6) for c in canonical),
        tuple(round(c, 6) for c in foot),
        round(radius, 6),
    )
    return key, canonical


def _axial_clusters(spans: list[tuple]) -> list[list[tuple]]:
    """Group spans `(lo, hi, ...)` into contiguous axial clusters.

    Faces whose axial spans touch or overlap belong to one bore (a seam-split
    cylinder, a bore interrupted by nothing); a gap along the axis separates
    two bores that merely share an axis line — the clevis's two lugs.
    """
    clusters: list[list[tuple]] = []
    hi: float | None = None
    for span in sorted(spans, key=lambda s: (s[0], s[1])):
        if hi is None or span[0] > hi + 1e-6:
            clusters.append([span])
            hi = span[1]
        else:
            clusters[-1].append(span)
            hi = max(hi, span[1])
    return clusters


def _empty(a: Any) -> bool:
    """No sub-shapes at all — an empty compound, not merely a shape without
    faces. A Wire or an Edge has vertices and is honestly measurable."""
    return not a.vertices()


def _material_volume(a: Any) -> float:
    """The volume of the shape's **material**: each solid's own, summed.

    Never `a.volume`, which build123d computes as
    `sum(i.volume for i in [*self.get_type(Solid), *self.get_type(Shell)])`
    over `self.compounds()`, and which is therefore wrong in two independent
    directions (measured, build123d 0.11.1):

    * It sums **shells** as well as solids. A `Shell` built over a solid's own
      faces is closed, so OCCT encloses a volume for it too, and a 20 mm cube
      bored 6 mm through read `14869.03` against its honest `7434.51` — exactly
      twice the part, flagged exact (#344).
    * `get_type` walks the direct children of `self.compounds()`, and
      `Compound.compounds()` returns self plus its *direct* compound children
      only. A solid below that is therefore invisible to it and the sum is
      `0.0` — 1000 mm³ of material reported as nothing, flagged exact (#347).
      Measured level by level, counting **TopoDS compound wrappings above the
      solid**: levels 0, 1 and 2 read 1000.0 and levels 3, 4, 5 and 6 read 0.0.
      That is not the same count as `Compound(children=[...])` calls -- the two
      differ by one, because `Box(...)` is already a compound over its solid --
      so level 3 is reached by **two** such calls, which is an assembly
      grouping a sub-assembly, the ordinary way to group one.

    Each solid's own `.volume` is `BRepGProp.VolumeProperties_s` over that
    solid, which recurses and knows nothing of the wrapping above it, so this
    is correct at any depth and counts no sheet. Measured over eighteen honest
    shapes, every one with a solid is unchanged.
    """
    return sum(float(solid.volume) for solid in a.solids())


# The five entity counts the Euler-Poincare formula reads, and the singular of
# each — genus is a statement about one closed body, so every one of them has to
# be that body's own (#334).
_EULER_ENTITIES = {
    "vertices": "vertex",
    "edges": "edge",
    "wires": "wire",
    "faces": "face",
    "shells": "shell",
}


def _shape_maps() -> tuple[Any, Any]:
    """The indexed shape map and the shape -> shapes map, on either OCP major.

    OCP 8 (build123d 0.13) moved them from `OCP.TopTools` to `OCP.collections`
    under template names; OCP 7.9 (build123d 0.11-0.12, and every CadQuery 2.x)
    has only the old ones (#454).
    """
    try:
        from OCP.collections import (  # pyright: ignore[reportMissingImports]
            IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as data_map,
        )
        from OCP.collections import (  # pyright: ignore[reportMissingImports]
            IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as index_map,
        )
    except ImportError:
        from OCP.TopTools import (
            TopTools_IndexedDataMapOfShapeListOfShape as data_map,  # pyright: ignore[reportAttributeAccessIssue]
        )
        from OCP.TopTools import (
            TopTools_IndexedMapOfShape as index_map,  # pyright: ignore[reportAttributeAccessIssue]
        )
    return index_map, data_map


def _not_closed(body: Any) -> str | None:
    """Why this solid's boundary is not closed, or None if it is.

    Every edge of a closed boundary is used by exactly two faces, with two
    details that each decide the answer on ordinary parts:

    * Counted as **occurrences**, not distinct ancestor faces. A seam edge is
      used twice by the SAME face; counting distinct faces refuses a sphere.
    * **OCCT-degenerate edges skipped** (`BRep_Tool.Degenerated_s`) — a sphere's
      poles are edges bounded by no area, used once each.

    `is_manifold` gets the first right and the second wrong, and that alone is
    why it cannot be this test. Measured, it applies the same `Extent() != 2`
    rule but skips an edge only when both its vertices are null and identical,
    which never fires on a solid's boundary — the predicate IS satisfiable, by an
    unbounded-line edge, which OCCT does not call degenerate and which bounds no
    face. So a sphere's 2 degenerate edges, a cone's 1 and a filleted box's 8 are
    each counted, used once each, and `is_manifold` reads False on all three —
    all three of them closed. Excluding the degenerate ones leaves no edge with a
    use count other than 2 on any of them.

    Deliberately the mesh tier's question in this tier's terms (`_not_closed` in
    mesh.py): a solid built over an open shell is one solid carrying nothing
    beside it, so the stray-geometry guard alone let it through to a genus taken
    over an open body (`Solid(Shell(box.faces()[1:]))` -- reported 0 on a shape
    with no genus at all).

    One pooled count, not the mesh tier's boundary/non-manifold split, and the
    phrasing is literally true of both: an edge used four times is as much "not
    bounded by exactly two faces" as an edge used once. Both defects are real and
    both are reachable -- sewing two stacked boxes yields a compound of shells in
    the DEFAULT mode, but `SetNonManifoldMode(True)` yields one shell, and the
    solid over it is 1 solid of 2000 mm3 with four edges used by four faces and
    no boundary edges at all. Measured, it reported `genus -1, exact` before this
    guard.
    """
    from OCP.BRep import BRep_Tool  # type: ignore[attr-defined]
    from OCP.TopAbs import TopAbs_ShapeEnum  # type: ignore[attr-defined]
    from OCP.TopExp import TopExp  # type: ignore[attr-defined]
    from OCP.TopoDS import TopoDS

    uses = _shape_maps()[1]()
    TopExp.MapShapesAndAncestors_s(
        body.wrapped, TopAbs_ShapeEnum.TopAbs_EDGE, TopAbs_ShapeEnum.TopAbs_FACE, uses
    )
    unshared = 0
    for i in range(1, uses.Extent() + 1):
        if BRep_Tool.Degenerated_s(TopoDS.Edge(uses.FindKey(i))):  # pyright: ignore[reportAttributeAccessIssue]
            continue
        if uses.FindFromIndex(i).Extent() != 2:
            unshared += 1
    if unshared:
        return f"it is not closed: {unshared} edge(s) not bounded by exactly two faces"
    return None


def _stray_geometry(a: Any, body: Any) -> str | None:
    """What `a` carries beyond the single solid `body`, phrased, or None.

    Counted per entity kind rather than by `a.children`, because the runner
    never sees the children: `adopt` rewraps the TopoDS handle, and the stray
    sheet that reaches `genus` as 8 faces arrives with `children == ()`.
    """
    extra = []
    for plural, singular in _EULER_ENTITIES.items():
        n = len(getattr(a, plural)()) - len(getattr(body, plural)())
        if n:
            extra.append(f"{n} {singular if n == 1 else plural}")
    return ", ".join(extra) if extra else None


def _min_draft_deg(a_coef: float, b_coef: float, c_coef: float, u1: float, u2: float) -> float:
    """min over u in [u1, u2] of asin(|a cos u + b sin u + c|), in degrees.

    The normal of a cylinder or cone dotted with the pull direction is exactly
    this sinusoid in the surface's angular parameter; its extreme over the
    face's wrap interval is at an endpoint, a crest (u = phi + k*pi), or a zero
    crossing (where the |.| bottoms out at 0). All candidates are enumerated,
    so the minimum is exact — no sampling.
    """
    radius = math.hypot(a_coef, b_coef)
    phi = math.atan2(b_coef, a_coef)

    candidates = [u1, u2]

    def add_periodic(base: float) -> None:
        k = math.floor((u1 - base) / math.tau)
        u = base + k * math.tau
        while u <= u2 + 1e-12:
            if u >= u1 - 1e-12:
                candidates.append(min(max(u, u1), u2))
            u += math.tau

    add_periodic(phi)  # crest
    add_periodic(phi + math.pi)  # trough
    if radius > 0.0 and abs(c_coef) <= radius:
        # |A cos u + B sin u + C| reaches 0 where cos(u - phi) = -C/R.
        offset = math.acos(max(-1.0, min(1.0, -c_coef / radius)))
        add_periodic(phi + offset)
        add_periodic(phi - offset)

    best = min(abs(radius * math.cos(u - phi) + c_coef) for u in candidates)
    return math.degrees(math.asin(min(1.0, best)))


def _segment_has_material(
    solid: Any, p1: tuple[float, float, float], p2: tuple[float, float, float]
) -> bool | None:
    """Whether the open segment p1-p2 crosses any material — an EXACT boolean
    common of the segment edge with the solid (PR #144, F1: a single probe
    point is not a certificate). None when the kernel cannot answer."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # type: ignore[attr-defined]
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge  # type: ignore[attr-defined]
    from OCP.gp import gp_Pnt  # type: ignore[attr-defined]
    from OCP.TopAbs import TopAbs_EDGE  # type: ignore[attr-defined]
    from OCP.TopExp import TopExp_Explorer  # type: ignore[attr-defined]

    if abs(p1[0] - p2[0]) < 1e-12 and abs(p1[1] - p2[1]) < 1e-12 and abs(p1[2] - p2[2]) < 1e-12:
        return None  # a degenerate segment cannot certify anything
    try:
        edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*p1), gp_Pnt(*p2)).Edge()
        common = BRepAlgoAPI_Common(edge, solid)
        if not common.IsDone():
            return None
        return TopExp_Explorer(common.Shape(), TopAbs_EDGE).More()
    except Exception:  # noqa: BLE001 - an unanswerable certificate is None, never a guess
        return None


def _circle_has_material(solid: Any, torus: Any) -> bool | None:
    """Whether the torus tube-centre circle crosses material — the exact
    boolean, on the circle edge."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # type: ignore[attr-defined]
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge  # type: ignore[attr-defined]
    from OCP.gp import gp_Ax2, gp_Circ  # type: ignore[attr-defined]
    from OCP.TopAbs import TopAbs_EDGE  # type: ignore[attr-defined]
    from OCP.TopExp import TopExp_Explorer  # type: ignore[attr-defined]

    try:
        pos = torus.Position()
        circle = gp_Circ(
            gp_Ax2(pos.Location(), pos.Direction(), pos.XDirection()), torus.MajorRadius()
        )
        edge = BRepBuilderAPI_MakeEdge(circle).Edge()
        common = BRepAlgoAPI_Common(edge, solid)
        if not common.IsDone():
            return None
        return TopExp_Explorer(common.Shape(), TopAbs_EDGE).More()
    except Exception:  # noqa: BLE001 - an unanswerable certificate is None, never a guess
        return None


def _chord_span(
    solid: Any, p1: tuple[float, float, float], p2: tuple[float, float, float]
) -> float | None:
    """The length of the chord p1-p2 if the WHOLE of it is material, else None.

    The exact boolean common of the chord edge with the solid, compared by
    LENGTH against the chord: equal length means the common is the whole
    chord. Where `_segment_has_material` asks "is any of this material?" to
    decide whether a span may count at all, this asks the stronger question
    "is all of it material?" (issue #145, item 2).

    **What this does and does not prove.** It is a tightness gate, not the
    soundness argument — PR #146's review earned that correction. The upper
    end is sound because a face's diametric span is a member of the declared
    measurand (SPEC-contract.md 4.11) and every member is an upper bound on
    the measurand's minimum; the certificate exists so the interval only
    collapses where real material can be shown along the span, keeping the
    number tethered to the part instead of to a formality. It does NOT prove
    a crossing between two points of the face: on a v-trimmed periodic face
    (a fillet band is a quarter-tube) the antipodal parameter lands off the
    face, inside the solid, and the chord still certifies. The span is still
    the face's own declared diametric span, so the bound holds; the executed
    fixture is pinned in the tests.

    The length comparison is two-sided, so an over-counted common would
    decline rather than certify. No shape has been found that produces one —
    an unreachable guard, recorded rather than claimed as tested.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # type: ignore[attr-defined]
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge  # type: ignore[attr-defined]
    from OCP.BRepGProp import BRepGProp  # type: ignore[attr-defined]
    from OCP.gp import gp_Pnt  # type: ignore[attr-defined]
    from OCP.GProp import GProp_GProps  # type: ignore[attr-defined]

    length = math.dist(p1, p2)
    if length <= 1e-9:
        # Load-bearing, and only for separations the kernel accepts:
        # `BRepBuilderAPI_MakeEdge` raises StdFail_NotDone on IDENTICAL
        # points, but at 1e-12 apart it builds a perfectly good edge that
        # measures 0.0 long. Without this gate that edge would compare mass
        # 0.0 against length 1e-12, pass the comparison, and certify a span
        # nothing was shown material along — a boolean that proves nothing,
        # read as proof (PR #146 review, round 2).
        return None
    try:
        edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*p1), gp_Pnt(*p2)).Edge()
        common = BRepAlgoAPI_Common(edge, solid)
        if not common.IsDone():
            return None
        props = GProp_GProps()
        BRepGProp.LinearProperties_s(common.Shape(), props)
    except Exception:  # noqa: BLE001 - an unanswerable certificate is None, never a guess
        return None
    if abs(props.Mass() - length) > 1e-7 * max(1.0, length):
        return None
    return length


Chord = tuple[tuple[float, float, float], tuple[float, float, float]]


def _diametric_chords(surf: Any, kind: Any) -> list[Chord]:
    """Candidate point pairs whose separation IS the face's diametric span.

    The antipodal parameter map differs per family and each is verified by
    execution (the chord length equals the analytic span to 1e-9): cylinder
    and cone `(u, v) -> (u + pi, v)`, sphere `-> (u + pi, -v)`, torus
    `-> (u, v + pi)`. The cone is sampled only at its minimal-radius end,
    which is the span the lower bound used; the others are sampled along the
    face so a chord blocked by a bore can be answered by one that is not —
    a fixture per family pins that (the cross-drilled rod, a bead with blind
    equatorial bores, a torus with pockets in its outer surface).
    """
    from OCP.GeomAbs import GeomAbs_SurfaceType  # type: ignore[attr-defined]

    u1, u2 = surf.FirstUParameter(), surf.LastUParameter()
    v1, v2 = surf.FirstVParameter(), surf.LastVParameter()

    if kind == GeomAbs_SurfaceType.GeomAbs_Cone:
        cone = surf.Cone()
        _, v_min = min(
            (abs(cone.RefRadius() + v * math.sin(cone.SemiAngle())), v) for v in (v1, v2)
        )
        vs, antipode = [v_min], lambda u, v: (u + math.pi, v)
    elif kind == GeomAbs_SurfaceType.GeomAbs_Sphere:
        vs = [v1 + (v2 - v1) * f for f in (0.5, 0.3, 0.7)]
        antipode = lambda u, v: (u + math.pi, -v)  # noqa: E731
    elif kind == GeomAbs_SurfaceType.GeomAbs_Torus:
        vs = [v1 + (v2 - v1) * f for f in (0.5, 0.25, 0.75)]
        antipode = lambda u, v: (u, v + math.pi)  # noqa: E731
    else:
        vs = [v1 + (v2 - v1) * f for f in (0.5, 0.2, 0.8)]
        antipode = lambda u, v: (u + math.pi, v)  # noqa: E731

    def point(u: float, v: float) -> tuple[float, float, float]:
        p = surf.Value(u, v)
        return (p.X(), p.Y(), p.Z())

    chords: list[Chord] = []
    for v in vs:
        for fraction in (0.3, 0.7):
            u = u1 + (u2 - u1) * fraction
            chords.append((point(u, v), point(*antipode(u, v))))
    return chords


def _certified_self_span(
    solid: Any, candidates: list[tuple[float, list[Chord]]], ceiling: float | None
) -> float | None:
    """The smallest certified diametric span among closed analytic faces that
    would improve on `ceiling` (the upper end the ray witness already found),
    or None if there is none.

    Candidates are tried in ascending span order and the search stops at the
    first certificate, so the usual cost is one boolean. `ceiling` bounds the
    other end of the work: a span at or above it cannot tighten anything, and
    since the list is sorted neither can any span after it. Without that
    guard a part whose chords are all blocked pays for every one of them and
    learns nothing — 20 cross-drilled rods measured 2.4x the whole check
    (PR #146 review, MINOR 3). Failing to certify is not a defect; it leaves
    the upper end to the ray witness, which is the loose direction.

    The certified value returned is the face's analytic span, not the chord's
    measured length: the two agree to 3e-15 by construction, and the analytic
    one is the number the lower bound already used, so a collapsed interval
    reports 2.0 rather than 2.0000000000000013.
    """
    for span, chords in sorted(candidates, key=lambda item: item[0]):
        if ceiling is not None and span >= ceiling:
            return None
        for p1, p2 in chords:
            if _chord_span(solid, p1, p2) is not None:
                return span
    return None


def _min_wall_measurement(raw: dict[str, Any]) -> Measurement:
    """The Measurement rule shared by `measure` and the check branch: exact
    when the interval collapses, else the guaranteed [lo, hi]."""
    lo, hi = raw["lo"], raw["hi"]
    if hi - lo <= 1e-9 * max(1.0, lo):
        return Measurement(lo, "mm", exact=True)
    return Measurement(lo, "mm", exact=False, bounds=(lo, hi))


class _quiet_occt:
    """Silence OCCT's console printers for the duration — the STEP machinery
    narrates transfers to stdout, and the CLI's stdout is the artifact
    channel. Printers are restored on exit, whatever happens."""

    def __enter__(self) -> None:
        from OCP.Message import Message  # type: ignore[attr-defined]

        self._messenger = Message.DefaultMessenger_s()
        self._printers = list(self._messenger.Printers())
        for printer in self._printers:
            self._messenger.RemovePrinter(printer)

    def __exit__(self, *exc: object) -> None:
        for printer in self._printers:
            self._messenger.AddPrinter(printer)


def _surface_name(kind: Any) -> str:
    """A human name for a GeomAbs surface type enum, without importing the
    whole enum table: the repr carries the name."""
    text = str(kind).rsplit("_", 1)[-1].rsplit(".", 1)[-1].lower()
    # "bsplinesurface surface" and "surfaceofextrusion surface" read doubled;
    # strip the noun the caller adds (PR #141 review, F5).
    text = text.removeprefix("surfaceof").removesuffix("surface")
    return text or "unknown"


class OcctBackend:
    """Measures an OCCT BREP shape, from either Python engine."""

    kind = Tier.OCCT

    def __init__(self, engine: str = "build123d") -> None:
        self.engine = engine
        self._version: str | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def engine_version(self) -> str:
        if self._version is None:
            self._version = pycad.version(self.engine)
        return self._version

    def build(
        self,
        source: pycad.PyCADSource,
        out_dir: Path,
        *,
        timeout_s: float | None = None,
        deps_out: list[Any] | None = None,
        unresolved_out: list[str] | None = None,
    ) -> Any | BuildError:
        """Build the part. `out_dir` is unused — nothing is exported to measure.

        `deps_out` and `unresolved_out` go unwritten for one reason each. There
        is no depfile channel: a Python model's reads are not reported by any
        engine. And there is nothing to write to `unresolved_out` because this
        tier cannot half-render -- an unresolved name in Python is an exception
        that reaches `pycad.build` as a `BuildError`, never a mesh that is
        quietly missing a feature (#286).

        The mesh tier has to round-trip through a file because OpenSCAD is a
        separate process. Here the shape is already in memory, and exporting it
        only to read it back would introduce the float32 quantisation this tier
        does not otherwise suffer.
        """
        return pycad.build(source, timeout_s=effective_timeout(timeout_s))

    def capabilities(self) -> frozenset[str]:
        return CAPABILITIES

    def provenance(self, a: Any) -> dict[str, Any]:
        """Empty on this tier.

        `triangles` and `distinct_normals` describe a tessellation, and this tier
        does not have one — the shape is analytic. Emitting a tessellation-shaped
        number here would invite a comparison between tiers that does not mean
        anything.
        """
        return {}

    # -- the primitives ----------------------------------------------------

    def bbox(self, a: Any) -> Measurement | Unsupported:
        """Refused for a shape with no geometry in it.

        An empty compound is not null, so `adopt` used to pass it through and
        this returned `(0.0, 0.0, 0.0)` flagged exact -- a number that satisfies
        `envelope(max=...)` for a part that does not exist. `adopt` now rejects
        it at the boundary; this is the same precondition stated where the
        measurement is taken, so the library path is closed too.
        """
        if _empty(a):
            return Unsupported(_EMPTY_REASON)
        size = a.bounding_box().size
        return Measurement(
            (float(size.X), float(size.Y), float(size.Z)), "mm", exact=True, axes=("x", "y", "z")
        )

    def volume(self, a: Any) -> Measurement | Unsupported:
        """How much **material** the shape holds: its solids' volume, summed.

        Refused for a shape that bounds no solid. The mesh tier's version of
        this returned a plausible wrong number; here it returns a plausible
        wrong *zero*. An open shell and a bare face both report `volume 0.0`
        while `is_valid` is True, so validity does not catch it — and
        `volume(max=...)` on a shape containing no material would pass.

        On a multi-body shape the quantity is the **total over the bodies**, not
        the total over everything the kernel finds. That is a decision about
        what volume means here, not a guard copied from `genus` (#344): a
        compound of several solids has a defensible total volume and keeps
        answering, while a sheet has no volume to contribute at all. Taken over
        `a.solids()` rather than off `a` — see `_material_volume` for the two
        measured ways `a.volume` gets this wrong.
        """
        if not a.solids():
            return Unsupported(
                "this shape bounds no solid, so it has no volume (check solid_count first)"
            )
        return Measurement(_material_volume(a), "mm3", exact=True)

    def area(self, a: Any) -> Measurement | Unsupported:
        """Total surface area — of the material where there is material, and of
        the shape itself where there is none.

        Deliberately **not** the single rule `volume` takes, and the fallback is
        the load-bearing half. Area is defined for a face and a shell as much as
        for a solid, so a naive sum over `a.solids()` would report a shell-only
        part as `0.0, exact` — measured, a closed 10 mm box shell reads 600.0
        today and 0.0 under that sum. That is a new confident wrong number of
        exactly the class this fixes, so no shape without a solid changes: it
        still reads `a.area`, and only the emptiness gate stands in front of it
        (`area(max=...)` would otherwise pass on an empty compound's 0.0).

        Where solids DO exist, the surface asked about is the material's. A
        `Shell` over a solid's own faces doubled the answer — 5440.88 against an
        honest 2720.44 on a bored 20 mm cube, flagged exact (#344) — because
        `BRepGProp.SurfaceProperties_s` visits every face occurrence in the
        compound, the duplicates included. Summing each solid's own area is
        unchanged on every honest solid measured and counts no stray sheet.

        **The cost, stated rather than left to be discovered: a sheet standing
        beside a solid contributes nothing here.** Measured, a 20 mm square face
        reports 400.0 alone and is dropped once a 10 mm box is beside it — 600.0
        on a shape carrying 1000 mm² of surface, so `area(max=700)` passes on
        it. Accepted, because the alternative is the doubling above and because
        a result mixing a solid with a loose sheet is the corruption this guard
        answers.

        **What names such a shape depends on whether the sheet is closed, and
        `watertight` alone does not.** Measured: an OPEN sheet or shell leaves
        an edge bounded by one face, so `is_manifold` reads false — that is the
        400 mm² case above. A CLOSED stray shell does not: a 10 mm box shell
        beside a plain box drops 600 mm² from `area` with `watertight` reading
        **true**, and beside the bored cube it drops the same 600 mm² while
        reading true (SPEC-backend.md §4's own row 3). What holds for both is
        `genus`, which refuses any stray beside its one solid (#339), and
        `bbox` / `topology_counts`, which move because the sheet is a separate
        body. SPEC-backend.md §4 records the trade.
        """
        if _empty(a):
            return Unsupported(_EMPTY_REASON)
        solids = a.solids()
        if not solids:
            return Measurement(float(a.area), "mm2", exact=True)
        return Measurement(sum(float(solid.area) for solid in solids), "mm2", exact=True)

    def center_of_mass(self, a: Any) -> Measurement | Unsupported:
        """The material's centroid: each solid's own centre, weighted by its
        volume.

        Refused for a shape bounding no solid, and for a sharper reason than
        `volume`'s: there build123d's `center()` still answers, but with the
        centroid of the *surface* — a different quantity under the same name.

        Taken over the solids for the same reason as `volume`, and found by the
        same sweep. `center()` reads `BRepGProp.VolumeProperties_s` over the
        whole shape, which encloses a volume for a closed stray shell too, so
        the centroid is dragged toward it: a bored 20 mm cube centred on the
        origin beside a closed 10 mm box shell 100 mm away measured
        `x = 11.856 mm, exact`, against its honest `-3.8e-16`. #344's own stray
        sits on the solid's own faces and so moves this by nothing, which is why
        the issue records `center_of_mass` as unmoved; move the stray and it
        moves. Nesting depth does not reach it — the GProp walk recurses — so
        this is the stray-body half of the class only.
        """
        solids = a.solids()
        if not solids:
            return Unsupported(
                "this shape bounds no solid, so it has no centre of mass (check solid_count first)"
            )
        total = _material_volume(a)
        if not total:
            # Weighting by a zero total divides by zero, which on Python
            # floats RAISES `ZeroDivisionError` -- it does not produce a `nan`.
            # So this guard prevents a crash, not a fabricated number; the
            # refusal is owed either way, because solids enclosing no net
            # volume have no centre of mass. Reachable: two independently built
            # 10 mm boxes, one reversed, are solids of +999.99 and -999.99 with
            # `solid_count 2` and `is_valid True` (SPEC-backend.md 4).
            return Unsupported(
                "this shape's solids enclose no net volume, so it has no centre of mass"
            )
        centres = [(float(s.volume), s.center()) for s in solids]
        com = tuple(
            sum(v * float(getattr(c, axis)) for v, c in centres) / total for axis in ("X", "Y", "Z")
        )
        return Measurement(com, "mm", exact=True, axes=("x", "y", "z"))

    def is_valid(self, a: Any) -> Measurement:
        """`is_valid` is a **property** on build123d and a **method**
        (`isValid()`) on CadQuery. Adoption normalises the object, so only the
        build123d spelling is needed here — but the divergence is the reason the
        adopt shim exists at all, and calling it as a method here was a real bug
        caught by a test on the adjacent path."""
        return Measurement(bool(a.is_valid), "bool", exact=True)

    def watertight(self, a: Any) -> Measurement | Unsupported:
        """`is_manifold` on a BREP: every edge bounded by exactly two faces.

        Vacuously true of a shape with no edges, which is why the emptiness gate
        has to sit in front of it rather than trusting the answer.
        """
        if _empty(a):
            return Unsupported(_EMPTY_REASON)
        return Measurement(bool(a.is_manifold), "bool", exact=True)

    def solid_count(self, a: Any) -> Measurement:
        return Measurement(len(a.solids()), "count", exact=True)

    def cavities(self, a: Any) -> Measurement | Unsupported:
        """Sealed internal voids.

        A solid is bounded by one outer shell plus one shell per enclosed void,
        so the difference is the void count. This tier has always counted solids
        correctly — a block with a sealed cavity is 1 solid and 2 shells — and
        the quantity was simply never exposed. The mesh tier reaches the same
        two numbers from triangle orientation.

        Counted **per solid**, not as a global `shells - solids`. The global
        form assumes every shell belongs to a solid, and nothing enforces
        that: one plain block beside a stray sheet body is 1 solid and 2
        shells, so the difference certified `cavities = 1, exact` on a part
        with no cavity at all — `verdict: pass`, exit 0. An open shell alone
        was the same arithmetic with nothing to hide behind, 1 minus 0.

        PR #147's first attempt gated on `not a.solids()`, which caught only
        the second case; its own review produced the first through the CLI
        and the false pass was still there. Summing each solid's own shells
        minus its outer one needs no precondition for the solid-bearing
        cases, is 0 for every stray-shell arrangement, and agrees with the
        mesh tier — which the gate did not (OCCT refused where mesh answered
        0, so one contract still adjudicated two ways).

        `_empty` is still refused, as `bbox` and `watertight` refuse it: a
        shape with no geometry at all is not a shape with no cavities.
        """
        if _empty(a):
            return Unsupported(_EMPTY_REASON)
        return Measurement(
            sum(max(len(solid.shells()) - 1, 0) for solid in a.solids()), "count", exact=True
        )

    def genus(self, a: Any) -> Measurement | Unsupported:
        """Through-holes, via the Euler-Poincare formula.

            V - E + 2F - W = 2(S - G)

        The naive `V - E + F` is **wrong on a BREP** and quietly so: OCCT faces
        carry inner wires, so a face with a hole is an annulus rather than a
        disc. Measured, the naive form reports a box with a through-hole as
        genus 0 and a box with a *blind* hole as genus -1. Including the wire
        count fixes both — verified against a box (0), one and two through-holes
        (1, 2), a blind hole (0) and a tube (1).

        Refused for multi-body parts for the same reason as the mesh tier: genus
        is defined per body.

        Refused too when the shape carries anything **the formula would read**
        beside that one solid — a vertex, edge, wire, face or shell of its own,
        whatever its dimensionality. (A duplicate reference to geometry the
        solid already owns adds nothing to those counts and is still measured;
        refusing it would refuse more than the mathematics requires.) The
        solid count does not establish one closed body: a stray face, a
        bodiless edge or a lone `Vertex` is not a solid, so it rode past the
        count and was summed into the characteristic anyway. On a 20 mm cube
        bored 6 mm through — honestly genus 1 — each of the three produced
        `0, exact`, and a contract declaring `genus(0)`, `watertight()`,
        `solid_count(1)` and `cavities(0)` reported `PASS: 5 pass` at exit 0 on a
        part with a through-hole (#334). `watertight` catches only part of the
        class: a `Vertex` contributes no edge, so `is_manifold` stays true.

        The precondition is therefore "one solid, nothing else it would read,
        and that solid closed" — the first two tested as the five counts the
        formula reads being the solid's own, which is exactly what the formula
        assumes when it is applied, and the third by `_not_closed`, because one
        solid over an open shell carries nothing beside itself and still has no
        genus. `cavities` above names the same configuration as the shape PR
        #147 was rewritten to survive; this is that guard, five lines further
        down, where it was never given.
        """
        solids = a.solids()
        if len(solids) != 1:
            return Unsupported(
                f"genus is defined per body; this part has {len(solids)} solids "
                f"(check solid_count first, or split the part)"
            )
        body = solids[0]
        stray = _stray_geometry(a, body)
        if stray is not None:
            return Unsupported(
                f"genus is defined for one closed body; this shape carries {stray} "
                f"beside its one solid (drop the stray geometry, or measure the solid alone)"
            )
        open_along = _not_closed(body)
        if open_along is not None:
            return Unsupported(f"genus is defined for one closed body; {open_along}")
        v, e, f, w = (
            len(body.vertices()),
            len(body.edges()),
            len(body.faces()),
            len(body.wires()),
        )
        genus = len(body.shells()) - (v - e + 2 * f - w) / 2
        if genus < 0:
            # The reported genus is the sum of the genera of the body's shells,
            # so a legitimate closed body cannot reach a negative one. It is
            # reachable when a single shell holds more than one closed
            # component -- one TopoDS_SOLID whose one shell carries two
            # disjoint boxes measured `-1, exact` at 2000 mm3, with nothing
            # beside the solid and every edge bounded by exactly two faces, so
            # neither guard above sees it.
            return Unsupported(
                f"genus is defined for one closed body; the Euler-Poincare formula gives "
                f"{int(genus)}, which no closed body has -- its shells do not each "
                f"enclose exactly one body"
            )
        return Measurement(int(genus), "count", exact=True)

    def topology_counts(self, a: Any) -> Measurement:
        """Real engineering topology — the reason this tier exists.

        On a mesh these would be triangle counts wearing the wrong name, so the
        mesh backend refuses them. Here they are faces, edges and vertices as
        modelled.
        """
        counts = (len(a.faces()), len(a.edges()), len(a.vertices()))
        return Measurement(counts, "count", exact=True, axes=("faces", "edges", "vertices"))

    def triangles(self, a: Any) -> Any:
        return a.tessellate(0.1)

    def min_distance(self, a: Any, b: Any) -> Measurement:
        return Measurement(float(a.distance_to(b)), "mm", exact=True)

    def intersect_volume(self, a: Any, b: Any) -> Measurement:
        """Volume of the boolean common.

        The empty case is explicit because build123d's `&` returns `None` for
        disjoint shapes rather than an empty compound — found by this
        primitive's first caller (keep_out, whose conforming case is exactly
        "these two shapes are disjoint"); `(a & b).volume` crashed on it.
        """
        common = a & b
        return Measurement(0.0 if common is None else float(common.volume), "mm3", exact=True)

    def region_solid(self, region: Any) -> Any:
        """Materialize a declared region as a native solid.

        A cylinder region is extruded from the same polygon vertex list the mesh
        tier triangulates (SPEC-contract.md 4.4): the two tiers must adjudicate
        the identical polyhedron, so a true OCCT cylinder — available here —
        is deliberately not used.
        """
        import build123d as bd

        from ..region import BoxRegion

        if isinstance(region, BoxRegion):
            (x0, y0, z0), (x1, y1, z1) = region.min, region.max
            return bd.Pos(x0, y0, z0) * bd.Solid.make_box(x1 - x0, y1 - y0, z1 - z0)
        points = [bd.Vector(*p) for p in region.base_polygon()]
        face = bd.Face(bd.Wire.make_polygon(points, close=True))
        return bd.extrude(face, amount=region.h, dir=region.axis_vector())

    def bore_table(self, a: Any) -> list[dict[str, Any]] | Unsupported:
        """Every bore with its geometry: `{"d", "direction", "center"}`.

        The raw data `bores` summarises and `bolt_circle` positions against
        (SPEC-contract.md 4.6): `direction` is the canonical unit axis (sign
        normalised, so parallel bores compare equal), `center` the midpoint of
        the bore's axial span on its axis — a real point of the feature, where
        the axis-line foot would be an artifact of where the world origin
        happens to sit. Like `triangles` and `region_solid`, this returns raw
        data rather than a Measurement; one detection implementation serves
        every consumer, so the bore definition cannot fork.
        """

        clusters = self._cylinder_clusters(a)
        if isinstance(clusters, Unsupported):
            return clusters
        table = [
            {"d": c["radius"] * 2, "direction": c["direction"], "center": c["center"]}
            for c in clusters
            if c["inward"] and c["wrap"] >= 2 * math.pi - 1e-6
        ]
        table.sort(key=lambda bore: -bore["d"])
        return table

    def _cylinder_clusters(self, a: Any) -> list[dict[str, Any]] | Unsupported:
        """Every cylindrical surface cluster: one entry per (axis line, radius,
        orientation, contiguous axial span), with its summed angular wrap.

        The single detection implementation beneath `bore_table` (inward,
        full-wrap clusters) and `blend_radii` (partial-wrap clusters): both
        kinds read one walk, so their definitions cannot fork.
        """
        if _empty(a):
            return Unsupported(_EMPTY_REASON)
        from build123d import GeomType
        from OCP.BRepAdaptor import BRepAdaptor_Surface  # type: ignore[attr-defined]
        from OCP.BRepTools import BRepTools  # type: ignore[attr-defined]

        # (key, inward) -> list of (axial_lo, axial_hi, extent, radius, dir, foot)
        groups: dict[tuple, list[tuple]] = {}
        for face in a.faces().filter_by(GeomType.CYLINDER):
            # BRepAdaptor, not the raw Geom surface: a planar cut part-way
            # around a cylinder (a slit clamp, an obround slot) wraps the
            # surface in Geom_RectangularTrimmedSurface, which the GeomType
            # filter sees through and the raw surface object cannot answer
            # Cylinder() on — the mismatch crashed on ordinary geometry.
            cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
            radius = float(cylinder.Radius())
            axis_location, axis_direction = cylinder.Axis().Location(), cylinder.Axis().Direction()
            origin = (axis_location.X(), axis_location.Y(), axis_location.Z())
            direction = (axis_direction.X(), axis_direction.Y(), axis_direction.Z())

            umin, umax, vmin, vmax = BRepTools.UVBounds_s(face.wrapped)
            surface_point = face.position_at(0.5, 0.5)  # u, v are normalised here
            point = (float(surface_point.X), float(surface_point.Y), float(surface_point.Z))
            normal_vec = face.normal_at(surface_point)
            normal = (float(normal_vec.X), float(normal_vec.Y), float(normal_vec.Z))
            radial = _radial(point, origin, direction)
            inward = sum(n * r for n, r in zip(normal, radial, strict=True)) < 0

            key, canonical = _axis_key(origin, direction, radius)
            # The v parameter measures axial distance from the face's own
            # surface origin along its own direction; both vary by face, so
            # spans are re-expressed on the canonical axis before comparison.
            base = sum(o * d for o, d in zip(origin, canonical, strict=True))
            sign = sum(d0 * d for d0, d in zip(direction, canonical, strict=True))
            ends = sorted((base + sign * vmin, base + sign * vmax))
            foot = tuple(o - base * d for o, d in zip(origin, canonical, strict=True))
            groups.setdefault((key, inward), []).append(
                (ends[0], ends[1], umax - umin, radius, canonical, foot)
            )

        clusters: list[dict[str, Any]] = []
        for (_, inward), spans in groups.items():
            for cluster in _axial_clusters(spans):
                # The rounded key groups; the surface parameter is the
                # measurement. Reporting the key's quantised radius flipped
                # verdicts at tolerances below its 1e-6 quantum — a false
                # pass with the true value appearing nowhere in the report.
                _, _, _, radius, canonical, foot = cluster[0]
                mid = (min(e[0] for e in cluster) + max(e[1] for e in cluster)) / 2
                clusters.append(
                    {
                        "radius": radius,
                        "direction": canonical,
                        "center": tuple(f + mid * d for f, d in zip(foot, canonical, strict=True)),
                        "inward": inward,
                        "wrap": sum(entry[2] for entry in cluster),
                    }
                )
        return clusters

    def draft_angle(
        self, a: Any, direction: tuple[float, float, float]
    ) -> Measurement | Unsupported:
        """Per-face draft against a two-half parting axis, ascending, exact.

        Draft of a face at a point is the angle between the face and the pull
        line: `asin(|n . d|)` — 0 for a vertical wall, 90 for a face square to
        the pull. The reported value per face is the MINIMUM over the face,
        which for planes is constant and for cylinders and cones is the
        closed-form extreme of `|A cos u + B sin u + C|` over the face's wrap
        interval — no sampling, so `exact=True` is the truth, not a hope.

        Any face outside those three families refuses the WHOLE check: a
        sampled minimum has no guaranteed lower bound (more samples can only
        find a smaller draft — the min_wall one-sidedness, POST-V0 section 5),
        and passing the analytic subset would be silence reading as success
        on the faces that were skipped.
        """
        from OCP.BRepAdaptor import BRepAdaptor_Surface  # type: ignore[attr-defined]
        from OCP.GeomAbs import GeomAbs_SurfaceType  # type: ignore[attr-defined]

        dx, dy, dz = direction  # normalised at declaration

        def dot(vec: Any) -> float:
            return vec.X() * dx + vec.Y() * dy + vec.Z() * dz

        drafts: list[tuple[int, float]] = []
        for index, face in enumerate(a.faces()):
            surf = BRepAdaptor_Surface(face.wrapped)
            kind = surf.GetType()
            if kind == GeomAbs_SurfaceType.GeomAbs_Plane:
                c = abs(dot(surf.Plane().Axis().Direction()))
                drafts.append((index, math.degrees(math.asin(min(1.0, c)))))
            elif kind == GeomAbs_SurfaceType.GeomAbs_Cylinder:
                pos = surf.Cylinder().Position()
                drafts.append(
                    (
                        index,
                        _min_draft_deg(
                            dot(pos.XDirection()),
                            dot(pos.YDirection()),
                            0.0,
                            surf.FirstUParameter(),
                            surf.LastUParameter(),
                        ),
                    )
                )
            elif kind == GeomAbs_SurfaceType.GeomAbs_Cone:
                cone = surf.Cone()
                pos = cone.Position()
                ca, sa = math.cos(cone.SemiAngle()), math.sin(cone.SemiAngle())
                drafts.append(
                    (
                        index,
                        _min_draft_deg(
                            ca * dot(pos.XDirection()),
                            ca * dot(pos.YDirection()),
                            -sa * dot(pos.Direction()),
                            surf.FirstUParameter(),
                            surf.LastUParameter(),
                        ),
                    )
                )
            else:
                return Unsupported(
                    f"face_{index} is a {_surface_name(kind)} surface; draft needs "
                    "the normal field's extreme, which this backend derives in "
                    "closed form only for planes, cylinders and cones — a sampled "
                    "minimum would have no guaranteed bound, and a verdict that "
                    "skipped this face would be silence reading as success"
                )
        drafts.sort(key=lambda entry: entry[1])
        return Measurement(
            tuple(value for _, value in drafts),
            "deg",
            exact=True,
            axes=tuple(f"face_{i}" for i, _ in drafts),
        )

    def self_intersection_free(self, a: Any) -> Measurement:
        """Whether the shape is free of pairwise self-intersection — exact.

        The kernel's own argument analysis (`BRepAlgoAPI_Check` in
        self-intersection mode): every sub-shape pair that intersects where
        the boundary says it must not is a fault. Exact because it is
        analysis, not sampling.

        The recorded limit (SPEC-contract.md 4.9, executed): a
        self-intersection lying within a single ANALYTIC surface — the
        spindle torus — goes undetected and passes. The kernel does test a
        face against itself and catches a self-overlapping swept face (a
        pair-less fault), so the escape is specifically the analytic case,
        not single-surface faults in general (PR #142 review, F1).
        """
        return Measurement(not self._self_intersections(a), "bool", exact=True)

    def self_intersection_free_detail(self, a: Any) -> str:
        """Name the intersecting entity pairs, for the failure detail."""
        pairs = self._self_intersections(a)
        counts: dict[str, int] = {}
        for kinds in pairs:
            counts[kinds] = counts.get(kinds, 0) + 1
        inventory = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        # "fault(s)", not "pair(s)": a face caught against ITSELF reports as
        # a single entity (PR #142 review, F1).
        return f"{len(pairs)} self-intersecting entity fault(s): {inventory}"

    def _self_intersections(self, a: Any) -> list[str]:
        """The faulty pairs as `type/type` strings (e.g. `edge/face`)."""
        from OCP.BOPAlgo import BOPAlgo_CheckStatus  # type: ignore[attr-defined]
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Check  # type: ignore[attr-defined]

        check = BRepAlgoAPI_Check(a.wrapped, False, True)  # SE off, SI on
        pairs: list[str] = []
        for result in check.Result():
            if result.GetCheckStatus() != BOPAlgo_CheckStatus.BOPAlgo_SelfIntersect:
                continue
            kinds = "/".join(
                str(shape.ShapeType()).rsplit("_", 1)[-1].lower()
                for shape in result.GetFaultyShapes1()
            )
            pairs.append(kinds)
        return pairs

    def step_roundtrip(self, a: Any) -> dict[str, Any] | Unsupported:
        """Write the shape to STEP, read it back, measure what survived.

        Returns the raw comparison — relative volume and area deltas (exact:
        both sides are the kernel's own exact quantities, so the delta is a
        computed number, not an estimate), the topology counts before and
        after, and the writer schema, which is recorded because it changes
        the artifact (the F13 lesson). The runner adjudicates.

        The exchange happens in a scratch directory: this check is about
        survivability, not about producing an export.
        """
        import tempfile

        from ..engines.pycad import adopt

        with _quiet_occt(), tempfile.TemporaryDirectory() as scratch:
            path = str(Path(scratch) / "part.step")
            schema = self._write_step(a, path)
            if schema is None:
                return Unsupported(
                    "the STEP writer could not serialise this shape; nothing "
                    "was compared, so nothing may be said about survivability"
                )
            raw = self._read_step(path)
            if raw is None:
                # The writer accepted it and the reader will not: that IS
                # degradation, total — but with nothing to measure, the
                # honest report is the refusal naming the asymmetry.
                return Unsupported(
                    "the STEP reader could not read back what the writer "
                    "wrote — the exchange failed whole"
                )
            back = adopt(raw)
        if isinstance(back, BuildError):
            return Unsupported(f"the round-tripped shape did not survive adoption: {back.message}")

        # `_material_volume`, not `a.volume`, on BOTH sides: the raw property
        # reads 0.0 once the solid sits three compound wrappings deep (#347),
        # and the STEP reader hands back a shallow shape, so the comparison
        # measured 0 against 7434.51 and reported `volume_rel 7.4e15` on a part
        # the exchange had preserved exactly -- a fabricated total degradation.
        # `area` is left as the shape's total on both sides: this is the
        # survivability question, where a stray sheet the exchange dropped IS
        # a change to the artifact, and area is immune to the nesting anyway.
        before = _material_volume(a)
        after = _material_volume(back)
        volume = abs(before)
        area = abs(a.area)
        return {
            "schema": schema,
            "volume_rel": abs(after - before) / max(volume, 1e-12),
            "area_rel": abs(back.area - a.area) / max(area, 1e-12),
            "faces": (len(a.faces()), len(back.faces())),
            "edges": (len(a.edges()), len(back.edges())),
            "solids": (len(a.solids()), len(back.solids())),
        }

    def _write_step(self, a: Any, path: str) -> str | None:
        """Write the shape to `path`; the writer schema on success, None on
        refusal. A seam, so the refusal branch is testable (PR #143, F3)."""
        from OCP.IFSelect import IFSelect_ReturnStatus  # type: ignore[attr-defined]
        from OCP.Interface import Interface_Static  # type: ignore[attr-defined]
        from OCP.STEPControl import (
            STEPControl_StepModelType,  # pyright: ignore[reportAttributeAccessIssue]
            STEPControl_Writer,  # pyright: ignore[reportAttributeAccessIssue]
        )

        writer = STEPControl_Writer()
        writer.Transfer(a.wrapped, STEPControl_StepModelType.STEPControl_AsIs)
        if writer.Write(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
            return None
        return str(Interface_Static.CVal_s("write.step.schema"))

    def _read_step(self, path: str) -> Any | None:
        """Read a STEP file back; the raw shape, or None on refusal."""
        from OCP.IFSelect import IFSelect_ReturnStatus  # type: ignore[attr-defined]
        from OCP.STEPControl import (
            STEPControl_Reader,  # pyright: ignore[reportAttributeAccessIssue]
        )

        reader = STEPControl_Reader()
        if reader.ReadFile(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
            return None
        reader.TransferRoots()
        return reader.OneShape()

    def min_wall(self, a: Any) -> Measurement | Unsupported:
        """The minimum wall for `measure`: the raw analysis as a Measurement,
        witness dropped. The runner's check branch uses `_min_wall_raw` and
        keeps the witness for the failure detail."""
        raw = self._min_wall_raw(a)
        if isinstance(raw, Unsupported):
            return raw
        if raw.get("vacuous"):
            return Unsupported(
                "no wall spans exist: every face pair meets at an edge, and "
                "corner features are not walls"
            )
        return _min_wall_measurement(raw)

    def _min_wall_raw(self, a: Any) -> dict[str, Any] | Unsupported:
        """Method E (#140), reworked after PR #144's review falsified the
        first draft's impossibility claim: the MEASURAND is now declared
        precisely, the bound is sound within it, and its escapes are
        recorded rather than denied.

        **Measurand**: the minimum span between NON-ADJACENT boundary faces
        through material, plus the certified diametric spans of closed
        analytic faces. `lo` is the minimum over ALL non-adjacent pairs of
        the kernel-exact distance — gap-classified pairs are RETAINED (PR
        #144, F2: any wall between two faces is at least their pair
        distance, so keeping the gap value is always sound; excluding the
        pair once took a real wall with it), which makes a gap-limited claim
        adjudicate approximate rather than falsely tight. A closed face's
        diametric span is included unless an EXACT boolean (its axis edge or
        tube circle against the solid) certifies the enclosed line is
        entirely void (PR #144, F1: a single probe point once discarded a
        rod's diameter because it landed in a cross-hole).

        `hi` is the smallest measurand member this can point to. Either a
        witnessed crossing — an inward normal ray whose first exit lands on a
        non-adjacent face, or on the same closed face — or the diametric span
        of a closed analytic face shown material along a chord (issue #145,
        item 2: the chord reaches a frustum's narrow rim, which the ray grid
        misses, and answers a frustum whose every normal exits through an
        adjacent cap). A RAY crossing below lo is not clamped away — it is
        proof the analysis contradicts itself, and the check refuses (PR #144,
        F3: the old clamp silenced exactly that counter-evidence). A certified
        span cannot go below lo: it is one of the values lo minimised over.

        **Recorded escapes** (SPEC-contract.md 4.11): material bounded by
        edge-SHARING faces — the web beside a drilled hole, a boss root —
        is outside the measurand (the shared-edge span tends to zero at the
        rim, which is the same geometry as a wedge tip); so is a wall whose
        two sides are one open non-analytic face (a folded sheet modeled as
        a single spline face). Neither is measured, and the spec says so.
        """
        from OCP.Bnd import Bnd_Box  # type: ignore[attr-defined]
        from OCP.BRepAdaptor import BRepAdaptor_Surface  # type: ignore[attr-defined]
        from OCP.BRepBndLib import BRepBndLib  # type: ignore[attr-defined]
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier  # type: ignore[attr-defined]
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # type: ignore[attr-defined]
        from OCP.GeomAbs import GeomAbs_SurfaceType  # type: ignore[attr-defined]
        from OCP.gp import gp_Pnt  # type: ignore[attr-defined]
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_IN, TopAbs_ON  # type: ignore[attr-defined]
        from OCP.TopExp import TopExp  # type: ignore[attr-defined]

        shape_map = _shape_maps()[0]
        faces = a.faces()
        solid = a.wrapped

        def point_inside(x: float, y: float, z: float) -> bool:
            probe = BRepClass3d_SolidClassifier(solid, gp_Pnt(x, y, z), 1e-7)
            return probe.State() in (TopAbs_IN, TopAbs_ON)

        best: float | None = None
        witness = ""
        self_span_faces: set[int] = set()
        span_chords: list[tuple[float, list[Chord]]] = []

        # -- certified self-spans of closed analytic faces ------------------
        for index, face in enumerate(faces):
            surf = BRepAdaptor_Surface(face.wrapped)
            if not (surf.IsUClosed() or surf.IsVClosed()):
                continue
            kind = surf.GetType()
            if kind == GeomAbs_SurfaceType.GeomAbs_Cylinder:
                cyl = surf.Cylinder()
                span = 2.0 * cyl.Radius()
                pos = cyl.Position()
                loc, axis = pos.Location(), pos.Direction()
                v1, v2 = surf.FirstVParameter(), surf.LastVParameter()
                include = _segment_has_material(
                    solid,
                    (loc.X() + axis.X() * v1, loc.Y() + axis.Y() * v1, loc.Z() + axis.Z() * v1),
                    (loc.X() + axis.X() * v2, loc.Y() + axis.Y() * v2, loc.Z() + axis.Z() * v2),
                )
            elif kind == GeomAbs_SurfaceType.GeomAbs_Sphere:
                sph = surf.Sphere()
                span = 2.0 * sph.Radius()
                centre = sph.Location()
                include = point_inside(centre.X(), centre.Y(), centre.Z())
            elif kind == GeomAbs_SurfaceType.GeomAbs_Torus:
                tor = surf.Torus()
                span = 2.0 * tor.MinorRadius()
                include = _circle_has_material(solid, tor)
            elif kind == GeomAbs_SurfaceType.GeomAbs_Cone:
                cone = surf.Cone()
                alpha = cone.SemiAngle()
                ref = cone.RefRadius()
                v1, v2 = surf.FirstVParameter(), surf.LastVParameter()
                radii = sorted(abs(ref + v * math.sin(alpha)) for v in (v1, v2))
                if radii[0] <= 1e-9:
                    continue  # the apex: a wedge-in-the-round, a feature
                span = 2.0 * radii[0]
                pos = cone.Position()
                loc, axis = pos.Location(), pos.Direction()
                a1, a2 = v1 * math.cos(alpha), v2 * math.cos(alpha)
                include = _segment_has_material(
                    solid,
                    (loc.X() + axis.X() * a1, loc.Y() + axis.Y() * a1, loc.Z() + axis.Z() * a1),
                    (loc.X() + axis.X() * a2, loc.Y() + axis.Y() * a2, loc.Z() + axis.Z() * a2),
                )
            else:
                return Unsupported(
                    f"face_{index} is a closed {_surface_name(kind)} surface "
                    "with no analytic self-span; a sampled span has no "
                    "guaranteed bound, so the wall cannot be certified"
                )
            if include is None:
                include = True  # an unanswerable certificate stays in: lo only shrinks
            if not include:
                continue  # the enclosed line is certified void: a bore, not a wall
            self_span_faces.add(index)
            span_chords.append((span, _diametric_chords(surf, kind)))
            if best is None or span < best:
                best, witness = span, f"face_{index} self-span"

        # -- adjacency by shared edges (IsSame-keyed via OCCT maps) ---------
        global_edges = shape_map()
        TopExp.MapShapes_s(solid, TopAbs_EDGE, global_edges)
        edge_sets: list[set[int]] = []
        for face in faces:
            face_edges = shape_map()
            TopExp.MapShapes_s(face.wrapped, TopAbs_EDGE, face_edges)
            edge_sets.append(
                {
                    global_edges.FindIndex(face_edges.FindKey(k))
                    for k in range(1, face_edges.Extent() + 1)
                }
            )

        boxes = []
        for face in faces:
            box = Bnd_Box()
            BRepBndLib.Add_s(face.wrapped, box)
            boxes.append(box)

        # -- the pair loop: every non-adjacent pair counts, AABB-pruned -----
        pair_seen = False
        gap_limited = False
        for i in range(len(faces)):
            for j in range(i + 1, len(faces)):
                if edge_sets[i] & edge_sets[j]:
                    continue  # shared edge: a feature, and a recorded escape
                pair_seen = True
                if best is not None and boxes[i].Distance(boxes[j]) >= best:
                    continue  # sound pruning: box distance <= true distance
                extrema = BRepExtrema_DistShapeShape(faces[i].wrapped, faces[j].wrapped)
                if not extrema.IsDone() or extrema.NbSolution() == 0:
                    return Unsupported(
                        f"the kernel could not resolve the distance between "
                        f"face_{i} and face_{j}; the bound would not be guaranteed"
                    )
                distance = extrema.Value()
                if best is not None and distance >= best:
                    continue
                p1, p2 = extrema.PointOnShape1(1), extrema.PointOnShape2(1)
                mid_in = point_inside(
                    (p1.X() + p2.X()) / 2, (p1.Y() + p2.Y()) / 2, (p1.Z() + p2.Z()) / 2
                )
                best, witness = distance, f"face_{i}/face_{j}"
                gap_limited = not mid_in

        if best is None:
            return {"vacuous": True, "pair_seen": pair_seen}

        hi = self._min_wall_witnessed_span(a, faces, edge_sets, self_span_faces, witness, best)
        certified = _certified_self_span(solid, span_chords, hi)
        if certified is not None:
            # A diametric span shown to be material caps the interval as
            # surely as a ray crossing does — and it reaches the narrow rim of
            # a frustum, where a fixed sampling grid does not (issue #145,
            # item 2). `_certified_self_span` returns only spans below `hi`,
            # so this can never loosen the upper end it was given.
            hi = certified
        if hi is None:
            return Unsupported(
                "no witnessed span could be measured, so the interval has no "
                "upper end and the wall cannot be honestly bounded"
            )
        if hi < best - 1e-9 * max(1.0, best):
            # The tripwire (PR #144, F3): a real crossing thinner than the
            # certified lower bound means the analysis contradicts itself.
            return Unsupported(
                f"the analysis contradicts itself: a witnessed crossing of "
                f"{hi:.6g} mm is thinner than the certified bound {best:.6g} mm "
                "— the wall cannot be honestly bounded"
            )
        # Below the tripwire threshold an inversion is float noise; the
        # interval is kept coherent. This is NOT the old clamp: a real
        # contradiction has already refused above.
        return {
            "lo": best,
            "hi": max(hi, best),
            "witness": witness,
            "gap_limited": gap_limited,
        }

    def _min_wall_witnessed_span(
        self,
        a: Any,
        faces: list[Any],
        edge_sets: list[set[int]],
        self_span_faces: set[int],
        witness: str,
        floor: float,
    ) -> float | None:
        """The smallest measurand-consistent witnessed crossing: an inward
        normal ray from a realizing face whose FIRST exit lands on a
        non-adjacent face, or crosses the same closed face diametrically.
        Adjacent-face exits are outside the measurand (the drilled-web
        escape) and are skipped, not silenced — a kept crossing below the
        lower bound trips the caller's refusal."""
        from OCP.BRepAdaptor import BRepAdaptor_Surface  # type: ignore[attr-defined]
        from OCP.BRepGProp import BRepGProp_Face  # type: ignore[attr-defined]
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Vec  # type: ignore[attr-defined]
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector  # type: ignore[attr-defined]
        from OCP.TopAbs import TopAbs_FACE  # type: ignore[attr-defined]
        from OCP.TopExp import TopExp  # type: ignore[attr-defined]

        shape_map = _shape_maps()[0]

        face_map = shape_map()
        TopExp.MapShapes_s(a.wrapped, TopAbs_FACE, face_map)
        intersector = IntCurvesFace_ShapeIntersector()
        intersector.Load(a.wrapped, 1e-9)

        indices = []
        for token in witness.split("/"):
            if token.startswith("face_"):
                indices.append(int(token.split("_")[1].split()[0]))
        hi: float | None = None
        for index in indices:
            face = faces[index]
            surf = BRepAdaptor_Surface(face.wrapped)
            prop = BRepGProp_Face(face.wrapped)
            u1, u2 = surf.FirstUParameter(), surf.LastUParameter()
            v1, v2 = surf.FirstVParameter(), surf.LastVParameter()
            steps = 6
            for iu in range(1, steps):
                for iv in range(1, steps):
                    u = u1 + (u2 - u1) * iu / steps
                    v = v1 + (v2 - v1) * iv / steps
                    pnt, vec = gp_Pnt(), gp_Vec()
                    prop.Normal(u, v, pnt, vec)
                    length = vec.Magnitude()
                    if length < 1e-12:
                        continue
                    direction = gp_Dir(-vec.X() / length, -vec.Y() / length, -vec.Z() / length)
                    line = gp_Lin(pnt, direction)
                    intersector.Perform(line, 1e-6, 1e9)
                    if not intersector.IsDone() or intersector.NbPnt() == 0:
                        continue
                    nearest = min(
                        range(1, intersector.NbPnt() + 1),
                        key=lambda k: intersector.WParameter(k),
                    )
                    span = intersector.WParameter(nearest)
                    exit_face = intersector.Face(nearest)
                    exit_index = face_map.FindIndex(exit_face) - 1
                    if exit_index == index:
                        if index not in self_span_faces:
                            continue  # same open face: the folded-sheet escape
                    elif exit_index >= 0 and edge_sets[index] & edge_sets[exit_index]:
                        continue  # adjacent exit: the drilled-web escape
                    if hi is None or span < hi:
                        hi = span
        return hi

    def blend_radii(self, a: Any) -> Measurement | Unsupported:
        """Radii of every partial-wrap cylindrical surface, sorted ascending.

        The blend candidates a `fillet_radius` claim ranges over
        (SPEC-contract.md 4.7). Partial wrap is the definition: a full wrap is
        a bore or a boss, whose radii are `hole_diameter`'s business, and the
        clustering shared with `bore_table` is what stops a seam-split bore's
        two half faces from masquerading as blends. Both orientations count —
        a convex-corner round and a concave-corner fillet are the same claim —
        and so do slot ends and grooves, deliberately: nothing at the surface
        level distinguishes them from fillets, and for the machinability claim
        this kind exists for they constrain the tool identically.
        """

        clusters = self._cylinder_clusters(a)
        if isinstance(clusters, Unsupported):
            return clusters
        radii = sorted(c["radius"] for c in clusters if c["wrap"] < 2 * math.pi - 1e-6)
        return Measurement(
            tuple(radii),
            "mm",
            exact=True,
            axes=tuple(f"blend_{i + 1}" for i in range(len(radii))),
        )

    def bores(self, a: Any) -> Measurement | Unsupported:
        """Diameters of every cylindrical bore on the shape, sorted descending.

        A bore is a set of cylindrical faces sharing one axis line, one radius
        and one **contiguous axial span**, that (a) face **inward** — the
        surface normal points toward the axis, so material surrounds the void;
        a boss is the same surface facing out — and (b) wrap the **full
        circle**: angular extents summing to 2π. Full-wrap is what keeps a
        concave fillet (a quarter-wrap) and a half-round groove (a half-wrap)
        from being counted as holes they are not. Coaxial groups of different
        radius stay distinct, so a counterbore reports one bore per diameter —
        each portion is a real seat with a real drawing callout. The axial-span
        clustering is what makes two aligned holes through two clevis lugs
        count as the two bores the drawing calls out, not one.

        Diameters are read from the BREP surface parameter, so they are exact:
        the predicted first exercise of `approximate` (POST-V0 §4) did not
        materialise, because a modelled cylinder's radius is a parameter, not
        an estimate.
        """
        table = self.bore_table(a)
        if isinstance(table, Unsupported):
            return table
        diameters = [bore["d"] for bore in table]
        return Measurement(
            tuple(diameters),
            "mm",
            exact=True,
            axes=tuple(f"bore_{i + 1}" for i in range(len(diameters))),
        )

    def raycast(self, a: Any, origin: Vec3, direction: Vec3) -> Unsupported:
        """Not implemented on this tier yet.

        `find_intersection_points` exists in build123d, but no check calls
        this primitive. `min_wall` shipped (#140) and casts its own rays
        through `IntCurvesFace_ShapeIntersector` inline, so the stated reason
        for deferring this one — that min_wall would need it — is spent; what
        is left is that nothing needs it. Declared absent rather than
        written untested.
        """
        return Unsupported("raycast is not implemented on the occt tier yet")
