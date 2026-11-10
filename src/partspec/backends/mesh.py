"""The mesh backend: measures a triangle mesh, which is what OpenSCAD emits.

Every quantity here is reported `exact`, and that is not a shortcut. Under D15 a
measurement describes *the artifact as authored and exported*, and a mesh **is** a
polyhedron — its volume, area, bounding box, watertightness, solid count and genus
are computed exactly from its triangles. There is no smooth ideal being
approximated, so there is no tessellation error to bound. Changing $fn does not
degrade a measurement; it produces a *different part*, which is a design change
the tool should report loudly rather than absorb into an error bar.

**Exactness is conditional on the mesh being what the measurement presumes.**
Volume and centre of mass are integrals over a closed, consistently-wound
surface; genus is the Euler characteristic of a closed one; a body count is
determined only where no edge is shared by more than two faces. Where a mesh
fails the precondition, the honest answer is `Unsupported` — returning a number
anyway is the second of the three failure modes this tool exists to prevent, and
it was doing exactly that until 2026-08-05 (dogfood F14).

The one genuine inexactness is float32 quantisation in binary STL (~1e-7
relative), which is narrower than the comparison epsilon and so carries no
information — see `SPEC-backend.md` 5.2 for why collapsing it is permitted here
and nowhere else.

Spec: SPEC-backend.md section 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..backend import BuildError, Tier, Unsupported, Vec3, effective_timeout
from ..engines import openscad
from ..install import install_hint
from ..status import Measurement

__all__ = ["CAPABILITIES", "MeshBackend"]

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
        "triangles",
        "min_distance",
        "intersect_volume",
        "region_solid",
    }
)
"""What this tier can answer at all. `topology_counts` is absent on purpose: a
triangle count is not a face count, and returning one is exactly the failure this
tool exists to prevent."""


class MeshBackend:
    """Measures a triangle mesh. Currently fed by OpenSCAD.

    Nothing here is OpenSCAD-specific — a tessellated OCCT shape would measure
    identically — but OpenSCAD is the only producer in v0.
    """

    kind = Tier.MESH
    engine = "openscad"

    def __init__(self) -> None:
        self._version: str | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def engine_version(self) -> str:
        if self._version is None:
            self._version = openscad.version()
        return self._version

    def build(
        self,
        source: openscad.OpenSCADSource,
        out_dir: Path,
        *,
        timeout_s: float | None = None,
        deps_out: list[Any] | None = None,
        unresolved_out: list[str] | None = None,
    ) -> Any | BuildError:
        result = openscad.render(
            source,
            out_dir,
            timeout_s=effective_timeout(timeout_s),
            deps_out=deps_out,
            unresolved_out=unresolved_out,
        )
        if isinstance(result, BuildError):
            return result
        return self.load(result)

    def load(self, stl: Path) -> Any | BuildError:
        """Load an exported mesh.

        `load_mesh` explicitly rather than `load`: the latter can return a Scene
        for a multi-body file, which has different semantics for the same
        attribute names. A silent type change is not something a measurement
        layer should be exposed to.

        The import is guarded because this is the first line of the mesh tier a
        `pip install partspec` user reaches, and it is the whole onboarding
        path. Unguarded it raised `ModuleNotFoundError: No module named
        'trimesh'` as a bare traceback, wrote no origin, and the run's generic
        hint blamed "a native segfault/OOM in the CAD kernel" — a machine fault
        described as a crash in an engine that was never installed. The OCCT
        tier has classified this correctly since v0.4.0
        (`pycad._engine_import_error`); this is the mesh tier catching up.

        `origin="environment"` is the load-bearing part: SPEC-report §6.1 says
        an environment fault MUST NOT be reported as a statement about the
        part, and `build_origin` is the key `AGENT-CONTRACT.md` §2.3 routes on.
        """
        try:
            import trimesh
        except ImportError as exc:
            return BuildError(
                f"the mesh tier is not importable: {exc}",
                hint=install_hint("'partspec[mesh]'"),
                origin="environment",
            )

        mesh = trimesh.load_mesh(stl)
        if getattr(mesh, "faces", None) is None or len(mesh.faces) == 0:
            return BuildError(f"exported mesh has no triangles: {stl}")
        return mesh

    def capabilities(self) -> frozenset[str]:
        return CAPABILITIES

    def provenance(self, a: Any) -> dict[str, Any]:
        """The report's `geometry` block.

        Takes the artifact rather than reading instance state: a backend that
        remembers its last build is one shared instance away from reporting
        provenance for the wrong part.

        Both counts, not either. `distinct_normals` is the identity signal: it
        tracks $fn one-to-one (a cylinder at $fn=n gives n+2) and is invariant
        under retriangulation, so two runs of the same design agree even if the
        triangulation differs. `triangles` is the drift explainer, because chord
        error scales with edge length.
        """
        return {
            "triangles": len(a.faces),
            "distinct_normals": _distinct_normals(a),
        }

    # -- the primitives ----------------------------------------------------

    def bbox(self, a: Any) -> Measurement:
        extents = tuple(float(v) for v in a.extents)
        return Measurement(extents, "mm", exact=True, axes=("x", "y", "z"))

    def volume(self, a: Any) -> Measurement | Unsupported:
        """Enclosed volume, by the divergence theorem over the triangles.

        Refused unless the mesh is a closed, consistently-wound surface, because
        the integral presumes one. On an open mesh it does not diverge or raise —
        it quietly returns a plausible number: a cube missing one face reported
        500.0 against a true 1000.0, flagged exact. That number is not a bad
        estimate of the volume, it is not a volume at all.
        """
        reason = _not_a_solid(a)
        if reason is not None:
            return Unsupported(f"volume is the integral over a closed surface; {reason}")
        return Measurement(float(a.volume), "mm3", exact=True)

    def area(self, a: Any) -> Measurement:
        """Surface area — the sum of the triangle areas.

        Ungated, unlike volume: a sum over the exported triangles is well defined
        whatever they enclose, and refusing it would be its own dishonesty.
        """
        return Measurement(float(a.area), "mm2", exact=True)

    def center_of_mass(self, a: Any) -> Measurement | Unsupported:
        """Centroid of the enclosed solid — the same integral as `volume`, and
        refused on the same precondition. The open cube above put its centre of
        mass at (-2.5, 0, 0), outside the material.

        Closedness is necessary and not sufficient: the centroid is that
        integral *divided by* the volume, so a closed surface enclosing none has
        no centre of mass. trimesh divides in numpy, which yields `nan` rather
        than raising, and `Measurement` then refuses that — correctly, but by
        raising, which took the whole `measure` run down with it (#365). The
        second precondition is stated here, where the inability to answer is
        known, so the caller sees a refusal with a reason. `intersection()` of
        two cubes meeting on a face reaches it: 2021.01 and 2026.08.01 both
        export the same 4-facet zero-thickness sheet, closed and consistently
        wound, area 480.0 mm2 and volume 0.0. The OCCT tier already refuses the
        analogous shape, in almost these words.
        """
        reason = _not_a_solid(a)
        if reason is not None:
            return Unsupported(f"centre of mass is an integral over a closed surface; {reason}")
        if not float(a.volume):
            return Unsupported(
                "this mesh encloses no volume, so it has no centre of mass (check volume first)"
            )
        com = tuple(float(v) for v in a.center_mass)
        return Measurement(com, "mm", exact=True, axes=("x", "y", "z"))

    def is_valid(self, a: Any) -> Measurement:
        """Diagnostic only — deliberately not a check kind.

        `is_volume` here means closed, consistently wound and of non-zero
        volume; on the OCCT tier `is_valid` means the BREP passes
        `BRepCheck_Analyzer`, which is a different question with a different
        answer (an open shell is `is_valid` True there and False here). A check
        whose meaning changes with the tier is exactly what "one contract,
        evaluated identically wherever it can be" forbids, so this is surfaced
        through `measure` and left out of the vocabulary.
        """
        return Measurement(bool(a.is_volume), "bool", exact=True)

    def watertight(self, a: Any) -> Measurement:
        return Measurement(bool(a.is_watertight), "bool", exact=True)

    def watertight_detail(self, a: Any) -> str | None:
        """Why a mesh is not watertight — boundary edges or non-manifold ones.

        trimesh's `is_watertight` means "every edge is used by exactly two
        faces", which conflates two different defects: an edge used **once** is
        a hole, an edge used **more than twice** is a non-manifold junction
        where surfaces touch. They have different causes and different fixes, so
        reporting only "not watertight" makes the reader go and find out which.

        Found by dogfooding: a community gridfinity bin rendered by OpenSCAD's
        default Manifold backend has 0 boundary edges and 4 non-manifold ones,
        and "not watertight" alone reads as "it has holes", which it does not.
        """
        if a.is_watertight:
            return None
        boundary, nonmanifold = _edge_defects(a)
        parts = []
        if boundary:
            parts.append(f"{boundary} boundary edge(s) — the surface is open")
        if nonmanifold:
            parts.append(
                f"{nonmanifold} non-manifold edge(s) — more than two faces meet along them"
            )
        return "; ".join(parts) or "not watertight for an unclassified reason"

    def solid_count(self, a: Any) -> Measurement | Unsupported:
        """Solids, counted over the exported triangles.

        **A solid is a closed, outward-oriented surface component.** Counting
        components instead was wrong twice over, and both errors were measured
        against the OCCT tier, which has been right all along:

        * A block with a *sealed cavity* is one solid, not two. Its boundary has
          two components — the outer shell and the void's inner shell — and the
          old count returned 2 where `TopoDS.solids()` returns 1. This is not
          academic: run under an agent loop, the false failure had no model-side
          remedy, so the agent drilled a vent bore the design never asked for in
          order to turn the check green (`evals/BASELINE.md`).
        * An *open* shell bounds no solid, so it is 0, not 1. The old count said
          1 where the OCCT tier says 0.

        Orientation is what separates the two: under the divergence theorem an
        outward-oriented closed component encloses positive volume and a cavity's
        inner shell, wound inward as seen from itself, encloses negative volume.

        Computed here rather than delegated, because both obvious delegates are
        wrong. trimesh's `body_count` routes through `graph.connected_components`
        and raises ImportError without scipy, which the `mesh` extra does not
        install. manifold3d answers, but only after silently rebuilding the mesh
        — measured on a clean gridfinity bin it retriangulated 55 of 10,688
        triangles and moved the enclosed volume by 25.31 mm3, so its answer
        describes its own reconstruction rather than the exported artifact,
        which D15 forbids.

        Refused where any edge is shared by more than two faces, because there
        the count is **not determined by the geometry**: counting through such a
        junction and counting across it give different answers, and nothing in
        the mesh says which was meant. On the F10 bin manifold3d welds and says
        1 while the exported triangles say 3 (a body plus two stray 2-triangle
        slivers). Both are defensible, which is precisely why neither may be
        reported as exact.
        """
        reason = _bodies_undetermined(a)
        if reason is not None:
            return Unsupported(reason)
        return Measurement(_shell_census(a).solids, "count", exact=True)

    def cavities(self, a: Any) -> Measurement | Unsupported:
        """Sealed internal voids — closed components wound inward.

        The third Betti number of the boundary, and the quantity `solid_count`
        used to be quietly conflated with. A contract that means "one block with
        one sealed void" can now say so, instead of being forced to describe the
        void as a second solid.
        """
        reason = _bodies_undetermined(a)
        if reason is not None:
            return Unsupported(reason)
        return Measurement(_shell_census(a).cavities, "count", exact=True)

    def genus(self, a: Any) -> Measurement | Unsupported:
        """Topological genus — through-holes — for a single closed body.

        From the Euler characteristic of the exported triangles, `g = (2 - X)/2`
        with `X = V - E + F`. Unlike the BREP tier, where faces carry inner wires
        and the naive form is quietly wrong, on a triangle mesh every face is a
        disc and `V - E + F` is simply correct.

        Three preconditions, each refused rather than assumed:

        * **Closed.** The Euler characteristic of an open surface does not give a
          genus. A cube missing one face reported genus 1 before this was
          checked — a through-hole that does not exist.
        * **One body.** Genus is defined per body; the characteristic of a
          complex is a different number. Two disjoint boxes give -1, not 0.
        * **One fan of faces at every vertex.** Where the surface touches itself
          at a single vertex every edge still has its two faces, so the first
          test passes, and `V` is one short of either surface the touch could
          be read as. A sphere pinched once has X = 1 and reported genus 1
          before this was checked; pinched twice it has X = 0 and reported the
          same, so the parity of X is not the test (#437).

        `V` counts *referenced* vertices only, so a stray unreferenced vertex
        cannot inflate it. Duplicate coincident vertices would break the count,
        but cannot occur here: closedness means every edge is used exactly twice,
        which is impossible on an unwelded mesh, so the precondition guarantees
        its own input.
        """
        reason = _not_closed(a)
        if reason is not None:
            return Unsupported(f"genus is defined for a closed surface; {reason}")
        census = _shell_census(a)
        if census.solids != 1:
            return Unsupported(
                f"genus is defined per body; this part has {census.solids} solids "
                f"(check solid_count first, or split the part)"
            )
        pinched = _pinched_vertices(a)
        if pinched:
            noun = "vertex" if pinched == 1 else "vertices"
            return Unsupported(
                f"genus is defined for a surface with one fan of faces at every vertex; "
                f"this mesh touches itself at {pinched} {noun}, "
                f"where joining the fans and parting them give different counts"
            )
        # G = S - X/2 over *all* shells, matching the OCCT tier. The naive
        # (2 - X)/2 assumes one shell and so is wrong by exactly the cavity
        # count: a block with a sealed void has X = 4 and reported genus -1,
        # a handle that does not exist.
        shells = census.solids + census.cavities
        return Measurement(shells - _euler_characteristic(a) // 2, "count", exact=True)

    def topology_counts(self, a: Any) -> Unsupported:
        """Always refused on this tier.

        A mesh has triangles, not engineering topology. Reporting a triangle
        count as a face count is precisely how PartCAD's OpenSCAD path misleads:
        the query runs, returns a number, and nothing signals that the number
        means something else.
        """
        return Unsupported(
            "a triangle mesh has no engineering topology; face and edge counts "
            "would be triangle counts wearing the wrong name",
            requires=Tier.OCCT,
        )

    def triangles(self, a: Any) -> Any:
        return a.triangles

    def min_distance(self, a: Any, b: Any) -> Measurement | Unsupported:
        ma, mb = _manifold(a), _manifold(b)
        if isinstance(ma, Unsupported):
            return ma
        if isinstance(mb, Unsupported):
            return mb
        return Measurement(float(ma.min_gap(mb, 1e6)), "mm", exact=True)

    def intersect_volume(self, a: Any, b: Any) -> Measurement | Unsupported:
        ma, mb = _manifold(a), _manifold(b)
        if isinstance(ma, Unsupported):
            return ma
        if isinstance(mb, Unsupported):
            return mb
        return Measurement(float((ma ^ mb).volume()), "mm3", exact=True)

    def bores(self, a: Any) -> Unsupported:
        """Defense-in-depth, like `topology_counts`: the capability is not
        declared so the runner never dispatches here, but a direct caller must
        get the refusal, not an AttributeError."""
        return _no_cylindrical_face("a bore diameter")

    def bore_table(self, a: Any) -> Unsupported:
        """Same refusal as `bores`, for the positional view `bolt_circle` uses."""
        return self.bores(a)

    def blend_radii(self, a: Any) -> Unsupported:
        """Same refusal again: a fillet fitted to facets is not a fillet."""
        return _no_cylindrical_face("a blend radius")

    # The depth epic's four (SPEC-contract 4.8-4.11). Defined here for the
    # same reason `bores` and `blend_radii` are: the runner consults
    # `capabilities()` first so it never dispatches to these, but SPEC-backend
    # §3.1 says a backend that cannot answer MUST return `Unsupported` rather
    # than raise, and a direct caller getting an AttributeError from a library
    # is exactly the failure that rule exists to prevent. Adding them to the
    # Protocol without adding them here is what made `isinstance(MeshBackend(),
    # GeometryBackend)` false (PR #151 review, R3).

    def draft_angle(self, a: Any, direction: tuple[float, float, float]) -> Unsupported:
        """A facet's normal is the tessellation's, not the surface's: every
        draft angle read off a mesh is an artifact of $fn."""
        return Unsupported(
            "a facet's normal is the tessellation's, not the surface's, so a "
            "draft angle read off a mesh varies with $fn and carries no bound",
            requires=Tier.OCCT,
        )

    def self_intersection_free(self, a: Any) -> Unsupported:
        """Mesh self-intersection needs a dependency that is either GPL
        (libigl/CGAL) or heavyweight (pymeshlab) — an open question (D14),
        not a capability this tier quietly has."""
        return Unsupported(
            "a mesh self-intersection test needs a library this tier does not "
            "carry; answering from watertightness alone would miss the case",
            requires=Tier.OCCT,
        )

    def step_roundtrip(self, a: Any) -> Unsupported:
        """STEP is a BREP exchange format. A mesh written to STEP round-trips
        its triangles, which says nothing about the part's fidelity."""
        return Unsupported(
            "STEP carries BREP; a triangle mesh has none, so a round trip "
            "would measure the tessellation surviving, not the part",
            requires=Tier.OCCT,
        )

    def min_wall(self, a: Any) -> Unsupported:
        """The recorded refusal (POST-V0 §5): sampling is one-sided by
        construction, so no principled lower bound exists on this tier."""
        return Unsupported(
            "sampling a mesh can only ever find a thinner wall, never bound "
            "one from below, so no honest interval exists on this tier",
            requires=Tier.OCCT,
        )

    def region_solid(self, region: Any) -> Any:
        """Materialize a declared region as this tier's native solid.

        `process=False`: the vertices are the canonical list `region.mesh()`
        computes, identical on every tier by design (SPEC-contract.md 4.4), and
        trimesh's cleanup must not be allowed to perturb them.
        """
        import trimesh

        vertices, faces = region.mesh()
        return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

    def raycast(self, a: Any, origin: Vec3, direction: Vec3) -> list[Vec3] | Unsupported:
        """Ray/mesh intersection — and NOT a declared capability.

        It was in `CAPABILITIES` while `trimesh`'s default ray path indexes
        through `rtree`, which the `mesh` extra does not carry (the
        accelerated engine is embree, and needs no rtree): a declared
        capability that raises is the exact thing §3.2 says capabilities
        exist to prevent, and adding a spatial-index dependency to the
        smallest useful install for a primitive no check calls is the wrong
        trade. Undeclared and working-when-available is honest; declared and
        raising was not.
        """
        try:
            locations = a.ray.intersects_location(
                ray_origins=[list(origin.as_tuple())],
                ray_directions=[list(direction.as_tuple())],
            )[0]
        except ImportError as exc:  # rtree absent: refuse, never raise (SPEC-backend 3.1)
            return Unsupported(f"the mesh tier's ray engine is unavailable: {exc}")
        return [Vec3(*(float(c) for c in point)) for point in locations]


def _distinct_normals(mesh: Any) -> int:
    """Count distinct face normals.

    Deliberately NOT trimesh's `.facets` (coplanar-region grouping), which needs
    scipy or networkx — a large dependency for one provenance field, against D14's
    "light, pure wheels". Distinct normals serve the same purpose: 6 for a cube,
    n+2 for a cylinder at $fn=n, and unchanged by subdivision.

    It differs from a true facet count only where two disjoint coplanar regions
    share a normal, which merges them. That is why the field is named for what it
    measures rather than borrowed from CGAL's vocabulary.

    Rounded to 4 decimals: the tolerance that makes two faces of one flat
    surface read as one normal despite float noise. Inlined rather than a
    parameter, because it was a parameter with a module constant for a
    default that no caller ever overrode.
    """
    import numpy as np

    normals = np.round(np.asarray(mesh.face_normals, dtype=np.float64), 4)
    normals += 0.0  # normalise -0.0 to 0.0 so it does not read as a distinct row
    return len(np.unique(normals, axis=0))


# --------------------------------------------------------------------------
# Surface classification — the preconditions the measurements presume
# --------------------------------------------------------------------------


def _edge_defects(mesh: Any) -> tuple[int, int]:
    """`(boundary_edges, non_manifold_edges)` — edges used once, and more than twice.

    The two defects are kept apart everywhere because they mean different things:
    a boundary edge is a hole in the surface, a non-manifold edge is a place
    where more than two sheets meet. They have different causes, different fixes,
    and — see `solid_count` — different consequences for what stays answerable.
    """
    import numpy as np

    _, counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    return int((counts == 1).sum()), int((counts > 2).sum())


def _not_closed(mesh: Any) -> str | None:
    """Why this surface is not closed, or None if it is."""
    if mesh.is_watertight:
        return None
    boundary, nonmanifold = _edge_defects(mesh)
    if boundary and nonmanifold:
        return f"this mesh has {boundary} boundary edge(s) and {nonmanifold} non-manifold edge(s)"
    if boundary:
        return f"this mesh is open along {boundary} boundary edge(s)"
    if nonmanifold:
        return f"this mesh has {nonmanifold} non-manifold edge(s)"
    return "this mesh is not watertight"


def _not_a_solid(mesh: Any) -> str | None:
    """Why this mesh does not bound a solid, or None if it does.

    Closedness plus consistent winding. Winding matters only here: the divergence
    theorem sums signed contributions, so a flipped triangle subtracts where it
    should add, whereas the combinatorial quantities are indifferent to it.
    """
    reason = _not_closed(mesh)
    if reason is not None:
        return reason
    if not mesh.is_winding_consistent:
        return "this mesh is closed but its triangle winding is inconsistent"

    # Consistent is not the same as correct. A uniformly inverted mesh is
    # perfectly consistent and encloses negative volume: an inside-out cube
    # measured -1000.0 mm3, flagged exact, and `volume(max=...)` passed on it
    # because every negative number is below every positive bound.
    #
    # Orientation is a precondition of the integral, not a property of the
    # answer, so it is refused here rather than corrected with abs(). The sign
    # is information: it says the normals point the wrong way, which is a real
    # defect in the exported artifact that a silent abs() would hide.
    census = _shell_census(mesh)
    if census.solids == 0 and census.cavities > 0:
        return (
            "this mesh is closed but wound inside-out — every component encloses "
            "negative volume, so its normals point inward"
        )
    return None


def _bodies_undetermined(mesh: Any) -> str | None:
    """Why the body count is not fixed by this mesh, or None if it is.

    Only non-manifold edges are disqualifying. An *open* mesh still has a
    determinate component count — every edge is used once or twice, so adjacency
    is unambiguous — and refusing there would be over-refusal, which inflates
    `incomplete` and is its own way of not answering an answerable question.
    """
    _, nonmanifold = _edge_defects(mesh)
    if not nonmanifold:
        return None
    return (
        f"this mesh has {nonmanifold} non-manifold edge(s), where counting "
        f"through the junction and counting across it give different answers"
    )


def _face_components(mesh: Any) -> Any:
    """Label every face with its connected component under shared-edge adjacency.

    Hooking plus pointer-jumping rather than a union-find, purely for speed: the
    scalar version costs 3.0 s on a 684k-triangle part against 1.8 s here and
    46 ms against 2.8 ms at a more typical 10k. Verified to produce partitions
    identical to union-find across closed, open, multi-body and non-manifold
    inputs.

    Terminates because labels are bounded below and never increase.

    Only ever called where `_bodies_undetermined` passed, which matters:
    trimesh's `face_adjacency` silently omits non-manifold edges, so on a mesh
    carrying them this would split components that the omitted edges joined.
    """
    import numpy as np

    n = len(mesh.faces)
    adjacency = np.asarray(mesh.face_adjacency, dtype=np.int64)
    labels = np.arange(n, dtype=np.int64)
    if len(adjacency) == 0:
        return labels

    return _hook(labels, adjacency[:, 0], adjacency[:, 1])


def _hook(labels: Any, left: Any, right: Any) -> Any:
    """Give joined items one label: `left[i]` and `right[i]` are joined."""
    import numpy as np

    while True:
        nxt = labels.copy()
        np.minimum.at(nxt, left, labels[right])
        np.minimum.at(nxt, right, labels[left])
        while True:  # collapse each chain to its root before the next round
            root = nxt[nxt]
            if np.array_equal(root, nxt):
                break
            nxt = root
        if np.array_equal(nxt, labels):
            return labels
        labels = nxt


def _pinched_vertices(mesh: Any) -> int:
    """How many vertices carry more than one fan of faces.

    A fan is the faces around a vertex joined through the edges that end at
    it. Each face has three corners; two corners at the same vertex are joined
    when their faces share an edge there, and a vertex whose corners fall into
    more than one group is where the surface touches itself.

    Only ever called on a closed mesh, where every edge has exactly two faces,
    so `face_adjacency` omits nothing.
    """
    import numpy as np

    faces = np.asarray(mesh.faces, dtype=np.int64)
    pairs = np.asarray(mesh.face_adjacency, dtype=np.int64)
    shared = np.asarray(mesh.face_adjacency_edges, dtype=np.int64)
    if len(pairs) == 0:
        return 0

    def corners(side: int) -> Any:
        """The corner of each pair's `side` face at each end of the shared edge."""
        face = np.repeat(pairs[:, side], 2)
        return 3 * face + (faces[face] == shared.reshape(-1, 1)).argmax(axis=1)

    fans = _hook(np.arange(faces.size, dtype=np.int64), corners(0), corners(1))
    per_vertex = np.unique(np.stack([faces.reshape(-1), fans], axis=1), axis=0)[:, 0]
    return int((np.bincount(per_vertex) > 1).sum())


def _no_cylindrical_face(what: str) -> Unsupported:
    """The refusal `bores`, `bore_table` and `blend_radii` share.

    One string, because they are one argument: a mesh has no cylindrical
    face, so any radius read off it is fitted to facets — and a fitted
    radius is smaller than the true one, which is a confident wrong number
    in the unsafe direction.
    """
    return Unsupported(
        f"a triangle mesh has no cylindrical face; {what} fitted to facets "
        "would be a confident wrong number in the unsafe direction",
        requires=Tier.OCCT,
    )


@dataclass(frozen=True, slots=True)
class _ShellCensus:
    """Connected boundary components, split by what they bound."""

    solids: int
    """Closed and outward-oriented: each bounds a solid."""
    cavities: int
    """Closed and inward-oriented: each is a sealed void inside a solid."""


def _shell_census(mesh: Any) -> _ShellCensus:
    """Classify each connected component by closedness and orientation.

    Signed volume is the discriminator, by the divergence theorem: summing
    `v0 . (v1 x v2) / 6` over a component's triangles gives the volume it
    encloses, positive when wound outward and negative when wound inward. A
    cavity's inner shell is, seen from itself, wound inward — which is precisely
    what distinguishes "a void in this solid" from "a second solid".

    Closedness is tested per component rather than over the whole mesh: a part
    may legitimately carry one closed body and one stray open sliver, and the
    open one must not be counted as a solid just because its neighbour is closed.

    Only ever called where `_bodies_undetermined` passed, so every edge is used
    once or twice and component membership is unambiguous.
    """
    import numpy as np

    faces = np.asarray(mesh.faces)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    labels = _face_components(mesh)

    solids = cavities = 0
    for label in np.unique(labels):
        tris = faces[labels == label]

        # Closed iff every edge in the component is shared by exactly two of its
        # own faces.
        edges = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        if not np.all(counts == 2):
            # Open: it bounds nothing, so it is neither a solid nor a cavity.
            # Skipped rather than counted — an open component promoted to a
            # solid because its neighbour was closed is the miscount this
            # per-component test exists to prevent.
            continue

        a, b, c = vertices[tris[:, 0]], vertices[tris[:, 1]], vertices[tris[:, 2]]
        signed = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0
        if signed >= 0.0:
            solids += 1
        else:
            cavities += 1

    return _ShellCensus(solids=solids, cavities=cavities)


def _euler_characteristic(mesh: Any) -> int:
    """`V - E + F` over the exported triangles.

    `V` counts referenced vertices rather than `len(mesh.vertices)`, so a stray
    unreferenced vertex — which is not part of the surface — cannot inflate it.
    """
    import numpy as np

    faces = np.asarray(mesh.faces)
    vertices = len(np.unique(faces))
    edges = len(np.unique(np.asarray(mesh.edges_sorted), axis=0))
    return vertices - edges + len(faces)


def _manifold(mesh: Any) -> Any | Unsupported:
    """Wrap a trimesh into a manifold3d Manifold, or refuse if it will not take.

    The guard is not defensive padding. Handed a cube missing one face,
    manifold3d returns an object reporting `Error.NotManifold`, `is_empty()` and
    zero triangles — and `.decompose()` on that empty object still returns a
    one-element list, `.genus()` still returns 1. Reading those without checking
    `status()` is how this backend came to report a through-hole in an open
    shell: the dependency raised its hand and nothing looked.

    Note also that manifold3d rebuilds the mesh it is given (see `solid_count`),
    so anything measured through here describes its reconstruction rather than
    the exported artifact. Tolerable for the relational primitives below, which
    compare two shapes; not tolerable for absolute measurements, which is why
    none now route through it.
    """
    import numpy as np
    from manifold3d import Error, Manifold, Mesh

    manifold = Manifold(
        Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        )
    )
    if manifold.status() != Error.NoError:
        return Unsupported(f"manifold3d rejected this mesh: {manifold.status()}")
    return manifold
