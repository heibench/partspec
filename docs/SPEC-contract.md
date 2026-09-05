# SPEC — the `partspec` contract

**Applies to:** v0.7.8 — the release this text describes. The `Status:` line records when
this document was last revised in substance; it is provenance, not currency (#300).

**Status:** draft 3 · 2026-08-09 · adds §4.8–4.11 (draft_angle, self_intersection_free,
step_roundtrip, min_wall) to the vocabulary table and the dimensional set; corrects the
constructor signatures in §3
**Scope:** the Python API an author (human or agent) writes to declare a part and the
claims it must satisfy. Defines the `kind` vocabulary that `SPEC-report.md` deliberately
left open.
**Normative:** MUST / SHOULD / MAY per RFC 2119.
**Backing:** D6 (contract is Python), D11 (parts only), D15 (measurand), `SPEC-report.md`.

---

## 1. Shape

A contract is an **ordinary Python module** that declares parts. It is not a config file,
not a DSL, and not a test file. Per D6 this buys expressiveness and costs no schema.

```python
# parts/bayonet/spec.py
from partspec import Part, openscad

SHELL_T = 2.5
PIN_R   = 1.0

def lock() -> Part:
    """The bayonet lock half. Defaults are the master design."""
    p = Part("bayonet-lock-pin", openscad(
        "vendor/bayonet_lock.scad",
        half="lock", interface_radius=8, allowance=0.2, part_height=8,
        entry_depth=4, number_of_pins=2, pin_radius=PIN_R, sweep_angle=40,
        shell_thickness=SHELL_T,
    ))
    # parameter phase — arithmetic over inputs, no engine needed
    p.requires("entry_depth < part_height")
    p.requires("pin_radius + allowance/2 <= shell_thickness")
    p.requires("0 < sweep_angle < 360/number_of_pins")
    p.param("interface_radius", min=0.1)
    # geometry phase
    p.envelope(max=(40, 40, 15))
    p.watertight()
    p.solid_count(1)
    return p
```

### 1.1 Rules

1. **A contract module MUST NOT do anything effectful on import.** No building, no export,
   no `if __name__ == "__main__"`. The CLI imports the module and applies exactly one
   effect. Borrowed from cad-khana, where it is load-bearing: the same module is imported by
   `check`, `measure` and `render`, and each applies its own single effect.
2. **A part factory is a module-level function annotated `-> Part`.** The annotation is the
   discovery mechanism (§2).
3. Contract modules MUST be importable without the CAD engines installed. Importing
   `partspec` MUST NOT import build123d, CadQuery, trimesh or OCP — those load lazily in
   the backend, so the parameter phase stays fast.

---

## 2. Target resolution

A **target** is `<module-path>[:<factory>]`.

- With `:factory` → call `getattr(module, factory)()` with **its defaults**. A factory's
  defaults are the master design.
- Without → if the module declares exactly one `-> Part` factory, use it. If it declares
  several, that is an error, and **the error message is the discovery mechanism**: it MUST
  list every available factory. (Directly cad-khana's `factories()` idea, which finds them
  by runtime introspection of the return annotation.)
- Resolution failure exits `64` (`EX_USAGE`) and writes no report.

Report paths derive deterministically from the target so co-located targets never clobber
each other's report, and a stale file is overwritten rather than accumulating beside its
replacement (`SPEC-report.md` §5.5).

---

## 3. Source declaration

One constructor per engine. Each takes a source reference plus the parameters to build with.

```python
openscad(path, /, method=None, backend=None, **params)  # -D name=value  (see §3.1)
build123d(path, /, method=None, **params)               # a .py file beside the contract
cadquery(path, /, method=None, **params)                # adopted via .wrapped (D3)
```

All three take a **path**, positionally. An earlier draft wrote `build123d(target,
**params)` and described `target` as `"module:callable"` or a callable — neither works:
the string is treated as a path and fails to resolve, and a callable raises `TypeError`.
Naming the factory inside that file is `method=`, the same parameter the OpenSCAD side
uses to name a module. `backend=` on `openscad` selects the mesh backend explicitly.

The engine is declared, never sniffed from the file extension: a `.py` file could be
either Python engine, and guessing is exactly the kind of implicitness this project exists
to remove.

`params` are the single source of truth for the build. They are what parameter checks
evaluate against, what is recorded in `report.params`, and what feeds `source_digest`'s
sibling identity. **A parameter MUST NOT be declared in two places** — if the `.scad` sets
`allowance = 0.2` internally and the contract also passes `allowance=0.2`, the contract
wins and the report records the contract's value.

### 3.1 OpenSCAD parameter passing

Parameters become `-D name=value` overrides of top-level variables. Where the contract
names a `method`, the parameters become a call to that module appended to a **throwaway
copy** of the source; the source file is never modified. This is PartCAD's proven approach
(D12) and is adopted deliberately.

Values render as OpenSCAD literals: numbers as-is, `True`/`False` → `true`/`false`, strings
quoted and escaped, sequences → `[...]`, `None` → `undef`. Any other type is a contract
error.

---

## 4. Check vocabulary — closed at each release

`SPEC-report.md` §7.1 declares `kind` an open vocabulary so the report format never needs
revising when a check is added. **This document closes it at each release**: v0 shipped the
set below through `topology`; `keep_out` / `keep_in` (§4.4), `hole_diameter` (§4.5),
`bolt_circle` (§4.6) and `fillet_radius` (§4.7) are the post-v0.1 additions, from epic #6;
`draft_angle` (§4.8), `self_intersection_free` (§4.9), `step_roundtrip` (§4.10) and
`min_wall` (§4.11) are the depth epic's (#136); `empty` (§4.12) is #257's.

### 4.1 Parameter phase

<!-- BEGIN GENERATED: vocabulary-parameter -->
| method | `kind` | shape |
|---|---|---|
| `p.requires(expr, id=)` | `requires` | predicate (see §5) |
| `p.param(name, min=, max=, unit=, id=)` | `param_range` | measurement + limit |
<!-- END GENERATED: vocabulary-parameter -->

`p.param` is the structured form and SHOULD be preferred when the claim is a simple bound
on one named parameter, because it produces a real measurement that `diff` can track drift
on. `p.requires` is the escape hatch for anything relational.

### 4.2 Geometry phase

<!-- BEGIN GENERATED: vocabulary-geometry -->
| method | `kind` | measurement | tier |
|---|---|---|---|
| *(implicit)* | `builds` | none | both |
| `p.empty(id=)` | `empty` | none | both |
| `p.envelope(max=, min=, id=)` | `envelope` | vector, `mm`, exact | both |
| `p.watertight(id=)` | `watertight` | bool-valued, exact | both |
| `p.solid_count(n, id=)` | `solid_count` | scalar, `count`, exact | both |
| `p.cavities(n, id=)` | `cavities` | scalar, `count`, exact | both |
| `p.genus(n, id=)` | `genus` | scalar, `count`, exact | both |
| `p.volume(min=, max=, id=)` | `volume` | scalar, `mm3` | both |
| `p.area(min=, max=, id=)` | `area` | scalar, `mm2` | both |
| `p.topology(faces=, edges=, vertices=, id=)` | `topology` | vector, `count`, exact | **occt only** |
| `p.keep_out(region, shell=, id=)` | `keep_out` | vector, `mm3`, exact | both |
| `p.keep_in(region, shell=, id=)` | `keep_in` | vector, `mm3`, exact | both |
| `p.hole_diameter(d, count=, tol=, id=)` | `hole_diameter` | vector, `mm`, exact | **occt only** |
| `p.bolt_circle(d, count=, bcd=, tol=, id=)` | `bolt_circle` | scalar, `mm`, exact | **occt only** |
| `p.fillet_radius(min=, max=, id=)` | `fillet_radius` | vector, `mm`, exact | **occt only** |
| `p.draft_angle(min=, direction=, id=)` | `draft_angle` | vector, `deg`, exact | **occt only** |
| `p.self_intersection_free(id=)` | `self_intersection_free` | bool-valued, exact | **occt only** |
| `p.step_roundtrip(tol=, id=)` | `step_roundtrip` | vector, `rel`, exact | **occt only** |
| `p.min_wall(min=, id=)` | `min_wall` | scalar, `mm`, **interval** (exact when it collapses) | **occt only** |
<!-- END GENERATED: vocabulary-geometry -->

`builds` is **implicit and always present**: every part gets it, and it fails if the engine
exits non-zero or emits no artifact — *unless* the contract declared `empty` and the engine's
own result was the empty one it declared, in which case the engine produced what it was asked
for and `builds` passes (§4.12). It is the one check an author cannot forget, and it is why a
contract with no declared checks still reports `empty` rather than crashing.

The word `empty` carries two unrelated meanings here and they are worth separating: the
**verdict** `empty` is a contract that declared nothing, and the **check** `empty` is a
contract that declared nothing was the result. A part can be neither, either, or — for a
`Part` carrying only `p.empty()` — not both, since that part has a declared check.

### 4.2.3 What the both-tier v0 measurements mean

The table names each kind's measurement **shape**; this says what the number **is**.
It covers the seven v0 geometry kinds that carry a measurement on both tiers —
`envelope`, `watertight`, `solid_count`, `cavities`, `genus`, `volume`, `area`. The
other three v0 rows are specified elsewhere and not repeated here: `builds` and
`empty` carry no measurement (above, and §4.12), and `topology` is OCCT-only (§4.2.2).
These are the conventions an author has to get right, and a guessed one is silent:
it produces a green run about a different claim rather than an error.

**`envelope` — the axis-aligned bounding box's EXTENTS, not its corners.** The
measurement is `(x, y, z)`: the part's size along each axis of the model's own
coordinate frame, in `mm`, taken over the whole part — measured, two 10 mm cubes with
a 10 mm gap between them report `(30, 10, 10)`. The box is axis-aligned rather than
fitted, so it is the part's size only when the part is square to the frame: the same
20 mm cube rotated 45° about z measures `(28.284271, 28.284271, 20.0)`. And it is
**translation-invariant** — a 40 × 30 × 6 mm plate reports `(40, 30, 6)` whether it
sits at the origin or at `(10000, 200, 300)` — so `envelope` never constrains *where*
a part is.

`min` and `max` therefore bound those extents. **The same API spells min/max the other
way one section down**: `region.box(min=, max=)` (§4.4) takes the box's min and max
*corners*. Carrying the corner reading into `envelope` writes a bound far looser than
intended and nothing says so — measured, that 40 × 30 × 6 mm plate at `(100, 200,
300)`, declared `p.envelope(max=(140, 230, 306))` from its far corner, passes, and the
identical declaration passes again against a part 120 mm wide.

A bound MAY be a bare scalar, which **broadcasts to every axis**: `p.envelope(max=45.0)`
bounds all three. A tuple MUST carry one entry per axis; `None` in a position is no
claim on that axis, and `checks[].components` then records only the axes actually
constrained. A tuple of the wrong length is a `ContractError` — *"vector limit has 2
components, measurement has 3"* — never a partial claim.

**`watertight`** is the boolean *every edge is bounded by exactly two faces*. It takes
no bound; `p.watertight()` claims True. It is a claim about the **surface**, not about
what the part contains: measured, a tray with an open pocket is watertight, one solid,
zero cavities and genus 0. On the OCCT tier the phrase is `is_manifold`, and it counts
**degenerate** edges — a sphere's poles are bounded by no area and used once each — so
it reads **false** on a sphere, a cone and a filleted box, all three of them closed.
`genus` (below) asks the same question of its own body and skips those edges,
which is why the two can disagree on the same part and why `watertight` is not the
closedness precondition `genus` uses.

**`solid_count(n)`** counts **solids** — closed, outward-oriented bodies — not surface
components. A sealed void is not a second solid: measured, a 20 mm cube with a 10 mm
cube void reports `solid_count 1` and `cavities 1`.

**`cavities(n)`** counts those **sealed internal voids**, the quantity `solid_count` was
once conflated with. `cavities(0)` is the claim that no void was left behind, which is
worth declaring: a void nobody asked for is trapped powder or a boolean that never
reached the surface.

**`genus(n)`** counts **through-holes, and only through-holes**. Measured on a 20 mm
cube: a Ø6 bore drilled through reports genus 1, the same bore drilled blind reports
genus 0, and a sealed void reports genus 0 — a blind hole is `hole_diameter`'s claim
(§4.5) or a region's (§4.4). It is read from the Euler characteristic, which is a
number about **one closed body**, so a part that is not one MUST be refused rather
than assumed. A part of more than one solid reports `unsupported` on both tiers, and
so does a wholly open surface — the mesh tier by testing closedness directly, the
OCCT tier because an open shell bounds no solid. Measured, the open surface says
*"genus is defined for a closed surface; this mesh is open along 4 boundary edge(s)"*
on the mesh tier and *"genus is defined per body; this part has 0 solids"* on the
OCCT tier; either way the run lands `incomplete` rather than buying a pass with
silence.

Both preconditions are checked on the OCCT tier too, and a whole **class** of
configurations used to escape them (#334). The guard there counted solids and never
tested closedness, so any body that is not itself a solid rode along beside one
without moving the count. Measured on a 20 mm cube bored Ø6 through, honestly genus
1: beside a disjoint face, a stray edge or a lone vertex it reported `genus 0`,
beside a `Shell` over the solid's own faces `genus 2`, all flagged `exact` — and a
contract declaring `genus(0)`, `watertight()`, `solid_count(1)` and `cavities(0)`
reported `PASS: 5 pass` at exit 0 on a part with a through-hole. **`watertight` is
not the missing test**: a vertex adds no edge, so manifoldness is unmoved and
`watertight` stays `true` while `genus` is wrong. It is not the closedness test
either: it counts degenerate edges, so measured it reads `false` on a sphere, a
cone and a filleted box, all three of them closed.

What is checked instead, stated where the measurement is taken:

- **One solid, and nothing else the formula would read.** The five counts the
  Euler characteristic reads — vertices, edges, wires, faces, shells — must be that
  solid's own. The refusal names what it found: *"genus is defined for one closed
  body; this shape carries 1 vertex beside its one solid"*. Geometry the solid
  already owns is not stray and is not refused, because it moves none of those
  counts.
- **That one solid closed.** `Solid(Shell(box.faces()[1:]))` is one solid carrying
  nothing beside it, and it reported `genus 0` on a surface that has no genus. Every
  edge of a closed boundary is bounded by exactly two faces — counted as *uses*, not
  as distinct faces, and skipping degenerate edges, which is where `watertight`
  differs (see above). Both directions are refused: measured, *"genus is defined for
  one closed body; it is not closed: 4 edge(s) not bounded by exactly two faces"*,
  on an open shell and equally on a solid whose partition edges are used by four
  faces.
- **A genus that is not negative.** The characteristic sums the genera of the body's
  shells, so a closed body cannot produce a negative one, and a solid whose single
  shell encloses two disjoint boxes does: measured `-1, exact` at 2000 mm³, with
  nothing beside the solid and every edge used exactly twice. Refused as *"the
  Euler-Poincare formula gives -1, which no closed body has"*.

Neither refuses more than the mathematics requires: a compound wrapping exactly one
solid still measures, and so does a solid with a sealed void — two shells, both the
solid's own, genus 0.

**On one member of that class the tiers still disagree, and it is a decision rather
than an oversight.** A stray vertex beside a solid: the mesh tier answers `genus 1`,
correctly, because it counts *referenced* vertices only; the OCCT tier refuses,
though it has the same answer in hand — it sums over the solid, not the compound. An
unreferenced vertex in a mesh is an artefact of the file format, while a `Vertex` in
a BREP compound is a body the model put there, and a part carrying one is not the
part the contract described. So a `genus` claim on such a part lands `incomplete` on
OCCT and decides on mesh. A wholly open surface is refused by both, and a part of
more than one solid by both.

**`volume(min=, max=)`** is the **enclosed material** in `mm3`, voids excluded — the
cube-with-a-void above measures 7000.0, not 8000.0. **`area(min=, max=)`** is the
**total** surface in `mm2`, cavity walls included — the same part measures 3000.0, the
2400 outside plus the 600 facing the void. Neither takes a tessellation tolerance, and
§4.2.1 is why.

### 4.2.2 `topology` — the check that makes the tiers visible

Every other v0 kind maps to a primitive both backends declare. `topology` is the exception,
deliberately — and since v0.1 it has company: `hole_diameter` (§4.5) is the first member of
the OCCT-only class whose machinery `topology` shipped to exercise. On the OCCT tier it
compares real modelled counts, and on the mesh tier it
reports `unsupported` with `requires: "occt"`, because a triangle mesh has faces only in the
sense that a mosaic has colours. Returning a triangle count is the PartCAD failure (D12), and
it is prevented structurally — the mesh backend does not declare the capability, so the
refusal happens before dispatch and no measurement is produced to be misread.

Its inclusion is what makes the degradation path **reachable from a contract**. Until it
existed, `SPEC-report.md`'s `requires` field was never populated in a real report and the
capability-refusal branch was unreachable code. A property that cannot be exercised is a
property that has not been tested.

Any subset may be constrained; an omitted axis carries no claim. Edge and vertex counts move
with modelling choices that are rarely intent, so `faces=` alone is usually the honest claim.
`p.topology()` with no arguments is a `ContractError`, not an empty pass — the vacuous-green
guard applies to a single check as much as to a whole contract.

**Its practical use is thin today, and that is recorded rather than papered over.** No part
in the dogfood corpus carries a face count that is *intent* rather than *incident* — the
pillow block's 15 faces are an artefact of how it was modelled, and Gridfinity's standard
fixes no topology, so asserting either would repeat the mistake F12 already caught. What
justifies the kind in v0 is that OCCT-only checks are a **class** the design already
committed to (`hole_diameter`, `fillet_radius`, `bolt_circle`, all post-v0), and shipping
one cheap honest member exercises the machinery those depend on instead of leaving it
unreachable until the first one lands.

A `topology` contract is portable in the sense that matters: it means the same thing on every
engine and says so where it cannot be evaluated. It is **not** portable in the sense of
turning green everywhere, and a part that needs it green belongs on a BREP engine.

### 4.2.1 A consequence of D15 worth stating plainly

An earlier draft required `volume` and `area` to carry a mandatory tessellation tolerance,
citing the 0.5 % drift measured between `$fn=32` and `$fn=128` (investigation 02). **Under
D15 that is wrong, and the reasoning is worth keeping.**

D15 fixes the measurand as *the artifact as authored and exported*. A mesh **is** a
polyhedron; its volume is computed exactly from its triangles. There is no smooth ideal it
approximates, so there is no tessellation error to tolerate. Changing `$fn` does not make a
measurement less accurate — **it produces a different part**, and a volume check written
against `$fn=128` failing at `$fn=32` is the tool working correctly, not a false alarm.

So `volume` and `area` take plain `min`/`max` bounds like any other range check, and the
author sets them from engineering intent rather than from anxiety about facets. The only
residual inexactness on the mesh tier is **float32 coordinate quantization in binary STL**,
which is real, rigorously computable, and roughly 1e-7 relative — see `SPEC-backend.md` §5.

This also retires the framing in `SPEC-report.md` §2 that treated tessellation as the
archetypal source of `approximate`. It is not; under D15 it is a source of *design
difference*, which is a thing the tool should report loudly rather than absorb quietly.

### 4.3 Deliberately NOT in v0

- **`clearance` / `interference`** — [`notes/survey/DIRECTION.md`][survey-direction] §5 listed these as v0 because they are
  *capability-portable* (exact on polyhedra via `manifold3d.min_gap`). **That was a
  category error: they take two bodies, and v0 is parts only (D11).** They move to post-v0
  with assemblies, where they have a subject. The portability finding stands and carries
  over unchanged.
*(Both `min_wall` and the BREP-tier feature checks were listed here and have since
shipped — §4.5–§4.11. `min_wall` remains `unsupported` on the mesh tier for want of an
honest lower bound, which was the real content of its entry.)*

- **`overhang`** — mesh-native and genuinely better there than on BREP, so it is *cheap*;
  deferred only because printability is a separate concern from dimensional intent and
  would widen v0's story.
- **`is_valid`** — implemented on both backends and reachable through `measure`, but
  deliberately **not** a check kind, because it does not mean the same thing on both. On the
  mesh tier it is "closed, consistently wound, non-zero volume"; on the OCCT tier it is
  "passes `BRepCheck_Analyzer`". Those disagree on real input — an open shell is `is_valid`
  **True** on OCCT and **False** on mesh. A kind whose meaning changes with the tier breaks
  "one contract, evaluated identically wherever it can be", which is a worse failure than
  the gap it would close. `watertight` already carries the portable half of the claim.
- **`center_of_mass`** — tier-consistent and cheap, and it will probably land; held back
  only because nothing in the dogfood corpus has needed it yet, and v0's vocabulary grows on
  demonstrated need rather than on availability. Visible through `measure` meanwhile.

### 4.4 `keep_out` / `keep_in` — interface intent without a second body

A region of space the part MUST be empty in (a bolt hole, a slot, a wrench clearance) or
solid throughout (a boss, a pin, a bearing seat). This is the one form of mechanical
interface intent that needs no reference model and no assembly support, and it is how
CADGenBench scores "interface match". Regions are declared as pure data from
`partspec.region` — `region.box(min=, max=)` and `region.cylinder(d=, h=, at=, axis=,
segments=)` — because the contract layer imports no geometry library (§1.1); each backend
materializes them via its `region_solid` primitive.

**A box is given by its two CORNERS; a cylinder by its BASE.** `region.box` takes the
min and max corners, in the model's own coordinates — the opposite reading to
`envelope`'s extents (§4.2.3). `region.cylinder`'s `at` is the **centre of the base
face**, not the centroid: the prism spans `h` from `at` in the named axis's POSITIVE
direction, and `axis` is the string `'x'`, `'y'` or `'z'`, never a direction vector
(#193, #199). Reading `at` as the centroid displaces the whole region by `h/2`, and
the displacement is silent — measured on `examples/stepper-bracket`, moving the
shipped `pilot-boss-clearance` region by ±h/2 along its own axis leaves both the
`ok pilot-boss-clearance` line and the `PASS: 10 pass` verdict unchanged. A region
that has drifted off its feature is still a region, so neither half of the paired
claim below is a guard against this; the convention has to be read, not discovered.

**The verification shell is mandatory, and it is the whole design.** The naive claims are
both vacuous: "no material here" is satisfied perfectly by a part with the material
deleted, and "material everywhere here" by an unbounded solid block. Each region is
therefore adjudicated together with a shell of thickness `shell` grown around it, holding
the *opposite* claim in weakened form:

- `keep_out`: the region MUST contain no material, **and its shell MUST NOT be entirely
  empty.** An absent part — and a hole whose clearance exceeds `shell` in every direction —
  fails.
- `keep_in`: the region MUST be entirely material, **and its shell MUST NOT be entirely
  solid.** The brick fails, and so does a feature oversize by more than `shell` in every
  direction.

The shell claims are deliberately the weak forms ("not entirely"), not the strong ones. A
strong keep_out shell — "entirely solid" — is failed by every clearance hole ever modelled,
because the modelled hole is always larger than the declared keep-out and the gap between
them is empty; the mirror kills the strong keep_in shell. `shell` is therefore read as
**the clearance budget**: material must appear within `shell` of a keep-out, and emptiness
within `shell` of a keep-in.

**A failing `keep_out` MUST report how deep the breach went, not only how much.**
Volume scales with the *area* of the contact and only linearly with depth, so a
hair-thin film over a large face outweighs a deep local spike, and faceting noise
reads the same as real interference (#207). The report therefore carries
`checks[].intrusion`. Diagnostic, not adjudicated: the claim is still "no material
here", and this says what the material did about it. Additive; `SCHEMA_VERSION`
does not move.

`min_depth_mm` is a **lower bound**, and the report MUST NOT present it as anything
else. The search erodes the region until the remaining intersection falls below
`detected_above_mm3`, which is small rather than empty, so the true depth lies above
the number by however far a sliver of that volume reaches. Where the search returns the
deepest value a region of that shape can yield at all, `depth_limited_by_region` is set
and the depth describes the declaration rather than the breach. That bound is the
region's own, not its inradius: the erosion runs out when the *region* holds less than
`detected_above_mm3`, which for an equilateral region is 5e-3 mm short of the inradius
whatever its size, and for an elongated one is far less — measured across shapes, from
3e-12 mm for a 400x400x8 plate to 3e-4 mm for a 0.3x4 pin. Implementations MUST NOT use
a fixed fraction of the inradius, which makes the flag a discontinuous function of the
declaration — measured, an 8x8x8 mm keep-out buried in solid material reported a partial
interference while 8x8x7.99, the same total breach, reported a complete one. Nor a fixed
ABSOLUTE one: the search's resolution is `inradius / 2**24`, which exceeds 1e-6 mm for
any region wider than 33.6 mm, so a 1e-6 slack silently stopped firing on most buried
cubes above 34 mm — 51% of integer sides in 34..100, 88% in 34..1000 — and
non-monotonically, side 50 firing where 60 did not. The slack MUST be the search's own
resolution: measured, a buried region sits under ONE interval short of the ceiling while
the nearest genuine partial intrusion sits TWO — which is why the slack is one interval
and not two. The margin is small and the difference is observable, so an implementation
that reads a comfortable multiple into this will withhold comparisons it owes.

**A `keep_out` at a bore's nominal diameter cannot pass, and the shortfall has two
terms — only one of which the contract can see.** `region.cylinder` CIRCUMSCRIBES the
declared circle (`_polygon_2d`), so every one of its `segments` corners stands
`r·(sec(pi/n) - 1)` proud of it. That radial excess is NOT the term, though: the depth
is an erosion, and `expand(-t)` moves the corners by `t·sec(pi/n)` rather than by `t`.
The corners clear a circle of radius `r` at `t = r·(1 - cos(pi/n))` — the sagitta,
smaller by exactly `sec(pi/n)`. That is `facet_floor_mm`:

| `segments` | floor at r = 20.5 mm |
|---|---|
| 16 | 0.39390 mm |
| 64 (default) | 0.024693 mm |
| 128 | 0.0061742 mm |

The radial excess shipped here for three review rounds — 0.12% high at 64 segments and
8.2% at 8 — and the resulting mismatch against measurement was explained away as the
bore's own faceting each time. Measured at 8 region segments the depth is 1.560399 mm,
against a sagitta of 1.560470 and a radial excess of 1.689040.

The second term is the modelled feature's own tessellation — on the mesh tier a bore is
*inscribed* in its `$fn`. It is not derivable from the declaration, because `$fn` is not
in it, and on an exact backend it is zero.

**How the two terms combine depends on how the two polygons are PHASED, and
`facet_floor_mm` MUST NOT be presented as a share of the depth.** The depth is bounded:

```
region term  <=  depth  <=  region term + feature term
```

— **the TRUE depth**, not the reported one. `min_depth_mm` is a lower bound on the true
depth (above), so it sits a little under the bracket's floor: 0.024684 reported against
a floor of 0.024693 at 64 segments, and 1.560399 against 1.560470 at 8. Read the bracket
as a statement about the geometry and the report as a conservative reading of it.

The region's corners sit at a fixed radius; the feature's own radius varies between its
inscribed and circumscribed values as the corner direction sweeps across a facet. So
where the depth lands in that bracket is set by how the two polygons are PHASED.
Measured against a Ø41 `$fn = 128` bore: at 64 region segments the corners land *on* the
bore's vertices, the feature contributes nothing, and the depth is 0.024684 mm — the
region's term (0.024693) alone, the bottom of the bracket. At 128 segments they land on
facet *midpoints* and the depth is 0.012341 mm — 0.9994 of the sum (0.0123484), the top.
Two earlier drafts of this paragraph asserted each end as the general rule and both were
measured false. A consequence: the depth is **not monotone in `segments`** — 0.024684 at
64, 0.012341 at 128, 0.006176 at 256, 0.006856 at 384, 0.006176 at 512.

So the floor is a *scale* the depth is read against: it says how much intrusion this
declaration would show against a perfectly circular feature. A report MUST print both
numbers and draw no conclusion from their comparison — `depth <= floor` licenses "the
region's own faceting could account for this", never "it did".

Raising `segments` shrinks the region's term quadratically but **does not make a nominal
bore pass**: the region's term falls but the feature's does not, and the depth tends to
the feature's sagitta rather than to zero — 0.006176, 0.006856 and 0.006176 measured at
256, 384 and 512 segments, against a feature term of 0.006174. It approaches that limit
unevenly rather than monotonically. What passes is a region whose own *corners* clear
the modelled surface, since the region circumscribes too. For a cylinder region against
a cylindrical feature, this is sufficient at every phase:

```
(d_region / 2) * sec(pi / segments)  <  (d_feature / 2) * cos(pi / $fn)
```

For the Ø41 `$fn = 128` bore at the default 64 segments that gives `d_region < 40.938`.
It is the WORST-phase bound, not the pass/fail boundary — measured, that boundary is at
40.95063 for this segment count, because the corners land on the bore's vertices and
the `cos(pi / $fn)` factor drops out. Use the inequality as a rule that always works,
not as the criterion. What does *not* work at any phase is the inscribed diameter,
40.98765, the natural reading of "strictly inside the modelled feature": it fails at
every segment count tried.

**What this deliberately does not claim: shape.** A hole oversize in one direction only —
an oval through a round keep-out — passes, because material still lies within the shell on
the tight sides. Roundness and diameter are `hole_diameter`'s claims. A region check is a
claim about space, and a contract that needs both should declare both.

**Materialization is tier-identical by construction.** A cylinder region *is* a
circumscribed `segments`-gon prism (flats touch the declared circle), built from one
canonical vertex list on every tier. Circumscribed, because the polygon then contains the
declared cylinder and an "empty" verdict is earned — no material can hide between polygon
and circle. The cost is radial over-approximation by `sec(pi/segments) - 1` (~0.12% at the
default 64), which fails a feature whose clearance to the declared region is micrometres; a
zero-margin region against its own feature's modelled surface is a claim the author should
not write, and on the mesh tier it was never available anyway (the modelled hole is itself
a polygon). Both statuses are conclusive: every volume involved is an exact boolean, so
`approximate` cannot arise; a mesh too broken for exact booleans reports `unsupported`.

The report records the declared region and shell on the check (`SPEC-report.md` §7.1), its
`measurement` is the vector `(region, shell)` of material volumes found, and `limit` is
null — the paired claim has no limit form, and inventing one would misdescribe it.

### 4.5 `hole_diameter` — the first drawing dimension

Exactly `count` cylindrical bores of diameter `d` exist. The first BREP dimension check
(POST-V0 §4), **OCCT tier only**: a triangle mesh has no cylindrical face, and fitting one
to the facets is the confident-wrong-number failure §4.2.2 exists to prevent. On the mesh
tier it reports `unsupported` with `requires: "occt"` — structurally, by the mesh backend
not declaring the `bores` primitive.

**The no-selectors resolution.** §8 deliberately provides no way to name a face, so this
cannot be "*this* hole is Ø8". It is a **count claim over detected bores**: the backend
enumerates every bore on the part, and the check asserts how many fall inside the diameter
band. A **bore** is a set of cylindrical faces sharing one axis line, one radius and one
contiguous axial span, facing *inward* (material surrounds the void — a boss is the same
surface facing out), whose angular extents sum to the full circle. Consequences, each
deliberate:

- **A counterbore counts once per diameter.** Its coaxial portions have different radii, and
  each is a real seat with a real drawing callout — `hole_diameter(8)` and
  `hole_diameter(12)` both hold on a Ø12-counterbored Ø8 hole.
- **A concave fillet (quarter-wrap) and a half-round groove (half-wrap) never count** —
  full-wrap is what separates "a hole" from "a concave cylindrical surface".
- **Two aligned holes through two clevis lugs count twice**: same axis, same radius,
  disjoint axial spans. The drawing says "2× Ø8" and so does the check.
- **Blind and through bores count alike.** Depth is not this check's claim.
- **A cross-drilled hole severed by a larger crossing hole counts once per severed span.**
  This is the clevis rule applied where the drawing disagrees with it: "1× Ø4 cross hole"
  through a Ø8 main bore is two disjoint Ø4 spans, so it counts as two — while two crossing
  holes of *equal* diameter still count once each, because their split spans touch at the
  intersection. An author cross-drilling through a larger bore should declare the count the
  geometry has, not the count the callout abbreviates.
- **A sealed internal cylindrical cavity counts.** The definition is a claim about surfaces,
  not about reachability — a tube's inner wall is a bore (the bearing-seat use case is
  exactly that), and a fully enclosed cylindrical void is the same surface with no opening.
  Nothing distinguishes them at the surface level, and inventing a reachability analysis to
  try would claim more than the check measures.

**What it deliberately does not claim:** position (that is `keep_out`'s and the future
`bolt_circle`'s territory), depth, and the absence of *other* holes — a part with an extra
Ø5 bore still passes `hole_diameter(8, count=2)`, because the claim is about the Ø8 bores.

**`tol` is the drawing's acceptance band** (Ø8 ±0.1 → `tol=0.1`). Omitted, the band is the
comparison epsilon — "modelled exactly as drawn" — the right default for CAD-as-code, where
the model is nominal geometry rather than a measured article. The band is materialised into
`limit` (`min`/`max`) at declaration and membership is plain interval containment: applying
epsilon again at adjudication would tolerance the tolerance.

**Exactness, recorded against a prediction.** POST-V0 §4 expected the first BREP check to
be the first real exercise of `approximate` (`SPEC-report.md` §3.1). It is not: a modelled
cylinder's radius is a surface *parameter*, read exactly, not an estimate carrying an error
interval. The measurement is the vector of matched diameters (exact, `mm`, axes
`bore_1..n`; null when nothing matched), which is what a comparator tracks drift on when a
real tolerance band is in play. The `approximate` machinery remains unexercised, and
POST-V0 §4 now says so.

The report records the declared bore on the check as `hole: {"d", "count"}`
(`SPEC-report.md` §7.1); a failing check's `detail` carries the full bore inventory of the
part, so the reader sees what exists rather than only what is missing.

### 4.6 `bolt_circle` — the mounting-interface callout

Exactly `count` bores of diameter `d`, axes parallel, centres on one circle of diameter
`bcd` — "4× Ø5 on Ø40 BCD" as one check. **OCCT tier only**, built on §4.5's bore
detection (`bore_table`), and adjudicated with **subset semantics**: the claim is that
such a circle of holes *exists*, so an unrelated Ø`d` bore elsewhere does not break it —
while a fifth hole ON the claimed circle does, because "4×" is a count, not a minimum.
Triples of candidate bores *seed* the search; each seed captures loosely (twice the
band), refits the centre by least squares over the capture, and adjudicates **strictly
against the refitted pattern circle** — a raw three-point circumcentre shifts by ~2x any
positional perturbation, enough to eject a conforming hole from a band it genuinely sits
in, and enough to let a cherry-picked centre defeat count exactness. The search is capped
at 60 candidate bores per direction; the cap produces a refusal only when the whole
search ends empty-handed with something unexamined — a passing circle found elsewhere is
still a pass.

Two deliberate edges:

- **`count=2` is a centre-distance claim.** Two bolts on a BCD sit diametrically
  opposite, and a circle through two points is under-determined — so the check asserts
  centre separation `bcd`, and *exactness of count* is only enforceable for `count >= 3`
  (two of four holes on a Ø40 circle genuinely are "2× on Ø40").
- **The bores' own diameters always match at the comparison epsilon**, never at `tol` —
  `tol` is the *positional* band on the circle diameter. A toleranced diameter claim
  belongs to `hole_diameter`; blurring the two would let a wrong-size hole satisfy a
  position claim.
- **`tol` MUST NOT exceed `d`**, refused at declaration. There is no datum to anchor the
  pattern centre (no selectors, §8), so the claim is existential — *some* circle of
  ~`bcd` holds exactly `count` holes — and a band wider than the hole itself makes that
  existential satisfiable by circles no drawing describes. The bound limits the residual
  rather than eliminating it: an author using an explicit `tol` near `d` on a part with
  many same-size holes has weakened the claim, and should keep `tol` at true-position
  scale, far below the hole spacing.

The measurement is the fitted circle diameter (exact, from exact centres; for `count=2`,
the pair closest to `bcd`, so the recorded value cannot depend on face-iteration order);
`limit` is the `bcd` band; the declared callout is recorded as `hole: {"d", "count",
"bcd"}`. On failure the detail carries the candidate count and the nearest circle found.

### 4.7 `fillet_radius` — every blend within bounds

`p.fillet_radius(min=, max=)`: every blend on the part is within the radius bounds.
**OCCT tier only.** `min=` is the machinability claim — no blend tighter than the tool
that must cut it.

**A blend is any partial-wrap cylindrical surface cluster**, either orientation, using the
same clustering as §4.5's bores — which is what stops a seam-split bore's two half faces
from masquerading as blends. Full-wrap surfaces (bores, bosses) never count; their radii
are `hole_diameter`'s business. Slot ends and grooves DO count, deliberately: nothing at
the surface level distinguishes them from fillets, and for the machinability claim they
constrain the tool identically — a definition that guessed at design intent would be
dishonest about what it measured. Toroidal and spherical blends are not yet detected;
that is a recorded gap, not a claim that they conform — and the zero-blend failure detail
names the gap rather than denying such blends exist. One further edge follows from the
partial-wrap definition: a bore *interrupted* along its wall (a keyway'd bore) wraps below
2π, so it leaves `hole_diameter`'s sight and appears here as a blend at the bore's radius.
Both effects err toward spurious FAIL, never silent PASS.

**Zero blends fails.** "Every blend is within bounds" over an empty set is vacuously
true, and vacuous truth is the green this tool refuses; an author who wants no constraint
on an unfilleted part does not declare the check.

The measurement is the full vector of blend radii, ascending, adjudicated by the generic
per-component machinery — so `components` (SPEC-report.md §7.1) names exactly which blend
broke which bound, and the failure detail reads `blend_1=1.5 outside min=2.0`.

---

### 4.8 `draft_angle` — every face releases from the tool

`p.draft_angle(min=, direction=(0, 0, 1))`: every face's draft is at least `min`, for a
mold pulled along `direction`. **OCCT tier only.** `min=` is the release claim — no wall
closer to vertical than the tool can eject.

**There is deliberately no `max=`.** Under the two-half convention every closed solid has
a face square to the pull (a cap, at 90°), so an every-face maximum is unsatisfiable by
construction — and the first draft of this check adjudicated `max` against each face's
MINIMUM draft, letting a face that violated the bound almost everywhere pass silently
(PR #141 review, F1: an executed silent pass). A bound that cannot be held to every face
is refused at the vocabulary level rather than quietly held to fewer.

**Draft is measured per face against a two-half parting axis**: the angle between the face
and the pull line, `asin(|n · d|)` — 0° for a vertical wall, 90° for a face square to the
pull. The two-half convention (the absolute value) is deliberate: a face releases with
whichever mold half it faces, so tops and bottoms measure 90° and pass a `min` naturally —
no exclusion rule exists to game, and the measure is orientation-independent, killing the
reversed-face bug class outright. The declared direction is normalised at declaration and
recorded in the check (`checks[].direction`), because a draft claim without its axis is not
reproducible.

**Exact, or refused — never sampled.** Planes answer directly; cylinders and cones at any
orientation answer in closed form (the face's normal dotted with the pull is a sinusoid in
the wrap parameter; its extreme over the face's wrap interval is at an endpoint, a crest,
or a zero crossing, all enumerable). A face outside those families — sphere, torus,
freeform — refuses the WHOLE check with the face and surface type named: a sampled minimum
has no guaranteed lower bound (more samples can only find a smaller draft, the same
one-sidedness that keeps `min_wall` out — POST-V0 §5), and a verdict that skipped a face
would be silence reading as success. This also means the check does not carry the
`approximate` obligation POST-V0 §4 records; that debt moves to the first check with a
genuinely bounded interval.

**What per-face normals cannot see is a recorded gap, not a claim**: a feature-level
undercut — material elsewhere blocking release along an otherwise-drafted path — is
invisible to surface interrogation. `draft_angle` proves wall-release geometry; it does not
prove moldability.

`min` must be in (0, 90]: the measure is non-negative by construction, so `min=0` would
pass every face vacuously and is refused at declaration. The measurement is the full vector
of per-face drafts, ascending, adjudicated by the generic per-component machinery — so
`components` names exactly which face broke which bound, and the failure detail reads
`face_3=0 outside min=2.0`. `min=` is a number an author chose, so the kind is in
`DIMENSIONAL_KINDS` and an unattributed bound draws the §6 warning; the pull axis is part
of the claim's identity, so `direction` is a claim field the report diff compares.

---

### 4.9 `self_intersection_free` — the shape does not cross itself

`p.self_intersection_free()`: no sub-shape pair intersects where the boundary says it must
not. **OCCT tier only** — D14 accepted the mesh-side gap deliberately rather than pull in
GPL libigl or heavyweight pymeshlab, and that decision stands; the mesh tier refuses with
`requires: occt`.

A self-intersecting BREP measures volume and topology plausibly and fails downstream —
booleans, STEP consumers, slicers — the classic silently wrong part. The check is the
kernel's own argument analysis (`BRepAlgoAPI_Check`, self-intersection mode): **exact**,
because it is analysis, not sampling. The failure detail is an inventory of the faults by
entity type (`8 self-intersecting entity fault(s): 2 edge/edge, 2 edge/face,
4 vertex/edge`) — "fault(s)", not "pair(s)", because a face caught against ITSELF reports
as a single entity.

**The recorded limit, executed:** a self-intersection lying within a single ANALYTIC
surface — the spindle torus, `Torus(6, 10)` — goes undetected and **passes**, alone, fused
with a box, or inside a compound. The escape is specifically the analytic case: the kernel
does test a face against itself, and a self-overlapping SWEPT face (adjacent helix coils,
pitch smaller than the profile) is caught as a pair-less fault. Both directions are pinned
by tests, so if the kernel's reach ever moves, the spec sentence moves with it.

**Relationship to `is_valid`, executed in both directions:** neither subsumes the other —
the overlapping helix is `is_valid` and self-intersecting; an open shell forced into a
solid is invalid and self-intersection-free. `is_valid` is BRepCheck's well-formedness;
this check is interference. Declare the one whose failure you mean.

**Multi-solid parts:** a compound of two overlapping unfused solids **fails** — a
multi-solid compound is one part, and its solids crossing is its own boundary
contradicting itself, not D11 two-body clearance (which needs two parts and stays with
assemblies). A part built as a compound of deliberately touching solids should be fused
before it is measured.

The quantity appears in `measure` (parameterless, like `watertight`), so an author sees it
before deciding to claim it.

---

### 4.10 `step_roundtrip` — the part survives its own exchange format

`p.step_roundtrip(tol=1e-6)`: written to STEP and read back, the part's volume and area
change by at most `tol` (relative) and its topology counts do not change at all. **OCCT
tier only** — STEP is a BREP format; a mesh has no BREP identity to preserve, and the mesh
tier refuses with `requires: occt`.

STEP is how a part leaves for manufacturing; a shape that degrades through its own
exchange ships a different part than the one verified. **Two gates, deliberately
separate**: topology drift (solids, faces, edges) fails at ANY tolerance — a count that
changed is a different part — and only then are the relative deltas held to `tol` by **plain membership — the tol IS
the tolerance, never epsilon-widened**. The shared comparison epsilon (§3.3's absolute
1e-6 floor, built for mm-scale STL round-trips) would silently swallow any tighter tol on
this unitless delta, recording a limit stricter than what was enforced (PR #143 review,
F2 — an executed incoherent artifact). The deltas themselves are **exact**: both sides
are the kernel's own exact quantities, so the comparison is a computed number, not an
estimate. (Consequence: this check does not carry POST-V0
§4's `approximate` obligation either; after this slice that debt rests entirely on
`min_wall`, #140, and if that slice ends in a recorded refusal the obligation stays
outstanding and recorded.)

**The default `tol` is calibrated, not chosen** — and recalibrated by execution: most
healthy families (booleans, fillets, lofts, text, 100-hole grids, 1e-3 to 1e6 mm scales)
round-trip below ~4e-13 relative, but the THREAD family — a helical sweep fused to a
cylinder, the canonical threaded rod — measures ~6e-9 on build123d 0.11.1 / cadquery-ocp 7.9.3.1.1 (PR #143 review, F1; re-measured for v0.7.0, where the recorded ~1.9e-8 no longer reproduced — the figure moves with the kernel, so it is named with its toolchain). Real
degradation — an ill-formed open shell forced into a solid, which the reader's healing
silently drops — loses its ENTIRE volume (`volume_rel = 1.0`, solids 1 → 0, the executed
degrader in the test suite). 1e-6 sits ~50x above the worst healthy citizen and six
orders below the failure; both halves are pinned by the threaded-rod test, so if
exchange fidelity moves, the calibration moves with it.

The writer schema (`AP214IS` on the current toolchain) is recorded on the check
(`checks[].step.schema`) because it changes the artifact — the F13 lesson. The exchange
happens in a scratch directory: the check is about survivability, not producing an
export. `tol` is a fidelity tolerance with a calibrated default, not a design dimension,
so the kind is deliberately NOT in `DIMENSIONAL_KINDS` and draws no attribution warning.

---

### 4.11 `min_wall` — every wall thick enough, within a declared measurand

`p.min_wall(min=)`: every wall of the part is at least `min` mm. **OCCT tier only.** The
first check whose measurement is a genuine interval, and therefore the first to exercise
§3.1's `approximate` adjudication — the debt POST-V0 §4 carried since `hole_diameter`
landed exact.

**The measurand, stated precisely** (the first draft claimed an unconditional
impossibility of false passes; PR #144's review falsified that by execution, twice, and
this section now says exactly what is measured): *the minimum span between non-adjacent
boundary faces through material, plus the certified diametric spans of closed analytic
faces.* Within that measurand the interval is guaranteed; outside it, unmeasured — and
the outside is recorded below, not denied.

**The bound.** `lo` is the minimum over ALL non-adjacent face pairs of the kernel-exact
distance (`BRepExtrema_DistShapeShape`). Gap-classified pairs are **retained** — any wall
between two faces is at least their pair distance, so keeping the gap value is always
sound, and PR #144 (F2) demonstrated that excluding such a pair once took a real 3 mm
wall with it into a `verdict: pass` on a `min=10` claim. The cost is honesty, not
tightness games: a claim limited by a nearby gap adjudicates `approximate` with the gap
named (`the bound is limited by a gap-like pair — a nearby void, not a proven thin
wall`), never a falsely tight pass. A closed analytic face (cylinder / sphere / torus /
frustum) contributes its diametric span unless an **exact boolean** — the axis edge or
tube circle common'd with the solid — certifies the enclosed line entirely void; PR #144
(F1) showed a single probe point is not a certificate (a cross-drilled rod's 4 mm
diameter was discarded because the probe landed in the hole, and the tool certified
19 mm, exact). A cone apex is the wedge-in-the-round and is skipped as a feature.

`hi` is the smallest measurand member the analysis can point to, from either of two
witnesses. An inward normal ray whose first exit lands on a non-adjacent face, or crosses
the same closed face diametrically — sampled on a parameter grid, which is why it is a
witness and not a bound. Or a **certified chord**: a diametric chord of a closed analytic
face whose exact boolean common with the solid has the chord's own LENGTH, so the span is
material end to end. The chord witness closes issue #145's two loosenings: it reaches the
narrow rim of a frustum, where the ray grid never samples (an interval of `[4, 6.88]` on a
part whose wall is exactly 4.0), and it answers a 45° frustum whose every inward normal
exits through an adjacent cap, which used to refuse the whole check for want of any
witness at all.

**Why a smaller `hi` is sound, stated precisely** (PR #146's review corrected the first
draft of this paragraph, which claimed more than the code proves). Two independent legs.
Adjudication is one-sided: a `min` limit at or below `lo` passes on `lo` alone, so
tightening `hi` can only turn an `approximate` into a `fail` — the false-alarm direction —
and never manufacture a pass. And a face's diametric span is a *member of the measurand
declared above*, so it is an upper bound on that measurand's minimum by definition; it is
also one of the values `lo` minimised over, which is why a certified span can never fall
below `lo` and why the two ends range over the same set. The boolean certificate is
therefore a **tightness gate, not the soundness argument**: it exists so the interval only
collapses where real material can be shown along the span, keeping the number tethered to
the part. Its teeth are that the whole chord must be material — a chord crossing a bore
does not certify, and one that is 95% material does not either — so it never degrades into
the probe-point fallacy of F1.

What the certificate does **not** prove is that the chord runs between two points of the
face. On a v-trimmed periodic face — a fillet band is a quarter-tube — the antipodal
parameter lands off the face, inside the solid, and the chord certifies anyway. The span
is still that face's own declared diametric span, so the bound holds; the fixture is in
the suite so the boundary stays visible rather than being assumed away. A fillet span can
therefore cap the interval, but it **cannot become the reported number**: a convex
full-revolution fillet's two flanks are non-adjacent, and their pair distance is
`2r·cos(θ/2)` for a dihedral θ, strictly below the `2r` span, so `lo` always sits under it
and the interval cannot collapse there. Executed across convex, concave, acute and obtuse
fillets on cylinders and frustums: `exact` never once landed on a fillet span.

Two consequences of that asymmetry are worth stating, because both invite a "fix" that
would be worse. Admitting a non-wall member (a fillet's tube diameter, a gap distance)
only ever pushes the reported minimum DOWN, toward `fail` — false safety comes from
members *removed*, which is what the recorded escapes below are. And restricting the
certificate to chords whose ends both lie on the face, applied consistently, would have to
restrict `lo`'s self-span set the same way — **removing** members and RAISING `lo`, which
is the false-pass direction. The looseness is deliberate; the symmetric tightening is not
available.

**A witnessed RAY crossing below `lo` refuses the whole check** ("the analysis contradicts
itself") — PR #144 (F3) found the first draft clamping exactly that counter-evidence
away, the thesis violation in one line. (A certified span cannot reach that tripwire, per
the leg above; what guards the chord machinery instead is a direct test that each family's
antipodal map really is diametric.) `[lo, hi]` collapses to exact on parallel-analytic
walls (uniform shells, tubes, sphere shells, the hidden thin spot, the cross-drilled rod's
diameter, every closed analytic family: hand-computed truth to 1e-9); a straddling limit
adjudicates `approximate` — the tool does not know, and will not guess.

**The wedge policy is structural, not a threshold.** Faces meeting at a shared edge are a
modeling feature — a wedge, a corner — never a wall; a 5.71° taper does not fail as a
sliver, and the moment the tip is truncated into an actual sliver the faces stop sharing
the edge and it is measured exactly (the 0.05 mm truncation fixture). cad-khana's
`min_wall_alignment` scalar was reconstructed and **falsified by execution** — a shallow
taper measures alignment 0.995, slab-indistinguishable — so the structural rule replaces
it. Consequences an author must know: a solid cone is vacuous (apex skipped, all faces
adjacent) and FAILS with the empty-set detail; and **filleting a knife edge flips it from
feature to wall** — the fillet band no longer shares an edge with both flanks, so the
real material behind it (0.6 mm for an r=0.3 fillet on a thin wedge) is measured and may
fail where the sharp edge passed. That is the material's truth, stated so nobody is
surprised by it. Since #145 the flip **fails conclusively rather than straddling where the
filleted edge is CLOSED**: a fillet band on a full-revolution edge is a closed analytic
face, so the chord witness collapses the upper end onto twice the fillet radius, and a
rounded Ø20 boss that used to report `[1.414, 20.0]` and shrug at a `min=3` claim now
reports `[1.414, 2.0]` and fails it. A fillet along a **straight** edge is an open strip
with no diametric certificate, so it still straddles — including the knife-edge-on-a-wedge
case this paragraph opens with, measured at `[0.599255, 1.167914]`, `approximate`, exit 2.
Both halves are stated because an earlier draft claimed the conclusive verdict for "the
documented fillet-flip" generally, which is the one example above that it does not cover. Correct within the
measurand — the 1.414 mm span is real — but a stronger verdict than "may fail", and
recorded here for that reason.

**Recorded escapes — what the measurand does not cover:**

- **Edge-sharing webs.** Material bounded by faces that share an edge — the web beside a
  drilled cross-hole, a boss root — is outside the measurand: the shared-edge span tends
  to zero at the rim (the same geometry as a wedge tip), so pair analysis cannot bound it
  without failing every drilled part. The cross-drilled rod reads its diametric 4.0 mm,
  NOT its ~1 mm web, and a test pins this boundary as executed fact.
- **Single-face folds.** A wall whose two sides are one open non-analytic face (a folded
  sheet modeled as a single spline face) has no pair and no analytic self-span.
- **Ledges bound like gaps.** A counterbore's radial ledge pair is wall-classified at ~the
  ledge width, and its planar sibling does the same: a 1.5 mm step on a slab whose every
  wall is 2.0 reports `lo = 1.5`. Neither is a defect in the bound — the ledge genuinely
  IS a 1.5 mm span between two non-adjacent faces through material, so the measurand
  contains it — but it means stepped parts straddle limits between the ledge and the true
  wall. The false-alarm direction, recorded (and pinned by a fixture) so the `approximate`
  is understood as structural, not sampling noise. The interval's *width* on such parts is
  loose for a second reason worth knowing: the ray witness samples only the faces that
  realized `lo`, so the 1.5 mm ledge above reports `hi = 27.0` — the width of the stepped
  section whose side faces realized it, not anything about the 2.0 mm wall.

**Gaps are not walls, but they bound them.** The U-channel (walls 3.0, gap 1.0) reports
`lo = 1.0, gap-limited`: conclusive pass for `min ≤ 1`, honest `approximate` above. The
same applies BETWEEN solids of a multi-solid part: inter-body clearance caps the bound,
so a compound can never conclusively pass a limit above its narrowest inter-body gap — the
referral for tighter gap claims is `keep_out`/clearance modeling, and a future certified
material-side separation could restore tightness without touching soundness. A part where
EVERY face pair shares an edge (a tetrahedron) has no walls and FAILS like
`fillet_radius`'s empty set: vacuous green, refused. Closed non-analytic periodic faces
and kernel-unresolvable pairs refuse the whole check by name.

**The mesh tier's refusal stands, with executed evidence** (#140's research, four
candidates run against fixtures with hand-computed walls): ray sampling is one-sided and
silent (1.75 reported on a true 0.8 wall at n=100, converging from above with no
completion signal; coarse tessellation makes it 13x); BREP inward-offset feasibility
certifies the wrong quantity (max inscribed depth — a false "walls ≥ 1.5" certificate on
a true 1.1 wall) and crashes or returns negative-volume "successes" on hollow shells;
voxel occupancy adds unsafe-direction gap fusion; morphological opening gives a real
bracket but only above a corner-shed noise floor, which is a threshold, not a bound.
POST-V0 §5's ship condition — "a different method on the BREP tier" — is met, within the
measurand stated above.

---

### 4.12 `empty` — nothing is the declared result

`p.empty(id=)`: the part is expected to build to **nothing**, and that is the passing
result. Both tiers. It has no backend primitive and takes no bound — like `builds`, it is
adjudicated from the build itself, which is why neither appears in `GEOMETRY_KINDS`.

**Why the vocabulary needs it.** An interference probe — `intersection() { A; B; }`
declared as its own part — could until this check grade only the *bad* outcome.
Interpenetrating parts give a closed solid and `volume` grades it. Parts that do not
interfere give nothing at all, and an empty build is a hard failure before any claim is
evaluated — so `volume(max=0)` was **skipped rather than satisfied**, and the good answer
was the one the tool could not state.

Parts resting on a face give a zero-thickness sheet, which `area` measures (§4.2) — but
only CGAL keeps that sheet reliably, so it is not part of this check's vocabulary. The
meaning below says why.

**Opt-in, and nothing else moves.** A part that does not declare `empty` and builds to
nothing still fails exactly as before. For an ordinary part contract a null render is a
real fault and this does not relax it; what changes is only that the intent can now be
declared.

**A broken probe must not satisfy it.** This is the whole difficulty, and it is not
visible in an exit code. On OpenSCAD 2021.01 a genuinely null intersection and a model
whose geometry never existed are **identical downstream**: both exit 1 with
`Current top level object is empty.` and write no STL. A misspelt module name, an
include that did not open, or a transform whose argument would not convert yields
nothing to intersect — so without a guard, one typo would make every interference probe
in a contract pass, and the more broken the source the greener the run.

The only evidence separating them is the engine's own diagnostics above that line —
`Can't open include file` / `Can't find include file`, `Ignoring unknown module` /
`function` / `variable`, `undefined operation`, and `Unable to convert`, each measured
under both pinned engines rather than assumed. `empty` therefore **fails when the engine
reported that it built something other than what the source describes**, and its detail
names the line. Engines own those strings, so the classification is made in the engine
and carried on `BuildError` (`produced_nothing`, `unresolved`) rather than by the runner
reading stderr.

Three causes reach the guard and the detail MUST name the one it found, because the
remedies do not overlap. A name that did not resolve is *the engine could not resolve a
name*; a value the engine could not convert — where it substitutes the module's own
default — is *the engine could not convert a value and built a default in place of it*.
Sending a reader after `OPENSCADPATH` for the second is advice about a library that is
not missing. Measured on both pinned engines, an `intersection()` whose second child is
displaced by `scale(undef)` renders genuinely empty at exit 1 and fails this check with
the conversion clause (#308).

The third is `Problem converting rotate(...)`, which OpenSCAD emits where the `rotate`
parameters could not be used *as written* (#333). It is **not** the second cause: an
over-long vector such as `rotate([90,0,0,0])` has its first three components read and
applied and substitutes nothing, so the detail says only *the engine could not use a
value as written* (#360). The refusal is the same — the source is wrong, and stderr
cannot say which of the shapes it is in (`FAILURE-MODES.md` 9b) — and the sentence
claims only what was observed.

A Python model has no equivalent hazard on either cause: an unresolved name raises, and
so does a value of the wrong type — neither silently renders empty, and no Python CAD
kernel substitutes a default for an argument it will not accept. Its null results all set the same flag, so the check reads the same on
either tier — a null shape, an empty CadQuery stack, **and an empty `Compound` with no
underlying handle**, which is what build123d returns for `a & b` on two disjoint solids
and so the one an interference probe on that tier actually produces. That third one did not
set the flag until #271, which meant `empty` could not pass on the OCCT tier for any
input at all while this paragraph said it read the same on both.

**What `empty` means.** A passing `empty` says the intersection of the two parts encloses
**no volume the kernel can represent** — no positive-volume interference, to the limit of
what the kernel keeps. Not "the parts do not touch", not "there is clearance", and not "no
interference whatsoever": that last qualifier is load-bearing, and §4.11 states
`min_wall`'s interval for the same reason.

**So `empty` over a bare pair is not a clearance**, and a contract that wants one MUST
intersect against a part **grown by the clearance it requires**: a violation with any
margin then encloses positive volume rather than a sheet, which makes the claim numeric;
how thin a violation still survives the kernel is the floor question below, and this
pattern does not escape it. At a gap of *exactly* the declared clearance the probe is a
zero-thickness sheet again and the pinned engines disagree — the degeneracy moves to the
boundary rather than disappearing. §9.1 rule 3 is the worked form and says to grade a
design gap strictly greater than the clearance; `partspec lint`'s
`csg-two-part-intersection` is the finding that says so at the source.

**Why it cannot mean more, and why it sometimes means less.** Past the unresolved-name
guard above, the check adjudicates on one thing: *did the engine produce anything*. That
coincides with "no interference" only where the kernel both refuses to represent a contact
and can represent every real overlap — and no kernel does both. The floors and the
sheet-representation split below are both consequences of that; manifold's
unpredictability is not, and is an independent fact about one kernel.

**Every kernel has a representational floor** beneath which a real interference is
discarded, and the floors sit in different places. Measured, each on a genuine
penetration:

| kernel | trips on | floor | result |
|---|---|---|---|
| OCCT — build123d / CadQuery | overlap depth | ≈5.97e-7 mm, constant | empty compound; `empty` passes |
| CGAL — OpenSCAD 2021.01 | a feature's cross-section | ~1.9e-6 mm for the probe below | nothing exported; `empty` passes |
| manifold — OpenSCAD 2026.08.01 | a feature's cross-section **or** its thickness | ~2.4e-7 mm near the origin for the probe below, coarsening with its coordinate | nothing exported; `empty` passes |

**The OpenSCAD figures are for one probe, and nothing more should be read into them.**
That row was measured with an axis-aligned square-section pin, its own dimension being the
feature, at positive coordinates — a shape chosen because it is easy to sweep, not because
it is representative. Three unstated parameters of it (pin length, penetration depth, the
other body's size) were varied over six combinations and did not move the floor, so a
reader can rebuild it and get those numbers.

**Everything else about this floor is uncharacterised, and this document no longer tries to
characterise it.** What is established is qualitative and enough:

- The floor is a property of the **arrangement**, not of the kernel. Rotating that pin by
  45° moves it. Making the interference an overlap between two blocks, rather than a body's
  own dimension, moves it by orders. The two backends differ from each other, and differ by
  shape in different directions.
- **Whether it coarsens with distance from the origin is itself construction-dependent.**
  manifold's square-pin floor coarsens 8× from coordinate 5 to 10 000; its rotated-pin floor
  does not move at all over that range (it does move further out). CGAL's did not coarsen in any construction tried — that is the one
  claim here that survived every attempt to break it.
- Every floor anyone has measured on this question has been **sub-physical for a real part**,
  by many orders. That conclusion has never depended on which of them is the largest.

**Four successive drafts of this passage each published a bound that the next measurement
falsified** — a formula fitted to nine same-shaped samples; a body-overlap figure measured
on an overlap thin on one axis and written about the case thin on two; a plateau a
triangular pin exceeds; and a range a sphere exceeds. Three came from bisections over
ranges whose monotonicity had never been checked, and the underlying function is not
monotone: a scan finds islands where a thinner feature survives and a thicker one does not,
so "the floor" is not always a well-defined number to begin with.

That is why this section states no bound, and it is the part worth carrying elsewhere: **a
claim fitted to a convenient sweep reads exactly like a measured one**, including to the
person who fitted it — four times in a row, each time while correcting the previous one.

The actionable half does not depend on any of the numbers: **a sufficiently thin
interference is discarded on every kernel, and `empty` passes on it.** What "sufficiently
thin" means depends on the geometry, so a contract that needs a guarantee should assert a
clearance with the grown-part pattern below rather than lean on a floor.

Two earlier drafts of this section overreached, and the second did it while retracting the
first. One stated a formula, `min(½·ULP32(coord), 2⁻¹⁹ mm)`, and the claim that no OpenSCAD
boolean resolves finer than 2⁻¹⁹ mm — both fitted to nine samples sharing one construction,
one sign and one cross-section. Its replacement then said a body-to-body overlap resolves
"on both backends down to at least 1e-9 mm", measured on an overlap thin on *one* axis and
written about the pin-in-a-hole case, which is thin on two and is lost on manifold at ten
metres. Recorded because the shape of the mistake is the useful part: a claim fitted to a
convenient sample reads exactly like a measured one, including to the person who fitted it.

OCCT's floor is a declared kernel constant and does not vary with the face or the
coordinate (measured out to 1e6 mm) — but the *volume* lost at it does vary with the face:
1.5e-7 mm3 across a 0.5 mm one, 2.2e-3 mm3 across a 60 mm one.

An earlier draft warned against relying on these floors *far from the origin*, on the
reasoning that they coarsen with distance; that reasoning was backwards for CGAL and only
sometimes true for manifold. They remain the direction in which a pass is weaker than it
reads, so they are stated rather than implied.

**And a zero-thickness contact is represented by some kernels and not others**, which is
the other half of the same bit:

| kernel | parts **touching** on a face | parts **clear** |
|---|---|---|
| CGAL — 2021.01 (its only kernel), or 2026.08.01 `--backend cgal` | a sheet — `empty` fails, `area` measurable | nothing — `empty` passes |
| manifold — 2026.08.01's default | unpredictable: usually nothing, sometimes a sheet | nothing — `empty` passes |
| OCCT — build123d / CadQuery | nothing — `empty` passes | nothing — `empty` passes |

Where a kernel discards the sheet, contact and clearance become the same downstream
signal, and nothing remains to tell them apart — which is why `empty` cannot mean "not
touching" however it is worded. CGAL is the predictable one: measured across eleven
arrangements it never varies. OCCT discards the sheet always — five distinct contact
types, including the two manifold keeps. **manifold cannot be predicted at all**: there are
pairs of solids whose intersection answers differently when the intersection's two
children are written in the other order, identical geometry either way. The flip is
deterministic across runs, so it tracks floating-point incidentals of evaluation rather
than noise — and no property of the arrangement predicts it, since a syntactic
reordering changes the answer. Nothing distinguishes the cases in the report:
`produced_nothing` is set or not, with nothing to say which produced it. (2021.01 does
not accept `--backend`; the flag names the kernel only on builds with more than one.)

**So it fails in both directions**, which is the "more" and the "less" above. Where a kernel keeps the sheet, a touching
pair builds geometry and `empty` **fails** although the interference is exactly zero —
on CGAL that is every face contact at any practical scale, its ordinary case. Where a
kernel is below its floor, a real interference **passes**. Measured on 2021.01, the same
part:

```
volume(max=0.0)  ->  ok volume    PASS
empty()          ->  FAIL empty — declared empty, but the part built geometry
```

Neither is fixable by wording, because both are that single bit being asked to answer a
question about volume.

**To assert a clearance, state the number and let a violation have volume.** Intersect
against a part grown by the clearance rather than against the part itself:

```openscad
// "is there interference" — this check
intersection() { a(); b(); }

// "is there 0.5 mm of clearance" — a solid when violated
intersection() { a(); grown_b(0.5); }
```

Declared with `empty` the second says *no part of `b`, plus 0.5 mm, meets `a`*. A
violation with any margin encloses volume rather than a sheet — only exact equality
between the gap and the declared clearance is degenerate — so every kernel agrees down to
its own floor, and the
bound is a number in the contract where a reviewer can see it. `partspec lint` flags the
bare form advisorily (`csg-two-part-intersection`, `LINT.md`) — the bare claim is valid,
it is simply narrower than it reads.

partspec does **not** select a backend to make this check answerable. Which kernel ran is
recorded, never chosen — F13's rule, and the reason the two options that would have had
partspec pin `--backend cgal` were refused.

**The claim is exclusive by nature, not by rule.** An empty part has no mesh, so every
other geometry check on it is skipped and the run reports `incomplete` (§3.1) rather than
a pass bought by silence. Declare `empty` alone on a probe.

Related: #237; #270 for the decision above; and §9.1 for the pattern this check
completes — a clearance probe's outcomes, worked in `examples/clearance/`.
Declaring part-versus-part interference with a first-class verb remains an
assemblies question (D19, #236).

---

## 5. Q7 resolved — predicates are not measurements

`SPEC-report.md` §11 Q7 asked whether `predicate` is a limit form or a kind, and flagged
`{"value": true, "unit": "bool"}` as a tell that parameter checks were being forced through
a model built for geometric measurement. **They were. Resolution:**

> A `requires` check has **no `measurement` and no `limit`.** It records the expression and
> the values of the operands it read.

```jsonc
{
  "id": "pin_fits_shell",
  "kind": "requires",
  "phase": "parameter",
  "status": "fail",
  "measurement": null,
  "limit": null,
  "expr": "pin_radius + allowance/2 <= shell_thickness",
  "operands": { "pin_radius": 1.0, "allowance": 0.2, "shell_thickness": 1.0 },
  "detail": "1.1 <= 1.0 is false"
}
```

This is strictly better than a bool measurement in three ways: an agent reading a failure
gets the *inputs that produced it* without re-deriving them; `diff` can report operand drift
on a check that still passes (the §7.2 principle, applied to parameters); and `unit: "bool"`
disappears, which was never a unit.

`expr` and `operands` are additive fields, so per `SPEC-report.md` §7.1 this is a
non-breaking change and does not bump `schema_version`. `bool` is removed from the §2.2
unit table.

**`p.param(...)`, by contrast, keeps the measurement/limit shape** — it *is* a bounded
scalar, and forcing it into the predicate form would lose the drift tracking that makes
§7.2 worth having. Two shapes, each where it fits.

### 5.1 Expression evaluation

`requires` expressions are evaluated against the declared `params` in a namespace
containing **only** those params and arithmetic builtins. No imports, no attribute access,
no calls. This is not a security boundary — the contract is already arbitrary Python (D6)
— it is a *legibility* boundary: an expression the tool can print operands for is worth
more than one it can only report as false.

An expression referencing an undeclared name is a contract error (`verdict: "error"`), not
a failing check. Chained comparisons (`0 < sweep_angle < 360/number_of_pins`) are supported
and record all operands.

**A `requires` expression MUST be a predicate.** The grammar is recursive, not a rule about
the outermost node:

> An expression is a *predicate* iff it is a `Compare`, a `BoolOp` whose every value is a
> predicate, a `UnaryOp(Not)` whose operand is a predicate, or a bare `Name`.

Anything else is a contract error. Python coerces freely, so without this
`requires("bore_d + 2*wall - plate_y")` — which reads like a clearance — is truthy for
every value except exact equality, and passes green while claiming nothing. The rule has to
recurse because `not (a - b)` and `a <= b and c` both have an admissible outermost node,
and `not X` always yields a genuine `bool`, so no check on the *result* can catch it.

A bare `Name` is admitted because bool parameters are a supported type and
`is_threaded and pitch > 0` is an honest claim. Every `Name` in boolean position MUST
therefore be verified to hold a `bool` **before** evaluation: `and`/`or` short-circuit, so a
guard on the result would fire or not depending on the parameter values, and a contract-shape
error that depends on the values is not one.

Two further refusals, both of expressions that cannot fail:

- An expression that reads **no declared parameter** (`operands_of(expr) == ()`) — its
  result is the same on every run. This matches `Limit.__post_init__`, which already refuses
  a bound that constrains nothing.
- A comparison whose two sides are the **syntactically identical** operand (`x == x`,
  `x >= x`). Broader semantic tautology detection (`x - x >= 0`, `x < x + 1`) is out of
  scope: the cheap syntactic case is worth catching, and the general case is undecidable
  enough that a partial job would mislead about what is guaranteed.

---

## 6. The vacuous-green guard

A `Part` with no declared checks beyond the implicit `builds` produces `verdict: "empty"`
and exit `3` (`SPEC-report.md` §6). The CLI MUST additionally emit a one-line warning
naming the part, because `empty` is the single most likely output when an agent does not
know what to assert, and a silent exit `3` in a batch is easy to miss.

**A run whose every dimensional check is unattributed MUST draw one warning line** on the
same channel, naming the part (#50). The dimensional kinds are the ones whose limits are
numbers an author chose, and so the ones a contract can make circular — a bound recomputed
from the model's own constants cannot fail however the design moves, and a single green run
cannot distinguish that from a proof.

<!-- BEGIN GENERATED: dimensional-kinds -->
`DIMENSIONAL_KINDS`: `param_range`, `envelope`, `volume`, `area`, `keep_out`, `keep_in`,
`hole_diameter`, `bolt_circle`, `fillet_radius`, `draft_angle`, `min_wall`
<!-- END GENERATED: dimensional-kinds -->

Attribution (§10) is the distinguisher: **the absence of `source` IS the unattributed
state** — the report does not stamp "unattributed" per check, because an absent claim of
authority must not be dressed as a present one. Topological kinds are absolute claims,
non-circular by construction, and never trigger the warning. Two exclusions are
deliberate and recorded: `requires` predicates are intrinsically relational — attribution
cannot reach an expression string, and counting them would warn forever on legitimate
internal-consistency claims with no remedy — and `keep_out`/`keep_in` regions do not yet
carry attribution (§10), so they stand outside the dichotomy until they do; a
region-only contract receives no warning today, and that is a recorded gap, not a claim
of coverage. The warning is one line, not a status: the five-member status set is closed,
and an unattributed pass is still a pass — of a weaker question. The run-level counts
behind it are in the report as `attribution` (`SPEC-report.md` §7.1), because the report
is the product surface and an agent consuming it over MCP never sees stderr.

**`partspec` MUST NOT auto-generate checks** from an existing part — not even as a
convenience. A check the tool wrote is a check nobody decided, and a report full of them is
vacuous green wearing a costume. `measure` (§7) exists precisely so that authoring a
contract from a real part is easy *and explicit*.

---

## 7. `measure` — how contracts get written

`partspec measure <target>` builds the part and dumps every quantity the backend can
honestly produce, with `exactness` on each, and **turns nothing it could not answer into a
number**. It is not a check run and produces no verdict. What it could not answer it names
rather than omits, in one of two blocks: `refused` when this part defeated the measurement,
`unavailable` when this tier cannot answer it for any part (`SPEC-report.md` §7.3).

This is the adoption path and the answer to "how do I retrofit contracts onto 30 existing
OpenSCAD libraries": measure, read, decide which numbers are *intent* rather than
*incident*, and write those as checks. The judgement stays with the author; the arithmetic
does not.

**`<target>` is a contract, never a model.** `measure` resolves its target exactly as
`check` does (§2) — a module declaring a factory annotated `-> Part` that returns a
`partspec.Part` — so the first step of a retrofit is to *write* one. A `Part` carrying an
id and a source and no checks at all is the smallest contract `measure` accepts, and it
reads every quantity the backend can produce:

```python
# probe.py — the whole contract
from partspec import Part, openscad

def probe() -> Part:
    return Part("probe", openscad("../vendor/bracket.scad"))
```

Naming the **model** instead exits `64`. That it gets as far as being called is worth
stating, because it decides what the diagnostic can say: a build123d or CadQuery model
annotated `-> Part` is annotated with *its* library's `Part`, and target resolution
compares the annotation by name, so such a model is discovered as a factory like any
other and refused only on what it returns. The refusal therefore MUST locate the returned
type — `build123d.topology.composite.Part`, not `Part` — since the unqualified form states
the collision as though it were a contradiction. Where the class is defined in the
contract file itself, the locus is that **file**: modules loaded this way are synthesised
under a per-process name, so qualifying by module there would print a different string on
every run. Both halves are pinned by
`tests/test_cli.py::test_the_refusal_locates_the_type_it_got`, which reads the expected
module off the returned class rather than restating this sentence.

`measure` deliberately reports a **superset** of the check vocabulary. `is_valid` and
`topology_counts` appear here and are not kinds (§4.3) — the first because its meaning
differs by tier, the second because only one tier can answer it. Both are worth *seeing*
while deciding what to claim, which is what this verb is for, and neither can mislead here
because the output carries no verdict. On a mesh, `topology_counts` is therefore in
`unavailable` and never present-and-wrong. It is **named there, not absent**: an omission
would read as "this part has no topology to speak of" to exactly the author this verb
exists to serve, when what happened is that the tier cannot see it. Run against the
example spacer, `unavailable` reads
`["self_intersection_free", "min_wall", "topology_counts", "bores", "blend_radii"]`.

---

## 8. Non-goals

- **No assemblies, no placement, no joints.** Per D11. §9 records what the v0 model must
  not foreclose.
- **No selectors.** There is no way to name a face or an edge. This is cad-khana's
  deliberate simplification and it is why twelve backend primitives suffice — it sidesteps
  the topological-naming problem entirely.
- **No solver.** Checks check; they do not drive. A contract never adjusts a parameter to
  make itself pass.
- **No severity.** Every declared check is load-bearing (`SPEC-report.md` §9).

---

## 9. Forward compatibility with assemblies

D11 requires the v0 model to *carry* assemblies later rather than be retrofitted. Three
constraints, adopted now at no cost:

1. **`checks[].id` is a free-form string**, so dotted paths (`turret.rotor.arm`) fit without
   a schema change.
2. **A check will record the part references it read** when there is more than one part to
   refer to. The field was carried in v0 as forward-compat and removed in v0.7.0: it was
   set on three code paths, never serialised, and so could not be read from any artifact —
   a cost paid for a benefit nobody could collect. `SPEC-report.md` §7.1 makes added fields
   non-breaking, so assemblies can introduce it for real. It is what makes cad-khana's `qualified()` propagation
   possible later.
3. **The `skipped` status already exists** with the semantics assemblies need — *"absence is
   a legitimate run state, not an input error"* — so a standalone sub-assembly run can
   evaluate the same check list without the absent parts.

### 9.1 Part-versus-part interference, with the unit of verification v0 has

Until an assembly verb exists, interference between two parts is declared by modelling
`intersection() { A; B; }` **at assembly pose** as a part of its own and claiming the
outcome the design intends. `examples/clearance/` is the worked pattern.

**`partspec lint` flags every probe written this way, and that is expected.**
`csg-two-part-intersection`'s predicate is the shape — one top-level node, an
`intersection()` of exactly two children — which a part-versus-part probe has by
construction, whether or not it grows a part per rule 3 below. The finding is advisory and
never a verdict on the part (`docs/LINT.md`, "Known noise, owned"), and on a grown probe
its own advice has already been taken. Read it, satisfy yourself that the clearance you
meant is the clearance you wrote, and accept it. This section recommends a pattern the
tool's own lint remarks on; an author should meet that in the spec rather than in a
surprising run.

Every pair of parts is in exactly one of three states, and each grades on a different
measurand. **Two of the three answer the same way on every engine and are what this
section recommends; the third does not and MUST NOT be declared as if it did:**

| the two parts | the probe builds to | the claim | in the example |
|---|---|---|---|
| interpenetrate | a solid | `volume(min=, max=)` | 24.0 mm3 |
| stand off by a stated amount | nothing | `empty()` over a **grown** part | pass |
| touch on a face | a sheet | `area(min=)` | not portable — see below |

**Both recommended rows are recent, and one was a hard failure before its own fix.** A
null intersection failed its build before any claim could be evaluated, so `volume(max=0)`
was *skipped rather than satisfied* until §4.12 (#237, a companion of #236). §4.2's
admission of `area` as the measurand for a part that is not a solid (#238) is what makes
the third row expressible at all — but expressible is not portable, and the two are
different questions.

**Face contact is kernel-dependent and is excluded on that ground.** A probe of two parts
that merely touch is a zero-thickness result, and what an engine does with one is a
property of its kernel. Measured on the two pinned OpenSCAD versions, `intersection()` of
two 10 mm cubes offset by exactly their own width: 2021.01 exports a 284-byte sheet and
`check` exits 1; 2026.08.01 exports nothing, and `check` exits 0. One source, two engines,
opposite verdicts. Under #270's settled semantics — `empty()` means *no positive-volume
interference* — the newer engine is the correct one, so the divergence cannot be resolved
by preferring the richer result. And retention is not the only axis: on
`examples/clearance/`'s own seated face the two engines each write a four-triangle sheet
and **disagree about its shape**, 384.0 mm2 against 268.8 mm2. A producer that could
record whether the kernel retains a zero-thickness result (#314) is the enabler; until a
report can state which behaviour was in force, an `area` claim over a contact patch means
whichever engine ran it. An author who needs bearing area SHOULD give the seat a
deliberate interference and grade the volume.

**Three rules the pattern depends on.**

1. **Poses live in one file.** The probe intersects two modules *as placed*, so an
   interference number is the assembly's and not a number about geometry at the origin.
2. **`empty` goes on the probe that should be empty and on no other.** On an interference
   probe an empty build is the *loose joint* — the failure — so declaring `empty` there
   would grade the fault as the pass. And declare it alone (§4.12).
3. **A clearance probe MUST intersect against a part grown by the clearance.** `empty()`
   over a bare `intersection() { A; B; }` says only that the two do not interpenetrate:
   it is equally satisfied at 9 mm of standoff, at 0.01 mm, and — on a kernel that drops
   a zero-thickness sheet — at exact contact. A clearance is a number and that probe
   carries none. Grow one part by the standoff the fit requires and a violation with any
   margin is a **solid with positive volume** rather than a sheet, which every kernel agrees
   about down to its own floor (§4.12). Measured in
   `examples/clearance/` by dropping the lid to a 1.0 mm standoff against a required
   1.5 mm: the grown probe fails on both pinned engines at 31.5 mm3, and the ungrown one
   passes on both. This is the remedy `partspec lint`'s `csg-two-part-intersection`
   names, and the rule fires on the probe either way — its predicate is the shape, which
   every part-versus-part probe has by construction (`docs/LINT.md`).

   **Growing relocates the degenerate case, it does not remove it, so grade a design gap
   strictly greater than the clearance.** At a gap of exactly `CLEAR` the probe is a
   zero-thickness sheet — the same artifact this section refuses above — and the two
   pinned engines disagree about it. Swept on `examples/clearance/`:

   | design gap, `CLEAR` = 1.5 | 2021.01 | 2026.08.01 |
   |---|---|---|
   | 1.6 mm | exit 0 | exit 0 |
   | **1.5 mm — exactly `CLEAR`** | **exit 1** (284-byte sheet, "may not be a valid 2-manifold") | **exit 0** (exports nothing) |
   | 1.49 mm | exit 1 | exit 1 |

   Only exact equality is degenerate (§4.12 states the same), but it is the value a
   designer working *to* the requirement lands on. This is why the example designs a
   2.0 mm standoff against a required 1.5 mm: the margin is load-bearing, not arbitrary.

   **A box grow measures Chebyshev distance, not Euclidean.** Growing an axis-aligned box
   by `CLEAR` per axis strictly contains the true offset, so the error is false FAIL only
   and never false PASS, and both engines agree — this is not F13. Measured: a body whose
   nearest corner sits 1.2 mm away on each axis is 2.0785 mm away in a straight line and
   still fails a 1.5 mm requirement, on both engines.

   **If the fit cares about Euclidean distance, `minkowski()` with a sphere is the
   spelling — but the sphere MUST be compensated by `cos²`, and the segment count MUST be
   a named variable rather than `$fn` in the argument list.** The form is:

   ```openscad
   CLEAR = 1.5;   // the standoff the fit requires, mm
   SEG   = 32;    // one name for the radius AND the facet count
   sphere(r = CLEAR / pow(cos(180 / SEG), 2), $fn = SEG);
   ```

   OpenSCAD's `sphere()` is a faceted solid whose vertices lie *on* the ideal ball, so it
   is inscribed and the envelope falls short of the true offset. It is faceted in **two**
   angular directions, so the worst-case shortfall goes as `cos²`, not `cos`: a one-axis
   check does not see it, because the axial direction is not the worst one. Measured from
   the exported ball on both engines, `CLEAR` = 1.5, `SEG` = 32:

   | grow (all with `$fn = SEG`) | guaranteed offset (min face plane) | max offset (vertex) |
   |---|---|---|
   | `sphere(r = CLEAR)` | 1.485589 | 1.500000 |
   | `sphere(r = CLEAR / cos(180 / SEG))` | 1.492777 | 1.507258 |
   | **`sphere(r = CLEAR / pow(cos(180 / SEG), 2))`** | **1.500000** | 1.514551 |

   Only the third reaches the required 1.5 in **every** direction, and it does so exactly
   at `SEG` = 8, 16 and 32. End to end against a body approaching along the sphere's worst
   direction, both engines: the first two **pass** violations at 1.495 mm and 1.499 mm,
   the third fails both and passes at 1.520 mm. The bare shortfall is 0.057090 mm at
   `SEG = 16` — inside a printed fit's tolerance.

   **Why the segment count must be a named variable.** A module call's arguments are
   evaluated in the **caller's** scope, so `$fn = 32` in the argument list applies inside
   `sphere` and not to the sibling `r =` expression. Spelled
   `pow(cos(180 / $fn), 2), $fn = 32`, the radius reads the *caller's* `$fn` — 0 by
   default — so `180/$fn` is infinite and the radius is `nan`. The engines then disagree:
   measured, that envelope reaches 1.507257 on 2021.01 and **nothing at all** on
   2026.08.01, where `minkowski()` yields the bare ungrown part, and the probe passes a
   0.1 mm gap against a 1.5 mm requirement at exit 0. One source, two engines, different
   geometry — F13, on this section's own prescribed spelling, which is why the named
   variable is normative and not style. Measured in five caller shapes — top level, inside
   a module, with a global `$fn` of 64, with a global `$fn` of 8, and with `$fa`/`$fs` and
   no `$fn` — the `SEG` form gives an identical envelope in all five on both engines.

   Compensated this way the residual error is **one-sided toward false FAIL**, out to the
   vertex column above — the same property the box grow has. Uncompensated, or compensated
   only by `cos`, it is one-sided toward false **PASS**, which is why this is a MUST.

   `empty` carries no bound, so the clearance number lives in the model rather than in
   the contract. That is the one place this pattern is weaker than a bound-carrying
   check, and an author should know it rather than discover it.

**What it costs, stated plainly**, because this is a pattern and not a feature: one extra
source and one extra target per pair, the pair modelled at assembly pose, a grown module
for every clearance stated numerically, and no automatic all-pairs sweep. A first-class verb taking N sources and reporting pairwise shared volume
needs `intersect_volume` and nothing else — no offsetting, no shell, no bisection — and is
what the problem actually is. It is an assemblies feature, so it lands after 1.0 under D19.

**Not `keep_out`/`keep_in`.** Those take a declared region — box or cylinder — because
their shell is mandatory and a shell is an offset of the region, which a rendered solid
can only supply through 3D offsetting: measured, `manifold3d`'s Minkowski gives the
outward offset in 13 ms and the inward one in 1290 ms, inside a 24-iteration bisection.
The shell exists to stop a `keep_out` passing vacuously when the feature is simply absent,
and for part-versus-part interference that risk does not arise — the other part is a real
rendered solid, and its absence is a build failure rather than a silent pass. So the
expensive machinery would be bought for a guarantee this case does not need (#236).

---

## 10. Referenced values — where a limit's number came from

Every payoff in the dogfood came from a human supplying an external reference (ISO 15's
22 mm, the NEMA bolt pattern). A limit is only as good as where its number came from, and
`Referenced` is how a contract records where that was: a float subclass that IS its value
— it compares, renders and serialises as a plain number — and additionally carries a
citation, conventionally `{"standard", "subject", "field"}`.

```python
from partspec.refs import iso15

seat = iso15.bearing(608)
p.hole_diameter(seat.od, tol=0.05)     # the check records source: ISO 15 / 608 / od
p.volume(min=1000.0)                    # a bare literal records nothing
```

The bound-carrying methods (`param`, `envelope`, `volume`, `area`, `hole_diameter`,
`bolt_circle`, `fillet_radius`, `draft_angle`, `min_wall`) record
`source: {field: citation}` on the
check when a `Referenced` reaches their bounds (`SPEC-report.md` §7.1) — the report states
not just what was claimed but on whose authority. `keep_out` and `keep_in` do the same for
the dimensions of the region they take — a box's `min`/`max`, a cylinder's `d`/`h` — and for
`shell`. A region's `at` is deliberately excluded: a standard vouches for how big a feature
is, never for where this design puts it, so a position stays the author's even when every
number in it came from a table. Three rules:

1. **Attribution is additive, never required.** Bare literals behave exactly as before.
2. **Arithmetic sheds it.** `seat.od + 0.1` is a plain float: the derived number is the
   author's, not the standard's, and carrying a citation across an operation the cited
   document never performed would launder authority. (#50 builds the warning channel on
   this axis: a run whose every dimensional limit is unattributed will say so.)
3. **A citation locates, it does not reproduce.** `{"standard": "ISO 15", "subject":
   "608", "field": "outside_diameter"}` is enough to find the number; the tables never
   carry a standard's text.

### 10.1 Scope policy for `partspec.refs`

In scope: **dimensional interface facts** that are widely published and independently
verifiable — boundary dimensions, bolt patterns, envelope sizes — as pure stdlib data,
**shipped in the wheel**: tables this small carry no dependency and no meaningful size,
and an extra would put an import error between an agent and the numbers.
Out of scope: reproducing any standard's text, figures, or tolerancing tables, and any
value not verifiable from public manufacturer documentation. An unknown designation is a
`ContractError` naming what the table does carry — a table must not guess.

**One exception to the tolerancing exclusion, and the test it must pass.** A standard's
tolerance **grades** and **fundamental deviations** are in scope where the standard states
them as a *formula* and that formula is executed by the test suite against every value
shipped. **Limits of size stay out.** The distinction is not size, it is what can be
checked: a deviation a table recomputes from the standard's own formula is verifiable by
construction, which is a stronger guarantee than any boundary dimension in these tables
gets — nothing arithmetically validates a bearing's 22 mm. A limit is a *fit*, and a
wrong digit in a fit is a part that does not assemble under a citation saying the standard
blessed it: worse than no data, because the reader stops checking. So the author derives
the limit from the deviation and the grade and owns the result (§10 rule 2), or a fragment
derives it and states the derivation in the citation's `note` (§11 rule 3). A table that
cannot execute the formula ships nothing: the exception is the test, not the subject
matter.

**ISO 965-1 was tested against this exception and does not meet it — recorded so the work
is not repeated.** Its clause 10 states the deviation and grade formulae the exception
anticipated, and its §10.1 also states that "in order to reproduce a smooth progression,
the rules of rounding off are not always used" and that "when the tolerance values
calculated from the formulae are different from the values specified by the tolerance
tables, the values in the tolerance tables shall be used". Measured against
ISO 965-1:2013 Table 1, executing every clause-10.2 formula with the R40 rounding §10.1
prescribes: **149 of 197 cells agree and 48 do not**. That is the *best* of fifteen
rounding models swept; the standard rounds half-to-even, which its own tables give away —
the images only half-up can produce (13, 27, 43) appear nowhere in Tables 1–5, while the
images only half-even can produce (26, 42) appear five times in Table 1 alone.

The divergence is not a rounding artefact. `es_d = −(65 + 19P)` at P = 8 gives −217 raw
and −212 rounded against a tabulated −180 — 32 µm that no model bridges, and column `d`
carries −105, −110, −115, −130, −135 and −155, none of which is the rounded image of any
R40 member. So both routes fail: the tabulated values cannot execute the formula, and the
computed values are ones the standard says shall not be used.

**The near miss was considered and rejected.** `EI_G` and `es_g` each reproduce 24 of 25
cells, missing only at P = 0.75, and all 15 cells at P ≥ 0.8 — the 6g/6G deviations,
which would cover every coarse thread from M5 up. (At P = 8 the formula lands on 103,
exactly between the R40 members 100 and 106. Table 1 resolves that tie downward, while
Table 2 resolves the same kind of tie at `TD1(6)`, P = 1 upward — so not even the tie
rule is constant, and under the upward reading `es_g` is 23 of 25 and the P ≥ 0.8 set is
14 of 15.) It is still out, for three reasons.

The bound P ≥ 0.8 is chosen *after* seeing where the formula fails, which is the sampling
bias this exception exists to forbid. It excludes ten of Table 1's twenty-five pitches,
and with them **thirteen of the forty coarse sizes `iso_metric_thread` ships** — M1
through M4.5, including M3 and M4. M3 is one of the two sizes all three fleet-01 arm-C
replicates hand-wrote 6g/6H data for before they could state a limit (#194), so the narrow
table would omit half the demand that motivated the exception — and it would do so at
pitches the formula gets *right*. Of the ten it discards, nine agree, M3's own 0.5
among them; only P = 0.75 does not. The bound sheds nine correct pitches to hide one
wrong cell. And §10.1 of that standard says its tables govern at every pitch,
so a column that happens to agree is agreeing by coincidence rather than by construction —
which is the entire distinction the exception draws. The exception is unchanged and may
still reach a standard whose formulae are normative; it does not reach this one (#260).

### 10.2 `build_input` — forcing byte identity for a named distribution

A second, separate declaration on the same axis, and it declares **provenance rather than a
claim**: it says how hard to look at a build input, never what the part must be. So it has
no measurand, no phase, no check id and no row in §4's vocabulary, and it can neither pass
nor fail.

```python
p.build_input("cadquery-ocp")
```

`source_closure.imports` decides identity in two automatic tiers (`SPEC-report.md` §8.3).
`metadata` trusts the installer — version plus a digest over the RECORD's own hashes — and
its bound is §8.3 rule 5: an edit to a file the RECORD *does* declare leaves the digest
unmoved, because ownership is decided by path and hashing every loaded file is the cost that
tier exists to avoid. This is the author's opt-out from that bound for the one distribution
they know is the subject: every file the RECORD declares is byte-hashed instead.

**Opt-in, because the cost is real and lopsided.** Measured: `build123d` 1.4 ms over 41
declared files, `cadquery-ocp` 228.5 ms over 396. Right for a contract whose geometry is
OCCT-version-sensitive, wrong for one that is not, and only the author can tell which.

**Additive, never required** — §10's rule 1, for §10's reason. Tiers 1 and 2 keep running
unconditionally, so a contract declaring nothing still gets a complete, honest inventory
with byte hashes wherever metadata would be vacuous. **Absence of a declaration MUST NOT
produce a stronger claim, only a weaker and clearly-labelled one.** A design that *leaned*
on the declaration would make the common case — an author who declares nothing — look
covered and not be, which is the §8.3 rule 5 mistake made a second time in a new place.

**Explicitly refused: coverage that depends on a size threshold.** No "hash it if it is
under 50 MB". That would make what a report claims depend on which machine wrote it, which
is the property the content-hash-not-path design exists to prevent. Coverage is a stated
property of the contract, never an emergent property of the filesystem.

Two rules on the name:

1. **It is a distribution, not a module.** That is what `imports` keys a RECORD-owned entry
   by. A module name is refused at the call site with the distribution that ships it —
   `build_input("OCP")` says *OCP is the module; the distribution that ships it is
   `cadquery-ocp`* — because a value one keystroke from correct must not be accepted and
   silently ignored. Spelling is normalised per PEP 503, so `cadquery_ocp` resolves.
2. **A declaration naming something that never loaded is a run-level `error`.** It cannot be
   judged when the contract is declared, because nothing is imported yet; it is adjudicated
   after the build. The contract described a build it did not get, which is a
   contract-versus-reality mismatch rather than a geometry claim — so `verdict: error`, not
   a failing check. Silence is clearly wrong here: the declaration's entire purpose is to
   strengthen coverage, so a typo in it would silently *weaken* coverage while looking like
   it had been asked for.

A declaration that changed nothing is still recorded (`declared: true` on the entry), so a
reader can tell coverage that was **asked for** from coverage that happened to be free.

---

## 11. Contract fragments — an interface standard as an import

A fragment is a plain function that declares a mechanical interface's checks onto a part:

```python
from partspec.refs import iso15, iso_metric_thread, nema17

nema17.mount(p)                        # nema17:pilot + nema17:bolt_circle, pattern cited
iso15.seat(p, 608)                     # iso15:608:seat, nominal cited
iso_metric_thread.tapped_hole(p, 3)    # iso_metric_thread:M3:tapped, minor diameter cited
```

No new machinery — a fragment is ordinary contract authoring, factored. Three rules:

1. **A fragment declares checks and nothing else.** No geometry, no measuring the part,
   and no checks invented from measurements — the §6 auto-generation ban applies to
   fragments exactly as to tools. A fragment's defaults are declarations the caller
   adopts, the same way a factory's defaults are the master design (§2).
2. **Ids are namespaced** (`nema17:pilot`, `iso15:608:seat`), so two *different* fragments
   never collide, a collision with the author's own checks is loud (§4's duplicate-id
   error), and `diff` joins stably across runs. Calling the *same* fragment twice needs a
   distinct `instance=` per call — and because `hole_diameter` counts the whole part (no
   selectors, §8), per-part count arguments (`pilot_count`, `count`) state the total. A
   fragment MUST declare atomically: an invalid argument raises before any check lands,
   so a corrected retry never collides with a failed attempt's leavings.
3. **The standard's numbers carry the citation; the designer's stay theirs.** A pattern
   dimension is `Referenced`; a clearance diameter is an argument the caller owns. Where
   a table *derives* a value (NEMA 17's hole square from the standard's stated pitch
   circle), the derivation is stated in the citation's `note` — a table may derive and say
   so, while a call site deriving silently owns the result (§10 rule 2). Get the direction
   right: the first cut of the NEMA table derived the circle from the catalogue square and
   attributed the square to the standard, 25.6 µm off the AJ dimension the document states
   directly — the review caught it against the standard's own text, and the table now
   converts what the document says, inch figures in every note.

[survey-direction]: https://github.com/heibench/partspec/blob/main/notes/survey/DIRECTION.md
