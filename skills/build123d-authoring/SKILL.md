---
name: build123d-authoring
description: Write build123d and CadQuery a verification loop can drive — factory shape, algebra over builders for parts, selector discipline, the adapter pattern for community code, and the version hazards F8 recorded.
---

# Writing build123d / CadQuery that survives verification

The Python engines fail differently from OpenSCAD: less silent geometry loss, more
silent *selection* drift and ecosystem breakage. Every rule cites its evidence; the
fenced examples are executed by `tests/test_docs.py`.

## Rule 1 — Ship a factory, not a script

partspec calls a model as `method(**params)` — deliberately dumb, no signature
inspection (`src/partspec/engines/pycad.py`, the module docstring is the rule's home). The community norm is the opposite: module-level
constants ending in `show(...)` (F8 — `docs/FAILURE-MODES.md` entry 8). A script
runs once at import with one set of numbers; a factory is a *family*.

```python
# bd-rule-1-after — a parameterised factory, defaults stated, shape returned
from build123d import Align, Box, Cylinder, Location


def make_part(plate_w: float = 40.0, plate_d: float = 30.0, plate_t: float = 4.0,
              bore_d: float = 6.0):
    plate = Box(plate_w, plate_d, plate_t, align=(Align.MIN, Align.MIN, Align.MIN))
    bore = Location((plate_w / 2, plate_d / 2, -1)) * Cylinder(
        bore_d / 2, plate_t + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)
    )
    return plate - bore
```

The `-1` / `+2` cutter overshoot carries over from the OpenSCAD skill's rule 3 — not
because OCCT needs it (executed: an exactly-flush bore booleaned bit-identically to an
overshot one), but for cross-tier consistency and as free insurance on tangency-rich
geometry. A model written with overshoot renders the same part on every tier.

## Rule 2 — The adapter pattern: three lines beat a rewrite

Community code that is a class, a script, or a differently-shaped function gets a
small explicit adapter in the *contract's* module — never a rewrite of the model, and
never a partspec feature (a tool that guessed calling conventions would be worse,
F8's accepted trade):

```python
# bd-rule-2-after — adapt a class-shaped community model to method(**params)
def make_part(units_wide: int = 2, units_deep: int = 1):
    from cq_gridfinity_like import GridfinityBox  # the community class, untouched

    return GridfinityBox(units_wide, units_deep, 3).render()
```

## Rule 3 — Selectors are position-dependent; prefer named geometry

The classic silent breaker: a selector that matches the *wrong* face still builds.
`faces(">Z")` (CadQuery's string selector; build123d spells it
`sort_by(Axis.Z)[-1]`) means "whatever is topmost *now*" — add a taller feature and
every downstream operation silently moves to it. Prefer keeping references to the geometry
you made (algebra mode hands you the objects) — and finish a feature BEFORE fusing it:
after `body = plate + boss`, chamfering `boss`'s own edges succeeds on the standalone
pre-fusion copy and leaves `body` untouched, the works-but-wrong-part trap again; where a selector is unavoidable,
select by property (`filter_by`, radius, axis) rather than by extremum, and pin the
result with a claim the contract can check (`hole_diameter`, `keep_out`, envelope) so
a drifted selection fails loudly instead of shipping.

```python
# bd-rule-3-before — the chamfer follows ">Z", not the designer's intent
from build123d import Align, Box, chamfer


def make_part(boss_h: float = 0.0):
    plate = Box(40, 30, 4, align=(Align.MIN, Align.MIN, Align.MIN))
    if boss_h:
        plate += Box(10, 10, 4 + boss_h, align=(Align.MIN, Align.MIN, Align.MIN))
    top = plate.faces().sort_by()[-1]  # ">Z": today the plate top, tomorrow the boss
    return chamfer(top.edges(), length=0.5)
```

With `boss_h=0` the plate's rim is chamfered; with `boss_h=2` the same code chamfers
the *boss* top instead — both build, both are watertight, and only a measurement
(the chamfered rim's effect on `area`/`volume`, or a `keep_out` at the rim) tells
them apart. That is FAILURE-MODES' shared moral wearing OCCT clothes.

## Rule 4 — Builder and algebra modes: pick per part, don't mix per line

Algebra mode (`Box(...) - Cylinder(...)`) keeps every intermediate in a named
variable — testable, selector-free, the right default for parts a loop verifies.
Builder mode (`with BuildPart() ...`) shines for sketch-then-extrude workflows and
implicit face bookkeeping; if you use it, extrude from *sketches on named planes*
rather than chaining selectors. Both produce the same OCCT solids; the contract
cannot tell which you used, which is the point — pick for maintainability.

## Rule 5 — CadQuery is the same kernel with different handles

One OCCT backend serves both engines through the `.wrapped` adopt shim (D3): a
CadQuery `Workplane` is reduced over its **whole stack**, anything exposing
`.wrapped` is rewrapped by shape type, nothing is converted. Consequences worth
knowing before they bite:

- `combine=False` leaves separate solids on the stack; partspec compounds **all** of
  them — but `.val()` in your own code keeps only the first (`engines/pycad.py`
  records the measured case: 4 boxes, `.val().Volume()` = a quarter of the part).
- A contract written against the build123d leg runs unchanged against a CadQuery
  model — `tests/test_bores.py::test_the_same_hole_contract_holds_on_cadquery` is
  that parity, executed. (Cross-ENGINE parity generally: `examples/bearing-block/`
  and `tests/test_differential.py`, whose two engines are OpenSCAD and build123d.)

The factory shape is the same on the CadQuery side, string selectors and all — which
is exactly why rule 3's discipline matters doubly here:

```python
# bd-rule-5-after — the same factory shape, CadQuery handles
import cadquery as cq


def make_part(plate_w: float = 40.0, plate_d: float = 30.0, plate_t: float = 4.0,
              bore_d: float = 6.0):
    return (
        cq.Workplane("XY")
        .box(plate_w, plate_d, plate_t)
        .faces(">Z")
        .workplane()
        .hole(bore_d)
    )
```

## Rule 6 — The ecosystem moves under you; pin and adapt

F8's two hazards, verbatim from the corpus: a 96-star community library that does
not import on build123d 0.11.1 (`ShapePredicate` no longer exists — libraries are
pinned to the build123d of their writing), and the OCP packaging landmine
(FAILURE-MODES entry 7: two providers own one `OCP/` package; `just ocp-guard`
asserts exactly one). Pin your engine versions in your project's lockfile, treat a
community model as *frozen at its version* behind an adapter (rule 2), and let the
report's `environment.packages` say which versions actually measured the part.

---

Contract-side guidance: `skills/contract-authoring/SKILL.md`. Source-side OpenSCAD:
`skills/openscad-authoring/SKILL.md`. Evidence: `docs/FAILURE-MODES.md` entries 7–8;
worked parts: `examples/stepper-bracket/` (build123d), `examples/bearing-block/`
(both engines), in the repository rather than an install, under
[https://github.com/heibench/partspec/tree/main/examples](https://github.com/heibench/partspec/tree/main/examples).
