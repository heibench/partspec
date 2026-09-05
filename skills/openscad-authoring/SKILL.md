---
name: openscad-authoring
description: Write OpenSCAD an agent loop can verify — parameterise, build from datums, decompose, pin $fn, overshoot booleans, and know the traps the dogfood corpus actually hit.
---

# Writing OpenSCAD that survives verification

The observed symptom this skill attacks ([`notes/GAPS.md`][gaps] A1–A7): agent-written OpenSCAD
is bloated, hardcoded, and structurally broken in ways that render fine. Every rule
below is concrete and checkable, carries a worked before/after, and cites the failure
it prevents in `docs/FAILURE-MODES.md`. The fenced examples are executed by
`tests/test_docs.py` — they build, and the after-forms satisfy what they claim.

## Rule 1 — Parameterise at the top; a magic number in geometry is unnameable

A `-D` override can only bind a **top-level variable** (a module-local assignment
shadows it). A `-D` whose name the file never declares is accepted without a whisper —
OpenSCAD just injects a top-level value that matters only if something happens to read
it — which is why partspec refuses any `-D` matching no declared top-level variable
(FAILURE-MODES entry 5).
A number buried in a call can never be overridden, checked by a `param` claim, or
named in a report.

```scad
// rule-1-before — nothing here can be driven or checked from outside
cube([60, 40, 4]);
```

```scad
// rule-1-after — every design decision has a name a contract can reach
plate_w = 60;
plate_d = 40;
plate_t = 4;

cube([plate_w, plate_d, plate_t]);
```

A parameter's *meaning* must match its name: `od_608 = 22.5` — a fit allowance baked
into a constant named for a nominal dimension — is entry 4 in the catalogue, found
twice in the corpus from two different authors.

## Rule 2 — First child of `difference()` is the material; everything after is removed

The single most destructive ordering trap, because the wrong order is not an error —
it is a *different part*. When anything at all survives the backwards subtraction,
OpenSCAD renders it happily at exit 0: a plausible mesh of the wrong thing. The one
variant the engine itself catches is the fully-empty result ("Current top level
object is empty.", exit 1, no STL) — do not count on being that lucky.

```scad
// rule-2-before — the cutter is the first child, so the PLATE is subtracted
// from the CUTTER. Fully empty here, which OpenSCAD refuses at export
// (exit 1); leave any sliver surviving and it renders fine, exit 0
difference() {
    translate([20, 15, 1]) cylinder(d = 6, h = 2, $fn = 48);
    cube([40, 30, 4]);
}
```

```scad
// rule-2-after — material first, removals after
plate_w = 40;
plate_d = 30;
plate_t = 4;
bore_d = 6;
facets = 48;  // rule 4: $fn is a named top-level parameter, like everything else

difference() {
    cube([plate_w, plate_d, plate_t]);
    translate([plate_w / 2, plate_d / 2, -1])
        cylinder(d = bore_d, h = plate_t + 2, $fn = facets);
}
```

partspec relays the empty-result refusal as a build failure; for the exit-0 variants —
a sliver of cutter rendered as if it were the part — only a `genus` / `solid_count` /
`envelope` claim proves the *right* subtraction happened.

## Rule 3 — Overshoot every cutter; never end a boolean on a coincident face

A cutter that stops exactly at a surface leaves coincident faces, and coincident
geometry is where render backends disagree: the corpus's 2,212-star library produced
**4 non-manifold edges under the default backend while OpenSCAD reported
`Status: NoError`** (FAILURE-MODES entry 2 — two shells touching along one plane). The
idiom is `-1` under, `+2` over, as in rule 2's after-form: start the cutter below the
material and end it above. The same rule applies to `union()`: solids that meet at a
face — and entry 2's evidence IS two shells touching under union — should overlap by a
small epsilon, not merely touch. Zero cost, removes the entire failure class from your
own booleans. (It cannot fix a library's internal coincidences — that is what
`p.watertight()` under both render backends is for.)

## Rule 4 — Pin `$fn` where curvature meets a claim

Under D15 the measurand is the artifact as exported: a `cylinder($fn=16)` **is** a
16-gon prism, and its bolt clearance is the apothem, not the radius
(`docs/SPEC-report.md` §1.1 — error always in the unsafe direction). Left unpinned,
tessellation follows the `$fa`/`$fs` defaults — so it varies with feature SIZE and
with the engine version, and a claim written against one part quietly measures
another. Pin it at the top, as a named parameter, sized to the claim:

```scad
// rule-4-before — facet count is whatever $fa/$fs resolve to for this size
cylinder(d = 6, h = 4);
```

```scad
// rule-4-after — the facet count is a named, driveable design decision
facets = 48;

cylinder(d = 6, h = 4, $fn = facets);
```

The claim-sizing precedent: the Ø22.5-seat finding (entry 4) pinned
`$fn=180` so a 0.003 mm polygon error could not be confused with the 0.5 mm
divergence under test.

## Rule 5 — Decompose into modules at feature boundaries, and locate from datums

A module per feature keeps every feature's parameters adjacent to its geometry, and
locating features from a named datum — not from accumulated `translate` chains —
means one design change moves one number.

```scad
// rule-5-after — features are modules, located from the plate's own frame
plate_w = 40;
plate_d = 30;
plate_t = 4;
bore_d = 6;
facets = 48;

module plate() {
    cube([plate_w, plate_d, plate_t]);
}

module bore(x, y) {
    translate([x, y, -1]) cylinder(d = bore_d, h = plate_t + 2, $fn = facets);
}

difference() {
    plate();
    bore(plate_w / 2, plate_d / 2);
}
```

Split a **file** when a module acquires its own parameter block that the rest of the
file never reads — and know that `include <>` files join the part's identity:
partspec's `source_closure` digests every file the render reads, because editing a
helper three levels down changes the part while the entry file's hash does not.

## Rule 6 — Prefer explicit geometry to `hull()` / `minkowski()` where a claim exists

Both are legitimate; both *manufacture* surfaces no parameter names, which makes the
result hard to claim (what is the envelope of a hull? whatever it turned out to be —
which is entry-4 territory the moment you measure it and assert the answer). Use them
for genuinely emergent shapes; for fillets and rounded plates whose radius is a
design parameter, model the radius explicitly so the number exists to check —
`minkowski` against a sphere also multiplies facet counts, which is a render-time
cost, not a correctness one.

## Rule 7 — Guard the loop count; `[1 : n]` at `n = 0` is engine-defined

`for (i = [1 : n])` is the ordinary way to place `n` features, and `n = 0` is an
ordinary thing a parameterised part does. It makes the range `[1 : 0]` — begin past
end, with an implied positive step — and the two engines this project pins do not
agree on what that means. With `n` arriving as a parameter, measured on both:

| `n` | 2021.01 | 2026.08.01 |
|---|---|---|
| `0` | iterates **ascending**, `i = 0` then `i = 1` — two features the source did not ask for | iterates nothing |
| `-1` | iterates `i = -1, 0, 1` — three | iterates nothing |
| `2` | two, as asked | two, as asked |

So the same source is a different part, which is the class of FAILURE-MODES entry 1.
`[0 : n - 1]` — the other common spelling — carries it identically: at `n = 0` its
`.csg` export holds two `multmatrix` nodes on 2021.01 and none on 2026.08.01.

**Do not count on being told.** 2021.01 does print `DEPRECATED: Using ranges of the
form [begin:end] with begin value greater than the end value is deprecated`, on every
shape measured — but it is not one of the lines partspec reads off a render that
succeeded, and `build_stderr` is `null` in the report either way (measured on this
part under both engines), so it reaches neither the guard nor a reader of the report.
2026.08.01 does not print it at all here: it warns only when the range is a
**literal** — `[1 : 0]` written out draws `WARNING: begin is greater than the end, but
step is positive` — and is silent when the same range arrives through a variable or a
module parameter, which is the only way a count falls to zero.

```scad
// rule-7-before — stud_n = 0 makes this `[1 : 0]`; 2021.01 builds two studs
rail_l = 40;
rail_w = 8;
rail_t = 6;
stud = [6, 8, 4];
stud_pitch = 8;
stud_n = 0;
eps = 0.01;  // rule 3: the stud overlaps the rail, it does not sit on it

cube([rail_l, rail_w, rail_t]);
for (i = [1 : stud_n])
    translate([i * stud_pitch, 0, rail_t - eps]) cube(stud);
```

```scad
// rule-7-after — the empty case is a branch in the source, not a property of
// range semantics: 12 triangles on both engines at stud_n = 0 and at -1,
// 44 on both at stud_n = 2
rail_l = 40;
rail_w = 8;
rail_t = 6;
stud = [6, 8, 4];
stud_pitch = 8;
stud_n = 0;
eps = 0.01;

cube([rail_l, rail_w, rail_t]);
if (stud_n > 0)
    for (i = [1 : stud_n])
        translate([i * stud_pitch, 0, rail_t - eps]) cube(stud);
```

The three-argument form `[1 : 1 : n]` also agrees on both engines — measured, same
triangle counts as the guarded form at `n = -1`, `0` and `2`. Prefer the `if` anyway:
it states "no studs" where a reader sees it, and it does not depend on the reader
knowing that adding an explicit step changes the semantics of a range that already
had one.

**An ordinary contract does catch this**, which is the point of pinning the binary.
A two-sided `envelope` on the `n = 0` part — `min=(40, 8, 5.9)`, `max=(40, 8, 6.1)` —
run against the before-form:

```
2021.01     FAIL envelope — z=9.98999977 outside min=5.9 and max=6.1     exit 1
2026.08.01  ok   envelope ... PASS: 4 pass                               exit 0
```

`watertight` and `solid_count` pass on both, so the envelope is the only check that
moves. Write the bound two-sided and from theory, run under both pinned binaries, and
the engine that builds the wrong part is the one that fails.

## Rule 8 — An `undef` that reaches a dimension is silent; test it or default it

`undef` is the language's own spelling of "not supplied", and using it as a parameter
default is ordinary OpenSCAD — BOSL2 and most libraries do. What is not ordinary is
letting one **reach geometry untested**, because the engine then substitutes a default
of its own and tells you nothing. Measured on both pinned engines, each source prefixed
`o = undef;` and rendered `--export-format binstl`:

| source | stderr, both engines | exit | mesh |
|---|---|---|---|
| `cube(o);` / `cube(size=o);` | *(nothing)* | 0 | 12 facets — a 1 mm cube |
| `linear_extrude(o) square([40,30]);` | *(nothing)* | 0 | 12 facets — **100 mm tall** |
| `cylinder(h=o, d=10);` | *(nothing)* | 0 | 60 facets — h = 1 |
| `sphere(o);` | *(nothing)* | 0 | 26 facets — r = 1 |
| `resize(o) cube(5);` | *(nothing)* | 0 | 12 facets — a **no-op**, the 5 mm cube |
| `cube(o + 1);` | `WARNING: undefined operation (undefined + number)` | 0 | 12 facets |

Every one exits 0 with a clean, watertight, single solid; in every row but `resize` it
is built to a number nobody wrote down. `resize(undef)` instead does nothing at all —
measured (5, 5, 5) on both engines — which is the same silence delivering a different
shape of wrong. The two engines agree, so a second binary does not catch this the way it catches
rule 7. Only `circle(r=o)` is refused, and only because a 2D result cannot be exported
to STL at all (exit 1, no file, both engines).

**Do not count on the warning either.** The `undefined operation` line in the last row
appears only because of the `+`, it fires beside completely correct parts
(`echo("holes: " + holes)` prints it), and partspec deliberately does **not** guard on
it — that was tried and reverted (PR #306). The `.csg` export cannot see the fault
either: `o = undef; cube(o);` exports **byte-identical** to `cube(1);` on both engines,
as do the `linear_extrude`, `cylinder` and `sphere` rows against their correct
counterparts. `partspec lint`'s `scad-untested-undef` is the one thing that says it out
loud, and it is advisory (`docs/LINT.md`).

```scad
// rule-8-before — `t` is never supplied and never tested, so linear_extrude()
// takes its own default: a 40 x 30 x 100 part, silent, exit 0
plate_w = 40;
plate_d = 30;

module plate(t = undef) {
    linear_extrude(t) square([plate_w, plate_d]);
}

plate();
```

```scad
// rule-8-after — the default is a real number a -D can drive and a contract
// can name; 40 x 30 x 6 on both engines
plate_w = 40;
plate_d = 30;
plate_t = 6;

module plate(t = plate_t) {
    linear_extrude(t) square([plate_w, plate_d]);
}

plate();
```

Where the value genuinely may be absent, **test it** — `is_undef(t)`, `t == undef`, or a
narrower `is_num(t)` — and supply the fallback in the source, not in the engine's head.
That is also what `scad-untested-undef` looks for, so a guarded optional parameter lints
clean.

**Assert the dimension in the contract.** A contract whose only geometry claims are
`watertight()` and `solid_count()` cannot catch any of this, because it asserts no
dimension — and that is the contract every reproduction above was built on. Adding one
`envelope` moves them, measured on both engines:

| part | `envelope(max=(40,30,6))` | `envelope(min=max=(40,8,10))` |
|---|---|---|
| `linear_extrude(undef)` — rule-8-before's shape | **FAIL, exit 1** | — |
| a range that would not convert, `[0:undef][2]` | **FAIL, exit 1** | — |
| a loop whose count went `undef` — geometry gone | PASS, exit 0 | **FAIL, exit 1** |
| the same loop at `n = 4` (correct) | — | PASS, exit 0 |

The third row is the one to take away, and it is rule 7's lesson again from the other
side: **a `max`-only envelope cannot catch geometry that disappeared**, because the part
got *smaller*. For anything a loop or an `if` builds, assert the lower bound too.

## The language moves — pin the binary, avoid removed constructs

`assign()` was removed, and modern OpenSCAD *ignores* unknown modules — their children
never render. A gear library lost its teeth to exactly this, both versions exiting 0
with clean watertight meshes (FAILURE-MODES entry 1, the catalogue's opening case).
Never use deprecated constructs; pin the engine with `PARTSPEC_OPENSCAD`; and write
the envelope claim from theory so the version that breaks the part fails the check.

---

Contract-side guidance is `skills/contract-authoring/SKILL.md`; the evidence base is
`docs/FAILURE-MODES.md`; worked parts are under `examples/` (the `enclosure` and
`bearing-block` exemplars are OpenSCAD).

**This skill is OpenSCAD-only.** If the source you are writing is build123d or CadQuery,
none of the rules above transfer — those engines fail by silent *selection* drift and
ecosystem breakage rather than by silent geometry loss. Load
`skills/build123d-authoring/SKILL.md` instead.

[gaps]: https://github.com/heibench/partspec/blob/main/notes/GAPS.md
