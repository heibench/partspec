# SPEC — the `partspec` geometry backend

**Applies to:** v0.7.8 — the release this text describes. The `Status:` line records when
this document was last revised in substance; it is provenance, not currency (#300).

**Status:** draft 4 · 2026-08-09 · the protocol block gains the five primitives it was
missing, the `decompose()` and winding claims are corrected; `build()` grows `timeout_s` with the blown-budget
MUSTs and the stated in-process enforcement ceiling
**Scope:** the protocol a geometry backend implements, the two v0 implementations, and how
`exactness`, `bounds` and capability gating are determined.
**Normative:** MUST / SHOULD / MAY per RFC 2119.
**Backing:** D3 (two backends), D13 (ignore `--summary`), D14 (trimesh + manifold3d),
D15 (measurand), [`notes/survey/03-cad-khana-absorption.md`][survey-absorption] §2, [`notes/survey/04-kernel-capability.md`][survey-capability].

---

## 1. Why a protocol at all

Investigation 03 established the finding this whole design rests on:

> cad-khana's build123d coupling is **pervasive by type but shallow by behaviour** — twelve
> geometry primitives carry its entire diagnostic vocabulary, and ~2,000 LOC of the valuable
> logic is already engine-independent.

So engine neutrality is not a rewrite. It is a protocol over a dozen methods, plus own
value types replacing five leaked build123d types.

**Two backends, not three** (D3): one OCCT backend serves build123d *and* CadQuery via a
`.wrapped` adopt shim; the only genuinely separate backend is mesh, for OpenSCAD.

---

## 2. Value types

Own types, so no engine type appears in the check layer.

```python
@dataclass(frozen=True)
class Vec3:   x: float; y: float; z: float

@dataclass(frozen=True)
class Measured:                            # what every primitive returns
    value: float | tuple[float, ...]
    exact: bool
    bounds: tuple[float, float] | tuple[tuple[float, float], ...] | None = None
```

`Transform` and `Plane` are **deliberately absent in v0**. They are needed for placement and
datum targets, which are assembly concerns (D11). Adding them later is additive.

`Measured` is the protocol's whole answer to `SPEC-report.md` §2: a backend never returns a
bare float, so a caller cannot accidentally lose provenance.

---

## 3. The protocol

<!-- BEGIN GENERATED: backend-protocol -->
```python
@runtime_checkable
class GeometryBackend(Protocol):
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
```
<!-- END GENERATED: backend-protocol -->

`min_distance` and `raycast` are present because the survey listed them, and **no check
calls either**. Two corrections to what this paragraph used to say. `min_wall` is no longer
among the deferred — it shipped (#140) and implements its own ray casting inline against
`IntCurvesFace_ShapeIntersector` rather than going through `raycast`, so the stated reason
for keeping `raycast` unimplemented no longer holds; what remains deferred is `clearance` /
`interference`, with assemblies. And the mesh backend does *not* implement `raycast`
cheaply, contrary to what this paragraph said through v0.6: `trimesh`'s default ray path
indexes through `rtree`, which the `mesh` extra does not carry, so the primitive raised
`ModuleNotFoundError` while `CAPABILITIES` advertised it — a declared capability that
cannot be honoured, the one thing §3.2 says capabilities exist to prevent. Resolved in
v0.7.0: the mesh tier no longer declares `raycast`, and the method returns `Unsupported`
rather than raising when the index is absent. Undeclared-and-works-when-available is
honest; declared-and-raising was not. `intersect_volume` gained its first caller with `keep_out` /
`keep_in`; its empty case is normative — **disjoint inputs MUST
return a `0.0` measurement, not raise**, because the conforming case of a `keep_out` is
exactly two disjoint shapes (build123d's `&` returns `None` there, and the naive
`.volume` read crashed on the first real call).

`region_solid` materializes a declared `partspec.region` as the backend's native solid. Both
tiers MUST realise **the same polyhedron from the region's canonical vertex list**: a
cylinder region *is* a circumscribed polygon prism everywhere, and a backend that
substitutes its own exact cylinder — as the OCCT tier could — is answering a different
question than the other tier (`SPEC-contract.md` §4.4).

`bores` enumerates every cylindrical bore's diameter, per the bore definition in
`SPEC-contract.md` §4.5 (inward-facing, full-wrap, one contiguous axial span per bore;
counterbore portions distinct per diameter). Declared only by the OCCT backend — the mesh
tier MUST NOT declare it, for the same reason as `topology_counts`: fitting cylinders to
facets manufactures the confident wrong number this protocol exists to refuse. Diameters
are exact (a BREP radius is a parameter, not an estimate), which is why the predicted
first use of `approximate` did not arrive with this primitive. `bore_table` is the raw
view beneath it — per bore `{d, direction, center}` — consumed by `bolt_circle`; one
detection implementation serves both so the bore definition cannot fork, and the mesh
tier refuses it identically.

### 3.1 `Unsupported` is a return value, not an exception

A backend that cannot answer returns `Unsupported(reason, requires)`. It MUST NOT raise, and
it MUST NOT return a plausible-looking number.

This is the protocol-level enforcement of `SPEC-report.md` §3.2. It is also the exact point
at which PartCAD went wrong (D12): by normalizing an OpenSCAD mesh into a faceted
`TopoDS_Shape`, its topology queries *run* and return triangle counts dressed as
engineering topology. **A backend MUST NOT satisfy a query by reconstructing an entity its
representation does not contain.**

### 3.2 Capabilities are declared, not discovered

`capabilities()` returns the set of primitives the backend can answer *at all*. The check
layer consults it before dispatch, so an `unsupported` result is produced without building
anything the backend cannot use. Per-call `Unsupported` remains necessary for the
geometry-dependent cases — capability is static, exactness is not (§5).

---

## 4. The OCCT backend

Serves **build123d and CadQuery from one implementation**, verified (D3):

```
both .wrapped are TopoDS_Shape from the SAME OCP module
bd.Solid(cq_shape.wrapped)  ->  volume 6000.0, is_valid True, faces 6
distance_to (expect 90) -> 90.0    intersection volume (expect 6000) -> 6000.0
```

**Adoption happens once, at the front door.** A CadQuery result enters as
`bd.Solid(shape.wrapped)`; everything downstream is build123d. There is no second code path,
which is why CadQuery costs an afternoon rather than a parallel backend.

The shim also normalizes the small API divergences so they never reach the check layer —
notably build123d's `is_valid` is a **property** while CadQuery's `isValid()` is a method.

Every quantity is `exact=True` on this tier. `bounds` is `None` throughout.

**But exactness still presumes a solid.** `volume` and `center_of_mass` MUST return
`Unsupported` for a shape bounding none. The failure is quieter here than on the mesh tier
rather than absent: an open shell and a bare face both report `volume 0.0` while `is_valid`
is `True`, so validity does not catch it, and `volume(max=…)` on a shape containing no
material would pass. `center()` is worse than a wrong number — it answers with the centroid
of the *surface*, a different quantity under the same name. `area` and `solid_count` stay
answerable: an area is defined for a face, and `0 solids` is a true answer.

**And these MUST be measured over the shape's solids, not off the shape.** They are
quantities about the part's **material**: how much of it there is, the surface bounding it,
and where its centroid sits. A compound of several bodies therefore keeps answering — the
total over the bodies is a defensible quantity, and refusing it would breach D17's second
half — but nothing that is not a body may contribute. The rule is not uniform across the
three, and the difference is deliberate:

- `volume` and `center_of_mass` are **unconditional**: they already refuse a shape bounding
  no solid, so there is no second case to serve.
- `area` is **conditional on there being solids**. Where the shape has none it MUST report
  its own area, as it always has — see below.

Reading these off the whole shape gives a confident wrong number in two independent ways,
both measured on build123d 0.11.1 / cadquery-ocp 7.9.3.1.1, with a 20 mm cube bored Ø6
through (honestly 7434.51 mm³, 2720.44 mm², centroid at the origin):

| shape | `a.volume` | `a.area` | `a.center().X` |
|---|---|---|---|
| the cube alone | 7434.51 | 2720.44 | −3.8e−16 |
| beside a `Shell` over its own faces | **14869.03** | **5440.88** | −4.3e−16 |
| beside a closed 10 mm box shell 100 mm away | **8434.51** | **3320.44** | **11.856** |
| the solid at compound level 3 | **0.0** | 2720.44 | −3.8e−16 |

`.volume` sums **shells alongside solids**, and a `Shell` over a solid's own faces is closed,
so OCCT encloses a volume for it too; `.area` visits every face **occurrence**, duplicates
included; `center()` reads volume properties over everything, so a closed stray shell drags
the centroid toward it — row 2's stray sits on the solid's own faces and so moves it by
nothing, which is why the corruption has to be moved off the part before that column shows
it. Separately, `.volume` walks `compounds()`, which reaches only the shape and its
**direct** compound children, so a solid below that is invisible to it and the sum collapses
to `0.0`.

**Compound level is counted in TopoDS wrappings above the solid, not in
`Compound(children=[…])` calls**, and the two differ by one because `Box(…)` is *already* a
compound over its solid. Levels 0, 1 and 2 read correctly; level 3 and below read `0.0`.
Level 3 is therefore reached by **two** `Compound(children=[…])` calls — an assembly that
groups a sub-assembly, which is the ordinary way to group one. Each solid's own `.volume` /
`.area` / `.center()` recurse and know nothing of the wrapping above them, which is why the
per-solid sum is right at every level. `solid_count`, `watertight`, `is_valid` and
`cavities` read normal on all four shapes above, so none of those four catches any of it.
(#344, #347.)

`center_of_mass` MUST also refuse when the shape's solids enclose **no net volume**. The
weighting is a division by that total, and Python raises `ZeroDivisionError` on it rather
than producing a `nan`; either way there is no centroid to report. Reachable: two
independently built 10 mm boxes, one of them reversed, measure as solids of `+999.99` and
`−999.99` with `solid_count 2` and `is_valid True`.

`area`'s fallback is load-bearing: **where the shape has no solid at all it MUST report its
own area.** A sum over `solids()` would report a shell-only or face-only part as `0.0`
exact — a new confident wrong number of exactly the class the rule fixes. The measurand is
the boundary of what the shape *is*: the material's faces where there is material, the sheet
itself where the sheet is all there is.

**The cost of that rule, stated rather than discovered: a sheet standing beside a solid
contributes nothing to `area`.** Measured, a 20 mm square face reports `area 400.0` alone
and is dropped entirely once a 10 mm box is beside it — `area 600.0` against a shape
carrying 1000 mm² of surface, so `area(max=700)` passes on it. This is accepted, not
overlooked: the alternative is the row-2 doubling above, and a modelling result that mixes a
solid with a loose sheet is the corruption this section exists to answer.

**What names such a shape depends on whether the sheet is closed, and `watertight` alone
does not.** Measured:

| shape | `area` before → after | dropped | `watertight` |
|---|---|---|---|
| an **open** 20 mm face beside a 10 mm box | 1000.0 → 600.0 | 400 mm² | **false** |
| an **open** shell (one face off) beside a 10 mm box | 1100.0 → 600.0 | 500 mm² | **false** |
| a **closed** 10 mm shell beside a 10 mm box | 1200.0 → 600.0 | 600 mm² | **true** |
| a **closed** 10 mm shell beside the bored cube (row 3 above) | 3320.4 → 2720.4 | 600 mm² | **true** |

An open sheet leaves an edge bounded by one face, so `is_manifold` reads false. A closed one
does not, and the last two rows drop 600 mm² with every adjacent boolean reading normal. What
holds across all four is **`genus`, which refuses any stray beside its one solid** (#339),
and `bbox` / `topology_counts`, which move because the sheet is a separate body.

`bbox`, `topology_counts`, `is_valid` and `watertight` are unchanged by this rule and keep
measuring the shape as given. Note that the Protocol's own taxonomy above is about
**refusal**, not about measurand: it names `bbox`, `area` and `watertight` as the primitives
that stay answerable however broken the shape is, which `area` still does. It does not say
those three sum over everything, and it does not classify `topology_counts` or `is_valid`
that way at all.

A stray body does **not** reliably move any of the four. Measured on the same bored cube:
the row-2 stray shares the solid's own TShapes, so the deduplicating `.faces()` / `.edges()`
/ `.vertices()` accessors are unmoved and `topology_counts` reads the honest `(7, 15, 10)`;
the row-3 stray is a separate body and moves it to `(13, 27, 18)`. `bbox` is likewise
`(20, 20, 20)` on row 2 and `(115, 20, 20)` on row 3. So these are left alone because an
envelope and an entity count are honest statements about what was drawn — not because they
carry any part of the guard.

**Two primitives do catch row 2, and neither is one of those four.** `genus` refuses it on
its own precondition (#339), at `incomplete` / exit 2. And `step_roundtrip` **fails** it at
exit 1: the STEP writer expands the shared TShapes into distinct entities, so the counts
move where the deduplicating accessors did not —

```
honest             faces (7, 7)    edges (15, 15)   solids (1, 1)   volume_rel 2.7e-15
row 2 (shared)     faces (7, 14)   edges (15, 30)   solids (1, 1)   volume_rel 2.7e-15
```

End to end, a contract declaring `step_roundtrip(tol=1e-6)` passes the honest cube and
reports `FAIL … the round-trip changed topology: faces 7 -> 14, edges 15 -> 30` at exit 1 on
row 2. That makes it the **stronger** of the two detectors — a verdict rather than a refusal
— and it is a deliberate property of this tier, not an accident: an exchange that duplicates
a part's faces has changed the artifact, which is exactly what the check asks. Backends MUST
take these counts from the same accessor on both sides, and MUST NOT reduce them to the
solids' own — the deduplicating accessor is what makes the drift visible, because raw
occurrence counts read `faces (14, 14)` on row 2 and see nothing.

### 4.1 Dependency pinning — mandatory

`cadquery-ocp` and `cadquery-ocp-novtk` **both install a top-level `OCP/` package, and
pip/uv do not detect the conflict** — both install and one silently clobbers the other. Our
spike worked only because the versions matched. PartCAD hits this in production and
re-asserts the VTK-enabled OCP last, after build123d.

The project MUST pin one OCP explicitly and commit the lockfile. A CI job SHOULD assert that
exactly one `OCP/` provider is installed, because the failure mode is silent.

---

## 5. The mesh backend

OpenSCAD → binary STL → trimesh/manifold3d (D13, D14).

1. Render: `openscad --export-format binstl -o <tmp>.stl -D name=value ... <source>`.
   `binstl` specifically — lib3mf cannot read ASCII STL, and OpenSCAD 2021.01's STL default
   *is* ASCII.
2. Load with `trimesh.load_mesh()` — **explicitly**, never `load()`, so a multi-body file
   cannot silently degrade into a different type with different semantics.
3. Measure the mesh. **Never parse `--summary`** (D13): it omits volume and area entirely,
   its `facets` field means different things per backend, and — the reason it is banned — on
   invalid geometry it emits JSON with the validity key **absent** while exiting 0, so
   `.get("simple", True)` silently passes a broken part.

### 5.1 Exactness under D15 — and why this is simpler than it looked

D15 fixes the measurand as *the artifact as authored and exported*. **A mesh is a
polyhedron.** Its volume, area, centre of mass, bounding box, watertightness, solid count
and genus are computed exactly from its triangles. There is no smooth ideal being
approximated, so there is no tessellation error to bound.

This dissolves the question the review raised — *"how does a backend know whether its input
is polyhedral or a tessellated curve?"* Under D15 the backend does not need to know, because
the distinction is not about measurement accuracy. It is about **design identity**, and it
is reported through `geometry.distinct_normals` and `geometry.triangles` rather than through error
bars.

> **Corrected 2026-08-05 (dogfood F14).** The paragraph above is true of a mesh that
> *is* a polyhedron, and the first implementation read it as though every mesh were. It is
> not: OpenSCAD exits 0 on meshes that are open, non-manifold or inconsistently wound.
> Exactness is therefore **conditional on a precondition per quantity**, stated in §5.1.1.
> Where the precondition fails a backend MUST return `Unsupported`, naming the defect.
> Reporting a number instead is failure mode two of `SPEC-report.md` §1.1, and this backend
> was doing exactly that: a cube missing one face measured `volume 500.0` (against 1000.0
> closed), `genus 1` and a centre of mass outside the material — all flagged `exact`.

#### 5.1.1 Preconditions

| quantity | precondition | if it fails |
|---|---|---|
| `bbox`, `area`, `triangles`, `distinct_normals` | none — statements about the triangles as exported | always answered |
| `watertight` | none — it *is* the closedness test | always answered |
| `volume` | closed, consistently wound **and outward-oriented**: the divergence theorem sums signed contributions, so a flipped triangle subtracts where it should add — and a uniformly inverted mesh is closed and consistent while every component encloses negative volume, which is refused too | `Unsupported` |
| `center_of_mass` | `volume`'s precondition, **and a non-zero enclosed volume**: the centroid is that same integral divided by the volume, so a closed surface enclosing none has no centre of mass. trimesh divides in numpy and yields `nan`, which is not a measurement — the OCCT tier refuses the analogous shape (§4) | `Unsupported` |
| `genus` | closed, and exactly one body | `Unsupported` |
| `solid_count` | no edge shared by more than two faces | `Unsupported` |

`solid_count`'s precondition is narrower than the others *on purpose*. An **open** mesh still
has a determinate body count — every edge is used once or twice, so face adjacency is
unambiguous — and refusing there would be over-refusal, which inflates `incomplete` and is
its own way of not answering an answerable question. A **non-manifold** mesh does not:
counting through a junction where four faces meet and counting across it give different
answers, and nothing in the mesh says which was meant. Measured on the F10 gridfinity bin,
manifold3d welds and reports 1 body while the exported triangles give 3 (the bin plus two
stray 2-triangle slivers). Both are defensible, which is exactly why neither may be reported
as `exact`.

`center_of_mass`'s extra clause is reached by a **sound** engine run and not only by a
broken model: `intersection()` of two cubes meeting on a face exports a four-facet
zero-thickness sheet — watertight, consistently wound, `area` 480.0 mm², `volume` 0.0 — on
2021.01 and on 2026.08.01 alike. Before it was stated, that `nan` reached `Measurement`,
which refuses a non-finite value by **raising**, and the raise ended the whole `measure`
run: nothing at all was emitted, `area` and `bbox` included (#365).

#### 5.1.2 Measure the artifact, not a library's rebuild of it

A backend MUST NOT read an absolute measurement out of a library that reconstructs its
input, because the reconstruction is not the exported artifact and D15 fixes the measurand as
the artifact.

This is not hypothetical. Handed the *clean*, watertight, consistently-wound CGAL render of
the gridfinity bin — same 5,330 vertices, none displaced — `manifold3d` retriangulated 55 of
10,688 triangles and moved the enclosed volume by **25.31 mm³ (0.078 %)**. An independent
float64 divergence-theorem sum agrees with trimesh (32341.840738) and not with manifold3d
(32367.150544). Sourcing `volume` from one library and `genus`/`solid_count` from the other
therefore put measurements of **two different solids** in one report, every one flagged
`exact`.

Consequently the mesh backend computes body count and genus itself, over the exported
triangles: components by shared-edge adjacency, genus as `(2 − χ)/2` with `χ = V − E + F`.
Unlike the BREP tier — where faces carry inner wires and the naive form is quietly wrong —
every face of a triangle mesh is a disc, so `V − E + F` is simply correct. Counting only
*referenced* vertices keeps a stray unreferenced one from inflating `V`; duplicate coincident
vertices would break it but cannot occur, because closedness means every edge is used exactly
twice, which is impossible on an unwelded mesh. The precondition guarantees its own input.

A library that *rejects* input must also be believed. `manifold3d` returns an object
reporting `Error.NotManifold`, `is_empty()` and zero triangles — on which `.decompose()`
still returns a one-element list and `.genus()` still returns 1. Any wrapper MUST check
`status()` before reading anything off it.

### 5.2 The one real bound: float32 quantization

The single rigorously derivable inexactness on this tier, and the only source of
`approximate` the mesh backend may legitimately produce:

Binary STL stores coordinates as **float32**. The exported artifact therefore differs from
what the engine computed by at most a half-ulp per coordinate:

```
ε_coord(v) = |v| · 2⁻²⁴  ≈  5.96e-8 · |v|
```

Measured: `cube([120.3, 80.7, 40.1])` round-trips as `120.30000305, 80.69999695,
40.09999847` — deltas of ±3.05e-6 mm, which is **three times** an absolute `1e-6` and is why
`SPEC-report.md` §3.3's epsilon carries a relative term.

Propagation:

- **bbox** — directly: each extent inherits the quantization of its two bounding
  coordinates. Trivially computable, and the honest source of `bounds` if a bbox check is
  ever reported `approximate` rather than absorbed by the epsilon.
- **volume / area** — a first-order bound follows from the coordinate perturbation, of order
  `1e-7` relative. Real, computable, and far below any engineering tolerance.
- **watertight / solid_count / genus** — topological and therefore **unaffected**;
  quantization cannot open a closed mesh at these magnitudes. Report `exact=True` *when
  answered at all* — §5.1.1 governs whether they are.

Backends SHOULD report bbox, volume and area as `exact=True` when the resulting interval is
narrower than `SPEC-report.md` §3.3's epsilon, because an interval below the comparison
tolerance carries no information and would produce `approximate` statuses that mean nothing.
This is the one place a backend is permitted to collapse a bound, and it MUST be the
epsilon that justifies it, never convenience.

### 5.3 Known gaps on this tier

- **Self-intersection is not available.** Neither trimesh nor manifold3d detects it, and the
  alternatives are GPL (libigl/CGAL) or heavyweight (pymeshlab). Accepted per D14; report
  `Unsupported`.
- **Topology counts are meaningless** and MUST return `Unsupported(requires="occt")`. A
  triangle count is not a face count, and returning one is the PartCAD failure.
- **`min_distance` is exact for polyhedra** via `manifold3d.min_gap` (verified: returned
  exactly 7.5). Under D15 that is simply exact — the polyhedron is the part. It is the one
  primitive still routed through manifold3d, tolerable only because it is relational: it
  compares two shapes rather than reporting an absolute quantity about one. §5.1.2 forbids
  the absolute case.
- **`body_count` is computed here, not delegated.** trimesh's routes through
  `scipy.sparse`, and scipy reaches a developer machine only via build123d/cadquery — so a
  mesh-tier dependency on it passes both locally and in CI while breaking anyone who
  installed `partspec[mesh]`. `just test-mesh-only` exercises that install in a throwaway
  scipy-free environment.

### 5.4 OpenSCAD version floor

D13's consequence: because `--summary` is never read, **2021.01 and current nightlies are
interchangeable** for our purposes and no nightly install is a v0 prerequisite. The backend
MUST record `engine_version` in the report regardless, since a Manifold-vs-CGAL backend
change alters triangulation and therefore `geometry.triangles`.

---

## 6. Provenance

`provenance(a)` populates `report.geometry`. Mesh tier emits `triangles` and
`distinct_normals`; OCCT tier emits neither (`SPEC-report.md` §7.1) and MAY emit nothing at
all in v0.

`distinct_normals` counts distinct face normals — retriangulation-invariant and tracking
`$fn` one-to-one (`$fn=n` on a cylinder yields `n+2`; a cube yields 6). `triangles` is the
drift explainer, because chord error scales with edge length. Both, not either.

**Not** trimesh's `.facets` coplanar grouping, which requires `scipy` or `networkx` — see
D16. Likewise `solid_count` uses **neither** `manifold3d.decompose()` nor trimesh's
`body_count`: it counts bodies itself from face connectivity over the exported triangles
(`_shell_census` / `_face_components`). `body_count` routes through the same graph
machinery and raises `ImportError` without `scipy`; `decompose()` was the earlier plan and
this paragraph went on describing it after §5.1.2 replaced it. Counting in-backend is what
D17 requires and what `just test-mesh-only` exists to keep honest.

---

## 7. Testing obligation

The protocol is only worth its cost if both backends genuinely agree where they claim to.

**A differential test MUST exist** (implemented: `tests/test_differential.py`, on a
deliberately polyhedral plate; gridfinity below remains the ready-made harder subject): the same
part, specified once, implemented in OpenSCAD
and in build123d, checked against one contract, with the report's `checks[]` compared
field-by-field excluding `engine` and `geometry`. Gridfinity is the ready-made subject —
implementations exist in all three engines under MIT
(`kennetek/gridfinity-rebuilt-openscad`, `michaelgale/cq-gridfinity`,
`Ruudjhuu/gridfinity_build123d`), so any divergence is a tool bug rather than a design
difference.

This is the substitutability proof. Without it, "one contract, evaluated identically
wherever it can be" is an assertion rather than a property.

[survey-absorption]: https://github.com/heibench/partspec/blob/main/notes/survey/03-cad-khana-absorption.md
[survey-capability]: https://github.com/heibench/partspec/blob/main/notes/survey/04-kernel-capability.md
