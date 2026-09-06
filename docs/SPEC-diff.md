# SPEC — `partspec diff`

**Applies to:** v0.8.0 — the release this text describes. The `Status:` line records when
this document was last revised in substance; it is provenance, not currency (#300).

**Status:** draft 7 · 2026-09-02 · §4 puts `payload` in this artifact, the discriminator
#295 named and PR #342 shipped to the other five (#345); §3 compares `part.contract`'s
FACTORY where both sides name one, two targets in one module having compared `identical` at
exit 0 — the module path is recorded instead, a rename being no difference — states the
declined comparison as a gap rather than a match, and answers what a moved contract digest
inside `identical` is: correct, and until now unsaid on the summary line (#343);
draft 6 · 2026-08-24 · §3 states three rules the reasons behind draft 5 already
implied: an entry carries every delta the comparison computed whatever bucket it landed in
(#330), the comparison tolerance keys on `phase` because that is where the report records a
value's provenance (#335), and a status-change entry says when the new report does not
answer the check, the headline counting those as it counts a moved claim (#325);
draft 5 stated that being parseable is not being a report,
two `measure` payloads of a changed part having compared `identical` at exit `0` (#292),
and §3 scoped the comparison tolerance to measured values, a status change over operands
inside the adjudication epsilon having been reported with none of them (#326);
draft 4 bound the §1 headline to the claim delta a status-change entry already carried, the
console having reported a loosened limit as `1 fixed` (#293); draft 3 keyed §2 rule 3 on the
class of a **named** gap rather than on the `partial` boolean and compared the closure's
`imports` map (#190); draft 2 put `kind` and `expr` in the claim fields and stated the
digests as recorded-not-outcome-bearing
**Scope:** the semantic comparison of two reports of one part, its artifact, and its exit
codes. Written before the implementation, like the other specs.
**Normative:** MUST / SHOULD / MAY per RFC 2119.
**Backing:** `SPEC-report.md` §7.1 (the silent-weakening gap), §7.2 (measurements on pass),
§8.3 (closures, their `imports` and their named gaps); `POST-V0.md` §2; D5 (the report is the product surface).

---

## 1. What it is for

`SPEC-report.md` §7.1 names the one gap v0 shipped with: an agent that deletes a check
produces a report that is internally consistent and green. `counts.total` and
`contract_digest` were designed to make that **detectable on comparison** — this verb is the
comparison. Its second job is the §7.2 payoff: **drift the boolean cannot see.** A wall
thinning from 2.9 mm to 2.1 mm against a 2.0 minimum is two passing reports and one
important trend, recorded in `measurement` since v0 and consumed by nothing until now.

```
partspec diff <old-report.json> <new-report.json>
```

The artifact is written to **stdout** (it is the product; it pipes); a one-line courtesy
summary goes to stderr. `diff` takes no out-directory because it owns no run.

The summary's **finding** stays one line. Where a group of `environment.packages` or
`source.imports` differences could run to dozens of entries, it names at most two per group
and counts the remainder (`+7 more`); the artifact on stdout carries the complete lists. It
names them on **every** outcome, `identical` included, because a build input that moved
under an unchanged part is exactly the case an unqualified "no semantic differences" would
misreport as nothing having happened. A distribution the `inputs` clause reports as
**moved** is not reported as moved again by the `packages` clause — every imported
distribution is also an installed one, so a library bump would otherwise be named twice on
one line — and that is the only suppression: matching names across *different* groups drops
real facts, since an import that appeared while its installed version moved is two
findings, not one. **An edited or renamed contract module is named there too**, on the same
grounds and with the same qualification: it is a build input that moved, it is the one input
the closure excludes by design, and its digest is module-scoped, so the clause says both that
it moved and that a move is not by itself a difference (§3). **A comparison this verb
declined is named there as well** — where the two `part.contract` values differ and a side
names no factory, the line says which target ran was not compared, because §2's opening
makes silence the one thing "no differences found" may not rest on.

Below that line, and on every outcome, the summary states the **coverage** the finding
rests on: what was covered, and every gap §2 rule 3 named that the headline has not already
stated. The irreducible ones are what replaces the exit code such a gap used to produce, so
they are not suppressible; the bounded ones appear here on the `different` path, where the
headline says nothing about them and "1 regressed" alone invites the reading that the named
regression is the whole story.

Owning no run, `diff` also keeps no history: both inputs are artifacts the caller already
has, and `check` does not supply the earlier one. `check` writes to one deterministic
destination, `<contract dir>/outputs/<slug>/report.json` or `<--out DIR>/report.json`, and
**overwrites it every run**, so the second run of a loop destroys the only baseline the
first produced. A baseline therefore has to be copied or committed before re-running
(`cp o/report.json baseline.json`), and the copy has to be taken before the run that might
change something. Left where `check` put it a report is overwritten and then untracked:
`outputs/` is gitignored at every depth in this repository and in the layout the exemplars
use, so the default disposition of a baseline is *deleted, then not in the history either*.
`examples/spacer/README.md` is the worked copy; `vdiff` needs two `render.json` and takes
the same step. Closing this in tooling — an `--out` that refuses to clobber, or one
accepting a run label — is a real option and is deliberately NOT built: the missing thing
was the statement, and a flag would leave every existing invocation exactly as silent about
it. It matters here rather than in `check`'s own documentation because §2 makes "no
differences found" a positive claim, and a baseline that was overwritten defeats that claim
in the same way an unidentified input does — by never reaching the comparison at all.

## 2. Outcomes and exit codes

Silence must never read as "no difference". "No differences found" is a **positive claim**
that requires comparable, fully-identified inputs — not a fallthrough.

| exit | `outcome` | meaning |
|---|---|---|
| `0` | `identical` | compared conclusively; no semantic difference |
| `1` | `different` | compared; at least one semantic difference found |
| `2` | `indeterminate` | the comparison could not be made conclusively |
| `64` | — | unusable input: unreadable file, unknown `schema_version` (§7.1 requires rejection, not best-effort parsing), a report violating its own `counts.total` invariant, a report carrying two checks under one `id` (SPEC-report.md §7.1 makes uniqueness a MUST NOT, and the comparison joins on it), a payload that is not a report at all — one carrying no `verdict` **or** no `counts` (a null counts as absent), since `measure` and `render` share the report's `schema_version` and identity prefix by design (SPEC-report.md's Scope names them) and so parse cleanly while declaring nothing for a comparison to be about — or otherwise malformed, or two reports that do not describe the same part. A forgotten argument is also `64` — argparse's default usage exit is `2`, which would read as `indeterminate` |

Rules:

1. Two reports with different `part.id` MUST be refused with exit `64`: `diff` compares two
   runs of one part, and comparing strangers is a usage error, not a finding.
2. A report whose `verdict` is `"error"` compares nothing — its checks are all `skipped` and
   its run did not complete. Either input erroring MUST make the outcome `indeterminate`.
3. **The gap-class rule** (`SPEC-report.md` §8.3). The comparison covers the closure
   `digest` **and** the `imports` map, entry by entry, and every gap the two closures name
   in `unseen` is classified:

   - `native_reads` is **irreducible** — a property of the tier, present in every Python
     report that will ever be written.
   - every other token is **bounded**, **including one this reader does not recognise**.
     Failing closed is a MUST there (§8.3): a closed vocabulary must be safe to extend.

   Then: a **bounded** gap on either side, or a closure absent from either input, MUST make
   the outcome `indeterminate` when no differences were found — matching digests there mean
   "nothing we looked at changed", not "nothing changed", and claiming `identical` is the
   silence-as-success mistake at the provenance layer. Otherwise any difference in the
   digest or the `imports` map is `closure: "changed"` and none is `"same"`.

   An **irreducible** gap MUST NOT make the outcome `indeterminate`, and MUST be printed on
   every outcome, in every mode. Through v0.7.4 the rule keyed on the `partial` boolean,
   which the Python tier sets unconditionally, so `diff` was permanently indeterminate for
   every contract wrapping an installed library: fleet-01 measured 3/3 CadQuery replicates
   indeterminate against 0/3 OpenSCAD ones on the same command and version, the only
   variable being that OpenSCAD libraries are source on disk and Python ones are installed
   distributions (#190). A signal constant across every possible input cannot discriminate
   between two of them, and all three CadQuery agents wrote shell to suppress the exit 2
   rather than go and look — a universally suppressed verdict protects less than a
   universally printed caveat. The caveat is therefore permanent output, not an option.

   **An import either side could not attribute to its own target MUST NOT be reported as
   one that appeared or disappeared.** `SPEC-report.md` §8.3 rule 7: `imports` is read
   from one `sys.modules` shared by every target of a batch, and `preloaded` names what
   that costs. An entry of `added` or `removed` that either side listed there is reported
   as **unattributable** — named on the summary line, counted apart in `covered`, and
   listed in `source.imports.unattributable`. The wording elsewhere is untouched: an
   appearance the `preloaded` sets do not explain is exactly what this verb has always
   said it was.

   **Except where a side proved it reached the entry itself.** `reached` (§8.3 rule 7)
   names what a target's own module graph provably reaches, and a distribution it names is
   that target's build input whoever imported it first — so such an entry is attributable
   and is NOT listed as unattributable. This subtracts from the unattributable set and
   never adds to it: `reached` proves reach and cannot disprove it, so an entry absent from
   it is governed exactly as before. A producer that omits `reached` — every report before
   the field existed, and every OpenSCAD one — is read as proving nothing, which reproduces
   what this verb already did.

   **It still makes the closure `changed`, and `source.closure` MUST NOT be read as a
   claim about the part's inputs.** That field says whether the two reports *recorded*
   different closures, and two `imports` maps that differ differ — the batch case,
   44 entries against 38 with nothing in the model moved, is `changed` on those grounds.
   Whose import it was is the separate question `unattributable` answers, and a reader
   keying on `source.closure` alone MUST consult it. Suppressing the entry here made the
   artifact assert `closure: "same"` while carrying the difference in `imports.added` in
   the same object; keeping what the comparison saw is the same rule that gave
   `closure_digest_changed` its own field. It costs no verdict: `different` is computed
   from the checks alone and only `inconclusive` is outcome-bearing, so a `changed`
   closure falls through to `identical` at exit `0`. This qualifies the
   *claim*, not the verdict: it moves no outcome and no exit code, and it is deliberately
   NOT a gap token, because a bounded gap here would make every multi-target Python
   comparison indeterminate and rebuild what rule 3 exists to remove. Measured before the
   qualification: one build123d cube diffed against itself, run behind a CadQuery target
   in a batch, reported `inputs appeared: cadquery 2.8.0, casadi 3.7.2, +4 more` at exit
   `0` — six build inputs positively claimed to have arrived, and nothing had.

   **The message MUST state the inability and MUST NOT state a cause.** `preloaded`
   evidences that this comparison cannot attribute the entry; it evidences nothing about
   why the entry is on one side, and "the difference is its position in a batch" is the
   same overclaim aimed the other way. Measured: a follower whose model began importing a
   shared module its leader's contract also imports — batch position 2 of 2 in **both**
   runs — is a genuine new build input that lands in this set, and calling it a batch
   artefact reports a real change as a non-event. `SPEC-report.md` §8.3 rule 7 already
   words it correctly: *the honest reading is that this comparison cannot attribute it.*

   Only `added` and `removed` can be affected; a `changed` entry is present on both sides
   with something moved between them, which is a fact about the distribution whoever
   loaded it.

   Found differences are real regardless of any gap, so this rule only ever blocks the
   `identical` claim, never the `different` one. A `changed` closure is likewise never a
   difference on its own (§3): the library moved and no declared claim moved with it is
   `identical` at exit `0`, with the moved distribution named on the summary line, which is
   what OpenSCAD already got for a changed `.scad` closure with no moved check.

   **A gap discards observed movement from the verdict, and from nothing else.** The
   `indeterminate` reason therefore takes one of two shapes, and the distinction is
   normative because only one of them is true at a time:

   - **nothing was observed to move** — the digests match and no `imports` entry differs.
     The reason MUST carry the sentence *"nothing this diff can see changed, which is not
     the same claim as nothing changed"*, verbatim.
   - **something was observed to move** — a moved closure digest, or a moved, appeared or
     disappeared import. The reason MUST name what moved and MUST NOT carry that sentence,
     because it would assert nothing was seen to change while the same line names something
     that changed. Through v0.7.4 this case was unreachable: `digest != digest` returned
     `changed` before the partiality check, so the sentence was only ever emitted with
     matching digests. Removing that short-circuit is correct — `changed` was never
     outcome-bearing, so the exit `0` it produced was an unearned `identical` — and it is
     what makes the second shape necessary.

   **Malformation fails closed, and separately from age.** Three states are distinguished:
   a field **absent** is "written before the question was asked" and is the only state that
   may be reported as `imports_not_recorded`; a field **present in the wrong shape** is
   `malformed_closure`, on either tier; and `partial` **disagreeing with `bool(unseen)`**
   violates §8.3's own invariant and is `unnamed_partial`. Collapsing any two of these
   opened a hole that failed open in review: a non-list `unseen` blocked on the Python tier
   and exited `0` on OpenSCAD, and `partial: true` beside `unseen: []` — the malformation
   closest to the real vocabulary — exited `0` where v0.7.4 exited `2`.

   **Migration.** A closure carrying no `unseen` predates 0.7.5. Where the field could have
   carried an answer — a Python closure, `scope: "model_directory"` — `diff` synthesises the
   bounded gap `imports_not_recorded`, which reproduces that report's existing exit 2 and
   names re-recording the baseline as the fix. **Naming it is a MUST, in the artifact and
   in the output**: a bounded gap that has a remedy carries it on the `indeterminate`
   entry as `remedy`, printed as its own line directly under the headline, because the
   `reason` ends in a sentence this rule fixes verbatim and a step spliced into that
   sentence would read as its consequence. Through v0.7.4 this comparison stated the cause
   and stopped — on the one exit `2` every upgrading user meets — while this document, the
   changelog, the code's own comment and its test all said the remedy was named. A gap with
   no remedy MUST NOT be given one: `unidentified_imports` is a property of how a package is
   distributed, and inventing a step sends a reader to do work that cannot help. A pre-0.7.5 **OpenSCAD** closure is
   classified from the legacy fields instead (`unresolved` → `unresolved_includes`,
   `reads_external_data` → `external_data_reads`, and a bare `partial: true` →
   `unnamed_partial`), because a complete one has no gap and flipping it to exit 2 on
   upgrade would be a false alarm about a question that tier never had. Those three plus
   `malformed_closure` are synthesised by this verb and are not part of the producer
   vocabulary §8.3 defines.
4. **Check ids MUST be unique within each input**, refused with exit `64` (#148). The
   comparator joins on `id`, so a report carrying two checks under one id does not merely
   lose a check — the second silently replaces the first and two unrelated claims are
   compared as one. Measured before the guard existed: a `genus` check aliased onto a
   `param_range` check reported `limit_changed` from `{"kind": "param_range"}` to
   `{"kind": "genus"}` at exit `1`, with the displaced claim absent from the output
   entirely. `counts.total` does not catch it — such a report carries exactly the number
   of checks it claims. Two neighbouring refusals share this precondition, because the join
   must be keyable and must key each check to itself: a check carrying no `id` is a missing
   REQUIRED field and is refused as that rather than as a repeated `null`, and an `id` that
   is not a string is refused as a type error — §7.1 types it as a string, and comparing
   ids any other way lets `1` and `1.0` pass a uniqueness check and then collapse onto one
   another in the join. `Part._add` refuses both the clash and the non-string id at
   authoring time, so `partspec` emits neither; this rule binds `diff` because the report
   schema is the product surface (D5) and the comparator must not assume it produced its
   own input.

## 3. What is compared

Checks join on `id` (`SPEC-report.md` §7.1 fixes `id` as the join key). Per check:

- **`removed` / `added`** — present in only one report. A removed check is the
  silent-weakening signal and is always a difference, whatever the statuses were.
- **`regressed` / `fixed`** — status changed, ordered by the severity that `verdict_of`
  already uses (`fail` > `unsupported` > `approximate` > `skipped` > `pass`). Any status
  change is a difference. A status-change entry MUST also carry the claim and value deltas
  when those moved: loosening a limit until a failing check passes is the flagship
  weakening move, and an entry saying only "fixed" would report the attack as an
  improvement. The **§1 headline** MUST state the same fact, since the reason is a
  statement about readers and the headline is the surface a human reads: a `regressed` or
  `fixed` count says how many of its entries also moved the claim. The count itself stays
  the bucket's true total, and each qualifier is an independent tally over it rather than a
  partition of it — with the second qualifier below now also in force, the two count
  overlapping sets and may sum past the bucket, and two different situations can render
  alike. Each number is individually true and the bucket total is the answer to "how many?",
  which is what this line is for. Neither `limit_changed` (where the claim moving is the
  bucket) nor `drifted` (which cannot carry one) takes the qualifier.
  This rule reaches a *moved claim* and no further, and a second fact needs saying
  alongside it.

  **A status-change entry MUST say when the new report does not answer the check, and the
  headline MUST count those the way it counts a moved claim** (#325). `pass` and `fail` are
  the two statuses meaning the check was evaluated to a conclusion, which the vocabulary
  states of itself rather than needing a list of the rest: `approximate` is "indeterminate
  … the tool does not know", `unsupported` is "cannot evaluate this check … at all",
  `skipped` is "not evaluated". The severity order ranks all three below `fail` — correctly,
  for a verdict — so a check that is not answered on the new side lands in `fixed` and is
  filed as one that was answered better. Measured: an `envelope` failing at `max=(40,30,4)`,
  then a `requires` precondition breaking so the geometry phase never runs, produced
  `{"change": "fixed", "status": {"old": "fail", "new": "skipped"}}` under a headline
  reading `2 regressed; 1 fixed`. That check did not get better. It stopped being evaluated.

  **The record keys on the new status alone.** Whether this report answers the check is a
  fact about this report; where it came from is already in `status`. Keying on the
  transition is how two drafts of #325 got the bound wrong, each by enumerating pairs — the
  first omitting `approximate`, the second admitting only transitions out of `fail`. Two
  consequences follow and neither is an exception: `unsupported` → `skipped`, answered on
  neither side, is recorded, because the headline calls it `fixed` just the same; and
  `pass` → `skipped`, which is bucketed `regressed`, is recorded too, because the fact is
  true of it and a rule firing on one bucket only would be the enumeration again. Both sides
  are carried, so a reader can tell a check that stopped being answered from one that never
  was without re-deriving the vocabulary.

  **The field rides a status-change entry and only those**, present there exactly when the
  new side is unanswered. It exists to correct a bucket that names a *direction*, and only
  `regressed` and `fixed` do; on a `limit_changed` or `drifted` entry `status` is the single
  unchanged value a reader can already read, and nothing is being misstated for the field to
  answer. Stated because the scoping is not implied by the rest: measured over a grid of
  **135 check variants per side — 5 statuses × 3 claims × 3 measurement values × 3 operand
  sets — diffed against each other, 135² = 18,225 ordered pairs**, 2,106 entries hold their
  status at an unanswered one and none carries the field, so an unscoped reading of this
  sentence would make every one of them a violation. The dimensions are the three fields
  this comparison *compares*, plus `status`; `phase` is held fixed and is deliberately not
  among them, since it is read to pick a tolerance and is never itself a difference. A
  reconstruction that makes it a fourth dimension reaches 18,225 by a different route and
  answers 1,944.

  **An additive field, not a fifth `change` value.** §4's compatibility rule covers
  *fields* — additive ones are non-breaking and consumers MUST ignore what they do not
  recognise — and says nothing about enum values, so a fifth `change` would break every
  consumer that switches on the four. Nor is a console-only qualifier enough: it would
  leave the artifact still calling the entry `fixed`, which is the complaint. This is a
  second qualifier rather than a widening of the first, because such an entry carries no
  `claim` for the first to fire on and the two answer different questions; where both
  apply, the headline states both.

  `_SEVERITY` is untouched. Its ordering is right for `verdict_of` — a run with a skipped
  check is not worse than one with a failing check, and the exit code must not say it is —
  and the question here was only whether this comparison may reuse that ordering to name a
  direction of change without saying which kind of change it was.

- **`drifted`** — status unchanged, but a recorded value moved beyond tolerance:
  `measurement.value` (per component for vectors), or `operands` for a `requires` check
  (`SPEC-contract.md` §5 records them for exactly this).
- **`limit_changed`** — status unchanged but the *claim* moved: `kind`, `expr`, `limit`,
  `region`, `hole`, `source` or `direction` differ. (The name is historical — it covers every field
  that makes a check the claim it is, which the code names `diff.CLAIM_FIELDS` and a test
  holds in step with this list.) `source` is the quiet half of the weakening move: same
  number, citation stripped, authority now the author's say-so. `kind` and `expr` are the loud half
  and were both missing until the v0.7.0 sweep — swapping `genus` for `cavities` under one
  id turns "no through-holes" into "one sealed void", and loosening `wall >= 2.0` to
  `wall >= 0.2` rewrites a predicate outright; each read as `identical`, exit 0. Every
  other key a check can carry is listed in `diff.NON_CLAIM_FIELDS` with the reason it is
  not a claim, and a test requires every emitted field to appear in one list or the other.
  This is a contract edit visible between runs — the raw material of weakening
  detection (#31 owns adjudicating *within* a run; `diff` only reports the change, both
  sides shown, and takes no view on direction).

**What an entry carries is not decided by the bucket it lands in.** The bucket names the
most significant thing that changed — a status change outranks a moved claim, which outranks
a moved value — and every delta this comparison computed then rides the entry, whatever
bucket that was. The reason is the one already given above for the status-change case, which
is a statement about what a reader is told rather than about statuses: an entry saying only
`limit_changed` tells a reader that the bound moved and the part did not. Measured: a `min`
loosened 2.0 → 1.0 while the wall it bounds thinned 2.9 → 2.1 — both sides passing, so no
status changed — reported the contract edit and **discarded** the drift it was covering. Not
omitted for brevity: computed, and thrown away. That is §1's second job (`SPEC-report.md`
§7.2) dropped on the one entry where the two facts explain each other, since a bound loosened
over a measurement moving toward it is a different event from either alone. The same chain
lost a `requires` check's `operands` whenever a `measurement.value` moved beside them (#330).

Three deltas are computed and any of them may ride any entry: `claim`, `value` and
`operands`. One structural consequence, which is not an exception: a `drifted` entry never
carries a `claim`, because a moved claim is what would have made it `limit_changed`. No other
recorded field is compared — `intrusion`, `components` and `measurement.unit` are not — so
this rule reaches exactly what the comparison already sees, and a field added later stays
outside it until it is compared.

**Tolerance.** A **measured** value compares under the same `epsilon(reference)` as
adjudication (`SPEC-report.md` §3.3), with the old value as reference: rebuilding identical
geometry through a different transform order perturbs coordinates at ~1e-13, and exact
float equality would bury signal under noise. Non-numeric values compare exactly.

**`operands` compare exactly too, and the reason scopes the tolerance rather than
excepting them from it.** The epsilon is sized for what a *measurement* survives — a binary
STL round-trip through float32 — and an operand survives nothing: it is a declared contract
parameter, read before any build and bit-reproducible across two runs of one contract, and
the predicate over it is adjudicated **exactly**, with no epsilon anywhere. A measurement
tolerance applied there is a dead band never narrower than seven orders of magnitude, and
unbounded above, in which the predicate flips and the comparison reports the flip carrying
none of the numbers that caused it. Measured against the ~1e-13 the epsilon is justified
by: `1e-06` at the floor (7.0 orders), `3.6e-06` at 26 mm (7.6), `1.01e-04` at 1000 mm
(9.0) — `epsilon` is minimised at zero, so seven is the floor and no operand magnitude
falls below it. And the flip: `bore_d + 2 * wall <= plate_y` goes true → false between
`bore_d = 26.0` and `26.000001`, inside `epsilon(26.0)`. The general rule this states, for
a field added later: a comparison tolerance belongs to the *provenance* of the value, not
to its type.

**The key is `phase`, because that is where the report records the provenance.**
`SPEC-report.md` types `checks[].phase` as `parameter` or `geometry`, and it is REQUIRED,
so every check states which side of the build its value came from. A parameter-phase check
reads the declared parameters before any engine runs — the two kinds that are
parameter-phase, `requires` and `param_range`, both take their numbers straight from the
contract's own inputs — and a geometry-phase value is measured off an exported artifact. A
parameter-phase `measurement.value` therefore compares **exactly**, on the same grounds as
`operands` (#335).

**`exactness` cannot be that key, and reaching for it would break the tier it looks like it
describes.** `exact` distinguishes a point value from a bounded interval — `bounds` is
required iff not `exact` — and says nothing about reproducibility. Measured on the mesh
tier: `cube([120.3, 80.7, 40.1])` reports `exactness: "exact"` beside
`[120.30000305175781, 80.69999694824219, 40.099998474121094]`, ±3.052e-06 of float32
quantisation, which `epsilon(120.3) = 1.303e-05` absorbs. `SPEC-backend.md` §5.2 permits
collapsing that quantisation *because* the comparison epsilon is wider than it, so a
comparison keyed on `exactness` would withdraw the tolerance that permission rests on and
report a rebuild of identical geometry as drift.

**This corrects the bound rather than extending past it.** The justification given above is
a conjunction — parameter provenance **and** exact adjudication — and `param_range`
satisfies only the first: its value is `params[expr]`, but it is adjudicated against a
limit under `epsilon(lo)`. The conjunction was the wrong bound, because the two tolerances
answer different questions. An **adjudication** tolerance decides a verdict and must
forgive what the pipeline could have perturbed. A **comparison** tolerance suppresses
noise, and a number read from the contract's declared parameters has none to suppress —
while it does have something to hide. A sub-epsilon parameter move that changed no status
is exactly the drift §1 exists to report: two passing reports and one trend the boolean
cannot see. Measured before the fix: `wall` moving `1.999999 → 1.999998` against
`min=2.0` flips `pass → fail` and was reported as `{id, kind, change, status}` with no
value at all.

**Where the two sides disagree, or say nothing.** A pair with `parameter` on either side
compares exactly: that direction can only report more differences, never fewer, and §2's
rule is that "no differences found" is the positive claim. A report recording no `phase`
at all gets the measurement tolerance: a producer that did not record the provenance is
read as having proven nothing about it, and a value this comparison cannot place is
treated as the kind that carries noise. No report partspec has ever written is in that
state — `phase` is REQUIRED, has been emitted unconditionally since the scaffolding commit,
and `schema_version` has never left 1 — so this governs a hand-written or third-party
document, which §2 rule 4's principle already covers: the comparator does not get to assume
it produced its own input.

Also compared, at the top level, and **outcome-bearing**: `verdict` and `counts.total` (a
shrink is named, not implied).

**`part.contract` is compared too. What is outcome-bearing is the FACTORY, and only where
both sides name one** (#343). It is the one field that separates two targets in one module:
`same.py:imperial` and `same.py:metric` return parts with the same `id`, and the contract
digest is module-scoped, so the two `part` blocks were byte-identical until `SPEC-report.md`
§7.1 put the symbol in this field. This comparison joins on `part.id` and read the field for
nothing, so those two — two different targets, two genuine reports — compared `identical` at
exit `0`. A difference is now `contract.target_changed`, named first on the §1 headline
because a check count under it describes a comparison between two different questions.

**The module path is recorded and never outcome-bearing**, as `contract.module_changed`.
Keying the outcome on the whole `<module>:<factory>` string makes a *rename* a difference:
measured on two byte-identical contract files, `single.py:spacer` against
`renamed.py:spacer` — equal digests, equal claims, equal measurements — reported `different`
at exit `1`, which is the same mistake this section already refuses for the closure digest,
whose whole point is that it identifies file *contents* and not layout. The summary names
the move, on the same terms as the digests above.

**Where one side names no factory, the comparison is a stated gap and MUST say so.** A
single-factory module resolved without a name being typed before `target.py` resolved it
always, so `spec.py` and `spec.py:spacer` may be two spellings of one run; an unsuffixed
side cannot say which target it was, so no change may be claimed from it in either
direction. Declining is right, and declining *silently* is not: §2's opening makes "no
differences found" a positive claim requiring comparable inputs rather than a fallthrough.
The pair is recorded as `contract.target_incomparable` and named on the summary line on
every outcome.

**It does not reach the outcome, and §2 rule 3 is not the authority for that.** That rule
classifies the gaps a closure names in `source_closure.unseen`; it governs that vocabulary
and no other, and borrowing its taxonomy here would misfile this gap rather than justify it.
This gap is not constant across every possible input — it fires wherever one side records no
factory, which is a shape this release still writes: a pre-resolution placeholder (`SPEC-report.md` §5 rule 2)
echoes the argument as typed, and a library caller may invoke `run()` naming none. It is
therefore that rule's own description of a **bounded** gap, and a bounded gap MUST make the
outcome `indeterminate`.

The reason this one does not is its own, and it is an argument about what the pair can prove.
An unsuffixed value written by the CLI **for a target that resolved** — §7.1's qualifier, and
it carries the same weight here — is evidence that the module declared **exactly one**
factory when that report was written, since a module declaring several refuses to resolve
without a name. So where the module path and the contract digest also match, the two sides
ran that one factory and the pair is one run spelled two ways: nothing to report.

The qualifier is load-bearing, because the refusal that supports the argument is also what
produces its counterexample. `partspec check multi.py` on a two-factory module writes a
placeholder — `{"id": "unresolved", "contract": "multi.py"}`, no digest, `verdict: "error"` —
and against `multi.py:nosuch` the module path matches and `digest_changed` is `false`, so the
antecedent holds while the consequent fails twice over: the module declares two factories and
neither side ran any. Nothing is claimed of that pair, and it is not this gap that protects
it — §2 rule 2 makes either side's `error` verdict `indeterminate` before this gap is
consulted at all. Measured: exit `2`.

Two residues remain for the resolved reports the argument does cover: a factory renamed
between the runs, which moves the digest and is reported on the same line; and a library
caller invoking `run()` with a factory it did not record, which nothing else in either
artifact can recover — measured, a `run(factory=None)` report against a
`partspec check multi.py:a` one compares `identical` at exit `0` under the caveat, both
written by this build. The caveat is what carries them, and it is why the pair is named on
every outcome rather than dropped.

The default `--out` directory does not move with any of this: `Target.slug` keys on the
factory the *invocation* named, and `partspec check spec.py` still writes `outputs/spec`,
never `outputs/spec-spacer`.

**Recorded but never outcome-bearing**: `contract_digest`, `source_digest`, the closure
digest and the closure's `imports` map. All four appear in the artifact — as
`contract.digest_changed`, `source.digest_changed`, `source.closure_digest_changed` and
`source.imports` — so a reader can see the inputs moved, and none of them can make an
outcome `different` on its own. The closure digest gets a field of its own rather than
riding `source.closure`, because a bounded gap collapses that field to `inconclusive` and
would otherwise take the only record of closure movement with it. The
contract digest is module-scoped and over-fires deliberately (`SPEC-report.md` §7.1) — an
unrelated docstring edit moves it — and a comment added to a `.scad` is not a semantic
difference of the part. A verb that reported `different` on either would be piped through
`|| true` inside a week, and what this comparison actually covers *is* the contract's
observable content: every check id, every field in `CLAIM_FIELDS`, every status and every
measurement. The closure is the exception that proves the rule: neither its digest nor a
moved `imports` entry can make an outcome `different`, but under §2 rule 3 an absent
closure or a bounded gap does block `identical`, because there the question is whether the
inputs were fully identified at all. Holding the line at "a moved library is not by itself
a difference of the part" is what keeps arm A and arm B one tool: OpenSCAD has always got
exit `0` for a changed `.scad` closure under unmoved checks, and the summary line naming
the distribution that moved is what carries that fact to the reader (#190).

**`contract.digest_changed: true` inside an `identical` outcome is correct, and MUST stay
reachable** (#343). The digest covers the whole module whatever `part.contract` spells, so
an edit that provably cannot reach this part moves it: measured, two reports of one part
from a module whose *other* factory gained a comment line differ in `contract_digest` and
in nothing else this comparison sees — same target, same claims, same statuses, same
measurements, same source. Reporting `different` there would answer a question about part A
with a fact about part B, and a verb that did it would be piped through `|| true` within a
week. What was wrong was not the outcome but the **silence**: §1 requires a moved build
input to be named on every outcome, and the contract file is the one input the closure
deliberately excludes (`SPEC-report.md` §8.3 — `contract_digest` already covers it), so an
edited `.scad` was reported on the summary line and an edited contract was not. The summary
now names it on every outcome, and says in the same clause that it is module-scoped and not
by itself a difference. The finding that *was* missing from `identical` is the one above:
which target was invoked.

Alongside them, the environment facts that *explain* differences without being differences
of the part — `tool_version`, `engine.version`, `engine.render_backend` and
`environment.packages` — reported only when they changed (`SPEC-report.md` §8's principle:
a dependency upgrade moving a number is a different explanation than the design changing).

**`environment.packages` is compared in three groups, and the split is normative.**
`changed` names a distribution whose version moved: a build input changed, and it is the
thing that explains a moved measurement. `added` and `removed` name distributions installed
on one side only, which is most often two machines resolving different transitive
dependency sets — CI against a laptop — and explains nothing about the part on its own.
Reporting both under one heading would leave the reader to separate them by hand.
`SPEC-report.md` §8 rule 2 says in bold that this field MUST NOT be excluded from
comparison; through v0.7.4 this comparator excluded it entirely (#211).

**The first comparison against a pre-v0.7.5 baseline MUST NOT report the widening as
installations.** The old field held at most five engine names, so every other installed
distribution is `added` against it. Nothing was installed; the recorded surface widened,
and the summary says that in those words with its remedy — re-record the baseline, the
same one-time step an upgrade already asks for. The names are listed in
`environment.packages.first_recorded`, and they stay in `added`, which is what that group
means. The split is by name against the old five: `trimesh` absent from a pre-0.7.5 report
genuinely was not installed, so it is an appearance and is reported as one on the same
line. Through v0.7.4 the whole group printed as `packages appeared: PyJWT 2.13.0, PyYAML
6.0.3, +107 more` — 109 installations reported, none of which happened — while this
paragraph already said what had actually occurred. An old report is dated by its closure
carrying no `imports` (`SPEC-report.md` §8.3), the same evidence rule 3 above reads, and
never by parsing `tool.version`.

When a side carries no usable `packages` map the artifact says so — `environment.packages`
becomes `{ "uncomparable": "…" }` — rather than omitting the key. An omission is
indistinguishable from "no dependency moved", which is a claim the comparison did not make.
It does not change the outcome: an old report that predates the field still diffs.

## 4. The artifact

```jsonc
{
  "schema_version": 2,              // this artifact's own version, not the report's
  "payload": "diff",                // which artifact this is (SPEC-report.md §7.1),
                                    // in the same position as the other five. Additive,
                                    // so `schema_version` did not move for it (#345)
  "tool": { "name": "partspec-diff", "version": "0.8.0" },
                                    // partspec's own version. `diff` has none of its own
                                    // and never has, so a sample showing one invites a
                                    // consumer to key on a number that will never appear.
                                    // `schema_version` above versions this artifact.
  "part": "example-spacer",
  "outcome": "different",           // identical | different | indeterminate
  "indeterminate": [],              // {code, reason[, remedy]} entries when indeterminate;
                                    // `remedy` is present only where the gap has one, and
                                    // is printed under the headline; codes are
                                    // machine-readable: "input_error" | "partial_closure",
                                    // so CI can tolerate one narrowly instead of tolerating
                                    // exit 2 wholesale. `partial_closure` now covers only
                                    // bounded gaps and absent closures; the reason names
                                    // each one, and `source.unseen.bounded` keys them
  "verdict": { "old": "pass", "new": "fail" },
  "counts_total": { "old": 8, "new": 7 },
  "contract": {
    "digest_changed": true,
    "target_changed": {             // the invoked target, present ONLY when the two
      "old": "same.py:imperial",    // sides name different FACTORIES and both name one
      "new": "same.py:metric"       // (§3). Outcome-bearing, unlike every digest here
    },
    "module_changed": {             // the recorded module path moved — a rename, so it
      "old": "single.py",           // is recorded and never outcome-bearing (§3).
      "new": "renamed.py"           // Present only when it differs
    },
    "target_incomparable": {        // present when the two values differ and a side names
      "old": "spec.py",             // no factory: which target ran was NOT compared, and
      "new": "spec.py:make"         // §3 requires the summary to say so (§2's opening)
    },
    "removed": ["wall_gt_2"],       // the headline finding, by id
    "added": []
  },
  "source": {
    "digest_changed": false,         // the entry file
    "closure": "changed",            // same | changed | inconclusive — whether the two
                                     // reports RECORDED different closures, not whether
                                     // the part's inputs moved: an entry in
                                     // `imports.unattributable` makes it "changed" while
                                     // saying nobody can tell whose import it was
    "closure_digest_changed": true,  // the closure digest, on its own field because a
                                     // bounded gap collapses `closure` to "inconclusive";
                                     // null when a side carries no closure at all
    "imports": {                     // the distributions the model loaded (SPEC-report 8.3),
                                     // three groups for the reason `environment.packages`
                                     // has three; `{ "uncomparable": "…" }` when a side
                                     // recorded no map, never an empty delta
      "changed": { "cqgridfinity": { "old": { "…": "…" }, "new": { "…": "…" } } },
      "added": {},
      "removed": {},
      "unattributable": []           // names in `added`/`removed` that a side's
                                     // `preloaded` covers: on one side only, and this
                                     // comparison cannot say whether they moved.
                                     // Never reported as an appearance, and never
                                     // explained away as batch position either
    },
    "unseen": {                      // the gaps by class, token -> what it says to a reader
      "irreducible": { "native_reads": "files read inside C extensions — …" },
      "bounded": {}                  // non-empty here means `closure: "inconclusive"`
    },
    "covered": "model directory (2 files); 14 imported distributions, all unchanged"
                                     // null where neither closure carries `unseen`, i.e.
                                     // two pre-0.7.5 reports, which get no coverage block
                                     // invented for a coverage they never recorded
  },
  "checks": [                        // one entry per difference; empty when identical
    {
      "id": "envelope", "kind": "envelope", "change": "drifted",
      "status": "pass",
      "value": { "old": [15.8, 15.8, 8.0], "new": [15.8, 15.8, 9.6] }
    },
    {
      "id": "genus", "kind": "genus", "change": "regressed",
      "status": { "old": "pass", "new": "fail" }
    },
    {
      "id": "watertight", "kind": "watertight", "change": "fixed",
      "status": { "old": "fail", "new": "skipped" },
      "answered": { "old": true, "new": false }
                                    // present only when the NEW side is not
                                    // answered: `fixed` here is the severity
                                    // order, not a repair. Both sides shown so
                                    // a check that stopped being answered is
                                    // distinguishable from one that never was
    }
  ],
  "environment": {
    "engine_version": { "old": "2021.01", "new": "2026.08.01" },
    "packages": {                    // present when a package differs, and in the
                                     // `uncomparable` shape when a side has no map;
                                     // absent when both sides carry the same map
      "changed": { "trimesh": { "old": "5.0.0", "new": "5.1.0" } },   // a version moved
      "added":   { "shapely": "2.1.2" },   // installed on the new side only
      "removed": {},                       // installed on the old side only
      "first_recorded": []                 // names in `added` the pre-0.7.5 five-name
                                           // field could not have carried: the record
                                           // widening, never an install
    }
  }
}
```

Field rules follow `SPEC-report.md` §7.1: additive fields are non-breaking; consumers MUST
ignore unknown fields and reject an unknown `schema_version`. `checks` lists differences
only — an entry per unchanged check would bury the finding in ceremony; `counts_total`
carries the reconciliation.

## 5. Non-goals

- **No weakening adjudication.** `limit_changed` shows both sides and stops. Deciding that
  a change *weakened* a contract needs a direction model and is #31's, not this verb's.
- **No visual diff.** Renders are evidence attached to a report (#21 consumes them).
- **No multi-report timelines.** Two inputs, one comparison. A trend over N runs is a
  consumer loop over N−1 diffs.

---

## Appendix: the visual diff (`partspec vdiff`, #21)

`vdiff` is the pair of this document's diff: that one says what changed in the claims,
this one what changed in the part's appearance. It consumes two on-disk render artifacts
(`render.json` from the `render` verb, or a report carrying `renders`) and emits its own
document (`vdiff_schema_version: 1`) with the same outcome vocabulary — `identical`
(exit 0) / `different` (exit 1) / `indeterminate` (exit 2).

Keys: `schema_version` and `payload` (`"vdiff"`) first, the identity prefix every other
artifact carries — this document spelled its version `vdiff_schema_version` alone, so a
consumer reading `doc["schema_version"]`, the key `SPEC-report.md` §7 tells it to key on,
found nothing; both spellings are emitted for one release (#295). Then
`inputs` (file, part id and engine block per side), `views` (per view:
`pixels_changed`, `fraction`, `image` — the diff image, the new run faded to grey with
changed pixels in magenta), `bbox_delta_mm`, `magnitude`, and on refusal `refused
{reason[, hint]}`.

Rules, all MUST:

- **No silent rescaling.** Differing image sizes are refused.
- **No cross-version scoring.** A pair rendered by different engine kinds or versions is
  refused: 7.68% of pixels differ across OpenSCAD versions for identical geometry (the
  recorded audit measurement), and scoring renderer noise as change is the tool lying.
- **No cross-part pairing.** Different part ids, and differing view sets, are refused.
- **Scale cannot hide.** The framing scales with the part, so a uniform size change is
  pixel-invisible; `render_bbox` is compared alongside, and a bbox delta with identical
  pixels is `different` with a `note` referring the numbers to `measure`.
- **The scalar is reproducible.** `magnitude = max(worst view fraction,
  bbox_delta_mm / old bbox diagonal)` — 0.0 exactly when nothing changed.
