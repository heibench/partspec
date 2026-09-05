# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.8] - 2026-09-03

### Added
- **A dimension defaulted from `undef` is now narrated, and honestly not
  refused** (#308, #332, #338). Prefixed `o = undef;`, seven spellings of five
  builtins exit **0** with a clean watertight single solid built to a number
  nobody wrote: `cube(o)` and `cube(size=o)` to 1 mm, `linear_extrude(o)` and
  `linear_extrude(height=o)` to **100**, `cylinder(h=o, d=10)` to h = 1,
  `sphere(o)` to r = 1 — stderr **empty** for all of them on both pinned
  engines. (`resize(o) cube(5)` is silent too but is a **no-op**, 12 facets and
  bbox 5 x 5 x 5 unchanged, because `newsize` defaults to `[0,0,0]` and a 0
  there means *keep this axis* — the one row of the seven whose resulting
  dimension IS a number the author wrote.) #332's eleven-row table was re-measured
  here row for row, including both amendments it had already taken: `circle(r=o)`
  exits **1** with no STL, and `linear_extrude(o + 1)` warns **twice** on
  2021.01 and once on 2026.08.01. **No new refusal ships, and the reason is
  provable rather than provisional.** stderr cannot decide it — the silent rows
  emit nothing, and `undefined operation` fires beside a correct 272-facet bored
  plate (measured, genus 1, exact 40 × 30 × 6, both engines), which is why
  PR #306 reverted it. The `.csg` cannot decide it either: `o = undef; cube(o);`
  exports **byte-identical** to `cube(1);` on both engines, as do the
  `linear_extrude`, `cylinder` and `sphere` rows against hand-written correct
  counterparts, so any tier-2 rule refusing the fault refuses ordinary code byte
  for byte. What ships instead is `partspec lint`'s tier-1 **`scad-untested-undef`**
  — a name bound to a literal `undef`, read, with no `is_*()` or `== undef` test
  in its scope — advisory, engine-free, and firing on none of this repository's
  29 tracked `.scad` files. `skills/openscad-authoring/SKILL.md` gains rule 8 and
  `FAILURE-MODES.md` entry 10, both carrying the contract half, which is the part
  that actually refuses: `envelope(max=(40,30,6))` turns #332 row 1 and #338(b)
  from exit 0 into **FAIL, exit 1** on both engines, while #338(a)'s vanished loop
  gets *smaller* and still passes it — only a two-sided
  `envelope(min=(40,8,10), max=(40,8,10))` fails that one, exit 1 on both engines,
  with the correct `n = 4` part passing. The rule's accepted noise is named rather
  than denied: an `undef` read only by an `echo` fires, and that is exactly the
  correct part PR #306 and PR #329 round 2 each refused at exit 4 — here it costs
  nothing, because `lint` exits 0 whatever it finds. `tests/test_docs.py` executes
  rule 8's two heights on whichever engine is pinned, and `docs/FAILURE-MODES.md`
  gains **entry 10**; entry 9b's symptom is rewritten for the third cause #377
  adds, so the two land in either order.

  Adversarial review found the rule's edges wrong in three ways, all fixed here and
  all with the corpus answer unchanged — **linting the same 126 tracked sources
  with the rule before and after produces byte-identical output**. The stated
  number is gone: two successive drafts quoted one, and both were stale within
  hours, because the corpus moves whenever any branch adds a literal. The
  byte-identity is the invariant and it does not move. Both this rule and
  `scad-unused-top-level` asked their "is this name read elsewhere" question over
  the **line**, so a packed `o = undef; h = o + 1; linear_extrude(h) …` — one legal
  line, and the exact string `docs/LINT.md` printed as this rule's own example —
  produced no finding here and a **false** "declared but never read" there. Both now
  ask it over the assignment **statement**, which is what `scad-magic-number` learned
  in the v0.7.0 pre-tag audit; `tests/test_lint.py` lints the documents' examples
  verbatim out of the shipped files rather than re-rendering them, since the
  harness's own newlines were what hid this. A `name =` at bracket depth >= 1 is a
  **keyword argument**, never a read — `cylinder(h = 20)` names cylinder's parameter
  and cannot reference the caller's `h` — which had said `'d'` was read by
  `cylinder(d = 8)` on a correct 272-facet part while hiding a genuinely dead
  `h = undef;` knob from `scad-unused-top-level`, so one rule stated a falsehood
  while no rule stated the fault; both are now right. And a parameter's scope now
  includes the parameter list, so `module m(a = undef, b = a)` is seen. The
  remaining noise — a shadowing rebind, and a top-level name silenced by an
  `is_undef` in an unrelated scope — is enumerated in `docs/LINT.md` rather than
  left implicit.

### Changed
- **A backwards range is engine-defined, and neither engine says so where it
  matters** (#356). `for (i = [1 : n])` at `n = 0` — the shape a loop takes when
  a count falls to zero — is normalised and iterated **ascending** by 2021.01 and
  iterated not at all by 2026.08.01. Measured on a 40 × 8 × 6 rail with a
  6 × 8 × 4 stud: 36 triangles and bbox z 9.99, two studs the source did not ask
  for, against a bare-rail 12 and bbox z 6 — both at exit 0, both watertight and
  single-solid. That is `FAILURE-MODES.md` entry 1's F13 class, and the stderr
  guard added for it does not reach this one: 2021.01's `DEPRECATED: Using ranges
  of the form [begin:end] …` is not among the lines read off a render that
  succeeded and `build_stderr` is `null` in the report either way, measured under both
  engines on this part, while 2026.08.01
  warns only when the range is a *literal* and a count that falls to zero always
  arrives through a variable. So the issue's premise that the older engine is
  silent is corrected here: it narrates, into a channel nothing reads.
  `skills/openscad-authoring/SKILL.md` gains rule 7 — guard the count with
  `if (n > 0)`, measured identical on both engines at `n = -1`, `0` and `2`, as
  is the three-argument `[1 : 1 : n]` — and entry 1 gains the sibling shape with
  its measurement. What does catch it is the guard entry 1 already names: a
  two-sided `envelope` on the `n = 0` part gives `FAIL envelope — z=9.98999977`,
  exit 1, on 2021.01 against `PASS: 4 pass`, exit 0, on 2026.08.01, with
  `watertight` and `solid_count` passing on both. `tests/test_docs.py` executes
  rule 7 on whichever engine is pinned.

- **ISO 965-1 does not meet §10.1's formula-executed exception, measured**
  (#260, #246, #261). The exception admits a standard's tolerance grades and
  fundamental deviations where the standard states them as a formula *and* the
  suite executes that formula against every shipped value. ISO 965-1:2013's
  clause 10 states the formulae — and its §10.1 also states that "in order to
  reproduce a smooth progression, the rules of rounding off are not always
  used", and that where the computed and tabulated values differ, **the tables
  govern**. Executing every clause-10.2 formula against Table 1 with the R40
  rounding §10.1 prescribes: **149 of 197 cells agree, 48 do not** — the best
  of fifteen rounding models swept. The standard rounds half-to-even, which
  its own tables give away: the images only half-up can produce (13, 27, 43)
  appear nowhere in Tables 1–5, while the half-even-only images (26, 42)
  appear five times in Table 1. Not a rounding artefact — `es_d = -(65 + 19P)`
  at P = 8 gives -217 raw and -212 rounded against a tabulated -180, and
  column `d` carries -105, -110, -115, -130, -135, -155, none of them the
  rounded image of any R40 member. `es_g = -(15 + 11P)`, the formula #246
  cited as its corroboration when it narrowed the exclusion, reproduces 24 of
  25 cells and misses at P = 0.75 — right often enough that a reader stops
  checking, which is the shape the exception exists to catch. Both routes
  therefore fail: the tabulated values cannot execute the formula, and the
  computed values are ones the standard says shall not be used, under a
  citation naming that standard — the "worse than no data" case the exception
  exists to prevent. The near miss was considered and rejected: `EI_G`/`es_g`
  hold for all 15 cells at P >= 0.8, but that bound is chosen after seeing
  where the formula fails, and it excludes ten of Table 1's twenty-five
  pitches — with them thirteen of the forty coarse sizes this module ships, M1
  through M4.5, **including M3**, one of the two sizes every fleet-01 arm-C
  replicate hand-wrote 6g/6H data for (#194). The standard's tables govern at
  every pitch regardless. Nor is the tie rule constant: Table 1 breaks
  `es_g`'s P = 8 tie downward while Table 2 breaks the same kind of tie at
  `TD1(6)`, P = 1 upward; under the upward reading `es_g` is 23 of 25 and the
  P >= 0.8 set is 14 of 15. The exception is unchanged and may still reach a
  standard whose formulae are normative. `iso_metric_thread`'s claim that the
  ruling licensed this data is corrected, the released #261 entry's
  "verifiable by construction" claim for `es_g` is falsified by the same
  measurement, and §10.1 records it so the work is not repeated.

### Fixed
- **The release workflow creates the GitHub release** (#381). It built,
  asserted the tag was on `main`, asserted the tag matched the package
  version, smoke-tested the wheel and published to PyPI — and never made the
  release page. That step lived only in habit, named in no workflow, no
  recipe and no document, and habit missed it three times running: **v0.7.5,
  v0.7.6 and v0.7.7 were tagged and on PyPI with no release**, so the
  repository advertised v0.7.4 as current for three weeks while users
  installed 0.7.7. The tag and the upload were right every time; the only
  human-readable record of them was the one step with no gate on it — epic
  #305's third state, which its "Done means" says may not exist. The new job
  takes the notes from the CHANGELOG section for the tagged version and
  **fails when there is none**, which is the first thing to confirm that
  `[Unreleased]` was renamed before the version reached PyPI rather than
  after. Notes over GitHub's 125,000-character body limit are truncated with
  a pointer to the file: v0.7.7's section is 170,793 bytes, so the first
  draft of this job would have failed on the release that motivated it —
  measured rather than assumed. The three missing releases were published
  retroactively.

- **`measure` answers every quantity it can, whatever defeated one of them**
  (#365). A zero-thickness part — `intersection()` of two cubes meeting on a
  face, which 2021.01 and 2026.08.01 both export as a closed, consistently
  wound four-facet sheet — has no centre of mass, because the centroid divides
  by the volume. `trimesh` returned `nan`, `Measurement` refused it by
  raising, and the raise escaped the per-name loop: exit 4, **stdout 0
  bytes**, no `area`, no `bbox`, on a part whose other thirteen names the
  payload accounts for — eight measured, five unavailable on that tier — and
  whose `area` the same geometry answers through `check` (480.0 mm², pass,
  exit 0). The mesh tier's `center_of_mass` now refuses that shape with a
  reason — "this mesh encloses no volume, so it has no centre of mass (check
  volume first)" — leaving `area` 480.0, `bbox` (20, 12, 0) and `volume` 0.0
  emitted, all fourteen names accounted for across the three §7.3 blocks.
  `measure` also catches a raising backend per name and records it in
  `refused` rather than ending the run, so the next one can cost one name and
  not the verb. The OCCT tier already guarded this case and was measured
  unaffected; `render` builds no `Measurement` and has no equivalent path.

- **The substitution sentence no longer asserts a default nothing took**
  (#360). `Problem converting rotate(...)` joined the substituted-value
  markers in #333 and inherited that marker's diagnosis — *the engine could
  not convert a value and built a default in place of it* — which is false for
  one of its measured shapes. `rotate([90, 0, 0, 0]) cube([10, 5, 2])` exports
  a mesh **byte-identical** to `rotate([90, 0, 0]) cube([10, 5, 2])` on both
  pinned engines (`cmp -s`, 1485 bytes on 2021.01 and 1479 on 2026.08.01):
  2021.01's `transform.cc` reads `default: ok &= false; /* fallthrough */
  case 3:`, so an over-long vector has its first three components read and
  applied and **nothing is substituted**. That line now gets a third cause —
  *the engine could not use a value as written* — with a hint that says stderr
  cannot tell which of the shapes it is in. `Unable to convert` keeps the
  substitution text unchanged to the byte: for that marker a default really is
  always taken, and one weaker sentence covering both would have cost the
  precision that makes it actionable. **The refusal is unchanged**, at exit 4,
  for `FAILURE-MODES.md` 9b's reason: the source is wrong whatever the mesh
  is. `SPEC-contract.md` §4.12 and `AGENT-CONTRACT.md` §2.3 move with it.

- **A re-pin confesses in the artifact, not only on the console** (#294). The
  stderr half shipped in #351; the report's `expectation` block still carried
  nothing, and `SPEC-report.md` §7.1 said the block was "present only when the
  run was invoked with `--expect`". Both move together here. A `--pin` run over
  a lock that already covered this part, whose declared claims differ from it,
  now writes `{"repinned": [...]}` into that part's own report — the same lines
  `compare()` gives the console under any single writer, with the caveat the
  two reads below make explicit. Measured on `examples/spacer`: pin, edit `PLATE` from
  (40, 30, 6) to (40, 30, 9), re-pin — the report went from no `expectation`
  key to `repinned: ["changed: envelope — pinned 'envelope max=[40.0, 30.0,
  6.0]', declared 'envelope max=[40.0, 30.0, 9.0]'"]`, at `verdict: "pass"`,
  exit 0. **Still not a refusal and not an adjudication**: §4 of the agent
  contract permits a deliberate re-pin. The two forms of the block are
  therefore **disjoint** — they share no key — because §7.1 binds
  `matched: false` to `verdict: "error"`, and a permitted re-pin is exactly a
  mismatch that is not one, so a consumer keying on `matched` may never meet
  this form. Absent in **four** cases: a first pin, a part the lock did not
  cover, a re-pin that moved nothing — and a lock that could not be READ, which
  is still overwritten when nothing failed to resolve and leaves every report
  without the block, all three records of the move vanishing together, since a
  lock whose bytes will not parse is also a lock whose diff a reviewer cannot
  read. §7.1 names that fourth case so absence is not read as "nothing moved".
  That the flag was passed at all is `invocation.argv`'s to say. The lock is
  read **twice**: once before the first target, because every report is written
  inside the target loop while the lock write comes after it, and again
  immediately before that write, because the two reads answer different
  questions. Reusing one snapshot for both let a part another process added
  during the build be written out of the lock with neither the `dropped` line
  nor a refusal — measured with a writer adding a part 2 s into a 4 s build.
  The cost is that the report and the console can word one move two ways when
  the lock moves under the run: seeded at `envelope max=[10, 10, 10]` and
  rewritten to `[20, 20, 20]` mid-build, the console names `[20, 20, 20]` and
  the report `[10, 10, 10]`, each correct for the question it answers. §7.1
  says so rather than promising an equality that only holds for one writer.
  The block records what was **compared**, not a write that happened: a crashed
  target that would drop a claim set makes `--pin` refuse, leaving the lock
  byte-unchanged at exit 4 while the surviving part's report still names the
  differences. `AGENT-CONTRACT.md` §4 and §5, and `examples/spacer/README.md`,
  name the third record and say the same thing about it.

- **A library only the engine can read no longer makes every `-D` unjudgeable**
  (#311, #287). `unbound_parameters` answers from the files *partspec*
  resolved, and #287 made the refusal honest when that list is short. It could
  not finish the job when the engine could open a file partspec could not: on
  the pinned 2026.08.01 AppImage, which bundles `MCAD` inside its own squashfs,
  `include <MCAD/units.scad>` with `mm=2.0` renders a 20 mm cube and partspec
  refused it at exit 4, on a correct part and a correct contract — while the
  report carried the disproof, `engine_inputs.state: complete` naming the
  resolved path. The refusal is now **deferred** when, and only when, the
  parameter binds nothing *and* an `include` did not resolve: the render goes
  ahead, and on a `complete` depfile the closure is walked again with the
  engine's own input list as a last-resort search path, matched back to the
  reference by path suffix. Measured on that arm: exit 4 → exit 0, bbox
  20 × 20 × 20, so the `-D` demonstrably reached the geometry. The other arm
  must not move and does not — the issue's own `bore_diamter` transposition
  beside the same unread library stays refused, now at `origin="model"` under
  the ordinary sentence, because the re-asked list holds `bore_diameter`, `mm`,
  `cm` … and still not `bore_diamter`. On apt 2021.01, which cannot read
  `MCAD` either, both arms keep #287's `environment` refusal verbatim: the
  depfile does not name the file, so nothing better is available and none is
  claimed — and that is the ordinary Debian/Ubuntu case, not an exotic one: an
  engine can have `-d`, write a `complete` depfile, and still be as blind to
  the library as partspec is, in which case the render is paid for and the
  answer does not improve. Ambiguity is not guessed at — two files ending in the
  same reference leave it unresolved. The suffix is matched against the token
  the depfile **wrote**, which is the half review found missing twice: partspec
  resolved every token while the reference stayed a literal, so a library
  reached through a symlink arrived under its real name and a decoy that still
  ended with the literal became the unique hit — one library's variables read
  behind another library's name. Measured, that returned an artifact for a `-D`
  that never reached the geometry, and in a second shape an `origin="model"`
  verdict blaming a correct contract off the decoy's contents, where main had
  refused honestly. OpenSCAD writes each token as `searchdir + reference`, so
  the literal is always a suffix of it — measured through a directory symlink
  and a file symlink, both engines — and `RenderDeps` now keeps both spellings:
  `files` resolved for identity, `missing` and the overwrite guard, `listed` as
  written for this one question. A first attempt counted basenames instead; it
  closed the directory-symlink shape, left the file-symlink shape open, and
  refused a case main resolved. Two spellings of one file are not an ambiguity,
  so the count is over resolved identity. The cost is one render on the path
  that used to exit 4 before rendering anything, and exactly one: +110 ms on a
  sphere whose bare engine render is 102 ms, +28 ms on the six-facet
  reproduction.

- **`EXIT_USAGE` no longer claims it writes no report** (#358). `check` puts a
  placeholder at every target's deterministic path before any target runs, and
  `--expect` is read after it, so a refused lock exits 64 over a report that is
  already on disk: `verdict: "error"`, `counts.total: 0`, no `checks`, and the
  diagnosis on stderr only. Measured on two shapes — `--expect nosuch.lock` and
  an unresolvable `nosuch.py:widget`, each leaving `outputs/<slug>/report.json`.
  The docstring now says which 64s write nothing — the rule is *raised before
  the placeholder loop*, and the examples given are not a closed list, because
  `partspec --docs check …` and a bare `partspec` are two more that fit it —
  and which leave an undiagnosable artifact, and `tests/test_cli.py` pins the
  behaviour so the wording cannot go stale silently. The second clause, that a
  64 never participates in batch aggregation, was independently true and is
  kept — but no longer stated as a consequence of the false one.

- **The fence guard reaches `examples/`, and reads more than the exit status**
  (#366). `test_every_openscad_fence_in_the_docs_parses` globbed `docs/` and
  `skills/` — the wrong half, since an exemplar README is where a snippet is
  most likely to be copied verbatim: PR #364 shipped one broken fence into
  `docs/` and an identical one into `examples/clearance/README.md`, and only
  the first turned the suite red. Both halves are fixed. The glob now covers
  `examples/**/*.md`, and a fence whose stderr carries an unresolved NAME
  fails even at exit 0 — measured on both pinned engines, deleting the
  `CLEAR = 1.5;` a fence depends on leaves both exporting rc 0 with `WARNING:
  Ignoring unknown variable 'CLEAR'`, i.e. a sphere at the default radius
  rather than the prescribed one. The vocabulary is the engine guard's own
  `_UNRESOLVED_NAME_MARKERS`, so the two cannot drift apart, with three
  **names** exempted rather than the marker — two shipped fences legitimately
  call `a`/`b`/`grown_b`, which they do not define (`SPEC-contract.md` §4.12
  and `skills/contract-authoring/SKILL.md`) — and an assertion that the
  exempted marker is still spelled that way upstream. Exempting the marker
  would have exempted the typo with it: appending `post_envelop();` to the
  `examples/clearance` fence, a misspelling of the `post_envelope` that same
  fence defines, renders nothing and passed on both engines under the
  marker-wide form.

- **The exemplar's `diff` transcript is now replayed, not read** (#361). PR
  #353 changed what a `diff` summary line can say, `examples/spacer/README.md`
  kept quoting the old text, and three gates stayed green over it: the console
  test reads the ROOT README, nothing in the suite read the exemplar's README
  at all, and `just example-spacer` runs `check --expect` and never `diff`.
  `tests/test_docs.py` now executes that transcript — every `$` line run in a
  copy of the exemplar, the narrative `# ... now edit BORE_D ...` applied as
  the edit it describes, every quoted output line required to be a LINE the
  tool printed, every `echo $?` matched against the exit code, the drift entry
  quoted below it compared against `drift.json` verbatim, and a command shape
  the replay does not know failed loudly rather than skipped. Falsifying the
  summary line, the exit code, the `covered:` line or the quoted entry each
  fails it on both pinned engines — including the falsification that actually
  happened, which was an **append**: restoring the pre-#353 `different:
  example-spacer — 2 drifted` fails on both engines, where a substring test
  over the whole printed blob passed it, the stale line being a prefix of the
  line that replaced it. The issue's other candidate — a `diff` step
  in `just example-spacer` — is deliberately not taken and the recipe says
  why: that recipe gates the console contract by printing it, and a `diff`
  over a drifted baseline exits 1 whatever the summary line says.

## [0.7.7] - 2026-09-02

### Added

- **The drift loop ships as something you can run** (#290, #291, #294). `--pin`
  and `--expect` are what partspec has over "run a script and eyeball it", and
  nothing the project shipped exercised either: no `claims.lock` was tracked
  anywhere, CI never invoked the CLI on an example, and no recipe existed.
  `examples/spacer/claims.lock` is now committed with the pin/expect sequence in
  that example's README, and **CI runs it on both engine legs** — a committed
  lock nothing exercises would reproduce the very root cause, the loop being
  unseen by the project's own gate. Verified green on 2021.01 and 2026.08.01,
  and exit 4 with all 8 checks skipped when `PLATE` moves without a re-pin.
- **Where a baseline comes from** (#291). `check` overwrites its report in place,
  so the second run of any loop destroys the only baseline the first produced —
  and `outputs/` is gitignored unanchored at every depth, making the default
  disposition "deleted, then untracked". `AGENT-CONTRACT.md` §4 and
  `SPEC-diff.md` §1 now say so, with the literal `cp` and the convention for
  keeping one.

- **The documents install with the package** (#349). `docs/` and `skills/` now
  ride in the wheel, and **`partspec --docs`** prints the directory they resolve
  against. Before this, an installed copy could reach neither: every diagnostic
  cites a spec by section, `AGENT-CONTRACT.md` opens by routing the reader to
  `skills/contract-authoring/SKILL.md`, and on 0.7.6 a `find` over the installed
  tree for `AGENT-CONTRACT.md` returned nothing — so the whole agent-facing
  corpus was reachable only over the network, which an agent without it cannot
  do at all. The bundled directory **mirrors the repository root** rather than
  flattening the two trees, so `docs/SPEC-contract.md` and
  `skills/contract-authoring/SKILL.md` resolve verbatim from an install and from
  a checkout alike, with no citation rewritten and no second spelling to keep in
  sync. `--help` names the directory when there is one and says there is not
  when there is not; `partspec --docs` prints the path alone on stdout, or
  exits `4` printing nothing there — a caller writes `cd "$(partspec --docs)"`,
  and a URL on stdout would be a string no shell can enter standing in for the
  answer. Combined with a verb (`partspec --docs check part.py`) it exits `64`
  rather than printing a path and exiting 0 on a check it never ran. Costs
  about +160 KiB on the wheel. `examples/` deliberately does not ship:
  `force-include` copies what is on disk rather than what git tracks, and
  adding it put ten untracked `outputs/` artifacts in the wheel — a dev build
  and a CI build would no longer agree (#218's failure, on the artifact that
  reaches PyPI).

  **What an install still cannot open**: the 27 citations in these documents
  that name a file under `notes/`, `tests/`, `src/` or `examples/`. Those are
  pointers into the repository, and `docs/README.md` now says so rather than
  implying the corpus is self-contained.

- **`payload` — every artifact now says which artifact it is** (#295, epic
  #305). `check`, `measure` and `render` all emit `schema_version: 1` under
  `tool.name: "partspec"` and share the whole identity prefix by design, so a
  consumer holding one of the three could not tell which it had. Each payload
  now names itself — `report`, `measure`, `render`, `lint`, `vdiff` —
  immediately after `schema_version`, where the two are read together: the
  version says how to READ the document, `payload` says WHAT it is.
  **`vdiff` spelled its version `vdiff_schema_version` and nothing else**, so
  `doc["schema_version"]` — the key `SPEC-report.md` §7 tells a consumer to key
  on — raised `KeyError` on that one artifact and on no other. It emits
  `schema_version` as well now, both spellings taken from one constant so they
  cannot drift; the old key stays for one release, and dropping it later is the
  breaking change §7.1 says a removal is.
  **Additive, so `schema_version` does not move** — §7.1: "adding a field is a
  non-breaking change and MUST NOT bump `schema_version`". The same rule makes
  the field optional to a *reader*: every artifact written before this release
  carries none, and its absence means "an older partspec wrote this", never
  "not a report". That is why `diff`'s "is this a report" guard (#292, #328)
  keeps keying on `verdict` and `counts` being present rather than on the new
  field — one keyed on `payload` would refuse every report the tool has written
  to date, and a document that declares a verdict is a report whatever it calls
  itself. The guard already refuses a `measure` or `render` payload by that
  test, at exit 64; what the discriminator adds is that a consumer which is not
  `diff` can now make the same distinction, by name, without reverse-engineering
  it from the key set.
  **All six payloads #295 names, `partspec diff`'s own artifact included
  (#345).** It shipped without one — its module belonged to another lane during
  #342 — which left §7.1's "absent means an older partspec wrote it" reading
  scoped to five artifacts, drawing a false conclusion about every `diff.json`
  this release had written, and left a consumer switching on `payload`
  special-casing that one document by `tool.name`. It now carries
  `"payload": "diff"` in the same position as the rest, `DIFF_SCHEMA_VERSION`
  unmoved at 2 by the same additive rule, and §7.1 states the plain rule with
  no exception attached.

- **`csg-two-part-intersection`, an advisory lint rule** (#270). Fires when a
  file's entire top level is a single `intersection()` of exactly two children.
  A probe whose two parts are module calls matches too, since the export folds
  the calls to two `group` children; a `difference()`, a second top-level node,
  or a third child does not.
  **The shape is not unique to probes, and the rule says so rather than
  pretending otherwise.** `intersection()` of two solids is also how a part gets
  built: a lens blank, a chamfer by rotated cube, two perpendicular extrusions,
  a lattice trimmed to its envelope — all four fire, measured, and none is a
  probe. The discriminator is the contract's `empty()` and `partspec lint` never
  sees a contract, so the finding is phrased conditionally and the noise is
  owned in `LINT.md` beside `csg-coincident-face`'s. Two of this repo's tracked
  `.scad` files trip it — `examples/clearance/`'s two probes, of the 24 of 28
  whose export can be read on 2021.01 and 25 of 28 on 2026.08.01; the rest are
  refused whole for string content — and a test pins that match list **by name
  and by equality** rather than three documents asserting a count. Those two are
  §9.1's worked probe pattern and are expected: the predicate is the shape, and
  every part-versus-part probe has it by construction.
  It reads the `.csg` tree **before any boolean runs**, so the predicate answers
  the same on every kernel — which is the point, the kernels being exactly what
  disagree about the result. It consults no engine verdict and needs none.

- **Part-versus-part interference is declarable, and `examples/clearance/` is
  the worked pattern** (#236, with #237 and #238). partspec's unit of
  verification is the single part through v1.0 (D19), and #236 read that as
  *interference cannot be declared at all* — because the obvious workaround,
  modelling `intersection() { A; B; }` at assembly pose as its own part,
  "fails in **both** of its normal outcomes, for two independent reasons".
  Those two reasons were #237 and #238, and both have closed. So the pattern
  works now, and what was missing was that nothing said so.
  **Two of the three outcomes grade portably, and each on a different
  measurand.** Measured on the new example: parts that interpenetrate build a
  solid and `volume` grades it at **24.0 mm3**; parts that stand off build
  nothing, which was a hard failure before any claim was evaluated and is now
  `empty()`'s passing result (#237). Documented in `SPEC-contract.md` §9.1 and
  executed by `tests/test_examples.py`, parameterised so a regression names the
  outcome that broke rather than reporting one failure for two unrelated
  mechanisms.
  **The clearance probe intersects against a GROWN part, and §9.1 makes that a
  rule.** `empty()` over a bare `intersection() { A; B; }` says only that two
  parts do not interpenetrate — it is equally satisfied at 9 mm of standoff, at
  0.01 mm, and, on a kernel that drops a zero-thickness sheet, at exact contact.
  A clearance is a number and that probe carries none. Grown by the standoff the
  fit requires, the same `empty()` states the standoff, and a violation of it
  *with any margin* is a solid every kernel agrees about down to its own floor:
  measured by dropping
  the example's lid to a 1.0 mm standoff against a required 1.5 mm, the grown
  probe fails on **both** pinned engines at **31.5 mm3** while the ungrown one
  passes on both. This is the remedy `partspec lint`'s
  `csg-two-part-intersection` names (#270), and §4.12 now says it at the check
  that carries the risk.
  **Growing relocates the degenerate case rather than removing it**, and §9.1
  rule 3 says so instead of overselling: at a gap of *exactly* the clearance the
  probe is a zero-thickness sheet and the pinned engines split — 2021.01 exits 1
  on a 284-byte sheet, 2026.08.01 exits 0 having exported nothing — which is the
  same divergence the section condemns for face contact, now sitting on the
  number a designer working *to* the requirement lands on. So a design gap must
  clear the requirement **strictly**, which is why the example designs 2.0 mm
  against a required 1.5 mm. A per-axis grow also measures **Chebyshev** rather
  than Euclidean distance — a corner 1.2 mm away on each axis is 2.0785 mm away
  in a straight line and still fails a 1.5 mm requirement — which is false FAIL
  only, never false PASS, and agrees on both engines.
  **The third outcome — face contact — is documented and NOT recommended**,
  because it is kernel-dependent. Measured on both pinned OpenSCAD versions,
  `intersection()` of two 10 mm cubes offset by their own width exports a
  284-byte sheet on 2021.01 (`check` exit **1**) and nothing at all on
  2026.08.01 (`check` exit **0**) — one source, two engines, opposite verdicts.
  Under #270's settled semantics for `empty()` — no *positive-volume*
  interference — the newer engine is the correct one, so the divergence cannot
  be resolved by preferring the richer result. Retention is not the only axis
  either: on the example's own seated face both engines write a four-triangle
  sheet and disagree about its shape, **384.0 mm2 against 268.8 mm2**. #314 is
  the enabler — once a report can state whether the kernel retained a
  zero-thickness result, an `area` claim over a contact patch means something.
  **The trap that remains is written down because it is silent.** `empty`
  belongs on the probe that should be empty and on no other — on an
  interference probe an empty build is the *loose joint*, so declaring `empty`
  there would grade the fault as the pass.
  **Not superseded: `keep_out`/`keep_in` still take a declared region.** Their
  shell is mandatory and a shell is an offset of the region, which a rendered
  solid could only supply through 3D offsetting — measured, `manifold3d`'s
  Minkowski gives the outward offset in 13 ms and the inward one in **1290 ms**,
  inside a 24-iteration bisection. The shell exists to stop a `keep_out`
  passing vacuously when the feature is absent, and that risk does not arise
  here: the other part is a real rendered solid whose absence is a build
  failure, not a silent pass. The expensive machinery would be bought for a
  guarantee this case does not need.

- **`p.build_input("cadquery-ocp")` — an author may force byte identity for a
  named distribution** (#215, epic #229, stage 4 of #190). Identity is decided
  automatically in two tiers, and `metadata` — what almost everything gets —
  trusts the installer: version plus a digest over the RECORD's own hashes.
  `SPEC-report.md` §8.3 rule 5 states its bound plainly, that **an edit to a
  file the RECORD *does* declare leaves the digest unmoved**, because ownership
  is decided by path and hashing every loaded file is the cost that tier exists
  to avoid. This is the opt-out, for the one distribution an author knows is the
  subject.
  **Opt-in because the cost is lopsided**, which is the whole reason it is a
  declaration rather than a default: measured, `build123d` 1.4 ms over 41
  declared files against `cadquery-ocp` **228.5 ms over 396**. Right for a
  contract whose geometry is OCCT-version-sensitive, wrong for one that is not,
  and only the author can tell which.
  Digested over **the RECORD's own rows, not the package tree**, and that
  distinction is load-bearing: a distribution's unit can be wider than its
  package directory — `cadquery_ocp.libs/` sits beside `OCP/` — and rooting at
  the tree would silently drop exactly the vendored shared objects an
  OCCT-sensitive contract wants this for.
  **Additive, never required.** Tiers 1 and 2 keep running unconditionally, so a
  contract declaring nothing still gets a complete inventory and behaves exactly
  as before. Absence of a declaration never produces a stronger claim.
  Two mistakes are refused rather than absorbed. A **module** name is rejected
  at the call site with the distribution that ships it — `build_input("OCP")`
  says *OCP is the module; the distribution that ships it is `cadquery-ocp`* —
  answerable there because installed metadata is readable before anything is
  imported; and spelling is normalised per PEP 503, so `cadquery_ocp` resolves.
  A declaration naming something that **never loaded** is a run-level `error`
  adjudicated after the build, because the contract described a build it did not
  get. Accepting it silently is the clearly wrong option: the declaration exists
  to strengthen coverage, so a typo would quietly *weaken* it while looking
  exactly like it had been asked for.
  A declaration that changed nothing is still recorded (`declared: true`), so a
  reader can tell coverage that was asked for from coverage that happened to be
  free.

- **`p.empty()` — a part may declare that nothing is the result** (#237). A
  clearance probe, `intersection() { A; B; }` declared as its own part, has
  three outcomes and until now only the *bad* one could be graded: parts that
  interpenetrate give a solid `volume` measures, parts resting on a face give a
  sheet `area` measures (#238), and parts that share no space give nothing at
  all — where an empty build is a hard failure before any claim is evaluated, so
  `volume(max=0)` was **skipped rather than satisfied**. The good answer was the
  one the tool could not state.
  Opt-in, and nothing else moves: a part that does not declare `empty` and
  builds to nothing still fails exactly as before. For an ordinary part contract
  a null render is a real fault, and #237 asked for a way to declare the intent,
  not for the default to soften.
  **A broken probe cannot satisfy it**, which is the whole difficulty and is
  invisible in an exit code. Measured on 2021.01: a genuinely null intersection
  and a model whose geometry never existed are identical downstream — both exit
  1 with `Current top level object is empty.` and write no STL. So one misspelt
  module would have made every probe in a contract pass, and the more broken the
  source the greener the run. The only evidence separating them is the engine's
  diagnostics above that line, so `empty` fails when the engine reported an
  unresolved name and its detail says which. The five markers were each produced
  from a source written to trigger them rather than taken from documentation.
  Classification lives in the engine and rides on `BuildError`
  (`produced_nothing`, `unresolved`), because engines own their own strings. A
  Python model has no equivalent hazard — an unresolved name raises rather than
  rendering empty — and its null results set the same flag, so the check reads
  the same on either tier.
  `SPEC-contract.md` §4.12 is normative for it; `builds` and `empty` are now
  `BUILD_PHASE_KINDS`, which `gen_docs.py` reads instead of naming `builds`
  itself, so the vocabulary table cannot go stale against the code.

- **`area` says what it is for, and names the 2x trap** (#238). It had no
  docstring at all — alone among the bound-carrying methods — while being the
  only measure that answers on a part that is legitimately not a solid.
  A clearance probe, `intersection() { A; B; }` built as its own part, has three
  outcomes and they do not land alike. Interpenetrating gives a closed solid and
  `volume` grades it. Resting on a face gives a zero-thickness sheet, where
  `volume` may refuse — an annular contact measured on 2021.01 exports 94
  non-manifold edges — and `area` still answers, because it is ungated for the
  mirror reason `volume` is gated. Not touching at all does not build, which is
  #237 and stays open.
  **On such a part `area` is twice the contact patch**: both sides of the sheet
  are exported, so a 10 x 10 mm face reads `200.0`. Nothing is wrong with the
  number — that is the surface area of a closed zero-thickness solid — but a
  bound written against a hand-computed patch is out by exactly 2x and silently,
  because 100.0 and 200.0 are both plausible and nothing distinguishes them
  afterwards.
  Pinned by execution rather than asserted in prose: one test measures the 2x on
  a box contact and that `volume` does NOT refuse there (four triangles meeting
  two-per-edge are watertight, so the integral is exactly zero — the half #238
  was filed without), and a second measures the annular case where `volume`
  refuses and `area` answers.

- **A region's dimensions carry their citation** (#250). `keep_out` and
  `keep_in` now record `checks[].source` for the numbers that size the region —
  a box's `min`/`max`, a cylinder's `d`/`h`, and `shell` — so a keep-out sized
  from `partspec.refs` is attributed like any other bound, and both kinds join
  `DIMENSIONAL_KINDS`. Carrying the citation without counting it would have left
  the misleading half in place: a contract whose one externally-footed number is
  a region dimension still reported `attributed: 0` and printed the
  unattributed-limits disclosure.
  A region's `at` stays uncited on purpose. A standard vouches for how big a
  feature is, never for where a design puts it, so recording a citation against
  a position would claim authority the standard never lent.
  **Upgrading re-pins a cited region.** `source` participates in the claims pin
  (`expectation._claim_slug`), so a region that now carries a citation has a
  different slug than it did before, and `--expect` against a lock written by an
  earlier partspec reports `changed: <id>` and exits 4 on a contract file nobody
  touched. That is the pin working — the claim did change, it gained attribution
  — but the change came from the tool rather than the author, so it is stated
  here rather than left to be discovered. Measured: only a region whose
  dimension is `Referenced` is affected; a region declared from literals has an
  identical slug before and after. Re-pin once.
  Found by the round-1 review of #200 — in `examples/stepper-bracket`, whose own
  docstring calls it the citation exemplar, and which shipped taking a keep-out's
  diameter from `refs.nema17` into a check reporting `source: null`. The gap was
  invisible without opening the JSON.
  **#250's stated cause is one cause; measured, it is two.** A box's corners were
  flattened by validation — `Referenced` is a float subclass, `_finite` returned
  `float(value)` and `__post_init__` wrote it back. A cylinder's `d`/`h` never
  were, because `__post_init__` validates them and discards the result — so the
  exemplar's own shape kept its citation the whole time and lost it only because
  `_region_spec` passed no `source`. The two tests are pinned against each half
  separately: dropping the recording fails both, dropping the preservation fails
  only the box.

- **A worked `keep_out` / `keep_in`, in a real part and in the skill** (#200).
  They appeared in no contract anywhere in the tree, so an author learning to
  write one had a single line of `SPEC-contract.md` — bare parameter names, no
  types, no values — and had to guess `region.cylinder`'s argument shapes. Two
  fleet agents on different engines guessed `axis=(0, 0, 1)`; a third form,
  `[0, 0, 1]`, crashed harder (#193, #199). `examples/stepper-bracket` declares
  them now, and `skills/contract-authoring/SKILL.md` carries the call rather
  than only a table row.
  The keep-out is the motor's locating boss, NEMA ICS 16's AK from
  `refs.nema17`. It earns its place beside `nema17.mount`, which declares the
  pilot *bore* through `hole_diameter` — a cylinder-precision claim the mesh
  tier refuses because a faceted bore has no diameter — while the same
  requirement stated as **space** is a claim about volume that both tiers
  answer. (A region's numbers do not reach `checks[].source` even when they
  come from `refs`; that gap is #250.)
  The keep-in is the L's corner, and it takes **two** boxes. The members are
  perpendicular slabs, so one box needing material from both would also span
  the concave quarter outside the L, which is air.
  It also says plainly what the shell does NOT do here: a `keep_in` rooted near
  the part's outer faces has a shell that escapes into free space, so it never
  fires and a solid brick passes it. The keep-out's shell does real work — pull
  the pilot bore and the region fails, pull the plate and the shell fails — and
  saying so of one while the other is inert is worth more than a rule that
  holds everywhere and bites nowhere.
  Which is the lesson the example is really for: **a region proves nothing
  about a member it never enters**, and both ways of getting that wrong were
  shipped in drafts of it. The first box lay inside the plate's thickness, so
  the plate alone satisfied it and it passed with the base cut to a third of
  its width. The second reached further into base-only material, away from the
  plate, so the base alone satisfied it and it passed on a bracket with no
  plate at all — while a 93%-severed joint left the contract nine-of-nine
  green. Check a region by breaking the model and watching it fail.

- **`partspec.refs` carries ISO metric threads** (#194). It had bearings and
  steppers but not the most widely used dimensional standard in mechanical CAD,
  so `iso_metric_thread.coarse(8)` now gives M8's size and profile dimensions
  with every value `Referenced` and cited:

  ```python
  from partspec.refs import iso_metric_thread as iso_thread

  m8 = iso_thread.coarse(8)
  p.hole_diameter(m8.minor_internal, tol=0.05)   # cites ISO 724 / M8 / D1
  ```

  The ISO 261 coarse series, all 40 diameters from M1 to M68 with each one's
  preference rank, and the three ISO 724 clause 5 relations — pitch diameter,
  and the two minor diameters, which differ by `H/6 = 0.144·P` and are the ones
  people confuse. Transcribed from the primary documents: the free iTeh previews
  carry ISO 261:1998's Table 2 complete and ISO 724:2023's Table 1 through M68,
  which is the last coarse row, so every row and all 120 derived values are
  checked against the standards rather than triangulated from secondary
  publishers. A first draft
  built the table from memory and had three defects the standard settles —
  M7 is second choice, the coarse series ends at M68 rather than M64, and M1
  through M1.4 were missing, two of them first choice.
  **The size, not the fit.** ISO 965's 6g/6H classes are out under
  `SPEC-contract.md` §10.1, which excludes a standard's tolerancing tables; #246
  argues that policy on its own merits rather than settling it inside a data
  module. The fit stays the designer's, as `iso15` already leaves it.
  **Derived, not transcribed**, because the standards print six to nine
  significant figures where a double holds seventeen: ISO 724 clause 5 gives
  `0,649 519`, ISO 68-1 clause 5 gives `0,541 265 877`, and `math.sqrt(3) / 2`
  gives every bit there is. The values are therefore
  the exact formula rather than the printed digits — up to 0.4955 um apart, at
  M5's `d3` — and each citation carries a `note` saying so.
  **Cited for what each document says, and dated.** ISO 261:1998 for the
  diameter/pitch pairs, ISO 68-1:2023 for the profile, ISO 724:2023 for the
  three relations and their values. The edition is load-bearing: `d3` exists
  only from ISO 724:2023, while ISO 261:1998 normatively references ISO
  724:1993, which has no `d3` at all. And these are ISO 724's *basic
  dimensions* but they sit on ISO 68-1's *design* profile — its Scope says so —
  which is a distinction two of the three prior fleet modules lost.

- **A failing `keep_out` says how deep the material reached, not only how much**
  (#207). `12.7331 mm3 of material intrudes` was the whole finding, and it is
  the same sentence for a nominal bore's faceting and for a rib 1.5 mm into
  that bore — the two situations an engineer most needs told apart. Volume
  cannot separate them: it scales with the *area* of the contact and only
  linearly with depth, so a hair-thin film over a large face outweighs a deep
  local spike. The reporter had to bisect the region diameter by hand to find
  out which they had.
  The line now reads `…, reaching at least 1.5 mm past its boundary; for scale,
  this region's own faceting would show 0.02469 mm against a perfectly circular
  feature` — against `…, reaching at least 0.02468 mm …` for the faceting case,
  where the depth and the floor all but coincide. It states the two numbers and
  **draws no conclusion**. `depth <= floor` licenses "the region's own faceting
  could account for this", never "it did": measured, a rib genuinely 1.5 mm in
  reads as discretisation once a short region caps the search, and the floor
  can exceed the entire depth — 134x at a Ø40.951 declaration against the Ø41
  fixture bore.
  **Posed as an erosion, which is not what the issue suggested.** #207 asks for
  "the largest distance any intruding vertex sits inside the region boundary",
  and that understates: depth is a min of linear functions, so it is concave,
  and a concave function's maximum over a polytope is generally interior —
  measured **1.2798 mm against a rib built at exactly 1.500**, because the
  deepest point of the rib's inner face is the middle of that face, which is a
  vertex of nothing. The intersection is non-convex in general, so there is no
  vertex guarantee to fall back on either.
  `sup{ r : the part still meets the region eroded by r }` has neither problem
  and needs no new backend capability: `expand(-r)` is already the uniform
  inward offset for both region kinds — a cylinder's flats are TANGENT to the
  declared circle, so `d - 2r` moves every side plane inward by exactly `r` —
  and `intersect_volume` is the primitive the check already runs. Measured
  1.499999 on the same rib. The cost is a bisection of booleans paid only on a
  failing region clause: 4 `intersect_volume` calls on a passing check against
  up to 28 on a failing one, measured 0.073 s on the mesh tier and 3.3 s on
  OCCT.
  **The floor it is read against is derived, not chosen.** #207 attributes the
  noise to the bore's faceting (~0.006 mm at `$fn=128`); it is really the
  REGION's own faceting. The region polygon circumscribes the declared circle,
  and `expand(-t)` moves its corners by `t·sec(pi/n)` rather than by `t`, so
  they clear that circle at the SAGITTA `r·(1 - cos(pi/n))` — 0.024693 mm at
  the default 64 segments, against 0.024684 measured, and four times the bore's
  own term. Not the radial excess `r·(sec(pi/n) - 1)`, which is the distance
  the corners stand proud of the circle but not the depth an erosion measures;
  the two differ by 8.2% at 8 segments, where the measurement is 1.560399
  against a sagitta of 1.560470 and an excess of 1.689040.
  **How that term and the modelled feature's own combine is a matter of PHASE**,
  so the floor is a scale and never a share: `region term <= depth <= region
  term + feature term`, bounding the true depth, of which the reported number
  is a lower bound and so sits a little under. Against a `$fn=128` bore the
  depth sits at the bottom of that bracket at 64 region segments (the corners
  land on the bore's vertices) and at 0.9994 of the top at 128 (facet
  midpoints). It is not even monotone in `segments` — 0.024684, 0.012341,
  0.006176, 0.006856, 0.006176 at 64 through 512 — and raising `segments` does
  not make a nominal bore pass: the depth tends to the feature's own sagitta
  rather than to zero. What passes is a region whose corners clear the modelled
  surface, `(d_r/2)·sec(pi/n) < (d_f/2)·cos(pi/$fn)`, which for the Ø41
  `$fn=128` bore is `d_r < 40.938`. That is the worst-phase bound rather than
  the boundary itself (40.9506 at 64 segments) — a rule that always works. What
  never works is the inscribed diameter, 40.98765, the natural reading of
  "strictly inside the modelled feature", which fails at every segment count
  tried. `SPEC-contract.md` §4.4 carries the table, the bracket and the
  inequality.
  The numbers land in a new `checks[].intrusion` field. `min_depth_mm` is a
  **lower bound and is named as one**: the search stops when the eroded
  intersection falls below `detected_above_mm3`, which is small rather than
  empty, so the true depth lies above it — measured on exact AABB arithmetic,
  4.995 reported against a true 5.0, an error 8400x the search interval. Where
  the search returns the deepest value a region of that shape can yield at all,
  `depth_limited_by_region` says so and the comparison is withheld — compared
  against the region's own search ceiling, since a fixed slack (fractional or
  absolute) makes the flag a discontinuous function of the DECLARATION: an
  8x8x8 mm keep-out buried in solid material read as a partial interference
  while 8x8x7.99, the same total breach, read as a complete one. A buried
  region sits under ONE search interval short of its ceiling while a genuine
  partial intrusion does not, which is what the slack is. Below four halvings
  neither number means anything and the field is omitted entirely: measured, a
  region 3e-6 mm thick and breached to a THIRD of its depth claimed "the whole
  depth of the region". Diagnostic rather than adjudicated, so it is its own
  field rather than part of `measurement`, which carries one unit — and so it
  does **not** discharge `POST-V0.md` §4's outstanding obligation to exercise
  the `approximate` machinery on a real adjudicated interval. Additive;
  `SCHEMA_VERSION` does not move. `keep_in` carries none: its failure is a
  deficit of material, not a breach.

### Changed

- **"Absent means complete — read it with `.get`", where the field is defined
  and where an agent is told to read it** (#302, epic #305).
  `AGENT-CONTRACT.md` lists `part.source_closure.partial` among four things to
  confirm before believing a green run, and carried no absence caveat — while
  the neighbouring bullet four lines down carries one for `imports`. On a clean
  OpenSCAD run there is no `partial` key: the runner writes it only inside
  `if unseen:`. The Python tier seeds `unseen` unconditionally
  (`native_reads`), so the field is always present and always `true` there, and
  it is emitted as `false` nowhere in the tool. **Absence is the only encoding
  of "complete", and it exists on one tier only** — so an agent that learned
  the field on a build123d part is exactly the reader who writes the
  bracket-index read and gets a `KeyError` on the first OpenSCAD part it meets.
  The same sentence is now in `SPEC-report.md` §8.3's `partial` bullet, where
  the field is defined; the omission was previously stated once, 235 lines
  later, inside a subsection about pre-0.7.5 reports.

- **`SPEC-report` specifies the `measure` payload's body** (#296, epic #305).
  `measurements`, `unavailable` and `refused` — the only part of that payload
  carrying information, 9 and 5 and 3 entries on a real run — appeared nowhere
  in `docs/` or `README.md`. The Scope paragraph described the payload as the
  identity prefix "followed by `geometry`", which is where it stops being
  true. A new §7.3 states the three blocks and the property that makes the
  shape worth having: **every name the verb asks about lands in exactly one of
  them**, so a name missing from all three is a silence about a quantity the
  tool asked for. That claim is now executed by a test over a sound part and a
  broken one on the same tier, where `refused` grows, `measurements` shrinks
  and the union may not move.
  **Two of the three are omitted when empty, and the section says so**, because
  the first draft did not and would have reproduced for `measure` the exact
  defect the `partial` fix below closes. `refused` is absent on a part that
  defeated nothing; `unavailable` is absent on a tier that answers everything
  asked — which is the whole OCCT tier, whose capability set covers all
  fourteen names the verb asks, so a build123d payload's top level is exactly
  `schema_version, payload, tool, part, engine, params, geometry,
  measurements`. A consumer MUST read both with a default, and the test that
  pins the partition now has a build123d arm, the property being
  tier-independent while the section had been written from mesh-tier runs
  alone.
  **All three are optional, and the section is scoped to the run that
  measured.** The first repair asserted `measurements` was always present,
  which reproduced the same defect one field over: `measure`'s failure payload
  carries none of the three, in both failure modes. §7.3 now opens by saying it
  describes a run that measured and that a failed one takes Scope's failure
  shape, tellable apart by `error`. The eight-key top level is likewise stated
  as the **minimal** shape and explicitly not a key set to validate against —
  `--out` adds `artifact` and a two-solid part adds `refused`, both reachable
  on that same tier, both now pinned by the test rather than left to the
  sentence.
  The issue said `unavailable` was sorted. It is not, and the spec says what
  it is: the fixed order the verb asks the quantities in, which is stable
  between runs and is not alphabetical.
  **`SPEC-contract` §7 said `measure` "emits nothing that would be
  `unsupported`"** and that on a mesh `topology_counts` "is simply absent
  rather than present-and-wrong" — while the shipped skill routes contract
  authors to that very section, and `topology_counts` is right there in
  `unavailable` on every mesh-tier run. The sentence dates from before the
  two silences existed. It now says what the verb does instead: what it could
  not answer it NAMES, in `refused` when the part defeated the measurement and
  in `unavailable` when the tier cannot answer it at all — because an omission
  reads as "this part has no topology to speak of" to exactly the author the
  verb exists to serve.

- **`SPEC-contract` states the two geometry conventions that a wrong guess
  passes on** (#283, epic #305). §4.2's normative prose reached five of its
  ten rows, across three sites — `builds` and `empty` in the section body,
  `topology` in §4.2.2, `volume` and `area`'s bound form in §4.2.1 — and the
  measuring kinds an author reaches for first were not among them. `envelope`
  had no definition anywhere: the generated vocabulary table, the §1 code
  sample and two category lists, and nothing saying what the number is. §4.4
  named
  `region.cylinder(d=, h=, at=, axis=, segments=)` without ever saying where
  `at` sits. Misreading either produces a **passing** run about a claim nobody
  made.
  **A new §4.2.3 says what the seven both-tier v0 measurements mean**, starting
  with `envelope`: the axis-aligned bounding box's **extents**, per axis of the
  model's own frame, taken over the whole part, translation-invariant, with a
  bare scalar broadcasting to all three axes and a wrong-length tuple a
  `ContractError` rather than a partial claim. The trap it exists for is that
  the same API spells min/max the other way one section down —
  `region.box(min=, max=)` takes **corners** — and the corner reading passes
  silently: measured, a 40 × 30 × 6 mm plate at `(100, 200, 300)` declared
  `p.envelope(max=(140, 230, 306))` from its far corner passes, and the
  identical declaration passes again against a part 120 mm wide. **A test on
  each tier pins the invariance that trap rests on** — one size measured at two
  positions. Both tiers, because §4.2.3 is about the measurements both carry
  and states the invariance without qualifying it.
  Neither file had measured a box at more than one position, which cannot
  separate an extent from a quantity that merely coincides with it at the
  origin. Substituting `2.0 * max_corner` for the extents on a tier is correct
  for every origin-centred fixture and wrong for a displaced one: on the mesh
  tier that tripped 12 tests, and the only backend-level bbox assertion among
  them was the new one; the same substitution on the OCCT tier fails the OCCT
  copy while `test_closed_form_measurements` beside it still passes.
  A third test pins the other half of the same sentence, that the box is
  axis-aligned rather than FITTED. A 20 mm cube rotated 45° about z measures
  `(28.284271, 28.284271, 20.0)` — the space it occupies, not its size — and
  trimesh's fitted `bounding_box_oriented.primitive.extents` returns
  `(20, 20, 20)` for it. That is the assertion that breaks on the PROPERTY.
  Two other mesh assertions break under the same substitution but on axis
  ORDER, because the fitted extents come back ASCENDING rather than in
  model-frame x/y/z — `(30, 20, 10)` reads `(10, 20, 30)` and `(100, 50, 2)`
  reads `(2, 50, 100)` — and neither says which property moved. Watch the
  attribute: `bounding_box_oriented.extents` is the AABB *of* the fitted box
  and agrees with the plain AABB, so only `.primitive.extents` measures the
  fit.
  The other six kinds get the same paragraph, each behind a measured number — a
  20 mm cube with a 10 mm cube void is `solid_count 1`, `cavities 1`,
  `genus 0`, `volume 7000.0` and `area 3000.0`, and the same cube bored through
  is `genus 1` where the blind bore is `genus 0`. `genus` states the *reason*
  it is refused rather than one instance of it — the Euler characteristic is a
  number about one closed body — and then states, per tier, what is actually
  shipped: a multi-solid part is `unsupported` on both, a wholly open surface
  likewise, the mesh tier testing closedness directly and the OCCT tier because
  an open shell bounds no solid. **A whole CLASS of configurations escapes that,
  and it is a defect rather than a convention — now tracked as #334**: on the
  OCCT tier the guard counts solids and never tests closedness, so any body
  that is not itself a solid rides along beside one without moving the count.
  Measured on a 20 mm cube bored through, honestly genus 1: beside a disjoint
  face, a stray edge or a lone vertex it reports `genus 0` flagged `exact`.
  **`watertight` catches only part of that** — `false` beside the face and the
  edge, but a vertex adds no edges, so manifoldness is unmoved and a contract
  declaring `genus(0)`, `watertight()`, `solid_count(1)` and `cavities(0)`
  reports `PASS: 5 pass` and exits 0 on a part with a through-hole. The mesh
  tier goes wrong on none of the three. The spec says all of this rather than
  naming a mitigation that does not hold, and #334 carries the note that a fix
  built on manifoldness alone would look like it worked. Found by this PR's own
  review over two rounds: the first caught a sentence that was false on one
  tier, the second caught the replacement recommending a mitigation that does
  not cover the class the sentence describes.
  **§4.4 now states that `at` is the centre of the base face**, not the
  centroid, and `region.cylinder`'s *function* docstring — the one an author
  reaches through `help()`, as against the class docstring that has said it all
  along — says so too. Measured on `examples/stepper-bracket`, displacing the
  shipped `pilot-boss-clearance` region by ±h/2 along its own axis leaves both
  `ok pilot-boss-clearance` and `PASS: 10 pass` unchanged, in both directions:
  a region that has drifted off its feature is still a region, so neither half
  of the paired keep-out claim is a guard against the misreading.

- **`--out` says where it writes when nobody tells it where to write** (#277,
  epic #305). With the flag absent, every verb that takes one resolves to
  `<contract dir>/outputs/<part-slug>` — beside the **contract**, not in the
  working directory, so the same command run from two places writes to one
  place. Nothing had said so: `check --help` and `measure --help` described the
  DIR layout without naming the default, `SPEC-report.md` declared the question
  "out of scope here", `AGENT-CONTRACT.md` called it "the deterministic path"
  without defining it, and **`render --out` carried no help at all** — the only
  `--out` in the parser without any, and the one flag where the #187 mistake
  (pass a filename, get a directory of that name) had no text in front of it.
  The three verbs are documented separately because they differ, though not
  where a first draft of this entry said: on the mesh tier all three write
  `<source stem>.stl` into that directory, and what distinguishes `measure` is
  that it writes *only* the artifact and no report, `check` adding
  `report.json` and `render` adding `render.json` plus `renders/`. The artifact
  appears **only on a tier that builds a file** — the OCCT tier, which covers
  both build123d and CadQuery, builds in memory and writes no artifact at all.
  There `check` and `render` still create the directory for their report;
  `measure`, having no report to put in it, creates not even that. Two earlier
  drafts got this wrong, each in its own direction: the first generalised the
  mesh tier's behaviour across every tier within `measure`, the second
  generalised `measure`'s behaviour across every verb on the OCCT tier. `vdiff`
  is anchored to the run being compared rather than to a contract, defaulting
  to `vdiff` beside `new`: inside it when `new` is a directory, in its parent
  when `new` is a file. The three MCP docstrings gain a sentence each, that
  boundary showing a caller a tool list and nothing else. The help strings are
  interpolated from one constant rather than repeated, so there is no second
  copy to drift.

- **`empty()` means no positive-volume interference** — not "the parts do not
  touch", and not "there is clearance" (#270, epic #305). The check is
  unreleased, so this is its introduced meaning rather than a change to one.
  Measured on all three kernels partspec drives: OpenSCAD's CGAL backend keeps
  a zero-thickness contact patch and `empty` fails on it; the OCCT tier always
  discards it; and **manifold cannot be predicted at all** — measured,
  **there are pairs of solids** whose intersection answers differently when the
  intersection's two children are written in the other order, identical geometry
  either way. The flip is deterministic across runs, so it tracks floating-point
  incidentals of evaluation rather than noise — and no property of the
  arrangement can predict it, since a syntactic reordering changes the answer.
  Measured across eleven arrangements, CGAL never varies. `produced_nothing`
  is set or not with nothing to say which case
  produced it. CGAL is the predictable one, not the correct one.
  The sharp end of that: **`empty` FAILS on a part whose interference is exactly
  zero, wherever the kernel keeps the sheet** — on CGAL that is every face
  contact, the ordinary case, not an exotic one. The touching pair builds
  geometry so `empty` fails, while `volume(max=0.0)` on the identical part
  passes. And in the other direction **every kernel has a floor** beneath which
  a *real* interference is discarded and `empty` passes — measured, OCCT at an
  overlap depth of ~6e-7 mm (constant, though the volume lost at it scales with
  the face: 1.5e-7 mm3 across 0.5 mm, 2.2e-3 mm3 across 60 mm), and on
  OpenSCAD ~1.9e-6 mm (CGAL) and ~2.4e-7 mm near the origin (manifold) for one
  specific probe — an axis-aligned square-section pin.
  **Those OpenSCAD figures do not generalise, and #315 is the record of finding
  that out.** The floor is a property of the arrangement rather than of the
  kernel — rotation moves it, making the interference a body-to-body overlap
  moves it by orders, and whether it coarsens with distance is
  construction-dependent (manifold's square-pin floor by 8× out to ten metres,
  its rotated-pin floor not at all; CGAL's in no construction tried).
  **Four successive drafts of this entry each published a bound the next
  measurement falsified** — a formula fitted to nine same-shaped samples; a
  body-overlap figure measured on an overlap thin on one axis and written
  about the case thin on two; a ~1.9e-6 mm plateau a triangular pin exceeds;
  and a range a sphere exceeds. Three came from bisections over ranges whose
  monotonicity had never been checked — and the function is not monotone, so
  "the floor" is not always a well-defined number. **No bound is quoted now.**
  Every floor anyone measured was sub-physical by many orders, and that
  conclusion never depended on which was largest.
  Sub-physical for real parts either way, and it is the one
  direction where a pass is weaker than it reads — so `empty` is now specified
  as "no positive-volume interference **the kernel can represent**", the same
  discipline §4.11 applies to `min_wall`. It is not fixable by wording — the
  check adjudicates on whether the
  engine produced anything, which coincides with the meaning only where the
  kernel refuses to represent a contact — and it is one more reason to prefer
  the grown-part pattern, which never puts a kernel in that position.
  So the ambiguity is a property of the question, not a gap to close, and the
  fix is to say what the check does claim: a passing `empty` says the
  intersection encloses no volume **the kernel can represent**. True, useful,
  and narrower than "separated".
  **To assert a clearance, state the number and let a violation have volume**:
  intersect against a part grown by the clearance rather than against the part
  itself. A violation with any margin encloses volume rather than a sheet,
  so every kernel agrees down to its own floor, and
  the bound sits in the contract where a reviewer can see it. `SPEC-contract.md`
  §4.12 carries the meaning, the kernel table and the pattern, and
  `skills/contract-authoring/SKILL.md` — the surface an authoring agent reads
  first — stops teaching the retired three-outcome model, whose middle row was
  CGAL-only and whose last row said the case was "not yet expressible" three
  releases after `p.empty()` shipped (#281).
  **partspec does not select a backend to make this answerable.** Pinning
  `--backend cgal` for `empty` probes was considered and refused: it addresses
  only OpenSCAD, leaving the OCCT tier answering differently — the tier
  divergence §4.12 promises not to have — and it would have partspec choosing a
  geometry kernel, which F13 says is part of the part. Which kernel ran is
  recorded, never chosen.
  The bare form is **not** refused; it is a valid weaker claim. `partspec lint`
  flags it advisorily instead — see below.

- **`source_closure` attributes imports to the target whose model reaches
  them** (#216, epic #229). `imports` is read from `sys.modules`, which is
  process-global, so a Python target behind another in one batch inherits every
  library the earlier one loaded — measured, the same build123d cube records 38
  imports alone and 44 behind a CadQuery target, `cadquery` among them. v0.7.5
  qualified that with `preloaded`, which states the **inability**; this settles
  the part of it the object graph can settle.
  `reached` names the entries of `imports` this target's **own modules provably
  reach**, walked from the model and the helpers beside it. `diff` subtracts it
  from the unattributable set, which closes a real under-report: a follower
  whose model begins importing a library the leader also loads had the entry on
  one side only *and* preloaded, so a genuine new build input was reported as a
  non-event.
  **One-directional, and that is the safety argument.** It proves reach and
  cannot disprove it — `from mylib import WALL_THICKNESS` binds a float, a float
  has no `__module__`, and the edge does not exist in the object graph at all,
  while `mylib` supplies a dimension. So absence means *not proven reached*,
  never *proven unreached*: a consumer may attribute an entry with it and MUST
  NOT dismiss one. Every report without the field — all of them until now, and
  every OpenSCAD one — is read as proving nothing, which is what those readers
  already did.
  Measured end to end on the batch #216 was filed against: 44 imports, all 44
  `preloaded`, **38 `reached` and `cadquery` not among them**; the CadQuery
  target reaches `cadquery` and not `build123d`, and both reach the shared
  `cadquery-ocp`, which is the semantic a `sys.modules` delta cannot express.
  Two things measurement changed on the way. Adding a reached package's loaded
  **submodules** cost 4005 ms against 42 ms — the membership scan is quadratic
  in `sys.modules` — and changed the answer not at all, so it is not done. And
  a walk from a model **imported into `__main__`** reaches essentially
  everything, because `IPython.core.completer` holds a reference to `__main__`
  and `__main__` holds every top-level import; partspec is unaffected only
  because `pycad` execs a model under a private name rather than importing it,
  and that is now written down so nobody re-derives it from a harness.

- **The OpenSCAD closure asks the engine what it read instead of guessing**
  (#226, epic #229). `Closure.reads_external_data` was a bool by deliberate
  design, on the stated ground that *"the path may be computed at render time,
  so no static reader can"* resolve it. That is true **statically, and only
  statically**: OpenSCAD takes `-d` and writes the resolved input set. Measured
  on 2021.01 against one model doing all three at once — an `include`, a
  `surface(file = ...)`, and a **computed** `import(names[0])`, which is the
  precise case the bool exists to admit defeat on — the dependency file names
  every one of them, absolute. `render()` now passes `-d`, and
  `source_closure.engine_inputs` carries what came back.
  The consequence is the one the epic was filed for: a model that reads
  external data was **permanently `partial`**, so `diff` was permanently
  indeterminate on it — the complaint #190 was filed for, still live on the
  other engine. With a `complete` engine report the gap is closed by evidence,
  `external_data_reads` leaves `unseen`, and the comparison becomes conclusive.
  **The data files are hashed into `digest`, not merely listed**: naming a file
  without hashing it would claim a coverage the digest does not have — edit the
  STL and a listing-only closure still answers `identical`.
  **Three states, and `absent` never reads as `complete`.** Absence of a
  dependency file means *unknown*, not *nothing was read*; a render that failed
  after writing one reports a floor rather than the set. Only `complete` may
  close the gap. **Which failures land in which state is engine-dependent** and
  a consumer must not infer a cause from it: 2021.01 writes no dependency file
  for a syntax error and the 2026.08.01 snapshot writes one anyway, so the same
  broken model is `absent` on one engine and `partial` on the other. That is
  F13, and this shipped a test asserting the 2021.01 answer as universal — the
  two-version matrix caught it, review did not.
  **It does not supersede the static walk**, and this contradicts part of the
  issue: a **missing** `include` is not listed in the dependency file at all —
  it records what was successfully *opened*, never what was *requested* — so
  `unresolved` stays the only evidence an include was asked for, and
  `include_closure` is still the only one that answers before a render.
  Two defects found while building it, both by the suite rather than by review.
  The first cut searched the whole of stderr for `-d` when deciding whether an
  engine had rejected the flag — and an OpenSCAD rejection prints a `Usage:`
  dump whose line 46 reads `-d [ --d ] arg  deps_file …`, so **every** rejected
  option matched and silently disabled depfiles for the rest of the process;
  `_is_unknown_option`'s own docstring already said "one line, not a window",
  and the rule is now pinned one field over. The second was drift: `check`
  gained `engine_inputs` while `measure` and `render` did not, which is #73's
  failure exactly, caught by the pinned identity test that exists for it — and
  the first fix for it covered only `render`'s success branch, so a headless
  box, which is the only kind CI has, still disagreed.

- **`SPEC-contract.md` §10.1 narrows the tolerancing exclusion rather than
  keeping or lifting it** (#246). The policy read *"out of scope: reproducing
  any standard's text, figures, or tolerancing tables"* — a blanket that also
  excluded the one half of thread data agents measurably duplicate: all three
  fleet-01 arm-C replicates hand-built 6g/6H for M3 and M8 before they could
  assert a limit, and none of them needed the pitch series to do it.
  The exclusion now turns on **what can be checked, not on how big the table
  is.** Tolerance *grades* and *fundamental deviations* are in scope where the
  standard states them as a formula and the test suite executes that formula
  against every shipped value — the deviation #246 records for class g,
  `es(g) = −(15 + 11P)` µm, is verifiable by construction in a way that no
  transcribed limit is, and a stronger guarantee than any boundary dimension in
  `partspec.refs` gets, since nothing arithmetically validates a bearing's
  22 mm. **Limits of size stay out.** A limit is a *fit*, and a wrong digit in a
  fit is a part that does not assemble under a citation saying the standard
  blessed it — worse than no data, because the reader stops checking. The author
  derives the limit and owns it (§10 rule 2), or a fragment derives it and
  states the derivation in the citation's `note` (§11 rule 3).
  **No numbers ship with this ruling.** `iso_metric_thread.py`'s bar is that
  every value is checked against the primary documents, and that module's own
  docstring records what a draft written from memory costs — three defective
  rows, plus a retracted claim about the prior art. The grade formulae are
  sourced nowhere in this repo, so they are #260 with the documents open, not a
  side effect of a policy PR.

### Fixed

- **OCCT `volume`, `area` and `center_of_mass` measure the material, not the
  shape** (#344, #347). All three read a build123d property off the whole shape,
  and none of those properties is about material. On a 20 mm cube bored Ø6
  through — honestly 7434.51 mm³ — a `Shell` over the solid's own faces read
  **14869.03**, exactly double; a closed 10 mm shell standing 100 mm away read
  **8434.51** and dragged the centroid to **x = 11.856 mm** from −3.8e−16; and
  the same solid **two `Compound(children=[...])` calls deep** — an assembly
  grouping a sub-assembly — read **0.0**. (Counted in calls; `occt.py` and
  `SPEC-backend.md` §4 count the same cliff as TopoDS compound level 3,
  which is the same shape: `Box(...)` is already a compound over its solid,
  so the two counts differ by one.) Every one was
  flagged `exact`, on a shape reporting `solid_count 1`, `watertight true` and
  `cavities 0`. On the shell-over-its-own-faces shape and the nested one,
  none of the primitives beside them moved: `solid_count`, `watertight`,
  `is_valid`, `cavities`, `bbox` and `topology_counts` all read the honest
  values. (`genus` refuses the shell shape and `step_roundtrip` fails it —
  `SPEC-backend` §4.) (Not a blanket claim: the stray standing 100 mm away is a
  separate body, so `bbox` and `topology_counts` do move for it. `SPEC-backend`
  §4 states which primitives name which shape.) All three now sum over
  `a.solids()`.
  **`area` keeps its fallback where there is no solid**: a naive sum reports a
  closed box shell as `0.0` exact, which is the same defect in a new place, and
  `area` is deliberately defined for a face and a shell as much as for a solid.
  **`step_roundtrip` read the same collapsed property on both sides** and
  reported a total volume degradation on an exchange that preserved the part
  exactly — the one member of this class that moved a verdict.

- **A rotation the engine dropped no longer reaches a measurement** (#333, epic
  #305). `o = undef; rotate(o) cube(5);` exports a clean, watertight,
  single-solid 12-facet cube standing at **identity** — the rotation is simply
  gone — and `check` over `watertight()` + `solid_count(1)` reported
  `PASS: 3 pass` at exit 0 on both pinned engines. The same damage as a
  dimension silently defaulting, and #329's guard could not see it because
  OpenSCAD words this one `Problem converting rotate(a=undef) parameter`, not
  `Unable to convert`. It is read now: the same case is `ERROR: 3 skipped` at
  exit 4 on 2021.01 and on 2026.08.01, quoting the engine's own line.
  Measured under both binaries and character-identical on each, all three
  templates fired from a source: `rotate(o)` →
  `Problem converting rotate(a=undef) parameter`, `rotate([o,0,0])` →
  `Problem converting rotate(a=[undef, 0, 0]) parameter`,
  `rotate(a=o, v=[0,0,o])` →
  `Problem converting rotate(a=undef, v=[0, 0, undef]) parameter`, and
  `rotate(a=45, v="z")` → `Problem converting rotate(..., v="z") parameter`.
  **The line does not always mean a default went in, and it has a measured
  remainder — this is `FAILURE-MODES.md` entry 9a's trade in a second place,
  and it is written down there as entry 9b.**
  It means the engine could not use the `rotate` parameters *as written*, and
  what that does to the mesh differs by shape. Measured on both engines, every
  byte comparison `cmp -s` against the correct source named:
  `rotate(o)` and `rotate([o,0,0])` lose the rotation and stand at identity —
  the wrong part, and the reason #333 exists. But `rotate() cube([10,5,2])` is
  identity because identity is what a no-op rotate is *for*, byte-identical to
  the bare cube; `rotate(a=45, v="z") cube(5)` substitutes the **default axis**
  and really is rotated 45° about Z (bbox `(-3.536,0,0)..(3.536,7.071,5)`),
  byte-identical to `rotate(a=45, v=[0,0,1]) cube(5)`; and
  `rotate([90,0,0,0]) cube([10,5,2])` substitutes **nothing at all** —
  2021.01's `src/transform.cc` reads
  `default: ok &= false; /* fallthrough */ case 3:`, so an over-long vector
  still has its first three components read and applied — byte-identical to
  `rotate([90,0,0]) cube([10,5,2])`. All three of those went exit 0 on `main`
  and are exit 4 here. **The refusal stands anyway**, on entry 9's reasoning:
  an over-long rotate vector, a string where an axis belongs and an angle that
  never arrived are bugs in the *source*, one character separates them from the
  correct spelling, and the marker cannot tell which of the four situations it
  is in. `tests/test_openscad_engine.py::test_the_rotate_marker_refuses_a_part_whose_mesh_is_byte_perfect`
  **executes** that cost — asserting both the refusal and the byte identity —
  so it cannot be quietly lost the way it was nearly shipped as "not a false
  positive". One consequence is filed rather than fixed here: the report
  sentence `runner.py` prints for this marker — "built a default in place of
  it" — asserts a mechanism the over-long vector never took (#360).
  **The marker stops at `rotate(`, and that is a measured choice rather than a
  minimal one.** `Unable to convert` turned out to have a context where it is
  true and says nothing about the mesh — the GUI camera — so `Problem
  converting` was inventoried the same way instead of assumed clean. Read out
  of each binary with `strings`, both carry exactly **four** templates with
  that head and the two lists are identical: the three `rotate` templates
  (2021.01 `src/transform.cc` 152–177; master `src/core/TransformNode.cc`
  130–163), and `Problem converting this number: %1$s` from
  `boost_numeric_cast` (2021.01 `src/boost-utils.h` 41; master
  `src/utils/boost-utils.h` 38), whose only caller in either version is
  `rands()`'s result count (2021.01 `src/func.cc` 134; master
  `src/core/builtin_functions.cc` 184). That fourth one is not about geometry
  at all, and it cannot occur beside an exported mesh: the cast fails only on
  positive overflow, after which the engine sets the count to `SIZE_MAX` and
  dies building it. Measured under a 2 GB address-space cap on both engines
  from `r = rands(0, 1, 1e30); cube([40,30,6]);` — `std::bad_alloc` on 2021.01,
  `std::length_error` on 2026.08.01, exit 134 and no STL either way. So it gets
  no `_NON_GEOMETRY_CONVERSIONS` entry, which is for lines that are true
  *beside* an exported mesh; the marker is narrowed instead, separating the
  four by the engine's own grammar exactly as the `[` split does, and keeping a
  crash from being reported as a defaulted dimension. It is pinned as the
  negative in
  `test_the_substituted_value_markers_match_both_engine_spellings`, where the
  two rotate lines used to sit.
  **Not every mis-specified rotation is narrated**, and that is #332's shape
  rather than a gap here: `rotate(a=90, v=undef)` is **silent on both engines**
  and still exits 0. `undef` is not "defined", so the engine reads it as "no
  axis given" and applies its **default** axis — the part is rotated 90° about
  Z, byte-identical to both `rotate(a=90, v=[0,0,1])` and `rotate(90)`. It is
  **not** unrotated; an earlier draft of this entry said so, and a reader told
  that hunts the wrong symptom. There is no stderr line for a guard to key on
  either way.

- **A `%`-only diagnostic is written down instead of being a silent trade**
  (#336, epic #305). `%` marks geometry as *background*: OpenSCAD **evaluates**
  the subtree and excludes it from the render and the export. Its diagnostics
  still reach stderr, stderr does not carry the modifier, and partspec's
  success-path guard therefore refuses a part whose only fault is in geometry
  nobody exported. Re-measured on both pinned engines: `cube([40,30,6]);
  %translate([undef,0,0]) cube(2);` exports 684 bytes that `cmp -s` finds
  **byte-identical** to the same source with the `%` line deleted, and `check`
  over `watertight()` + `solid_count(1)` gives `ERROR: 3 skipped` at exit 4 on
  both. **The refusal stands** — an `undef` inside a `%` subtree is a bug in
  the source whatever it costs today, the modifier is one character so
  scaffolding routinely becomes the part, and the alternative (correlating
  stderr line numbers against the `%` nodes of a `.csg` export) buys silence on
  a real defect at the price of a second parser between the engine and the
  verdict. What changes is that an agent hitting exit 4 on a byte-perfect mesh
  can now reach that conclusion from the documents: `FAILURE-MODES.md` gains
  entry **9a** — the first half of a new entry whose second half (**9b**) is
  the `rotate()` remainder above — and `AGENT-CONTRACT.md` §2.3's conversion
  bullet says what the quoted line does *not* tell you.
  The three modifiers were measured, not assumed, and only one has this
  property: `*` (disable) is never evaluated, so it emits nothing and is the
  modifier that is free; `#` (highlight) **is** exported, so its warnings are
  about the mesh and its refusal is a catch; `%` alone is evaluated and not
  exported. All three are executed in
  `tests/test_docs.py::test_the_background_modifier_entry_is_reproducible_here`,
  byte identity included, so entry 9a is a claim that runs rather than one that
  is asserted.

- **`--pin` names the claims it rewrote** (#294). It read the previous lock only
  when a target had failed to resolve; on the ordinary path it rewrote a changed
  claim and printed `pinned 1 part(s)`. `AGENT-CONTRACT.md` §4 rests the whole
  guarantee on "the lock is committed, and its diff is the confession in your
  PR" — so the one weakening move partspec computes the diff for was the one it
  discarded. The differences now print on **stderr**, which `--quiet` does not
  suppress, because `--quiet` is the invocation a weakening uses. It stays exit
  0: §4 permits a deliberate re-pin, and the requirement was only that it cannot
  be silent. The lock-shrink guard also fired only when a target failed to
  resolve, so pinning a subset of a multi-part lock silently deleted the rest.

- **A data file the model asked for and did not get no longer reports `pass`**
  (#309, epic #305). `import("missing.stl")` renders as nothing and the engine
  still exits `0` with a well-formed mesh, so `check` measured a part the source
  does not describe and called it green — while `report.json` already named the
  file, under `source_closure.engine_inputs.missing`, and nothing read it.
  Measured identically on 2021.01 and on the 2026.08.01 snapshot. The run is now
  `verdict: "error"`, exit `4`, every check `skipped`, with the console naming
  the file the way #286's refusal does.
  **`unseen` could never have caught this, and the reason is worth stating**:
  `SPEC-report.md` §8.3 emits `external_data_reads` only when
  `engine_inputs.state` is *not* `complete` — "the gap is then closed by evidence
  rather than assumed away" — and here the state **is** `complete`. The engine
  answered in full, and the full answer is that the file is absent, so the one
  field that would have held the verdict below `pass` was empty *because* the
  problem is provable. The depfile list is read directly instead, at the point in
  `runner.py` where the closure is upgraded from it, which covers `import()` and
  `surface()` uniformly without matching two stderr strings that share no
  wording. §6.1 records this as the third way a successful build reaches `error`;
  `build_origin` stays `null`, because whether the path is a typo or a file a
  two-pass workflow has not produced yet is not something partspec can tell.
  **The guard is narrowed to files the export actually depended on**, because the
  depfile records what the engine *resolved*, not what it exported. OpenSCAD
  **evaluates** a `%` subtree and then excludes it from the export, so
  `cube([10,10,10]); %import("mate.stl");` lands `mate.stl` in `missing` while
  exporting byte-identical STLs with and without the file — measured, both
  pinned engines. Refusing that is refusing more than the mathematics requires,
  and it is `FAILURE-MODES.md` entry 9a's class arriving through a second
  channel. stderr cannot tell the two apart — the warning is worded identically
  for a `%`-ed and a plain `import()`, differing only in the line number, which
  is the correlation #336 declined to build — but the `.csg` export keeps the
  modifier beside the filename on both engines, and `csg.py`'s reader already
  drops `%` and `*` subtrees for the same stated reason. So a file named only
  from a dropped subtree is exonerated, one named from both is not, `*` never
  reaches the depfile at all, and `#` stays a catch because its geometry IS
  exported. One extra `.csg` export, measured at 21–31 ms, and only on a run
  that was going to exit `4`: correct runs pay nothing. **Fail closed** — an
  export that will not run, will not parse, or names no literal that resolves
  onto a missing entry keeps the refusal, which matters because the format
  prints string contents raw and `text("say \"hi\"")` is a genuine parse
  failure.
  **Two things the narrowing has to get exactly right, because getting either
  wrong fails OPEN** — it passes a part whose export is provably short, which is
  the failure this guard exists to prevent, and both shipped broken in this
  PR's first cut before review caught them. The `.csg` literal is joined to a
  depfile entry by **resolved path**, not by suffix: the depfile entry is
  `.resolve()`d (so `..` is collapsed and symlinks followed) and the literal is
  rewritten relative to the ENTRY file's directory, so a kept literal carrying
  `../` could not match its own resolved path while a shorter dropped literal
  matched it by accident. Measured on an `import()` inside an included file the
  two engines do not even agree where it resolves — 2021.01 writes
  `"mate.stl"`, the 2026.08.01 snapshot `"lib/mate.stl"` — and each engine's
  literal resolved against the entry's parent reproduces that engine's own
  depfile entry, so the exact test is right on both where a suffix test is
  right on neither. And the export is taken **of the model that was built**,
  with the contract's `-D` values and through the method scratch entry, because
  a modifier can sit behind a parameter: `if (ghost) { %import(f); } else {
  import(f); }` with `ghost=false` adjudicated the default tree and passed a run
  whose mesh was 12 triangles instead of 24.
  `!` (root) is a residual false red in the safe direction, described in
  `FAILURE-MODES.md` 9a: the engine writes only the rooted subtree to the
  `.csg`, so a reference outside it is unaccounted for and refused.
  `measure` and `render` still emit numbers and views on this shape — they are
  guarded for #286's channel, which is a stderr marker, and this one is visible
  only in the depfile. Measured and tracked as #355.

- **`render` no longer writes views of a part the engine hollowed out** (#307,
  epic #305). #286 made `check` and `measure` refuse a build whose stderr says
  the engine could not resolve a name, and left `render` out; it went on writing
  four PNGs at exit `0` of a bare cube whose declared bore is absent. A picture
  is the one output a reader trusts without checking. The refusal is now asked
  inside `render_views`, immediately after the STL render it already performs and
  **before the first view is drawn** — not in the caller, because the four views
  are rendered to a scratch directory and moved into place as a batch, so a guard
  bolted on afterwards leaves four wrong PNGs on disk (measured during #306's
  review). **No view is rendered and an earlier run's four PNGs are
  byte-for-byte untouched** — measured. Not "nothing is written": the STL export
  is how the fault is detected, so it lands in `--out` and replaces the previous
  run's, and the stale `render.json` is removed as it is on every failing render
  (#21). A consumer reads its absence as "this run wrote no payload".
  **`BuildError.origin` gains a third state, `None`.** `render`'s failure payload
  publishes `origin` (#191) and the field was `Literal["environment", "model"]`,
  so this refusal would have shipped the default `"model"` — asserting the DESIGN
  is at fault on the one failure partspec is certain it cannot attribute, which is
  the exact misattribution `origin` exists to prevent. `render.json` carries
  `origin: null` here, matching what `report.build_origin` has always said on
  `check`'s path. Widening the type was not a one-liner for the same reason:
  `runner.py` adjudicated `if origin == "environment": … else: builds fail`, and a
  `None` would have fallen through to the model arm. That branch is now written as
  `!= "model"`, so it fails closed — the only arm that makes a claim about the
  design is the only one that must be reached deliberately.
  **`check --render` was never affected** and is pinned so: `cli.py` gates the
  views on `report.error is None`, so a run #286 already refused never reached the
  render path.

- **`measure` emits `axes` on an empty vector measurement** (#346).
  `SPEC-report.md` §2.1 makes `axes` REQUIRED on vector measurements, and a
  measurement is vector iff `value` is an array — so an empty array is one. The
  payload gated the field on truthiness rather than presence, so a `Box(20,10,5)`
  emitted `bores: {"value": []}` and `blend_radii: {"value": []}` with no `axes`,
  while the same part with two bores carried it. The field's presence tracked the
  *part* rather than the shape, and it went missing on exactly the parts that are
  simplest. `report.py` had been presence-based all along, which is the asymmetry
  that made the gate look accidental. Additive; `schema_version` does not move.

- **`AGENT-CONTRACT`'s measured enumeration of `measure`'s failure payload
  counts the field this release added to it** (#295, #340). §2.4 lists that
  payload's keys as "Measured … exactly `engine`, `error`, `geometry`, `hint`,
  `params`, `part`, `schema_version`, `tool` — in *both* failure modes", which
  an agent reads to learn there is no `origin` to branch on. Adding `payload`
  made it nine, and neither change was wrong alone: #340 measured the payload
  correctly, and #295 extended it additively. **The composition was false and
  no test could see it**, so CI stayed green over a document that had just been
  measured.
  That is #299's class in a second file, and the second time in one wave that a
  hand-maintained list went stale where nothing gated it. The list is corrected
  and now has a gate:
  `tests/test_cli.py::test_the_measure_failure_payload_carries_exactly_these_keys`
  asserts the exact key set in both failure modes — exit 4 from a build that
  failed and exit 64 from a refused `--out` — and §2.4 cites it by name, so the
  next such falsification is a red run rather than a shipped falsehood. The
  test states the shape directly rather than parsing the document, which would
  only prove two copies of one list agree.
  **The same test pins the key ORDER**, which §8 rule 1 makes a MUST and which
  nothing executed on this payload: moving `payload` to sit after `params`
  passed the entire suite. Both assertions stay — §2.4 claims a set, §8 rule 1
  claims an order, and neither implies the other.

- **AGENT-CONTRACT's exit table covers only `check`, and routed the agent into
  the one case it does not cover** (#301, epic #305). §2 opens "Every evaluated
  `check` run", the exit-3 row says to run `measure`, and `measure` has no
  verdict — so a model-origin build failure lands there on exit 4, where the
  table's own exit-4 row says "editing the model on exit 4 is noise", which is
  the opposite of the right response.
  The routing is reachable, measured end to end: a checkless contract over a
  `.scad` with a syntax error gives `check` exit `3`, `verdict: "empty"`,
  `checks[0]` = `("builds", "fail")` — `empty` outranks `fail` per
  `SPEC-report.md` §6.1 — and the prescribed `measure` then exits `4`.
  A new §2.4 covers `measure` and `render`. Both of the issue's own corrections
  were re-measured and hold. `lint` is out of scope: it exits 0 whatever it
  finds and `LINT.md` already says its exit 0 is not this table's exit-0 row.
  And "read `build_origin`" is unimplementable for `measure`: its failure
  payload carries exactly `engine`, `error`, `geometry`, `hint`, `params`,
  `part`, `schema_version`, `tool` — in **both** failure modes, with `origin`
  **absent** rather than null, so it cannot even be read as "unknown". `render`
  does carry one: `"model"` for the broken `.scad`, `"environment"` under
  `PARTSPEC_OPENSCAD=/nope/openscad`.
  So §2.4 says to branch on `render`'s `origin` and to fall back to `error` and
  `hint` on `measure` — and names the states that fit neither branch, since
  narrowing the table could otherwise leave them uncovered. Exit 4 with
  **stdout empty** is two different things, and **stderr is the discriminator**:
  *"the contract is wrong, not the part"* is a contract that raised (§2.3's last
  bullet), while *"this is a partspec failure, not a verdict on the part"* is
  partspec's own failure and an escalation. Measured, `render --out` pointed at
  an existing **file** takes the second branch on a contract that is entirely
  correct — so attributing every empty stdout to the contract would have
  prescribed a repair to a file with nothing wrong in it. The verbs are not
  symmetric there either, and the section says so: the same bad `--out` leaves
  `measure` emitting a payload. Exit 64 still means a malformed invocation.
  It records the asymmetry as a gap rather than a design:
  `check`'s report has carried `build_origin` since #47, `render`'s payload
  gained `origin` in #191, `measure` was given neither, and the two that exist
  do not share a key name. A test pins both payload shapes, so giving `measure`
  the field — the real fix — fails the assertion that tells the agent there is
  none.

- **The MCP surface now tells its agent it is the weaker loop, which
  AGENT-CONTRACT already said it must** (#298, epic #305). That document's §0
  states the MCP tools cannot execute it — no `--expect`, no `--pin`, no
  `--timeout`, no `diff` — and concludes an MCP-driven agent "should be told so
  rather than assumed to be following it". `mcp.py`'s `_INSTRUCTIONS` said none
  of it, and carried no pointer to any partspec document.
  Measured, that gap is total for this consumer:
  `grep -rn "github.com/heibench/partspec" src/` returns **one** hit,
  `cli.py`'s epilog, which an MCP client never sees — it has a tool list and
  nothing else. `_INSTRUCTIONS` now names the four tools as the whole surface,
  says which flags and verbs are CLI-only and that the pin-and-compare remedy
  therefore needs a shell, and gives the documents' URL. It also says which
  tool produces an artifact and which return their payload directly, **scoped
  to the tool it is true of**: only `check` writes a `report.json` and only
  `check` passes `--quiet`, which is not merely unpassed on the other three but
  not a valid flag — `measure ... --quiet` exits 64, unrecognized. A test pins
  that by parsing, since a sentence generalising over a tool list is exactly
  what drifts. The same clause says what `render` *does* leave — `render.json`,
  the view PNGs its payload names by path, the exported artifact on the
  OpenSCAD tier — because `vdiff` consumes exactly those, and a blanket "do not
  look for a file" would have told an agent chaining render into vdiff not to
  seek the input it needs.
  `lint` joins `diff` in §0's gap list: `git log -S` dates that paragraph to
  2026-08-09, one day after `lint` shipped, so it named the gap that existed
  when it was written.
  Two tests, both against the code rather than against the sentence. One pins
  the surface — `tool_names(mcp.py)` is exactly
  `["check", "measure", "render", "vdiff"]`, reusing #331's parser rather than
  writing a second one that could forget `async def`; registering a `lint` tool
  fails it. The other pins that the instructions' URL resolves to a directory
  that exists, so moving `docs/` fails here instead of shipping a dead pointer.

- **`skills/build123d-authoring` had zero inbound links, so every author was
  handed the OpenSCAD rules** (#284, epic #305). Verified before and after:
  `grep -rn "build123d-authoring" --include="*.md" .`, CHANGELOG excluded,
  returned exactly two lines — a rationale string in `docs/LINT.md` and the
  skill's own frontmatter `name:`. Nothing pointed at it. `README.md` says
  "three authoring skills" in prose and linked one; `contract-authoring`, the
  document that routing goes through, sent all source-side work to
  `openscad-authoring`.
  That is not a missing link, it is the wrong rules: the Python engines fail
  by silent **selection** drift and ecosystem breakage where OpenSCAD fails by
  silent geometry loss, so an agent writing build123d was reading advice that
  does not transfer. `contract-authoring` now routes by the source constructor
  the contract declares — `openscad(...)` to one skill, `build123d(...)` or
  `cadquery(...)` to the other, which covers both Python engines. `README.md`
  links all three. `AGENT-CONTRACT.md`'s scope note, which named only
  `SPEC-contract.md`, now says to start at the routing skill and why the two
  differ. And `openscad-authoring` gained the reverse pointer it lacked, since
  its reader is exactly the agent who arrived with the wrong engine.

- **The retrofit path's first command named the model file, and a model file
  fails with the same word twice** (#282, epic #305).
  `skills/contract-authoring/SKILL.md` step 1 of "The retrofit path" said
  `partspec measure model.py:factory`. Both verbs resolve a target that must
  return a `partspec.Part`, so naming the model exits 64 — and a build123d or
  CadQuery model annotated `-> Part` is annotated with **its** library's
  `Part`, which produced *"returned Part, not a Part"*: no way forward, and it
  reads as a tool bug rather than a user error.
  The model gets that far because `target._load` compiles and execs, which
  leaves every annotation a **string** — measured, the `bracket` factory in
  `examples/stepper-bracket/bracket.py` arrives as `'Part'`, and so does every
  shipped contract's, while a normal import of the same contract gives the
  class. So the `hints is Part` half of the discovery test cannot fire under
  `_load` at all, the comparison is purely lexical, and the model is discovered
  as a factory, called, and refused only on what it returned.
  The refusal now LOCATES the returned type — `returned
  build123d.topology.composite.Part, not partspec.Part` — with a second line
  saying to write a contract declaring the model as its source. Where the class
  is defined in the contract file itself, which is the shape #282 filed its
  reproduction on, the locus is that **file**: `_load` synthesises a module
  name embedding `hash()`, so qualifying by module there printed a different
  string every run — `_partspec_contract_691635311308020508.Part`, then
  `..._6872466290535898064.Part`, measured across three processes. A test pins
  the property rather than the sentence, reading the expected module off the
  class: reverting to the old wording fails it, and so does dropping the
  file-name fallback. It lives in `tests/test_cli.py` beside the other
  resolve-failure paths, not in `test_docs.py` — it never reads the document,
  so filing it under "docs held to code" would have claimed a link it does not
  make; §7 carries the pointer to it instead.
  The skill's step 1 and `SPEC-contract.md` §7 both now open the retrofit by
  writing that contract: a `Part` with an id and a source and no checks, which
  is the smallest thing `measure` accepts. Measured on
  `examples/spacer/spacer.scad`, it reads `bbox (40, 30, 6)`,
  `volume 6898.891440076026`, `genus 1` and names five unavailable primitives.
  **Both copies of that block are executed** — the skill's, which an agent
  pastes, and §7's, which carries the normative MUST and which nothing in the
  suite had run.

- **OCCT `genus` measures one closed body, or refuses** (#334). The guard counted
  solids and nothing else, so any body that is *not* a solid rode along beside one
  without moving `len(a.solids())` — and its vertices, edges, faces and wires were
  then summed into the Euler-Poincaré characteristic anyway. Measured on a 20 mm
  cube bored Ø6 through, honestly genus **1**:

  | stray beside the solid | reported | `solid_count` | `watertight` |
  | --- | --- | --- | --- |
  | a disjoint face | `0` exact | 1 | false |
  | a bodiless edge | `0` exact | 1 | false |
  | a lone `Vertex` | `0` exact | 1 | **true** |
  | a `Shell` over the solid's own faces | `2` exact | 1 | **true** |
  | a `Wire` over the solid's own edges | `int(1.5)` exact | 1 | false |

  End to end, a contract declaring `genus(0)`, `watertight()`, `solid_count(1)` and
  `cavities(0)` reported `PASS: 5 pass` at exit 0 on a part with a through-hole; it
  now reports `INCOMPLETE: 4 pass, 1 unsupported` at exit 2.
  **`watertight` could not have been the precondition.** Two of those five leave
  `is_manifold` **true** — a `Vertex` contributes no edge, and a shell over the
  solid's own faces shares them — so a guard built on it would have fixed the sheet
  and the edge and looked like it had fixed the class. The precondition is *one
  solid, nothing else the formula would read*, tested as the five entity counts
  being that solid's own, which is exactly what the formula assumes when it is
  applied. Counted from the topology and not from `a.children`, because the runner
  never sees children: `adopt` rewraps the TopoDS handle, and the stray sheet
  reaches `genus` with `children == ()`.
  **And the solid itself must be closed**, which the count test does not establish:
  `Solid(Shell(box.faces()[1:]))` is one solid carrying nothing beside it, and
  reported `genus 0` on a surface with no genus. Closedness is every edge being
  bounded by exactly two faces — counted as *uses* rather than distinct faces, so
  a seam edge used twice by one face stays closed, and **skipping degenerate
  edges**. `is_manifold` applies the same rule and gets only the second wrong: its
  degeneracy test never fires, so a sphere's 2 pole edges, a cone's 1 and a
  filleted box's 8 each count as unshared and it reads `false` on all three, every
  one of them closed. That, and not the seam, is why it cannot serve here.
  An integrality test on the genus alone would not have done it either: a shell
  missing two opposite faces has an even characteristic and comes out a whole `1`.
  **Two further corruptions clear both of those and are refused as well.** An edge
  used by FOUR faces — one solid of 2000 mm³, no boundary edge anywhere, built by
  sewing two stacked boxes with `SetNonManifoldMode(True)` — reported `genus -1`;
  it is caught by counting uses `!= 2` rather than `< 2`. And a single shell
  holding two disjoint boxes passes every structural test there is, so the last
  guard is arithmetic: the characteristic sums the shells' genera, so a closed
  body cannot produce a negative one, and that shape reported `-1, exact` at
  2000 mm³.
  **Nothing legitimate is newly refused**, measured rather than assumed: eighteen
  single-solid shapes taken before and after — a `BuildPart` part, a compound
  wrapping one solid, a sealed cavity (two shells, both the solid's own), a torus,
  a sphere, a chamfered box, a shelled box, a CadQuery bored plate among them —
  plus this repo's two build123d examples, `block.py` at genus 1 and `bracket.py`
  at genus 5, all answer exactly as before.
  `cavities`, the primitive immediately preceding `genus` in the same file, already
  named this configuration as the shape PR #147 was rewritten to survive; this is
  that guard, where it had never been given. `SPEC-contract.md` §4.2.3 described
  the defect in the present tense and told authors not to trust a `genus` claim
  until this landed; it now describes what ships, including the one member of the
  class where the tiers still disagree on purpose — a stray vertex, which the mesh
  tier answers correctly at genus 1 by counting *referenced* vertices only, and
  which OCCT refuses. `volume` and `area` double on the `Shell` row above and are
  **not** fixed here; that is #344, and #347 is the same primitive reading `0.0`
  on a solid two compounds deep.
  The `cavities` fixture table also gains the comment #337 asks for: its cases
  build their shapes inside a `lambda` because `Compound(children=[...])`
  **reparents**, and a shape handed to a second compound leaves the first holding
  nothing — a row that then goes on reporting green while measuring nothing.

- **A check that stopped being answered is no longer filed as a repair**
  (#325, epic #305). `_SEVERITY` ranks `approximate`, `unsupported` and
  `skipped` below `fail` — right for a verdict, since a run with a skipped
  check is not worse than one with a failing check — and `diff` reused that
  ordering to name a *direction* of change. So every transition into a status
  the tool cannot draw a conclusion from landed in `fixed`. Measured: an
  `envelope` failing at `max=(40,30,4)`, then a `requires` precondition
  breaking so the geometry phase never runs, produced
  `{"change": "fixed", "status": {"old": "fail", "new": "skipped"}}` under
  `different: example-spacer — 2 regressed; 1 fixed`. That check did not get
  better; it stopped being evaluated. It now reads
  `2 regressed (1 not answered); 1 fixed (1 not answered)`, with
  `"answered": {"old": true, "new": false}` on both entries.
  **Keyed on the new status alone**, because whether this report answers the
  check is a fact about this report and where it came from is already in
  `status`. `pass` and `fail` are the two outcomes `Status` calls conclusive;
  the other three are, in its own words, "indeterminate … the tool does not
  know", "cannot evaluate this check … at all", and "not evaluated". Two
  drafts of the issue got this bound wrong by enumerating pairs — the first
  omitting `approximate`, the second admitting only transitions out of
  `fail` — so the code names the conclusive set and the test sweeps all 20
  ordered pairs of distinct statuses with the expectation derived from that
  set rather than listed.
  It follows that `unsupported` → `skipped` is recorded although it was
  answered on neither side, since the headline calls it `fixed` just the same,
  and that `pass` → `skipped` is recorded although it is bucketed `regressed`.
  Both consequences are about the **headline**, so the headline is swept the
  same way the record is — over every ordered pair, the qualifier appearing
  exactly when the entry carries the record, in whichever bucket. Review found
  the first version of this had given the artifact a derived sweep and the
  headline enumerated coverage, every case a `fixed` entry that had been
  `fail`; two mutants lived in the gap and one printed #325's original output
  verbatim.
  **The record rides a status-change entry and only those**, present there
  exactly when the new side is unanswered. It corrects a bucket that names a
  *direction*, and only `regressed` and `fixed` do; where the status held,
  `status` is the single unchanged value a reader can already read. A census
  holds the scoping to evidence, stated with its method so the next reader
  re-checks it instead of re-deriving it: 135 check variants per side — 5
  statuses × 3 claims × 3 measurement values × 3 operand sets — diffed against
  each other is 135² = 18,225 ordered pairs, of which 2,106 hold their status
  at an unanswered one and 0 carry the record. The dimensions are the three
  fields this comparison compares, plus `status`; `phase` is held fixed and is
  deliberately not one of them, since it picks a tolerance and is never itself
  a difference — a grid that makes it a dimension also totals 18,225 and
  answers 1,944, which is the shape of a number that is wrong until its method
  travels with it.
  **An additive field, not a fifth `change` value.** §4's compatibility rule
  covers fields; it says nothing about enum values, and widening a closed
  vocabulary breaks every consumer that switches on it. A console-only
  qualifier was the other tempting shape and is not enough — it would leave
  the artifact still calling the entry `fixed`, which is the complaint.
  `verdict_of` and `_SEVERITY` are untouched.

- **A `param_range` check's value compares exactly, because it is a contract
  parameter and not a measurement** (#335, epic #305). `runner` reads it
  straight from the declared parameters before any engine runs, so it is the
  same kind of number a `requires` operand is — but `diff` gave it the
  adjudication `epsilon`, which is sized for what a *measurement* survives.
  Measured before the fix, end to end: `wall` moving `1.999999 → 1.999998`
  against `min=2.0` flips `pass → fail`, and the entry read
  `{id, kind, change, status}` with no value at all — a parameter crossing its
  own limit, reported with neither number.
  **The key is `phase`, which is where the report records the provenance.**
  `checks[].phase` is REQUIRED and closed (`parameter` | `geometry`), and the
  two parameter-phase kinds — `requires` and `param_range` — both take their
  numbers from the contract's own inputs.
  **Not `exactness`, which looks like the right field and would have broken
  the mesh tier.** `exact` separates a point value from a bounded interval
  (`bounds` is required iff not `exact`) and says nothing about
  reproducibility: measured, `cube([120.3, 80.7, 40.1])` reports
  `exactness: "exact"` beside `[120.30000305175781, 80.69999694824219,
  40.099998474121094]` — ±3.052e-06 of float32 quantisation, absorbed by
  `epsilon(120.3) = 1.303e-05`. `SPEC-backend.md` §5.2 permits that tier to
  collapse the quantisation *because* this epsilon is wider than it, so a
  comparison keyed on `exactness` would withdraw the tolerance that permission
  rests on and report a rebuild of identical geometry as drift. A test pins
  the two apart on one fixture with one field changed.
  **This corrects §3's bound rather than reaching past it.** The rule was
  justified by a conjunction — parameter provenance *and* exact adjudication —
  and `param_range` satisfies only the first. The conjunction was wrong: an
  adjudication tolerance decides a verdict and must forgive what the pipeline
  could have perturbed, while a comparison tolerance suppresses noise, and a
  number read from the declared parameters has none to suppress. A sub-epsilon
  parameter move that changed no status is exactly the drift §1 exists to
  report.
  `parameter` on either side is enough, since exact comparison can only report
  more and "no differences found" is the positive claim; a report recording no
  `phase` keeps the tolerance, because silence is not evidence of provenance.

- **A `diff` entry now carries every delta the comparison computed, whatever
  bucket it landed in** (#330, epic #305). `_check_entry` was a chain of
  returns and each branch returned as soon as it knew its own *name*, one
  delta into a chain of three. So `limit_changed` reported a contract edit
  and discarded the drift it was covering, and `drifted` reported a moved
  measurement and discarded the operands beside it — both computed one line
  earlier, both thrown away rather than merely omitted.
  Measured on the flagship shape, end to end: a `min` bound loosened
  2.0 → 1.0 while the parameter it bounds moved 2.9 → 2.1 in the same edit,
  both sides passing so no status changed. The entry named the bound and not
  the parameter, which tells a reader the bound moved and the part did not —
  and a bound loosened over a value moving toward it is a different event
  from either alone. That is §1's second job (`SPEC-report.md` §7.2) dropped
  on the one entry where the two facts explain each other.
  **The rule is that the bucket names the change and does not decide what the
  entry carries**, which §3 now states once for all four buckets rather than
  as a MUST scoped to status changes. The code says it the same way: the
  deltas are built into one mapping above the branch and spread onto
  whichever entry is returned, so no branch is able to ship a subset of what
  was measured. Three deltas are computed and any may ride any entry —
  `claim`, `value`, `operands` — with one structural consequence that is not
  an exception: a `drifted` entry never carries a `claim`, because a moved
  claim is what would have made it `limit_changed`.
  Filed rather than folded into #326 when it was found, because §3's MUST was
  scoped to status-change entries and genuinely did not reach this bucket —
  so the spec sentence came first and the code followed it.

- **`part.contract` names the factory that was invoked** (#297, epic #305).
  `SPEC-report.md` §7 showed `"contract": "parts/bayonet/spec.py:lock"` and
  §7.1 said normatively that "the contract digest is module-scoped while
  `part.contract` names a symbol" — the whole justification for the
  module-scoped digest. The runner passed the contract path as **both**
  arguments to `_relative`, which always yields the bare basename: never the
  directory, never the `:factory`.
  **Two factories in one module returning parts with the same `id` therefore
  produced byte-identical `part` blocks** — same module-scoped
  `contract_digest`, same source, same closure — and nothing in either
  artifact said which target ran. Measured, before: two `check` runs of
  `same.py:imperial` and `same.py:metric` both wrote
  `"contract": "same.py"` and the same digest; after, `same.py:imperial` and
  `same.py:metric`. The code was wrong and the spec was right about the
  symbol: the collision is a defect whichever document one prefers, and the
  spec's stated reason for the over-firing digest rests on the field naming a
  symbol.
  The spec was wrong about the **path**, and its example is corrected to
  `"spec.py:lock"`: #45 deliberately normalized this field to the contract's
  own directory — the frame `_anchor` already resolves against, so that two
  checkouts of one tree produce byte-identical `part` blocks — and a
  CWD-relative chain is exactly what that closed. §7.1 now states both halves,
  including that a consumer MUST parse the suffix as **optional**: a module with
  one factory needs no name to resolve, and a library caller may name none.
  `tests/test_report.py`'s fixture asserted `parts/p.py:main`, a shape the
  production path cannot emit, so the spec, the dataclass and the suite all
  agreed and only the runner did not — which is why 1,203 tests could not see
  this. The one spec-conformance test reads key names and order and never
  values; a second now executes the documented value through the tool's own
  target parser, where a directory chain and a missing symbol both fail.
  **Compatibility, for consumers rather than for the schema.** The field stays
  a string and the `<module>:<symbol>` form is what `SPEC-report.md` has shown
  since scaffolding `34104ab`, so this brings the code to the schema rather than
  changing the schema, and `schema_version` does not move. But the value
  *shipped* to date was a bare filename, so anything that parsed it as one — a
  consumer splitting on `.py`, or comparing it to `Path(target).name` — now sees
  `spec.py:spacer` where it saw `spec.py`. The tool's own rule, worth copying
  rather than approximating (`target.py`'s `Target.parse`): partition on the
  LAST `:`, and treat the tail as a factory **only if it is an identifier** —
  otherwise the whole string is the module, and the guard is what stops a
  contract filename that contains a colon (`rev2:spec.py`) from being read as
  module `rev2`. Both forms remain well-formed for a reader; what the CLI now
  writes is the suffixed one whenever the target **resolves** and the module
  declares a factory — the pre-resolution placeholder echoes the argument as
  typed and carries no suffix (#343, below).
  **The comparator half is #343, below.** As shipped here, `partspec diff` still
  answered `identical` at exit 0 for those two reports: it pairs on `part.id`
  and read `part.contract` for nothing.

- **`diff` reads which target was invoked** (#343). #297 put the
  factory in `part.contract`; the comparator still pairs two reports on
  `part.id` and read that field for nothing, so two genuine reports of two
  different targets compared clean. Measured before, on two factories in one
  module returning `Part("widget", ...)` with the same claims:
  `identical: widget — no semantic differences`, exit 0. After:
  `different: widget — the invoked target changed: same.py:imperial →
  same.py:metric`, exit 1, with `contract.target_changed` carrying both sides.
  The digest could never have been the signal — it is module-scoped, so it is
  **equal** on that pair by design.
  **What is outcome-bearing is the FACTORY**, and only where both sides name
  one. The module path is recorded instead, as `contract.module_changed`:
  keying on the whole `<module>:<factory>` string made a *rename* a
  difference — measured, two byte-identical contract files, equal digests,
  `single.py:spacer` against `renamed.py:spacer`, reported `different` at exit
  1 — which is the mistake `SPEC-diff.md` §3 already refuses for the closure
  digest, whose point is that it identifies contents and not layout.
  **The guard is why `target.py` resolves the symbol always.** A single-factory
  module resolves without one being typed, so `spec.py` and `spec.py:spacer`
  were two spellings of ONE run and a plain equality would have called that
  pair a change; resolving always gives one spelling per target for every
  report of a target that resolves, and the guard covers the pair where one
  side predates it. That pair is a **stated gap**, not a match: it is recorded
  as `contract.target_incomparable` and named on the summary line, because §2's
  opening makes "no differences found" a positive claim rather than a
  fallthrough. It does not move the outcome, on an argument of its own rather
  than a borrowed one: an unsuffixed value written by the CLI **for a target
  that resolved** is evidence the module declared exactly one factory at the
  time, so a matching path and digest make the pair one run spelled two ways.
  The qualifier is not decoration — a pre-resolution placeholder is unsuffixed
  and its module may declare several — and `SPEC-diff.md` §3 carries it with
  the two residues the caveat covers.
  **The default `--out` directory does not move**: `Target.slug` keys on the
  factory the *invocation* named, so `partspec check spec.py` still writes
  `outputs/spec` and not `outputs/spec-spacer` — moving it would relocate
  every existing user's reports, `--pin` baselines and stored `diff` inputs
  included. Note where that rule bites: every production slug is taken from a
  *parsed* target, so the flag guards a resolved target's `slug` — a library
  caller's, and any later move of `_out_dir` onto it — rather than today's CLI
  path.
  **`contract.digest_changed: true` inside an `identical` outcome is correct,
  and stays reachable.** The digest is module-scoped, so an edit that provably
  cannot reach this part moves it: measured, two reports of one part from a
  module whose *other* factory gained a comment line differ in
  `contract_digest` and in nothing else the comparison sees. Reporting
  `different` there would answer a question about part A with a fact about
  part B. What was wrong was the **silence** — `SPEC-diff.md` §1 requires a
  moved build input to be named on every outcome, and the contract file is the
  one input the closure deliberately excludes (`SPEC-report.md` §8.3), so an
  edited `.scad` reached the summary line and an edited contract did not. The
  summary now names it, qualified in the same clause as module-scoped and
  never by itself a difference.

- **The eval harness stops calling a file "lint-clean" when three rules never
  looked at it** (#317, epic #305).
  [`evals/run.py`](https://github.com/heibench/partspec/blob/main/evals/run.py)
  branched on `counts.findings` alone and
  [`evals/AUTHORING.md`](https://github.com/heibench/partspec/blob/main/evals/AUTHORING.md)
  reported that as "trials lint-clean" — the blind loop `docs/LINT.md` names in
  its own words: "a `findings: 0` with `unsupported: 3` is not a clean file".
  A trial on a machine with no OpenSCAD, or over a source whose `.csg` export
  is refused, recorded zero and counted as clean while every tier-2 rule was
  skipped. Reproduced directly: a three-line `.scad` carrying a string reports
  `counts` `(findings 0, unsupported 3)` — clean under the old metric.
  The harness now records `findings`, `unsupported` and a three-way
  `lint_outcome`: `clean` only when both are zero, `findings` when every rule
  ran and something was found, `incomplete` when any rule did not. Wholeness is
  decided **first**, because nothing can be concluded from a findings count
  taken over a partial pass — a trial with both findings and refusals is
  `incomplete`, not `findings`. An absent `counts.unsupported` (a partspec
  predating #316, where the key is additive) reads as `incomplete` rather than
  as a zero. `results.json` gains a per-bucket `lint` tally beside `summary`,
  so the figure `AUTHORING.md` reports by hand is one the harness computes
  under a stated definition.
  **The recorded figures are annotated, not restated.** They are a measurement
  from a dated run that costs real agent calls to retake, so `AUTHORING.md`
  keeps its numbers and gains the definition in force when they were taken:
  every lint figure there is a **tier-1 count**. The runs are stamped
  `20260808-133845` and `20260808-134127`, and tier 2 was not committed until
  `1ac5807` at 17:27 the same day — so no tier-2 rule ran and none could
  refuse. `counts.unsupported` did not exist in the payload at all until #316.
  Reinterpreting those numbers under the new definition would report a
  measurement nobody took.

- **`just eval` runs the partspec it is meant to measure, and the result says
  which one** (#304). `justfile:303` was the only place in the justfile running
  Python outside `uv run`, so nothing put `.venv/bin` on PATH for the harness —
  on this checkout `partspec` does not resolve on the bare PATH at all, so the
  recipe as written failed its own guard rather than measuring the wrong build.
  It goes through `uv run python` now.
  `results.json` recorded `when`, `agent`, `arm`, `trials` and `summary`: no
  version, no commit, no path to the binary it measured. The header now carries
  `partspec` (an absolute path), `partspec_version` (what that binary reports)
  and `harness_commit` (the checkout the driver ran from — a separate key
  because `--partspec` may be an installed wheel from anywhere, and the two are
  not one fact). The commit carries the working tree's state in the value —
  `<sha>-dirty`, or `<sha>-unknown` when git could not be asked — because a
  bare `HEAD` from a modified checkout names a commit that is not what ran,
  which is the claim this header exists to refuse. A suffix rather than a
  sibling boolean: the boolean is dropped the first time anyone quotes the
  commit on its own. This is the class of defect the tool exists to prevent:
  `report.json` carries `tool_version` and `diff` refuses a comparison without
  one, while the directory arguing the tool works carried none — and a run costs
  real agent calls, so a baseline that cannot name its build cannot be compared
  to a later one.
  **`--partspec` names one executable, resolved to an absolute path.** It was
  split for `shutil.which` and passed whole as `argv[0]`, so
  `PARTSPEC_BIN="uv run partspec"` cleared the guard and then failed in the
  first trial — after the spend had started. `shutil.which` alone closes only
  half of that: given a path containing a separator it returns the string
  **unchanged** when it is executable relative to the CWD, so
  `PARTSPEC_BIN=.venv/bin/partspec` — the natural thing to type from the repo
  root — also cleared the guard, printed a reassuring version into the header
  (`provenance` runs with no `cwd`), and then died in every trial, because
  `run_check` runs with `cwd=work`, a temp copy. It is resolved once and made
  absolute while the CWD it was typed against is still the CWD, and that
  absolute path is what runs and what the header records. A path that exists
  but is not executable now says so rather than reporting "not found".
  `PARTSPEC_BIN` was documented nowhere;
  [`evals/README.md`](https://github.com/heibench/partspec/blob/main/evals/README.md)
  documents it now.

- **`AGENTS.md`'s layout tree is generated, so it can neither miss a module nor
  keep describing one that moved** (#299). The `## Layout` fence is the map this
  repo tells an agent to read first, and it had no generator and no test behind
  it. It named 15 of the 21 modules in `src/partspec/`: `csg.py`, `imports.py`,
  `raster.py` and `vdiff.py` — 1,874 of `src/`'s 16,722 lines — were absent.
  Three of the four are named elsewhere in the file, so the damage is bounded;
  **`raster.py` was not, and no shipped markdown named the file at all**, so an
  agent looking for the OCCT tier's render path goes to `engines/`, where it is
  not — `cli.py` and `vdiff.py` are the two modules that import it.
  Two rows had also gone false. `mcp.py` read "check/measure/render" while the
  module registers a fourth `@server.tool()`, `vdiff`; `refs/` read
  "(iso15, nema17)" while `iso_metric_thread.py` sits beside them. (#299 reports
  a third, `lint.py` as tier-1-only — #316 had already fixed that one.)
  **A generator rather than a test**, which is this repo's own convention: a
  test that reads the map and reads the tree is two copies of one fact with a
  failure report attached, and it reports drift only after it has happened.
  `scripts/gen_docs.py` gains a **seventh** block — it owned six, not the five
  #299 counted — and a module added with no row fails `just fmt` and
  `just check` alike, naming the module and the row that has to go with it.
  The MCP tool list and the `refs/` contents are derived the same way, the
  latter from `refs.__all__`, which is the question `cli.py`'s
  `_refs_carried()` already asks and for the same reason: a glob over
  `refs/*.py` would advertise a private helper as a cited reference table.
  What stays hand-written is the one line saying what each module is FOR — a
  judgement, not a projection of the code.
  **The tool list counts an `async def`.** `ast.AsyncFunctionDef` is not a
  subclass of `ast.FunctionDef`, and async is the idiomatic form for an MCP
  tool, so a generator matching only the latter would have dropped one — and
  the drop is not inert, because the prescribed remedy is `just fmt`, which
  would then *write* the shortened row and leave `--check` green on it. A guard
  whose failure mode is to author its own defect class is worse than no guard;
  `tests/test_docs.py` pins the shape.
  One fossil of the same enumeration lived outside every gate and is fixed with
  it: `pyproject.toml`'s `mcp` extra comment said "check/measure/render" too,
  the last place in the repo that did — `README.md` and `docs/AGENT-CONTRACT.md`
  already named all four.

- **A `requires` check that regresses now carries the operands that moved with
  it** (#326, epic #305). `SPEC-diff.md` §3 makes `operands` the value of a
  `requires` check — "`measurement.value` … or `operands` for a `requires`
  check (`SPEC-contract.md` §5 records them for exactly this)" — and the same
  section requires a status-change entry to carry the value delta.
  `_check_entry` attached `claim` and the `measurement`-based `value` on the
  status branch and returned there, one branch above the operands comparison,
  so the delta was recorded when the status *held* and dropped when it
  changed. Measured end to end over `examples/spacer` with `BORE_D` moved
  8.0 → 28.0, which breaks `bore_d + 2 * wall <= plate_y`: the artifact's
  entry was `{id, kind, change: "regressed", status}` — a precondition
  reported broken with none of the three numbers that broke it, though both
  reports record all three. It now carries
  `operands: {old: {bore_d: 8.0, …}, new: {bore_d: 28.0, …}}`, both maps in
  full, so "which input changed?" is answered by the comparison rather than
  only by the two files it compared.
  One helper, called by both branches, because the defect was two branches
  disagreeing about a question with one answer.
  **Operands compare exactly, and that is a domain judgement, not a
  shortcut.** The adjudication `epsilon(reference)` is sized for a
  measurement — §3 justifies it by transform-order noise at ~1e-13 and
  `SPEC-report.md` §3.3 sizes it for a binary-STL float32 round-trip — while
  an operand is a declared contract parameter that `expr.evaluate` reads
  before any build and adjudicates **exactly**, with no epsilon anywhere.
  Borrowing the measurement tolerance left a dead band never narrower than
  seven orders of magnitude, and unbounded above: measured against the ~1e-13
  the epsilon is justified by, it is `1e-06` at the floor (7.0 orders),
  `3.6e-06` at 26 mm (7.6) and `1.01e-04` at 1000 mm (9.0), the expression
  being minimised at zero. Inside it the predicate flips and the operands are
  called unmoved — `bore_d + 2 * wall <= plate_y` goes true → false between
  `bore_d = 26.0` and `26.000001`, and the entry emitted there was
  `{id, kind, change: "regressed", status}`, #326's own defect inside the fix
  for it, found in review.
  §3's MUST already required this, so it needed no change; the *tolerance*
  paragraph did, and gained the general rule that a comparison tolerance
  belongs to the provenance of a value and not to its type.
  The claim qualifier reads the claim and nothing else — `operands` is a
  result, listed in `NON_CLAIM_FIELDS` as one — so a part whose inputs moved
  is not accused of being a contract that was edited. (A second, independent
  qualifier for checks the new report does not answer landed later in this
  same cycle; see #325 above.)
  This entry originally recorded #335 as the place the new rule stopped — a
  `param_range` value having the same provenance and still being compared
  under the epsilon. That is no longer true of the tree these notes ship
  with: #335 was fixed later in the same unreleased cycle, and the sentence
  is corrected here rather than left to contradict the entry above it,
  because a released section is what this project's rule protects from
  rewriting and an unreleased one is not.

- **`partspec diff` refuses a payload that is not a report, rather than
  reporting two of them as identical** (#292, epic #305). Its only structural
  gate was `schema_version`, and `measure` and `render` carry the same one —
  and the same `tool`/`part` identity prefix — by design, so such a payload
  parsed, was read as carrying no checks, and skipped the `counts.total`
  invariant for want of a `counts`. Measured: two `measure` payloads of
  `examples/spacer` with `plate_z` moved 6 → 9 in the `.scad` printed
  `identical: example-spacer — no semantic differences` at exit `0`, on an
  artifact that recorded `source.digest_changed: true` in the same object —
  and exit `0` is what a CI gate reads. The reverse pairing was already
  refused as a difference (`8 check(s) removed`, exit `1`), which is the
  asymmetry that made it a bug rather than a policy.
  The guard requires what a report has — `verdict` and `counts` — rather than
  naming the payloads it is not, because the set of documents sharing that
  prefix is open and a guard listing today's two members would pass
  tomorrow's third. The message names the top-level fields the input actually
  carries, since the failure it closes is a reader wired to the wrong
  artifact — and it names the `measure`/`render` cause only where the payload
  actually lacks report shape. §2 rule 3's wording rule reaches this message
  too: a genuine report with `verdict` stripped is malformed, still carrying
  `checks`, `counts`, `error` and `hint`, and telling its author it is
  probably a `measure` payload is a confident diagnosis of the wrong defect,
  contradicted by the field list in the same sentence. A null field counts as absent, which also takes
  `"counts": null` off the CLI's catch-all — it reached `.get("total")` on a
  `None` and reported `these inputs are not well-formed reports
  (AttributeError: 'NoneType' object has no attribute 'get')`, the right exit
  under a Python type name for a diagnosis.
  This is the cheap half. The structural fix — a `payload` discriminator in
  the identity prefix — is #295 and is independent of it.

- **`--list` is no longer cited as a CLI flag that does not exist** (#303,
  epic #305). One sentence, copied to **three** files: the docstring at
  `src/partspec/__init__.py:5` that `help(partspec)` shows, where the
  lazy-import rule is justified; `SPEC-contract.md` §1.1 rule 3; and the
  comment on `dependencies = []` in `pyproject.toml`, which ships in the sdist.
  All three named a flag in the same clause, two of them word for word — "keeps
  the parameter phase and `--list` fast" — and §1.1 rule 3 as "the parameter
  phase and `--list` stay fast". There is no such flag: `partspec check --list
  foo.py` exits 64 with *unrecognized arguments: --list*, and none of the six
  verbs' `--help` mentions one. All three landed together in `34104ab`, the
  commit that scaffolded the repo — the first commit, `c28973d`, is the LICENSE
  and nothing else — and none was ever reconciled.
  The third site is the finding worth recording, because #303's own evidence
  grepped `src/ docs/ README.md AGENTS.md tests/` and called the result
  repo-wide, so the fix inherited the undercount and the first commit's subject
  said "two documents". The same divergence has bitten this tree before, the
  other way round: `tests/test_packaging.py:394` records PR #155's review
  finding two figures already corrected in `pyproject.toml` and not in the
  test enforcing them. A build file that carries prose is a documentation site.
  All three sentences keep their parameter-phase half, which was always the
  argument, and `--pin LOCK` remains the nearest shipped thing to enumerating a
  contract's declared claims — and it still builds.

- **`iso_metric_thread.tapped_hole` is named in a document** (#285, epic #305).
  It ships in the module's `__all__` and is a full §11 fragment — namespaced
  ids, bound at the basic minor diameter D1 — and `grep -rn tapped_hole
  --include='*.md'` returned nothing repo-wide. #247 added
  `iso_metric_thread` to §11's example **import** line and never added the call
  line, so the block imported a module its own example did not use. §11's
  example gains `iso_metric_thread.tapped_hole(p, 3)`, and
  `skills/contract-authoring/SKILL.md`'s fragment row — the second enumeration
  site, carrying the same two-of-three list — names it beside `nema17.mount`
  and `iso15.seat`. Verified before documenting: the call declares
  `iso_metric_thread:M3:tapped`, `kind: hole_diameter`, limit
  2.4087341226347263..2.508734122634726, cited to ISO 724:2023 / M3 /
  `minor_diameter_internal`, and passes against a Ø2.459 bore.

- **A dimension the engine defaulted, because a value would not convert, no
  longer reaches a measurement** (part of #308; the remainder is #332, epic
  #305). `cube(size=[o, 30, 6])` with `o = undef` exports a clean,
  watertight, single-solid **1x1x1 unit cube** — the 30 and the 6 go with the
  axis that did not convert — and `check` over `watertight()` +
  `solid_count(1)` reported `PASS: 3 pass` at exit 0 on both pinned engines.
  #286's success-path guard reads only the markers that name a NAME, and this
  shape names none. `Unable to convert` — the line OpenSCAD prints at the
  moment of substitution, naming the module and the value it rejected — is now
  read there too, and the same case is `ERROR: 3 skipped` at exit 4 on both.
  **Measured under both pinned engines rather than assumed**, which the
  include marker's `Can't open` / `Can't find` split makes mandatory:
  `cube`, `translate`, `square` and `scale` print this line
  character-for-character alike on 2021.01 and 2026.08.01.
  It is its own marker set rather than an addition to the name markers,
  because `undefined operation` — the obvious candidate, tried and reverted in
  PR #306 — also fires on `echo("holes: " + holes)`, a debug line with a type
  error beside a completely correct 272-facet part. `Unable to convert` is
  emitted only where a value actually reached geometry, so that part still
  passes at exit 0; asserted through the binary, not reasoned about.
  **Two classes of conversion warning are carved out.** The **GUI camera** is
  unconditionally safe — `$vpt = [undef, 0, 0]` prints the marker's exact words
  on both engines beside a cube that is exactly right, and no exported mesh can
  depend on the camera. The second is a **trade with a remainder, stated here
  rather than implied**: a **range or step built in an expression**. On
  2026.08.01,
  `echo("holes:", [0 : holes])` with an optional module parameter left at
  `undef` prints `Unable to convert [0:...:undef] to a range` — head-anchored,
  so the anchor above does not exclude it — beside a part whose export is
  **byte-identical** to the same source with the echo deleted. That is PR
  #306's protected echo case with a range where the string concat was, and
  matching it gave exit 4 on 2026.08.01 against exit 0 on 2021.01, with a
  diagnosis whose every clause was false: no module, no default, nothing
  reaching geometry. Counted in OpenSCAD's own source, the two range templates
  are the only two of its 21 distinct `Unable to convert` messages that begin
  with `[`; every substitution begins with a module or field name, so the
  bracket separates the classes by the engine's grammar rather than by a list
  this repo would have to chase.
  **What that carve-out costs** (#338): a failed range yields `undef` into the
  expression, and that `undef` can reach geometry. On 2026.08.01, where this
  line is the only stderr signal produced, `for (i = [1 : n])` with `n` unbound
  drops the loop's geometry entirely — the engine's summary line reads
  `Facets: 6` against 76 for `n = 4`, and the exported STL carries 12 triangles
  against 76, the engine's own vocabulary rather than the measured mesh — and
  `n = undef; r = [0 : n]; linear_extrude(r[2])` exports a part 100 mm tall,
  which is #308's own headline fault. Both pass at exit 0. The line cannot tell
  an expression that reached geometry from one that did not, so correct parts
  win the tie: matching it refused a byte-identical-export part in round-2
  review, and `undefined operation` came off the success path for the same
  reason with #332 holding its remainder. The trade is deliberate; the
  remainder is filed, not waved away.
  **What is still uncovered, measured rather than supposed** (#332): a
  *scalar* dimension taking `undef` narrates nothing at all.
  `linear_extrude(undef)` and `cylinder(h=undef)` are silent on both engines,
  and #308's own headline reproduction — `linear_extrude(undef + 1)` — prints
  `undefined operation` and no conversion line, so it still passes. There is
  no stderr signal to guard on, so #308 stays open. `rotate(a=undef)` was a
  sibling with a different spelling, `Problem converting`, left out to keep
  this change to one guard (#333) — and pinned as a negative, since adding it
  to the marker set otherwise left the whole suite green, which is a deferral
  with nothing holding it. That deferral is now closed, in the entry below; the
  negative pin moved to the one `Problem converting` template that is not a
  substitution. The docstring in `engines/openscad.py` says both, rather than
  implying the shape closed.
  **The marker is anchored at the head of the engine's sentence**, and that is
  the whole of its safety. Two measured reasons. OpenSCAD echoes string
  literals verbatim into the warning, so an unanchored test let a source turn
  the guard off by naming it — `translate(["harmless", o, 0])` was refused at
  exit 4 while `translate(["Unable to convert $vp", o, 0])` reported
  `PASS: 3 pass` at exit 0, one dropped transform either way. And
  `Unable to convert` is not only a substitution: CGAL says
  `The given mesh is not closed! Unable to convert to CGAL_Nef_Polyhedron.` on
  2021.01 for a `difference()` over an unclosed polyhedron — exit 1, no STL,
  nothing substituted — where 2026.08.01 words it `[manifold] Input mesh is not
  closed!` and never says "convert". Unanchored, one source got two different
  reports on the two pinned engines and the 2021.01 one blamed a defaulted
  dimension for an unclosed mesh: F13 with a false cause attached. The matcher
  and the diagnosis now share one predicate, so what is refused and what is
  called a substitution cannot drift apart.

  **Real library code does trip this, and that is a behaviour change.** Not a
  count: three attempts at a corpus total were wrong three different ways — one
  engine, then a 15 s render cap, then a corpus swept with the libraries hidden
  from themselves, where the dominant marker was `Can't open include file` and
  the conversion lines beneath it were knock-on `undef`s from a library that
  never loaded. That is a #286 refusal, already exit 4 before this change. What
  follows is therefore a **verified list, not a census**: each file rendered
  with its own library root on `OPENSCADPATH`, under both pinned engines, at a
  250 s cap, classified by the shipping predicate, and kept only where **no**
  `#286` name marker accompanies the conversion line.

  | file | 2021.01 | 2026.08.01 |
  |---|---|---|
  | `MCAD/hardware.scad` (its own demo block) | 5 | 5 |
  | `YAPP_Box/examples/GateAlarm_Sample_v30.scad` | 1 | 1 |
  | `pathbuilder/demo/TwistedMesh.scad` | 1 | 68500 |
  | `MCAD/trochoids.scad` | — | 120 |
  | `openscad/examples/Old/example011.scad` (OpenSCAD's own) | — | 1 |

  Counts are conversion lines emitted. Every one is a **true** refusal:
  `module bearing(position) … translate([0, 0, -position - bearingwidth/2])`
  with `position` unbound really does lose the offset, and `faces = undef` into
  `polyhedron()` really is a solid with no faces. So a user pointing
  `partspec check` at one of these now gets exit 4 where they previously got a
  build, and the report is about their library rather than their part.

  Files that look like hits and are not, since the difference is the whole
  lesson: `BOSL`/`BOSL2` `orientations.scad` emit **zero** conversion lines
  once BOSL is on the path; two of the three `pathbuilder` demos are likewise
  clean once `pathbuilder/` is; `YAPP_Box`'s `RidgeExtDemo` and `HookTest`
  carry `Ignoring unknown variable 'ridgeExtTop'` on both engines and so were
  already exit 4; and `NopSCADlib`'s Gridfinity example is a 2021.01 hit
  accompanied by `Ignoring unknown variable '$d'` — already exit 4 there — and
  a clean **non**-hit on 2026.08.01, one more divergence in this family.

  Nothing partspec ships trips it — all 25 in-repo `.scad` files are clean on
  both engines.

  **The refusal says which of the two faults it is.** #286's guard had one
  sentence, and *the engine could not resolve a name* with a hint to check
  `OPENSCADPATH` sends a reader hunting for a library that is not missing.
  A conversion now reads *the engine could not convert a value and built a
  default in place of it*, with a hint that names the module and points at
  whatever left the value undefined. `check`, `measure` and the `empty()`
  detail take the cause from one classifier, so one engine line cannot be
  diagnosed two ways by two verbs; the name text is unchanged to the byte and
  both are pinned.
  **The specs say so too.** `SPEC-report.md` §6.1 and §6.2 enumerated the ways
  a run reaches `error`/exit 4 and this was none of them — the contract did not
  raise, the build succeeded, every name resolved — so both tables and the
  prose above them now carry it. `SPEC-contract.md` §4.12 listed the evidence
  `empty()` reads and omitted the new marker while `empty()` was already
  failing on it; `AGENT-CONTRACT.md` §2.3 is a decision list whose branches
  this cause matched none of, so an agent fell through to *the contract itself
  raised* and was sent to edit the contract — the one thing §4 forbids. It has
  its own branch now, saying explicitly not to go looking at `OPENSCADPATH`.


- **`partspec diff`'s headline now says when a status change moved the claim
  with it** (#293, epic #305). `SPEC-diff.md` §3 requires a status-change entry
  to carry the claim delta because "an entry saying only 'fixed' would report
  the attack as an improvement". The artifact discharged that; the stderr
  headline counted entries per bucket and printed `1 fixed` — so loosening a
  bound until a failing check passes, the flagship weakening move, reached the
  console as good news. Reproduced end to end against a real build over
  `examples/spacer`'s `spacer.scad`: one contract, its `envelope` bound edited
  in place from `max=(40,30,4)` to `max=(40,30,8)`, the source unmoved
  (`source.digest_changed: false`). The artifact carried
  `status: fail→pass` beside `limit.max: [40,30,4]→[40,30,8]`; the headline
  read `different: example-spacer — 1 fixed` and named neither.
  The count keeps the bucket's true total and the qualifier is an independent
  tally over it — `1 fixed (1 with the claim changed)` — rather than splitting
  into two counts, because `N fixed` is what §3 names and what a reader greps,
  and a split total answers "how many were fixed?" with a number that is not
  the answer. (Said as "breaks it down" when this entry was written, which was
  true of the one qualifier that then existed; #325 later in this same cycle
  added a second, and two independent tallies over one bucket can overlap and
  sum past it.)
  Both status buckets take it: `1 regressed` alone cannot tell a part that got
  worse from a contract the author deliberately tightened, and only one of
  those is a defect. `limit_changed` does not — the claim moving *is* that
  bucket — and a `drifted` entry cannot carry a claim at all.
  §3 now binds the headline in the bullet that binds the entry, immediately
  after it and giving the same reason, so the two surfaces are specified
  together rather than one inheriting the other's reasoning by implication.

- **`partspec lint`'s console now names the rules that did not run** (#288,
  epic #305). `unsupported[]` was written per file while the stderr courtesy
  stream was built from `findings` alone, so a source whose `.csg` export
  fails printed three tier-1 findings and no hint that every tier-2 rule had
  been skipped — and with no engine installed, that is every tier-2 rule on
  every file, which nothing downstream ever corrects. #118's rule is that a
  rule which could not run must not read as a clean bill; that held for the
  payload and not for the console.
  Grouped **by cause, not per entry**: with no engine every `.scad` refuses
  every tier-2 rule for the same reason, so one line per entry would put
  three identical sentences per file on the console — 75 of them over this
  repo's own sources — and a courtesy stream nobody reads is the silence it
  exists to break. One line per distinct cause names the rules and the files,
  the latter bounded at two names plus a count the way `diff` bounds its own
  name lists — a bare count says something was skipped and leaves no way to
  find out which, which is live on this repo: four of its own sources refuse
  for string content even with an engine present.
  `counts` gains **`unsupported`**, counted per (file, rule) so the tally and
  the blocks cannot disagree. It is the field that says whether the run was
  whole: `findings: 0` with `unsupported: 3` is not a clean file, it is a file
  three rules never looked at. Additive, so `LINT_SCHEMA_VERSION` does not
  move — the rule `--out`'s `written` followed (#225).
  `LINT.md` prescribed the blind loop: "read each file block's `findings[]`
  before the first render", never naming `unsupported[]`. It now names both.
  Its scope paragraph also still said tier 2 was "the two `csg-*` rules" —
  the same stale count found on the README one PR earlier.

- **`partspec lint` no longer computes a volume for a surface that encloses
  nothing** (#289, epic #305). `csg.volume_of`'s `polyhedron()` branch is a
  signed-tetrahedron sum with no watertightness precondition.
  `tests/fixtures/open_box.scad` names
  this case in its own header — "every measurement library will still hand you
  a volume for this … which is the case partspec must **refuse** rather than
  answer" — and partspec was answering: exporting that fixture and reading it
  back gave **666.67** for five faces of a cube. `planes_of` refuses the same
  node honestly; this is `volume_of` catching up.
  Measured end to end before the fix: an open polyhedron differenced against a
  smaller cube produced a `csg-difference-order` finding whose order was
  correct, computed from a volume that does not exist. A wrong lint finding is
  the same fault as a wrong check, one advisory step removed.
  The precondition needs only the faces and points: on a closed,
  coherently-oriented surface every directed edge appears exactly once and its
  reverse exactly once. A missing face leaves edges unpaired; a face wound the
  wrong way traverses one twice in the same direction. Both are refused, the
  offending edge is named, and the rule goes to `unsupported` rather than
  silently producing nothing — so the reason survives into the report.
  **Edges are keyed by coordinate, not by index.** Keying on the index refused
  a cube written as a triangle soup — per-face vertices, which is what every
  STL/OBJ-to-`polyhedron()` conversion emits — reporting all 24 of its edges as
  belonging to one face while OpenSCAD rendered a watertight 1000 mm3 solid
  that the old code had measured correctly. The engine welds coincident
  vertices; the check now does too. That over-refusal was caught in review, and
  it is worth naming because the same index-pairing rule *is* sound in
  `tests/test_region.py`, where it runs on partspec's own canonical
  triangulation and one index is one vertex by construction — user input
  carries no such invariant.
  Two limits of "exact" are now stated in `LINT.md` rather than implied: a
  closed but self-intersecting polyhedron measures the sum of its shells (an
  upper bound, which is what the rule compares), and a globally inverted
  surface is measured with its sign discarded.

- **A parameter refusal no longer claims to have read includes it could not
  open** (#287, epic #305). `unbound_parameters` answers from
  `top_level_variables`, which reads the files partspec *resolved*, and the
  refusal's sentence said the name matched nothing "in `<file>` **or its
  includes**" — about includes that never opened. Measured: a model whose
  `include <missing_lib.scad>` fails, given `lib_x`/`lib_y`, was refused with
  `FAIL builds` at exit 1, blaming the contract, while the engine built the
  part cleanly at 20×10×3 with both `-D` values reaching the geometry. A cold
  agent believing that deletes a correct declaration, and the real fault — an
  include that did not open — went unmentioned though the report carried it.
  The refusal now names what it could not read, says the list is therefore
  short, and carries `origin: "environment"`: an include that will not open is
  not a statement about the part, so the remedy is to make it resolvable
  rather than to edit the contract. `verdict: "error"`, exit 4, `builds` not
  emitted failing.
  **Withholding the refusal instead was tried and rejected**, and the reason
  is worth recording: `Closure.unresolved` held `use` targets as well as
  `include` ones, and a `use`d file contributes no top-level variable at all —
  so an unresolved `use` suppressed a refusal that was never in doubt, and
  because `Can't open library` is deliberately not one of #286's markers,
  nothing downstream spoke either. A transposed `bore_diamter=20` then reached
  `verdict: "pass"` at exit 0 on both engines against geometry 8 wide, with
  `params` asserting the value the geometry never saw. Trading a loud false
  error for a silent false pass is the one trade this tool must not make.
  `Closure` therefore gains **`unresolved_includes`**, and only that arm takes
  the new sentence. It is include-*reachability*, not "an include seen anywhere
  in the walk", and the difference was measured rather than reasoned: with
  `entry → use → include` of a file declaring `X`, the engine prints
  `Ignoring unknown variable 'X'` where including that file directly renders
  it. `use` stops the chain transitively, so an unresolved include found behind
  one cannot have narrowed a list it could never have widened — the same false
  sentence, one level deeper. For every other question the two are the same fact —
  neither file was read — but for the variable list they differ absolutely:
  `include` splices top-level assignments into the entry and `use` imports only
  modules and functions. Saying otherwise was not merely imprecise, it was
  actionable and wrong: an unresolved `use` was told a variable declared in the
  unread file "would be missing from" its list, and a reader who created that
  file to satisfy the hint reached `verdict: "pass"` on a `-D` the engine had
  dropped. An unresolved `use` now keeps the ordinary refusal, which is exit 1
  and substantively true.
  `AGENT-CONTRACT.md` §2.3 gains the branch. It is the one exit-4 shape where a
  model edit may be the fix — the include path can be misspelt in the source as
  easily as the library can be absent from the machine, and partspec cannot
  tell those apart — which the exit-code table's "editing the model on exit 4
  is noise" would otherwise send an agent straight past.

- **A build that silently lost geometry no longer reports `pass`** (#286, epic
  #305). OpenSCAD renders an unresolved call's children *not at all* and still
  exits 0 with a clean, watertight, single-solid mesh, so a misspelt module or
  an include that did not open removes the feature a contract is about and
  every check downstream measures a part nobody described. partspec already
  owned the evidence — `_UNRESOLVED_MARKERS` names the diagnostics the engine
  prints, measured on 2021.01 — and read it **only where the build had already
  failed**; the path that succeeded discarded `proc.stderr` outright. A
  declared bore could therefore go missing under four green checks at exit 0.
  This is `FAILURE-MODES.md` §1 — the 35%-smaller gear with its teeth gone —
  reproduced inside this repo with partspec green, and it is the one shape the
  tool existed to catch and could not see.
  `check` now reads those lines on the path that *worked*: such a run is
  `verdict: "error"`, exit 4, with `builds` and every geometry check `skipped`
  and the engine's own diagnostic quoted in `error`. **`measure` refuses on the
  same evidence**, because it is where numbers become claims — an author
  reading `volume: 7200.0 exact` off a hollowed part writes it into a contract
  that passes forever after. `render` is **not** yet guarded and still writes
  views of the wrong part; it needs a way to say "partspec cannot attribute
  this fault", which `BuildError.origin` has no spelling for, and is tracked
  separately.
  **`builds` is not emitted failing and `build_origin` stays `null`**, which is
  the load-bearing half: the source compiled, so a failing `builds` would be a
  statement about the design partspec has not earned — and whether the name is
  a typo or a library absent from this machine is precisely what it cannot
  tell. It claims neither and says only what it knows. Parameter-phase checks
  still answer: they are arithmetic over the contract's inputs and need no
  engine. `SPEC-report.md` §6.1 and §6.2 gain the third route to `error`, and
  `AGENT-CONTRACT.md` §2.3 gains the branch that routes it — without which an
  agent read `build_origin: null` as "the contract raised" and was sent to
  repair a contract that was fine.
  **The engines word these warnings differently, and one of the markers had
  been dead on half the CI matrix since the snapshot leg was added.** A missing
  include is `Can't open include file` on 2021.01 and `Can't **find** include
  file` on 2026.08.01; only the first was listed. Measured by running the same
  source under each pinned binary, after the snapshot leg failed on exactly the
  two include cases. So on the newer engine a source whose include did not open,
  with no other unresolved name, reported `pass` — and did so on `main` too,
  including on the empty-result path this marker list was written for. Both
  spellings are now listed and both are pinned against the matcher directly, in
  a test that needs no engine and so cannot be skipped into silence.
  Only the markers that name a **name** are read on the success path.
  `undefined operation` is deliberately excluded: it reports a type error, and
  `echo("holes: " + holes)` — `+` where `str()` was meant — renders a perfect
  part while printing it. Guarding on it errored that part at exit 4 while
  claiming a name had not resolved. It stays in the wider set used where the
  render already produced nothing, which is where its reasoning holds.
  The false-positive bound is measured, not asserted, and measured on **both**
  engines rather than one: of the 25 `.scad` files tracked in this repo, 25
  build with no name marker on 2021.01 and 24 on 2026.08.01. The one exception
  is a true positive — `tests/fixtures/imports_stl_data.scad` calls
  `import_stl()`, a builtin the newer engine removed, so that fixture really
  does lose its imported solid there and the guard really should say so.
  Alongside: `is_undef()` — how a source legitimately probes for a name it does
  not require — emits no warning, while reading an undefined variable directly
  *does* warn and silently renders a default cube. One behaviour change worth
  naming: `include <optional.scad>`
  for a file that is deliberately absent now errors rather than rendering, and
  that is intended — the closure genuinely is partial.

- **A canonical view is no longer written over a heightmap the model reads**
  (#267, completing #263). `render --out .` against a model reading
  `renders/iso.png` through `surface()` had partspec write its own iso view
  over that heightmap, and from the next run **the part IS the previous run's
  picture**: measured on 2021.01, `IMAGE_SIZE` is 800x800 and `surface()`
  spans one unit per pixel gap, so `render_bbox` reads **799 in x and y**, at
  exit 0 with nothing on stderr, on every run after. #224 fixed the *unlink*
  on this path; the *move* was left, and #263's own docstring recorded it as a
  known residue rather than an unanswerable one.
  **It costs no new question of the engine.** A `surface()` target is opened
  when the source is parsed, so the STL pass's depfile already names the
  heightmap — the views are four re-parses of one source and could not differ.
  **Every view is asked before any view moves**, which is the constraint the
  batched move exists for (#234): a per-view refuse-then-continue would let
  three land and the fourth refuse, leaving a directory of images from two
  different builds. What survives is the case no depfile reaches — an engine
  with no `-d` keeps this path's previous behaviour, which was no guard at
  all, because a refusal nothing can justify is worse than the residue.

- **`p.empty()` could not pass on the OCCT tier for any input at all** (#271).
  `a & b` on two disjoint solids returns an **empty `Compound`** — not a null
  shape and not an empty CadQuery stack, which were the only two null results
  `produced_nothing` reached. So the natural spelling of a clearance probe on
  that tier landed in the ordinary build-failure branch: `builds` **fail**,
  `empty` **fail**, for a probe whose parts are nowhere near each other. The
  check #237 added to grade the good outcome graded it as the bad one, on half
  the tiers.
  Found by measuring the line #270 recorded as "not measured", and the two
  messages on that path already said *"a shape containing no geometry"* — the
  classification was in the prose and not on the flag.
  **Nothing else moves.** `produced_nothing` is read in exactly one place and
  only inside `if empty_specs`, so a contract that does not declare `empty`
  still fails its build on a null result exactly as before — pinned, because
  that is the half #237 was explicit about not softening.
  `SPEC-contract.md` §4.12 claimed the check "reads the same on either tier"
  while enumerating two of the three null results that tier produces. It now
  enumerates all three, and states plainly what a null result cannot tell you
  on **any** kernel that declines to represent a zero-thickness one: whether
  the parts are clear or merely touching (#270).

- **An invocation that cannot cover its pin says so before the first build,
  not after the last one** (#202). `check a b c --expect lock.json` whose lock
  also covers a deleted `d` built every surviving target first — **56 to 108 s
  each on the OCCT tier** — and only then reported that the invocation could
  never have covered its pin. The answer was knowable at second one, because
  coverage needs the RESOLVED set and resolution is engine-free: a whole
  mismatch run measures **0.095 s**.
  **Nothing else moves, and that is the decision rather than the shortcut.**
  The issue frames the surviving targets' builds as waste; the suite calls them
  the work, and `test_an_unpinned_part_does_not_pass_on_someone_elses_pin`
  pins it — failing before the loop would write no report at all for the
  targets the user actually supplied. So the exit code, the reports and the
  authoritative diagnosis are untouched; what a human gains is the chance to
  abort at the start of a long run instead of at the end of one.
  **Silent whenever anything is uncertain.** A target that fails to resolve
  abandons the preview entirely rather than guessing: weighing a failure
  against a missing part is #201's and #243's work, it lives after the loop,
  and a preview that could contradict it would be worse than no preview.
  Silent under `--quiet` for the same reason it exists — "you can stop this
  now" is meaningless to a non-interactive caller, and the failure still
  reaches CI once, from the place that owns the exit code.
  It costs running the contract factory a second time, which `SPEC-contract.md`
  nowhere forbids being impure, so the preview takes nothing from that resolve
  but the part id, holds no `Part`, and evicts model modules between targets
  exactly as the build loop does (#114, #101).

- **The output-collision guard is exact, so a subdirectory import no longer eats
  its own output** (#263, closing out #226). `.stl` is an INPUT extension as well
  as an output one, and until now nothing could say which — `reads_external_data`
  is a bool by design, because an `import(names[i])` path is computed at render
  time. So both guards refused conservatively, and #223's shipped its residue in
  its own docstring: scoped to the model's own directory, `--out sub` for a model
  importing `sub/<stem>.stl` **replaced** that import, which still resolved, so
  the model ate its own output. Re-measured on this fix's own repro before and
  after: `[8, 7, 11]`, `[13, 7, 11]`, `[18, 7, 11]` on three identical runs, each
  at exit 0 — and a `check` claim false of the real part passing from run 2. Now
  every one of those three runs refuses, the donor is byte-identical afterwards,
  and the same contract into an ordinary output directory still measures
  `[8, 7, 11]` on every run.
  **The engine answers what no static reader could.** `openscad -d` names a
  subdirectory import by full resolved path, so the guard asks the dependency
  list instead of the destination's location — and asks it after the render and
  **before the rename**, where both movers are still staging into a scratch
  directory and the caller's file is untouched. The error says it took a render
  to find out, rather than implying the caller could have known.
  **It stops over-refusing in the same stroke**, which is the half a reader
  notices first. `measure --out FILE` refused on the mere presence of `import()`
  anywhere in the closure; it now refuses only where the render actually read
  that file. The v0.7.6 audit's finding falls out with it: the old hint's remedy
  — a directory — worked on the first run and was refused from the second, so it
  had to exclude the model's own directory; that directory now simply works,
  repeatedly, because the depfile proves `<stem>.stl` is not `input.stl`.
  **The question is asked of the whole of `partial`, not of
  `reads_external_data`**, and the difference is a hole the first cut of this
  fix left open. A closure reporting no external data is not a promise that the
  render read none: an `include` partspec cannot find on ITS search path may
  resolve on the engine's, and the file behind it may hold the `import()`
  partspec then never saw. Pinned with a real divergence — `OPENSCADPATH` set
  for the engine, `library_path` emptied for partspec — and the pin fails
  against the narrower gate.
  **A complete dependency list that CONTRADICTS the source is not an answer
  either**, and that is F13 arriving in a guard. `import_stl()` is deprecated:
  2021.01 executes it and the 2026.08.01 snapshot ignores it, so **one source**
  gives a depfile naming the data file on one engine and omitting it on the
  other. The first cut of this fix took the second at face value and handed
  back "safe to write" for a file the same contract reads on the machine beside
  it; the two-engine matrix caught it, and this machine could not have. Where
  the closure says the source reads external data and the render read none, the
  accounts disagree, and a disagreement is now treated exactly as no answer at
  all — so both callers keep the answer they gave before. It over-refuses by
  that clause alone (an `import()` in a branch the render never took reads
  nothing legitimately), which is the direction to err in, because the cost of
  the other one is the caller's data.
  **Neither arm is loosened where the engine cannot answer.** An unresolved
  `include` is listed in no depfile at all — the file names what the render
  *opened*, never what it asked for — so that arm still refuses before the
  render, which is the only honest answer available for it. And an engine with
  no `-d` writes nothing, so there the pre-#263 rule applies unchanged rather
  than an unanswerable question becoming a pass. `EXIT_USAGE` is unchanged too:
  the same `--out` is refused at 64 as before, because a bad argument and a
  build failure are not the same answer to a script.
  `diff`'s phrase for the `external_data_reads` gap named a limitation without
  naming the remedy, and now names both — phrased as a fact about *this run*
  rather than about the engine, so it stays true of a pre-0.7.7 report, which
  carries no `engine_inputs` at all.

- **What `builds` means, now that `empty` exists.** `p.empty()` shipped and made
  three statements about `builds` false in the same batch that introduced it —
  including one in a docstring written by that PR. `SPEC-contract.md` §4.2 said
  `builds` "fails if the engine exits non-zero or emits no artifact", which is
  exactly what a declared-empty part does while `builds` **passes**; and both the
  `GEOMETRY_KINDS` and `BUILD_PHASE_KINDS` docstrings called it "whether the
  engine produced anything". It is whether the engine produced *what the contract
  asked for*, which is `anything` unless the contract declared `empty` — the one
  case that makes the two readings differ.
  §4.2 also now separates the two meanings of the word, which `p.empty()` made
  collide: the **verdict** `empty` is a contract that declared nothing, the
  **check** `empty` is a contract that declared nothing was the result. Nothing
  in the code can confuse them — a `Verdict` member and a `kind` string are never
  compared — so the risk is a reader's, and a test pins the one contract where
  both could plausibly apply.

- **A region declared 10 000 km from the origin no longer dies blaming its
  author** (#245). `_max_intrusion_depth` erodes the region 24 times to prove
  how deep material reaches, and at extreme coordinates the constructor refused
  its own eroded copy: `box region min must be strictly below max on every
  axis; x: 10000000004.0 vs 10000000004.0`. A `ContractError` naming a
  declaration that was legal, raised only after every backend boolean had been
  paid for.
  It takes two conditions, which is why #244 fixed the neighbouring case and
  left this one. The search brackets `[0, inradius()]` and halves 24 times, but
  `hi` collapses toward `_search_ceiling`, so only a region whose ceiling sits
  *at* its inradius — an elongated one, where the erosion closes one axis
  rather than three — probes near the degeneracy at all; an 8x8x8 keep-out
  stops 1e-2 mm short of it and is fine at any offset. The coordinate's ulp
  then has to exceed the extent left at that probe: 8x400x400 is fine at
  x = 1e9 and refused at x = 1e10, an ulp of 1.9e-6 mm against an extent of
  4.8e-7 mm.
  The clause still fails — material fills the region, and that much is decided
  by the same booleans as before. What it no longer does is claim a depth: the
  erosion is not representable at those coordinates, so the honest answer is
  the one this function already gives when the backend cannot answer. Bounding
  the probe below the ceiling, the other remedy #245 proposes, was measured and
  does not reach this case: the elongated region's ceiling *is* its inradius to
  within 3e-12.

- **`eroded_volume` refuses a non-finite offset, as `expand` already did**
  (#245). It clamped with `max(0.0, ...)`, and `max(0.0, nan)` is `0.0` in
  Python, so a NaN offset was graded "erodes to nothing" — an answer — while
  `expand(-nan)` raised. It was the only region entry point that accepted a
  non-finite argument. Not reachable from the search, whose probe is a midpoint
  of two finite bounds, so this is a public method brought back in line rather
  than a live defect.

- **`check --render` takes the several targets `check` itself takes** (#189).
  It refused them — `partspec: --render is single-target for now`, exit 64 —
  and the "for now" was right: nothing under the refusal was load-bearing.
  Every target already resolves its own output directory, so the views land
  beside that target's own report and are recorded relative to it, exactly as
  the single-target shape does. Fleet agents in two arms hit this on their
  first attempt to render a whole contract, and one more in the earlier spike.
  Each of them dropped `--render` from the batch check and rendered target by
  target through the standalone `render` subcommand instead — which writes
  `render.json` and no report, so the views stop being attached to the verdict
  at all. a1's frozen log carries 20 such renders across a session.
  Nothing announced the exclusion in advance either — `check --help`
  documents multi-target and documents `--render`, and said nothing about their
  being exclusive, so the refusal arrived only after the command was written.
  A render that fails now names its target, which it never had to before: one
  message against four parts and a single exit code says nothing about which
  one could not be drawn.

- **The unattributed-limits advisory names every table `refs` carries** (#194).
  It printed a hardcoded `(iso15, nema17)`, so the one place the tool routes an
  author to an attributed number went stale the moment a table was added — and
  stale in the direction that matters, since its whole job is to point at a
  table the reader did not know existed. It asks the package now.

- **`diff` no longer says a claim held when it failed on both sides** (#220).
  Whenever the outcome was `identical` and the closure had moved, `diff`
  printed `every declared claim held across the change` without ever asking
  what the claims' status was. Two reports whose same check fails identically
  on both sides were therefore told the claim held. It did not — it failed,
  twice. What is true is that its *status* did not change, which is a weaker
  statement and a different one.
  `identical` at exit 0 is correct here and is not what changed: `diff`
  compares two reports and nothing about them differs. Only the sentence was
  wrong — "code right, words wrong", in permanent output, on the honesty line
  the #190 work added precisely to stop a silent claim.
  Gated rather than reworded flat, because the strong sentence is worth keeping
  where it is TRUE. A `fail` or `incomplete` pair is told its status did not
  change and which state both sides are in; **a pair with no declared claim is
  told so**, since "every declared claim held" over no claims is vacuously
  true, which is the shape this project exists to refuse rather than a
  technicality it gets to lean on. Under `identical` every id, status and claim
  field is equal on both sides, so the later report describes both.
  **Read off the checks, and off nothing else.** The first version of this fix
  keyed on the artifact's `verdict`. The comparison only ever compares that field
  against its counterpart — it decides `different` and `indeterminate`, and is
  never read as a fact about one report — so a lie repeated identically on both
  sides costs it nothing. Keying a claim about what the checks DID on it made
  that lie load-bearing for the first time, and a report claiming `pass` over a
  failing check printed #220's sentence verbatim. `status` adds none: it is what the
  comparison already joins, the evidence every `regressed` and `fixed` rests
  on. `summary_of` takes the later report now, and requires it.
  **Two questions, and they take different check sets** — which the second
  version got wrong, and which is the sharper half of this entry.
  `Report.verdict` excludes `builds` from the EMPTINESS test, because partspec
  adds it and a contract asserting nothing would otherwise look asserted, and
  then collapses status over EVERY check, because a build that failed is a
  claim that failed. Applying the exclusion to both questions reported
  `every declared claim held across the change` for a model that does not
  compile — #220 reproduced by its own fix, on two reports `partspec check`
  wrote unmodified.
  Three more from the same reviews. "Zero checks" was wrong for `empty`: it is
  zero DECLARED checks, and a real one carries the `builds` check partspec
  adds itself, so the first fixture tested a shape no run emits. The sentence
  was never "unconditional" — the gate always had two further conditions, a
  0.7.5-shaped closure and attributed movement, and making the report optional
  silently un-pinned the second of those in three tests. And every fixture
  carried exactly one declared check, so the boundary the function exists to
  draw — one claim passing beside one failing — went unexercised until now.
  The issue also asked whether the neighbouring `covered:` line overreaches the
  same way. It does not — it is built from the closure and the imports and
  describes which *inputs* were accounted for, saying nothing about the
  checks — and a test now pins that separation, since it is the reason the
  claims line could be wrong on its own.
- **A wrong-typed argument gets partspec's own message rather than a dict-key
  error** (#199). `region.cylinder(axis=[0, 0, 1])` raised
  `TypeError: cannot use 'list' as a dict key`: the guard is
  `self.axis not in _AXES`, a membership test that HASHES its operand, so an
  unhashable value died inside the guard rather than at it — and what the
  reader was handed as a diagnosis was partspec's own implementation detail,
  that `_AXES` happens to be a dict. Two fleet agents wrote `axis=(0, 0, 1)`; a
  tuple is hashable and reached the real message, a list is not and did not.
  The exit code was 4 either way, so nothing was ever misclassified; this is
  entirely about the sentence.
  **The sweep found two more, and took two passes to find the second.**
  `iso15.bearing` guards the same way and is the reference table an author
  reaches for. `Part.param` guards the same way —
  `p.param(["plate_x", "plate_y"], min=1.0)`, bounding two parameters in one
  call, is at least as plausible as the `axis=(0, 0, 1)` that motivated the
  issue. **All three** lost #188's traceback trimming with it, since that keys
  on `ContractError` and a raw `TypeError` walks past it, so the reader got
  partspec's internal frames as well as its internal data structure.
  The first sweep missed `param` and the PR's prose was scoped so that its
  literal truth concealed the gap; the adversarial review fuzzed the whole
  public API and found it.
  All three now refuse before a raw `TypeError` can reach the reader, and two
  of the
  three distinguish a wrong TYPE from a wrong VALUE (`region.cylinder` uses one
  sentence, which already names the type it wants) — a dict is not an unknown designation, it is
  not a designation — while still naming what is available either way.
  **Two narrowings, introduced and removed within the slice, and the lesson is
  the interesting part.** A type pre-screen does not ask what a dict lookup
  asks. `isinstance(designation, int)` rejected `numpy.int64`; replacing it
  with `numbers.Integral` then rejected `Decimal`, `Fraction`, `float` and
  `numpy.float64` — the last being what a pandas integer column with one
  missing value gives you. All of them hash equal to an int key and all of them
  worked before. The lookup is now asked directly, with `TypeError` caught
  around it, which is the only test that asks the question the lookup asks:
  everything that worked still works, and nothing reaches a raw `TypeError`.
  `bool` is still excluded from the *number* branch of the message, because
  `isinstance(True, int)` is True in Python and `True` is not a designation —
  the trap `scad_literal` and `runner._number` each carry a note about.
  (An earlier draft claimed this was "the one place that skipped it". It is
  not: eight numeric guards in `contract.py` and two in `region.py` accept
  `True` as a number, including `hole_diameter`'s own `d=` and `tol=`.)
  **The messages are bounded.** All three sites now quote the operand, and on
  `main` the unhashable value died before it could be formatted — so the fix
  made the message worse before it made it better: `cylinder(axis=[0.0]*2000)`
  produced a 10 KB error and a 20 KB CLI run against main's 1.4 KB, putting the
  actionable half ten kilobytes from the start of the line. One shared
  `short_repr` caps it.
  `diff`'s handling of a report carrying a list where a gap token belongs was
  checked too, since that is an untrusted-JSON boundary rather than an API one,
  and that path is clean.
- **A solid the kernel cannot mesh is a refusal, not a stack trace** (#191).
  OCCT returns no triangulation for a face it cannot mesh and build123d assumes
  one, so `render` raised
  `AttributeError: 'NoneType' object has no attribute 'NbNodes'` straight out of
  `raster.render_views`. The CLI's last-resort handler does catch it and exit 4
  — an earlier draft of this entry said "no exit code, just a stack trace",
  which #191's own transcript refutes — so what was lost is the artifact and
  the classification: a raw traceback where a named refusal belongs, and no
  `render.json` at all. Found by a fleet adoption agent on `bd_warehouse`'s
  `IsoThread(external=False)` nut, whose thread vanishes during fusion, and
  reproduced independently.
  `check` on the SAME part reaches a real verdict, so the part is evaluable and
  only rendering it falls over — which is what the message now says, with a
  hint pointing at `watertight` and `self_intersection_free`, the checks that
  do answer on it. The agent had drawn that inference from the traceback by
  itself; the tool states it now.
  **Three clauses, not one, and the first draft had only the last.** Running out
  of memory, stack, disk or a loadable OCCT library is the ENVIRONMENT, and
  catching those with everything else answered "this shape could not be
  tessellated" at `origin="model"` with a hint telling the reader their solid
  was probably degenerate — which SPEC-report §6.1 forbids in as many words.
  `MemoryError` is the Python-level case, and
  `str(MemoryError())` is empty, so that message also ended in a dangling colon:
  the "nothing is hidden" claim failing exactly where there was nothing to show.
  Those are `origin="environment"` now, with no geometry-blaming hint — and so
  is **`Standard_OutOfMemory`, which no builtin catches**: every OCCT exception
  derives straight from `Exception`, so the first tuple missed the kernel
  running out of memory while triangulating, which is the case this entry calls
  canonical. Matched by name, which is ugly and is the only thing available.
  Three of the four builtins cannot actually fire inside `tessellate` — it does
  no file I/O, no imports and no Python recursion — and stay because the claim
  they make is true whenever they do.
  The empty-shape branch keys on the SHAPE rather than on the exception type. It
  caught every `ValueError`, so a meshing failure that raised one was reported
  as a part containing no geometry — a part with geometry, described as having
  none — and the test pinned type→message, certifying it. It asks
  `_wrapped is None` now, which is what build123d calls empty (the public
  property asserts rather than returning `None`, so asking it inside the handler
  raises again).
  What remains broad is deliberate and is not a mask: the `try` wraps a single
  call, so anything not a resource fault IS a failure to tessellate this shape,
  and the underlying type and text ride along — including a partspec bug, which
  names itself rather than vanishing. **Bounded on both branches**: the
  empty-`str(exc)` guard went into the resource branch first and was missed on
  the one that receives them. build123d's `tessellate` carries an `assert` two
  lines above #191's crash and every default-constructed OCP exception is empty,
  so the message ended in a dangling colon — under a test asserting
  `str(raised) in result.message`, vacuously true for an empty string, which
  certified it.
  **And the payload says whose fault it was.** #191 asked for "the same origin
  discipline every other engine-side failure gets" and `render`'s failure
  payload had no `origin` at all, so a consumer could not tell a degenerate
  solid from an OCCT library that would not load. It carries `origin` now, and
  `SPEC-report.md` says so. Additive; `SCHEMA_VERSION` does not move. Note this
  is the payload on **stdout**: a failed render writes no `render.json` at all,
  which the entry above says plainly and an earlier draft of this sentence did
  not.
  All of the above came from the adversarial review. It also caught the message
  saying "solid" where a `Face` reaches it unmodified, and the unlink comment
  one function down giving the weaker of two safety reasons — what makes that
  clear-before-write safe is ORDERING (the model is built before this runs), not
  the absence of `surface()` on this tier, since an OCCT-tier model is arbitrary
  Python and can `open()` a PNG.
  Also corrected while in the file: `render_views`'s docstring claimed it
  mirrors the OpenSCAD tier's "stale-artifact discipline". Since #223 and #224
  the two are opposites, and the v0.7.6 audit caught the sibling citation one
  line down without this one.
- **A pinned target that crashed is no longer reported as a deletion, and the
  remedy that destroys its claim set is no longer offered** (#201). A pinned
  target SUPPLIED on the command line but failing to resolve never reaches
  `covered_ids.add(part.id)` — `_resolve_or_report` returns an int and bails
  first — so the coverage comparison reported it as *dropped*, one line below
  the message saying the contract had raised. The advice attached to that was
  `re-pin with --pin if the removal is deliberate`, and **following it writes a
  lock without the part, permanently deleting its claim set**: a typo, a
  missing import or a half-saved file converted into a silently deleted check.
  That is the failure class PR #105's review added this guard for, performed by
  the guard's own advice.
  The run still fails at exit 4 and the pin is still reported as uncovered — a
  target that crashed proved nothing, and green would be worse. What changes is
  that the message declines to call it a deletion, names the target that did
  not resolve, and says plainly not to re-pin yet.
  **Which pinned part a failed target would have produced is not knowable** —
  the id comes from running the contract — so the message never guesses an
  attribution. But the COUNT is knowable, and the first version of this fix
  threw it away: a target resolves to at most one part, so N failures account
  for at most N uncovered ids and everything beyond that is provably deleted,
  whatever crashed. Declining there was the mirror of the defect being fixed —
  a guard refusing a conclusion it had earned, withholding the correct remedy
  for parts the failure cannot explain. It now says how many were certainly
  deleted.
  **And the destructive act itself is guarded**, which removing the advice did
  not touch. `--pin` overwrites, so a crashed target dropped a part from an
  existing lock with nothing but `pinned 2 part(s)` on stdout — the silent
  weakening `expectation.py` says the tool's job is to make impossible to do
  silently. `--pin` now refuses to write a lock that would shrink while a
  target is unresolved, rather than warning: by the time a warning is read the
  claim set is gone.
  A genuine deletion, where nothing failed to resolve, keeps the old message
  and the old advice, both of which are correct there. Each branch has its own
  test, and the hint's CONTENT is asserted rather than one spelling of it —
  `REFUSED_OUT_HINT`'s docstring records why, and four mutants
  of the first version's hint survived the suite.

## [0.7.6] - 2026-08-15

### Fixed

- **The remedy for a refused `measure --out FILE` no longer points somewhere
  that stops working.** The hint said "pass a directory", which was true until
  the entry below gave the DIRECTORY spelling of the same request its own
  refusal on the same grounds (#223). The obvious directory to reach for is the
  model's own — and `_output_over_an_input` requires `<stem>.stl` to already
  exist, so that **works on the first run and is refused from the second**, at
  a different exit code with a different message. A remedy that works once is
  harder to diagnose than one that never works. The hint now excludes the
  model's own directory by name, and a test follows it rather than reading it:
  refuse, take the remedy, and require three consecutive runs to succeed. Found
  by the v0.7.6 pre-tag audit, whose own account of the mechanism this
  corrects — it read the first run as refused too.

- **A failing scalar check now prints the number it measured and the number it
  was given** (#210). `FAIL solid_count` was the entire diagnostic: it stated
  the fact the reader already had — that something is wrong — and withheld the
  one they needed, while `report.json` two feet away held `{"value": 1}`
  against `{"equals": 2}`. For that check the value *is* the finding, and the
  two directions point at opposite causes: too few means bodies fused, too many
  means something fragmented or a support detached. The line now reads
  `FAIL solid_count — measured 1, limit equals=2` and
  `FAIL volume — measured 1125.0 mm3, limit min=5000.0`.
  **Only the scalar case was missing.** Vector checks have named their numbers
  since `_failing_axes` (`FAIL envelope — z=10 outside max=5`), and `keep_out`
  has its own sentence; the gap was every check with nothing to attribute. The
  renderer is generic rather than per-kind, which `Limit`'s own docstring
  licenses — a closed set of forms exists "so a consumer can render and compare
  limits without knowing the check kind" — so it covers every present and
  future scalar check for free. A backend that knows better still wins:
  `<kind>_detail` is consulted first, which is how the mesh tier's `watertight`
  keeps its distinction between a hole and a non-manifold junction.
  **A `bool` with an `equals` limit is the one kind that gets nothing**, and
  the reason is a proof rather than a taste: for a two-valued measurement,
  `equals` plus `FAIL` determines the value in both directions, so
  `measured false, limit equals=false` restates the id and the status and adds
  no fact. That is what the OCCT tier printed for `watertight`, having no hook
  to win ahead of it.
  Four things fell out of writing it. `_render` handled three of `Limit`'s four
  forms and said nothing at all about `choices` — unreachable through the
  contract API today, so the first check to use one would have rendered
  `limit ` with nothing after it. Both halves of the comparison now go through
  **one** number formatter, because they did not: a large value printed
  `measured 1.23456789e+09 mm3, limit min=10000000000.0`, two notations for the
  single comparison the line exists to enable. **All three callers**, which
  took two rounds: routing only `_render` through the shared formatter created
  the same two-notation defect on the parameter path (`p.param("hole_d",
  max=1e9)` printed `hole_d=10000000000.0 outside max=1e+09`) and left it
  untouched on the vector path, where a `1000.0002` against `max=1000.0` still
  printed `x=1000 outside max=1000.0` — a failure line reading as an equality,
  which is the exact collapse the format was chosen to prevent. Vector axis
  values now show their type too, so `envelope` reads
  `z=10.0 outside max=5`. The limit's own forms join with
  `and` rather than a comma, since the caller already puts a comma between the
  measurement and the limit and one separator cannot do both jobs — and
  `choices` braces its members, because it is the one form with an internal
  list and reproduced that ambiguity two lines after removing it. And the
  format is `:.9g` for the reason `hole_diameter` records at its own: six
  significant figures collapse numbers a reader must see apart — `1000.0002`
  against `max=1000.0` is a real failure that `:g` renders as `1000` on both
  sides.
  A `<kind>_detail` hook may decline (`-> str | None`) and none does today, so
  the fallback is chained rather than `elif`-ed for the first one that will —
  the same footing as the `choices` branch, written for a caller that does not
  exist yet.
  The numbers land in the report's existing `detail` field, so a consumer gets
  them too; prose stays prose and the typed `measurement`/`limit` fields are
  unchanged, per the principle SPEC-report states at §6.1 for `origin` and in
  its post-v0.1 Q8 resolution for `components` — data a consumer branches on is
  a field, and `detail` is prose. (Not "§7.1's rule": §7.1's only word on
  `detail` sanctions putting a bore inventory in it, which is the opposite.
  Round-2 review of #232, and the same misattribution round 1 found in the
  `:.9g` citation.) `detail` is in `diff`'s `NON_CLAIM_FIELDS`, so nothing here
  can make two identical runs compare `different`. No schema change.

- **Correction to 0.7.5: the fleet-01 `diff` figure below is wrong, and the
  right one is 87** (#217). That entry says "3/3 CadQuery replicates
  indeterminate over **73 real invocations**". Counted from the frozen fleet-01
  logs, arm A ran **90** `diff` invocations, 3 of them `--help`, so **87 real**,
  of which **79 exited 2**: a1 ×3 (3 at exit 2), a2 ×71 (63), a3 ×13 (13). The
  released section is left as shipped and corrected here, per this file's rule
  that a published entry takes form-only edits.
  **The qualitative claim is confirmed and unaffected** — 3/3 arm-A replicates
  went indeterminate and 0/3 arm-B ones did, on the same command and version.
  One nuance the original sentence flattened: only **two** of the three arm-B
  replicates ran `diff` at all (b1 ×3, b2 ×3, both `identical` at exit 0); b3
  never ran it, so 0/3 is true as a count of replicates that hit the defect and
  is not a count of three that tried.
  **Where 73 came from, since a wrong number with no story invites the same
  mistake:** the fleet report's table sums `a1 ×3 + a2 ×57 + a3 ×13`, and that
  `a2 ×57` matches arm A's **whole** non-control total — a1 ×3 plus a2 ×41 plus
  a3 ×13 is 57 exactly, so summing the row counts a1 and a3 twice and 73 is the
  double count. **That is the reading that reproduces, not a recorded
  lineage.** "Non-control" here means any argv element containing `control`,
  which is this entry's definition and not the study's: `analyse.py` has no
  notion of a control at all, and `PROTOCOL.md` codes `control` over non-zero
  exits by argv and target names. The fleet-wide `--help` total is also exactly
  57, three rows above in the same table, so the attribution is inference and
  is stated as one — which is the whole point of the bullet.
  This bullet said the opposite in its first form — that `57` "matches no
  reading of the frozen log". That was false, and #217 itself prints the
  counter-example ("57 excluding controls"); the reading was applied at
  replicate scope and never at the arm scope the report's row is about, which
  is where it resolves. Found by the adversarial review of this change: a
  correction whose subject is unsupported claims, making an unsupported
  universal negative refuted by the record it cites.
  The issue also cites `docs/SPEC-diff.md:87-90` as carrying the figure. It
  does not and never has: `git log --all -S` puts "73 real" in this file only,
  the spec's version of the sentence names the ratio without a count, and a
  wrapping-defeat sweep of every `+`/`-` line ever touching that file finds no
  73 in any form.

- **A build no longer destroys the input it derives its own artifact name from
  — on `check` as well as on `measure`, and on every path in the OpenSCAD
  engine.** ("not yet on every path" until the entry below closed #224 — and
  it is still not every path in the tool. Seven `unlink` sites remain outside
  `engines/openscad.py`; `report.py`'s is the atomic-write scratch and belongs
  to nobody's output, leaving six that clear a derived file. Two clear
  `render.json`, an output on every tier. One is `raster.render_views` clearing
  `renders/<view>.png`, reached only from the OCCT branch, which has no
  `surface()` to make a PNG an input. **Three clear
  `renders/section_<plane>.png`, and the OpenSCAD tier reaches two of them** —
  `cli` hoists one above every refusal inside its `engine == "openscad"` branch,
  `raster.render_section` is called from both branches, and `cli`'s other one
  is OCCT-only. Those two are the same defect class on a section image,
  measured: `render --out DIR --section xy:999` deletes an existing
  `renders/section_xy.png` and then reports `renders: {}` at exit 4. Filed as
  #233 rather than fixed here, because unlike #224's cases it is a genuine
  trade — the hoist exists so a failing section cannot leave the previous run's
  image to be read as this run's — and that call deserves its own slice.
  This parenthetical has now been wrong twice: the first version had the count
  and the tier wrong, the second claimed six and enumerated five while missing
  the third section unlink. Both found by adversarial review, of #230 and of
  #234.)
  `engines/openscad.render` unlinked `<out dir>/<source stem>.stl`
  before invoking the engine, so a model whose `import()` target sits at that
  derived path built without it. Filed as a `measure --out DIR` bug (#208); it
  is a bug in `render`, which means `check --out DIR` reached it too, and that
  is the worse half — measured on the filed repro, `partspec check spec.py:part
  --out .` printed `PASS: 2 pass` for `envelope(max=(20,20,20))` on geometry
  that was not the part, at exit 0, with the input gone. `measure` answered
  `bbox [5,5,5] volume 125` where the part measures `[8,7,11]` / `356`. The
  engine now exports into a scratch directory under the output directory and
  the result is moved into place with `os.replace` only once it exists and is
  non-empty, so the output directory is write-only for the whole render — the
  shape `_build_to_file` already used for the filename form of `--out`, and the
  one `SPEC-backend.md` §5 step 1 already spells the invocation with
  (`-o <tmp>.stl`), though that spec is illustrating the command rather than
  requiring the temporary. The unlink's
  stated reason dies with it: the exists/non-empty guards now ask about a file
  in a directory this call created empty, so no previous run's mesh can answer
  them (pinned by a test against a stub engine that exits 0 writing nothing,
  because the installed 2021.01 exits 1 on empty geometry and cannot reach that
  branch). A failed render, a blown timeout or a Ctrl-C now leaves whatever was
  there rather than deleting it.
- **`render`'s two siblings no longer delete their outputs before the engine
  reads them either** (#224). `render_views` unlinked
  `<out dir>/renders/<view>.png` per view and `render_section_stl` unlinked
  `<stem>.section.stl`, both citing a rule in `render()` that the fix above
  deletes. The first is reachable: `surface(file = "...")` reads a PNG as a
  heightmap on both engine versions, so `render --out .` against a model
  reading `renders/iso.png` destroyed that heightmap before invoking the
  engine, then rendered and reported the part built without it — measured on a
  first run into a clean directory, exit 0, nothing on stderr. Both now export
  into a scratch directory and move the result into place. **The four views
  move together, once all four exist**, which the per-view shape would not
  have fixed: the model is re-parsed once per view, so a view written as it
  finished would be read by the *next* view, and the four images would depict
  four different parts — pinned by a test that records what the engine found
  at that path on all five invocations. A failure while **rendering** leaves
  the previous set of renders intact rather than half of it overwritten, and
  `render_section_stl` no longer writes its `<stem>.section.scad` into the
  caller's directory at all (the cut script names the mesh it imports by
  resolved absolute path, so it relocates with nothing to re-resolve).
  **A failure while MOVING cannot leave it intact**, and this entry claimed it
  did until the adversarial review of #230 measured otherwise: with a directory
  sitting at `renders/top.png`, two views were replaced before the third move
  failed, and the `BuildError` said the artifacts could not be written while
  half the set was already new. There is no atomic rename of four files, so
  the case that is knowable up front is now refused before the first move —
  naming the blocking path and stating that nothing was touched — and a move
  that fails anyway reports how many were replaced rather than implying none
  were — and says plainly that nothing was moved when nothing was, since
  "the 0 view artifact(s) already moved … are from this run and the rest are
  not" described a corrupted directory that was in fact untouched. That is the
  thesis inverted, in the branch added to stop exactly that; it shipped in this
  entry's first form, which also claimed both layers were pinned when the
  second had no test at all. Found by the adversarial review of #234, along
  with a pre-flight that refused a symlink pointing at a directory: `is_dir()`
  follows symlinks and `rename(2)` does not follow its destination, so a render
  that had always worked was refused and the symlink was called a directory.
  All three now pinned, and the unwritable-directory test relabelled — it
  passes unchanged against its own parent and characterises behaviour #230
  shipped, which its first docstring claimed as new and attributed to two call
  sites that are not involved.
  The residue is the one `render()` also ships with and #226 closes: the move
  at the end still replaces whatever sits at the destination. It is not a lost
  file. Measured for views — a model reading `renders/iso.png` as a heightmap,
  with `--out` pointing at a directory that CONTAINS that file, renders
  correctly once and then reads its own output at exit 0 on every run after.
  The condition matters and the first version of this sentence omitted it:
  OpenSCAD resolves `surface(file=)` against the entry file's directory, so
  with `--out` genuinely elsewhere the written PNG never lands on the read one
  and three consecutive runs are identical (adversarial review of #234).
  Unlike
  `render()`'s case there is no directory-collision refusal here at all:
  `_output_over_an_input` knows only `<stem>.stl` and fires only when the out
  dir is the source's own, which a view directory need not be.
- **A render into the model's own directory is refused when it cannot be told
  from an input.** Non-destructive building fixes the measurement and not the
  file: `os.replace` still lands the artifact on top of the input at the end.
  `Closure.reads_external_data` is a bool by design — a data path may be
  computed at render time — so the refusal is conservative and narrow, firing
  only when the output directory resolves to the source's own directory AND the
  closure is partial AND `<stem>.stl` already exists there. All three clauses
  exist to avoid over-refusing: without the first, every REPEAT run of any
  external-data model against the default `outputs/<slug>` would be refused for
  finding its own previous artifact. It therefore **under-refuses, and the cost
  of that is not one file.** For a model importing `sub/<stem>.stl` run with
  `--out sub`, the artifact REPLACES the import instead of deleting it, so the
  import still resolves and the model eats its own output. Measured over three
  identical consecutive runs against a 3x7x11 donor: `[8,7,11]`, `[13,7,11]`,
  `[18,7,11]`, every one at exit 0 — and `check` with `envelope(min=(12,7,11))`,
  a claim FALSE of the real part, fails at run 1 and **passes at run 2**. That
  is #208's own headline symptom surviving in a narrower case, and the same
  compounding the #187 review recorded (`[30,10,10]`, `[50,10,10]`,
  `[70,10,10]`). It ships that way because every rule wide enough to catch a
  subdirectory import also refuses legitimate output directories, and
  over-refusal breaks the ordinary run rather than a rare one; the real remedy
  is a signal saying which files a render actually READ, tracked as #226.
  The compounding is pinned by an executing test, not described. The
  refusal is `origin="environment"`, so `check` reports it as a run-level fault
  with every check skipped rather than as a failing `builds` (SPEC-report
  §6.1), and both verbs exit 4.
- **`measure --out DIR` on a tier that exports nothing now says so, in both
  channels.** The OCCT tiers build in memory, so there is no artifact for
  `--out` to place. The *filename* spelling of that request has exited 64 with
  a named reason since 0.7.5; the *directory* spelling accepted the path, wrote
  nothing and exited 0 in silence — two spellings of "put the artifact here" on
  a tier that has none, one named and one not (#204). The payload now carries
  `artifact: {requested, written: false, reason}` and stderr says the same
  sentence, because a fact living only on stderr is invisible exactly where a
  machine is the audience (#47) — one `reason` string feeds both. Exit stays 0:
  the measurement succeeded and is this verb's product, and discarding it over
  an unfulfillable side-request costs the caller more than the no-op flag does.
  The key is present wherever `--out` was passed, in one state or the other
  (see below); it is additive, and
  `SCHEMA_VERSION` does not move. `check --out` is untouched — it writes
  `report.json` into that directory on every tier. `SPEC-report.md`'s Scope
  states the rule. **The issue's other half does not reproduce and did not need
  fixing:** `measure --out DIR` was reported to leave an empty directory
  behind, and it never created one — not at v0.7.5, not at the commit the issue
  was filed against (`aa08dc0`), and not at v0.7.4, v0.7.0 or v0.6.0, on either
  OCCT engine. The OCCT backend's `build()` has documented `out_dir` as unused
  since it was written, and nothing else in `measure`'s directory path calls
  `mkdir`. What the sweep establishes is that `measure` never created it; it
  does not establish what the reporter saw. `check --out DIR` does create the
  directory and writes `report.json` into it, which is the nearest behaviour
  that exists.
- **A locally built sdist is the CI sdist again** (#218). `uv build --sdist` in
  a working checkout shipped `.claude/scheduled_tasks.lock`: Claude Code's
  runtime state lived only in `.git/info/exclude`, which is local to one clone
  and which hatchling does not read, and it was absent from the sdist exclude
  list too. **The published artifact was never affected** — `release.yml`
  builds from a clean CI checkout — but a dev-built tarball is only worth
  building if it is the same tarball, which is the property that makes local
  verification mean anything. `.gitignore` now carries `**/.claude/`, which
  hatchling honours and which is already how `outputs/` stays out (`notes/` has
  a `[tool.hatch.build.targets.sdist] exclude` entry as well, so it is not a
  clean example of the mechanism). The same shape as the `notes/` leak #150
  fixed, through a different door, and the test that should have caught it
  could not: it asserts exclusions **by name**, so each new tree gets in free
  until someone notices.
  **This shipped twice before it was right.** The first form copied the ten
  entries `.git/info/exclude` happens to name, root-anchored — so
  `examples/.claude/scheduled_tasks.lock` still reached the tarball with both
  sdist tests green, and anything Claude Code wrote that was not on the list
  (a `history.jsonl`, a `todos/`) was a leak or a red local suite waiting.
  The adversarial review of this change measured both. It is now the whole
  directory at any depth, and the new test grew a second clause to match: an
  allowlist over the **top level** (a new one has to be argued for; per-file
  would fail on every module added and be deleted within a month) *and* over
  **dot-directories at any depth**, which is where tool and agent state always
  lands. Nothing under `.claude/` is tracked here, and this repo's own agent
  material lives in the top-level `skills/`, which ships.
- **`release.yml` no longer explains its `setup-uv` pin with a convention the
  file does not follow** (#218). The comment said `astral-sh/setup-uv@v9` would
  fail as "the floating-major form every other action here uses" — and no
  action in that file used one: the rest are `@v7.0.1`, `@v7.0.1`, `@v8.0.1`
  and a SHA. The conclusion was right and the pin stays; the stated reason
  invited the next reader to conclude the exact pins were the anomaly and tidy
  them into real floating majors. The corrected comment says every action in
  the file is pinned to an exact patch or a SHA, and a test enforces that
  rather than leaving the paragraph to assert it. Pre-existing, from #173.
  **The first version of that test checked less than the comment claimed**,
  which is the same defect in the fix for it: it rejected `@vN` alone, so
  `@main` — the most mutable ref there is, on the checkout step the release
  gate's whole safety argument runs from — passed, as did `@latest`, `@7`,
  `@V7` and the quoted `"…@v7"` form, which is valid YAML and slipped the
  pattern because `\S+` swallowed the closing quote. Found by the adversarial
  review of this change. The rule is now the comment's rule — a 40-hex SHA or a
  version carrying a full major.minor.patch — so anything a release could move
  under, `@v7.0` included, is rejected by not matching rather than by being on
  a list of forms someone thought of.
- **`SPEC-diff`'s artifact sample no longer shows a version the tool has never
  emitted** (#219). The sample carried `"tool": {"name": "partspec-diff",
  "version": "0.2.0"}`; `diff` emits the **partspec** version and has never had
  one of its own, so `0.2.0` is not a stale value but a fictional one — and
  this is a normative document whose sample is what a reader copies when
  writing a consumer. The sample now shows a real value and says where it comes
  from, so the next reader does not reinvent an independent `diff` version.
  `SPEC-report.md`'s sample was checked for the same drift and carried
  `"version": "0.1.0"` — stale rather than fictional, since that was a real
  release — and is corrected the same way. Both now point the reader at
  `schema_version`, which is the field a consumer is supposed to key on.
  Pre-existing, from #88.
  **And the literal is now pinned rather than trusted**, because correcting it
  by hand fixed the instance and left the mechanism: nothing read those values,
  so both would have gone stale again at the next bump — the adversarial review
  of this change made exactly that point. A test asserts each sample's version
  equals the installed one. The cost is a line per spec per release and the
  failure names both files and the value to use.

### Added

- **`measure --out` now says where the artifact landed, on the tier that
  writes one** (#225). The entry above only ever appeared to report a
  shortfall, so on the OpenSCAD tier a caller who passed `--out DIR` got exit
  0, a file on disk, and nothing in the payload saying where — leaving them to
  re-derive `<source stem>.stl`, a name partspec owns and has already moved
  once (#187). The directory was the caller's; the filename inside it is not.
  A successful `--out` now carries
  `artifact: {requested, written: true, path}` in the same key, which cost
  nothing to add because #204 made `written` a value rather than an inference
  from the key's presence. Both spellings report through it: for a filename
  destination `path` is the normalised destination rather than an echo —
  `--out ./x.stl` reports `requested: "./x.stl"` and `path: "x.stl"` — so a
  consumer reads one field instead of branching on the caller's phrasing. No
  `--out`, no key — a report of a request nobody made is noise. Additive, so
  `SCHEMA_VERSION` does not move; `SPEC-report.md`'s Scope states the rule.

## [0.7.5] - 2026-08-14

### Added

- **`part.source_closure` now says which distributions the model imported, and
  names its own gaps.** Two additive fields on both tiers, `schema_version`
  unchanged. `imports` maps each import to how it was identified: `metadata`
  where every loaded file of a distribution is declared in its installer's
  RECORD — version plus a digest over the RECORD's own hashes, ~0.1 ms — and
  `content` where a loaded file is declared by no RECORD, which byte-hashes the
  package tree. The second tier is the one the fleet-01 study needed and the
  one no cheap mechanism can replace: all three arm-A agents imported a
  `sys.path` checkout of `cq-gridfinity` (17 files) while the venv reported
  0.5.7 from a different, 12-file copy, so `importlib.metadata.version()`
  described code that never ran. Ownership is checked per file against **whole
  RECORD rows**, never a first path segment, because distributions routinely
  share a top-level directory (`zope.*`, `google.*`, `sphinxcontrib.*`,
  `ruamel.*`, `jaraco.*`) and this repo's venv holds a five-way `trame`
  collision. Distributions whose RECORD-declared bytes were not loaded are
  never named — and neither are those whose only loaded file is setuptools'
  `__editable___<name>_finder.py`, which `pip install -e .` writes into
  site-packages and lists in the RECORD: counting it hands a `metadata` entry
  to a library nothing imported, over a shim whose `MAPPING` embeds the
  checkout's absolute path, so two byte-identical editable installs at two
  paths disagree. The map covers what was imported **after partspec was**,
  which keeps the tool itself and `_virtualenv` out of every part's inputs:
  `partspec` is already `tool.version`, and in a dogfood loop it is
  editable-installed, so recording it would move an input on every part after
  any edit to the tool; `_virtualenv` says which program created the venv.
  Measured across the fleet's three venvs and this repo's, that baseline is
  exactly those two names and nothing else. `unseen` names the gaps from a
  closed vocabulary —
  `native_reads`, `unidentified_imports`, `external_data_reads`,
  `unresolved_includes` — and `partial` is now **derived** from it,
  `partial == bool(unseen)`, with the same value in every case it had before: a
  namespace package with no `__file__` is now a named gap instead of a silent
  omission. An unrecognised token MUST be read as a bounded gap, so an older
  consumer of a newer report fails closed. An **absent** `imports` is not
  "nothing imported" — it is a report written before the question was asked,
  which is why the OpenSCAD tier emits `{}`. Two bounds are stated rather than
  implied, because a spec that overclaims is the defect this field exists to
  fix: a `content` digest covers the package tree it was loaded from and
  cannot reach a distribution's vendored sibling directory when no RECORD
  exists to associate them (which is why the `cadquery_ocp.libs` case is
  defended on the `metadata` tier, where the RECORD names all 69 of them), and
  an edit to a file a RECORD *does* declare leaves that entry `metadata` with
  an unmoved digest, since ownership is decided by path and hashing every
  loaded file is the cost this tier exists to avoid (§8.3 rules 5 and 6,
  §7.1). **Recording the fields changes no `diff` behaviour, verdict or exit
  code by itself** — what the comparator does with them is the `diff` entry
  under **Changed** in this same release, and that one does move verdicts and
  exit codes (stage 3 of #190). Cost, measured
  against 6e9b67e: the OpenSCAD tier is unchanged (+1.6 ms, +0.29%, it builds
  no index — `_record_index.cache_info()` after a full run is
  `hits=0, misses=0`), and the Python tier pays one RECORD
  index per process — 62.5 ms cold / 57.9 ms warm in the fleet's
  84-distribution venv, 100.9 / 65.2 in this repo's 114-distribution one — for
  +62 ms warm and +29 ms cold end to end on a 5.2 s cadquery run (+1.2% /
  +0.6%), +86 ms warm and +119 ms cold on a 2.7 s build123d run (+3.2% /
  +4.3%). Distributions the installer already describes are **not** byte-hashed:
  hashing everything imported measured 836 ms warm / 1921 ms cold over 1270 MB,
  70% of it `vtk` and `casadi` (#190, stage 2 of 4).

### Changed

- **`diff` is no longer permanently indeterminate for a contract that wraps a
  library.** `SPEC-diff.md` §2 rule 3 keyed on `source_closure.partial`, which
  the Python tier sets unconditionally, so the version-bump gate — *re-run this
  evidence when the library moves, tell me if the part moved* — could never
  answer on that tier. Measured in the fleet-01 adoption study: 3/3 CadQuery
  replicates indeterminate over 73 real invocations, 0/3 OpenSCAD ones, same
  command and same version, the only variable being that OpenSCAD libraries are
  source on disk and Python ones are installed distributions. The rule now keys
  on the **class of each named gap** in `unseen`. `native_reads` — a C
  extension reading a file with no Python event to observe it — is
  *irreducible*: it is a property of the tier, present in every Python report
  that will ever be written, so it cannot discriminate between two of them and
  no longer produces a verdict. It is printed instead, on **every** outcome,
  permanently, as a `not covered:` line beside a `covered:` line saying what
  the comparison did reach. That trade is empirical and is the one thing in
  this change to scrutinise: all three CadQuery agents responded to the blanket
  exit 2 by writing shell to suppress it, and a universally suppressed verdict
  protects less than a universally printed caveat. Every other token stays
  **bounded** and still blocks `identical`, *including a token this version does
  not recognise* (`SPEC-report.md` §8.3 makes failing closed a MUST), so
  OpenSCAD's external-data and unresolved-include cases are unchanged — #198's
  behaviour is narrowed by no case. `diff` also compares the closure's
  `imports` map entry by entry and reports it as `source.imports`, splitting a
  version that **moved** from an import that **appeared or disappeared**; a
  distribution whose identity tier flipped (`metadata` ↔ `content` — an
  ordinary install against an editable one) is a changed build input, not a
  gap, since the two digests are over different things. A moved library with no
  moved check is **`identical` at exit 0**, with the distribution named on the
  summary line: OpenSCAD already got exit 0 for a changed `.scad` closure under
  unmoved checks, and a second rule for Python would rebuild the very asymmetry
  this fixes. A gap discards observed movement from the **verdict** and from
  nothing else: the closure digest keeps its own artifact field
  (`source.closure_digest_changed`), since a bounded gap collapses
  `source.closure` to `inconclusive` and would otherwise take the only record
  of closure movement with it; and where movement *was* observed the
  indeterminate message names it and drops the sentence *"nothing this diff
  can see changed…"*, which through v0.7.4 was unreachable in that state and
  would now be asserting nothing-was-seen one line above the line naming what
  moved. Where nothing moved, that sentence is unchanged and verbatim.
  Malformation fails closed and is kept distinct from age: a field **absent**
  is "written before the question was asked" (`imports_not_recorded`, whose
  remedy is to re-record), a field in the **wrong shape** is
  `malformed_closure` on either tier, and `partial` disagreeing with
  `bool(unseen)` is `unnamed_partial` — v0.7.4 exits 2 on `partial: true`, and
  each of those states exited 0 somewhere before review caught it.
  `DIFF_SCHEMA_VERSION` is now `2` — diff's own output, so no
  stored report is refused — and the report `schema_version` is untouched.
  **Upgrading: re-record your Python baseline to get exit 0 again.** A report
  written by 0.7.4 or earlier carries no `imports`, which is not "nothing
  imported" but "never asked", so `diff` synthesises the bounded gap
  `imports_not_recorded` and keeps returning exit 2 with the remedy named —
  exactly what such a comparison already returned, so no gate changes verdict
  behind anyone's back. That absence rule applies only where the field could
  have carried an answer: a pre-0.7.5 **OpenSCAD** closure that was complete
  keeps its exit 0, because synthesising a gap there would raise a first alarm,
  on upgrade, about a question that tier never had. One behaviour does tighten:
  a bounded gap beside a **moved** closure digest is now `indeterminate` where
  it was `identical` at exit 0, since "changed" was never outcome-bearing and
  the identical claim was unearned (#190, stage 3 of 4).

### Fixed

- **Two migration diagnostics stated a fault and withheld the remedy their
  own specs promised.** `SPEC-diff.md` §2 rule 3 said this comparison "names
  re-recording the baseline as the fix", the #190 stage-3 entry above said it
  "keeps returning exit 2 with the remedy named", and `diff.py`'s comment and
  its test said it too — while the run printed the cause and stopped:
  *"indeterminate: … the old report was written before partspec recorded
  imports (0.7.4 or earlier): its source identity covers one directory, so
  nothing this diff can see changed…"*, with no remedy in the output or the
  artifact. That is the only exit 2 an upgrading user hits. A bounded gap that
  has a remedy now carries it on the `indeterminate` entry as `remedy` and
  prints it as its own line under the headline — its own field because the
  `reason` ends in a sentence §2 rule 3 fixes verbatim, so a step spliced in
  there would read as the consequence of the step. A gap with no remedy is
  not given one: `unidentified_imports` is a property of how a package is
  distributed, and an invented remedy sends a reader to do work that cannot
  help, which is what the bare cause already did. Second, the
  `environment.packages` widening printed as a positive finding: the first
  diff after an upgrade said *"identical: example-spacer — no semantic
  differences; packages appeared: PyJWT 2.13.0, PyYAML 6.0.3, +107 more"* at
  exit 0 — 109 installations reported, none of which happened — while
  `SPEC-diff.md` §3 and the #211 entry below both already said "nothing was
  installed; re-record the baseline to clear it". The comparator could always
  tell: an old report's closure carries no `imports`, which is the same
  structural evidence the gap rule reads to date one, and no `tool.version`
  has to be parsed. Those names are now listed in
  `environment.packages.first_recorded` — still inside `added`, which is what
  that group means — and reported as *"N packages recorded for the first
  time: … nothing was installed, and re-recording the baseline clears it"*.
  The split is by name against the pre-0.7.5 five: `trimesh` absent from an
  old report genuinely was not installed, so it stays an appearance and is
  reported as one on the same line. No verdict or exit code changes in either
  half (#190, #211).
- **`source_closure.imports` recorded a per-process fact as a per-part one.**
  The map is read from `sys.modules`, and `partspec check` runs *"several
  targets share one process, one report each"* — so a Python part behind
  another one inherits every distribution the earlier target loaded. Measured:
  the same build123d cube recorded **38 imports alone and 44 behind a CadQuery
  target**, `cadquery` among them, and `diff` over those two reports of one
  part — same source, same versions — said `identical: b3-cube — no semantic
  differences; inputs appeared: cadquery 2.8.0, casadi 3.7.2, +4 more` at exit
  0. Six build inputs positively claimed to have arrived, and none had. The
  bound was known and lived in one private docstring, while `SPEC-report.md`
  §8.3 headed the field *"the distributions the model loaded"*. The map is
  **unchanged and still wide**: a producer reporting only what arrived after
  its target began would drop a library the second target genuinely uses
  whenever the first loaded it first, which is the under-reporting direction
  the field exists to refuse. What is new is the claim it makes.
  `part.source_closure.preloaded` lists, sorted, the entries that were already
  in `sys.modules` when that target's contract was resolved — the ones the
  report cannot claim as its own — and it is `[]` for a target that ran first
  or alone, verified from a cold CLI. Only the caller that owns the loop can
  take that snapshot: by the time the runner has a part, its contract has been
  imported, and a contract's own imports are its part's. Python tier only, the
  OpenSCAD render being a subprocess that imports nothing, and malformed the
  way `unseen` and `imports` already are — a `preloaded` **present** in a
  shape §8.3 does not define is `malformed_closure` at exit 2, since reading
  an uninterpretable field as an empty one put the entry straight back into
  `inputs appeared` at exit 0. Absence is not a shape and stays untouched, so
  no older producer and no OpenSCAD report is affected. `diff` **qualifies
  rather than asserts**: an `added`/`removed` entry either side named there is
  reported as `inputs not attributable: …`, stating that this comparison
  cannot tell an input that moved from one inherited from an earlier target —
  the inability `preloaded` evidences, and never a cause it does not, since a
  part that genuinely starts importing a library its batch neighbour also
  loads is indistinguishable from here (measured at batch position 2 of 2 in
  both runs). They are counted apart under `covered:` and listed in
  `source.imports.unattributable`. They still make `source.closure`
  `changed` — that field says the two reports **recorded** different closures,
  which two differing maps do, while `unattributable` says whose import nobody
  can tell; a reader keying on `source.closure` alone must consult it, and the
  spec now says so. Suppressing it there made the artifact assert `same` over
  a difference it was carrying in `imports.added` in the same object.
  Movement the `preloaded` sets do not explain keeps its wording exactly, a
  version that moved under an inherited import is still a move, and two
  reports carrying the same `preloaded` set with nothing moved print nothing
  at all. **No verdict and no exit code changes** — the comparison above is
  `identical` at exit 0 before and after — and this is deliberately not an
  `unseen` gap: a bounded gap there would make every multi-target Python diff
  indeterminate, which is the state #190 stage 3 removed (#190).
- **`environment.packages` recorded five hardcoded names and `diff` read none
  of them.** `SPEC-report.md` §8 rule 2 says in bold that the field MUST NOT be
  excluded from comparison — it is what distinguishes "a trimesh upgrade moved
  this number" from "the design changed" — and `diff` compared exactly
  `tool_version`, the engine version and the render backend, so a dependency
  bump produced a verdict with nothing on the page to explain it. Both halves
  are fixed. The field now records **every distribution installed in the
  environment** instead of the allowlist `build123d`, `cadquery`,
  `cadquery-ocp`, `trimesh`, `manifold3d` — which could not see the library a
  contract wraps, and so never named `cqgridfinity` in any report of the study
  that found #190. It enumerates installations rather than imports on purpose:
  the field lives in the `environment` block, several targets share one
  interpreter, and a `sys.modules`-derived value made a part's recorded
  environment a function of which unrelated target ran before it — measured on
  the first cut of this change, `examples/spacer` recorded 6 distributions
  alone and 41 behind a build123d part, claiming `build123d` and `cadquery-ocp`
  as inputs to an OpenSCAD build that never touched them, which rule 2 forbids.
  Which distributions *a part* loaded belongs to `part.source_closure`, where
  byte-level identity lives — which reads the same shared `sys.modules` and so
  carries the same batch dependence, stated there as a bound (`preloaded`,
  §8.3 rule 7) rather than escaped: scoping the question to the part is what
  made it statable, not what removed it (#190). `diff`
  compares the map in three groups, because a version that **moved** is a
  changed build input that explains a moved measurement, while a package that
  **appeared or disappeared** is usually two machines resolving different
  transitive dependency sets and explains nothing on its own; reporting them
  together would leave the reader to separate them by hand. Where a side
  carries no usable map the artifact says `uncomparable` rather than omitting
  the key, since an omission is indistinguishable from "no dependency moved".
  No verdict or exit code changes. The one-line summary names the moves on
  every outcome, `identical` included — a dependency that moved under an
  unchanged part is exactly what an unqualified "no semantic differences"
  would misreport — bounded at two names per group with the remainder counted,
  because the inventory now runs to dozens of entries. **The first comparison
  against a baseline recorded by v0.7.4 or earlier reports the widening as
  appearances**: the old field held at most five names, so every other
  installed distribution is `added` against it. Nothing was installed;
  re-record the baseline to clear it. Measured on this repo's
  114-distribution venv: 57 ms cold with the page cache evicted, 26 ms warm,
  cached per process so later targets in a batch pay nothing — end to end
  +23 ms on an OpenSCAD-tier run, 534 → 557 ms, the tier with no 956 ms build
  to hide it. The MCP layer runs the CLI as a subprocess per call by design, so
  it pays the cold cost on every call (#211, stage 1 of #190).
- **`scad-magic-number` flagged two positions where the literal already has a
  name, or is not a dimension at all.** A parameter default on a
  `function`/`module` **declaration line** fired (`module post(h = 40)`), while
  the identical default wrapped onto a continuation line did not: the
  exemption — which the rule's own comment says covers "the named argument and
  signature-default case" — is keyed on a **line-leading `name =`**, and a
  declaration line never is one, because it leads with `module` or `function`.
  A wrapped signature's continuation line is (`    h = 40`), which is the
  whole of why the rare form escaped. Paren depth is not the cause and #205's
  suggested remedy was measured not to work: `depth` feeds the multi-line
  assignment opener alone and never the exemption, so advancing it earlier
  leaves the output byte-identical. The common form was flagged and the rare
  form was tested, which is how it survived. Defaults are exempt whether scalar or vector —
  `module plate(size = [60, 40, 4])` is the ordinary way to spell a size, and
  exempting only the offset past `name =` would have left that half of the
  report unfixed — and it is the DEFAULTS that are exempt, not the line: the
  walk stops at the parameter list's closing paren, so a one-line module's
  body literals still fire (#205). Separately, an integer **subscript index**
  fired past `MAGIC_EXEMPT`: `type[3][0]` is a field offset into a registry
  row — no unit, unreachable by `-D`, never a `param` or a report — so the
  accessor idiom that exists to replace magic indices with names drew one
  finding per field past the third. A `[` following an identifier or a `]` is
  now read as a subscript; a `[` opening a vector literal (`size = [3, 4]`) is
  not, a keyword before the bracket is not an identifier (`each [100, 200]`
  splats, and its literals stay flagged), and integers only, so `v[3.5]` stays
  visible (#206). Measured on the repo's own `examples/` and `.scad` fixtures:
  34 findings before, 34 after — though that corpus contains no vector default
  at all, which is why the case carries a fixture of its own rather than a
  count.
- **A contract that raised printed partspec's own call stack before its
  answer.** Six internal frames wrapped the one useful one — the reader's own
  contract line — and a `ContractError` is partspec's own exception, raised
  deliberately with a message written for the reader, so its internal path is
  never the diagnosis. The traceback stays, because a contract is arbitrary
  Python and for a `TypeError` in user code the frame is the only thing that
  says *where*; partspec's frames are dropped from it. Frames from a library
  the contract called are kept — a CadQuery operation that raised four calls
  deep is where the failure happened. Every gap left by a dropped frame carries
  a `[N frames hidden]` marker, so the reprint cannot be read as a call chain
  that never happened, and surviving frames are formatted in runs so CPython's
  `[Previous line repeated N more times]` collapse survives — formatting them
  one at a time turned a recursive contract's 20-line traceback into 1995
  lines. Four cases still print unfiltered, because a
  filter that hides a partspec bug is the silence this tool exists to refuse: a
  stack with no contract frame at all; a non-partspec exception with a partspec
  frame *inside* the failure rather than merely on the way to the contract (an
  `AttributeError` from partspec's own code is a bug report, and its frames are
  the report); an exception group, which renders header-only through the
  filtered path and would lose every sub-exception and the contract lines
  inside them; and a chained exception, whose other segments are information.
  The chain case leaves `try/except → raise ContractError(...)` — an idiomatic
  contract — printing unfiltered; filtering each segment independently means
  reproducing CPython's chain and group formatting by hand, and is deferred
  rather than guessed at. Presentation only — the exit code (`4`), the "the
  contract is wrong, not the part" classification and the report are
  unchanged. (#188)

- **`measure --out` described the artifact and took a directory, so a filename
  became a directory of that name.** `--out out/a.stl` created a *directory*
  called `a.stl`, wrote `spacer.stl` inside it and exited 0 — silent success,
  the one outcome this tool exists to refuse — while the same command against
  a path that already existed as a file exited 4, so prior state decided what
  the flag meant. An adoption agent hit it four times in a row.

  A path ending in **`.stl`** — matched exactly, the one thing the OpenSCAD
  tier writes — is now the artifact itself, and the mesh lands exactly there.
  Every other path is the directory it has always been: an existing directory
  whatever it is called, a path with a trailing separator
  (`--out run.2026-08-13/`), any other suffix (`--out v1.2`), and `.STL`,
  which partspec never writes and so is far likelier to be someone's input.
  Gating on `.stl` rather than on "has a suffix" was found in review: while
  any suffix counted, `--out models/spacer.scad` replaced the run's own source
  with binary STL at exit 0, a worse defect than the one being fixed.

  **The destination is written only once the build succeeds.** The engine runs
  in a scratch directory beside it and the result is moved into place with
  `os.replace`, so the file is the old one or the new one and never neither: a
  failed build, a blown timeout or a Ctrl-C leaves what was already there.
  (Directory mode still removes `DIR/<source>.stl` before the engine runs.
  That is not defended as better here, only left alone: it is a path partspec
  derived rather than one the caller typed, and it is pre-existing behaviour
  this change does not reach.) Building in the scratch directory is also what
  stops the export from overwriting a neighbour called `<source>.stl` on the
  way. A symlink at the destination is replaced rather than written through,
  so its target is untouched.

  **A file destination is refused when partspec cannot account for every
  input.** `import()` reads an `.stl`, which makes the suffix an input
  extension as well as an output one, and a closure that reads external data
  cannot say *which* file it reads (SPEC-report §8.3). Writing the artifact
  over an input changes what the next run measures — measured on a model
  importing its own destination: `[5, 5, 5]` reported at exit 0 for a part
  that measures `[10, 10, 10]`, with the input destroyed. The test is the
  closure's `partial`, not `reads_external_data` alone: a model with an
  unresolved `include` cannot be read to find out whether *it* imports data
  either. Refused (exit 64) rather than guessed at; a directory still works
  and is what the hint recommends.

  Likewise on the OCCT tier, which builds in memory and exports nothing: a
  filename is refused rather than accepted and quietly not written. Both
  refusals are artifacts — identity plus `error`/`hint` on stdout, as
  SPEC-report's Scope requires of any failure after the target resolves.

  `check --out` and `render --out` are unchanged: they hold several files, so
  they remain directories.

- **A closure claimed to be complete for models that read a file through any
  spelling but `import()`.** `reads_external_data` matched `import(` and
  `surface(` only, so `import_stl(`, `import_dxf(`, `import_off(`, the
  deprecated `dxf_linear_extrude(`/`dxf_rotate_extrude(`/`dxf_dim(`/
  `dxf_cross(`, and `linear_extrude(... file=)`/`rotate_extrude(... file=)`
  all read data while the report said the closure was whole. OpenSCAD 2021.01
  — what this tier targets, and what Debian and Ubuntu ship — still executes
  every one of them. `source_closure.partial` is therefore now `true` for
  models where it used to be `false`, which **changes report contents**: a
  `diff` of two such reports will start declaring `partial_closure`
  indeterminacy it previously missed. That is the honest answer to a question
  the tool was getting wrong, and it is a correction rather than a new policy.
  Found by an adversarial review of the `--out` fix above, which asks this
  question before overwriting anything: `import_stl("input.stl")` walked
  through the guard, and three consecutive runs ate their own input and
  reported `[30,10,10]`, `[50,10,10]`, `[70,10,10]`, each at exit 0.

## [0.7.4] - 2026-08-13

**A remedy that cannot be run is not a remedy.** One fix, found the way the last
release was: by installing the published artifact the way a stranger would and
following its own instructions literally.

Measured at this tag, five environments, no failures anywhere:

| environment | passed | skipped |
| --- | ---: | ---: |
| `uv sync --all-extras` (`just test`) | 800 | 0 |
| base install, no extras | 466 | 260 |
| `[mesh]` only | 586 | 152 |
| `[occt]` only | 665 | 126 |
| `[cadquery]` only | 671 | 120 |

### Fixed

- **Every hint that named an installer named `pip`, which a `uv venv` does not
  have.** Absent would have been the kind outcome: on a distro that packages
  pip the word still resolves — to `/usr/bin/pip`, bound to the system
  interpreter — so `pip install --force-reinstall --no-deps cadquery-ocp`, the
  entire answer to the two-provider clobber, was refused outright under PEP 668
  with advice to "create a virtual environment" the reader was already standing
  in, and its suggested `--break-system-packages` override would have installed
  OCP into a Python that could never satisfy the failing one. Either way the
  next run printed a byte-identical diagnosis. Hints are now phrased for the
  interpreter that will read them (`install.py`), detected with `find_spec` and
  deliberately not `shutil.which` — `which` is exactly what finds the wrong
  pip. Verified end to end in a pip-less two-provider venv: the printed command,
  run verbatim, takes the run from `ERROR: 3 skipped` to `PASS: 3 pass`. Found
  on the v0.7.3 cold verify, in the install shape the README documents.

## [0.7.3] - 2026-08-13

**The first release cut from an adoption measurement rather than from review.**
A fresh agent was dropped on a cold PyPI install of 0.7.2 with a real
objective — evaluate the community CadQuery library `cq-gridfinity` against
the published Gridfinity standard — and no other context: no access to this
checkout, no worked example, nothing but the installed tool. Roughly **40% of
its effort went to discovering the contract API**, and every fix below is one
of the reasons why.

The measurement paid for itself twice over. It also produced the thing it was
pointed at: `cq-gridfinity`'s stacking lip is 0.6 mm shorter than the standard
at both sizes tested — `GR_LIP_PROFILE`'s final segment is 1.3 mm where the
reference implementation has 1.9 — found by an `envelope` bound sourced from
the standard rather than from the library, which is the whole argument for
attribution.

**What this release does not change:** `pip install 'partspec[cadquery]'` still
lands two OCP providers and still needs the re-assert the README documents.
That was confirmed on a clean ancestor chain with `--no-config`, so it is the
default outcome and not a local artefact. The extra cannot fix it — the
override that does is a workspace setting wheel metadata cannot carry — so what
changed is that the tool now prints the remedy instead of only recording it.

Measured at this tag, five environments, no failures anywhere:

| environment | passed | skipped |
| --- | ---: | ---: |
| `uv sync --all-extras` (`just test`) | 798 | 0 |
| base install, no extras | 464 | 260 |
| `[mesh]` only | 584 | 152 |
| `[occt]` only | 663 | 126 |
| `[cadquery]` only | 669 | 120 |

### Fixed

- **`check` named the fault and withheld the remedy.** `BuildError` carries a
  message and a hint; `measure` and `render` have always printed both, and
  `check` — the verb people actually run — printed only the message, leaving
  the hint in `report.json`. On a cold `partspec[cadquery]` install, which
  lands two OCP providers so that CadQuery cannot import at all, the console
  named the clobber precisely, twice, and never said
  `pip install --force-reinstall --no-deps cadquery-ocp`. The same agent lost
  time to this twice more in one session: `available: <names>` on a mistyped
  factory, and the claims-pin mismatch hint, were withheld identically. Every
  path that sets `report.hint` is one where nothing was proven about the part,
  so the rule is now simply that a hint is printed. The console is still a
  courtesy and `report.json` is still ground truth; the courtesy just stopped
  naming a problem and hiding its answer.
- **A run-level fault was stated once per check.** An environment-origin build
  failure skips every declared check carrying the same sentence as its detail,
  so a ten-check contract printed an identical forty-word packaging diagnosis
  ten times — and `report.error`, the thing that actually happened, not once.
  The console now elides a detail that merely echoes the run-level error and
  states the error a single time. The artifact is untouched: a per-check
  consumer still reads `detail` on every check.
- **Both Python engine factories were undocumented.** `openscad` had a
  docstring; `build123d` and `cadquery` had none, and they are the entry point
  for both Python engines. What they did not say is what bites: partspec calls
  a *named callable*, defaulting to `make_part`, with the contract's params as
  keyword arguments. The agent assumed CQGI's module-level `result` — the
  convention `cq-gridfinity`'s own shims use — and learned otherwise only by
  failing. `Source.path` now also records that a relative path resolves against
  the contract's directory rather than the working directory.
- **Diagnostics cited specs an installed user cannot reach.** Messages name
  `SPEC-report.md 7.1` and `SPEC-contract.md 10`; the wheel ships the package
  and nothing else, deliberately. `--help` now says where the documents are.
  The wheel still ships no docs.
- **The unattributed-limit advisory named the problem and not the way out.**
  `partspec.refs` carries `iso15` and `nema17`, so an author citing anything
  else was told their bound proves the model matches itself and not how to fix
  that. It now names `partspec.Referenced`, which the agent found by reading
  `dir(partspec)`.
- **The README's front-page transcript quoted output the tool had stopped
  printing** — one commit after the commit that changed it. Neither existing
  guard reads what a transcript *says*: one compares the contract's call shape,
  the other counts `ok` lines and the tally. The transcript is recaptured and
  now executed, so every non-path line it quotes must appear in a real run.
  The OCP error block one section down was never captured at all — it was
  assembled from `BuildError`'s fields, and showed a `hint:` line `check` did
  not then emit. That is the third block of "captured" output in this README
  found not to have been captured.
- **`--out` meant two different things and said so nowhere.** On `measure` it
  is the engine's build directory — an `.stl` on OpenSCAD, nothing at all on
  the OCCT tier, which builds in memory — because `measure` writes no report by
  design (SPEC-report scope: the payload is stdout). It had no help text, while
  `check --out` is documented as "report directory", so it read as a report
  flag that silently did nothing. Behaviour is unchanged; the flag now says
  what it controls. `check --out`'s own layout is documented too:
  `DIR/report.json` for one target, `DIR/<part-slug>/report.json` for several.

## [0.7.2] - 2026-08-12

**A retraction.** For ten days, across three releases, this project told uv
users that `uv pip install 'partspec[occt]'` does not work and named an
upstream cause. Both halves were wrong, and the cause was one line of this
repo's own configuration. Eight files carried the explanation — the README,
`AGENTS.md`, `docs/FAILURE-MODES.md`, the justfile, CI's workflow, this file,
the error message itself and the test that pinned its wording — and the single
change inside `partspec/` is that error message. Everything else is
documentation, recipes and gates that repeated it.

Measured at this tag, five environments, no failures anywhere:

| environment | passed | skipped |
| --- | ---: | ---: |
| `uv sync --all-extras` (`just test`) | 791 | 0 |
| base install, no extras | 466 | 251 |
| `[mesh]` only | 585 | 144 |
| `[occt]` only | 665 | 117 |
| `[cadquery]` only | 671 | 111 |

### Fixed

- **`uv pip install 'partspec[occt]'` was never broken, and #109 was ours.**
  For ten days the README told uv users the command does not work and to fall
  back to plain `pip`; the issue recorded an upstream cause — that build123d's
  `cadquery-ocp-proxy` picks a real OCP wheel with an install-time hook uv's
  installer skips — and the error message, its test, two justfile recipes and
  `AGENTS.md` all repeated it. None of it was true. `cadquery-ocp-proxy` ships
  no OCP and has no dependencies at all; every build123d release ever published
  hard-depends on a concrete provider (`cadquery-ocp` through 0.10.0,
  `cadquery-ocp-novtk` from 0.11.0), so there was no hook to run and nothing
  for uv to skip. The strand was this repo's own
  `[tool.uv] override-dependencies = ["cadquery-ocp-novtk ; sys_platform == 'never'"]`,
  which uv finds by walking up from the working directory and applies to
  whatever it is installing. Measured four ways against
  `partspec[occt]==0.7.1` on Python 3.13: outside the repo it installs OCP;
  inside the repo it does not; inside the repo with `--no-config` it does;
  and in an empty directory holding nothing but a pyproject.toml carrying that
  one override, it does not. `partspec[occt]==0.4.0`, the version of the
  original report, installs cleanly from outside the repo today — and the
  override predates that report by six days, so it was in scope for every
  measurement the issue was ever built on.

  Fixed in what the tool says and in what the gates measure. The README
  paragraph is replaced with the correction rather than deleted, since the
  wrong version shipped in three releases. `_engine_import_error` no longer
  blames uv's installer: the state it detects is now stated as what it is — no
  OCP provider installed, the proxy present as a breadcrumb — and it names the
  distribution to install instead of advising a switch of installer. Its test
  asserts those invariants rather than the phrasing, which is how the fiction
  survived: the test pinned the words. All five throwaway-environment recipes
  pass `uv pip install --no-config`, which lets `test-occt-only` and
  `test-cadquery-only` drop the seeded-venv-plus-plain-pip workaround they
  carried for a cause that did not exist, and `test_packaging.py` fails any
  future recipe that omits the flag — a recipe measuring what a consumer gets
  cannot read config no consumer has.

- **The dual-engine install's second line is not optional advice, and the
  recipe that was supposed to prove it was living on luck.** `cadquery-ocp` and
  `cadquery-ocp-novtk` own the same top-level `OCP/` and whichever lands last
  wins; `just test-cadquery-only` was green for a month on plain pip, which
  happened to land `cadquery-ocp` last, and failed on its first CI run under
  `uv pip`, which landed novtk last — `ImportError: cannot import name
  'IVtkOCC_Shape' from 'OCP.IVtkOCC'`, CadQuery unable to import at all. pip's
  order was never a guarantee either. The recipe now runs the re-assert step
  the README documents, so it verifies those instructions rather than hoping a
  resolver agrees with them, and the README carries the `uv` form of the
  two-step beside the `pip` form.

- **The guard against #109 did not cover the release.** Its first version read
  the justfile, because that is where the recipes it was written for live. The
  install it therefore missed is the last one to touch an artifact before PyPI:
  `release.yml`'s cold smoke-test of the built wheel, whose stated purpose is
  to reproduce "the environment every `pip install partspec` user starts
  from". It runs in the checkout, so it read the override like everything
  else. Harmless in fact — core depends on no OCP provider, so there was
  nothing for the override to drop — but the claim it makes is exactly the one
  #109 falsified, and this is the release path. It passes `--no-config` now,
  and the guard searches every file that runs a `uv pip install`, comments
  excluded, rather than one file by name. Found by the pre-tag audit for this
  release, in the workflow that publishes it.

- The comment above CI's two OCCT-tier jobs still gave the retracted cause —
  that `uv pip install .[occt]` "lands `cadquery-ocp-proxy` and NO `OCP`
  module ... still reproducing on 2026-08-12", and that plain pip in a seeded
  venv is the way around it. The recipes it describes had already moved back
  to plain `uv pip` with `--no-config` in the same change that retracted the
  cause; the prose above them had not. Nothing executed it, which is how it
  survived — the repeat defect of this project, recorded in `AGENTS.md`.

- 0.7.1's release entry says the published wheel differs from 0.7.0's in "the
  version string, and the README it embeds". Comparing the two wheels *as
  published* — which is only possible after the fact — there is a third:
  `WHEEL` carries `Generator: hatchling 1.31.0` against `1.32.0`, the build
  backend CI resolved on the day. The containing claim holds and was verified
  against the published artifacts (29 package files, same set, none differing;
  every difference inside `.dist-info`), but the enumeration was two of three.
  Recorded here rather than edited into the released section, per the rule in
  `AGENTS.md`: a released entry takes form-only edits, and a changed claim
  goes in a new entry.

- **The suite the sdist ships still hid tests from the install it ships to.**
  0.7.1 made `tests/` *pass* in a base install; it did not make it *run*. Ten
  module-level `pytest.importorskip` gates collapsed their files to a single
  skip line each, so a base install collected 588 of the suite's 788 tests and
  ran 451. Gating is per test, and at the commit that changed it 714 collected
  there and 463 passed — 717 and 466 at this tag, per the table above. And
  `pip install partspec[mesh]` — which reported four whole files as
  `4 skipped` — runs the four `the mesh tier refuses with the tier named`
  tests, the only executed evidence that the mesh tier refuses honestly in
  the one install where the mesh tier is the only tier. No code in
  `partspec/` changed (#165).

- **The shipped suite failed one test under `pip install partspec[cadquery]`.**
  That extra names `cadquery-ocp` explicitly while build123d hard-depends on
  `cadquery-ocp-novtk` — so pip installs both providers of the same top-level
  `OCP/` package and neither notices.
  partspec's own guard detects exactly this and says so, which is what broke
  the test: it pinned the wording of a different branch. It now asserts what
  every branch owes a reader — the environment's fault, the module named, a
  next step given — and the three wordings are pinned individually, including
  the two-provider one, which had no test and is the only branch reachable
  without monkeypatching. Measured after the fix: `[cadquery]` 670 passed,
  `[occt]` 664 passed, no failures in either — 671 and 665 at this tag, per the
  table above. Again no code in `partspec/` changed.

## [0.7.1] - 2026-08-11

**No code changed.** `src/` is byte-identical to 0.7.0, and so is every one of
the 29 files inside the installed `partspec/` package — verified by SHA-256
against a wheel rebuilt from the v0.7.0 tag. The only differences in the wheel
are its `.dist-info` metadata: the version string, and the README it embeds as
the long description. No verb, check kind, exit code or engine behaviour
differs; nothing in the installed package changes.

What did change is the **source distribution** and the repository's own gates.
Two things a consumer gets: the test suite the sdist ships now passes in a base
install, and the documents it ships no longer cite files the tarball does not
contain.

### Fixed

- **The sdist shipped a test suite that did not pass.** `pyproject.toml`
  argues `tests/` ships "because a downstream packager runs the suite from an
  sdist, and that claim only holds if the suite actually passes there... The
  claim is ZERO FAILURES." At v0.7.0 a base install — `pip install partspec`,
  no extras, OpenSCAD binary present — the shipped suite reported **23 failed
  / 314 passed**. It is **451 passed / 137 skipped / 0 failed** now, and from
  the unpacked tarball itself, 439 passed / 149 skipped.

  Two causes. An OpenSCAD part is measured *through* the mesh tier, so tests
  marked `needs_openscad` alone ran and errored instead of skipping when
  `trimesh` was absent; `needs_scad_tier` names that coupling. And a
  module-level `importorskip` raises at import, collapsing a whole file to one
  skip line — `test_diff.py` reported `1 skipped` for 34 tests, 32 of which
  need no engine at all. Eight such gates are gone.

  No CI job could have caught either: `check` and `test` install every extra,
  and `mesh-only`/`mcp-only` each ran a single module, so no job ran the whole
  suite anywhere an extra was missing. `just test-no-extras` does now, in a job
  the path filter cannot skip.
- **17 citations across ten shipped documents** named files under `notes/` and
  `evals/`, neither of which has shipped in the sdist since #150 — so they
  dangled for every reader who arrived from PyPI rather than a checkout. They
  are `blob/main` links now, and three tests hold them: every linked path is
  tracked, every backticked path is tracked, and no shipped document may cite
  a non-shipping file as a bare path. The last is the one that matters — the
  other two ask "is this tracked?", and `notes/` is tracked *and* excluded,
  which is why `AGENTS.md` passed both while being unopenable.
- The `[0.7.0]` heading in this file had no link definition, so it rendered as
  literal text between neighbours that were links — on the document
  `pyproject.toml` advertises as the project's Changelog URL. `[Unreleased]`
  also still compared from `v0.6.0`, a range spanning all of 0.7.0. A test
  holds both, and a second refuses two `### Fixed` sections in one release.
- `ok`, the branch-protection gate, listed its upstream jobs by hand and
  nothing checked the list. A job missing from it still runs and still goes
  red, while the merge button turns green because the one required check never
  waited for it — a job that cannot fail the gate reads as success.
- The eval harness told the agent its report was at
  `outputs/spec-<part id>/report.json`, but partspec derives that directory
  from the contract's filename and factory, not the part id. No eval case has
  the two equal, so the path was dead in every archived repair turn — four
  lines below partspec's own output naming the real one. `run_check` already
  found the true path and discarded it; it returns it now. (`evals/` does not
  ship; this affects contributors only.)

### Changed

- `tests/test_mesh_backend.py` was nearly half coverage of
  `engines/openscad.py` under a filename naming a different module (#153) —
  37 of its 75 tests, 496 of its 1100 lines, now
  `tests/test_openscad_engine.py`. Not only tidiness: the old file binds
  `trimesh` at import, so tests that never measure a mesh could not run
  without the mesh extra. The split alone accounts for 44 of this release's
  base-install gain.
- `just test-mesh-only` ran a single module, so nothing covered the ground
  between "no extras" and "all extras". It runs the whole suite now — which
  caught a regression mid-release: a module gated on a *proxy* dependency
  (`numpy`, which arrives with `trimesh`) rather than the one its tests use
  collected on `pip install partspec[mesh]` and failed, with every other gate
  in the repo still green.
- `tests/test_cli.py` carried a private `_contract()` byte-identical in output
  to `support.scad_target()`; proved equivalent, deleted, and its 15 call
  sites moved. `support.py` gains `py_target`, the build123d counterpart,
  written for #153 and then deleted unused because a helper nothing calls is
  the slop that slice was removing — it returns with 16 callers.
- `_write_json` already wrote atomically, and **that is unchanged**; what was
  missing is that nothing held it there. Replacing the tempfile-and-rename
  with a direct truncating open left the whole suite green. Two properties are
  pinned now: a failed write leaves the previous report byte-identical, and a
  successful one replaces the file by rename rather than writing in place —
  checked by inode, because a writer that copies a temp file over the
  destination satisfies the first and still lets a reader observe a
  half-written report.

## [0.7.0] - 2026-08-11

### Fixed

- `cavities` certified exactly one sealed void in a shape with no material
  (OCCT, #147). The same report said `solid_count: 0`, and the mesh tier
  answered `0` — a number contradicted by its own neighbour and by the other
  tier. Gated now.
- `diff` compared every claim field except the one that says what a check IS
  (#147). Swapping `genus` for `cavities` under one id reported `identical`,
  exit 0. `CLAIM_FIELDS` is public and held in step with `SPEC-diff.md`;
  `NON_CLAIM_FIELDS` enumerates the rest, and every `CheckResult` field is
  classified into one or the other, so a field added later cannot fall through
  both.
- `diff` returned `identical` when both inputs' source closures were absent —
  "nothing we looked at changed" reported as "nothing changed" (#147). And
  `counts` was asserted only to sum, so a tally claiming every check passed
  while the verdict said fail was a self-inconsistent report the comparator
  accepted.
- An empty `Compound()` escaped as an `AssertionError` traceback with empty
  stdout (#133). All three verbs now name it — `model returned a shape
  containing no geometry (an empty Compound with no underlying handle)` — and
  `measure`/`render` still emit the identity artifact so a consumer learns
  which file and revision it was talking about.
- `check --render` built the model twice (#133): doubled side effects, a
  `--timeout N` that bounded each build separately rather than the run, and
  renders that could disagree with the geometry measured beside them. One
  build now.
- The release workflow's safety argument is enforced rather than stated
  (#149). It runs no tests by design — correctness is the `ok` gate's job on
  main — and that reasoning holds only if the tag is ON main, which nothing
  checked. `scripts/assert_tag_on_main.sh` refuses a tag that is not an
  ancestor of `origin/main`, in a script because an inline gate can only be
  grepped, not tested. The publish action is SHA-pinned.
- A missing mesh wheel is an environment fault, not a traceback. `pip install
  partspec` then running an OpenSCAD part raised `ModuleNotFoundError` with a
  hint blaming "a native segfault/OOM in the CAD kernel"; it now reports
  `build_origin: environment` with `pip install 'partspec[mesh]'`. The OCCT
  tier has classified this correctly since v0.4.0.
- An OpenSCAD binary rejecting an option partspec passed is an environment
  fault. `backend="CGAL"` on 2021.01 — what Debian and Ubuntu ship — reported
  `build_origin: "model"`, sending an agent to fix a source that was fine.
- `scad-magic-number` exempted the line, not the statement: a named constant
  wrapped across lines drew three findings that the same constant on one line
  did not.

- `partspec diff` refuses a report carrying two checks under one `id`, exit 64
  (#148). SPEC-report §7.1 already made uniqueness a MUST NOT; nothing checked
  it on the consuming side, and the comparator joins on `id`, so the second
  occurrence silently replaced the first and two unrelated claims were compared
  as one. Measured before the fix: a `genus` check aliased onto a `param_range`
  check reported `limit_changed` from `{"kind": "param_range"}` to
  `{"kind": "genus"}` at exit 1, with the displaced claim absent from the output
  entirely — a confident wrong answer, not a lost check. `counts.total` cannot
  catch it, because such a report carries exactly the number of checks it
  claims. `Part._add` already refuses an id clash at authoring time, so
  `partspec` never emitted one; this binds `diff`, which consumes reports it did
  not produce. Two neighbouring refusals share the precondition: a check with no
  `id`, and an `id` that is not a string (§7.1 types it as one — comparing ids
  any other way lets `1` and `1.0` pass a uniqueness check and then collapse
  onto one another in the join).
- `Part._add` refuses a check `id=` that is not a string. `CheckResult.id: str`
  was an annotation, not an enforcement, so `p.param("wall", min=2.0, id=3)`
  was accepted and `check` wrote `"id": 3` — which the new `diff` guard would
  then refuse at exit 64, blaming the artifact for a contract error made two
  commands earlier. **Behaviour change**: a contract passing a non-string `id=`
  now raises `ContractError` (verdict `error`, exit 4) where it previously ran.
  `id=None` is untouched — it is the default and means "derive the id".

### Changed

- `Part._add` refuses `id="builds"` — reserved for the runner's own build
  check, which a contract could previously shadow, putting two same-id checks
  in one report and once letting a passing parameter check impersonate a
  failed build to `check --render`'s gate (#135). The gate keys on `kind` now.
  **Behaviour change**: such a contract raises `ContractError`, verdict
  `error`, exit 4.
- The package ships a type marker (`py.typed`, #149). It is fully annotated
  and pyright-clean and shipped no marker, so a downstream consumer got not
  weaker type checking but **none**, silently.

- The sdist no longer ships `notes/` or `evals/` (#150). They were carried
  because tests read them — an inverted dependency that put 310 KB of archived
  agent transcripts in front of every PyPI consumer so a test could assert a
  phrase appeared in prose. Those tests are deleted rather than skip-guarded, so
  nothing reads those trees and the question does not arise. The tarball loses
  105 KiB. (A delta, not a share: the share depends on which tarball is the
  denominator and moves as prose is added to the repo, which is how the
  figure this replaces came to be wrong.) `tests/`, `docs/`, `examples/`, `skills/` and
  `.github/` still ship, and the suite still passes from an unpacked sdist.
- The mechanical enumerations in the specs are **generated** from the code
  (`scripts/gen_docs.py`, run by `just fmt`, gated by `just check`): the §4.1/§4.2
  vocabulary tables, SPEC-report §2.2's unit table, `DIMENSIONAL_KINDS`,
  SPEC-backend §3's protocol block and the README's exit codes. Six tests used to
  hold those second copies in step and report drift after it happened; there is
  one copy now. Consequence for readers: §4.2 gains the `id=` parameter it never
  documented on any of its eighteen rows, and §2.2's unit column now names the
  kinds that emit each unit. Prose is untouched and stays normative.

### Added

- `p.min_wall(min=)` — every wall thick enough within a declared measurand,
  OCCT tier (#140): kernel-exact face-pair minima and certified diametric
  self-spans bound the wall from below; a witnessed crossing bounds it from
  above — an inward normal ray, or a diametric chord certified material end
  to end by exact boolean, which is what makes every closed analytic family
  exact and answers a frustum whose every normal exits through an adjacent
  cap (#145). One consequence to know: a fillet band on a CLOSED
  (full-revolution) edge is a closed analytic face, so the chord witness
  collapses the upper end onto twice the fillet radius — a rounded Ø20 boss
  that used to report `[1.414, 20.0]` and shrug at a `min=3` claim now reports
  `[1.414, 2.0]` and fails it. A fillet along a straight edge is an open strip
  with no diametric certificate and still straddles, including §4.11's
  knife-edge-on-a-wedge example (`[0.599255, 1.167914]`, `approximate`). A crossing thinner than the bound refuses the check as
  self-contradictory, and a straddling limit adjudicates `approximate` —
  the first genuine exercise of the interval machinery, closing POST-V0's
  outstanding obligation. Gap-limited claims straddle honestly (never
  falsely tight); edge-sharing webs, single-face folds and step/counterbore
  ledges are recorded escapes with fixtures, not silent green; the wedge
  policy is structural. The mesh
  tier's refusal stands with the research's executed evidence recorded.
  SPEC-contract 4.11.
- `p.step_roundtrip(tol=)` — the part survives its own exchange format,
  OCCT tier (#139): written to STEP and read back, volume/area within a
  calibrated relative tolerance (default 1e-6: most families measure below
  4e-13, threaded parts ~6e-9 on build123d 0.11.1 / cadquery-ocp 7.9.3.1.1 —
  the figure moves with the kernel, so it is named with its toolchain — and
  the executed degrader loses everything)
  and topology counts unchanged at any tolerance. Plain membership — the
  tol is never epsilon-widened. The writer schema rides on the check
  (`checks[].step.schema`). SPEC-contract 4.10.
- `p.self_intersection_free()` — the shape does not cross itself, OCCT tier
  (#138): the kernel's own pairwise interference analysis, exact, with the
  faults inventoried in the failure detail. The recorded limit is pinned
  by tests in both directions: an analytic single-surface self-intersection
  (spindle torus) escapes, while a self-overlapping swept face is caught as
  a pair-less fault. Listed by `measure`. SPEC-contract 4.9.
- `p.draft_angle(min=, direction=)` — every face's draft at least `min`
  for a declared pull axis, OCCT tier (#137). Deliberately no `max=`: an
  every-face maximum is unsatisfiable under the two-half convention (caps
  measure 90), and a bound held to fewer faces would pass silently. Exact on planes, cylinders and
  cones at any orientation (closed-form wrap extremes, no sampling); a
  freeform face refuses the whole check with the face named, never a subset
  pass. The two-half parting convention makes tops measure 90 and pass a min
  naturally, and the pull axis is recorded in the check
  (`checks[].direction`). SPEC-contract 4.8.

### Removed

- `partspec.BBox` — a dataclass never constructed anywhere in the repo, on the
  public export list since v0.1. `Vec3` stays; nothing else changes.
- `partspec.run` leaves `__all__`. README has called it internal since v0.1
  while the export said otherwise; it remains importable (`from partspec
  import run` still works, and `partspec.runner.run` is the honest path), but
  it is not part of the stable surface and its signature may change without a
  major bump. The stable surface is the report schema and the exit codes.
- `CheckResult.part_refs` — set on three of the construction sites, never
  serialised by `to_json`, and therefore unreadable from any artifact, while
  four claim sites across three documents said every check recorded it. Forward-compat for
  assemblies that cost coherence now and could not be collected later anyway:
  SPEC-report §7.1 makes an added field non-breaking, so assemblies can
  introduce it for real.
- `partspec.csg.read_csg` and `partspec.csg.contains_strings`. Neither had a
  production caller; `contains_strings` was the superseded tree-walking half
  of a guard that `lint.lint_scad_tier2` performs on the raw export bytes,
  because the tree version was bypassable by hiding the string in a %-dropped
  statement. `csg` is not a documented surface, but `contains_strings` was in
  `csg.__all__`, so it is recorded here.
- The mesh tier no longer declares the `raycast` capability. It needs
  `rtree`, which the `mesh` extra does not carry, so the declaration was a
  promise the backend could not keep — the one thing SPEC-backend §3.2 says
  capabilities exist to prevent. The method remains and now returns
  `Unsupported` instead of raising when the ray engine is absent.

## [0.6.0] - 2026-08-08

An agent can see the part it made (epic #2): renders on every engine, section
cuts, a visual diff — plus the lint tier that reads the geometry.

### Added

- `render` and `check --render` accept build123d and CadQuery parts (#18): the
  part builds through the same backend `check` uses and the canonical views are
  rasterized from its tessellation — deterministic (identical geometry renders
  byte-identical), headless, no new dependency. Framing is the OpenSCAD path's,
  measured and verified cross-tier to the pixel. OCCT payloads and reports carry
  `render_tessellation` (`{tolerance_mm, triangles}`) beside `renders` (D15).
- `render` payloads carry the report's identity prefix, and a render failure is
  a JSON artifact with `error`/`hint` at exit 4 instead of a bare stderr line
  (#103); the MCP `render` tool returns the whole payload as `rendered`.
- `partspec vdiff old new` compares two runs' renders visually (#21):
  per-view changed-pixel fractions with grey-plus-magenta diff images, a
  reproducible scalar magnitude, and refusals for everything that would let
  noise read as change — differing image sizes (never rescaled), engine
  versions (7.68% renderer noise), part ids or view sets. Pure scale is
  pixel-invisible by construction, so every render now records its framing
  bbox (`render_bbox`) and the render verb leaves `render.json` on disk;
  a bbox delta with identical pixels reads as change, referred to `measure`.
  Exposed over MCP as `vdiff`.
- `render --section xy|xz|yz[:offset]` cuts through a named plane and renders
  the cut with exposed material in a distinct colour, on both tiers (#19):
  OpenSCAD subtracts a half-space from its exported STL (kernel-capped), the
  OCCT tier booleans the shape, and the shared rasterizer draws both. The
  payload records the resolved plane, offset and cut-facet count; a plane
  that misses the part is refused with its span.
- `partspec lint` tier 2 — the geometry rules, over OpenSCAD's constant-folded
  `.csg` export via a hand-rolled stdlib reader (`csg.py`; sca2d is GPLv3 and
  geometry-blind, FreeCAD's importer LGPL and welded to its document model):
  `csg-coincident-face` (exact plane coincidence of cutter and minuend — zero
  epsilon, the literals are folded) and `csg-difference-order` (analytic
  upper-bound volumes, convention stated in the finding). Requires the engine;
  a missing engine, failed export, unmodelled node (`hull()` and kin on a
  rule's evaluation path) or string-carrying export produces per-rule
  `unsupported` entries — a rule that could not run is an entry, never an
  absence. Tier-2 findings carry line 0: the folded tree has no source lines
  (#118, #125).

### Changed

- Lint payload schema 2: per-file `{file, digest, findings[, unsupported]}`
  blocks — a clean file is a visible entry with the sha256 of the linted
  bytes, and duplicate arguments are deduped. A breaking reshape of the
  schema-1 payload that shipped in 0.5.0, versioned honestly (#120, #124).

### Fixed

- Module eviction covers every CLI exit path: contract-sibling imports are
  recorded and evicted on failed resolves and on the error paths of `check`,
  `measure` and `render` (record-in-finally), closing the remaining
  cross-directory stale-module windows (#114, #124).
- A stranded `cadquery-ocp-proxy` (proxy installed, no OCP — the observed
  `uv pip` outcome at the time) is named as the environment state with a
  plain-pip hint, instead of the circular "pip install partspec[occt]"
  (#109, #124).

## [0.5.0] - 2026-08-08

The repo teaches the craft it verifies (epic #3): skills, exemplars, the failure
catalogue, a source linter, and a recorded before/after on agent output.

### Added

- **`partspec lint`** — tier-1 advisory source lint over `.scad`/`.py` models, in the
  wheel and engine-free: five rules with exact predicates (`docs/LINT.md`), findings
  as data at exit 0 — advisory and never a verdict on the part — with 64 reserved for
  unlintable input. The `-1`/`+2` overshoot idiom is exempt by design; tier 2
  (geometry-dependent rules over the `.csg` tree) is deferred to #118 behind its
  prior-art survey (#119).
- **Three authoring skills** (repo content, not wheel content): `contract-authoring`
  (the decision table, the limit-provenance ladder, the retrofit path),
  `openscad-authoring`, and `build123d-authoring` — every executable claim in them is
  executed by the test suite, and several were corrected by exactly that discipline
  before shipping (#115, #116, #117).
- **Three worked exemplars** under `examples/`: a NEMA 17 bracket whose interface is
  one cited `nema17.mount` call, a bearing-seat family in OpenSCAD **and** build123d
  with shared claims stated once and the ISO 15 designations cited, and a
  sealed-cavity enclosure whose sealedness claim is `cavities(1)` — because an open
  tray is also watertight, one solid, genus 0 (#112).
- **`docs/FAILURE-MODES.md`** — the eight observed CAD-as-code failure modes from the
  dogfood corpus, each with symptom, root cause, detection, and what it looks like
  when green; raw record frozen at [`notes/dogfood-results.md`][dogfood-results] (#111).
- **The authoring before/after, recorded** ([`evals/AUTHORING.md`][authoring-evals]): guidance-present vs
  absent arms over exemplar-shaped tasks, 12 trials. Pass rate saturated (6/6 both
  arms); on the transfer tasks the guidance moved source quality from mixed to
  uniformly lint-clean (6 → 0 findings) while LoC rose — the added lines are the
  parameterisation. One task's treatment output was a line-for-line copy of a skill's
  own worked block; it is scored separately as retrieval and kept as the
  contamination exhibit (#121).
- **`notes/`** — the analysis the tracker cites (gap inventory, W1–W10 findings, the
  audit synthesis, as-filed tracker scripts) is tracked and visible to clones, with
  per-item dispositions recorded (#110).

### Fixed

- **`measure` reports `cavities`** — the number distinguishing a sealed enclosure
  from an open tray was absent from the verb whose job is showing every claimable
  number (#113, landed with #115).
- **A contract's sibling imports no longer cross directories** — a shared `claims.py`
  cached from directory A silently supplied directory B's checks in one process; the
  module-cache registry now covers resolve-time additions for every engine (#112).

## [0.4.0] - 2026-08-08

The loop can be trusted unattended (epic #4's remnant): a run that cannot hang, a
contract that cannot shrink silently, and the rules an agent follows written down.

### Added

- **Bounded builds.** `--timeout SECONDS` on `check`, `measure` and `render`
  (default 300 s, then `PARTSPEC_TIMEOUT`; `0` explicitly waives), recorded in
  `invocation.timeout_s`. A blown budget is `error` exit 4 with
  `build_origin: "environment"` naming the elapsed time and the budget — never a
  failing `builds` check: a stopwatch disproves nothing about the part. The Python
  tier gets a real SIGALRM bound that records it fired — a model whose mundane
  `except Exception` swallows the alarm still has its over-budget result discarded —
  and re-fires past `except Exception`; the residual ceilings (C-kernel hangs,
  signal-owning models, leaked threads) are stated in `SPEC-backend.md`, not hidden
  (#100).
- **Multi-target `check`.** One process, one report per part at its deterministic
  path, exit by highest-precedence verdict (`error > empty > fail > incomplete >
  pass`, SPEC-report §6.2); an unresolvable target exits 64 with the remaining
  targets still evaluated; placeholders for every target go down before any runs;
  colliding slugs under one `--out` are refused rather than silently overwritten.
  The `sys.modules` model cache is invalidated after every Python-engine build —
  a second contract importing an edited helper used to get the previous version, a
  stale build reported as fresh (POST-V0 §8) (#104).
- **The claims pin.** `check --pin LOCK` writes the declared claim set;
  `check --expect LOCK` fails before the engine starts unless the set matches
  exactly — removed, added, and changed claims named with both slugs, stripped
  `source` citations included, verdict `error` exit 4 with every check skipped and
  the adjudication in the artifact as `expectation`. A pinned part no target
  produced fails too. This closes silent contract weakening with **no baseline in
  hand**; `diff` remains the comparison half (#105).
- **`measure` is as identifiable as a report.** Its payload opens with the report's
  exact identity prefix (`schema_version`, `tool`, `part` with digests and closure,
  `engine`, `params`, `geometry`), built by the same code, and any failure after
  the target resolves emits that identity plus `error`/`hint` as JSON on stdout
  (#102).
- **`docs/AGENT-CONTRACT.md`** — the agent contract: a bounded 5-attempt repair
  loop with failure fed forward, an action map keyed on (exit, verdict, report
  fields), the greppable `HUMAN_REVIEW:` escalation format with its parse rule,
  and the out-of-bounds section naming the guards that watch every weakening move.
  A drift-guard test file holds the document's executable claims to the code (#106).

### Fixed

- **A missing third-party package at model import read as a disproven design.**
  Found live: a `uv sync` dropped a wheel and the batch reported the part as
  failing. Now `origin: "environment"`, exit 4, package named in the hint; a
  broken local import chain stays the part's fault (#101).
- **Stale bytecode could answer for an edited file.** CPython validates a `.pyc`
  by (mtime seconds, size), so a same-length edit within one second re-executed
  the OLD contract under the NEW `contract_digest` — precisely an agent's rapid
  edit-loop shape, and precisely what would blind the claims pin. Contract and
  model entry files now compile from source, never from the bytecode cache (#105).

## [0.3.0] - 2026-08-08

Reference data with provenance — limits that know where their numbers came from (epic #5).

### Added

- **`partspec.refs`** — reference tables shipped in the wheel, importable with no engine
  installed: ISO 15 deep-groove bearing boundary dimensions (`iso15`, 22 designations) and
  the NEMA 17 mounting interface (`nema17`, exact conversions of the standard's own inch
  figures, with the inch figure in every note) (#95, #96).
- **`Referenced` values.** A bound taken from a reference table carries its citation into
  the report as `checks[].source` (`{standard, subject, field}`). Arithmetic sheds the
  attribution — a derived number is the author's, and a fragment must never launder the
  designer's numbers into a standard's (#95).
- **Contract fragments.** `nema17.mount(p)` and `iso15.seat(p, 608)` declare an interface
  standard's checks in one call, with namespaced ids (`nema17:pilot`,
  `nema17:left:bolt_circle`) and atomic failure — an invalid argument lands no checks. The
  bolt pattern carries the standard's citation; the clearance diameters are the designer's
  arguments and deliberately carry none (#96).
- **The report says when it proved nothing external.** A run-level
  `attribution: {dimensional, attributed}` block, and a CLI warning when every dimensional
  limit is unattributed — bounds derived from the model's own numbers prove only that the
  model matches itself (#97). The signal lives in the artifact, not just on stderr, because
  the MCP tools run `--quiet`.

### Changed

- `partspec diff` treats a check's `source` as part of the claim: stripping a citation
  reports as `limit_changed`, so quietly de-attributing a limit is visible on comparison
  (#95).

### Fixed

- The first version of the NEMA 17 table cited the catalogue's 31 mm hole square to the
  standard and derived the pitch circle from it — exactly backwards: NEMA ICS 16 states the
  pitch circle (1.725 in) directly. Caught in review against the standard's own text before
  release; the corrected derivation is recorded in `SPEC-contract.md` §11 as the cautionary
  example (#96).

## [0.2.0] - 2026-08-08

A part proven against mechanical intent (epic #6): the check vocabulary reaches drawing
callouts, and reports become comparable.

### Added

- **`keep_out` / `keep_in`** — spatial claims over declared regions, each with a mandatory
  weak-form verification shell so a region check can never pass vacuously; the region
  materializes tier-identically as a circumscribed prism (#85, `SPEC-contract.md` §4.4).
- **`checks[].components`** — a vector check names the failing axis: per-axis statuses whose
  worst is exactly the check's own, one adjudication rendered two ways (#86).
- **`hole_diameter`** — the first drawing dimension: count claims over detected bores, OCCT
  tier only; the mesh tier refuses rather than approximating a cylinder from triangles
  (#87, §4.5).
- **`partspec diff`** — two reports compared semantically (`SPEC-diff.md`): `removed` /
  `added` / `regressed` / `fixed` / `drifted` / `limit_changed`, exit 0 identical / 1
  different / 2 indeterminate / 64 usage. A partial or missing source closure blocks only
  the `identical` claim, and every indeterminate entry carries a machine-readable code.
  This closes the silent-contract-weakening gap on comparison (#88).
- **`bolt_circle`** — the mounting-interface callout as one check: the pattern circle is
  least-squares fitted, adjudication is strict against the fitted centre, and `tol > d` is
  refused at declaration (#89, §4.6).
- **`fillet_radius`** — every cylindrical blend within bounds; a part with no detected
  blends FAILS rather than passing vacuously, and the message names the detection gap
  (toroidal/spherical blends) rather than claiming none exist (#90, §4.7).

### Changed

- Usage errors exit 64 CLI-wide — argparse's exit 2 is remapped, because 2 belongs to
  `incomplete` (#88).

## [0.1.0] - 2026-08-07

### Added

- The report/status seam (P0), specified before implementation because it — not the CLI
  verbs — is the product contract.
  - `status.py`: five check statuses, verdict precedence, exit-code mapping, and interval
    adjudication. A relative comparison epsilon, `1e-6 + 1e-7·|limit|`, because binary STL
    stores float32 and a flat `1e-6` fails a geometrically perfect part above ~16.8 mm.
  - `report.py`: the JSON artifact, fixed field order, atomic writes, and an `error`
    placeholder written *before* the engine runs, since a `try/finally` cannot survive an
    OCP segfault.
  - `backend.py`: the `GeometryBackend` protocol and value types. `Unsupported` is a return
    value rather than an exception.
- Specs and decision log under `docs/`, promoted from the design survey.
- A conformance test asserting the schema example in `docs/SPEC-report.md` satisfies its own
  stated rules — that example is the contract, so it should be executable.
- `just ocp-guard`, asserting exactly one OCP provider is installed. `cadquery-ocp` and
  `cadquery-ocp-novtk` both own the top-level `OCP/` package and pip does not detect the
  conflict.

- **P1 — the mesh backend.** OpenSCAD → binary STL → trimesh/manifold3d, never
  `--summary` (D13). Implements bbox, volume, area, centre of mass, watertightness, solid
  count, genus, min distance, intersect volume and raycast; refuses topology counts.
  - Verified against closed-form geometry rather than against its own output: a 30x20x10
    block with a 6x6 square through-hole checks out on volume, area, bbox, genus and centre
    of mass, and a `$fn=16` cylinder matches the **16-gon prism** volume, not `pi*r^2*h` —
    which is D15 in one assertion.
  - `solid_count` via `manifold3d.decompose()` and `distinct_normals` by face-normal
    counting, both because trimesh's equivalents need `scipy`/`networkx` (D16).
  - `genus` is refused for multi-body parts: manifold3d reports the genus of the whole
    complex (two disjoint boxes give -1), which answers a question nobody asked.

- **P2 — the contract API.** `Part` with the closed v0 check vocabulary, engine-declaring
  source constructors, target resolution (`<module>[:<factory>]`, where the error message
  lists the available factories rather than saying "ambiguous"), and a `requires` evaluator
  that records the operands it read.
  - Phase ordering with short-circuiting: a failing parameter check stops the engine from
    running, and the geometry checks are reported `skipped` naming the blocker rather than
    quietly omitted.
  - `check` and `measure` subcommands. `measure` emits nothing that would be unsupported
    and produces no verdict — it is the adoption path, and partspec deliberately will not
    auto-generate checks from it.
  - A worked example under `examples/spacer/`.

### Fixed

- **A contract declaring no checks exited 0.** The implicit `builds` check satisfied the
  emptiness test, so the tool defeated its own vacuous-green guard. `Report.verdict` now
  excludes implicit kinds; a contract that asserts nothing is `EMPTY` with exit 3, as
  `SPEC-contract.md` §6 had already specified.
- **Relative source paths resolved against the CWD**, so a contract worked or failed
  depending on the shell's history. They now anchor to the contract file's directory.
- **`operands_of` returned names in `ast.walk` order**, which is breadth-first: `z + a*z + m`
  came back as `(z, m, a)`. Now sorted by source position, since the order reaches a report
  that gets diffed.

- **P4 — the OCCT backend.** One implementation serving build123d *and* CadQuery, with
  adoption at the front door (`adopted_via: "wrapped"` records it). Answers
  `topology_counts`, which the mesh tier refuses — that asymmetry is the point of tiers.
  - `genus` via the Euler-Poincare form `G = S - (V - E + 2F - W)/2`. The naive
    `V - E + F` is wrong on a BREP and quietly so: OCCT faces carry inner wires, so it
    reports a through-hole as genus 0 and a *blind* hole as genus -1. Verified on a box,
    one and two through-holes, a blind hole, a tube, and a real pillow block (genus 5).
  - `engines/pycad.py` builds from either Python engine. Adoption dispatches on
    `ShapeType()`, because `build123d.Shape.cast` returns `None` in 0.11.1 and
    `Compound(topods_solid)` constructs happily while reporting volume 0.
  - Models are called as `method(**params)` — no signature inspection, no guessing. A
    differently-shaped model gets an explicit adapter in the contract.

### Fixed

- **`is_valid` was called as a method** on the OCCT backend, raising
  `TypeError: 'bool' object is not callable`. build123d exposes it as a property —
  the exact divergence `SPEC-backend.md` §4 documents as the reason the adopt shim exists.
- **CadQuery could not import at all** after adding the OCCT extras.
  `cadquery-ocp` and `cadquery-ocp-novtk` both install a top-level `OCP/` package (326 vs
  322 files) with no conflict detection, and novtk landed last, stripping the VTK modules.
  Fixed with a `[tool.uv] override-dependencies` marker that drops novtk from resolution.

- **P5 — the differential test.** One contract, the same specified part in OpenSCAD and
  CadQuery, reports compared field-by-field. No tool feature was needed: the contract is
  Python, so sharing claims across implementations is a function.
- **`openscad(..., backend=...)`** selects the render backend, recorded as
  `engine.render_backend`. It changes the *artifact*, not just the speed — measured, the
  default Manifold backend produced 4 non-manifold edges on a community gridfinity bin
  where CGAL produced a clean mesh from identical source.
- **`watertight` now says why it failed** — boundary edges (a hole) versus non-manifold
  edges (surfaces touching). trimesh's `is_watertight` conflates them, and they have
  different causes and different fixes.

- **`part.source_closure`** — a digest over *every* file an OpenSCAD render reads, not just
  the entry point. `source_digest` covers one file, and on real libraries that is a small
  fraction of the build: the gridfinity bin in the dogfood corpus is one file of sixteen, so
  editing a helper three levels down changes the part while the entry hash does not. That is
  F13's failure class arriving in the provenance layer, and `diff` would have inherited it.
  - Digested over sorted **content** hashes rather than paths, so a CI run and a laptop run
    of the same tree agree.
  - Reports what it could not cover: `unresolved` includes, and `reads_external_data` when
    `import()`/`surface()` name files whose paths may be computed at render time. Either
    sets `partial`, stated positively so absence cannot be read as a guarantee.
  - Python engines emit none — a claim withheld rather than one made. **(Historical note, corrected 2026-08-09: this was already untrue at the tag. The Python closure shipped in `83f1119`, inside v0.1.0, emitting `scope: "model_directory", partial: true`; SPEC-report §8.3 records the reversal two days before the tag and this entry was written from the superseded plan.)**. `environment.packages`
    already covers installed deps; local helper modules beside a model are a recorded gap.

- **`p.topology(faces=, edges=, vertices=)`** — modelled face/edge/vertex counts, and the
  first v0 check that a tier cannot answer. On build123d or CadQuery it compares real
  topology; on OpenSCAD it reports `unsupported` with `requires: "occt"`, because a triangle
  mesh has no modelled faces and returning a triangle count is the PartCAD failure. That
  path was previously unreachable from any contract — every other kind resolved to a
  primitive both backends declare — so `requires` had never appeared in a real report.
  Any subset of the three may be constrained; `p.topology()` with none is a `ContractError`.

- **`PARTSPEC_OPENSCAD`** pins the OpenSCAD binary. The engine version changes the
  artifact: 2021.01 honours the removed `assign()` construct and 2026.08.01 ignores it, so
  a gear library's teeth silently vanish and the part comes out 35% smaller in every planar
  dimension — both versions exiting 0 with clean watertight meshes. An environment variable
  rather than a contract field, because which binary is installed is a property of the
  machine, not of the design.

### Changed

- `geometry.facets` is now `geometry.distinct_normals` (D16), named for what it measures
  rather than borrowing CGAL's vocabulary for a different quantity.
- `GeometryBackend.provenance()` takes the artifact rather than reading instance state.
- `just setup` installs **all** extras, matching CI exactly; `just setup-mesh` is the
  lighter OpenSCAD-only path and is explicitly not what the gate runs.
- `measure` now also reports `is_valid` and, on the OCCT tier, `topology_counts` — a
  deliberate superset of the check vocabulary. `is_valid` is not a check kind because it
  means different things per tier (an open shell is valid on OCCT, invalid on mesh), and a
  kind whose meaning moves with the backend breaks the one-contract property.
- A vector limit may now leave components unconstrained — `equals=(6, None, None)` claims a
  face count and nothing else. Those axes are skipped rather than adjudicated; previously
  they raised, because a per-component `Limit` of three `None`s trips its own validation.
  A limit that constrains *no* component is a `ContractError`, since folding zero components
  would return `pass`.
- `volume`, `center_of_mass`, `solid_count` and `genus` may now return `Unsupported`. The
  protocol signatures widened to match; `bbox`, `area` and `watertight` stay total.

### Fixed

- **The mesh tier answered questions it could not answer** (dogfood F14) — the second of
  the three failure modes `docs/SPEC-report.md` §1.1 names, in the tool built to prevent
  it. A contract declaring `volume`, `solid_count` and `genus` but not `watertight` scored
  four green checks and exit 0 on a community gridfinity bin that partspec itself knew
  carried 4 non-manifold edges. Reduced: a cube missing one face reported `volume 500.0`
  (against 1000.0 closed), `genus 1` and a centre of mass outside the material — all
  flagged `exact`.

  Each quantity now declares its precondition (`docs/SPEC-backend.md` §5.1.1) and refuses
  with the defect named rather than returning a number. Deliberately narrow: `solid_count`
  is refused only for non-manifold edges, since an *open* mesh still determines its own
  component count and over-refusal is its own way of not answering.

- **A dependency's error status was discarded.** Handed an open mesh, manifold3d returns an
  object reporting `Error.NotManifold`, `is_empty()` and zero triangles — on which
  `.decompose()` still returns a one-element list and `.genus()` still returns 1. Both were
  read without checking `status()`. Now checked.

- **Two libraries were measuring two different solids into one report.** `volume` came from
  trimesh and `genus`/`solid_count` from manifold3d, which rebuilds its input: on the clean
  CGAL gridfinity render — same 5,330 vertices, none displaced — it retriangulated 55 of
  10,688 triangles and moved the enclosed volume by 25.31 mm³ (0.078 %). An independent
  divergence-theorem sum agrees with trimesh, not manifold3d. Body count and genus are now
  computed over the exported triangles, which is what D15 requires. Verified equivalent to
  manifold3d on sound meshes.

- **`same-source` OCCT gap closed too:** `volume` and `center_of_mass` refuse for a shape
  bounding no solid. An open shell reports `volume 0.0` with `is_valid` True, so
  `volume(max=…)` would have passed on a shape containing no material.

### Notes

- The `approximate` machinery ships dormant. As v0 is scoped no check can produce it, so it
  is covered by direct unit tests rather than by use — see `docs/SPEC-report.md` §10.
- `just test-mesh-only` runs the mesh tests against a throwaway `partspec[mesh]` install.
  Because `just setup` takes all extras and scipy arrives only via build123d/cadquery, a
  mesh-tier dependency on scipy would otherwise pass both locally and in CI while breaking
  every mesh-only user.

- `PARTSPEC_REQUIRE_ENGINES` turns a missing engine from a skipped test into a hard failure.
  CI reported 195 passed / 23 skipped because no runner had an OpenSCAD binary, and the 23
  were the entire end-to-end path. The gate was green because the tests were absent.
- CI runs the mesh tier across **two OpenSCAD versions** — apt 2021.01 and a pinned
  2026.08.01 snapshot — because F13 found the same source builds a different part on each,
  and one version leaves that an anecdote. A step asserts each leg got the engine it
  declares, so an apt bump cannot collapse the matrix while still reporting two green checks.
  `just test-mesh-only` becomes a CI job; it guards a failure mode defined as "passes
  locally and in CI" and had been running only locally.
- `tests/test_cli.py` — the verbs had no tests at all, on a design whose D5 makes the exit
  code half the product contract. Every verdict now round-trips through `main` on a real
  render.

### Fixed

- **`measure` went silent exactly where it became most useful.** It dropped every
  `Unsupported` result, which was honest while a refusal only meant "this tier cannot answer
  this quantity". Since D17 it also means "this part is broken, and here is the defect", and
  the two arrived identically: absent. On a cube missing one face, `measure` printed area,
  bbox and solid_count with no volume, centre of mass or genus — in the verb that exists so
  somebody can see the numbers before deciding which are intent. `refused` now carries the
  reason per quantity and `unavailable` lists tier gaps separately.
- **A contract that raises exited 1** — this tool's code for *the part failed its contract*.
  A mistyped keyword argument raised `TypeError` out of `resolve()` and the traceback escaped
  `main`, so a malformed question was reported as a wrong answer about the design. Now exit
  4, for the same reason a `ContractError` during a run is.
- **The engine was resolved from a hardcoded path in `$HOME`.** `find_executable` preferred
  `~/Applications/openscad/OpenSCAD-nightly.AppImage` ahead of `PATH`, so `which openscad`
  said 2021.01 while every render used 2026.08.01 — on a tool whose own F13 says the version
  changes the part. The dogfood write-up claimed the wrong engine for two days as a result;
  the reports never did. The rule is now the pin, then `PATH`.
- **OpenSCAD's own diagnosis was discarded** unless it contained `ERROR` or `WARNING`, so
  `unrecognised option '--backend=CGAL'` — what 2021.01 says to a contract written against a
  newer engine — became `openscad exited 1` with no hint.
- **A mistyped `PARTSPEC_OPENSCAD` raised `FileNotFoundError` out of `run()`**, escaping the
  report machinery entirely: no artifact, no verdict, no exit code. Now a `BuildError`.
- **The Python tier recorded one file as the whole build input.** `engines/pycad.py` puts the
  model's directory on `sys.path` so a model can import helpers beside it, which makes those
  helpers build inputs by design — and editing one changed the part while `source_digest`
  stayed identical. `part.source_closure` now covers them, read from `sys.modules` after the
  build, with `partial` unconditional. `SPEC-report.md` §8.3 previously specified emitting
  nothing here; the reversal and its reasoning are recorded in place.

### Added

- **P6 — the product surface for agents.** `partspec-mcp`, an MCP server exposing `check`,
  `measure` and `render` as stateless tools — every call a fresh subprocess returning the
  same artifact the CLI writes, per the D18 boundary (#63, #66). `partspec render` emits
  canonical multi-view PNGs on the mesh tier, and the report references the renders it
  produced (#64, #65).
- **The convergence eval, run and recorded** ([`evals/CONVERGENCE.md`][convergence-evals]): 15/15 trials across
  five defect classes, an agent taking a broken part to green with exactly one edit each and
  zero contract-weakening attempts (#67).
- Tagged releases publish to PyPI via trusted publishing: tag/version assertion, build,
  `twine check`, cold-wheel smoke test, then OIDC upload (#60).

### Fixed

- The two pre-tag adversarial audits (#56, #57) and the eight-defect close: measurements
  that lied, failures that blamed the part instead of the machine, and one rename the audit
  itself got backwards.
- Release-window fixes (#70–#77): a failed build's hint is the diagnosis rather than a
  cache statistic; comparison operators slug to distinct check ids; the report records the
  invoked callable and how parameters applied; `engine.render_backend` is always present;
  `measure` and `render` carry the same engine provenance as `check`; the OpenSCAD method
  scratch moved out of the source tree.

[authoring-evals]: https://github.com/heibench/partspec/blob/main/evals/AUTHORING.md
[convergence-evals]: https://github.com/heibench/partspec/blob/main/evals/CONVERGENCE.md
[dogfood-results]: https://github.com/heibench/partspec/blob/main/notes/dogfood-results.md

[Unreleased]: https://github.com/heibench/partspec/compare/v0.7.8...HEAD
[0.7.8]: https://github.com/heibench/partspec/compare/v0.7.7...v0.7.8
[0.7.7]: https://github.com/heibench/partspec/compare/v0.7.6...v0.7.7
[0.7.6]: https://github.com/heibench/partspec/compare/v0.7.5...v0.7.6
[0.7.5]: https://github.com/heibench/partspec/compare/v0.7.4...v0.7.5
[0.7.4]: https://github.com/heibench/partspec/compare/v0.7.3...v0.7.4
[0.7.3]: https://github.com/heibench/partspec/compare/v0.7.2...v0.7.3
[0.7.2]: https://github.com/heibench/partspec/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/heibench/partspec/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/heibench/partspec/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/heibench/partspec/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/heibench/partspec/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/heibench/partspec/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/heibench/partspec/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/heibench/partspec/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/heibench/partspec/releases/tag/v0.1.0
