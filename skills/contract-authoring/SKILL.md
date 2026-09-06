---
name: contract-authoring
description: Write a partspec contract that proves something — how to choose checks, where limits may come from, and the retrofit path for an existing part.
---

# Writing a contract that proves something

A contract is the whole interface: `partspec` evaluates exactly what you declare, and a
run is only as meaningful as the claims are. The one rule everything below serves —
promoted from the dogfood evidence (`docs/PLAN.md`, "the load-bearing qualification"):

> **Geometry is verifiable, but only against a reference the model does not contain** —
> a standard, a datasheet, a derivation, or an invariant.

That sentence is `docs/PLAN.md`'s; the evidence behind it, synthesised: every payoff in
the dogfood record came from such a claim, and a "unit test" asserting what the model
produced last time would have passed on every broken part in `docs/FAILURE-MODES.md`,
because each was a faithful render of its own source.

This is also why `partspec measure` will never write checks for you
(`SPEC-contract.md` §6): a check generated from the part's own output is a check nobody
decided, asserting that the model matches itself.

## 1. Choosing checks — the decision table

Navigate by what you need to prove; the kind vocabulary itself is normative in
`SPEC-contract.md` §4.1–4.11 (do not learn it from here — this table only routes you).

| you need to prove | reach for | notes |
|---|---|---|
| the declared inputs are mutually sane | `p.param` / `p.requires` (§4.1) | runs before any engine; milliseconds |
| the part fits / fills a space | `p.envelope`, `p.keep_out`, `p.keep_in` (§4.2, §4.4) | both tiers, exact — the region kinds take a spelled-out `axis="z"`, never a vector; worked call below |
| the part is one sound solid | `p.watertight`, `p.solid_count` (§4.2) | both tiers |
| through-holes exist — and stay holes | `p.genus` (§4.2) | genus sees through-holes only (a blind hole is genus 0 — route it to `hole_diameter` or `keep_out`); a hole reaching the boundary is a notch — FAILURE-MODES entry 3 |
| a cavity is sealed | `p.cavities` (§4.2) | an open tray is also watertight, 1 solid, genus 0 |
| a drawing callout (bore Ø, bolt circle, fillet) | `p.hole_diameter`, `p.bolt_circle`, `p.fillet_radius` (§4.5–4.7) | OCCT tier; the mesh tier refuses honestly |
| the part can leave the mould | `p.draft_angle(min=, direction=)` (§4.8) | OCCT tier; exact on planes, cylinders and cones — a freeform face refuses the whole check |
| the shape does not cross itself | `p.self_intersection_free()` (§4.9) | OCCT tier; the kernel's own pairwise analysis, faults inventoried |
| the part survives its exchange format | `p.step_roundtrip(tol=)` (§4.10) | OCCT tier; topology drift fails at any tolerance |
| every wall is thick enough | `p.min_wall(min=)` (§4.11) | OCCT tier; a guaranteed interval — a limit inside it adjudicates `approximate`, never a guess |
| a whole interface standard | a fragment — `nema17.mount(p)`, `iso15.seat(p, n)`, `iso_metric_thread.tapped_hole(p, 3)` (§11) | one call, cited |
| material amount / wall drift over time | `p.volume`, `p.area` (§4.2) | drift shows in `diff` even while both runs pass |
| two parts do not interfere | `p.empty()` on an `intersection()` part (§4.12) | proves no positive-volume *interference* — NOT that they are separated. See below |

### An interference probe, and the clearance it cannot state

Build `intersection() { partA; partB; }` as its own part and the shared space becomes
something you can claim about. Two outcomes land the same way on every kernel:

| the two parts | what builds | grade it on |
|---|---|---|
| interpenetrate | a closed solid | `p.volume(max=...)` — the ordinary case |
| do not interfere | **nothing** | `p.empty()` (§4.12) |

A third outcome exists on **one** kernel only. Parts resting on a face give a
zero-thickness sheet, which `p.area(...)` measures — but only OpenSCAD's CGAL backend
keeps that sheet reliably. The OCCT tier never does. Manifold (current OpenSCAD's
default) cannot be predicted: there are pairs of solids whose intersection answers
differently when the intersection's two children are written in the other order, identical
geometry either way. So there *touching* and *clear* are usually the same signal and
`empty()` passes for either — and on the cases it keeps, `empty()` **fails** for a touching
pair whose interference is exactly zero.

Every kernel also has a floor beneath which a *real* interference is discarded and
`empty()` passes — OCCT below ~6e-7 mm of overlap depth, constant; OpenSCAD's depends on
the arrangement and has no characterised bound (#315). Sub-physical for real parts, and
the reason `empty()` is stated as "no interference **the kernel can represent**". **Do
not build a contract on the middle row unless you pin the kernel yourself.**

**`empty()` means no positive-volume interference — not "these parts do not touch", and
not "there is clearance."** To assert a clearance, state the number and let a violation
have volume: intersect against a part grown by the clearance rather than against the part
itself.

```openscad
intersection() { a(); b(); }              // "is there interference"
intersection() { a(); grown_b(0.5); }     // "is there 0.5 mm of clearance"
```

Declared with `empty()`, the second says *no part of `b`, plus 0.5 mm, meets `a`* — a
violation with any margin encloses volume rather than a sheet, so every kernel agrees
down to its own floor, and the bound sits in the
contract where a reviewer can see it. `partspec lint` flags the bare form advisorily on the OpenSCAD tier only
(`csg-two-part-intersection`; it reads the `.csg` export, so a build123d probe written
as `a & b` gets no finding). The bare claim is valid either way, just narrower than it
reads (#270).

`volume` is gated on a closed surface and a contact sheet is often not one: an annular
contact measured on 2021.01 exports 94 non-manifold edges, so the check reports `n/a`
and the run is `incomplete`. That refusal is right — integrating volume over an open
surface is meaningless — and `area` is ungated for the mirror reason, so it answers
where `volume` cannot. Declare `area` alone and the resting-on case passes cleanly — on a kernel that keeps the
sheet.

**The number is twice the contact patch.** Both sides of the sheet are exported, so a
10 x 10 mm face reads `200.0`, not `100.0`. Write the bound against the measured value or
against `2 x` your own arithmetic — never against the patch you computed by hand, because
both numbers look plausible and nothing will tell you which one you used.

### Regions, written out

A table row is not enough for these two: they are the only checks whose argument is a
shape you construct, and every worked contract in the tree went without one until #200.

```python
from partspec import region
from partspec.refs import nema17

# keep_out — this space must hold NO material. The motor's locating boss
# needs it clear, so the requirement is about volume rather than about a
# feature, and both tiers answer it. (`hole_diameter` would state the same
# interface as a bore, which the mesh tier refuses: a faceted hole has no
# diameter.)
p.keep_out(
    region.cylinder(d=nema17.PILOT_BOSS, h=2.0, at=(0.0, 0.0, 34.0), axis="y"),
    shell=0.6,
    id="pilot-boss-clearance",
)

# keep_in — this space must be ENTIRELY material. Here, an L-bracket's
# corner: TWO boxes, because the members are perpendicular slabs and one box
# needing material from both would also span the air outside the L.
p.keep_in(region.box(min=(-26.0, 0.5, 0.5), max=(26.0, 4.5, 12.0)), shell=1.0,
          id="joint-web-plate")   # up the plate, past where the base stops
p.keep_in(region.box(min=(-26.0, 0.5, 0.5), max=(26.0, 12.0, 4.5)), shell=1.0,
          id="joint-web-base")    # along the base, past where the plate stops
```

- **`axis` is one of the strings `"x"`, `"y"`, `"z"`.** Not `(0, 0, 1)`, which is
  refused — and which two fleet agents on different engines both reached for.
- **`at` is the centre of the cylinder's base**, in the model's own coordinates.
  Locate it off the datum the model uses, not off accumulated offsets.
- **`shell` is not optional thinking** — it is the anti-vacuity guard. An absent part
  has an empty region too, so `keep_out` pairs "no material here" with "material near
  here", and `keep_in` pairs the converse. Size it to a real clearance. Know when it
  cannot help, too: a `keep_in` rooted near the part's outer surface has a shell that
  escapes into free space, so it is never entirely solid and a solid brick passes it.
  Both `keep_in`s above are in that position; their work is done by the pair of them,
  and the brick is excluded by `envelope` and `solid_count`.
- **A region must reach where the claim is.** A single `keep_in` box that fits inside
  one feature is satisfied by that feature alone, whatever happened to the thing you
  meant to prove. Both ways of getting this wrong were shipped in drafts of the bracket
  example: a box inside the plate passed with the base cut away, and a box inside the
  base passed with no plate at all. The fix is not a bigger box — one cannot exist here
  — but the PAIR above, which is why each of them may sit inside a single member: what
  carries the claim is that between them they enter both. **Check by breaking the model
  and watching the check fail**, and check that the right one fails; that is the only
  way to know a region says what you think.
- **A region's DIMENSIONS carry their citation** into `checks[].source` — a box's
  `min`/`max`, a cylinder's `d`/`h`, and `shell` — so a keep-out sized from
  `partspec.refs` is attributed like any other bound (§10). A region's `at` does not:
  a standard vouches for how big a feature is, never for where your design puts it.

`examples/stepper-bracket/` is the worked part; its README explains each choice.

## 2. `param` vs `requires` vs geometry — a worked before/after

The spec's rule (§4.1): the structured form SHOULD be preferred when the claim is a
simple bound on one named parameter, because it produces a real measurement `diff` can
track drift on. `requires` is the escape hatch for anything relational.

```python
# Before — everything crammed into requires: no measurements, no attribution
p.requires("wall >= 0.8")
p.requires("bore_d > 0")
p.requires("bore_d + 2 * wall <= plate_y")

# After — structured where one parameter is bounded, relational where it is not
p.param("wall", min=0.8)          # a measurement: joins attribution, diff tracks it
p.param("bore_d", min=0.1)
p.requires("bore_d + 2 * wall <= plate_y")   # genuinely relational: stays requires
```

(To be precise about the asymmetry: `diff` DOES report operand drift on a
`requires` check — what the structured form adds is a real measurement with a limit,
which joins the report's `attribution` accounting and gives `diff` a value-with-bound
to track rather than raw operands.)

And know when NOT to reach for the parameter phase at all: a parameter claim proves the
*inputs*, never the geometry — F18 in `docs/FAILURE-MODES.md` (entry 5) is a green
report whose parameter never reached the geometry, which is why the unbound-`-D` guard
exists and why geometry claims must carry the weight.

## 3. Where may a limit come from?

In descending order of strength — and the report's `attribution` block discloses which
you used:

1. **A published standard, cited** — `iso15.bearing(608).od`,
   `iso_metric_thread.coarse(8).minor_internal`, `nema17.mount(p)`. The
   number arrives as a `Referenced` value and the citation lands in
   `checks[].source`. Never retype a standard's number; even the exemplar that
   preaches this shipped a transcription error until review computed it
   (`examples/stepper-bracket/bracket.py`).
2. **A derivation from theory** — the involute-gear envelope that caught F13 was
   `teeth × outside_circular_pitch / 180`, derived, not measured. Write the derivation in the contract.
3. **An invariant** — topology (`genus`, `solid_count`, `cavities`) needs no numbers at
   all and catches what visual review is worst at.
4. **The design's own parameters** — legitimate ONLY as a change-detector, and say so
   in a comment (`examples/stepper-bracket/spec.py` is the worked form). A contract
   with nothing but these proves the model matches itself; the console and the
   report's `attribution` block will tell you so (`SPEC-contract.md` §6, §10).

Arithmetic on a `Referenced` value sheds the citation deliberately — a derived number
is yours. Cite the un-derived bound.

## 4. The retrofit path — contracting a part you did not model

`partspec measure` exists for exactly this (`SPEC-contract.md` §7): it dumps every
quantity the backend can honestly produce, with no verdict, so you can see the numbers
*before* deciding which are intent.

1. **Write a contract that declares only the source, and measure that.** A `Part`
   with an id and a source and no checks at all is the smallest thing `measure`
   accepts, and it reads every quantity the backend can produce:

   ```python
   # probe.py
   from partspec import Part, openscad

   def probe() -> Part:
       return Part("probe", openscad("../vendor/bracket.scad"))
   ```

   `partspec measure probe.py:probe` — read what the part is. **Name the contract,
   never the model.** `measure` and `check` both resolve a target that must return a
   `partspec.Part`, so pointing either at the model file fails at exit 64; a
   build123d or CadQuery model annotated `-> Part` is returning *its* `Part`, not
   partspec's. The id is positional and required — `Part(source=...)` alone raises.
2. For each number, ask: **what fixes this?** A standard → cite it (path 1 above). A
   datasheet or drawing → its number, in a comment naming the source. Nothing → do not
   assert it yet; `examples/enclosure/` shows the honest topology-only position.
3. Declare the topology you know the design requires (the invariants survive
   re-parameterisation; the numbers often do not).
4. Only then bound dimensions — from the references you found in step 2, never by
   copying step 1's output into a limit. That copy is the auto-generation the tool
   refuses to do for you, done by hand.

## 5. Soundness checks assert no dimension, and that is the gap

`watertight()` and `solid_count(1)` are the two claims everyone writes first, and a
contract that stops there **cannot catch a part that came out the wrong size**. They
assert the mesh is sound, not that it is the part you meant. A dimension defaulted from
`undef` produces a clean, watertight, single-solid mesh at whatever size the engine
substituted, and that contract passes it (#308, #332).

Measured on both pinned engines, `o = undef; h = o + 1; linear_extrude(h) square([40,30]);`
— a plate that is 100 mm tall because a name was undefined:

| contract | verdict |
|---|---|
| `watertight()` + `solid_count(1)` | **exit 0** |
| the same, plus `envelope(max=(40,30,6))` | **exit 1** |

There is no guard coming for this. Every stderr and `.csg` signal that could refuse it
refuses correct parts too — `o=undef; cube(o)` and `cube(1)` export byte-identical `.csg`
files — so **the contract is the mechanism**, not a fallback for one. `partspec lint`
flags the source shape as `scad-untested-undef`, advisory only.

**Assert at least one dimension on every part.** An envelope is the cheapest; a `volume`
range does the same work when the outline is irregular.

### A one-sided envelope cannot catch geometry that vanished

`envelope(max=...)` catches a part that grew. It does nothing about a part that
**shrank**, and a loop or an `if` that silently produced nothing is exactly that case
(#338).

    module rail(n = undef) {
      cube([40, 8, 6]);
      for (i = [1 : n]) translate([i*8, 0, 6]) cube([6, 8, 4]);
    }

The loop contributes nothing when `n` is `undef`, and the part is a bare bar. Measured,
both engines:

| contract | `n = undef` | `n = 4` |
|---|---|---|
| `watertight()` + `solid_count(1)` | exit 0 | exit 0 |
| `envelope(max=(40,30,10))` | **exit 0** | exit 0 |
| `envelope(min=(40,8,10), max=(40,8,10))` | **exit 1** | exit 0 |

**For anything built by a loop, a comprehension or an `if`, assert a lower bound too.**
The upper bound alone says the part is not too big, which is not the failure that shape
has.

The OpenSCAD-side view of the same fault — which source shapes produce it, and how to
write them so they cannot — is `skills/openscad-authoring/SKILL.md` rule 8. This section
is the contract side, and it holds whatever engine the source declares: the Python tiers
have their own ways of building a sound mesh of the wrong thing.

## 6. Keep the loop honest

- Pin the claim set once (`partspec check spec.py:part --pin claims.lock`, lock
  committed), then run with `--expect claims.lock` from that point on — `--expect` is
  what fails a shrunk contract (exit 4, differences named); a plain `check`, or
  re-running `--pin`, verifies nothing and silently blesses the shrink. Re-pin only
  with review (`docs/AGENT-CONTRACT.md` §4).
- Shared claims across implementations assert **only what the requirement fixes**
  (FAILURE-MODES entry 6; `examples/bearing-block/claims.py` is the worked form).
- The source-side rules live in **two** skills, one per engine family — load the one
  matching the source your contract declares. `openscad(...)` →
  `skills/openscad-authoring/SKILL.md`. `build123d(...)` or `cadquery(...)` →
  `skills/build123d-authoring/SKILL.md`, which covers both: the Python engines fail
  by silent *selection* drift and ecosystem breakage rather than by silent geometry
  loss, so the OpenSCAD rules do not transfer.
- The worked exemplars under `examples/` are the imitation set: the exemplar
  READMEs (`stepper-bracket`, `bearing-block`, `enclosure`) each say what to copy and
  why.
