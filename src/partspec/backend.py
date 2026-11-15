"""The geometry backend protocol.

The finding this design rests on (investigations/03): cad-khana's build123d
coupling is *pervasive by type but shallow by behaviour* — twelve geometry
primitives carry its entire diagnostic vocabulary, and most of the valuable logic
is already engine-independent. So engine neutrality is not a rewrite; it is a
protocol over a dozen methods plus value types of our own.

Two backends, not three (D3). One OCCT backend serves build123d *and* CadQuery
via a `.wrapped` adopt shim at the front door — verified: both expose a
`TopoDS_Shape` from the same OCP module, and `bd.Solid(cq_shape.wrapped)` adopts
losslessly. The only genuinely separate backend is mesh, for OpenSCAD.

Spec: SPEC-backend.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from .status import Measurement

__all__ = [
    "DEFAULT_TIMEOUT_S",
    "BuildError",
    "GeometryBackend",
    "Tier",
    "Unsupported",
    "Vec3",
    "effective_timeout",
]

DEFAULT_TIMEOUT_S = 300.0
"""The build budget when nobody chose one, in seconds.

A bound exists by default because every consumer of a run assumes it
terminates: a bounded repair loop with an unbounded build step is a stall, not
a loop (#46). The value is a property of the run, not of the design — it is
set per invocation (`--timeout` / `PARTSPEC_TIMEOUT`), recorded in
`invocation.timeout_s`, and never lives in a contract.
"""


def bbox_block(lo, hi) -> dict[str, list[float]]:
    """The framing bbox as a payload block, shared by both render tiers.

    Recorded beside the images because the framing derives from it: two runs
    whose sizes differ uniformly render byte-identical pixels (the camera
    scales with the part), so the bbox is the only scale witness a visual
    diff has (#21). Stdlib on purpose — the OpenSCAD tier records it in
    environments that have no numpy."""
    return {
        "min": [round(float(c), 6) for c in lo],
        "max": [round(float(c), 6) for c in hi],
    }


def effective_timeout(timeout_s: float | None) -> float | None:
    """Resolve a requested budget to the one a backend enforces.

    `None` means nobody chose — the default applies. `0` is the explicit
    waiver — the build runs unbounded, chosen rather than defaulted, so an
    unbounded run is always something someone asked for. Positive values are
    themselves. The two tiers share this mapping so `--timeout` means one
    thing regardless of engine.
    """
    if timeout_s is None:
        return DEFAULT_TIMEOUT_S
    if timeout_s == 0:
        return None
    return timeout_s


# `Transform` and `Plane` are deliberately absent in v0. They are needed for
# placement and datum targets, which are assembly concerns (D11). Adding them
# later is additive and breaks nothing.


@dataclass(frozen=True, slots=True)
class Vec3:
    x: float
    y: float
    z: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


class Tier:
    """Capability class of a backend, as opposed to its implementation."""

    MESH = "mesh"
    OCCT = "occt"


@dataclass(frozen=True, slots=True)
class Unsupported:
    """A backend's honest refusal — a *return value*, never an exception.

    This is the protocol-level enforcement of the rule that gives the tool its
    point. A backend MUST NOT satisfy a query by reconstructing an entity its
    representation does not contain, and it MUST NOT return a plausible-looking
    number in place of an answer.

    It is also precisely where PartCAD goes wrong: by normalising an OpenSCAD
    mesh into a faceted TopoDS_Shape, its topology queries *run* and return
    triangle counts dressed as engineering topology, with no capability
    declaration and no degradation signal.

    The second, less obvious route here is a quantity with no honest error
    bound. Wall thickness is sampled on both tiers, and sampling is one-sided by
    construction — more samples can only ever find a *thinner* wall — so a
    measurement is an upper bound on the true minimum, not an interval. That is
    `Unsupported`, not `approximate`.
    """

    reason: str
    requires: str | None = None
    """The tier that would answer *for an equivalent part*. The hedge matters:
    porting a 16-gon bore to build123d does not merely enable the check, it
    changes the part."""


@dataclass(frozen=True, slots=True)
class BuildError:
    """The engine failed to produce an artifact.

    `origin` separates two failures that used to be reported identically and
    mean opposite things. `"model"` is a statement about the part -- the design
    does not compile -- and adjudicates as a failing `builds` check, exit 1.
    `"environment"` is not a statement about the part at all: no engine on PATH,
    a mistyped pin, a missing package, an absent source file, a render that ran
    out of time. Every one of those used to land on `builds: fail`, so a CI run
    on a machine without OpenSCAD reported the *design* as disproven.

    `None` is the third state, and it is a claim of its own: partspec CANNOT
    attribute this failure. A name the engine did not resolve is genuinely
    ambiguous -- a misspelt module is the model's, a library absent from
    `OPENSCADPATH` is the environment's -- and SPEC-report §6.1 already refuses
    to guess, which is why `report.build_origin` is null there. The field had
    only two spellings until #307, so the render path's failure payload
    published `"model"` by default: the exact misattribution `origin` exists to
    prevent, asserted where the tool knows nothing. Every consumer MUST handle
    it explicitly, and `runner.py`'s adjudication branches on `!= "model"`
    rather than on `== "environment"` for this reason: `builds: fail` is the
    only arm that makes a claim about the design, so it is the only one a
    `None` may not fall into.
    """

    message: str
    hint: str | None = None
    origin: Literal["environment", "model"] | None = "model"
    stderr: str | None = None
    """The engine's full stderr, when the failure came from a subprocess.

    `hint` is one selected line; selection can be wrong, so the unabridged
    diagnosis rides along and reaches the report (#37). None for failures
    with no engine output (missing binary, unbound parameter)."""

    produced_nothing: bool = False
    """The engine completed and the result was EMPTY, rather than the engine
    failing to run.

    A null intersection is the motivating case: two parts with no
    positive-volume interference render nothing, which is a real answer and,
    for an interference probe, the passing one (SPEC-contract §4.12).
    Distinguished here rather than in the runner because the
    evidence is an engine-specific string, and engines own their own strings.
    A contract can declare that outcome with `p.empty()` (SPEC-contract 4.12);
    without such a declaration this changes nothing and the failure is a
    failure."""

    unresolved: tuple[str, ...] = ()
    """Diagnostic lines saying the engine built something other than the source.

    Three causes, and the field carries all of them: a name the engine could
    not resolve, a value it could not convert, where it substitutes a default
    (#308), and the model's own `assert()` failing, which stops evaluation
    (#400). `engines.openscad.is_substituted_value` and `is_failed_assertion`
    tell them apart for a caller that has to name one.

    An empty result means two very different things — "the intersection is
    genuinely null" and "a module name was misspelt, an include did not open,
    or a transform's argument would not convert, so the geometry never existed
    to intersect". On OpenSCAD 2021.01 both exit 1 with the same
    `Current top level object is empty.`, so the exit code cannot separate them
    and the warning lines above it are the only evidence that can. Carried so
    `empty` can refuse to be satisfied by a broken probe; an empty result with
    these lines is a laundered pass, which is the one outcome this whole check
    must not produce (#237)."""


@runtime_checkable
class GeometryBackend(Protocol):
    """What every backend implements.

    Every primitive either backend implements, plus lifecycle and an explicit
    capability declaration. Both backends DEFINE every member and satisfy
    `isinstance` at runtime: an OCCT-only primitive is still defined on the
    mesh backend, returning `Unsupported` with `requires="occt"`, because §3.1
    says a backend that cannot answer must refuse rather than raise — and an
    AttributeError from a library call is the kind of failure a caller
    misreads. (Static assignability is a weaker story and predates this: both
    declare `engine_version` as a property, and the OCCT tier widens some
    return types to `Measurement | Unsupported`.) Each returns a `Measurement` carrying its own
    `exact` flag, so a caller cannot accidentally lose provenance by receiving
    a bare float.

    No count in this sentence, deliberately: it read "sixteen" while the block
    held seventeen and the backends implemented twenty-two, and a number in a
    docstring is a claim that rots. SPEC-backend §3 does not hold a second copy
    of this block to be compared against — it is generated from this class by
    `scripts/gen_docs.py`, so there is nothing to disagree with. This docstring
    is stripped on the way in; the spec carries its own prose.
    """

    kind: str  # Tier.MESH | Tier.OCCT
    engine: str  # "openscad" | "build123d" | "cadquery"
    engine_version: str

    # --- lifecycle ---

    def build(
        self,
        source: Any,
        out_dir: Any,
        *,
        timeout_s: float | None = None,
        deps_out: list[Any] | None = None,
        unresolved_out: list[str] | None = None,
    ) -> Any | BuildError:
        """Run the engine and return an opaque artifact handle.

        `timeout_s` is interpreted through `effective_timeout` — None defaults,
        0 waives, positive bounds — and a blown budget is a `BuildError` with
        `origin="environment"`: a stopwatch disproves nothing about the part.

        `deps_out`, when given, receives what the engine reports it actually
        read (#226) — one `openscad.RenderDeps` on the mesh tier, nothing on a
        tier whose engine has no such channel. The artifact handle cannot carry
        it: the mesh tier loads the exported STL into a `trimesh` before
        returning, so the render's own account of its inputs is gone by the
        time a caller holds the result. Same shape as the runner's
        `artifact_out`, and an empty list means "the engine did not say",
        which is never "the render read nothing".

        `unresolved_out`, when given, receives the diagnostic lines saying the
        engine built something other than what the source asked for on a build
        that nonetheless SUCCEEDED -- a name it could not resolve (#286), or a
        value it could not convert and defaulted (#308) -- populated on the
        mesh tier, empty on a tier whose engine cannot half-render. Same reason
        it is an out-parameter rather than part of the return: the handle is a
        `trimesh` by the time a caller holds it, and a mesh cannot say what its
        own source was built without.
        """
        ...

    def provenance(self, a: Any) -> dict[str, Any]:
        """Populate the report's `geometry` block.

        Mesh tier emits `triangles` and `distinct_normals`; both, not either.
        `distinct_normals` is the identity signal — retriangulation-invariant,
        and it tracks $fn nearly one-to-one. `triangles` is the drift
        explainer, because chord error scales with edge length.

        NOT `facets`, which is what this docstring said until the v0.7.0
        sweep: trimesh's `.facets` is coplanar-region grouping and needs
        `scipy` or `networkx`, so D16 replaced it with a count the backend
        computes itself. The name never shipped, and four documents plus this
        line went on describing a field no report has ever carried.
        """
        ...

    def capabilities(self) -> frozenset[str]:
        """Primitives this backend can answer at all.

        Consulted before dispatch, so an `unsupported` result costs nothing.
        Capability is static; exactness is not, and is decided per evaluation.
        """
        ...

    # --- the primitives ---

    # `bbox`, `area` and `watertight` are total: they are statements about the
    # triangles or the shape as given, and stay answerable however broken it is.
    # The rest are conditional, and each returns `Unsupported` rather than a
    # number when its precondition fails — volume and centre of mass presume a
    # closed consistently-wound surface, genus presumes a single closed body,
    # and a body count presumes no edge shared by more than two faces.
    def bbox(self, a: Any) -> Measurement: ...
    def volume(self, a: Any) -> Measurement | Unsupported: ...
    def area(self, a: Any) -> Measurement: ...
    def center_of_mass(self, a: Any) -> Measurement | Unsupported: ...
    def is_valid(self, a: Any) -> Measurement: ...
    def watertight(self, a: Any) -> Measurement: ...
    def solid_count(self, a: Any) -> Measurement | Unsupported: ...
    def genus(self, a: Any) -> Measurement | Unsupported: ...
    def topology_counts(self, a: Any) -> Measurement | Unsupported: ...
    def triangles(self, a: Any) -> Any: ...

    # Present because they are part of the survey's twelve. `intersect_volume`
    # has a caller — the shipped `keep_out` / `keep_in` compose from it and
    # `region_solid` (SPEC-contract 4.4), and its empty case is normative.
    # `min_distance` and `raycast` have none: they serve clearance and
    # interference, which wait on assemblies, and specifying them now means
    # the protocol does not change when those land. The mesh tier does NOT
    # implement `raycast` cheaply — it needs a spatial index the `mesh` extra
    # does not carry, so on that install it refuses rather than answering.
    def min_distance(self, a: Any, b: Any) -> Measurement | Unsupported: ...
    def intersect_volume(self, a: Any, b: Any) -> Measurement | Unsupported: ...
    def raycast(self, a: Any, origin: Vec3, direction: Vec3) -> list[Vec3] | Unsupported: ...

    def region_solid(self, region: Any) -> Any:
        """Materialize a declared `partspec.region` as this backend's native solid.

        Both tiers MUST realise the same polyhedron from the region's canonical
        vertex list (SPEC-contract.md 4.4) — a backend that substitutes an exact
        cylinder for the polygon prism is answering a different question than
        the other tier, however much better its representation could do.
        """
        ...

    def bores(self, a: Any) -> Measurement | Unsupported:
        """Every cylindrical bore's diameter (SPEC-contract.md 4.5).

        OCCT-only, like `topology_counts`, and for the same reason: a mesh has
        no cylindrical face to enumerate, and fitting one to the facets
        manufactures the confident wrong number this protocol exists to refuse.
        The mesh backend MUST NOT declare this capability.
        """
        ...

    def bore_table(self, a: Any) -> Any:
        """The raw per-bore view beneath `bores` — `{d, direction, center}`
        per bore — consumed by `bolt_circle` (SPEC-contract.md 4.6). OCCT-only,
        with `bores`."""
        ...

    def blend_radii(self, a: Any) -> Measurement | Unsupported:
        """Every partial-wrap cylindrical cluster's radius, ascending — the
        candidates a `fillet_radius` claim ranges over (SPEC-contract.md 4.7).
        OCCT-only, with `bores`; MUST share its clustering, so a seam-split
        bore cannot masquerade as two blends."""
        ...

    # --- cavities (SPEC-contract.md 4.2), both tiers ---

    def cavities(self, a: Any) -> Measurement | Unsupported:
        """Sealed internal voids: per solid, its shells minus its outer one.
        Refused when there is no geometry to be about."""
        ...

    # --- the depth epic (#136), OCCT-only: SPEC-contract.md 4.8-4.11.
    #     These were implemented, dispatched by the runner and declared in
    #     CAPABILITIES for a day while this Protocol said nothing about them,
    #     and nothing noticed because nothing in src/ or tests/ ever does
    #     `isinstance(x, GeometryBackend)`. A structural type that lags the
    #     structures it types is decoration. SPEC-backend §3 no longer holds a
    #     second copy of this block to be compared against — it is generated
    #     from this class, so there is nothing left to disagree. ---

    def draft_angle(
        self, a: Any, direction: tuple[float, float, float]
    ) -> Measurement | Unsupported:
        """Every face's draft against a pull axis, ascending, in degrees."""
        ...

    def self_intersection_free(self, a: Any) -> Measurement | Unsupported:
        """Whether the shape crosses itself, with the faults inventoried."""
        ...

    def step_roundtrip(self, a: Any) -> dict[str, Any] | Unsupported:
        """Write to STEP, read back, report the drift and the writer schema."""
        ...

    def min_wall(self, a: Any) -> Measurement | Unsupported:
        """The minimum wall within a declared measurand, as a guaranteed
        interval that may collapse to exact."""
        ...
