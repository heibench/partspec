# SPEC — the `partspec` report

**Applies to:** v0.7.8 — the release this text describes. The `Status:` line records when
this document was last revised in substance; it is provenance, not currency (#300).

**Status:** draft 13 · 2026-08-09 · §10 rewritten (`approximate` is live), §2.2 gains
`bool` and `rel`, the example's phantom `timestamp` removed; the render verb leaves
`render.json` on disk (its
payload with `renders` relativized, §8 rule 4) and every render records `render_bbox`
(`{min, max}` mm) — the framing scales with the part, so the bbox is the scale witness
`vdiff` (#21) compares when the pixels cannot; draft 11 added `render --section` (#19):
the payload may carry a `section_<plane>` view and a `section` block; draft 10 made `render` cover the OCCT tier
(#18): the verb accepts every engine, its OCCT payloads and reports carry
`render_tessellation`, and the Scope's engine-block subset is now the OpenSCAD case only;
draft 9 extended the identity-prefix scope to `render` (#103);
draft 8 added `expectation` (the claims pin), `invocation.timeout_s`, the exit-130 row,
batch coverage of `64` (reversing the earlier no-aggregation theory), the
model-cache-invalidation MUST, and the `measure` identity-prefix scope; draft 7 added
`checks[].components` / `region` / `hole` / `source`, run-level `attribution`, render
references, and the §8.3 closure reversal
**Scope:** the JSON artifact `partspec check` emits, and the process exit code that
accompanies it. `partspec measure` and `partspec render` emit sibling payloads that MUST
share the identity prefix — `schema_version`, `payload`, `tool`, `part`, `engine`,
`params`, built
by the same code (#47, #103) — followed by `geometry` for `measure` and by `renders` for
`render`, which carries no `geometry` block. Sharing that prefix is what makes `payload`
(§7.1) load-bearing: it is the only field that says WHICH of the three a consumer is
holding, the other five being identical by design. `render`'s engine block states what ran
(#18): on the OCCT tier the part builds through the same backend `check` uses, so the
block is §7's in full — `backend` included — and the payload carries
`render_tessellation` after `renders` (`{tolerance_mm, triangles}`: under D15 the
tessellation is what was shown, so its quality rides with the images). On OpenSCAD the
engine draws its own geometry and no measurement tier runs, so the block is the subset
`kind`, `version`, `render_backend`, `method`, `param_mode` (`backend` would name a tier
that did not run; `adopted_via` could only ever be null there) and there is no
tessellation record. With `--section` (#19) the payload's `renders` additionally carries
`section_<plane>` and a `section` block follows — `{plane, offset_mm, cut_triangles}`:
the offset is always the RESOLVED value (the bounding-box centre when none was given,
never left implicit), and `cut_triangles` counts the facets lying on the plane, so zero
states the plane passed only through voids rather than looking like an uncut render. A
plane outside the part's span on its axis MUST be refused (a section that misses the
part renders an image that looks fine — the documented failure), and the refusal names
the span. `measure --out` names where the engine's build artifact goes, and only the
OpenSCAD tier produces one (#204). The two spellings of that request are answered
differently in **both** the exit code and the payload shape, and neither difference is
incidental. A *filename* destination on such a tier is a refusal: the payload is the
failure shape below — identity plus `error`/`hint`, no measurements — at exit `64`
(§6.2), because the caller named a path they will go looking for and nothing will be
there. A *directory* destination keeps exit `0` **where the measurement succeeded**,
because that measurement is the verb's product and an unfulfillable side-request does not
take it away; the payload MUST then carry both the measurements and an `artifact` entry —
`{requested, written: false, reason}` — and stderr MUST say the same, because a request
the run could not fulfil must not read as one it did (§1.1), and a fact living only on
stderr is invisible to the machine this payload is for. Where the measurement did **not**
succeed — the model raised, the build failed — the run is a failure like any other and
takes the failure shape below, carrying `error`/`hint` and no `artifact`: the unfulfilled
`--out` is not the finding there, and reporting it beside a build that never happened
would be noise dressed as a second problem. On the tier that **does** produce an
artifact, either spelling succeeding at exit `0` MUST carry the same key in the other
state — `{requested, written: true, path}` — where `path` is where the artifact actually
landed (#225). `written` is a value rather than an inference from the key's presence
precisely so both states fit one key, and `path` is required rather than derivable: for a
*directory* destination the caller chose the directory and partspec chose the name inside
it, so a consumer that had to re-derive `<source stem>.stl` would be reimplementing a rule
this tool owns and has already changed once (#187). `check --out` writes `report.json`
into that directory on every tier, so it needs none of the above. On any failure after the
target resolves, both MUST emit a JSON object carrying that identity plus `error`/`hint` —
`renders` empty rather than absent — so a consumer always learns which file and revision
it was talking about. A target that never resolves has no identity to emit: those failures
are stderr + exit code only (for `check`, the placeholder artifact covers that window;
`measure` and `render` write no artifact).

Where `--out` is **absent**, every verb that takes it resolves the destination the same
way: `<contract dir>/outputs/<part-slug>`, anchored to the contract file and not to the
working directory, so the same command run from any directory writes to the same place.
`<part-slug>` is the module stem, plus `-<factory>` when a factory is named. Two
qualifications. `measure` names a build artifact rather than a directory of reports, so
this is where the artifact lands **on a tier that writes one at all** — the OCCT tier
builds in memory and creates nothing, as above (#204). And `vdiff` does not take a target:
its inputs are artifacts, so it defaults to `vdiff` beside `new` — inside it when `new` is
a directory, in its parent when `new` is a file — relative to the run being compared
rather than to any contract.

Under an explicit `--out`, `check` with several targets writes
`DIR/<part-slug>/report.json` rather than `DIR/report.json`, one directory being unable
to hold N reports at one deterministic name.

**Normative:** MUST / SHOULD / MAY per RFC 2119.
**Backing:** `DECISIONS.md` D5, D10, D13; [`notes/survey/04-kernel-capability.md`][survey-capability].

---

## 1. Why this document exists first

Per D5, the CLI verbs are not the contract. **The report schema plus the exit code is the
contract.** Everything else — the MCP layer, `diff`, CI annotations, a scorecard — is a
consumer of this artifact. If the report is right, an MCP server is a thin adapter; if it
is wrong, every consumer re-derives meaning from prose and the tool gets built twice.

So this is specified before any implementation.

### 1.1 The one property everything else serves

> **Silence must never read as success.**

Three distinct failure modes collapse into that sentence, and all three have been observed
in shipping tools:

- **Vacuous green** — cad-khana's own named anti-pattern: a module declaring no assertions
  exits 0 and writes `"assertions": []`. *"That is not a passing design; it is an unasked
  question, and an agent will read it as success."*
- **Unsupported-as-pass** — PartCAD normalizes an OpenSCAD mesh into a faceted
  `TopoDS_Shape`, so topology checks *run* and *return numbers* that mean nothing
  (`face_count` is a triangle count; there are no cylindrical faces to measure).
- **Approximate-as-pass** — an OpenSCAD `cylinder($fn=16)` is a genuine 16-sided prism.
  Fitting recovers the circumscribed radius (5.0000) while real bolt clearance is the
  apothem (4.9039), so `hole_diameter >= 10.0` passes at a reported Ø10.000 on a hole that
  clears Ø9.808 — **error always in the unsafe direction**.

A verification tool that reports any of these as green is worse than no tool, because it
converts an open question into a false assurance.

---

## 2. The measurement model

Every geometric quantity in a report is a **measurement**, not a float. A bare float cannot
express what the mesh tier actually knows.

```jsonc
{
  "value": 634.5135,
  "unit": "mm3",
  "exactness": "exact" | "approximate",
  "bounds": [633.9, 634.6]        // REQUIRED iff exactness == "approximate"
}
```

- `value` — the best estimate.
- `exactness` — **a property of *(check, backend, geometry)*, not of *(check, backend)*.**
  It MUST be determined per evaluation, never looked up in a static table.
- `bounds` — a closed interval `[lo, hi]` guaranteed to contain the true value, where "true
  value" means what §2.3 says it means. **Asymmetric bounds are expected and MUST be
  preserved**; a backend derives the interval from what it actually did, never from a
  constant and never from an assumed sign.

> **Tessellation is not a source of `approximate`.** An earlier draft treated it as the
> archetypal one. Under §2.3 a mesh **is** a polyhedron and its volume, area, bbox, genus
> and watertightness are computed exactly from its triangles — changing `$fn` does not
> degrade a measurement, it **produces a different part**, which the tool should report
> loudly rather than absorb into an error bar. The one genuine source of inexactness on the
> mesh tier is float32 coordinate quantization in binary STL (~1e-7 relative); see
> `SPEC-backend.md` §5.2.

A backend that cannot honestly produce `bounds` for a quantity MUST NOT report that
quantity as `approximate`; it MUST report the check as `unsupported` (§3). Guessing an
error bar is the same lie in a smaller font.

### 2.1 Scalar and vector measurements

Measurements are **scalar by default**. A vector quantity (an envelope, a centre of mass)
carries an array `value`, and its `bounds`, when present, is an array of intervals
**positionally aligned with `value`**. A measurement is vector iff `value` is an array;
there is no separate type tag.

```jsonc
{
  "value":  [15.8, 15.8, 8.0],
  "unit":   "mm",
  "exactness": "exact",
  "axes":   ["x", "y", "z"]
}
```

```jsonc
{
  "value":  [30.02, 20.01, 10.00],
  "unit":   "mm",
  "exactness": "approximate",
  "bounds": [[29.98, 30.04], [19.97, 20.03], [9.98, 10.02]],
  "axes":   ["x", "y", "z"]
}
```

`axes` is REQUIRED on vector measurements and names each component, so a consumer never
infers meaning from position alone. Adjudication (§3.1) is applied **per component**, and
the check's status is the worst across components in the order
`fail > approximate > pass`.

### 2.2 Units

`mm` is the only length unit in v0, matching every engine in scope. `unit` is nonetheless
REQUIRED on every measurement, because it distinguishes quantities a bare number cannot:

<!-- BEGIN GENERATED: unit-table -->
| unit | emitted by |
|---|---|
| `mm` | `envelope`, `hole_diameter`, `bolt_circle`, `fillet_radius`, `min_wall` |
| `mm2` | `area` |
| `mm3` | `volume`, `keep_out`, `keep_in` |
| `deg` | `draft_angle` |
| `count` | `solid_count`, `genus`, `cavities`, `topology` |
| `bool` | `watertight`, `self_intersection_free` |
| `rel` | `step_roundtrip` |
<!-- END GENERATED: unit-table -->

`bool` and `rel` were absent from this table while the tool emitted both. §5's remark that
`unit: "bool"` disappears was scoped to `requires` predicates, which carry no measurement
at all, and got over-generalised into a claim about the vocabulary. The table is generated
from `contract.MEASURANDS` now, so a new check emitting a new unit brings its own row.

Values are never scaled. There is no `part.units` field: a single legal value is not
information, and every measurement carries its own unit anyway.

### 2.3 The measurand — what "the true value" refers to

**A measurement describes the geometry as actually authored and exported, NOT an idealized
smooth solid the designer may have had in mind.** (Settled 2026-08-02; this determines
every backend method's obligation to produce `exactness` and `bounds`.)

An OpenSCAD `cylinder($fn=16)` **is** a 16-sided prism. Its volume, bounding box, genus,
clearance and interference are therefore **closed-form exact**, not approximations of a
cylinder. This is consistent with §1.1 (which calls it "a genuine 16-sided prism"), with
§3.2's prohibition on reconstruction, and with investigation 04 §4's conclusion that for
fit and printability the mesh is sometimes the *more honest* representation.

The rejected alternative — measuring against the idealized smooth solid — would make every
curved-surface quantity approximate, and is **unimplementable on the mesh tier anyway**,
because the exported STL has erased `$fn` and the tool cannot recover what the designer
meant.

**The honest corollary, which MUST be stated rather than hidden:** `partspec` measures the
artifact, not the intent. A coarse `$fn` is a *design choice the tool reports* (via
`geometry.triangles`), not an error the tool bounds away. A part whose bore is a 16-gon
will be measured as a 16-gon — which is what a real dowel will experience.

---

## 3. Check status — five values, and how they are decided

```
pass · fail · approximate · unsupported · skipped
```

Only `pass` is green.

| status | meaning |
|---|---|
| `pass` | Evaluated and satisfied, **conclusively** |
| `fail` | Evaluated and violated, **conclusively** |
| `approximate` | Evaluated, but the error interval straddles the threshold — **indeterminate** |
| `unsupported` | This backend cannot evaluate this check on this geometry at all |
| `skipped` | Not evaluated: a referenced part is absent, or a `parameter` check short-circuited the run (§4.1) |

### 3.1 Adjudication against an interval

This is the core algorithm and the reason `approximate` is a *status* rather than a flag.

For a threshold check (`measurement ≥ limit`, or `≤`, or within a range):

1. If `exactness == "exact"` → compare `value` directly → `pass` or `fail`.
2. Otherwise compare the **whole interval** `[lo, hi]` against the limit:
   - interval lies **entirely** in the satisfying region → `pass`
   - interval lies **entirely** in the violating region → `fail`
   - interval **straddles** the limit → `approximate`

So an approximate measurement still adjudicates **conclusively** most of the time. A wall
measured at 2.4 mm ±0.01 against a 2.0 mm minimum is a real `pass`; the same wall measured
at 2.01 mm ±0.05 is `approximate`, because the tool genuinely does not know.

`approximate` therefore means exactly one thing: **the answer is inside the error band.**
It is not a general "this was a mesh" marker — that is what `exactness` on the measurement
records.

### 3.2 `unsupported` vs `approximate`

`unsupported` MUST be used when the *representation lacks the entity*, not merely precision.
On a triangle mesh there is no cylindrical face, so hole diameter is `unsupported` — never
`approximate`, and never fitted (see §1.1). Per investigation 04 §4, fitting produces
confident wrong numbers in the unsafe direction; **a backend MUST NOT satisfy a check by
reconstructing an entity the representation does not contain.**

There is a second, less obvious route to `unsupported`: **a quantity for which no honest
two-sided bound exists.** Wall thickness is the worked example. It is measured by ray or
maximum-inscribed-sphere sampling on *both* tiers, and sampling is one-sided by
construction — more samples can only ever find a *thinner* wall. A measurement is therefore
an **upper bound on the true minimum**, not a centred interval, and no principled `lo`
exists.

By §2's rule ("a backend that cannot honestly produce `bounds` MUST NOT report that
quantity as `approximate`"), **`min_wall` is `unsupported` on the mesh tier** until someone
derives a defensible lower bound — the tier refusal stands.

On the OCCT tier it **is** an `approximate` check, and the first one: a guaranteed `[lo,
hi]` interval whose straddle of a limit adjudicates `approximate` and exits 2 (§10, and
`SPEC-contract.md` §4.11). An earlier draft of this paragraph said "it is not an
`approximate` check" without the tier qualifier, which stopped being true when #140
shipped.

### 3.3 Bound epsilon

Every threshold comparison MUST apply a tolerance, because contracts routinely derive
geometry from the same constant they bound against and exact float equality at a boundary
is a coin flip. The tolerance is **relative as well as absolute**:

```
ε(limit) = 1e-6 + 1e-7 · |limit|
```

**A purely absolute `1e-6` is wrong, and it breaks the v0 envelope check.** Binary STL
stores coordinates as float32, whose half-ulp is `v · 2⁻²⁴ ≈ 5.96e-8 · v` and therefore
exceeds `1e-6` for any dimension above ~16.8 mm. Measured:

```
cube([120.3, 80.7, 40.1])  →  extents 120.30000305, 80.69999695, 40.09999847
                              deltas  +3.05e-6, −3.05e-6, −1.53e-6
```

Against `max: 120.3` an absolute `1e-6` yields a **conclusive `fail` on a geometrically
perfect part** — and `envelope` is one of only three geometry checks in v0, so this is the
main path, not a corner case. The relative term covers float32 quantization with an order
of magnitude of headroom while staying far below any real engineering tolerance.

(cad-khana uses a flat `1e-6`, which is safe there because it operates only on in-memory
OCCT doubles and never round-trips through binary STL.)

### 3.4 Limit forms

A check's `limit` is one of a small closed set, so consumers can render and compare limits
without knowing the check kind:

| form | shape | satisfied when |
|---|---|---|
| minimum | `{"min": 2.0}` | `value ≥ min` |
| maximum | `{"max": 40.0}` | `value ≤ max` |
| range | `{"min": 7.9, "max": 8.1}` | `min ≤ value ≤ max` |
| equality | `{"equals": 1}` | `value == equals` (exact types only) |
| membership | `{"in": ["inner", "outer"]}` | `value ∈ in` |

`equals` and `in` MUST NOT be used with an `approximate` measurement — equality against an
interval is not decidable, and a check that needs it MUST be expressed as a `range`.

**Vector limits.** Any of the numeric forms MAY carry an array value instead of a scalar,
positionally aligned with the measurement's `value` and `axes`, and compared elementwise:
`{"max": [40, 40, 15]}`. A length mismatch between limit and measurement is a **contract
error** (`verdict: "error"`), never a partial evaluation. The limit does **not** carry its
own `axes` — a second copy of the axis order is redundant state that can desynchronize from
the measurement's, and the measurement is the authority.

---

## 4. Phases

Checks run in two phases, and the distinction is visible in the report because it changes
what a result means.

| phase | when | engine required |
|---|---|---|
| `parameter` | before the engine is invoked; pure arithmetic over declared inputs | no |
| `geometry` | after the artifact is built | yes |

Every check carries `"phase": "parameter" | "geometry"`.

The parameter phase is the fully engine-neutral core — `bayonet-lock-scad`'s entire
documented rule set (`entry_depth < part_height`,
`pin_radius + allowance/2 ≤ shell_thickness`, `0 < sweep_angle < 360/number_of_pins`) lives
here and needs no kernel at all. Parameter checks MUST report `exactness: "exact"` and MUST
NOT report `approximate` or `unsupported`; arithmetic does not degrade by backend.

### 4.1 Short-circuiting

**If any `parameter` check fails, the engine MUST NOT be invoked.** Building geometry from
parameters already known to be invalid wastes time and, worse, produces a shape whose
geometric measurements describe something the contract has already rejected.

In that case every `geometry` check MUST still appear in the report with
`status: "skipped"` and `detail` naming the parameter check that short-circuited. They MUST
NOT be silently omitted — an absent check is indistinguishable from a check that was never
declared, which is the vacuous-green failure in another form.

The verdict is `fail` (a check failed), so the exit code is `1`, not `2`.

---

## 5. Write semantics

1. **A report MUST be written on every terminal outcome, including `error`.** A run that
   crashes and leaves the previous report in place is the worst failure in the system: the
   file is stale but reads as current, and both a human and an agent will trust it. This is
   why `verdict: "error"` exists rather than simply exiting non-zero.
2. **An `error` placeholder MUST be written *before* the engine is invoked**, and replaced
   by the real report on completion. A `try/finally` cannot survive a native fault: an OCP
   segfault or an OOM kill takes the process down with no Python unwinding, leaving
   yesterday's `verdict: "pass"` at a deterministic path. Writing the placeholder first
   means the *worst* case is a report that says the run died, never one that says the part
   was fine. Only the in-process OCCT tier is exposed to this — OpenSCAD runs as a
   subprocess whose crash the parent observes normally.
3. **Writes MUST be atomic** — write to a temporary file in the destination directory, then
   rename. A partially-written report that happens to parse is worse than none.
4. **Batch runs MUST NOT abort early.** When several parts are checked in one invocation,
   a failure in one MUST NOT prevent the others from being evaluated and written; failures
   are collected and reported as a single non-zero exit at the end. Directly cad-khana's
   deferred-failure lesson — the purpose is that every report on disk is fresh.
5. The report path is deterministic from the target, so that a stale file is overwritten
   rather than accumulating beside its replacement.

---

## 6. Verdict and exit codes

### 6.1 Verdict

Computed from the check statuses, in this precedence order:

A build failure is split by **cause**, because the two mean opposite things to a
reader. A design that does not compile is a statement about the part: `builds` fails,
`verdict: "fail"`, exit `1`. An *environment* fault — no engine on `PATH`, a mistyped
`PARTSPEC_OPENSCAD`, a missing engine package, a source file that is not there, a render
that exceeded its timeout — is not a statement about the part at all, and MUST NOT be
reported as one. It is `verdict: "error"`, exit `4`, with every declared check `skipped`
and `builds` never `fail`. A CI run on a machine with no OpenSCAD installed must not
report the design as disproven.

The distinction is carried in `BuildError.origin` and surfaced in the report as a field a
consumer can branch on — not as prose in `detail`. It has **three** values, not two:
`"environment"`, `"model"`, and `null` for a failure partspec cannot attribute to either.
The third is not a gap in the enumeration but a claim of its own, and the paragraphs below
on a build that succeeded are where it is earned — a reader must not treat `null` as a
missing answer, nor as a licence to assume `"model"`.

A third case reaches `error` by neither route: the build **succeeded** and the engine
built something other than what the source describes, so what the contract names is not
what was measured. It arrives three ways.

A **name did not resolve**. For a module or an include the mechanism is direct — OpenSCAD
renders an unresolved call's children *not at all*, so a misspelt module or an include
that did not open removes geometry and still exits `0` with a well-formed, watertight mesh
(`FAILURE-MODES.md` §1). For an unresolved function or variable the expression yields
`undef` instead, which may or may not reach geometry; partspec refuses either way, because
stderr cannot say which, and a value silently substituted into a dimension is precisely
the case it must not wave through.

A **value did not convert**. Every name resolved and the expression was well-formed, but
the value reaching a module's parameter was not of a type it accepts, so the engine
substituted **that module's own default** and said so. `cube(size=[o, 30, 6])` with
`o = undef` exports a 1×1×1 unit cube — clean, watertight, one solid, exit `0` — on both
pinned engines. This is not a name failing to resolve and MUST NOT be reported as one: the
diagnosis and the remedy differ, and `error` MUST carry the cause it actually found.

A **build input was not there**. Every name resolved and no value was substituted, but a
file-reading construct named a path that does not exist, so the engine rendered it as
nothing and exited `0`. Measured on both pinned engines for `import()` and for
`surface()`. The evidence is `part.source_closure.engine_inputs.missing` (§8.3), taken
from the engine's own dependency file rather than from stderr, so it covers every such
construct in one shape and needs no per-construct wording. Note that `unseen` is **empty**
in this case and MUST NOT be consulted for it: the `external_data_reads` token is emitted
only when `engine_inputs.state` is not `complete`, and here the engine answered in full —
the full answer being that the file is absent. A consumer reading `unseen` alone sees a
closure with no gaps, which is correct and is not the same question.

**`missing` is evidence, not the verdict, and a producer MUST NOT read one off the other.**
The dependency file records what the engine *resolved*, which is a wider set than what it
*exported*: OpenSCAD evaluates a `%` (background) subtree and then leaves it out of the
export, so a file referenced only from one is listed in `missing` while the exported
geometry is byte-identical with and without it — measured on both pinned engines. Such a
file is not a build input and MUST NOT hold the verdict; `*` (disable) is never evaluated
and never appears; `#` (highlight) IS exported and MUST be treated like an unmodified
reference. Distinguishing them is the producer's obligation, on evidence that carries the
modifier — the `.csg` export does, engine stderr does not — and where no such evidence can
be obtained the producer MUST keep the refusal rather than assume the file was scaffolding.
Two properties of that evidence are load-bearing, and a producer that gets either wrong
fails **open** — it passes a part whose export is provably short, which is the failure this
whole arrival exists to catch. The evidence MUST describe **the model that was built**,
with the same parameter values and the same entry file, because a modifier may sit behind a
parameter. And a name in it MUST be matched to a dependency-file entry by **resolved
path**: that entry is canonicalised, while the reference as written need not be, so any
textual comparison between the two is unsound in both directions.
`engine_inputs.missing` itself still reports what the engine said, unnarrowed: it is a
record of the run, and narrowing it would destroy the evidence the judgement was made on.

In none of these cases can the tool claim it measured the part the contract describes, so
no geometry check is evaluated:
`builds` and every geometry check are `skipped`, `verdict: "error"`, exit `4`, and `error`
carries the engine's own diagnostic line. Parameter-phase checks are unaffected — they are
arithmetic over the contract's inputs and need no engine.

Here `builds` MUST NOT be reported as `fail` and `build_origin` MUST remain `null`: the
source compiled, so a failing `builds` would be a statement about the design that has not
been earned, and whether an unresolved name is a typo in the source or a library absent
from this machine is exactly what partspec cannot determine — as is whether an absent
build input is a mistyped path or a file a two-pass workflow has not produced yet. It
claims neither, and states only what it knows — that it did not measure the part it was
given.

**A sibling payload that refuses for one of these reasons attributes it the same way.**
`measure` and `render` produce no verdict, so they carry the refusal as their own
`error`/`hint` and exit `4`. This holds today for the first two arrivals — a name that did
not resolve and a value that was defaulted, which share one stderr signal. The third is
`check`-only so far: `measure` and `render` do not yet read `engine_inputs.missing`, and
until they do a reader MUST NOT infer one verb's answer from another's on that arrival
(#355).

`render` additionally publishes an `origin`, and on both arrivals it refuses for that
field is `null` — a defaulted `"model"` would assert the very attribution the report
declines to make.

**What a refusing `render` leaves on disk**, stated positively because "nothing is
written" is not true and a consumer would plan around it: no view is rendered, and the
views a previous run left are byte-for-byte untouched. Two things do move, and both are
pre-existing rules rather than consequences of the refusal. The engine's STL export is how
the fault is detected at all, so it lands in `--out` and replaces whatever was there. And
`render.json` is **removed**, as it is on every failing render, so a later `vdiff` cannot
read the previous run's payload as this one's (§8 rule 4). A consumer must therefore read
the *absence* of `render.json` as "this run wrote no payload", never as "the run left the
last one intact".

(`check --render` is unaffected by any of this, because it never reaches the render path —
the run has already errored.)

| verdict | condition |
|---|---|
| `error` | the contract raised, the build could not be *attempted*, or the build succeeded and the engine reported that it built something other than the source — a name it could not resolve, a value it could not convert and defaulted, or a build input it asked for and did not get (see above) |
| `empty` | zero checks were declared |
| `fail` | ≥1 `fail` |
| `incomplete` | no `fail`, but ≥1 `approximate` / `unsupported` / `skipped` |
| `pass` | ≥1 check, **all** `pass` |

`empty` is a distinct verdict rather than a degenerate `pass`, because a contract with no
checks is the vacuous-green case and is the single most likely thing an agent produces when
it does not know what to assert.

### 6.2 Exit codes

| code | verdict | meaning |
|---|---|---|
| `0` | `pass` | everything asserted was proven |
| `1` | `fail` | something asserted was disproven |
| `2` | `incomplete` | nothing disproven, **not everything proven** |
| `3` | `empty` | no checks declared |
| `4` | `error` | the contract raised, the environment prevented a build, or the build succeeded and the engine built something other than the source (an unresolved name, or a value it could not convert and defaulted) |
| `64` | — | usage error: unresolvable target, bad arguments (`EX_USAGE`) |
| `130` | — | user interrupt (SIGINT convention); the operator's own abort, never a verdict |

**`2` is the load-bearing one.** It is what stops D10 from being a comment. A tool that
exits 0 on a part whose checks were mostly unavailable has told the operator that the part
is fine, which it has not established.

**Batch invocations.** One report is written **per part** (§5.4), not per invocation. When
several parts are checked at once, the process exit code is that of the
**highest-precedence verdict across all parts**, using the same order as §6.1
(`error > empty > fail > incomplete > pass`).

An unresolvable target exits `64`, outranking every verdict — but the remaining targets
MUST still be evaluated and written first (§5 rule 4). An earlier draft reserved `64`
from this aggregation on the theory that usage failures produce no reports; the
placeholder rule (§5 rule 2) means they do — an error artifact naming the dead run — and
a batch that reported a mistyped (or deleted: that is how a contract vanishes in a
weakening attack) target as a mere part-verdict would bury the fact that a question went
unasked. A user interrupt (exit `130`) is the one failure that does stop a batch: it is
the operator's own abort, not a part's.

The model-module cache MUST be invalidated after every Python-engine build in a process
(every module a resolve or build introduced from the model's directory evicted from
`sys.modules`), because a second contract
importing an edited helper otherwise gets the previous version — a stale build reported
as fresh, with a closure digest computed from a file that never reached the interpreter
(POST-V0 §8, shipped with #29).

**`--allow-incomplete` is deliberately NOT in v0.** It would map `incomplete` → exit `0`,
and it is the obvious first request once exit `2` becomes inconvenient. Shipping the escape
hatch alongside the discipline means the discipline is never actually tested: the first
time a mesh-tier part reports `incomplete`, the flag gets set in CI and D10 quietly stops
existing.

Withhold it until the dogfood run shows a case where `incomplete` is genuinely the right
long-term state for a part rather than a gap to close. If it is added later it MUST NOT
change the report body, and MUST be recorded (`invocation.allow_incomplete: true`) — an
escape hatch that leaves no trace is indistinguishable from the bug it papers over.
Adding both the flag and the field later is a non-breaking change (§7.1, unknown fields),
so nothing needs reserving now.

---

## 7. Schema

`schema_version` is an integer, incremented on any breaking change. Consumers MUST reject
an unknown major version rather than best-effort parse it. It says how to READ the
document; `payload` (§7.1) says WHAT the document is, and a consumer needs both — the
version alone cannot tell a report from a `measure` dump, the two carrying the same one.

```jsonc
{
  "schema_version": 1,
  "payload": "report",                                 // which artifact this is (7.1)
  "tool": { "name": "partspec", "version": "0.7.8" },  // whatever is installed; a
                                                       // consumer keys on `schema_version`
                                                       // above, never on this

  "part": {
    "id": "bayonet-lock-pin",
    "contract": "spec.py:lock",           // the module in its own frame, then the symbol
    "contract_digest": "sha256:4a17...",
    "source": "vendor/bayonet_lock.scad",
    "source_digest": "sha256:9f2c...",
    "source_closure": {                // §8.3 — every file the render reads
      "digest": "sha256:b304...",      // over sorted content hashes, not paths
      "files": 16,
      "imports": {},                   // distributions the model loaded; {} is a claim, absent is not
      "unseen": []                     // the closed gap vocabulary; partial == bool(unseen)
    }
  },

  "engine": {
    "kind": "openscad",              // openscad | build123d | cadquery
    "version": "2021.01",
    "backend": "mesh",               // the measurement tier: mesh | occt
    "render_backend": "CGAL",        // always present: the pinned choice, or null = the engine's own default
    "adopted_via": null,             // "wrapped" when a cadquery shape entered the occt backend
    "method": null,                  // the invoked callable/module when method= was set; null = the default entry
    "param_mode": "define"           // OpenSCAD only: "define" (-D) | "call" (a derived entry invoking method)
    // "source_rendered": "derived"  // call path only: the engine's entry was a derived scratch, not the digested file
  },

  "params": { "interface_radius": 8, "allowance": 0.2 },

  "geometry": {
    "triangles": 3748,               // mesh tier only; drift explainer (chord error ~ edge length)
    "distinct_normals": 70           // mesh tier only; identity signal, tracks $fn, retriangulation-invariant
  },

  "renders": {                       // only when the run produced images (§8.4); omitted otherwise
    "iso": "renders/iso.png",        // relative to the report's directory, per §8 rule 4
    "front": "renders/front.png",
    "top": "renders/top.png",
    "right": "renders/right.png"
  },
  "render_tessellation": {           // §8.4 — beside renders when they came from the OCCT
    "tolerance_mm": 0.1,             // tier's rasterizer (#18): the tessellation is what was
    "triangles": 520                 // shown (D15). Absent for OpenSCAD renders.
  },

  "verdict": "incomplete",
  "counts": { "total": 5, "pass": 3, "fail": 0,
              "approximate": 0, "unsupported": 1, "skipped": 1 },
  "attribution": { "dimensional": 2, "attributed": 0 },   // envelope + hole_diameter,
                                                         // neither citing a source: this
                                                         // example draws the §6 warning

  "checks": [
    {
      "id": "sweep_fits_pin_count",
      "kind": "requires",
      "phase": "parameter",
      "status": "pass",
      "measurement": null,
      "limit": null,
      "expr": "0 < sweep_angle < 360/number_of_pins",
      "operands": { "sweep_angle": 40, "number_of_pins": 2 },
      "detail": null
    },
    {
      "id": "pin_fits_shell",
      "kind": "requires",
      "phase": "parameter",
      "status": "pass",
      "measurement": null,
      "limit": null,
      "expr": "pin_radius + allowance/2 <= shell_thickness",
      "operands": { "pin_radius": 1.0, "allowance": 0.2, "shell_thickness": 2.5 },
      "detail": null
    },
    {
      "id": "envelope",
      "kind": "envelope",
      "phase": "geometry",
      "status": "pass",
      "measurement": {
        "value": [15.8, 15.8, 8.0], "unit": "mm",
        "exactness": "exact", "axes": ["x", "y", "z"]
      },
      "limit": { "max": [40, 40, 15] },
      "components": { "x": "pass", "y": "pass", "z": "pass" },
      "detail": null
    },
    {
      "id": "watertight",
      "kind": "watertight",
      "phase": "geometry",
      "status": "skipped",
      "measurement": null,
      "limit": { "equals": true },
      "detail": "not evaluated: part 'cap' absent from this run"
    },
    {
      "id": "bore_diameter",
      "kind": "hole_diameter",
      "phase": "geometry",
      "status": "unsupported",
      "measurement": null,
      "limit": { "min": 10.0 },
      "detail": "mesh backend has no cylindrical faces; fitting is unsafe on faceted prisms",
      "requires": "occt"
    }
  ],

  "error": null,
  "hint": null,
  "build_origin": null,              // "environment" | "model" | null — see below
  "build_stderr": null,              // engine's full stderr on a build failure; hint is one selected line of it

  "environment": {
    "python": "3.12.7",
    "packages": { "build123d": "0.11.1", "cadquery-ocp": "7.9.3.1.1",
                  "cqgridfinity": "0.5.7", "numpy": "2.5.2" },  // every installed
                                                                // distribution, name-sorted
    "platform": "linux-x86_64",
    "duration_ms": 812
  },

  "invocation": { "argv": ["check", "parts/bayonet"], "timeout_s": 300.0 }
}
```

This example is **conformant and confined to the v0 check set** (D11): parameter predicates
plus `envelope` and `watertight`. `counts.total` equals `len(checks)`, and the five status
counts sum to it — both MUST hold. `bore_diameter` is shown only to illustrate
`unsupported` + `requires`; it is not a kind, then or now — the shipped hole check is
`hole_diameter` (`SPEC-contract.md` §4.5, since 0.2.0), and the example predates it.

Note there is **no `approximate` check here, and there cannot be one in v0** — see §10.

### 7.1 Field rules

- **`payload`** — which artifact this document is. The three this specification governs
  are `report`, `measure` and `render`; `lint`, `diff` and `vdiff` name the sibling
  artifacts that carry the same field. A consumer MUST key on it rather than on `tool.name`
  or on the presence of a block: `check`, `measure` and `render` all emit
  `schema_version: 1` under `tool.name: "partspec"` and share the whole identity prefix by
  design (Scope), so until this field existed the three were told apart only by guessing
  from the keys further down (#295). Additive (no schema bump), and therefore **optional to
  a reader**: an artifact written before the field existed carries none, and its absence
  means "an older partspec wrote this", never "not a report".
  The optionality is also why a structural test — does this document declare a `verdict`
  and `counts`? — remains the right guard for "is this a report", and `partspec diff`
  keeps that one: a guard keyed on `payload` would refuse every report the tool wrote
  before this release, and a document that declares a verdict is a report whatever it
  calls itself.
- **`part.contract`** — the contract module, followed by `:<factory>` when the invocation
  named one. The path is in the frame §8 rule 4 fixes and `_anchor` already uses —
  relative to the contract's own directory, which for the contract file itself is its
  filename (#45; the alternative, a CWD-relative path, makes two checkouts of one tree
  produce different reports). The symbol is the rest of the identity, and it is not
  decoration: two factories in one module returning parts with the same `id` otherwise
  produce **byte-identical** `part` blocks — same module-scoped `contract_digest`, same
  source, same closure — and nothing in either artifact says which target was invoked
  (#297). A module declaring a single factory needs no name to resolve, so both
  `<module>` and `<module>:<factory>` are well-formed and a consumer MUST parse the suffix
  as optional — but partspec **resolves the symbol and records it either way**, so a report
  of a target that RESOLVED carries the suffix whenever the module declares a factory
  (#343). The qualifier is not decoration: the pre-resolution placeholder below is written
  before any of that is known and echoes the argument as typed, so a bare `<module>` is
  still a shape this tool writes. That resolution is what makes the field comparable:
  emitted only when the invocation typed it, one run spelled two ways — `spec.py` and
  `spec.py:spacer` for the same single-factory module — recorded two different strings for
  one part, and no comparator could tell that pair from a genuine change. It does **not**
  move the default `--out` directory, which keys on the factory the invocation named:
  `partspec check spec.py` writes `outputs/spec`, as it has since v0, and a test pins it.

  It remains **provenance, not comparison identity**. What a comparator pairs two reports on
  is `part.id`: `partspec diff` refuses a mismatch there. It now *compares* `part.contract`
  as well, and what is outcome-bearing is the **factory alone**, where both sides name one —
  `SPEC-diff.md` §3 states the rule, why the guard is needed for the two spellings above,
  and why a moved module path is recorded rather than reported (renaming a contract file
  changes no part). The digests are not join keys and are not outcome-bearing either: two
  reports with one `part.id` and different `contract_digest`s compare `identical` at exit 0,
  deliberately, because the digest is module-scoped and an edit to a factory that cannot
  reach this part moves it. `partspec diff` reports it as `contract.digest_changed` and
  names it on its summary line whatever the outcome.

  Two forms of this field are **not** `<module>[:<factory>]`, and both are visible from
  the artifact. The pre-resolution placeholder (§5 rule 2) is written before the target
  resolves, so it can only echo the argument as typed — absolute path included — and its
  `part.id` is `"unresolved"`. A library caller that invokes `run()` with no
  `contract_path` records `"<in-memory>"`, there being no file to name — or
  `"<in-memory>:make"` when it also names a factory, the suffix rule above applying to
  that placeholder like any other module. The CLI cannot produce either `<in-memory>`
  spelling; the placeholder above is a CLI artifact and the common case for one.
- **`part.contract_digest` / `part.source_digest`** — sha256 of the contract module and of
  the source content. Digests give **identity**, and support **comparison-based** tamper
  evidence: two reports whose `contract_digest` differs were produced from different
  contracts.

  They do **not** make a weakened contract visible in a *single* report — "the digest
  changed" is a two-observation predicate, and D6 assigns that job to the semantic `diff`
  that §9 defers. Two further limits, stated rather than glossed. The contract digest is
  **module-scoped** while the part it describes is one factory's output — narrower than
  the module whatever `part.contract` happens to spell, since a module with several
  factories resolves to one of them and a module with one is still not the same thing as
  the function. So the digest **over-fires**: an unrelated edit anywhere in the module,
  a sibling factory included, moves the digest of a part that did not change. And
  `source_digest` covers only the named file, **not** anything
  it pulls in via `include <>` / `use <>`.

  > **The v0 gap, closed post-v0.1: silent contract weakening.** An agent that deletes a
  > check produces a report that is internally consistent and green. `counts.total` and
  > `contract_digest` make it *detectable on comparison*, not *visible on inspection* —
  > and `partspec diff` (`SPEC-diff.md`) is now that comparison: a removed check is named
  > by id, exit 1. Since #31 the no-baseline half is closed too: the claims pin
  > (`--expect`, the `expectation` block below) fails a single run whose declared claim
  > set drifted from its committed lock — no previous artifact required.

  Module-scoping is deliberate, not an oversight: digesting only the resolved symbol would
  miss an edit to a module-level constant such as `MIN_WALL`, which is precisely the
  attack. Over-firing is the right direction of error here.
- **`expectation`** — the claims pin's record, in one of **two disjoint forms**, which
  share no key so a consumer can never read one as the other.

  The first is present only when the run was invoked with `--expect`: the claims-pin
  adjudication `{claims, matched[, differences]}` (#31). "Make the check pass" and "delete
  the check" are the same action from where a model sits; `diff` catches the second on
  comparison, and the pin catches it with no previous artifact in hand — a fresh CI
  checkout, or an agent loop whose first run is already post-tamper. A mismatch MUST be
  `verdict: "error"` with every declared check `skipped` and the differences named — the
  question changed identity, so nothing may be said about the part — and MUST live in the
  artifact, not only on stderr, for the same reason `attribution` does. The pin covers the
  claim *set* (kind, limits, region, hole, expression, citation per id), not the count:
  swapping a strict check for a lax one under the same id, or stripping a `source`
  citation, is a named difference. Every pinned part MUST be covered by the invocation —
  a pinned part no target produced is the same failure, on stderr and in the exit code,
  since no report exists to carry it. Two scope limits, stated: the pin binds *claims*,
  not the source (identical claims pointed at a different model pass — `source_digest`
  and `diff` own source identity), and the lock is regenerable by design — the tool makes
  weakening impossible to do *silently*, while forbidding re-pin-after-weakening is the
  agent contract's job.

  The second form is `{repinned: [...]}`, present when the run was invoked with `--pin`
  over a lock that **already covered this part** and this contract's declared claims
  differ from it (#294). Same strings as the `--expect` differences and as the stderr
  confession, from one `compare()` — computed against the lock as this run **found** it.
  The confession is computed a second time at the write, against the lock as it stands
  **then**, because the guard must speak for the file it is about to overwrite while a
  report already written cannot be revised. Under a single writer those are the same
  bytes and the two wordings are identical; where the file moved under the run they
  differ, and that is deliberate rather than a drift between them (#294). It is a **record, not an adjudication**: `--pin` is the deliberate-update
  path (`AGENT-CONTRACT.md` §4), so the run proceeds to a real verdict and MAY be
  `pass`. That is why the two forms may not share `matched` — the MUST above binds a
  mismatch to `verdict: "error"`, and a permitted re-pin is exactly a mismatch that is
  not one. What the field says was compared, not what was written: the write is refused
  when a crashed target would drop a claim set from the lock (that refusal is stderr and
  exit 4, `--pin`'s counterpart to the uncovered-pin failure above), and the differences
  named here are then what the run declined to overwrite.

  Absent in **four** cases, three of which say nothing moved: a **first** pin, a part the
  lock did not cover, and a re-pin that moved nothing — an overwrite that overwrites
  nothing is not one, and reporting a new part's every claim as `added` is how the loud
  case stops being read. That the flag was passed
  at all is `invocation.argv`'s to say, not this field's, so an always-emitted empty list
  would state twice what the artifact already carries once and dilute the signal this
  field exists for.

  **The fourth case does not say that, and a reader MUST NOT take it to.** A lock that
  could not be READ — malformed, or a schema this build does not know — is still
  overwritten when nothing failed to resolve, since overwriting one is the documented way
  out of it; there is then no previous claim set to compare against, so every report in
  that run carries no `expectation` at all while the lock on disk was rewritten. It is
  the arrival where the silence bites hardest: the stderr line saying partspec cannot
  tell which claims moved is the run's only record, and a lock whose bytes will not parse
  is also a lock whose diff a reviewer cannot read. Absence of this field therefore means
  "nothing was overwritten" only for a run whose lock was readable, which
  `invocation.argv` plus that stderr line are what establish. Recording the unreadable
  arrival *in* the block would need a second shape for it, which is a schema question and
  is deliberately not answered here.
- **`invocation.timeout_s`** — the build budget that governed the run, in seconds. The CLI
  always records the fully resolved value (`--timeout`, then `PARTSPEC_TIMEOUT`, then the
  300 s default); `0` records an explicit waiver of the bound, and `null` means a library
  caller invoked `run` without choosing (the backend default still applied). A run stopped
  by its budget MUST be attributable to that budget from the artifact alone — `verdict:
  "error"` with `build_origin: "environment"`, never a failing `builds` check: a stopwatch
  disproves nothing about the part (#46).
- **`geometry.triangles`** and **`geometry.distinct_normals`** — both recorded, because
  `$fn` lives *inside* the `.scad` and is invisible to the tool while these are not.
  `distinct_normals` is the count of distinct face normals: it tracks `$fn` one-to-one (a
  cylinder at `$fn=n` yields `n+2`) and is invariant under retriangulation, making it the
  better *identity* signal. `triangles` is the better *drift explainer*, because chord error
  scales with edge length. Neither substitutes for the other. Both are mesh-tier only and
  MUST be absent on the OCCT tier.

  It is deliberately **not** a coplanar-region facet count (D16): that needs `scipy` or
  `networkx`, a large dependency for one provenance field. The two agree on convex solids
  and differ only where disjoint coplanar regions share a normal, so the field is named for
  what it measures rather than borrowing CGAL's vocabulary for a different quantity.
- **`engine.method` / `engine.param_mode` / `engine.source_rendered`** — `method` is
  always present (mirroring `adopted_via`): the callable or module `method=` invoked, or
  `null` for the default entry. Two runs of one contract can build different things, and
  a single report must say which happened. On OpenSCAD, `param_mode` states how the
  parameters reached the geometry — `"define"` (`-D`) or `"call"` — and on the call path
  `source_rendered: "derived"` records that the engine's entry was a derived scratch
  including the digested file, so `source_digest` cannot be read as naming the rendered
  input. Additive, same terms as `engine.render_backend` below.
- **`engine.render_backend`** — always present: the pinned string, or `null` when the run
  took the engine's default. `null` MUST be read against the recorded `engine.version`:
  it means "the default for that version", which on OpenSCAD is **CGAL on 2021.01 and
  Manifold on current builds** — so the null case is exactly the run whose backend a
  reader could not otherwise infer. Recorded at all because it
  **changes the artifact, not merely the speed of producing it**: measured on a community
  gridfinity bin, OpenSCAD's default Manifold backend emitted 4 non-manifold edges where
  CGAL emitted none, from identical source. Two reports that differ only here are not
  comparable on mesh validity.
- **`build_origin`** — `"environment"`, `"model"`, or `null`: whose fault a build failure
  was. `"model"` is a statement about the part (the design does not compile) and adjudicates
  as a failing `builds` check; `"environment"` is not a statement about the part at all — no
  engine on PATH, a missing wheel, an option the installed engine does not accept, a render
  that ran out of time — and MUST NOT be reported as a verdict on the design (§6.1). Null
  when the build succeeded. This is the primary routing key `docs/AGENT-CONTRACT.md` §2.3
  tells an agent to read, and it was emitted by every report since v0.4.0 while appearing in
  this document only in passing; the omission is what let two faults ship misclassified into
  the v0.7.0 audit.
- **`environment.packages`** — **every distribution installed** in the environment that ran
  the build, name → version, sorted by name, first occurrence on `sys.path` winning so the
  report cannot disagree with a hand-run `importlib.metadata.version()`. Through v0.7.4 it
  was a five-name allowlist of engine packages (`build123d`, `cadquery`, `cadquery-ocp`,
  `trimesh`, `manifold3d`), which could not see the library a contract wraps and therefore
  could not explain a number that moved when *that* was upgraded (#211). It is keyed on
  what is installed, **not** on what the process imported, and rule 2 below is why: several
  targets share one interpreter, so an import-keyed field would make a part's recorded
  environment depend on which unrelated target ran before it — measured, an OpenSCAD-tier
  part recorded 6 distributions alone and 41 in a batch behind a build123d part, from
  identical inputs on one machine. An environment is a property of the venv. Which
  distributions *a given part* loaded, and whether the bytes that ran are the ones the
  installer recorded, is answered by `part.source_closure` (§8.3), not here — with the
  same shared interpreter still in the way there: `source_closure.imports` scopes the
  question to the part but is still read from one `sys.modules`, so it over-reports in a
  batch and §8.3 rule 7 requires it to name what it cannot attribute. Moving the field did
  not remove the sharing; it made the bound statable per part.
- **`checks[].requires`** — present only on `unsupported`, naming the tier that would answer
  **for an equivalent part**. The hedge is load-bearing: porting a 16-gon bore to build123d
  does not merely enable the check, it **changes the part** (investigation 04 §4). This is
  an actionable pointer, not a promise that the answer would be the same.
- **`checks[].id`** — stable within a contract, used as the join key by `diff`. Two checks
  in one report MUST NOT share an `id`. A contract that would emit a duplicate is a
  contract error (`verdict: "error"`), not a silently deduplicated report.
- **`checks[].components`** — present on a check whose measurement is a vector **and whose
  components are adjudicated against a limit**: axis → status (e.g. `{"x": "pass", "y":
  "pass", "z": "fail"}`), so a failure names *which* component to act on instead of leaving
  the consumer to re-derive it from the vectors. This said "every check whose measurement is
  a vector" until v0.7.0, which `hole_diameter` falsifies: its measurement is the vector of
  matched diameters, adjudicated as a set against a band rather than per axis, so it carries
  a `hole` callout and no `components`. A consumer must therefore test for the key rather
  than assume a vector implies it.
  Derived from the same per-component adjudication the check status folds, never computed a
  second way. Recorded on pass too (the §7.2 principle applied to attribution); an
  unconstrained axis is **absent**, because an omitted claim has no status. The check-level
  `status` remains the worst constrained component — this field adds attribution, not a new
  verdict path. On `keep_out` / `keep_in` the two clauses appear as `region` and `shell`.
  Additive (no schema bump). Resolves Q8.
- **`checks[].region`** — present only on `keep_out` / `keep_in` checks: the declared region
  (`shape`, its dimensions, and the mandatory `shell` thickness), so the report states what
  was claimed and not just how it went. These checks carry `limit: null` — the claim is a
  paired one (empty here AND solid nearby, or the mirror) that no limit form expresses — and
  their `measurement` is the two-component vector `(region, shell)` of material volumes.
  Additive (no schema bump).
- **`checks[].hole`** — present on `hole_diameter` and `bolt_circle` checks: the declared
  callout, `{"d": ..., "count": ...}` (plus `"bcd"` for a bolt circle). The diameter band lives in the check's `limit`; the
  measurement is the vector of matched diameters (null when none matched, with the part's
  full bore inventory in `detail` on failure). Additive (no schema bump).
- **`checks[].intrusion`** — on a failing `keep_out` region clause only, and not on
  every one of those: it is omitted when the backend cannot answer and when the region
  is too small for the search to resolve (SPEC-contract §4.4), so a consumer MUST treat
  it as optional. When present it carries
  `volume_mm3`, `min_depth_mm`, `search_resolution_mm`, `detected_above_mm3`,
  `depth_limited_by_region` and `facet_floor_mm`. The depth is a
  LOWER BOUND from an erosion search that stops on a volume threshold rather than on
  emptiness, and MUST NOT be reported as an upper bound or a bracket; `facet_floor_mm`
  is a SCALE it is read against and MUST NOT be reported as a share of it, since how the
  region's faceting and the modelled feature's combine depends on how the two polygons
  are phased (SPEC-contract §4.4).
  Diagnostic rather
  than adjudicated, which is why it is a field of its own and not part of
  `measurement`: that carries one unit, and this carries mm beside mm3. Additive (no
  schema bump).
- **`checks[].direction`** — present only on `draft_angle` checks: the pull axis the draft
  was measured against, as `[x, y, z]`. Part of the claim's identity, not context — the same
  part measures differently under a different pull, so a draft claim without its axis is not
  reproducible, and `SPEC-diff.md` compares it as a claim field. Additive (no schema bump).
- **`checks[].step`** — present only on `step_roundtrip` checks: `{"schema": ...}`, the
  application protocol the writer emitted (`AP214IS` today). The check answers whether the
  part survives its own exchange format, and which format that was is part of the answer.
  Additive (no schema bump).
- **`checks[].source`** — present when any of the check's bounds was a `Referenced` value
  (`SPEC-contract.md` §10): `{field: {"standard", "subject", "field"}}`. The report states
  not just what was claimed but on whose authority; a bare-literal bound records nothing,
  which is itself the signal #50's warning channel reads. Additive (no schema bump).
- **`checks[].kind`** — an **open vocabulary**, defined in `SPEC-contract.md`. This document
  deliberately does not enumerate it: the report format must not need revising every time a
  check is added. Consumers MUST treat an unrecognized `kind` as opaque and rely on
  `status`, `measurement` and `limit`, all of which are closed.
- **`checks[].phase`** — `parameter` or `geometry` (§4). Lets a consumer explain a report
  full of `skipped` geometry checks without re-deriving the short-circuit rule.
- **`attribution`** — run-level `{"dimensional": N, "attributed": M}` over the
  `DIMENSIONAL_KINDS` (`SPEC-contract.md` §6): how many checks carry chosen numbers, and
  how many of those numbers came from somewhere (§10). `dimensional > 0 && attributed == 0`
  is the circular-contract signal, carried in the artifact because the artifact is the
  product surface — the CLI warning derives from this field, and an agent consuming the
  report over MCP would otherwise never see the disclosure. Additive (no schema bump).
- **`counts.total`** — MUST equal `len(checks)`, and the five status counts MUST sum to it.
  Redundant by construction and included anyway, because it is the cheapest signal that a
  contract lost checks between two runs.
- **`build_stderr`** — the engine's complete stderr when a build failed, `null` otherwise.
  Additive (no schema bump). `hint` is one *selected* line of engine output and selection
  can be wrong — noise filtering must never be able to lose the diagnosis, so the
  unabridged text travels with the report.
- **`error` / `hint`** — `error` carries the full traceback when `verdict == "error"`;
  `hint` carries a pattern-matched one-line repair suggestion when one is recognized.
  Consumers SHOULD surface `hint` before `error`.
- **On `verdict: "error"`, `checks` MUST still list every declared check**, each with
  `status: "skipped"`. An error report with an empty `checks` array is indistinguishable
  from `empty`, and would let a crash masquerade as an unwritten contract.
- **Unknown fields.** Consumers MUST ignore fields they do not recognize. This is the
  precondition for every deferral in this document: adding a field is a non-breaking change
  and MUST NOT bump `schema_version`; removing or re-typing one MUST.

`engine.backend` is the **measurement tier** (`mesh` | `occt`); `engine.render_backend` is
the OpenSCAD **kernel** (`Manifold` | `CGAL`). Two different things, and the shared word is
unfortunate — but `engine.tier` was tried and dropped in an early draft, and
`tests/test_report.py::test_spec_example_uses_no_deleted_fields` exists to stop it coming
back. `measure` MUST emit `backend` too; it emitted `tier` until 2026-08-07, which is the
only reason the name looked unsettled.

### 7.2 Measurements are recorded on pass, not only on failure

`checks[].measurement` MUST be populated whenever the check was evaluated, **including when
it passed.** This is non-obvious and load-bearing: it is what lets `diff` report *drift on
checks whose pass/fail state did not change* — "drift the boolean can't see." A wall
thinning from 2.9 mm to 2.1 mm against a 2.0 mm minimum is two passes and one very
important trend, and nothing else in the system can see it.

### 7.3 The `measure` payload — `measurements`, `refused`, `unavailable`

**This section describes the payload of a run that measured.** A run whose build failed,
or whose `--out` was refused, takes the failure shape Scope fixes instead — the identity
prefix, an empty `geometry`, and `error`/`hint` — and carries **none** of the three blocks
below, `measurements` included. The two shapes are told apart by `error`, which the
failure shape always carries and this one never does.

Within that payload, `measure` emits the identity prefix (Scope), then `geometry`, then
the numbers. Those arrive in up to **three** blocks, and the distinction between them is
the verb's product rather than bookkeeping. Every name the verb asks about lands in
exactly one of them, so a consumer that reads all three has accounted for the whole
vocabulary and a name missing from all three is a defect in this tool, not a silence about
the part.

**None of the three is unconditional, and a consumer MUST read all three with a default
rather than by subscript.** They are not absent under the same condition, and the
difference is worth knowing. `refused` is absent on a part that defeated nothing — the
common case — and `unavailable` on a tier that can answer everything asked, which is
**not** hypothetical: the OCCT tier's capability set covers all fourteen names the verb
asks, so a build123d or CadQuery payload carries neither key. Those two are omitted
whenever they would be empty, rather than emitted as `{}` or `[]`, for the same reason
`partial` is (§8.3), and their absence carries the same obligation on the reader: it means
"nothing to report", never "not asked". `measurements` is different — a run that measured
nothing still emits it, as `{}` — and it is absent only from the failure shape above.
Three keys, two conditions, one rule for the consumer.

A **sound** part measured **without `--out`** on a tier that answers everything therefore
has as its whole top level
`schema_version, payload, tool, part, engine, params, geometry, measurements` — the
minimal shape, stated so a consumer knows what it may see, and **not** a key set to
validate against: `refused`, `unavailable` and `artifact` each extend it, and each is
reachable on the same tier from the rules just above.

- **`measurements`** — name → the §2 measurement shape: `value` (scalar or vector),
  `unit`, `exactness` (`"exact"` | `"approximate"`), `bounds` when the backend gave an
  interval, and `axes` on a vector. The interval is the honesty: an approximate value shown
  without it reads more certain than it is, in the verb whose whole job is showing the
  numbers.
- **`refused`** — name → the reason this **part** could not be measured, in the reason's
  own words: `"volume": "volume is the integral over a closed surface; this mesh is open
  along 4 boundary edge(s)"`. The reason names the part's defect, so it is the finding and
  not an apology. **Omitted entirely when nothing was refused** — a sound part carries no
  `refused` key. A backend that *raises* instead of refusing — a non-finite value reaching
  the §2 measurement shape, which rejects one — lands here too, naming the fault rather
  than the part's defect, and it MUST cost **that one name only**: the verb continues and
  emits every other quantity, since a quantity needing nothing the part lacks is answerable
  whatever defeated its neighbour (#365).
- **`unavailable`** — the names this **tier** cannot answer for any part, so the same list
  every time that backend measures anything. Listed in the fixed order the verb asks them
  in, which is not alphabetical. **Omitted entirely when the tier can answer everything
  asked**, which is the whole OCCT tier today.

The two silences are separate because conflating them was a bug this verb had. `refused`
is a property of the part and `unavailable` a property of the tier, and an author reading
a measure dump to decide what to claim needs to know which one they are looking at: a
refusal is something to fix in the model, a tier limit is something to claim on the other
tier or not at all. Before D17 only the second kind existed and dropping the name silently
was honest; it is not honest now, since an open mesh drops `volume`, `genus` and
`center_of_mass` and a reader would conclude the part has no volume to claim.

Emission order, among those present, is `measurements`, `refused`, `unavailable`, after
`geometry`; `artifact` follows them when `--out` was passed, in the two states Scope fixes. The name vocabulary
is the backend capability set, deliberately **not** enumerated here — it is a superset of
the check vocabulary (`SPEC-contract.md` §7: `is_valid` and `topology_counts` are worth
seeing while deciding what to claim and are not check kinds), and the report format must
not need revising each time a backend can answer one more thing.

A `measure` payload carries **no `verdict`, no `counts` and no `checks`**, and MUST NOT be
read as a report: it states numbers and makes no claim about the part. That absence is
what `partspec diff` tests to refuse one (`SPEC-diff.md` §2), since a comparison of two
documents that declare nothing would answer `identical` for two files that never made a
claim; `payload: "measure"` (§7.1) now says the same thing by name.

---

## 8. Determinism

The report is compared across runs, so instability is a correctness bug.

1. **Ordering.** `checks` MUST appear in contract declaration order. Object keys MUST be
   emitted in the order given in §7. Any derived collection MUST be sorted by a stated key.
2. **Volatile data is quarantined — by field, not by block.** Only
   `environment.duration_ms` and `environment.platform` may vary
   between two runs of identical inputs on the same machine, and only those MUST be excluded
   from comparison.

   **`environment.packages` MUST NOT be excluded.** It is exactly what distinguishes "a
   trimesh upgrade moved this number" from "the design changed" — the drift §7.2 exists to
   surface. A comparator that quarantines the whole block loses the ability to explain its
   own findings. The corollary binds the producer as well as the comparator: a field that
   is mandatory to compare MUST be stable across two runs of identical inputs, which is
   why `packages` enumerates the installed distributions rather than the imported ones.

   Nothing outside `environment` and `invocation` may carry a timestamp, duration,
   hostname, or PID. **Exception:** `error` and `build_stderr` carry engine and
   interpreter output verbatim — tracebacks with absolute paths, cache statistics,
   rendering times. That is intentional and outside rules 2 and 4: a diagnosis with the
   volatile parts stripped is materially harder to act on, and both fields are `null`
   except on a failure, where run-to-run comparability is not the concern.
3. **Floats.** Emitted at full `repr` precision. Byte-stability across OCCT or engine
   versions is **not** guaranteed and MUST NOT be assumed — rebuilding identical geometry
   through a different transform-composition order perturbs coordinates at ~1e-13. Any
   comparator MUST therefore apply a numeric tolerance (`1e-6` recommended) rather than
   exact equality, or it will report noise and bury signal.
4. **Paths** are project-relative, POSIX-separated.

### 8.3 `part.source_closure` — identifying the whole input

`source_digest` covers the entry file. On real OpenSCAD libraries that is a small fraction
of the build: the gridfinity bin in the dogfood corpus is one file of **sixteen**. Edit a
helper three levels down and the part changes while `source_digest` does not, so two
genuinely different builds compare as identical inputs. This is F13's failure class — a
library moving underneath a source that did not change — arriving in the provenance layer,
and a comparator would have inherited it silently.

An OpenSCAD report therefore carries:

```json
"source_closure": {
  "digest": "sha256:…",
  "files": 16,
  "unresolved": ["some/missing.scad"],
  "reads_external_data": true,
  "partial": true,
  "imports": {},
  "engine_inputs": { "state": "complete", "data_files": ["heights.dat"] },
  "unseen": ["external_data_reads", "unresolved_includes"]
}
```

- **`digest`** is taken over the member **content hashes, sorted** — never over paths. A
  comparator's whole purpose is comparing a CI run against a laptop run, and a
  path-sensitive digest would differ on every one of them. The trade is deliberate: it
  identifies the set of file *contents*, not the layout, so relocating a file without
  editing it does not move the digest.
- **`unresolved`** lists `include`/`use` targets not found on any search path. Resolution
  follows OpenSCAD's rule — relative to the file containing the statement, then
  `OPENSCADPATH`, then the library directories.
- **`reads_external_data`** is `true` when any file-reading construct appears anywhere in the
  closure: `import()` and its deprecated `import_stl()`/`import_dxf()`/`import_off()`
  spellings, `surface()`, the `dxf_*` extrudes and dimension functions, and
  `linear_extrude()`/`rotate_extrude()` given a `file=`. Those name STL/DXF/DAT files that
  genuinely are build inputs, and their paths may be computed at render time, so no static
  reader can resolve them — which is why `engine_inputs` below asks the engine instead.
  The flag stays `true` either way: it says the model *reads* external data, which remains
  a fact about the source whether or not this run learned what was read.
  **The deprecated spellings count**: the version floor executes
  them, so a reader that recognised only the modern two reported a complete closure for a
  build that reads a file.
- **`partial`** is `true` whenever the closure left anything unseen — `partial ==
  bool(unseen)`, and that identity is the whole rule. It is **not** "either of the previous
  two is non-empty", which is what this said until the engine could report its own inputs:
  a model that reads external data under a `complete` `engine_inputs` has
  `reads_external_data: true` and no gap, so it is not `partial`. Read the equivalence off
  `unseen`, never off the fields above it.
  **Absent means complete: read it with `.get`.** A clean OpenSCAD closure carries no
  `partial` key at all, and the field is never emitted as `false` anywhere in the tool, so
  absence is the only encoding of "complete" — and that encoding occurs on one tier only,
  the Python tier being unconditionally partial (`native_reads`, below). An agent that
  learned the field on a build123d part, where it is always present and always `true`, is
  exactly the reader who writes the bracket-index read and gets a `KeyError` on the first
  OpenSCAD part it meets.
  It is stated positively so a consumer cannot read the *absence* of those fields as a
  completeness guarantee the closure never made. **A comparator MUST treat a `partial`
  closure as inconclusive evidence of sameness**, exactly as `unsupported` is treated for a
  check: matching digests then mean "nothing we looked at changed", not "nothing changed".
- **`imports`** is `{}` on this tier and MUST be present anyway. The render happens in a
  subprocess and loads no Python, and *that is a finding*: an absent `imports` means the
  question was never asked, which is what every report written before 0.7.5 says.
- **`engine_inputs`** is what the ENGINE said it read, from `openscad -d`, and it is the
  one source of truth in this block that is not a static read of the source. It is present
  only on a report whose run actually rendered. Three states, and **`absent` MUST NOT be
  read as `complete`**:
  - `complete` — the engine exited zero and wrote a dependency file: its resolved input
    set, in full.
  - `partial` — the engine failed but wrote one: what it had opened before it stopped,
    which is a floor and not the set.
  - `absent` — no dependency file. Nothing may be concluded; in particular this is *not*
    "the render read nothing", which is what an empty `data_files` under either other
    state would mean. **Which failures land here is engine-version-dependent** — 2021.01
    writes nothing for a syntax error and the 2026.08.01 snapshot writes one anyway — so a
    consumer MUST NOT infer a cause from the state. What holds on every engine is that a
    failed render is never `complete`.

  `data_files` names the entries the engine resolved that the static walk could not see —
  the `import()`/`surface()` targets — and `missing` names entries the engine listed that
  do not exist on disk, which is a build input the model asked for and did not get.
  **A named data file is hashed into `digest`**; naming one without hashing it would claim
  a coverage the digest does not have.

  This does **not** supersede the static walk, and a reader must not treat it as a
  replacement. Measured on 2021.01: a **missing** `include` is not listed in the dependency
  file at all — it records what was successfully opened, never what was requested — so
  `unresolved` remains the only evidence that an include was asked for. The two are
  complementary, and `include_closure` additionally answers before any render happens.
- **`unseen`** names the gaps; see below. `external_data_reads` is omitted **only** when
  `engine_inputs.state` is `complete`: the gap is then closed by evidence rather than
  assumed away, and a `partial` or `absent` state leaves it exactly where an engine that
  never answered would.

A **Python** report carries a closure too, of a different shape:

```json
"source_closure": {
  "digest": "sha256:…",
  "files": 2,
  "scope": "model_directory",
  "partial": true,
  "imports": {
    "cadquery":     { "identity": "metadata", "version": "2.8.0", "digest": "sha256:…" },
    "cqgridfinity": { "identity": "content",  "version": null, "digest": "sha256:…", "files": 16 }
  },
  "preloaded": [],
  "reached": ["cadquery", "cqgridfinity"],
  "declared": ["cadquery-ocp"],
  "unseen": ["native_reads"]
}
```

- **`scope`** names the boundary of `digest`/`files`: local modules imported from the
  model's own directory. That is not arbitrary. `engines/pycad.py` puts exactly that
  directory on `sys.path` before exec'ing the model, so a model can import helpers beside
  it — which makes those helpers build inputs by design.
- Membership is read from `sys.modules` **after the build**, so it records what was
  imported rather than what appears importable, and catches helpers imported lazily inside
  the factory.
- The contract file is excluded. `contract_digest` already covers it, and a *source* closure
  that moved whenever a claim changed would answer a different question than its name.
- **`preloaded`** names the entries of `imports` this run cannot attribute to itself,
  because a batch shares one interpreter; rule 7 below states the bound in full.
- **`reached`** names the entries of `imports` this target's **own modules provably reach**,
  walked over the live object graph from the model and the helpers beside it. It is the part
  of `preloaded`'s inability that can actually be settled: a distribution the model's graph
  reaches is this target's build input **whoever imported it first**, which is the attribution
  a snapshot-and-delta cannot give and the direction §8.3 refuses to under-report in.
  **It proves reach and never disproves it.** A `from mylib import WALL_THICKNESS` binds a
  float, a float has no `__module__`, and the edge therefore does not exist in the object
  graph — while `mylib` is a real build input supplying a dimension. So **absence from
  `reached` means not-proven-reached, never proven-unreached**, and a consumer MUST treat it
  as the weaker claim: it may lift an entry out of `unattributable`, and MUST NOT use it to
  dismiss one. A producer that cannot walk the graph omits the field, which every reader
  already handles as "the question was not asked".
- **`declared`** lists the distributions the contract named with `build_input`
  (`SPEC-contract.md` §10.2), as the author spelled them. Each such entry is byte-hashed
  over **every file its RECORD declares** — not over its package tree, because a
  distribution's unit can be wider than its package directory (`cadquery_ocp.libs/` beside
  `OCP/`) and only the RECORD knows the association. The entry reads
  `identity: "content"` with `declared: true` and a `files` count.
  This is the author's opt-out from rule 5 below, and it is **opt-in because the cost is
  lopsided**: measured, `build123d` 1.4 ms over 41 declared files against `cadquery-ocp`
  228.5 ms over 396.
  **A declaration that changed nothing is still recorded** — an entry no RECORD claims is
  already `content`, and it gets `declared: true` and no other difference — so a reader can
  tell coverage that was *asked for* from coverage that happened to be free. Adding a
  declaration therefore moves `identity` and `digest` for a previously-`metadata` entry, and
  a comparator reports that as `changed`, which it is: the report describes the same library
  under a stronger claim. For an entry that was already `content` nothing moves, and the
  contract's own change is carried by `contract_digest`.
  **A declared distribution that was never imported is a run-level `error`**, adjudicated
  after the build; see §10.2 rule 2 for why silence is the wrong answer there.
- **`partial` is unconditional here**, because `native_reads` always is. Python can import
  from anywhere on `sys.path`, read data files at run time and load C extensions, none of
  which this sees — measured: an audit hook watching `OCP.StlAPI_Reader().Read()` load an
  STL saw zero `open` events.

#### `imports` — the distributions the model loaded

A contract that wraps a third-party library identifies none of the code that built the
part: `scope` is the model's directory, and the library is not in it. The fleet-01 study
that produced #190 recorded `files: 1` for a bin whose sixteen files of `cqgridfinity`
did all the work, so every `diff` over it was permanently indeterminate and both agents
wrote their own tree hash outside the tool.

Each entry is keyed by **distribution** name where `identity` is `metadata`, and by
**top-level module** name where it is `content` or `unidentified`, because a distribution
is what carries a version and an unowned source tree has none.

The map covers what was imported **after partspec was**, which excludes the tool itself
and the interpreter's own scenery — `partspec` is already `tool.version` and would
otherwise report an input moving on every part whenever the tool was edited, and
`_virtualenv` records which program created the venv rather than anything a model reads.
Everything a contract loads happens after that point, engines included: they import their
CAD kernel lazily at build time.

| `identity` | when | `digest` covers | `version` |
| --- | --- | --- | --- |
| `metadata` | every loaded file of that distribution is declared in its installer RECORD | the RECORD's own declared hashes, `path,hash` rows sorted by path | the distribution's |
| `content` | a loaded file no RECORD declares — an editable install, a `sys.path` checkout, a package no installer wrote | the bytes of the package tree the import was loaded from, sorted content hashes as `digest` above, with `files` | `null` |
| `unidentified` | `__file__ is None` and nothing under the name is identifiable | `null` | `null` |

Rules a producer MUST follow:

1. **`metadata` identity requires positive proof of ownership.** A distribution appears
   with `identity: "metadata"` only because a file it declares was actually loaded.
   Without that check the tier is vacuous where it matters most: an editable install's
   RECORD lists only a `.pth` and a finder shim, so a material source edit left both the
   version and the RECORD digest unmoved while the bytes that ran had changed.
   Correspondingly, **a row that is not the distribution's code MUST NOT be proof**:
   setuptools writes `__editable___<name>_finder.py` into site-packages and lists it, and
   accepting it hands a `metadata` entry to a library nothing imported, with a digest over
   a shim that embeds the checkout's absolute path.
2. **Rows beginning `../` MUST be excluded from a `metadata` digest**, with `__editable__`
   rows, `.pyc` rows and the `dist-info` metadata. Console-script shebangs embed the
   venv's absolute path: unfiltered, numpy 2.5.2's digest differed across all five fleet
   venvs and agreed across none. The rule is by location, not by kind, and so also drops
   stable rows outside site-packages such as installed man pages — a reproducible digest
   over slightly less is worth more than a complete one that differs per machine.
3. **A `metadata` digest MUST cover every row of the distribution, not the imported
   package's directory.** `cadquery_ocp.libs/` holds 69 vendored OCCT shared objects,
   105 MB, beside the `OCP/` package rather than inside it, and `sys.modules` never names
   it; the RECORD does, so a digest scoped to the distribution catches it and one scoped
   to the imported directory silently does not.
4. **An import that cannot be identified MUST still be listed.** A map that omits it reads
   as an import that never happened.
5. `identity: "metadata"` is the installer's word, taken deliberately (§7.1: digests are
   comparison-based tamper *evidence*, not tamper-proofing). Ownership is decided by path,
   so **a post-install edit to a file the RECORD declares does not move a `metadata`
   digest** and does not demote the entry to `content`. Detecting it would mean hashing
   every loaded file to compare against its declared hash, which is the cost this tier
   exists to avoid. What rule 1 bounds is vacuity, not tampering.
   **`build_input` is the author's opt-out from this rule**, per distribution and by name
   (`SPEC-contract.md` §10.2): a declared entry is byte-hashed over the RECORD's own rows,
   so the edit this rule describes does move its digest. It is opt-in, and a contract that
   declares nothing behaves exactly as this rule says. Absence of a declaration MUST NOT
   produce a stronger claim.
6. A `content` digest covers **the package tree the import was loaded from**. Where a
   distribution's unit is wider than that tree — vendored shared objects in a sibling
   directory, as in rule 3 — nothing outside RECORD can discover the association, so a
   `content` entry MUST NOT be read as covering it. **A `declared` entry is the exception
   and is why it digests RECORD rows rather than a tree**: where the RECORD exists it names
   the sibling, so declaring a distribution covers exactly what its installer wrote. This is a stated bound rather than a
   gap token because a Python-tier closure is `partial` unconditionally (`native_reads`),
   so no reader may treat any of it as complete coverage.
7. **`imports` is read from a process and describes a part, so it over-reports in a
   batch, and `preloaded` MUST name what it cannot attribute.** Several targets share one
   interpreter (§8 rule 2 is the same fact one block up), and `sys.modules` does not
   record which target imported what: measured, one build123d cube recorded 38 imports
   alone and 44 behind a CadQuery target, `cadquery` among them. The map stays wide,
   because a producer that reported only the delta since the target began would drop a
   library the second target genuinely uses whenever the first loaded it first — the
   under-reporting direction this whole section refuses. So the bound is stated instead:
   `preloaded` lists, sorted, the entries of `imports` that were already in `sys.modules`
   when this target's contract was resolved, and an entry named there is one **this report
   cannot claim as its own**. It is `[]` for a target that ran first or alone, and it is a
   **Python-tier field**: an OpenSCAD closure carries `imports: {}` and no `preloaded` at
   all, because the render is a subprocess that imports nothing and there is nothing to
   attribute. Its absence therefore dates no report — `imports` is the field that does
   that (above), and a consumer reading the same absence rule into this one would misdate
   every 0.7.5 OpenSCAD report as pre-0.7.5. A consumer MUST NOT report
   an entry it names as a build input that appeared; the honest reading is that this
   comparison cannot attribute it (SPEC-diff.md §2 rule 3). It is not an `unseen` token:
   the coverage is not incomplete, the attribution is, and routing it through the gap
   vocabulary would make every multi-target Python comparison indeterminate — the exact
   outcome #190 removed.

   **`reached` settles the part of that inability the object graph can settle**, and a
   consumer MAY use it to lift an entry out of the unattributable set. Walked from the
   model's own modules over the live object graph, so a distribution it names is this
   target's build input whoever loaded it first — measured on a build123d target running
   behind a CadQuery one, where all 44 entries are `preloaded` and the 38 `reached` do not
   include `cadquery`. **It is one-directional**: absence is not-proven-reached and never
   proven-unreached, because an edge can fail to exist at all — `from mylib import
   WALL_THICKNESS` binds a float, which has no `__module__`. So a consumer MUST NOT use
   `reached` to dismiss an entry, only to attribute one, and an entry that is in neither
   `reached` nor an earlier target's `preloaded` is governed by this rule exactly as before.

#### `unseen` — the gaps, by name

A closed vocabulary. `partial` is derived from it: `partial == bool(unseen)`.

| token | tier | class | meaning |
| --- | --- | --- | --- |
| `native_reads` | Python | irreducible | a C extension may read files Python cannot observe |
| `unidentified_imports` | Python | bounded | an import with no `__file__`, listed in `imports` |
| `external_data_reads` | OpenSCAD | bounded | `import()`/`surface()`/`import_stl()`/… in the closure, and `engine_inputs` did not report `complete` |
| `unresolved_includes` | OpenSCAD | bounded | named `include`/`use` targets not found |

A **bounded** gap is one a run could in principle close; an **irreducible** one is a
property of the tier and is present in every report that tier will ever write.

**A consumer that meets a token it does not recognise MUST treat it as a bounded gap.**
Closed vocabularies leak, and the failure must be closed: an older reader of a newer
report goes inconclusive rather than silently ignoring a gap it does not understand.

**The same rule covers the field's absence, wherever the field could have carried an
answer.** A closure missing `unseen` **or** `imports` was written before the question was
asked, and MUST NOT be read as an answer to it — so a consumer synthesises a bounded gap
for it. The qualifier is load-bearing and is not a softening: on the Python tier the
absence is exactly the pre-0.7.5 state this section describes, where `partial` was
unconditional and every comparison was already inconclusive, so the rule reproduces what
that reader already did. A pre-0.7.5 **OpenSCAD** closure is the case the qualifier
excludes: a complete one carries no `partial` key at all and compares conclusively today,
and synthesising a gap for it would raise a first alarm, on upgrade, about a question that
tier never had — the render happens in a subprocess and loads no Python. Such a closure is
classified from the legacy fields it does carry (`unresolved`, `reads_external_data`,
`partial`), which name the same gaps this vocabulary does. This is why `imports` is `{}`
and not absent on that tier from 0.7.5 on: an empty map is the answer "nothing was
imported", and only absence means "never asked".

> **Reversed 2026-08-05.** This section previously specified that the Python engines emit no
> closure at all, on the grounds that partial coverage would "assert coverage that does not
> exist, which is worse than the silence." That was wrong, and the mistake is worth keeping
> visible: silence here is not the absence of a claim, because `source_digest` remains in the
> report asserting that **one file** identifies the build. The choice was never between a
> claim and no claim — it was between a flagged partial claim and an unflagged overclaim.
> `partial` is the mechanism this very section defines for known-incomplete coverage, so a
> comparator treats matching Python digests as inconclusive rather than proven.

---

### 8.4 `renders` — images a run produced

View name → image path, relative to the report's own directory (rule 4). Present **only**
when the invocation actually produced images (`check --render`); when nothing was rendered
the key MUST be absent — never an empty object, and never an empty-string path, which reads
as a file that exists. A requested render that fails exits `4` and leaves the key absent:
the report speaks for the part, the exit code for the run. (The `render` verb's own
sibling payload is the opposite by design — its failure artifact carries `renders: {}`
beside an `error`, per the Scope above — because there the empty map sits next to the
error that explains it, while in a report it would sit next to a verdict it has nothing
to do with.) That payload MUST also carry `origin` — `"model"`, `"environment"`, or
`null` — on the same §6.1 grounds every other engine-side failure does: a degenerate solid
the kernel cannot mesh and an OCCT library that will not load are different facts, and a
consumer that cannot tell them apart will read the second as a statement about the part
(#191). `null` is the third of those grounds and carries the same weight as the other two:
§6.1 records that a build which succeeded and lost geometry is attributable to neither, so
a payload refusing for that reason MUST spell it `null` rather than default to `"model"`.
Additive; `SCHEMA_VERSION` does not move.

`render_bbox` MUST sit beside `renders` whenever they are present (#21): `{min, max}`
in mm, the framing bbox. Two runs whose sizes differ uniformly render byte-identical
pixels — the camera scales with the part — so this block is the only scale witness the
images leave behind.

When the images came from the OCCT tier's rasterizer (#18), `render_tessellation` —
`{tolerance_mm, triangles}` — MUST sit beside `renders`: under D15 the tessellation is
what was shown. It is absent for OpenSCAD renders, where the engine draws its own
geometry, and never present without `renders`.

The images are evidence, not judgement — no verdict, status, or measurement may be derived
from them (D18). §9's rule stands: paths only, never inline image data.

## 9. Non-goals for v1

Stated so they are decisions rather than omissions:

- **No assemblies.** Per D11, v0 is parts only. The schema anticipates them only in that
  `checks[].id` is a free-form string, so dotted paths (`turret.rotor.arm`) will fit without
  a schema change.
- **No diff output.** `diff` consumes two reports and emits its own artifact; that is a
  separate spec.
- **No embedded renders.** Images are files on disk referenced by path, never inline.
- **No remediation advice** beyond `hint`. The report states what is; it does not plan.
- **No severity or weighting.** Every check is load-bearing or it should not be declared.
  Introducing `warning` would immediately recreate the silence-as-success problem this
  document exists to prevent.

---

## 10. The `approximate` machinery, and how it stopped being dormant

Through v0 this section said the opposite of what it says now, and the correction is worth
keeping rather than overwriting: **as v0 was scoped, no check in it could produce
`approximate`.** The v0 set was parameter predicates plus `builds`, `envelope`,
`watertight`, `solid_count` and `genus`; under §2.3's measurand every one of those is exact
on a polyhedron, and an exported OpenSCAD part *is* a polyhedron. So `bounds`, §3.1's
interval adjudication and the `approximate` status were correct, load-bearing for the
design D10 commits to, and unexercised. The two consequences were stated openly: the
dogfood run would not test the machinery, and its first real exercise would be its first
bug report.

**That debt is paid.** `min_wall` (#140, `SPEC-contract.md` §4.11) is a genuine interval
measurement on the OCCT tier — a guaranteed `[lo, hi]` from kernel-exact face-pair minima
and certified diametric spans — and a limit inside that interval adjudicates `approximate`
and exits 2. It is routine, not exotic: a U-channel bounded by a nearby gap, a stepped
slab bounded by its ledge, a tilted pocket. The first exercise was a fixture, not a bug
report.

Two notes for a reader arriving from an older copy of this document:

1. **`approximate` is live and an agent must act on it.** `AGENT-CONTRACT.md` §2.2 used to
   call it dormant and instruct an agent to escalate it as a tool bug; correct output was
   being described as a defect. Both are fixed.
2. **The mesh tier still cannot produce it.** `min_wall` is `unsupported` there for want of
   an honest lower bound (§3.2), so a mesh-only run remains exact-or-refused. That is a
   property of the tier, not of the machinery.

---

## 11. Open questions

- **Q1** — Should `skipped` and `unsupported` share exit code `2`? They differ in kind:
  `skipped` is usually the operator's doing, `unsupported` is the tool's limitation.
  Splitting them costs an exit code and may buy clarity in CI.
- **Q2** — Is `empty` (exit `3`) worth a distinct code, or should it be `fail`? Argument for
  `fail`: a contract with no checks is a defect, not a partial result. Argument for `3`: it
  is not a *geometry* failure and conflating them muddies CI triage.
- **Q3** — Should `bounds` be mandatory on *every* measurement, with exact measurements
  carrying a degenerate `[v, v]`? Uniform shape for consumers, at the cost of noise.
- **Q6** — Where does an error bound come from, for the first check that needs one? Two
  things are now known. **The one rigorously derivable bound is float32 quantization from
  binary STL** — `±v·2⁻²⁴` per coordinate, propagating trivially to a bounding box; real,
  computable, defensible, and currently unused. And **sampled quantities admit no honest
  two-sided bound at all** (§3.2), so they are `unsupported`, not `approximate`. What
  remains open is the middle ground: a defensible interval for mesh *volume* and *area*.
  Not a v0 blocker (§10).
*Resolved in draft 2:* Q5 (`--allow-incomplete` withheld from v0, §6.2).
*Resolved in draft 3:* Q4 (a facet-resolution signal added alongside `triangles`, §7.1;
implemented as `distinct_normals` per D16).
*Resolved in draft 4:* Q7 — parameter predicates are **not** measurements. A `requires`
check carries `expr` and `operands` instead of `measurement`/`limit`; `bool` is gone from
the unit table. See `SPEC-contract.md` §5.
*Resolved post-v0.1:* Q8 — per-component statuses are recorded in `checks[].components`
(§7.1), not left to `detail`: prose is for humans, and the failing axis is data an agent
acts on.

[survey-capability]: https://github.com/heibench/partspec/blob/main/notes/survey/04-kernel-capability.md
