# Clearance — part-versus-part interference, one part at a time

partspec's unit of verification is the single part, and stays that way through
v1.0 (D19). An assembly verb that takes N parts at their poses and reports
pairwise shared volume is a post-1.0 question (`SPEC-contract.md` §9).

This example is the pattern that does that work today: model
`intersection() { A; B; }` **at assembly pose** as a part of its own, and claim
the outcome the design intends.

## The two outcomes that are portable

Every pair of parts in an assembly is in exactly one of three states, and each
one grades on a different measurand. **Two of the three answer the same way on
every engine. This example declares those two**, and measures the third below
rather than recommending it:

| the two parts | the probe builds to | the claim | measured here |
|---|---|---|---|
| interpenetrate | a solid | `p.volume(min=, max=)` | 24.0 mm³ |
| stand off by a stated amount | nothing | `p.empty()` over a **grown** part | pass |
| touch on a face | a sheet | `p.area(min=)` | **kernel-dependent — see below** |

Run them:

```
$ partspec check examples/clearance/spec.py:interference
  ok   builds
  ok   volume
  ok   solid_count

PASS: 3 pass · not rendered
  every dimensional limit on 'clearance-interference' is unattributed: …

$ partspec check examples/clearance/spec.py:clearance
  ok   builds
  ok   empty

PASS: 2 pass
  hint: Current top level object is empty.
```

Both exit 0. The interference probe's limits come off this example's own
drawing rather than a standard, so §10's attribution warning fires and is
correct — it is elided above for width, not omitted.

## Grow the part you are clearing

`intersection() { lid(); post(); }` declared `empty()` says the lid and the post
do not **interpenetrate**. It says nothing about how much room is between them:
it is equally empty at 9 mm of standoff, at 0.01 mm, and at exact contact on the
engine that drops a zero-thickness sheet. A clearance is a number, and that
probe carries none.

So the probe intersects the lid against `post_envelope()` — the post grown by
the standoff the fit requires:

```openscad
CLEAR = 1.5;           // required standoff, lid to post, per fit

module post_envelope() {
    translate(POST_AT - [CLEAR, CLEAR, CLEAR]) cube(POST + 2 * [CLEAR, CLEAR, CLEAR]);
}
```

Now `empty` is a numeric claim — *nothing comes within 1.5 mm of the post* — and
a violation of it *with any margin* is a **solid with positive volume** rather
than a sheet, which every kernel agrees about down to its own floor (§4.12).

**Design the gap strictly greater than `CLEAR`, and here is why.** Growing
relocates the degenerate case onto `gap == CLEAR`; it does not remove it. At
exactly the clearance the probe is a zero-thickness sheet — the same artifact
this README condemns as non-portable further down — and the two pinned engines
disagree about it:

| design gap, `CLEAR` = 1.5 | 2021.01 | 2026.08.01 |
|---|---|---|
| 1.6 mm | exit 0 | exit 0 |
| **1.5 mm — exactly `CLEAR`** | **exit 1** (284-byte sheet, "may not be a valid 2-manifold") | **exit 0** (exports nothing) |
| 1.49 mm | exit 1 | exit 1 |

Only exact equality is degenerate — but it is precisely the value a designer
lands on who designs *to* the requirement rather than above it. So the assembly
leaves **2.0 mm against a required 1.5 mm**: that 0.5 mm margin is load-bearing,
not a round number picked for looks.

**The box grow measures Chebyshev distance, not Euclidean.** Growing an
axis-aligned box by `CLEAR` on every axis strictly contains the true offset, so
the error is false FAIL only — never false PASS — and both engines agree, so it
is not F13. Measured: a body whose nearest corner sits 1.2 mm away on each axis
is 2.0785 mm away in a straight line and still fails a 1.5 mm requirement, on
both engines.

If the fit cares about the straight-line distance, grow with `minkowski()` and a
sphere. Use this form, and copy it whole:

```openscad
CLEAR = 1.5;   // the standoff the fit requires, mm
SEG   = 32;    // one name for the radius AND the facet count
sphere(r = CLEAR / pow(cos(180 / SEG), 2), $fn = SEG);
```

**Why a named `SEG` rather than `$fn` in the radius.** OpenSCAD evaluates a
module call's arguments in the *caller's* scope, so `$fn = 32` in the argument
list takes effect inside `sphere` and **not** in the sibling `r =` expression
beside it. Written `pow(cos(180 / $fn), 2), $fn = 32`, the radius therefore reads
the caller's `$fn` — 0 by default — giving `180 / 0 = inf`, `cos(inf) = nan` and
a radius of `nan`. The engines then disagree about the wreckage: measured, that
envelope reaches 1.507257 on 2021.01 and **nothing at all on 2026.08.01**, where
`minkowski()` returns the bare ungrown part. The probe then passes a **0.1 mm**
gap against a 1.5 mm requirement on 2026.08.01, silently, exit 0. `SEG` is an
ordinary variable, so it means the same thing in both places.

Measured in the five shapes a reader is likely to put it in — top level, inside a
module, with a global `$fn` of 64, with a global `$fn` of 8, and with `$fa`/`$fs`
set and no `$fn` — the `SEG` form gives an **identical envelope in all five, on
both engines** (1148 facets, reach 1.507257). `SEG` governs the radius and the
facet count together, so nothing in the caller's scope can pull them apart.

OpenSCAD's `sphere()` puts its vertices *on* the ideal ball, so it is inscribed
and the envelope falls short of the true offset. It is faceted in **two** angular
directions, so the shortfall goes as `cos²`, not `cos` — and the axial direction
is not the worst one, so checking a single axis will not show it. Measured from
the exported ball on both engines, `CLEAR` = 1.5, `SEG` = 32:

| grow (all with `$fn = SEG`) | guaranteed offset (min face plane) | max offset (vertex) |
|---|---|---|
| `sphere(r = CLEAR)` | 1.485589 | 1.500000 |
| `sphere(r = CLEAR / cos(180 / SEG))` | 1.492777 | 1.507258 |
| **`sphere(r = CLEAR / pow(cos(180 / SEG), 2))`** | **1.500000** | 1.514551 |

Only the third reaches the required 1.5 in every direction, and it does so
exactly at `SEG` = 8, 16 and 32. Against a body approaching along the sphere's
worst direction, both engines: the first two **pass** real violations at 1.495 mm
and 1.499 mm; the third fails both and passes at 1.520 mm. The bare shortfall is
0.057090 mm at `SEG = 16`, inside a printed fit's tolerance.

Compensated by `cos²` with `SEG` named, the leftover error is one-sided toward
false FAIL — out to the vertex column above — which is the same safe direction
the box grow has. The bare and `cos` forms are one-sided toward false **PASS**.

Measured, by dropping the lid to a 1.0 mm standoff and running both probes on
both pinned engines:

| probe at 1.0 mm standoff | 2021.01 | 2026.08.01 |
|---|---|---|
| `lid() ∩ post_envelope()` — grown | **exit 1**, `empty` fails, 31.5 mm³ | **exit 1**, `empty` fails, 31.5 mm³ |
| `lid() ∩ post()` — ungrown | exit 0, `empty` **passes** | exit 0, `empty` **passes** |

Both engines agree in both rows, and the ungrown probe passes a standoff that is
a third of what the fit requires. That is the whole reason to grow.

**Where the number lives.** `empty` carries no bound, so unlike the volume band
on the interference probe, `CLEAR` lives in `assembly.scad` and not in the
contract. That is the cost of grading a clearance with the check that has
nothing to grade; the contract's docstring names it rather than hiding it.

**The interference probe is not grown, and does not need to be.** Its claim is
already a numeric band on positive volume — 0.1 to 0.3 mm of crush over a
20 × 6 mm flank, so 12.0 to 36.0 mm³ — and it measures 24.0 mm³ on both engines.
Growing has nothing to add to a claim whose violation already has volume.

## What the files are for

- **`assembly.scad`** — the parts, each at the pose it occupies in the product.
  Poses live here so that an interference number is the *assembly's* interference
  rather than a number about geometry sitting at the origin. Move a part by
  editing this file and every probe follows it. `post_envelope()` lives here too,
  for the same reason: it is placed geometry.
- **`interference.scad`**, **`clearance.scad`** — one probe each, both of them
  two module calls inside an `intersection()`.
- **`spec.py`** — the two contracts.

## What will bite

**`empty` is for the probe that should be empty, and for nothing else.** On the
interference probe an empty build is the *loose joint* — the failure — so that
contract deliberately does not declare `empty` and fails its build if the
flanks ever stop touching. And declare `empty` alone: an empty part has no
mesh, so every other geometry check on it is skipped (§4.12).

**`partspec lint` flags both probes, and the finding is correct.**

```
$ partspec lint examples/clearance/clearance.scad examples/clearance/interference.scad
  csg-two-part-intersection  examples/clearance/clearance.scad:0     the whole file is an
    intersection of two parts — … To assert a numeric clearance, intersect against a part
    grown by it … If this intersection is how the part is BUILT rather than a probe, the
    finding does not apply (LINT.md)
  csg-two-part-intersection  examples/clearance/interference.scad:0  … (the same message)
$ echo $?
0
```

(One finding per file, wrapped and elided here; the JSON payload on stdout
carries them in full.)

**Expect this, and do not try to author it away.** The rule's predicate is the
**shape** — one top-level node, an `intersection()` of exactly two children — and
every part-versus-part probe has that shape by construction, grown or not. Three
spellings of "grown by the clearance" were measured against it (an enlarged
module, a `minkowski()`, a `hull()` sweep) and all three still match, on both
pinned engines. The remedy makes the *claim* numeric; it was never a way to
silence the finding.

The finding is advisory, exits 0, and is a statement about the source rather than
a verdict on the part — `LINT.md`'s "Known noise, owned" paragraph under
`csg-two-part-intersection` is where that standing is set out. Read it, satisfy
yourself that the clearance you mean is the clearance you wrote, and accept it:
on `clearance.scad` its own advice is already taken, and on `interference.scad`
the claim is a volume band whose violation has volume anyway.

`tests/test_lint.py` pins these two files by name, so the repo notices a *third*
`.scad` joining them.

## What the pattern costs

One extra source and one extra target per pair, the pair modelled at assembly
pose, a grown module for every clearance you want stated numerically, and no
automatic all-pairs sweep — you write the pairs you care about. That is the
whole of it; #236 is the issue that measured it.

## The third outcome, and why it is not here

**Face contact is not portable, and it is the only one of the three that is
not.** A probe of two parts that merely touch is a zero-thickness result, and
what an engine does with one is a property of its kernel rather than of the
design. `assembly.scad` still carries `cover()`, seated flat on the rail, so
the case has a referent — but no contract claims it.

Two pinned engines, one source, opposite answers. `intersection()` of two 10 mm
cubes at three offsets, exported with `--export-format binstl`, then the same
three sources through `partspec check` declaring `p.empty()`:

| probe | 2021.01 export | 2026.08.01 export | `check` 2021.01 | `check` 2026.08.01 |
|---|---|---|---|---|
| interpenetrate (offset 5) | rc 0, 684 B | rc 0, 684 B | exit 1 | exit 1 |
| **touch on a face (offset 10)** | rc 0, **284 B** | rc 1, **0 B** | **exit 1** | **exit 0** |
| share no space (offset 20) | rc 1, 0 B | rc 1, 0 B | exit 0 | exit 0 |

One source, two engines, opposite verdicts — [F13](../../docs/FAILURE-MODES.md),
on the very pattern this example teaches. And the older engine is the one that
is *wrong*: under the settled semantics of `empty` (#270) it means **no
positive-volume interference**, a zero-thickness contact has no positive volume,
and so it should pass. 2026.08.01 gives the semantically correct answer, which
is why the divergence cannot be resolved by preferring the richer result.

The seated face in **this** assembly diverges a third way, which is worse than
either: both engines write a 4-triangle sheet, and they do not agree on its
shape.

| | `rail() ∩ cover()` corners | `area` |
|---|---|---|
| 2021.01 | (2, 0), (18, 0), (18, 12), (2, 12) — the 16 × 12 rectangle | 384.0 mm² |
| 2026.08.01 | (2, 0), (18, 6.6), (18, 12), (2, 11.4) — a skewed quad | 268.8 mm² |

So the newer engine does not always *drop* a zero-thickness result; here it
retains a degenerate one and reports a number no reader would question. That is
the failure this project exists to refuse, arriving through the geometry rather
than through the contract.

**What would make face contact expressible.** #314 — recording whether the
kernel retains a zero-thickness result — is the enabler. Once a run can state
which behaviour was in force, an `area` claim over a contact patch means
something; before that it means whichever engine the CI image happens to
install. Until then, if you need bearing area, measure it on a part that has
thickness: give the seat a deliberate interference and grade the **volume**.

None of this narrows what #236 asked for. Its measured interferences — eight
numbers across six rows, 192,318 / 43,234 / 61,575 / 32,723 / 14,328 / 1,691 /
693 / 56.6 mm³ — are every one of them positive volume, and not one is face
contact. The two outcomes that ship portably cover every case that motivated
the report.
