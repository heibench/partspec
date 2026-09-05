# Decisions

Numbered, with the reasoning that made the call, so it isn't relitigated. Follows the
`scadman/docs/DECISIONS.md` pattern. D1–D17 are survey-stage calls, promoted here when this
repo was created; decisions from D18 on were made in this repo.

| # | Decision | Call | Date |
|---|---|---|---|
| D1 | Scope | Personal open-source tool, dogfooded by the author | 2026-08-02 |
| D2 | Engine coverage | Neutral across OpenSCAD, CadQuery, build123d from v0 | 2026-08-02 |
| D3 | Backend count | **Two** backends, not three — OCCT (b123d + CQ) and mesh (OpenSCAD) | 2026-08-02 |
| D4 | Repo shape | **One repo**, not a CQ/b123d vs OpenSCAD split | 2026-08-02 |
| D5 | Interface | CLI first; MCP layered later over the same primitives | 2026-08-02 |
| D6 | Contract format | **Python**, not sidecar YAML | 2026-08-02 |
| D7 | Prior art | Absorb cad-khana's design; do **not** depend on the package | 2026-08-02 |
| D8 | Language | Python + `uv` | 2026-08-02 |
| D9 | Name | **`partspec`** | 2026-08-02 |
| D10 | Degraded results | `approximate` is **non-green** — its own status, not `pass` | 2026-08-02 |
| D11 | v0 scope | **Parts only.** Assemblies tracked as a real post-v0 goal | 2026-08-02 |
| D12 | PartCAD | Out of scope for v0; revisit post-v0 as a parts source | 2026-08-02 |
| D13 | OpenSCAD measurement | **Ignore `--summary` entirely**; export `binstl` and measure the mesh | 2026-08-02 |
| D14 | Mesh dependencies | `trimesh` + `manifold3d`; accept the self-intersection gap | 2026-08-02 |
| D15 | **The measurand** | Measure the artifact **as authored and exported**, not an idealized smooth solid | 2026-08-02 |
| D16 | Facet-resolution signal | `distinct_normals`, not a coplanar facet count — avoids a scipy dependency | 2026-08-03 |
| D17 | **Measurement preconditions** | Per-quantity, refused **narrowly**; never measure a library's rebuild of the artifact | 2026-08-05 |
| D18 | **Product boundary** | partspec is the **stateless gate**; it does not own the authoring loop | 2026-08-07 |
| D19 | Road to v1.0 | **Depth, not width** — richer part-level intent checks; assemblies open the post-1.0 line | 2026-08-07 |

---

## D1 — Scope: personal OSS, dogfooded

Cameron, 2026-08-02: *"this has nothing to do with integrum or integrum flow. this is a
personal open source project i was looking to start working on and prototype and dogfood
myself over next few days and weeks and months."*

Rules out the source memo's Phases 2–5 entirely: team standards, org assets, controlled
autonomy, product UI, multi-tenant isolation, ERP/PLM APIs. There is no team and no tenant.

Follows the established `scadman-survey → scadman → scadman-dogfood` pattern.

---

## D2 — Engine coverage: all three from v0

Cameron's call. OpenSCAD is where the existing portfolio lives (~30 libraries, continuously
active); build123d and CadQuery are where he intends to go.

Cheaper than it first appeared — see D3.

---

## D3 — Two backends, not three

**Verified locally, not assumed.** build123d 0.11.1 and CadQuery 2.8.0 install into one
`uv` venv on a shared `cadquery_ocp 7.9.3.1.1`. Both `.wrapped` are `TopoDS_Shape` from the
*same* OCP module, and `bd.Solid(cq_shape.wrapped)` adopts across losslessly — volume,
`is_valid`, face count, `distance_to` (exact 90.0), boolean intersection (exact 6000.0),
bbox and center all correct.

> One **OCCT backend** serves both build123d and CadQuery via a `.wrapped` adopt shim.
> The only genuinely separate backend is **mesh**, for OpenSCAD.

CadQuery therefore costs an afternoon and adds no ongoing maintenance surface, because
there is no second code path to keep in sync.

**Alternatives and why they lost:**

| Option | Why not |
|---|---|
| Lowest common denominator (mesh only) | Discards the BREP vocabulary, which is where the engineering value is |
| Convert OpenSCAD mesh → BREP, one vocabulary | Sewing a tessellated mesh yields thousands of triangular faces, not engineering faces |
| Three parallel backends | CadQuery/build123d share a kernel; a second implementation would be duplicated by construction |

---

## D4 — One repo

Cameron offered a CQ/b123d vs OpenSCAD split if forcing them together was a bad idea. It
isn't: after D3, neutrality costs a twelve-method protocol, not a fork. The mesh backend
shares the *protocol*, not the code, so it adds a module.

Keeping one repo preserves the property worth building: **one contract, evaluated
identically wherever it can be, with honest degradation where it can't.** Two repos would
make that a coordination problem instead of a type signature.

Per the Anolis ruling, defer the split until a second consumer or a real driver lands.
Design the protocol as the seam so a later split stays cheap.

---

## D5 — CLI first, MCP later

`dev-toolbox/docs/tooling-philosophy.md` core belief #3: *"Agents use the same commands as
humans"*, with *"Agent-specific commands"* named as an anti-pattern. cad-khana's author
reached the same conclusion independently (`# mcp.py # future: MCP server over the same
primitives`, library modules free of CLI/MCP deps).

**The load-bearing corollary:** the real contract is the **report schema plus the exit
code**, not the verbs. If `check` emits human prose, the MCP layer becomes a parser and the
tool is built twice. With machine-readable output first, MCP is ~100 lines and `diff`, CI
annotations and a scorecard all fall out of the same artifact.

Startup cost (importing OCP takes seconds) is handled by **batching** — one `check`
evaluates the whole contract and emits one report — not by a daemon, which would be
premature.

---

## D6 — Contract in Python, not sidecar YAML

Reverses the first design sketch. A Python contract module references a `.scad` file as
easily as a Python model, so it is engine-neutral regardless of the model's language.

- More expressive; no schema to design or version.
- Avoids the DSL trap that `agent-policy/docs/decisions.md` marks **locked**: *"The history
  of custom policy DSLs in infrastructure tooling is a cautionary tale."*
- Extends the `Spec` dataclass + `__post_init__` assertion idiom already in
  `build123d-template`.
- The "an agent can silently weaken a code assertion" objection is answered by a **semantic
  report diff that reports `removed:` assertions** — a YAML schema would not do better.

---

## D7 — Absorb cad-khana's design, don't depend on it

`cyberchitta/cad-khana`, Apache-2.0. One author, 92 commits, **no CI, no releases**,
`Development Status :: 2 - Pre-Alpha`, and `khana build` was retired in its last week of
activity with an incompatible `check()` signature change and no shim. Test suite is
genuinely good (361 test functions, ~1:1 with source).

**Absorb:** the eight-primitive assertion vocabulary; claims stored *inside* the immutable
model value with `qualified()` propagation up the tree; tri-state `passed`; recording
`value` even on pass so `diff` can report drift the boolean can't see; `BOUND_EPSILON`;
deferred failure roll-up; `min_wall_alignment`; and the `SKILL.md` agent contract (bounded
3–5 attempt repair loop, machine-greppable `HUMAN_REVIEW:` escalation, the **vacuous green**
anti-pattern, token-aware view loading).

**Re-implement behind `GeometryBackend`:** the twelve geometry primitives that carry the
entire diagnostic vocabulary.

**Leave:** the glTF machinery, the HLR plumbing, `hints.py`'s build123d regexes, and the
five build123d type leaks that constitute the whole of the lock-in.

Note its assertion vocabulary is whole-solid plus one datum `Plane` — **no face or edge
selectors**. That deliberately sidesteps the topological-naming problem the source memo
named as central, and is why twelve primitives suffice.

---

## D8 — Python

`scadman` and `agent-policy` both chose Rust, twice, for single-binary distribution. That
argument does not transfer: measuring BREP requires build123d/CadQuery/OCP, which are
Python. A Rust core would marshal geometry across a process boundary on every check, and
the single-binary benefit is unavailable regardless of language. Take the ecosystem access
instead.

---

## D9 — Name: `partspec`

**Availability, checked 2026-08-02:** `partspec`, `part-spec`, `py-partspec` all free on
PyPI; free on npm; `heibench/partspec` free. (`cadman`, `cadcheck`, `cadspec`,
`geocheck` were also free; `fitcheck` was taken.)

**Minor collision, non-blocking:** four small unrelated GitHub repos are named
`PartSpec`/`PartSpecs` — a part-lookup/sourcing app, an engineering calculator, a Korean PC
parts DB, and a flange spec web app. All hobby projects, none in CAD-as-code, none with
traction, and none holding the package names. Worth knowing for search ranking, not worth
renaming over.

Reads as what the tool does — it holds a part's spec and checks the part against it — and
does not claim the CAD-wide or package-manager territory that `cadman` would collide with
against `scadman` and PartCAD.

Follow the `scadman` triad convention: `partspec` (product) · this survey (throwaway) ·
`partspec-dogfood` (scratch workspace, not a git repo).

---

## D10 — `approximate` is non-green

Five result states, generalizing cad-khana's existing tri-state skip:

| status | meaning | green? |
|---|---|---|
| `pass` | evaluated, satisfied | yes |
| `fail` | evaluated, violated | no |
| `skipped` | referenced part absent | no |
| `unsupported` | backend cannot evaluate this check at all | no |
| `approximate` | evaluated, but tolerance-bearing on this backend | **no** |

The failure this prevents is specific and measured. On `bayonet-lock-scad`, volume drifted
0.5 % between `$fn=32` and `$fn=128` while bbox stayed exact — so some checks are
trustworthy on mesh and some silently are not, and only the tool can tell them apart.

**Refinement after the capability findings (investigation 04):** the status is a property
of *(check, backend, geometry)*, not of *(check, backend)*. Clearance via manifold3d
`min_gap` returned **exactly 7.5** — it is **exact for polyhedral geometry** and only
becomes approximate once curved surfaces are tessellated. So `approximate` must be decided
per evaluation, not looked up in a static table.

The sharpest case for this status is §4 of investigation 04: OpenSCAD's `cylinder($fn=16)`
is a genuine 16-sided prism, so RANSAC fitting returns the **circumscribed** radius
(5.0000) while the real bolt clearance is the apothem (4.9039). A `hole_diameter >= 10.0`
check would **pass at a reported Ø10.000 on a hole that actually clears Ø9.808** — and the
error is *always in the unsafe direction*. A verification tool that reports that as green
is worse than no tool.

cad-khana already names the adjacent disease — **vacuous green**: a module with no
assertions exits 0 and writes `"assertions": []`, and *"an agent will read it as success."*
Unsupported-as-pass and approximate-as-pass are the same failure wearing different hats.

The top-level verdict must carry the counts, and `check` must not exit 0 on a contract
whose checks were mostly unavailable.

---

## D11 — Parts only in v0; assemblies are a tracked post-v0 goal

**v0 is parts only.** The check set is class-1 parameter checks (pure arithmetic on inputs,
fully engine-neutral, no kernel needed) plus `builds`, `envelope`, `watertight`.

**Explicitly not "never" — assemblies are a real post-v0 item**, and the assertion model
must be designed to carry them rather than retrofitted. What is being deferred, from
cad-khana:

- **`qualified()` propagation** — a sub-assembly declares a claim once at the level that
  owns the knowledge; composing into a parent re-frames it automatically. The single best
  idea in that codebase.
- **Anchors as cross-unit interface contracts** — each unit exports where it *believes* a
  shared datum is; the parent asserts the beliefs coincide after placement.
- **`JointWindow` phase gating** on joint angle rather than animation `t`, so re-timing
  cannot invalidate a claim.
- **`drop_contact_shadowed`** — order-free contradiction resolution between group-expanded
  and hand-declared claims.
- Relational primitives: `NoInterference`, `Clearance`, `TangentContact`, `AllowedContact`,
  `ExpectedInterference`.
- **`sweep.py`** — `factory(t) -> Assembly` motion sampling with bracket-then-bisect onset.

Design constraints to honour now so this stays cheap later: attach claims **by dotted path
name** rather than by object identity; re-introduce `part_refs` on every assertion (it was carried unserialised in v0 and
removed in v0.7.0 rather than left as an invisible half-measure); keep the
tri-state skip (it is what lets a standalone sub-assembly run evaluate the same list
without the absent parts).

Known ceiling to record: cad-khana's interference is unconditional all-pairs OCCT booleans,
documented good to **~20 parts**.

---

## D12 — PartCAD: out of scope for v0, revisit as a parts *source* later

**Resolved from primary source** — read `partcad/src/partcad/part_factory_scad.py` and
`wrappers/wrapper_import_mesh.py` directly.

### How PartCAD achieves engine neutrality

It **normalizes everything to OCCT.** For an OpenSCAD part it:

1. passes declared parameters as `-D name=value` (or appends a call to a named `method` on
   a throwaway copy of the source — the original is never modified),
2. shells out to `openscad -o <tmp>.stl --export-format binstl`,
3. imports the mesh back through a **sandboxed Python runtime** with pinned deps, via
   `b3d.Mesher().read(path)[0].wrapped`, falling back to `b3d.import_stl(path).wrapped`.

The result is a `TopoDS_Shape`. Everything downstream then treats an OpenSCAD part exactly
like a build123d part.

### Why that is the trap, not the solution

This is option C from the design sketch, and seeing it implemented confirms the suspicion.
An STL imported into OCCT is a shell of **triangular faces**. So for an OpenSCAD part:

- `face_count` / `edge_count` return **triangle counts**, not engineering topology;
- there are no cylindrical faces, so no hole diameters, no bolt circles, no fillet radii;
- yet every check *runs* and *returns a number*.

There is **no capability declaration and no degradation signal**. You silently get less,
dressed as more — which is precisely the failure D10 exists to prevent. PartCAD chose
uniformity of interface over honesty about the guarantee; `partspec` makes the opposite
call, and that is now the clearest single point of differentiation between them.

**This does not make PartCAD bad** — for its actual job (packaging, BOM, sourcing,
assembly, visualization) a uniform shape type is the right call, because none of those
consumers ask topology questions. It makes it the wrong *foundation* for a verification
tool, whose entire value is knowing what it cannot prove.

### The decision

**Out of scope for v0.** `partspec` does not depend on PartCAD, does not wrap it, and does
not adopt its normalization.

**Revisit post-v0 as a parts *source*, not a substrate** — its `interfaces:`/mating model
(abstract interfaces with inheritance and ports, verified in
`partcad/examples/feature_interface/partcad.yaml` upstream) remains the best existing prior art for
declaring mechanical interfaces as data, and is the natural reference when assemblies land
(D11).

### Two things worth stealing now

1. **The `-D name=value` parameter-passing pattern**, including the "append a call to a
   named module on a throwaway copy rather than mutate the source" trick. That is exactly
   what `partspec`'s OpenSCAD adapter needs, and it is already proven.
2. **A dependency-conflict warning, from PartCAD's own source comments.** build123d depends
   on `cadquery-ocp-novtk`, which can *replace* the VTK-enabled `cadquery-ocp` that CadQuery
   wants; PartCAD re-asserts `CADQUERY_OCP` last, after build123d, to undo this. It also
   pins `pyexpat` **before** any CAD import, because OCP loads VTK's bundled copy of expat
   and build123d 0.11 imports IPython, which later uses `xml.dom` and dies on an
   undefined symbol.

   Corroborated in our own spike: the venv contains **both** `cadquery_ocp-7.9.3.1.1` and
   `cadquery_ocp_novtk-7.9.3.1.1` dist-infos. It worked because the versions matched —
   which is luck, not design. **Pin both explicitly and lock them.**

---

## D13 — Ignore OpenSCAD's `--summary`; measure the exported mesh

Verified against both OpenSCAD 2021.01 and the 2026.08.01 nightly.

**Context.** Stable OpenSCAD is **2021.01, dated 2021-01-31** — five and a half years old.
Nightlies ship roughly weekly and are effectively a different product: Manifold backend by
default, `--summary`, `--backend`, 19 export formats vs 8. Everything machine-readable
exists **only in unreleased nightlies**.

**Three measured reasons not to depend on it anyway:**

1. It yields only bounding box, counts, and a `simple` flag. **No volume, no area, no
   center of mass, no genus** (`Genus: 1` prints to console but is deliberately omitted
   from the JSON).
2. **The schema depends on the backend.** Same file, same nightly: `facets` = 272
   (triangles) under Manifold, 70 (planar facets) under CGAL. Solid count (`volumes`) exists
   *only* under CGAL — the non-default backend.
3. **The killer: invalid geometry yields JSON with the validity field missing, and exit 0.**
   Fed an open 3-triangle shell, the `geometry` block came back with **no `simple` key at
   all**, and OpenSCAD wrote the STL and exited 0. A checker doing `.get("simple", True)`
   **silently passes broken geometry**. trimesh caught it instantly:
   `is_watertight=False, volume=-416.67`.

**Decision:** export `--export-format binstl` and measure the mesh with trimesh/manifold3d.
`binstl` specifically, because lib3mf cannot read ASCII STL and 2021.01's STL default *is*
ASCII.

> ### Reinforced 2026-08-03 by a stronger case than the one above
>
> This decision was made on the basis that `--summary` **omits** the validity key on
> degenerate input. Dogfooding found it **asserting a false one**, which is worse.
>
> A community gridfinity bin (kennetek, 2,212★) rendered by OpenSCAD 2026.08.01's **default
> Manifold backend** produces a mesh with **4 non-manifold edges**. OpenSCAD reports:
>
> ```
> Top level object is a 3D object (manifold):
> Status:     NoError
> exit code:  0
> --summary:  { "facets": 10022, "simple": true, ... }
> ```
>
> It says *manifold*. It says *`"simple": true`*. Both are wrong. The same source under
> `--backend CGAL` renders clean, so it is a meshing artifact rather than a design error.
>
> "Never let OpenSCAD self-report validity" is therefore not conservatism. It is the
> difference between catching this and shipping it.
>
> **Consequence:** the render backend is selectable (`openscad(..., backend=...)`) and
> recorded as `engine.render_backend`, because it determines whether the artifact is valid.

**Consequence, and the reason this is the right call:** it dissolves the version problem.
With `--summary` unused, 2021.01 and the nightly become near-interchangeable and the schema
drift stops mattering. No nightly install becomes a prerequisite for v0.

This is the same principle as D10 in another costume — **never let the thing under test
report its own validity.**

---

## D14 — Mesh stack: `trimesh` + `manifold3d`

Light, pure wheels, no Blender or OpenSCAD shell-out for booleans. `manifold3d` is **the
same kernel OpenSCAD now uses by default**, so measuring an OpenSCAD part with it is
unusually well matched, and it exposes far more than CSG: `genus`, `volume`,
`surface_area`, `min_gap`, `decompose`, `slice`, `ray_cast`, `calculate_curvature`.

**Accept the self-intersection gap** (table row 6) rather than pulling in **GPL** libigl or
heavyweight pymeshlab. Add `rtree` only if trimesh proximity is ever needed over
manifold3d's `min_gap`.

⚠️ **Landmine to pin against, confirmed twice.** `cadquery-ocp` and `cadquery-ocp-novtk`
both install a top-level `OCP/` package and **pip/uv do not detect the conflict** — both
install and one silently clobbers the other. Our spike worked only because the versions
matched. PartCAD hits this in production and works around it: *"Last: re-asserts the
VTK-enabled OCP that build123d's 'cadquery-ocp-novtk' dependency has just replaced."*
**Pin one OCP explicitly and lock it.**


---

## D15 — The measurand: the artifact as exported, not the idealized solid

Settled after the adversarial review of `SPEC-report.md`, which found that the draft used
both readings and never defined which. **This gates `SPEC-backend.md`**, because it fixes
every backend method's obligation to produce `exactness` and `bounds`.

**Decision: a measurement describes the geometry as actually authored and exported.**

An OpenSCAD `cylinder($fn=16)` **is** a 16-sided prism. Its volume, bounding box, genus,
clearance and interference are therefore closed-form **exact** — not approximations of a
cylinder.

**Rejected:** measuring against the idealized smooth solid the designer imagined. It makes
every curved-surface quantity approximate, and it is unimplementable on the mesh tier
anyway, because the exported STL has erased `$fn` and the tool cannot recover intent it was
never given.

**The corollary is stated openly rather than hidden:** `partspec` measures the artifact, not
the intent. A coarse `$fn` is a design choice the tool *reports* (via `geometry.triangles`
and `geometry.distinct_normals`), not an error it bounds away. A bore modelled as a 16-gon is measured
as a 16-gon — which is what a real dowel will experience.

**Consequence that fell out of this, and is worth knowing before implementation:** under
D15, essentially the whole v0 check set is exact on a polyhedron, and the one candidate for
`approximate` — `min_wall` — turns out to admit no honest two-sided bound (sampling can only
ever find a *thinner* wall), making it `unsupported` instead. **So v0 contains no check that
can produce `approximate`.** The interval machinery stays because D10 is the thesis and the
first BREP tolerance check will need it — but it is dormant in v0 (no longer: `min_wall`,
#140, made it live on the OCCT tier), the dogfood run did not
exercise it, and its first real test was expected to be its first bug report (it was not — `min_wall`'s
straddle fixtures got there first).


---

## D16 — `distinct_normals` rather than a coplanar facet count

D-3 (folded into D15's review) added a facet-resolution signal to the report's `geometry`
block alongside `triangles`, described as "coplanar-grouped facet count" on the strength of
trimesh `.facets` recovering CGAL's 70 facets exactly on a test part.

**Implementing it revealed the cost.** trimesh `.facets` routes through
`graph.connected_components`, which raises `ImportError: no graph engines available!`
without `scipy` or `networkx`. So does `.body_count`. That is a large dependency for one
provenance field, against D14's explicit "light, pure wheels".

**Decision: count distinct face normals instead**, rounded to 4 decimals. Measured:

| shape | `distinct_normals` | note |
|---|---|---|
| cube | 6 | matches a coplanar facet count exactly |
| cylinder `$fn=16` | 18 | `n+2` — tracks `$fn` one-to-one |
| cylinder `$fn=64` | 66 | |
| cube, subdivided | 6 | unchanged by retriangulation |

It serves the stated purpose — an identity signal that tracks `$fn` and survives
retriangulation — in four lines of numpy, which is already a trimesh dependency.

It differs from a true coplanar facet count only where two **disjoint** coplanar regions
share a normal, which merges them. That is why the field is **named for what it measures**
rather than borrowing CGAL's "facets": someone comparing our number to CGAL's on a
non-convex part would otherwise be quietly misled, which is the failure mode this whole
project is organised against.

`solid_count` hits the same wall and takes the same route: `manifold3d.decompose()` rather
than trimesh's `body_count`.

> **Superseded 2026-08-05 by D17.** The wall was correctly identified — trimesh's
> `body_count` does need scipy — but `manifold3d.decompose()` was the wrong way round it,
> because manifold3d rebuilds the mesh before answering. `solid_count` and `genus` are now
> computed directly over the exported triangles. `distinct_normals` is unaffected and the
> reasoning above still stands for it.

**Also corrected here:** the claim in [`notes/survey/DIRECTION.md`][survey-direction] and investigation 02 that a mesh
bounding box is *"exact and resolution-independent"*. It is exact — the polyhedron is
measured exactly, per D15 — but **not invariant to facet settings**. The original spike used
explicit `$fn` values, and OpenSCAD places a vertex on the +X axis for an explicit `$fn`, so
the bbox landed on `2r` every time. With the **default** `$fa`/`$fs`, `cylinder(h=10, r=7.9)`
measures **15.737706**, not 15.8. The invariance was an artifact of the test inputs. This is
D15 working correctly — with default facets the part genuinely is 15.74 wide — but a
contract author writing `envelope(max=15.8)` against a curved OpenSCAD part must know the
number moves with `$fn`.

---

## D17 — Measurement preconditions are per-quantity, and refusal is narrow

**Date:** 2026-08-05. Prompted by dogfood F14, which found the tool committing the failure
mode it exists to prevent.

D15 fixed the measurand as *the artifact as authored and exported*, and `SPEC-backend.md`
§5.1 concluded that a mesh, being a polyhedron, is measured exactly. Both are right. The
implementation read them as though **every** mesh were a polyhedron bounding a solid, which
does not follow: OpenSCAD exits 0 on meshes that are open, non-manifold or inconsistently
wound, and on those the integrals and the Euler characteristic are not merely imprecise —
they are undefined. Measured, a cube missing one face reported `volume 500.0`, `genus 1` and
a centre of mass outside the material, all flagged `exact`.

**Decision, in three parts.**

**1. Each quantity declares its own precondition** and returns `Unsupported` naming the
defect when it fails (`SPEC-backend.md` §5.1.1). Not one global "is this mesh sound" gate:
`bbox`, `area` and `watertight` are statements about the triangles as exported and stay
answerable however broken the mesh is.

**2. Refusal is as narrow as the mathematics allows.** `solid_count` is refused only where
an edge is shared by more than two faces, *not* for an open mesh. An open mesh still fixes
its own component count — every edge is used once or twice, so adjacency is unambiguous. A
non-manifold one does not: counting through a four-face junction and counting across it give
different answers, and the mesh does not say which was meant. On the F10 bin manifold3d
welds and reports 1 body while the exported triangles give 3.

This is the part worth defending. Over-refusal looks like caution and is not — every
unnecessary `unsupported` pushes a part to `incomplete`, which is also a way of failing to
answer an answerable question, and a tool that refuses too much gets its refusals ignored.
`Unsupported` only means anything if it is reserved for questions that genuinely have no
answer.

**3. No absolute measurement may be read from a library that rebuilds its input.** manifold3d
retriangulated 55 of 10,688 triangles on a *clean* gridfinity render, shifting the enclosed
volume by 25.31 mm³ (0.078 %) — verified against an independent divergence-theorem sum, which
agrees with trimesh. Sourcing `volume` from one library and `genus`/`solid_count` from
another therefore put two different solids in one report. Both are now computed over the
exported triangles: components by shared-edge adjacency, genus as `(2 − χ)/2`. Relational
primitives (`min_distance`, `intersect_volume`) may still use manifold3d, because they
compare two shapes rather than reporting an absolute quantity about one.

A library that *rejects* its input must also be believed: manifold3d returns an errored,
empty object whose `.decompose()` and `.genus()` still answer, so `status()` is checked
before anything is read off it.

**Consequence for the domain profile.** Neither root cause was findable by reading the code
— both took a deliberately broken mesh and an independently computed reference — while 169
tests passed throughout, every one of them measuring a mesh that was already sound. That is
the project's own thesis turned on the project, and it is evidence for the success condition
in `PLAN.md` §0 rather than against it.

---

## D18 — Product boundary: the stateless gate, not the authoring loop

**Date:** 2026-08-07. Filed as issue #54 out of the tracker audit; ratified by Cameron with
the final wording delegated.

**Decision.** partspec is a **stateless declarative contract checker**. Its product is a
persisted, schema'd report and an exit code that gates CI (D5). It does not own the geometry
loop: no session state, no incremental modelling surface, no edit–render–look cycle. The
authoring loop belongs to authoring tools; partspec is the gate their output must pass.

**The evidence that the adjacent niche is occupied.** `pzfreo/build123d-mcp` is a stateful
interactive authoring session for agents — roughly 20 MCP tools around a persistent
`execute` session: PNG/SVG/DXF preview, measurement, feature detection for holes and hole
patterns, printability and fit validation, snapshots, 2D drafting. On the CADGenBench
leaderboard (June 2026) it raised the same model's score 0.360 → 0.457 and CAD validity
88% → 100%. Its own shipped prompt already assumes this split: *"let MCP own the geometry
loop and the skill own visual review and manufacturing handoff."* Epics #2 and #4, as first
filed, drifted toward that niche — where partspec would be a worse copy of a shipped tool
with published gains. Nothing in the repo drew the line, which is why the drift was
invisible. (Citations: [`notes/RESEARCH.md`][research] §6, and a local clone of the upstream
`build123d-mcp` project — gitignored, so it is a pointer for whoever has it rather than
something this repository carries.)

**What stays on partspec's side of the line** — what the authoring tools do not have: the
OpenSCAD tier; a persisted, schema-versioned report; adjudication in which `unsupported` and
`approximate` are non-green (D10, D17); exit codes CI can trust; and engine-version
determinism as a first-class concern (F13). A session tool tells the agent what it just
made; partspec proves whether that is the part the contract meant, and persists the proof.

**Consequences.**

1. **partspec's own MCP server (#27) is in scope and unchanged in kind** — the boundary is
   about state and loop ownership, not transport. Its tools are stateless verbs over
   `check` / `measure`: every call is a fresh evaluation of a contract against a source on
   disk, returning the same artifact the CLI writes. No tool holds geometry between calls.
2. **Renders (epic #2) are evidence attached to a report** — failure triage and human
   review — **not the agent's perception channel.** The primary channel is numeric. Four of
   the five dogfood payoffs were invisible to visual review (`PLAN.md` §7), and BenchCAD
   finds vision QA underperforming code QA by 15–20 points on identical questions. F13
   remains the honest case *for* renders — visible on re-render — and it is one of five,
   not the pattern.
3. **The recommended agent stack is both tools**, an authoring session inside the loop and
   partspec at the end of it — the relationship a REPL has to a test suite. README's Prior
   art records build123d-mcp accordingly, per the absorb-vs-depend standard (D7, D12).

---

## D19 — The road to v1.0 is depth, not width

**Date:** 2026-08-07. The ceiling question — is v1.0 the part, or the assembly? — was
delegated by Cameron: *"you decide what the proper boundary point would be all things
considered."*

**Decision.** Through v1.0 the unit of verification stays the **single part**, extending
D11 past v0, and the growth budget goes to **depth of intent** — the checks that decide
whether a built, watertight part is the *right* part (epic #6). Assemblies are the theme
that opens the post-1.0 line, not a v1.0 item.

**Reasoning.**

1. **The value is concentrated where the vocabulary is thinnest.** The 2026 benchmarks
   (Text2CAD-Bench, MUSE; [`notes/RESEARCH.md`][research] §1) find the same three-stage cascade —
   executes → geometrically valid → intent-aligned — with the last stage worst (the best
   closed models land at ~39–54% intent-aligned) and **largely independent** of the first.
   partspec's stages 1–2 are built and dogfooded; its stage-3 vocabulary is seven mostly
   global scalars. Effort spent widening to assemblies is withheld from the stage where
   both the failures and the differentiation live.

2. **Assemblies are an occupied niche, by D18's own logic one shelf over.** cad-khana *is*
   an assembly-relations checker, absorbed rather than depended on (D7); its best ideas —
   `qualified()` propagation, anchors, joint windows — are recorded in `POST-V0.md` §1 and
   keep. Re-deriving them before the part-level vocabulary has proven itself would be width
   into someone else's depth.

3. **Deferral is not foreclosure — v0 already paid the carrying cost.** Free-form check
   ids, `part_refs` on every check (to be re-introduced — §7.1 makes it additive),
   `skipped` as a legitimate run state
   (`SPEC-contract.md` §9). Nothing in a depth-first v1.0 makes assemblies harder later.

**What v1.0 therefore means.** An agent — or a CI job — given one part and one contract
gets a verdict deep enough to prove design intent, and there is transcript evidence that
the repair loop converges. Concretely: the agent loop shipped and measured (epic #4); the
intent vocabulary grown where a tier can answer honestly — BREP feature checks (holes,
patterns; the first real exercise of `approximate`, per `POST-V0.md` §4), keep-in/keep-out
regions (#49); and `diff`, closing the known contract-weakening gap (`POST-V0.md` §2).
Renders stay evidence (D18). Assemblies begin after that proves out, with `POST-V0.md` §1
as the design basis.

[survey-direction]: https://github.com/heibench/partspec/blob/main/notes/survey/DIRECTION.md
[research]: https://github.com/heibench/partspec/blob/main/notes/RESEARCH.md
