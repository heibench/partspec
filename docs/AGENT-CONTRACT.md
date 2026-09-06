# The agent contract — driving partspec in a repair loop

**Applies to:** v0.8.0 — the release this text describes. The `Status:` line records when
this document was last revised in substance; it is provenance, not currency (#300).

**Status:** v1 · 2026-08-08 · closes #28
**Audience:** an agent (or the harness around one) using `partspec` to take a part to
green, **via the CLI**.
**Scope:** how to act on partspec's output. How to *author* a contract is
`SPEC-contract.md`; what the artifact means is `SPEC-report.md`.
**If you are about to write one, start at `skills/contract-authoring/SKILL.md`** — it is
the routing document, and it sends you to the source-side skill for your engine
(`openscad-authoring`, or `build123d-authoring` for build123d and CadQuery). The spec is
normative and closes the vocabulary; the skill is how to choose within it.

A path beginning `docs/` or `skills/` — the routing path above is one — is relative to
the directory **`partspec --docs`** prints: the repository root in a checkout, and the
copy of both trees that the wheel carries in an install (#349). A bare `SPEC-report.md`
means `docs/SPEC-report.md`. A path under `tests/` is a pointer into the repository, which
an install does not carry. Before #349 the routing path above resolved to nothing at all
for anyone who installed rather than cloned.

**The `partspec-mcp` tools cannot execute this document.** They run the same CLI per call,
but the four registered tools are `check` / `measure` / `render` / `vdiff`, and the check
tool builds only `["check", target, "--quiet"]` plus `--out` and `--render`. There is no
`--expect`, no `--pin`, no `--timeout`, and **no `diff` tool and no `lint` tool** — so §1
step 1's claims pin and §4's `diff` remedy are both unreachable from MCP, and so is the
advisory source read. An MCP-driven agent is running a weaker loop than the one specified
here, and should be told so rather than assumed to be following it. (Tracked: the flags
are plumbing, not design.) The MCP server's own `instructions` now say all of this, which
is the only place an MCP client can learn it: that client has a tool list and nothing
else. The package does ship these documents now, but reaching them still means leaving
the tool surface for a shell — there is no docs tool either.

The one rule everything below serves: **the report artifact is the ground truth, and
only `pass` is green.** Read `report.json`, not the console — the console is a courtesy
and MCP runs `--quiet`.

---

## 1. The loop

1. `partspec check <target>` — with `--expect <lock>` whenever a lockfile is committed
   beside the contract or named in the repo's CI invocation (conventionally
   `claims.lock`). A green obtained without the pin while a lock is committed is
   unverified: re-run with `--expect` before believing it, and a harness should treat
   the missing flag as reviewable.
2. Read `report.json`. Act per §2, editing **one thing per attempt**.
3. Re-run. **At most 5 attempts per part**, counting every run after the first.
4. On attempt 5 without green — or as soon as any §4 condition fires — escalate per §3.

**Feed the failure forward.** Each attempt's context must carry the previous failing
check's `id`, `measurement`, `limit`, and `detail`. Re-deriving the failure from scratch
is how a loop rediscovers the same dead end five times; the report already names the
axis and the bound that broke (`components`, `detail`), so the next edit can be aimed.

**Batch:** `check` takes several targets in one process. The exit is the
highest-**precedence** verdict across parts — `error > empty > fail > incomplete > pass`
(SPEC-report §6.2), so a batch containing a disproven part can still exit `3` if another
part asserts nothing. Route per-part from each part's own report, never from the process
exit; iterate on the one failing part singly and re-run the batch to confirm. The one
thing the reports do not carry is §2's exception: a render the run was asked for and did
not deliver is a fact about the RUN, so it reaches the exit and stderr — named with its
target — while that part's own report says whatever the part deserved, `pass` included.

## 2. What each outcome instructs

Every evaluated `check` run leaves a report at the deterministic path (a placeholder
saying the run died is written before anything happens, then overwritten by the real
report; a usage refusal — exit 64 — may leave the placeholder, or nothing when the
invocation's shape was refused outright). That path is
`<contract dir>/outputs/<part-slug>/report.json` unless `--out` says otherwise —
anchored to the contract file, not to the working directory, so the same command run
from anywhere writes to the same place. `<part-slug>` is the module stem, plus
`-<factory>` when a factory is named. The exit code plus two fields — `verdict` and
`error` — decide the action, with **two** exceptions, both of which exit 4 while the
report says something else:

1. The uncovered-pin failure (§4) lives on stderr and in the exit alone, because no report
   path exists for a part no target produced.
2. A `check --render` whose render fails on an otherwise green part writes a normal report
   — `verdict: "pass"`, `error: null`, no `hint` — and still exits 4. The report speaks for
   the part; the exit speaks for the run, and the run did not produce what was asked of it.
   The diagnosis is on stderr, prefixed with the target when several were given, since one
   message and N parts otherwise names nothing.

In both, reading `error` and `hint` from the report yields nothing. Read stderr.

| exit | verdict | action |
|---|---|---|
| `0` | `pass` | Stop. Do not "improve" a passing part. First green on an unfamiliar file: apply §5 before believing it. |
| `1` | `fail` | Something asserted was disproven. Disambiguate by the failing check (§2.1), then edit the **model** — or, for a parameter-phase fail, the declared parameter *values*; never the claims (§4). |
| `2` | `incomplete` | Nothing disproven, not everything proven. **Do not edit geometry** — the part is not the problem. Disambiguate by `checks[].status` (§2.2). |
| `3` | `empty` | The contract asserts nothing — the single most likely output when you do not know what to assert. Run `measure`, decide which numbers are *intent*, declare them. Never celebrate exit 3. |
| `4` | `error` | Not a statement about the part (§2.3). Read `error` and `hint` — **except in the two cases above, where the report carries neither and stderr is the only diagnosis**; fix the machine or the contract, or escalate. Editing the model on exit 4 is noise. |
| `64` | — | Your invocation is malformed (unresolvable target, bad flag, missing/corrupt pin, colliding slugs). Fix the command, not the code. |
| `130` | — | The operator interrupted you. Stop entirely. |

### 2.1 exit 1 — which `fail`?

- **`id: "builds"` failed** → the source does not compile / the model raised
  (`build_origin: "model"`). Fix the source; `build_stderr` carries the engine's own
  diagnosis unabridged.
- **A check with `phase: "parameter"` failed** → the *declared inputs* are wrong, before
  any geometry existed: a `requires` expression came out false (`operands` shows the
  values it read) or a `param` left its range. Everything else reports `skipped` with a
  `detail` naming the blocker ("not evaluated: parameter check … failed") — fix that
  blocker first; nothing else was asked. The fix is the parameter values in the
  contract's source declaration (`openscad("m.scad", x=…)`), which is a value edit, not
  a claim edit — it changes no claim slug and does not trip the pin.
- **A geometry check failed** → the geometry is wrong. `measurement` vs `limit` says by
  how much; `components` names the failing axis; for `hole_diameter`/`bolt_circle` the
  `detail` carries the full bore inventory or the nearest circle found.

### 2.2 exit 2 — which `incomplete`?

Read the non-`pass` statuses in `checks[]`:

- **`unsupported`** → this engine tier cannot answer, and `requires` names the tier that
  would (`"occt"` → port the source to build123d/CadQuery, or accept the gap). **Never
  delete the unanswerable check to make the run conclusive** — that is §4.
- **`approximate`** → the guaranteed interval around the measurement straddles the limit:
  the tool does not know, and will not guess. **Live since `min_wall` shipped** (#140) and
  routine on the OCCT tier — a wall whose bound is `[1.0, 3.0]` against `min=2` is neither
  proven nor disproven. This paragraph told you the opposite until the v0.7.0 sweep, and an
  agent following it would have escalated correct output as a tool bug. Act on it: tighten
  the design away from the boundary, or measure the feature a different way, or accept the
  gap and say so. **Never shave the limit to swallow it** — that is §4.
- **`skipped` alone** cannot produce exit 2 in v0: every path that skips checks
  co-occurs with a `fail` (exit 1, §2.1's parameter branch) or an `error` (exit 4). A
  lone `skipped` under exit 2 would mean a referenced part is absent — an assemblies
  state with no v0 path — and is worth escalating as unexpected.

### 2.3 exit 4 — whose error?

- **`build_origin: "environment"`** → the machine, not the part: missing engine or
  package (named in `hint`), absent source file, or a blown build budget — `error` names
  the budget; a legitimately slow model gets `--timeout` raised *deliberately*. **Unless
  `error` says a variable list is INCOMPLETE** — that shape carries the same origin and
  is the next bullet, and it is the one case here where the source may be at fault.
- **`error` says a variable list is INCOMPLETE** (`build_origin: "environment"`) → an
  `include` did not open, so partspec could not finish reading which names `-D` can bind
  and will not judge your parameter either way. `error` names the file. **This is the one
  `build_origin: "environment"` shape where a model edit may be the fix**, against the
  table above: the include path can be misspelt in the source exactly as easily as the
  library can be missing from the machine, and partspec cannot tell those apart —
  `environment` is the nearer of the two values it can carry, not a finding. The two
  `build_origin: null` shapes below — a name that did not resolve, and a value the engine
  could not convert — are model edits too, but they never claimed the machine's origin, so
  the tension this bullet exists to flag is not theirs. Said "the one exit-4 shape" until
  it was one of three. Check the path in the source first, then the
  machine. Do not touch the contract: the parameter has not been judged, so nothing has
  been said about it.
- **`error` mentions the claims pin** → the contract does not match its committed lock.
  If you did not change the contract, someone else's change is unreviewed — escalate.
  If you did: §4.
- **`error` names a name the engine could not resolve** (`build_origin: null`) → the
  build *succeeded* and the artifact **may not be** the part: OpenSCAD renders an
  unresolved call's children not at all, so a misspelt module or an include that did not
  open removed geometry the contract is about (`FAILURE-MODES.md` §1). *May*, because the
  marker does not separate the shapes: an unresolved **module** removes its children, and
  an unresolved **function** in a position that reaches no geometry does not.
  `echo(nofunc(3)); cube([10,5,2]);` exports byte-identical to the `cube` alone on both
  pinned engines, and is refused anyway — partspec cannot tell which shape it has, and a
  refusal it can defend is not improved by a claim it cannot (#375). The `error` field
  hedges to match. **Do not touch the
  contract** — the fix is in the model source or on `OPENSCADPATH`. `error` quotes the
  engine's own line verbatim, and the two pinned engines word it differently. An
  unresolved module, function or variable names the file and the line number on both. An
  include that did not open reads `Can't open include file 'BOSL2/std.scad'.` on 2021.01
  — the include path and nothing else — and `Can't find include file 'BOSL2/std.scad'. in
  file <the file containing the include>, line N` on 2026.08.01 — which for a nested
  library include is not the entry file. So on the older engine, start from the include
  path; do not expect a location. Whether it is a typo or a library absent from this
  machine is what partspec cannot tell, which is why the origin is `null` rather than a
  guess.
- **`error` says the engine could not convert a value and built a default in place of
  it** (`build_origin: null`) → the build *succeeded*, every name resolved, and the
  artifact is still not the part: a value reaching a module's parameter was not a type it
  accepts, so the engine substituted **that module's own default** and exported it.
  `cube(size=[o, 30, 6])` with `o = undef` gives a 1×1×1 unit cube — clean, watertight,
  one solid — on both pinned engines. **Do not touch the contract**, and **do not go
  looking at `OPENSCADPATH`**: nothing here is missing from the machine. `error` quotes
  the engine's own line, which names the module and the value it rejected —
  `Unable to convert cube(size=[undef, 30, 6], ...) parameter to a number or a vec3 of
  numbers in file part.scad, line 2`, identical on both engines. Read it as a pointer to
  the *expression*, not the module: the fix is wherever that value was left `undef` or
  given the wrong type, which is usually a parameter that was never bound or a name
  spelled correctly but assigned nothing.
  **A second spelling, and it does not mean quite the same thing.** `rotate()` words its
  failure `Problem converting rotate(a=undef) parameter in file part.scad, line 2` — also
  identical on both engines — and it says the engine could not use the `rotate` parameters
  *as written* (#333). `error` says so too, and adds only a hedged consequence — **the
  engine could not use a value as written, so the geometry measured may not be the
  geometry this source describes** — never the substitution sentence above, because for
  one of these shapes no default is taken (#360). `rotate([90,0,0,0])` exports
  byte-identical to `rotate([90,0,0])`, so *may* is the strongest claim the line carries
  (#375). Sometimes that is a default going in and the
  rotation being lost:
  `rotate(undef)` and `rotate([undef,0,0])` leave the part at identity, nothing having
  changed size, standing in an orientation nobody wrote down. Sometimes it is not.
  `rotate(a=45, v="z")` substitutes the **default axis** `[0,0,1]`, so the part really is
  rotated 45° about Z; `rotate([90,0,0,0])` substitutes **nothing at all** — the engine
  reads the first three components of an over-long vector and applies them, and only
  complains about the fourth. Read the line as "look at this `rotate` call", not as "your
  part is unrotated".
  **What neither spelling says is whether the mesh is actually wrong.** Two measured
  shapes where it is not, both refused at exit `4` on both engines, both covered by
  `FAILURE-MODES.md` §9:
  - **A fault inside `%` background geometry** (§9a). OpenSCAD evaluates the subtree under
    a `%` (background) modifier and then excludes it from the render, so a fault inside one
    is narrated on stderr while contributing nothing to the mesh:
    `cube([40,30,6]); %translate([undef,0,0]) cube(2);` exports a file **byte-identical**
    to the same source with the `%` line deleted. If the quoted line's file and line number
    land on a `%` subtree, the mesh you have is very likely correct. `*` (disable) is the
    modifier that costs nothing — its subtree is never evaluated, so it emits no
    diagnostic — while `#` (highlight) is exported, and its warnings are about the mesh.
  - **A `rotate()` parameter the engine ignored** (§9b). `rotate([90,0,0,0]) cube([10,5,2])`
    exports **byte-identical** to `rotate([90,0,0]) cube([10,5,2])`, and
    `rotate(a=45, v="z") cube(5)` to `rotate(a=45, v=[0,0,1]) cube(5)`.

  In both, **the source is wrong and the mesh may be right**, and the remedy is the same
  as for the damaging shapes: fix the value, or delete the scaffolding. Do not conclude
  the tool is unreliable, and do not go looking for a flag to wave it through — there is
  none, by design.
- **Otherwise** → the contract itself raised (the report says "the contract is wrong,
  not the part"), or the report is still the placeholder ("run did not complete") —
  whose most common cause is deterministic, not transient: **the contract failed to
  resolve** (a typo'd keyword, an import error at contract scope), and here the
  diagnosis (the traceback) is on stderr only, like the uncovered-pin case — though
  here a placeholder exists where that one leaves no report at all. Re-run once; if the
  placeholder recurs, read the console before escalating — the fix is usually a
  one-line contract repair to propose.

### 2.4 `measure` and `render` — the table above is `check`'s

§2 opens "Every evaluated `check` run", and that is exact: the table governs `check`.
`measure` and `render` reach no verdict, so they exit `0` or, on **any** build failure,
`4` — model-origin included, which is the case the table has no row for.

**`measure` has one further exit-`4` state, and it is the only one that emits a full
payload.** If a backend *raises* while measuring a name, that name lands in `refused`
with `refused_by: "tool"` and the run exits `4` **with every other measurement present**
(#371). Read it as "partspec failed for that name", never as a finding about the part:
the numbers on stdout are as good as they ever were, and the exit code is not about them.
It is distinguishable at a glance — the failure shape below carries `error` and no
`measurements`, this one carries `measurements` and no `error`.

**The table routes you into it.** The exit-3 row says to run `measure`, and a contract
that asserts nothing over a model that does not build is exactly the shape that produces
exit 3: measured, a checkless contract over a `.scad` with a syntax error gives `check`
exit `3`, `verdict: "empty"`, `checks[0]` = `("builds", "fail")` — `empty` outranks
`fail` (`SPEC-report.md` §6.1) — and the `measure` that row prescribes then exits `4`.

**So "editing the model on exit 4 is noise" is a rule about `check`, and does not carry
here.** On these two verbs, decide whose fault it is first:

- **`render` carries the answer.** Its failure payload has an `origin`, `"model"` or
  `"environment"`; branch on it exactly as §2.3 branches on `build_origin`. Measured, that
  same syntax-error `.scad` gives `origin: "model"`, and the same contract run under
  `PARTSPEC_OPENSCAD=/nope/openscad` gives `origin: "environment"`.
- **`measure` has no such field for a build failure, so there is nothing to branch on
  there.** (It does carry `refused_by` when a *measurement* was refused, which is a
  different question — that block is about individual names on a part that built.)
  Measured, its failure payload carries exactly `engine`, `error`, `geometry`, `hint`, `params`,
  `part`, `payload`, `schema_version`, `tool` — in *both* failure modes, and
  `tests/test_cli.py::test_the_measure_failure_payload_carries_exactly_these_keys`
  fails when that stops being true. `origin` is **absent**, not
  null, so a consumer cannot even read it as "unknown". Fall back to the prose: `error`
  and `hint` quote the engine, and a parser error naming a line in your source is the
  model where a missing binary or package is the machine. Or run `check` on the same
  target, whose report does carry `build_origin`.

**States fall outside both branches, and none of them is about the part.** If the exit is
`4` and **stdout is empty** — no payload at all, not a payload without `origin` — then
either the contract raised **or partspec itself failed**, before the verb had anything to
describe. (Empty is the discriminator, and it is why the `refused_by: "tool"` state above
is not one of these: partspec failed for *one name* there and still described the part.) **stderr says which**, in one line, and the two are distinct:

- *"the contract is wrong, not the part"* → the contract raised. That is §2.3's last
  bullet and it applies here in full; §2.4 narrows the table's *rows*, not §2.3's
  diagnosis of a contract that would not run. Measured, a factory that raises gives both
  verbs exit `4` and zero bytes on stdout, with the traceback above that line.
- *"this is a partspec failure, not a verdict on the part"* → partspec's own failure, and
  an **escalation** (§3) rather than a contract repair. Measured, `render --out` pointed
  at an existing **file** gives exit `4` and zero bytes with a `NotADirectoryError`, on a
  contract that is entirely correct. Proposing a one-line fix to that contract is the
  wrong move; nothing in it is wrong.

**The two verbs are not symmetric here, so do not infer one from the other**: that same
bad `--out` leaves `measure` emitting a payload rather than an empty stdout.

And exit `64` still means what the table says it means — a malformed invocation, stdout
empty, e.g. a target naming a file that does not exist. Read stderr in every one of these
cases; there is no artifact to read.

That asymmetry is a gap rather than a design. `check`'s report has carried `build_origin`
since #47 and `render`'s payload gained `origin` in #191; `measure` was given neither, and
the two that exist do not even share a key name. Giving `measure` the same field is the
real fix; until it has one, the prose is what there is.

`lint` is not part of this gap, and is documented where it belongs. It exits `0` whatever
it finds — the findings are data in its payload, `64` is reserved for input it cannot lint
at all, and `LINT.md` says both, and says in as many words that its exit 0 is not this
table's exit-0 row.

## 3. Escalation

Emit exactly this line — it is the greppable surface a harness watches:

```
HUMAN_REVIEW: <why in one clause> — last failure: <check id>: <detail or error text>
```

Parse rule for harnesses: split on the **first** `" — last failure: "`; everything after
it is one opaque assertion string (check ids legitimately contain colons — `param:x`,
`iso15:608:seat` — so id and detail are not separately recoverable, by design).

Example:

```
HUMAN_REVIEW: bore must be Ø22 H7 but the seat prints at 22.31 after 5 attempts — last failure: iso15:608:seat: found 0 bore(s) with diameter in [21.99, 22.01] mm, expected 1
```

Escalate — immediately, without spending remaining attempts — when:

- green would require **weakening the contract** (§4);
- the same check has failed **identically twice** despite different edits;
- exit 4 persists after one environment fix attempt;
- the contract itself appears wrong (a limit contradicts the drawing, a `requires`
  expression is inverted): propose the contract change in the escalation, do not apply it.

## 4. Out of bounds — and the guards that are watching

**Never weaken the contract to reach green.** Deleting a check, loosening a limit,
swapping a strict check for a lax one, stripping a `source` citation, or dropping a
pinned part from the invocation — from where you sit these are indistinguishable from
"fixed it", which is exactly why they are forbidden and instrumented:

- the **claims pin** (`--expect claims.lock`) catches all of that, but its guards do not
  cost the same, and the difference is a build budget. A lock that is missing or the wrong
  schema is refused before any target runs (exit 64). A **claim mismatch** — the declared
  claims differ from the lock — is adjudicated from the resolved contract, so *that part*
  never builds and every removed/added/changed claim is named (exit 4, `expectation` block
  in the report): free in a single-target run, but a batch keeps going, so the other pinned
  targets still build. A **dropped part** — the lock covers a part no target in this
  invocation produced — is compared only after the target loop has finished, so today every
  surviving target **builds first** and the run fails after them: budget a full build per
  surviving part, tens of seconds each on the OCCT tier. That variant is also the one guard
  with **no report evidence**: the surviving parts' reports look normal (`verdict: "pass"`,
  no `error`), the confession is stderr + exit 4 alone — a harness must watch the exit, not
  only the artifacts;
- **re-pinning after weakening** (`--pin`) defeats nothing, and it leaves three records,
  not one: the committed lock's diff in your PR, a stderr line naming every claim the
  rewrite overwrote, and — in the report of each part the lock already covered and whose
  claims moved — `expectation.repinned` carrying the same lines (#294), which they are
  under any single writer: the report answers for the lock the run found and the stderr
  line for the lock it is about to overwrite, two reads that agree unless the file moved
  under the run (SPEC-report §7.1). That block says
  what was **compared, not what was written**: the write is refused when a crashed target
  would drop a claim set, and the differences named are then what the run declined to
  overwrite (SPEC-report §7.1). The report half matters because the first two can both be
  absent from what a reviewer reads: a lock nobody committed has no diff, and stderr is
  not an artifact. None of the three is a refusal; a deliberate re-pin is permitted.
  Treat running `--pin` as requiring the same human sign-off as the contract edit itself.

  **One arrival leaves none of the three.** A lock that could not be READ — malformed, or
  a schema this build does not know — is still overwritten when nothing failed to resolve,
  because overwriting one is the documented way out of it. partspec then says on stderr
  that it cannot tell which claims moved, and no report carries `expectation` at all,
  there being nothing to compare against; the lock's own diff is equally unreadable. That
  path is the one where "the lock is committed" buys a reviewer nothing, so read the
  stderr line and re-derive the claim set from the contract before signing anything off;
- `partspec diff old/report.json new/report.json` reports `removed` and `limit_changed`
  on comparison, including a stripped citation. The **first** comparison against a
  baseline recorded before v0.7.5 is a migration, not a finding about the part: a Python
  baseline is `indeterminate` at exit 2 because it carries no import map, and either tier
  reports the widened `environment.packages` as names recorded for the first time. Both
  name the same remedy — re-record the baseline (`indeterminate[].remedy`,
  `environment.packages.first_recorded`) — and it is one step, not a per-run condition to
  tolerate;
- the run-level `attribution` block discloses when every dimensional limit is
  unattributed — bounds derived from the model's own numbers prove the model matches
  itself; take limits from `partspec.refs` (`iso15`, `iso_metric_thread`,
  `nema17`) or the drawing.

A contract change can be *right* — the fix is to propose it in an escalation and let a
human apply and re-pin it, never to make it silently.

**`check` overwrites its report, so the baseline for that `diff` is yours to keep.**
Every run writes to one deterministic destination — `<contract dir>/outputs/<slug>/report.json`,
or `<--out DIR>/report.json` — and overwrites it. The second run of any repair loop destroys
the only baseline the first produced, and `outputs/` is gitignored at every depth in this
repository and in the layout the exemplars use, so a report left where `check` put it is
**overwritten and then untracked**. Nothing does the copy for you:

```console
$ partspec check spec.py:part --out o --quiet
$ cp o/report.json baseline.json          # the step no flag performs
# ... edit the model ...
$ partspec check spec.py:part --out o --quiet
$ partspec diff baseline.json o/report.json
```

Take the copy **before** the run that might change something, not after you wish you had.
The convention: commit `baseline/report.json` beside the contract when the drift matters
across sessions, or keep it as a CI artifact when it matters only across one pull request.
`vdiff` needs two `render.json` and takes the same step.
`examples/spacer/README.md` is the worked copy of both this and the pin above.

## 5. Before believing a green run

On the first `pass` for an unfamiliar part, confirm in `report.json`:

1. `counts.total` is plausible for the part's complexity — one `watertight` on a bracket
   with four bolt holes proves almost nothing (exit 3 catches *zero* checks; it cannot
   catch *too few*). Under `--expect` the test is exact, not a judgment call:
   `counts.total == expectation.claims + 1` (the implicit `builds` check). Only under
   `--expect` — the `--pin` form of the block carries `repinned` and no `claims`, so read
   that field with `.get`, never as a key;
2. `attribution.dimensional > 0` with `attribution.attributed == 0` is the
   circular-contract signal — checkable from those two fields alone. Two honesty limits:
   `attributed` counts citations present, not pertinent; and arithmetic on a
   `Referenced` value deliberately sheds the citation (a derived number is the
   author's), so cite the un-derived bound, not an expression over it;
3. `part.source_closure.partial` — **absent means complete, so read it with `.get`**: a
   clean OpenSCAD closure carries no `partial` key at all, and the field is never emitted
   as `false` anywhere. A partial closure means "nothing *we looked at*
   changed"; treat identity claims accordingly. `unseen` says *which* gaps, from a closed
   vocabulary, and `imports` says which distributions the model loaded and whether their
   bytes were read or their installer taken at its word (SPEC-report §8.3). An unrecognised
   `unseen` token is a gap, not noise; `imports` absent means the question was never asked.
   `imports` **over-reports in a multi-target run** — one interpreter, one `sys.modules` —
   and `preloaded` names the entries this part cannot be credited with. Such an entry may
   have been loaded by this part or by an earlier target — nothing in the report can say
   which — so treat its arrival between two runs as unresolved: not as a build input that
   appeared, and equally not as one that did not (§8.3 rule 7). In a diff this shows up as
   `source.closure: "changed"` with the name in `source.imports.unattributable`: the field
   says the two reports recorded different closures, never that the part's inputs moved,
   so read the two together and not `source.closure` alone.
   `diff` classifies those gaps rather than counting them: `native_reads` is irreducible on
   the Python tier and reaches no verdict — it is printed on every outcome as `not covered:`
   — while every other token, recognised or not, still blocks `identical` (SPEC-diff §2
   rule 3). Read the `not covered:` line; do not filter it out;
4. when a pin is in play, `expectation.matched` is `true` in this same report. That field
   belongs to the `--expect` form of the block; a `--pin` run writes the other form,
   `expectation.repinned`, and its presence says this run's declared claims differ from a
   lock that already covered this part — a rewrite this run would perform, and did unless
   the write was refused (§4) — so read those lines before believing the green
   (SPEC-report §7.1).

---

*Design basis: cad-khana's `SKILL.md` (bounded loop, greppable escalation, feed-forward,
vacuous-green warning), recorded in `POST-V0.md` §3. Acceptance per #28 with the
2026-08-06 audit revision: the action map keys on (exit, verdict, report fields), not on
the exit code alone.*
