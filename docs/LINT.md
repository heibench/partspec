# partspec lint — the rules

**Applies to:** v0.8.0 — the release this text describes. The `Status:` line records when
this document was last revised in substance; it is provenance, not currency (#300).

**Status:** v2 · 2026-08-22 · closes #26 (tier 1) and #118 (tier 2) · `csg-two-part-intersection` added (#270); refusals reach the console (#288); `scad-untested-undef` added (#332, #338)
**Scope:** `partspec lint <source>…` over `.scad` and `.py` model sources. Findings are
**advisory and never a verdict on the part — it is about the source** (#26, verbatim):
exit 0 says the lint ran, the findings are data in the JSON payload, and 64 is reserved
for inputs that cannot be linted at all. The payload (schema 2) is per-file
blocks — `{file, digest, findings[, unsupported]}` — so a clean file is a visible entry with the
sha256 of the bytes that were linted, not an absence; duplicate arguments are deduped
(#120). **Tier 1** runs without an engine installed; **tier 2** (the three `csg-*` rules)
reads OpenSCAD's constant-folded `.csg` export and refuses by name when the binary is
absent.

`counts` carries `{files, findings, unsupported}`. **`unsupported` is the one that says
whether the run was whole**: a `findings: 0` with `unsupported: 3` is not a clean file, it
is a file three rules never looked at. Counted per (file, rule), the same unit
`unsupported[]` holds, so the tally and the blocks cannot disagree.

Each rule states its exact predicate — a lint whose rules are vibes teaches nothing —
plus the rationale and a real example. The rule registry in `src/partspec/lint.py` and
this document are held together by test (`tests/test_lint.py`).

Lint is for **model sources**. Pointing it at a contract flags check *limits* as if
they were model constants — advice aimed at the wrong file. An agent loop should read
each file block's `findings[]` **and its `unsupported[]`** before the first render, and
treat each finding as an optional aimed edit, never
as a failure to clear (exit 0 with findings is not AGENT-CONTRACT's exit-0 row: that
map governs `check`).

Reading `findings[]` alone is the blind loop this document used to prescribe (#288): the
rules that did not run are exactly the ones whose silence would otherwise read as a pass,
and with no engine installed that is every tier-2 rule on every file. Both surfaces now
carry them — `unsupported[]` per file in the payload, and one line per distinct cause on
stderr naming the rules and the files, the latter bounded at two names plus a count the
way `diff` bounds its own name lists (`SPEC-diff.md` §1). A bare count would say something
was skipped and leave no way to find out which.

## `scad-unused-top-level`

- **Predicate:** a top-level variable **of the entry file itself** (deliberately
  narrower than the `-D` guard's include-closure walk: lint speaks about the file it
  was pointed at) whose name appears nowhere in the noise-stripped source outside its
  own assignment lines. `$`-variables are exempt — the engine reads them.
- **Rationale:** a declared knob the geometry ignores is either dead weight or a
  misrouted parameter — the same family as FAILURE-MODES entry 5, one step earlier.
- **Real example:** `examples/spacer/spacer.scad:10` — `wall = 2;` is never read by
  the geometry. It exists for the *contract's* `requires` arithmetic, which is the
  documented legitimate case: the finding's message says so, and the advisory verdict
  means it costs nothing to accept knowingly.

## `scad-untested-undef`

- **Predicate:** a name **bound to a literal `undef`** — a top-level `o = undef;` of the
  entry file, or a `module`/`function` parameter defaulted `undef` — whose name **appears
  in its scope outside its own assignment statements**, with **no test of that name**
  anywhere in that scope. "Appears", as in `scad-unused-top-level`: this is a text scan,
  not a dataflow analysis, and the gap between appearing and being read is where the
  accepted noise below lives. A test is
  any `is_*(name)` predicate (`is_undef`, and also `is_num`, `is_list`, … — `is_num(h)`
  before using `h` as a dimension is the same guard wearing a narrower hat) or a `==`/`!=`
  comparison against `undef` in either order. Scope is the whole file for a top-level
  binding and the declaration's own body for a parameter, so a same-named variable
  elsewhere is not read as a use. A binding that is never read produces **no** finding
  here: that is `scad-unused-top-level`'s, and one fault should not report twice.
- **Statements, not lines.** `o = undef; h = o + 1; linear_extrude(h) square([40,30]);`
  is one legal line, and until the #372 review the scan was line-based and saw no binding
  in it at all — while `scad-unused-top-level` reported a *false* "declared but never
  read" on the same string, because dropping the assignment's line dropped the read with
  it. Both rules now ask the question over the assignment **statement**, which is what
  `scad-magic-number` already learned in the v0.7.0 pre-tag audit. The corpus answer is
  unchanged: linting the same 126 tracked sources with the rule before and after this
  change produces byte-identical output. No count is given, deliberately — the first
  draft of this sentence quoted one, and it was stale before the branch merged.
- **A keyword argument is not a read.** `cylinder(h = 20)` names *cylinder's* parameter
  and cannot reference the caller's `h`, so a `name =` at bracket depth ≥ 1 is a keyword
  argument or a signature default, never a use — the same distinction the magic-number
  rule's depth counter already draws. Reading them as uses said `'d'` was read by
  `cylinder(d = 8)` on a correct 272-facet part (measured, both engines), and hid a
  genuinely dead `h = undef;` knob from `scad-unused-top-level` at the same time, so one
  rule stated a falsehood while no rule stated the fault. Both are fixed; the dead knob
  now reports as unused, which is what it is.
- **`$name` is not a read of `name`.** The read scan was a `\b` word boundary, which
  matches inside `$t` and `$fn`, so `t = 6;` beside `cube([10, 10, $t])` counted as
  read. `$t` is a special variable and cannot reference the caller's `t`; the scan now
  refuses a `$` before the name, and that source draws a `scad-unused-top-level` it did
  not draw in v0.7.7 (measured against both implementations over the same file). This
  is the third edge corrected here, and the second that ADDS a finding rather than
  removing one: the keyword-argument edge above does the same, and its own example
  says so — `h = undef;` beside `cylinder(h = 20, …)` drew nothing in v0.7.7 and now
  reports as unused. Only the line-to-statement edge is purely subtractive.
- **Rationale:** where an `undef` reaches a dimension, OpenSCAD substitutes its own
  default and **narrates nothing at all**. Measured on both pinned engines, each source
  prefixed `o = undef;` and rendered `--export-format binstl`: `cube(o)`,
  `cube(size=o)`, `linear_extrude(o)`, `linear_extrude(height=o)`, `cylinder(h=o, d=10)`,
  `sphere(o)` all exit **0** with a clean, watertight,
  single-solid mesh built to a number nobody wrote — `cube` to 1, `linear_extrude` to
  100, `cylinder` to h=1, `sphere` to r=1. (`resize(o) cube(5)` is silent too, but it is
  a **no-op** rather than a substitution — `newsize` defaults to `[0,0,0]` and a 0 means
  *keep this axis* — so the part stays 5 x 5 x 5 on both engines.) Stderr is empty for
  every one of them. Add an
  arithmetic step (`o + 1`) and the only line that appears is
  `WARNING: undefined operation (undefined + number)`, which fires beside completely
  correct parts and was tried as a guard and reverted for that reason (PR #306). So this
  rule is the **only** thing in partspec that says the shape out loud, and it says it
  advisorily. `undef` itself is not the fault — it is the language's own spelling of
  "not supplied", and BOSL2 and most libraries use it — the **untested-ness** is.
  (#308, #332, #338; FAILURE-MODES entry 10.)
- **Real example:** the openscad skill's rule-8-before block fires once, on its
  `module plate(t = undef)` parameter; its after-form lints clean. #308's own headline
  reproduction — `o = undef; h = o + 1; linear_extrude(h) square([40,30]);` — fires on
  line 1.
- **Tier 1, and it has to be.** The `.csg` export cannot decide this and the reason is
  not "not yet": a defaulted part's `.csg` is **byte-identical** to a correct part's.
  Measured on both engines, `cmp` on the exports of `o=undef; cube(o);` against
  `cube(1);`, `linear_extrude(o) …` against `linear_extrude(100) …`, `cylinder(h=o,…)`
  against `cylinder(h=1,…)`, and `sphere(o)` against `sphere(1)` — identical, all four,
  both engines. Any tier-2 rule that refused the left column would refuse the right one
  byte for byte. Keying on the token `undef` in the `.csg` is worse still: `polygon()`
  serialises `paths = undef` on every **correct** part, and where `undef` genuinely
  reaches `points` the two engines disagree (`points = undef` on 2021.01,
  `points = []` on 2026.08.01) — F13 inside the detector.
- **Known noise, owned — and it is the interesting half.** An `undef` default read only
  by an `echo` fires, and the part is correct:

  ```
  module plate(w, h, holes = undef) { echo("hole positions:", [0 : holes]); ... }
  ```

  That is exactly the source PR #306 and PR #329 round 2 each refused by mistake, at
  exit 4, with a diagnosis whose every clause was false. It is a **finding** here and
  costs nothing, because `lint` exits 0 whatever it finds — which is the whole reason
  this signal lives in the lint and not in the success-path guard. Two more accepted
  false positives: a truthiness guard (`n ? n : 1`) is not read as a test, deliberately,
  because it cannot tell `undef` from `0` and for a count or a dimension that is a second
  bug rather than a guard; and a test written through an alias (`c = chamfer;` then
  `is_undef(c)`) is not seen, because the rule tracks the bound name and does not follow
  assignments. In the other direction the rule is **not** a taint analysis: in
  `n = undef; r = [0:n]; h = r[2]; linear_extrude(h) square([40,30]);` it fires on `n`,
  which is the actionable binding, and says nothing about `h`.
- **Appearing is not being read, and three shapes exploit the gap.** A name that only
  ever appears in a *comment* cannot reach here (comments are stripped first), but a name
  **rebound in an inner scope that shadows the `undef`** still counts as appearing, and
  fires. So does a top-level `o = undef;` whose only mention is in a context the value
  never flows through. And in the other direction a **top-level** binding is silenced by
  an `is_undef(o)` anywhere in the file — including inside a module whose *own* parameter
  happens to be named `o`, which is a different variable. The scope protection stated
  above ("a same-named variable elsewhere is not read as a use") is a parameter's, not a
  top-level name's: narrowing that one needs the scope analysis a text tier does not
  have, and the failure direction is a missed finding rather than a false one.
- **The remedy the finding names is a contract claim, not only an edit.** Measured on
  both engines with `watertight()` + `solid_count(1)` + an envelope: `envelope(max=…)`
  turns #332 row 1 and #338(b) from exit 0 into **FAIL, exit 1**; but geometry that
  *vanished* (`module rail(n = undef)`, the loop gone) gets **smaller**, so a `max`-only
  envelope still passes it at exit 0 and only a two-sided `envelope(min=…, max=…)` fails
  it — exit 1 on both engines, while the same part at `n = 4` passes. That asymmetry is
  `skills/openscad-authoring/SKILL.md` rule 8.

## `scad-magic-number`

- **Predicate:** a numeric literal with `|value| > 2` on any line that is not an
  assignment or an `include`/`use`, in the noise-stripped source. (Any assignment, at
  any depth — not only top-level ones, which is what this said until v2; `x = 50;`
  inside a module body is exempt.) Two further positions are exempt because the
  literal is already named or is not a dimension at all: a **parameter default** in a
  `function`/`module` signature, scalar or vector (`module post(h = 40)`,
  `module plate(size = [60, 40, 4])`), and an **integer subscript index**
  (`type[3][0]`). The
  exemption is deliberate: 0/1/2 are structure, and the `-1`/`+2` boolean-overshoot
  idiom (skills/openscad-authoring rule 3) must not be flagged by the tool whose own
  skills teach it.
- **Rationale:** a magic number is unnameable — by `-D`, by `param`, by a report
  (skills/openscad-authoring rule 1).
- **Real example:** `cube([60, 40, 4]);` — the openscad skill's rule-1-before block,
  three findings; its after-form lints clean.
- **Wrapping does not change the answer.** The exemption belongs to the statement, not
  to one line of it, so `plate = [60, 40, 4];` and the same assignment spread over four
  lines both lint clean. Until v0.7.0 the rule matched a line-leading `name =`, so a
  wrapped lookup table — ordinary formatting — was exempt on its first line and flagged
  on every other, three findings on a constant that has a name. The rule's own rationale
  is that a magic number is *unnameable*; the code was the defect.
- **A signature default is named by its parameter.** `function radius(i, r_min = 100)`
  and the same signature wrapped over three lines both lint clean. Until #205 only the
  wrapped form did, and for a reason worth stating exactly, because the plausible one is
  wrong: the exemption was keyed on a **line-leading `name =`**, and a declaration line
  never is one — it leads with `module` or `function`. A wrapped signature's continuation
  line *is* (`    r_min = 100`), which is the whole of why the rare form escaped and the
  common one was flagged. Paren depth was not the cause: it fed only the multi-line
  assignment opener, never the exemption, so advancing it earlier changes nothing
  (measured, byte-identical output — #205's suggested remedy, recorded on the issue). **A vector default is the whole bracket group** —
  `module plate(size = [60, 40, 4])` is clean, because a size, a position and a range
  are all spelled `[...]` in OpenSCAD. The exemption covers the DEFAULTS, not the line:
  the walk stops at the parameter list's closing paren, so a one-line module's body
  literals still fire.
- **A subscript index is structure, not a dimension.** `type[3][0]` reads field 3 of a
  registry row: no unit, unreachable by `-D`, never a `param` or a report (#206). A `[`
  following an identifier or a `]` is a subscript; a `[` opening a vector literal
  (`size = [3, 4]`) is not, and the rule applies there as before. A keyword before the
  bracket is not an identifier — `each [100, 200]` splats a vector and its literals are
  flagged. Integers only, so `v[3.5]` — a bug either way — stays visible.
- **Known noise, owned:** canonical-orientation angles (`rotate([-90, 0, 0])`, `45`,
  `360` in ranges) fire. Accept them knowingly, or name them (`quarter_turn = 90;`) —
  the advisory verdict means acceptance costs nothing. Scientific literals match as
  whole numbers (`1e-3` is 0.001, exempt; `1e6` flags).

## `scad-module-size`

- **Predicate:** a `module` whose reported span exceeds 40 lines (brace-matched, over the
  noise-stripped source). The span is counted from the `module` line, so **a body of 40
  lines reports 41 and fires** — the effective body limit is 39.
- **Known asymmetry with `py-function-size`:** that rule counts from the *first statement
  of the body*, excluding the `def` (`lint.py`'s `fn.body[0].lineno`), so a 60-line body
  reports 60 and stays **silent**. The same-sized body therefore fires here and not there.
  The limits differing (40 vs 60) is deliberate; the counting frames differing is not.
  Aligning them changes behaviour, so it is tracked separately rather than fixed in a
  documentation pass. Both boundaries are pinned by tests.
- **Rationale:** the LoC symptom head-on — the observed failure is bloat, and a module
  past feature-size has stopped being a feature (skills/openscad-authoring rule 5).
- **Real example:** the corpus's gear library concentrates its geometry in one
  ~100-line body ([corpus]; the fixture in `tests/test_lint.py` reproduces the shape).

## `py-magic-number`

- **Predicate:** a numeric `Constant` with `|value| > 2` inside a `Call`'s arguments —
  positional and keyword alike — within any `def` body (stdlib `ast`. **`async def` is not
  seen by this rule OR by `py-function-size`**: both walk for `ast.FunctionDef`, and
  `ast.AsyncFunctionDef` is not a subclass, so an async factory is silently unlinted
  however long or magic it is — a rule staying quiet about code it cannot evaluate, which
  is the failure this tool's own refusal policy forbids. Tracked. A call inside a nested
  `def` reports twice; lambda bodies are pruned; defaults in the signature
  are exactly where numbers SHOULD live and are never flagged; module-level constants
  likewise; signs are kept, so `-90` reports as -90).
- **Rationale:** skills/build123d-authoring rule 1 — hoist it to a parameter with a
  default.
- **Real example:** `Box(40, 30, 4)` inside a factory — the bd skill's rule-3 block
  carries them deliberately (it is a *before* block).

## `py-function-size`

- **Predicate:** a function whose body spans more than 60 lines.
- **Rationale:** same as `scad-module-size`, Python spelling.
- **Real example:** community models are commonly one monolithic script promoted to a
  function ([corpus], F8).

## Tier 2 — the geometry rules, over the `.csg` tree (#118)

Shipped after the audit-mandated prior-art survey (recorded on #118): nothing exists
to depend on — sca2d is GPLv3 and geometry-blind, FreeCAD's importer is LGPL and
welded to its document model — so the reader is hand-rolled, stdlib-only
(`src/partspec/csg.py`), with FreeCAD's node inventory absorbed as the refusal
checklist. These rules read `openscad`'s constant-folded `.csg` export, so they
**require the engine** — and when it is missing, or a rule's evaluation must cross a
node outside the modelled set (`hull`, `minkowski`, extrudes, imports…), the file block
carries an `unsupported` entry naming the rule and the reason. (A node the rules never
needed to evaluate — a `hull` outside any `difference` — produces no entry: the rules
ran, and ran vacuously.) **A rule that could not run is an
entry, never an absence.**

Tier-2 findings carry **line 0**: the tree is constant-folded, so no source line
exists to name — the message describes the geometry instead.

### `csg-coincident-face`

- **Predicate:** a `difference()` cutter sharing a face plane with its minuend,
  exactly — planes are cube faces and cylinder caps, transformed through the
  accumulated `multmatrix` by the inverse-transpose, canonicalized (unit normal,
  orientation-normalized, rounded at 1e-9 for float representation of the folded
  literals), and compared for set intersection. Zero epsilon on the literals is the
  point: the folded tree has the author's exact numbers.
- **Rationale:** FAILURE-MODES entry 2; skills/openscad-authoring rule 3. OpenSCAD
  itself documents coincident faces as undefined behavior and has no static
  diagnostic — the manual's own remedy is "make the cuts a little bit larger".
- **Real example:** a bore cut with `h = plate_t` from `z = 0` fires twice (both cap
  planes coincide); the taught `-1`/`+2` overshoot lints clean.
- **Known noise, owned:** the comparison is **plane-level, not face-level** — a cutter
  cap on the right plane but outside the material's footprint, or on an interior
  joint plane of a union, fires too. Advisory means accepting those knowingly costs
  nothing; checking face overlap is a heavier geometry problem deliberately not
  taken on here.

### `csg-two-part-intersection`

- **Predicate:** the file's entire top level is a single `intersection()` of exactly two
  children. A probe whose two parts are *module calls* matches too, because the export
  folds `rail(); cover();` into two `group` children; a `difference()`, a second
  top-level node, or a third child does not. Of the `.scad` files tracked in this repo,
  **2 match** — `examples/clearance/clearance.scad` and
  `examples/clearance/interference.scad` — counted over those whose export can be read at
  all, which is 24 of 28 on 2021.01 and 25 of 28 on 2026.08.01, the rest being refused
  whole for string content before any rule runs.
- **The two matches are expected, and no authoring of them would remove the finding.**
  They are `SPEC-contract.md` §9.1's worked probe pattern, and the predicate is the
  *shape*, which every part-versus-part probe has by construction. Growing a part by the
  clearance — this rule's own stated remedy — does not change the shape: an enlarged
  module, a `minkowski()` and a `hull()` sweep were each measured, and all three still
  match on both pinned engines. The remedy makes the *claim* numeric, which is what it is
  for; it was never a way to silence the finding, and the finding is advisory anyway. The
  clearance probe has taken the remedy; the interference probe needs no clearance, its
  claim being a band on positive volume already.
- **Trust the test, not these counts.** All three numbers move whenever a `.scad` is added
  to the repo, and the denominators move again whenever an engine changes what it will
  export. `tests/test_lint.py::test_only_the_clearance_probes_match_the_two_part_intersection_rule`
  asserts the match list by **name and by equality**, so a newly matching file fails it and
  says which file — a guarantee a prose count cannot make.
- **Rationale:** declared with `p.empty()`, that shape proves **no positive-volume
  interference**, which is not the same as proving the parts are separated. A
  zero-thickness contact collapses to empty on the OCCT tier always, and on OpenSCAD's
  manifold backend for most arrangements though not all, so touching and clear are one
  signal there — unless the contract itself pins a kernel that keeps the sheet, which is
  the author's call and stays theirs
  (`SPEC-contract.md` §4.12, #270). The claim is valid and the finding is not a defect:
  it is narrower than it reads, and the remedy is to say the clearance you mean —
  intersect against a part grown by it, so a violation with any margin has volume rather
  than a sheet. The remedy is bounded, not absolute: a gap of exactly the clearance is
  degenerate again, and a thin enough violation still falls under the kernel's floor
  (`SPEC-contract.md` §4.12 and §9.1 rule 3).
- **Known noise, owned.** This shape is **not** unique to probes: `intersection()` of two
  solids is also how a part gets *built*. All four of these fire, measured, and none is a
  probe — a lens blank (`sphere ∩ cylinder`), a chamfer by rotated cube, two
  perpendicular `linear_extrude` profiles, and a lattice trimmed to its envelope. The
  discriminator is the contract's `p.empty()`, and `partspec lint` never sees a contract,
  so the finding is phrased conditionally and cannot be narrowed without also losing
  genuine probes. **If the intersection is how your part is built, the finding does not
  apply to you.** Same standing as `csg-coincident-face`'s known noise: advisory, and
  never a verdict on the part.
- **Reads the tree before any boolean runs**, so the *predicate* answers the same on
  every kernel — which matters here, because the kernels are precisely what disagree
  about the result. It consults no engine verdict and needs none. (Whether the rule gets
  to run at all can still differ: a file refused for string content is refused on the
  engine that exports the string, and the two engines do not always export the same
  tree.)

### `csg-difference-order`

- **Predicate:** a `difference()` whose first child's analytic volume is smaller than
  a later child's. Volumes are exact for cubes, **closed** polyhedra, and ideal
  cylinders/spheres, scaled by `|det M|`; union/group volumes are the **sum** of
  children — an upper bound when children overlap — so the verdict is
  upper-bound-vs-upper-bound and the finding says so.
  A `polyhedron()` whose faces do not bound a volume — an edge with no reverse,
  or one traversed twice the same way — is **refused, not estimated** (#289):
  the divergence sum returns a number for any surface, and a number computed
  over a surface that encloses nothing is a finding invented out of nothing.
  The rule goes to `unsupported` with the edge named. Edges are matched by
  vertex **coordinate**, because the engine welds coincident vertices and a
  mesh converted from STL/OBJ shares none of its indices.
  Two limits of "exact", stated because the rule leans on the number: a closed
  but **self-intersecting** polyhedron measures the sum of its shells rather
  than the solid — an upper bound, which is all `csg-difference-order` needs,
  and the finding already says it compares upper bounds. And a **globally
  inverted** surface (every face reversed) is closed and coherently wound, so
  it is measured; the magnitude is right and the sign is discarded. The one
  shape that can therefore read *below* the material is a solid plus a disjoint
  inverted shell — measured 784 mm3 for a shape a CGAL boolean on 2021.01 puts
  at 1216 mm3 — which is a pathological authoring error rather than a partspec
  disagreement: OpenSCAD's own exported mesh measures 784 too, on both pinned
  engines, directly and through `render()`.
- **Rationale:** skills/openscad-authoring rule 2 — the first child is the material;
  the wrong order is a different part, sometimes an empty one.
- **Real example:** the skill's rule-2-before block fires; its after-form is clean.
- **Known noise, owned:** an idiomatic oversized cutter ("remove everything above
  z = h" as a giant box) can out-measure the material and fire on correct code; and
  a polygonized minuend (a coarse `$fn` sphere) measures below its ideal bound, so a
  true wrong order can fail to fire. Both directions follow from the stated
  upper-bound convention.
