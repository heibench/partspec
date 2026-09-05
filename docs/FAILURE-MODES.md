# Observed CAD-as-code failure modes

**Applies to:** v0.7.8 — the release this text describes. The `Status:` line records when
this document was last revised in substance; it is provenance, not currency (#300).

**Status:** v1 · 2026-08-08 · closes #24
**Source:** the 2026-08-03–06 dogfood runs (partspec 0.1.0, 15 targets, 18-library
OpenSCAD corpus plus community CadQuery/build123d models), distilled from the scratch
workspace's `results.md`, preserved verbatim as [`notes/dogfood-results.md`][dogfood-results]. Finding
numbers (F5, F10, …) refer to that record.
**Scope:** failure modes of *CAD-as-code itself* — the ways a part goes wrong while
every tool in the chain reports success. partspec's own development bugs are deliberately
excluded (the tracker and [`notes/`][notes] carry those); this file is what an authoring agent
needs to have seen *before* writing a part.

**Workspace ruling (#24's last acceptance box):** `docs/PLAN.md` records the dogfood
workspace's untracked status as a deliberate call, and that call **stands** — it remains
a scratch corpus of third-party code. What changes is that everything load-bearing now
lives here: this catalogue is the shipped artifact, and the raw record is frozen at
[`notes/dogfood-results.md`][dogfood-results].
Entries below are marked **[repo]** when reproducible from this repository alone and
**[corpus]** when they need the external library corpus.

Every entry answers four questions: the symptom, the root cause, how it was caught, and
— the one that matters most — **what it looks like when it's green**: the exact face a
quietly-wrong part shows you.

---

## 1. A removed language construct silently deletes geometry **[corpus]**

- **Symptom.** A gear library renders a part **35% smaller in every planar dimension**
  with its teeth missing — 48.8 mm outer extent where theory says 72.2 mm, essentially a
  gear blank at pitch diameter.
- **Root cause.** The source uses OpenSCAD's `assign()`, deprecated and later *removed*.
  Modern OpenSCAD ignores an unknown module — and ignoring a module means **its children
  never render**. The children were the `polyhedron()` calls cutting the teeth. The
  library's source is unchanged and correct; the language moved underneath it.
- **Detected by.** A contract asserting the involute-gear envelope *derived from theory*
  (`teeth × outside_circular_pitch / 180`, plus addenda), run under two pinned binaries:
  PASS on 2021.01 (honours `assign`), FAIL on 2026.08.01 (ignores it). One variable. (F13)
- **When it's green.** Both versions **exit 0 and write clean, watertight, single-solid
  STLs**. The only signal is a `WARNING: Ignoring unknown module 'assign'` buried in
  stderr. No `assert()` in the library could catch it — the 18-library corpus
  contains zero asserts; the one library with any (the bayonet, 12 of them, from a
  separate collection) was the outlier, and even those only guard inputs.
- **Guards.** partspec reads the *mechanism* directly since #286: `check` and `measure`
  scan the engine's stderr for unresolved names on the path that **succeeded**, not only
  where the build had already failed, and both refuse — `verdict: "error"`, exit `4`,
  every geometry check `skipped` (`SPEC-report.md` §6.1). Before that the warning was
  read only after a failed build, so this shape was invisible: the gear above was caught
  by the envelope check, which needed a contract carrying theory-derived bounds and a
  second engine to compare against. The stderr line is now evidence on its own, and
  needs neither. **`render` refuses on the same evidence** (#307): the guard is asked
  before the first view is drawn, so a hollowed part yields `origin: null` and exit `4`
  rather than four pictures of a part the source does not describe. Alongside that:
  `PARTSPEC_OPENSCAD` pins the binary; the version is recorded in every report because it
  changes the artifact; bounds derived from theory, not measured off the part (see
  `docs/SPEC-contract.md` §10 on reference-derived limits).
- **A second shape of the same class, which the guard above does not reach** **[repo]**
  — unlike the gear, this one needs nothing but the two pinned binaries. A two-argument
  range that runs backwards, `for (i = [1 : n])` at `n = 0`, is the shape a loop takes
  when a count falls to zero. 2021.01 normalises it and iterates **ascending**;
  2026.08.01 iterates nothing. Measured on a 40 × 8 × 6 rail with a 6 × 8 × 4 stud at an
  8 mm pitch: 2021.01 exports 36 triangles and a bbox z of 9.99 — two studs the source
  did not ask for — against 2026.08.01's bare-rail 12 and bbox z of 6, both at exit 0,
  both watertight and single-solid. What differs from `assign()` is that **no stderr
  line reaches the guard**: 2021.01's `DEPRECATED: Using ranges of the form
  [begin:end] …` is not one of the lines read off a render that succeeded, and
  `build_stderr` is `null` in the report either way, measured under both engines on this
  part; 2026.08.01 warns only when the range is a *literal*, and a count that falls to
  zero always arrives through a variable. So the older half of this entry's Guards is
  what catches it, on its own: pin the binary, and write the bound two-sided and from
  theory. Measured, `envelope min=(40, 8, 5.9) max=(40, 8, 6.1)` on the `n = 0` part —
  `FAIL envelope — z=9.98999977`, exit 1 on 2021.01 against `PASS: 4 pass`, exit 0 on
  2026.08.01, with `watertight` and `solid_count` passing on both, so the envelope is
  the only check that moves. The authoring remedy is
  `skills/openscad-authoring/SKILL.md` rule 7 (#356).

## 2. The default backend emits a broken mesh and certifies it valid **[corpus]**

- **Symptom.** A 2,212-star Gridfinity library, rendered with current OpenSCAD's
  **default** Manifold backend, produces a mesh with **4 non-manifold edges** (each
  shared by four faces — two shells touching along the z = 19.8 plane; genus 8 where the
  clean render is genus 0).
- **Root cause.** Backend-specific tessellation of coincident geometry. The same source
  under CGAL renders clean — the defect is the *render*, not the design.
- **Detected by.** A differential run varying only the backend; the face-per-edge count
  is arithmetic, not a heuristic, and `manifold3d` independently agrees. (F10)
- **When it's green.** OpenSCAD prints `Status: NoError`, `"simple": true`, **manifold**
  — and exits 0. Every one of those statements is false. This confirmed D13 —
  partspec never parses `--summary` — harder than the case D13 was built on: not an
  omitted validity key but a false one, asserted on a real part.
- **Guards.** `openscad(..., backend="CGAL")` selects the backend and
  `engine.render_backend` records it; `watertight` names boundary vs non-manifold edges;
  D17 preconditions make `volume`/`genus` refuse on the broken mesh instead of
  answering.

## 3. A hole that reaches the boundary stops being a hole **[corpus; essence [repo]]**

- **Symptom.** Lengthening a NEMA 17 plate's belt-tension slots from 6 mm to 8 mm —
  exactly the parameter someone bumps between revisions — makes the plate **unable to
  hold a motor**: the slots breach the plate edge and become open notches.
- **Root cause.** A hole is a topological property. When it opens onto the boundary the
  genus falls (5 → 1); nothing about "a slot got longer" warns that a threshold was
  crossed. Pushed further, one parameter swept across six values yields four regimes, the first
  three all exiting 0:
  correct (genus 5), unmountable (genus 1), pinched to non-manifold (refused, named),
  and shattered into six solids (`solid_count` answers 6 while `genus` declines,
  per-body).
- **Detected by.** `genus 5` — the only check of five that moved. (F15)
- **When it's green.** Renders, exits 0, watertight, one solid, exactly 42 × 42 × 4 —
  four of five checks identical to the good part. **Visual review is worst here**:
  open-ended slots look like a deliberate design choice.
- **Guards.** Assert topology (`genus`, `solid_count`), not just size; the mesh tier
  answers both with no feature recognition. The essence is reproduced in-repo:
  `tests/test_docs.py` sweeps a slot across a plate edge and watches `genus` drop while
  envelope, watertightness and solid count hold still.

## 4. A clearance allowance baked into a constant named for a nominal dimension **[repo]**

- **Symptom.** `bearings.scad` declares `od_608 = 22.5` — but a 608 bearing is Ø22.0
  (ISO 15), held to 0/−0.008 by ISO 492. Any model using `bearing(608)` *as the bearing*
  gets a phantom part 0.5 mm oversize; the bore carries its own undeclared +0.4.
- **Root cause.** A print-fit allowance for a *pocket* was written into the constant
  named for the *part*, with no comment. The width gives it away: exactly nominal — the
  allowance was applied where somebody was thinking about fit and omitted where they
  were not. The same shape recurs one library over: `NEMA17.scad`'s header says
  `42.67mm square plate` and ten lines later declares `l_NEMA17 = 42`. **Two authors,
  same slip — a property of the corpus, not a person.**
- **Detected by.** A contract carrying ISO 15's numbers with a generous ±0.1 band:
  `envelope` and `volume` both FAIL, bracketing the divergence between them. (F16; the
  in-repo reproduction is the Ø22.5-seat test in `tests/test_provenance.py`, and
  `partspec.refs.iso15` exists so the standard's numbers arrive cited instead of
  retyped.)
- **When it's green.** Nothing in the corpus checks anything, so the 22.5 mm "608" passes
  every render, forever, and every model built on it inherits the half-millimetre.
- **Guards.** Take limits from `partspec.refs` or the drawing — never from the model's
  own constants (the circular-contract disclosure, SPEC-contract §6/§10).

## 5. A parameter that binds nothing is accepted and dropped **[repo]**

- **Symptom.** Four contracts passed `style_lip=0` to a Gridfinity entry point that does
  not declare that variable (it lives in a sibling file). OpenSCAD silently discards a
  `-D` naming no top-level variable — so every run built a bin **with** the lip, while
  the report listed `style_lip: 0` under `params`, positively asserting a value the
  geometry never saw. Two of the four runs were green.
- **Root cause.** `-D` is an unchecked write into the interpreter's namespace; a typo'd
  or misrouted name reaches nothing and nobody says so.
- **Detected by.** partspec's unbound-parameter guard (#9), on its first run against the
  corpus — the first finding produced by a guard rather than a human. (F18)
- **When it's green.** Exit 0, clean mesh, and an artifact describing a part that was
  not built — the same shape as entries 1 and 2: **the tool chain is unanimous and
  wrong**.
- **Guards.** A `-D` matching no top-level variable fails the build, naming the variable
  and listing the ones that exist. Where an include did not open, the refusal still
  fires — withholding it traded this false error for a *silent false pass* — but it says
  the list is incomplete and names the file it could not read, and the fault is
  `environment` rather than the contract's, because an include that will not open says
  nothing about the part (#287).

## 6. Shared claims that assert the first implementation you looked at **[corpus]**

- **Symptom.** A claims file shared by two Gridfinity implementations asserted
  `genus(0)` — "an open tray has no through-holes". True of the CadQuery
  implementation; false of the OpenSCAD one, which enables refined base holes by
  default (genus 8 on a 2×1 bin).
- **Root cause.** The claim encoded an *implementation choice* the Gridfinity standard
  does not fix. Written while looking at one implementation, it silently became a claim
  about all of them.
- **Detected by.** The differential run: one contract, two engines, a FAIL that was the
  contract's fault. (F12)
- **When it's green.** With only one implementation in the loop, the over-tight claim
  passes indefinitely — and rejects every conforming alternative the day one appears.
- **Guards.** In shared claims, assert **only what the specification fixes**. The
  standard's numbers (42n − 0.5 pitch) agreed across engines to the micrometre;
  everything else is per-implementation.

## 7. The engine ecosystem breaks at install time, silently **[repo]**

- **Symptom.** After adding OCCT extras, `import cadquery` dies:
  `ImportError: cannot import name 'IVtkOCC_Shape'`. Later, *uninstalling* the culprit
  deleted co-owned files and broke build123d too.
- **Root cause.** `cadquery-ocp` and `cadquery-ocp-novtk` both install the same
  top-level `OCP/` package (326 vs 322 files); neither pip nor uv detects the conflict;
  whichever lands last wins. A fresh-venv spike that worked was resolution-order luck.
- **Detected by.** The first `import cadquery` after `uv sync --all-extras` — days can
  pass between the install exiting 0 and the import that reveals it, and the traceback
  blames the library, not the resolver. (F5. The sibling hazard is #109: the override below
  is *configuration*, and `uv pip` applies it to anything installed from this directory — so
  it silently reshapes installs it was never meant to touch, including published wheels.)
- **When it's green.** The install exits 0. The breakage surfaces only at first import,
  possibly days later, and looks like the *library's* bug.
- **Guards.** `[tool.uv] override-dependencies` drops novtk from resolution;
  `just ocp-guard` asserts exactly one provider; `_engine_import_error` names the
  two-provider state instead of relaying the raw ImportError.

## 8. Community CAD code is scripts and pinned libraries, not callables **[corpus]**

- **Symptom.** A 96-star community build123d library fails to import on build123d
  0.11.1 (`ShapePredicate` no longer exists); the flagship library's 66 examples are
  module-level scripts ending in `show(...)`, not parameterised functions. Most OpenSCAD
  is the same.
- **Root cause.** Community models are written against the engine version of their
  moment and for interactive use. Nothing about the ecosystem pushes toward
  `factory(**params) -> shape`.
- **Detected by.** Attempting to drive the corpus through `method(**params)`. (F8)
- **When it's green.** It isn't subtle — but the *cost* is: every real contract on
  community code ships a three-line adapter, and an agent that doesn't know this
  pattern will rewrite the model instead.
- **Guards.** partspec deliberately does not guess calling conventions; the adapter
  friction is recorded in `docs/PLAN.md`'s P4 revision note (citing F8): a real
  contract on community code usually ships a small explicit adapter.

## 9. A true diagnostic about a source whose mesh is exactly right **[repo]**

*Not from the dogfood corpus: found in review of PRs #329 and #357, and filed as #336 and
#333. It is here because it is a property of the language an authoring agent has to have
seen, and because it is the one entry whose green face is a **false red**.*

Two cases, one shape. In both, OpenSCAD prints a warning that is **true about the source**
and says nothing at all about whether the exported mesh is wrong — and partspec refuses on
it, because stderr does not carry the difference. Refusing is the deliberate choice; the
cost is written down here rather than paid quietly.

### 9a. A fault inside `%` background geometry

- **Symptom.** `partspec check` reports `ERROR: 3 skipped` at exit `4` over a part whose
  exported STL is **byte-identical** to the correct one. The quoted evidence names a
  module and a value, and the mesh it is supposedly about does not contain that module's
  output at all.
- **Root cause.** `%` marks a subtree as *background*: OpenSCAD **evaluates** it, shows it
  in the preview, and excludes it from the render and the export. Diagnostics from inside
  it still reach stderr, and stderr does not carry the modifier — the line names the file
  and the line number and nothing else — so a warning about scaffolding is
  indistinguishable, at the point partspec reads it, from a warning about the part.
  Measured on both pinned engines, `cube([40,30,6]);` followed by
  `%translate([undef,0,0]) cube(2);` prints
  `WARNING: Unable to convert translate([undef, 0, 0]) parameter to a vec3 or vec2 of
  numbers`, exports 684 bytes, and `cmp -s` says those bytes are the same 684 the source
  without the `%` line produces.
  The three modifiers differ, and only one of them has this property: `*` (disable) is
  never evaluated, so it emits nothing and costs nothing; `#` (highlight) **is** exported,
  so its warnings are about the mesh; `%` alone is evaluated and not exported.
  A fourth, `!` (root), leaves a residual false red in the safe direction: it exports
  *only* its own subtree, and the engine writes only that subtree to the `.csg` — measured
  on both engines, `!cube(10);` followed by `import("outside.stl")` produces a one-line
  export naming no file at all. So a reference discarded by `!` appears in neither the kept
  nor the dropped set, is unaccounted for, and is refused. That is the fail-closed rule
  behaving correctly on absent evidence rather than a second instance of this entry's
  class, and it is left alone: `!` is a debugging modifier that is not meant to survive
  into a checked-in source, and refusing is the direction to be wrong in.
  **stderr is not the only channel that loses the modifier, and the other one is now
  narrowed.** The engine's dependency file records what it *resolved*, not what it
  exported, for the same reason stderr records the line but not the modifier: `%` is
  evaluated, so an `import("mate.stl")` inside one is resolved, recorded in the depfile,
  and reported under `source_closure.engine_inputs.missing` when the file is not there —
  while the export is byte-identical either way, measured on both pinned engines. `*`
  records nothing on this channel either, because it is never evaluated. So the guard that
  reads `missing` (#309) would have produced a second false red of exactly this class.
  It does not, because on this channel the cheap discriminator that stderr lacks does
  exist: the `.csg` export **keeps the modifier next to the filename** —
  `%import(file = "ref.stl", …)` on both engines — and `csg.py`'s reader already drops
  `%` and `*` subtrees, so the refusal is narrowed to files the export actually depended
  on with no line-number correlation and no second parser (#354). `#` stays a catch there
  too, on the asymmetry above.
- **Detected by.** The engine's own stderr on the path that succeeded — the same guard as
  entries 1 and 5 (`SPEC-report.md` §6.1). Nothing here needed a contract carrying theory.
- **When it's green.** It isn't, and that is the entry: this is the one shape in this
  catalogue where partspec refuses **more** than the geometry requires. **The refusal
  stands, deliberately** (#336). An `undef` inside a `%` subtree is a bug in the source
  whatever it costs today; the modifier is one character, so the scaffolding routinely
  becomes the part; and the alternative — correlating stderr's line numbers against the
  `%` nodes in a `.csg` export — buys silence on a real defect at the price of a second
  parser between the engine and the verdict. (That reasoning is about **stderr**, whose
  evidence is a line number; it does not carry to the depfile channel, where the `.csg`
  names the file itself and no correlation is needed. Hence the narrowing above and the
  refusal here, in one catalogue entry.) What was wrong was that the trade was
  **silent**: an agent hitting exit 4 on a byte-perfect mesh had no way to reach this
  conclusion from the report.
- **Guards.** `AGENT-CONTRACT.md` §2.3 now says it, at the bullet that routes a
  conversion error: if the quoted line's file and line land on a `%` subtree, the mesh is
  probably right and the source is still wrong. The remedy is unchanged — fix the `undef`,
  or delete the scaffolding. When debug geometry must stay and must cost nothing, `*` is
  the modifier that is free.

### 9b. A `rotate()` parameter the engine ignored

- **Symptom.** The same `ERROR: 3 skipped` at exit `4`, over a part that is rotated
  exactly as the source asked. Before #377 the report said the engine "could not convert
  a value and built a default in place of it", and for this shape **no default went in**
  — the defect #360 records. That marker now carries a cause of its own, "the engine
  could not use a value as written", which is all the stderr line supports;
  `Unable to convert` keeps the default-substitution wording unchanged to the byte,
  because for that marker a default is certain.
- **Root cause.** `Problem converting rotate(...)` means the engine could not use the
  `rotate` parameters *as written*. That is four different situations, and only some of
  them damage the mesh. Measured on both pinned engines, every byte comparison `cmp -s`
  against the correct source named:

  | source | what the mesh is | vs. correct |
  |---|---|---|
  | `rotate(o) cube(5)`, `o = undef` | identity — the rotation is **lost** | wrong part |
  | `rotate([o,0,0]) cube(5)` | identity — the rotation is **lost** | wrong part |
  | `rotate() cube([10,5,2])` | identity, which is what a no-op rotate is for | **byte-identical** to `cube([10,5,2])` |
  | `rotate([90,0,0,0]) cube([10,5,2])` | rotated 90° about X, as asked | **byte-identical** to `rotate([90,0,0]) …` |
  | `rotate(a=45, v="z") cube(5)` | rotated 45° about Z — the default axis, which is the one the author named | **byte-identical** to `rotate(a=45, v=[0,0,1]) …` |

  The fourth row is the one to understand: OpenSCAD 2021.01's own `transform.cc` reads
  `default: ok &= false; /* fallthrough */ case 3:`, so an over-long `a` vector still has
  its first three components read and applied. Only the "could I use this?" flag goes
  false. **Nothing is substituted at all**, and the warning is purely "your vector had a
  fourth element".
- **Detected by.** The engine's own stderr on the path that succeeded (#333), the same
  guard as 9a.
- **When it's green.** Three of the five rows above are byte-perfect and refused. `main`
  passes all five at exit 0; this guard errors **all five** at exit 4 (a sixth shape,
  silent on both engines, is below).
- **Guards.** The refusal stands. An over-long rotate vector, a string where an axis
  belongs, and an angle that never arrived are all bugs in the source; the marker cannot
  tell which of the four situations it is in, and the two that *do* damage the mesh are
  exactly the ones #333 exists to catch. `AGENT-CONTRACT.md` §2.3 tells the reader what
  the line does not say, so a byte-perfect mesh at exit 4 is diagnosable rather than
  baffling.
- **Not narrated at all**, and therefore not caught: `rotate(a=90, v=undef)` is silent on
  both engines and exits `0`. `undef` is not "defined", so the engine reads it as "no axis
  given" and applies its default — the part is rotated 90° about Z, byte-identical to
  `rotate(90)`. **It is not unrotated.** Same class as entry 5's silent shapes, and the
  general case is entry 10 below.

## 10. A dimension defaulted from `undef`, narrated by nothing at all **[repo]**

- **Symptom.** A 40 × 30 plate comes out **100 mm tall**. Its thickness arrived `undef`,
  and `linear_extrude` substituted its own default. Seven spellings do the same thing,
  each measured under both pinned engines with the source prefixed `o = undef;`:
  `cube(o)` and `cube(size=o)` build a 1 mm cube, `linear_extrude(o)` and
  `linear_extrude(height=o)` extrude to 100, `cylinder(h=o, d=10)` takes h = 1,
  `sphere(o)` takes r = 1. `resize(o) cube(5)` is the instructive exception: it is a
  **no-op**, 12 facets and bbox 5 x 5 x 5 unchanged on both engines, because `newsize`
  defaults to `[0, 0, 0]` and a 0 there means *keep this axis* — the one row of the seven
  whose resulting dimension IS a number the author wrote. Only
  `circle(r=o)` escapes, and only because a 2D result cannot be exported to STL at all
  (exit 1, no file, both engines). #338's variant reaches the same place through a range
  that would not convert — `n = undef; r = [0:n]; h = r[2];` — and its sibling loses a
  loop's geometry entirely: `module rail(n = undef) { … for (i = [1:n]) … }` exports the
  bare rail, 12 triangles against 76 at `n = 4`.
- **Root cause.** `undef` is the language's own "not supplied", and every builtin has a
  fallback for a parameter it cannot read. Nothing in the chain asks whether the author
  meant the fallback.
- **Detected by.** #308's reproduction, deliberately left uncovered by the guard PR #306
  narrowed; #332 and #338 measured the surface. **The engines agree**, so unlike entries
  1 and 9 a second pinned binary catches nothing here.
- **When it's green.** Exit 0, empty stderr, a clean watertight single solid — and the
  report's `build_stderr` is `null`, so there is not even a line for a reader to be
  suspicious of. Where an arithmetic step is involved (`o + 1`) one
  `WARNING: undefined operation (undefined + number)` appears, twice on 2021.01 and once
  on 2026.08.01; it is not usable as a guard, because the same line prints beside
  completely correct parts (`echo("holes: " + holes)` — measured, exit 0, 272 facets,
  bore present, both engines), which is why PR #306 tried it and reverted.
- **Guards.** **No refusal, on purpose, and the reason is provable rather than
  provisional.** stderr cannot decide it — the silent rows emit nothing and the noisy one
  fires on correct code. The `.csg` cannot decide it either: `o = undef; cube(o);`
  exports **byte-identical** to `cube(1);` on both engines, as do the `linear_extrude`,
  `cylinder` and `sphere` rows against hand-written correct counterparts, so any tier-2
  rule refusing the fault refuses ordinary correct code byte for byte. What ships instead
  is `partspec lint`'s **`scad-untested-undef`** (tier 1, engine-free, advisory —
  `docs/LINT.md`), which names the binding, and an **ordinary dimensional claim**, which
  refuses the part. Measured on both engines against `watertight()` + `solid_count(1)`
  + an envelope: `envelope(max=(40,30,6))` turns the `linear_extrude` and range shapes
  from exit 0 into **FAIL, exit 1**; the vanished loop still passes it, because the part
  got *smaller*, and only a two-sided `envelope(min=(40,8,10), max=(40,8,10))` fails it
  — exit 1 on both engines, while the correct `n = 4` part passes. The authoring remedy
  is `skills/openscad-authoring/SKILL.md` rule 8 (#308, #332, #338).

---

## The shared moral

Six of these ten (1, 2, 3, 5, 10, and the header half of 4) have the same signature:
**exit 0, a clean watertight mesh, and an artifact that is not the part you asked for.**
Nothing in the render pipeline is positioned to notice, because every stage's contract
with the next is "produce *a* mesh", not "produce *the* mesh". The checks that caught
them — envelope from theory, topology, external standards, unbound-parameter refusal —
are all statements about **intent the model does not contain**, which is the reason this
tool exists and the reason a contract derived from the model's own numbers proves
nothing (entry 4).

Entry 9 is the inverse, and it is here so the ledger has both columns: a guard sharp
enough to catch entries 1–8 refuses a byte-perfect mesh when the fault it can see is
in geometry that was never exported (9a), or in a parameter the engine ignored on its way
to building the part correctly (9b). That cost is written down rather than paid quietly —
the alternative to naming it is a reader who concludes the tool is unreliable, which is
the more expensive mistake.

Entry 10 is the same boundary approached from the other side, and it is the reason the
ledger needs both: a fault the guard cannot see **at all**, where every channel that
could carry a refusal was measured and each one refuses correct parts as readily as
broken ones. What it gets instead is an advisory lint finding and a contract claim — a
narration rather than a verdict, which is the honest answer when a verdict cannot be
made safely, and a weaker one that should not be mistaken for the guard the other
entries have.

*Cross-references from the authoring skills (#22, #23) land with those skills; each
entry above carries a stable heading for them to anchor to.*

[dogfood-results]: https://github.com/heibench/partspec/blob/main/notes/dogfood-results.md
[notes]: https://github.com/heibench/partspec/tree/main/notes
