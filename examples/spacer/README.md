# spacer — the smallest honest contract

The example the front page inlines, and the one to read first. It exists to show
the *whole* loop on a part small enough to hold in your head: an OpenSCAD source,
a contract beside it, and a report that says which claims were proven.

```console
$ partspec check examples/spacer/spec.py:spacer
```

Every other exemplar teaches something extra. `bearing-block` runs the *shared*
claims against both engines — not one identical contract, which is the point: the
build123d leg adds the cited seat diameter, and the OpenSCAD leg omits it because
a 96-gon bore has no diameter to measure. `stepper-bracket` reduces a whole
mounting interface to one cited call, `nema17.mount(p)`. `enclosure` is one
factory with four members, three ordinary and one whose walls consume its own
height — `requires` disproves that member in the parameter phase, before a render
is attempted. This one adds nothing to the *vocabulary* on purpose; what it does
carry, and no other exemplar does, is the loop **around** the contract — the
committed `claims.lock` below, and the baseline a `diff` needs.

## What it claims, and why each claim is here

| claim | what it catches |
|---|---|
| `requires("bore_d + 2 * wall <= plate_y")` | a bore that cannot leave the wall the design asks for — decided from the parameters, before any geometry exists |
| `requires("bore_d > 0")` | a degenerate bore, for the same price |
| `param("plate_z", min=1.0)` | a plate driven to zero or negative thickness by a caller |
| `envelope(max=PLATE)` | a part that grew past the space it has to live in |
| `watertight()` | a mesh that looks right and is not a solid |
| `solid_count(1)` | a boolean that quietly left two bodies |
| `genus(1)` | the bore stopped being a through-hole — a blind hole is genus 0, and a hole that reaches the edge is a notch (`docs/FAILURE-MODES.md` entry 3) |

The last two are the interesting pair. A spacer whose bore has drifted off the
edge is still watertight, still one solid, still inside its envelope, and no
longer a spacer. `genus` is the claim that notices.

## The claims pin — `claims.lock`, committed beside the contract

`claims.lock` in this directory is the repository's only committed claims pin,
and it is here to be copied. It records the *claim set* — one entry per declared
check, seven of them; the implicit `builds` is not pinned, which is why
`counts.total` is 8 and `expectation.claims` is 7. A run whose contract has
drifted from it fails **before the engine starts**, so the pin costs no build.

Write or update one:

```console
$ partspec check examples/spacer/spec.py:spacer --pin examples/spacer/claims.lock
...
pinned 1 part(s) -> examples/spacer/claims.lock
```

Enforce it. This is step 1 of
[`docs/AGENT-CONTRACT.md`](../../docs/AGENT-CONTRACT.md) §1, and it is what CI
runs on every pull request and on every push to `main` (`just example-spacer`):

```console
$ partspec check examples/spacer/spec.py:spacer --expect examples/spacer/claims.lock
...
PASS: 8 pass · not rendered
$ echo $?
0
```

Now loosen a bound — `PLATE = (40.0, 30.0, 9.0)` — and re-run the same command:

```console
  --   bore_d_2_wall_le_plate_y — not evaluated: the contract does not match its pin
  ... elided ...
  --   builds — not evaluated: the contract does not match its pin

ERROR: 8 skipped
  the contract does not match its claims pin: changed: envelope — pinned 'envelope max=[40.0, 30.0, 6.0]', declared 'envelope max=[40.0, 30.0, 9.0]'
  hint: a deliberate contract change is re-pinned with --pin; anything else is the contract quietly not being the one that was reviewed
$ echo $?
4
```

Every check is `skipped`, not failed: the question changed identity, so nothing
may be said about the part. Exit 4 is `error` — nothing was evaluated, so
nothing may be concluded. **This particular exit 4 must never be repaired by
editing the contract**, which is §4's rule and is specific to the pin: exit 4
from a contract that *raised* is repaired by editing the contract, and
`AGENT-CONTRACT.md` §2.3 says exactly that. The two are told apart by the
report — a pin mismatch names the moved claims in `expectation.differences`.

A change that is genuinely intended is re-pinned in one flag, and says what it
overwrote on stderr:

```console
$ partspec check examples/spacer/spec.py:spacer --pin examples/spacer/claims.lock
...
pinned 1 part(s) -> examples/spacer/claims.lock
partspec: --pin rewrote claims the previous examples/spacer/claims.lock already covered:
    example-spacer: changed: envelope — pinned 'envelope max=[40.0, 30.0, 6.0]', declared 'envelope max=[40.0, 30.0, 9.0]'
  hint: the lock's diff is the whole record of this change — ...
```

That line is one of **three** records of the same move, and it is why the lock
is **committed**: the tool makes weakening impossible to do *silently*, not
impossible to do. The diff of this file in a pull request is the second. The
third is in the report `check` just wrote — `expectation.repinned`, carrying
that same line — and it is the one a reviewer still has when the other two are
missing, since an uncommitted lock has no diff and stderr is not an artifact
(`AGENT-CONTRACT.md` §4, `SPEC-report.md` §7.1):

```console
$ python3 -c "import json;print(json.load(open('examples/spacer/outputs/spec-spacer/report.json'))['expectation'])"
{'repinned': ["changed: envelope — pinned 'envelope max=[40.0, 30.0, 6.0]', declared 'envelope max=[40.0, 30.0, 9.0]'"]}
```

## The drift the pin cannot see

The pin covers the claim *set*. A wall thinning from 2.9 mm to 2.1 mm against an
unchanged 2.0 minimum moves no claim at all — two green reports and one
important trend. `partspec diff` is what sees that, and it needs a **baseline**,
which `check` does not keep for you.

Note which edit this is. The `PLATE` change above moves a claim, so the pin
catches it. Change the **model's** numbers instead — `BORE_D` from 8.0 to 12.0,
a bore half again as wide, every declared claim still satisfied:

```console
$ partspec check examples/spacer/spec.py:spacer --out o --quiet
$ cp o/report.json baseline.json     # check overwrites o/report.json every run
# ... now edit BORE_D: 8.0 -> 12.0 ...
$ partspec check examples/spacer/spec.py:spacer --expect examples/spacer/claims.lock --quiet
$ echo $?
0                                    # green: not one claim moved
$ partspec check examples/spacer/spec.py:spacer --out o --quiet
$ partspec diff baseline.json o/report.json > drift.json
different: example-spacer — 2 drifted; contract module edited: the digest moved — module-scoped, so it over-fires and is never by itself a difference
  covered: source closure (1 file)
$ echo $?
1
```

The redirect is not decoration. `diff` writes its **artifact** to stdout because
that is the product and it pipes; the two lines above are the courtesy summary,
and they are on stderr. The clause after the semicolon is the edit you just made:
`BORE_D` lives in the contract module, so its digest moved. That digest is
module-scoped and never by itself a difference — the exit 1 is the drift, not the
edit. Both `drifted` entries in `drift.json` are still `pass`
— they are the two `requires`, whose captured operands moved with the bore:

```json
{"id": "bore_d_gt_0", "kind": "requires", "change": "drifted", "status": "pass",
 "operands": {"old": {"bore_d": 8.0}, "new": {"bore_d": 12.0}}}
```

That is the division of labour: the pin refuses a changed *question*, `diff`
reports a changed *answer*, and neither substitutes for the other.

Without the `cp`, the second run has already destroyed the only baseline the
first produced — and `outputs/` is gitignored at every depth, so the default
disposition of a report is "overwritten, then untracked". `docs/SPEC-diff.md` §1
and `docs/AGENT-CONTRACT.md` §4 state the rule; this is the worked copy of it.

## The point of the exercise

Read `spec.py` and note what is *not* in it: no assertion that the file exists,
no check that OpenSCAD ran, no test that the export is non-empty. `builds` is
implicit and always present, so those are the tool's job, not the author's. What
is left is engineering intent — the numbers a reviewer would ask about.

Then run `partspec measure examples/spacer/spec.py:spacer` and compare. `measure`
reports everything the tier can answer; the contract asserts the subset that is
*intent*. Deciding which numbers are intent is the whole skill, and
`skills/contract-authoring/SKILL.md` is the guide to it.
