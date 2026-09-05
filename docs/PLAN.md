# PLAN — `partspec` v0

**Date:** 2026-08-02 · **frozen 2026-08-05**
**Status:** **HISTORICAL.** This describes how v0 was built and what was known while
building it. It is not a description of the current feature set — §5's "deliberately not
in v0" list has since shipped almost entirely, and §7 is the only part still load-bearing.
For what exists now, read `README.md` and `SPEC-contract.md` §4; for what is still
withheld, `POST-V0.md`.
**Reads with:** `DECISIONS.md` (D1–D19), `SPEC-report.md`, `SPEC-contract.md`,
`SPEC-backend.md`, `POST-V0.md`.
**Shape:** survey → build → dogfood, following the `scadman` precedent (D1). This working
directory is the survey and is **throwaway**; only its distilled outputs get promoted.

---

## 0. What v0 is, in one sentence

> A CLI that builds a part from an OpenSCAD, build123d or CadQuery source, checks it against
> engineering intent declared in a Python contract, and emits a JSON report whose statuses
> never let silence read as success.

**Success condition** (unchanged since the first pass): enough evidence to decide whether to
retire *"No unit tests for geometry; rely on visual / diff review"* from the CAD domain
profile in `~/.claude/skills/scaffold-new-project/domain-profiles.md`. That is the claim
this project exists to test, and it is falsifiable.

**Answered 2026-08-05 — see §7.**

**v0 is done when** three real parts across two engines are under contract, the differential
test passes, and `results.md` exists. Not when the feature list is complete.

---

## 1. Repo shape

Three repos, mirroring `scadman-survey` → `scadman` → `scadman-dogfood`:

| repo | status | notes |
|---|---|---|
| `working-b123d-agentic` | this one | survey. Throwaway. Promote `DECISIONS.md` + the specs, archive the rest. |
| `partspec` | to create | the tool. Apache-2.0 (D9 precedent; also what cad-khana is, which matters for absorbed code). |
| `partspec-dogfood` | to create | **not a git repo** — a scratch workspace, per `scadman-dogfood`. |

Scaffold `partspec` from the `dev-toolbox` `python-uv` template: `uv`, `justfile`
(`setup`/`fmt`/`fmt-check`/`lint`/`typecheck`/`check`/`test`), `AGENTS.md` with a
**Constraints** section, pre-commit with gitleaks, and CI behind the unified `ok` gate.
Python ≥3.12, ruff, pyright.

---

## 2. Phases

Each phase ends in something runnable. No phase is "write the rest of the code."

### P0 — Skeleton and the seam ✅ *done 2026-08-02*

Scaffold; then define, in this order, **before any geometry**:

1. `partspec/report.py` — the report dataclasses and the JSON writer, straight from
   `SPEC-report.md`. Atomic write, `error` placeholder written *before* the engine runs.
2. `partspec/status.py` — the five statuses, verdict precedence, exit-code mapping,
   `ε(limit) = 1e-6 + 1e-7·|limit|`, and interval adjudication.
3. `partspec/backend.py` — the `GeometryBackend` Protocol and value types. No
   implementations.

**Exit criterion:** `partspec check` on a hand-written fake backend emits a schema-valid
report and the right exit code for each of the five statuses. **A conformance test asserts
the schema example in `SPEC-report.md` §7 parses and satisfies its own MUSTs** — that
example is the contract, so it should be executable, not decorative.

Ship the status machinery before any geometry deliberately: it is the thesis, it is where
the design risk lives, and it is testable without a CAD kernel.

### P1 — Mesh backend + OpenSCAD ✅ *done 2026-08-03*

`openscad -D … --export-format binstl` → `trimesh.load_mesh()` → measure. Never parse
`--summary` (D13). Implements: `bbox`, `volume`, `area`, `center_of_mass`, `watertight`,
`solid_count`, `genus`, `triangles`, `facets`. (`facets` was renamed `distinct_normals`
before it shipped — D16.) Returns `Unsupported` for topology counts and
self-intersection.

Mesh before OCCT because it is the cheaper install, the faster loop, and the engine with the
largest existing corpus (~30 personal libraries).

**Exit criterion:** the backend measures `bayonet_lock.scad` and returns values verified
against independently-known geometry (analytic where the shape allows, cross-checked against
a second measurement path otherwise), with every quantity correctly flagged `exact` and
topology correctly refused.

> **Corrected 2026-08-03.** This criterion originally read *"`bayonet-lock-scad` under
> contract, with its README's documented rules as `requires` checks"* — which needs the
> contract API from **P2**. A phase whose exit criterion depends on the next phase is not a
> phase. P1 is now verifiable at the backend's own API, which is where it belongs; the
> combined run moves to P2.

### P2 — Contract API ✅ *done 2026-08-03*

`Part`, the source constructors, the closed v0 `kind` vocabulary, target resolution
(`<module>[:<factory>]` with the error message as discovery mechanism), and `requires`
expression evaluation with operand capture.

**Exit criterion:** the `SPEC-contract.md` §1 example runs verbatim, and
`bayonet-lock-scad` passes `just check` with its README's documented rules as `requires`
checks (inherited from P1).

### P3 — `measure` ✅ *shipped early with P2*

The adoption path. Dumps every honestly-available quantity with `exactness`, emits nothing
that would be `unsupported`, produces no verdict.

Early, not late: it is how contracts get *written*, so every subsequent phase is easier with
it. It is also the guard against the temptation to auto-generate checks
(`SPEC-contract.md` §6).

### P4 — OCCT backend ✅ *done 2026-08-03*

build123d, plus CadQuery via `bd.Solid(cq_shape.wrapped)` at the front door. Pin one OCP
explicitly and commit the lockfile; add the CI assertion that exactly one `OCP/` provider is
installed, because that failure is silent.

**Exit criterion (revised, met):** a real **community** model under contract on each Python
engine. `cq-gridfinity`'s `GridfinityBox(2,1,3)` (CadQuery, MIT) checked against the
*Gridfinity standard's own numbers* — 42 mm pitch less 0.5 mm clearance — and a build123d
pillow block whose `genus 5` counts one bearing bore plus four bolt holes.

> **Revised 2026-08-03.** The original criterion named `parametric-sensor-manifold`. That is
> just the build123d template rather than a real part, so it proves nothing; community models
> replace it. Two hazards found on the way, both recorded in dogfood F8: community build123d
> libraries are pinned to the build123d of their writing (`gridfinity_build123d` does not
> import on 0.11.1), and community models are *scripts*, not parameterised callables, so a
> real contract usually ships a small explicit adapter.

### P5 — The differential test ✅ *done 2026-08-03*

The substitutability proof, and the phase that makes engine-neutrality a property rather
than an assertion. One contract, the same specified part in two engines, reports compared
field-by-field excluding `engine` and `geometry`.

Subject: **gridfinity**, which exists in all three engines under MIT
(`kennetek/gridfinity-rebuilt-openscad`, `Ruudjhuu/gridfinity_build123d`,
`michaelgale/cq-gridfinity`). Any divergence is a tool bug, not a design difference.

⚠️ Expect this to fail first time in an interesting way. **It did, three times over**, and
each was a different kind of finding — see dogfood F10–F12:

1. **A real defect.** OpenSCAD's *default* Manifold backend emitted 4 non-manifold edges
   where CGAL emitted none, from identical source — while reporting `manifold`,
   `Status: NoError`, `"simple": true` and exit 0. The payoff F1 said was missing.
2. **A wrong claim of mine.** The shared set asserted `genus(0)`; kennetek's bin enables
   Gridfinity Refined base holes by default, so a 2x1 bin is genus 8. Assert what the
   *specification* fixes, not what the first implementation you looked at does.
3. **Legitimate design difference.** Envelope Z differs (24.5479 vs 24.8) — both checks
   PASS and the measurements still differ, which is precisely what recording measurements
   on pass exists to surface.

X and Y agree exactly at the standard's `42n - 0.5` across both languages. That is the
substitutability claim holding on real third-party code.

### P6 — Dogfood ✅ *done 2026-08-05; first batch 2026-08-03*

Three or more real parts, at least two engines. Then `results.md` in the `scadman-dogfood`
house style: numbered findings, root cause, before/after regression table, and a
**validation-payoff proof** — a case where a check predicted a real failure.

**This is the deliverable.** P0–P5 are setup.

**First batch, 2026-08-03.** 11 targets across three engines via `./run-batch.sh`; 0
unexpected failures, 4 expected ones each with a recorded cause.

**Self-review, 2026-08-05.** 15 targets, 0 unexpected failures, 7 expected. `results.md`
carries 17 numbered findings.

The success condition — *"enough evidence to decide whether to retire 'No unit tests for
geometry'"* — now has two payoffs behind it, both on third-party code, both silent in the
engine:

- **F10:** OpenSCAD's default Manifold backend emits 4 non-manifold edges on a 2,212-star
  gridfinity library while reporting `manifold`, `Status: NoError` and `"simple": true`.
- **F13:** a gear library from a corpus with **zero asserts in 18 files** silently loses its
  teeth on modern OpenSCAD, because `assign()` was removed from the language. The same
  contract passes on 2021.01 and fails on 2026.08.01 — one variable, controlled.

Neither is a rule an author forgot to write down. Both are parts that are quietly wrong and
look fine, which is the case visual review is worst at.

**F14 is a third kind, and it is about the tool.** A step-back review found partspec itself
committing failure mode two: on the F10 bin, a contract that declared `volume`,
`solid_count` and `genus` but not `watertight` scored four green checks and exit 0. Two root
causes — a dependency's `Error.NotManifold` status read straight past, and absolute
measurements sourced from a library that rebuilds its input (25.31 mm³ of drift on a *clean*
part). Fixed under D17.

It belongs in this phase's record for a reason that bears on §0's success condition: **169
tests passed throughout**, every one of them measuring a mesh that was already sound, and
neither cause was findable by reading the code. It took a deliberately broken input and an
independently computed reference. That is this project's own argument about CAD, holding
when turned on the project.

**F15 supplies the before/after table this phase was still missing**, and from a *design*
change rather than a version change. One parameter on a NEMA 17 mount plate — `l_slot`
6 → 8 mm, a plausible edit to gain belt adjustment — breaks the mounting holes out through
the plate edge. Four of the five checks report no difference: it still builds, is still
watertight, is still one solid, is still exactly 42×42×4. Only `genus` moves, 5 → 1, because
a hole that reaches the boundary is a notch. The plate cannot hold a motor and does not look
wrong. Pushed further the same parameter walks the part through two more silent states — 2
non-manifold edges at 14 mm, six disconnected solids at 16 mm — every one of them exiting 0.

**F16 is the cheapest kind of payoff and the hardest to argue with.** `bearing(608)` measures
22.5 mm where ISO 15 says 22.0, with no comment saying why, in a file whose width dimension
is exactly nominal. F15's library has the same shape of defect — a header comment claiming a
22 mm collar over code declaring 28 — which makes it a property of the corpus rather than one
author's slip.

**Exit criterion met.** Fifteen targets, three engines, five libraries, three payoffs on
third-party code and one on the tool. §7 answers the success condition.

---

## 3. Ordering rationale

Two choices worth defending, since both invert the obvious:

**Report before geometry.** The report is the contract (D5); building it last means
retrofitting honesty onto a tool that already works, which is when honesty loses. It is also
the only part that can be fully tested without a CAD kernel.

**Mesh before BREP**, despite BREP being the richer tier — cheaper install, faster loop,
bigger corpus, and it forces the `unsupported` path to be exercised from day one rather than
bolted on when OpenSCAD support arrives.

---

## 4. Risks, with the honest ones first

| risk | why it matters | mitigation |
|---|---|---|
| **The `approximate` machinery is dead code in v0** (no longer — see the mitigation) | No v0 check can produce it (`SPEC-report.md` §10). Its first real exercise will be its first bug report. | Accept. Unit-test the adjudicator directly with synthetic intervals so it is at least *tested*, even if unexercised. **Discharged 2026-08-09**: `min_wall` (#140) exercises it with real geometry, and the first exercise was a fixture rather than a bug report. |
| **The parts have nothing interesting to say** | If every contract passes first try, the project has proved nothing. | Deliberately contract a part **known to have a defect**, and confirm the report catches it. A green dogfood run is a failed experiment. |
| ⚠️ **This risk fired.** `bayonet-lock-scad` carries 12 of its own `assert()`s, so OpenSCAD already rejects every invalid parameterisation and partspec's `requires` checks are redundant there (dogfood F1). | The first dogfood subject was the best-defended library in the corpus — the worst choice for demonstrating the tool. | **P6 must start from a library with no asserts** (`NEMA17.scad`, `bearings.scad`, `hotends.scad`). Until then the core claim is untested on a subject that needs it. |
| Silent OCP clobbering | `cadquery-ocp` and `-novtk` both own `OCP/`; pip does not notice | Pin + lock + CI assertion (P4) |
| Contract weakening undetected | Known gap: needs `diff`, out of v0 scope | Recorded in `SPEC-report.md` §7.1. **Closed**: `diff` (#83) names removed and claim-changed checks, and the claims pin `--expect` (#31) refuses before the engine starts |
| Scope creep into assemblies | The absorbed design's best ideas are assembly-level | `POST-V0.md` exists to hold them |

### Deferred setup

- **Branch protection was OFF, deliberately** (decided 2026-08-03) — requiring PRs and the
  `ok` check on a solo repo cost velocity during bootstrap, and the gate already reported
  correctly. The condition was "before v0.1.0 is tagged", and it was met: `main` now
  requires the `ok` check and linear history, blocks force-pushes and deletions, and
  requires conversation resolution. **Done 2026-08-05; this entry is history.**

---

## 5. Deliberately not in v0

`diff` · MCP server · renders · assemblies · `clearance`/`interference` · BREP-tier feature
checks (holes, fillets, bolt circles) · `min_wall` · `--allow-incomplete` · a benchmark
suite · PartCAD integration · a viewer.

Each has a recorded reason. None is "we ran out of time."

**As of 2026-08-09, all but four have shipped**: `diff` (#83), the MCP server (#63/#66),
renders (#18/#19/#21), the BREP-tier feature checks (epic #6) and `min_wall` (#140).
`--allow-incomplete` was refused outright rather than deferred (`SPEC-report.md` §6.2).
Still withheld and still reasoned: assemblies with `clearance`/`interference`
(`POST-V0.md` §1), the benchmark suite, PartCAD integration, and a viewer.

---

## 6. What promotes out of this directory

To `partspec/docs/`: `DECISIONS.md` (renumbered from D1), the three specs, `POST-V0.md`.
Archived here: the investigations, `SYNTHESIS.md`, `TRIAGE.md`, [`notes/survey/DIRECTION.md`][survey-direction] — the
reasoning trail, per D7 of the scadman precedent (*"only its stable outputs are promoted"*).

---

## 7. The success condition, answered

**Verdict: retire the line — but not by replacing it with "write unit tests for geometry."**

### What the evidence says

Five findings across the dogfood corpus where a declared check caught something that had
already survived the alternative the profile recommends:

| | what was wrong | what visual / diff review sees |
|---|---|---|
| **F10** | OpenSCAD's default backend emitted 4 non-manifold edges on a 2,212-star library | a correct-looking bin; the engine reports `manifold`, `Status: NoError`, `"simple": true`, exit 0 |
| **F13** | a gear silently lost its teeth on a newer OpenSCAD — 35% smaller in every planar dimension | **nothing in a diff**: the source is byte-identical and correct. Visible on re-render, if anyone re-renders that part |
| **F14** | partspec itself scored four green checks on a part it knew was non-manifold | nothing — 169 tests passed throughout |
| **F15** | `l_slot` 6 → 8 mm broke the mount holes out through the plate edge | a plate that still renders, is still watertight, is still one solid, is still 42×42×4. Open-ended slots look deliberate |
| **F16** | a part named `bearing(608)` is 22.5 mm where ISO 15 says 22.0 | nothing. A ring 2% oversize is a ring |

Four of the five are invisible to both halves of the recommendation. F13 is invisible to
diff review specifically, which is the half that scales.

### The load-bearing qualification

**Every payoff came from a claim derived outside the model.** ISO 15's 22 mm, the Gridfinity
standard's `42n − 0.5`, the NEMA 17 mounting pattern, involute gear theory, a topological
invariant. Not one came from measuring the part and asserting the result.

That distinction decides what should replace the retired line. A geometry "unit test" written
the way unit tests usually get written — run the code, record what it produced, assert that
next time — would have passed on **every broken part above**, because each one is a faithful
render of its own source. `measure` exists to make writing contracts cheap and deliberately
refuses to generate checks from its own output (`SPEC-contract.md` §6); this is the evidence
for that refusal, and it is the single most transferable result here.

So the replacement is not "unit-test your geometry." It is:

> Geometry is verifiable, but only against a reference the model does not contain — a
> standard, a datasheet, a derivation, or an invariant. Visual review cannot see dimensional
> or topological divergence in a part that renders correctly, and diff review cannot see a
> part that changed without its source changing.

### Where the old line was right, and stays right

- **F1.** The first subject, `bayonet-lock-scad`, carries 12 of its own `assert()`s, so the
  engine already rejected every invalid parameterisation and the contract's `requires` checks
  were redundant. On a well-defended library the profile's advice costs nothing.
- **F12.** A claim I wrote by hand (`genus 0`) was simply wrong about the standard. Authoring
  checks has its own error rate; the tool caught this one, but only because a second
  implementation disagreed. Checks are not free and are not automatically right.
- The `approximate` machinery is unexercised by anything in the corpus, as §4 predicted.
  Some of what a checker could assert about geometry, v0 still cannot assert honestly.

### Confidence

Moderate, and bounded by the corpus. Fifteen targets, three engines, five libraries, and
F15 and F16 come from the same collection by the same curator — so the pattern they share
(an allowance baked into a constant named for a nominal dimension) is not yet established
beyond it. What is well established is the negative claim, and it is the one the profile
line turns on: **a part that renders cleanly, exits 0 and looks right is not thereby
correct**, and four of the five findings above were found no other way.

[survey-direction]: https://github.com/heibench/partspec/blob/main/notes/survey/DIRECTION.md
