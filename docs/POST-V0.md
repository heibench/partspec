# POST-V0 — the backlog, recorded now so v0 carries it

**Date:** 2026-08-02
**Why this exists:** D11 scopes v0 to parts only, but requires the v0 model to *carry*
assemblies rather than be retrofitted. Writing the backlog now is what makes that possible —
and it is also where the best ideas being absorbed from cad-khana live, so leaving them
unrecorded would quietly lose them.

Nothing here is scheduled. This is a holding pen, not a roadmap — and a holding pen for
what is **still withheld**, which is the only thing it is useful for. Sections whose
subject has since shipped are reduced to a pointer at the spec that now owns it, rather
than kept as struck-through archaeology: half this file had become a record of completed
work, in a document `README.md` sells as "what is still withheld and why". Assemblies (§1)
and printability (§6) are the substance now.

---

## 1. Assemblies — the largest item

Everything below is from [`notes/survey/03-cad-khana-absorption.md`][survey-absorption] and is deferred whole.
**Scheduling decision, 2026-08-07:** D19 places assemblies after v1.0 — the v1.0 budget
goes to part-level depth of intent. This section is the design basis for when they begin.

**The design constraints v0 must honour to keep this cheap** (all adopted at no cost, per
`SPEC-contract.md` §9): `checks[].id` is a free-form string so dotted paths fit; every check
would record `part_refs` (carried in v0, never serialised, removed in v0.7.0 — additive
re-introduction is what §7.1 is for); and `skipped` already means
*"absence is a legitimate run state, not an input error"*, which is exactly what a
standalone sub-assembly run needs.

**What lands with assemblies:**

- **`qualified()` propagation** — a sub-assembly declares a claim once, at the level that
  owns the knowledge; composing it into a parent re-frames it automatically. The best single
  idea in cad-khana, and the one most worth getting right.
- **Anchors as cross-unit interface contracts** — each unit exports where it *believes* a
  shared datum is, in its own frame; the parent asserts the beliefs coincide after
  placement. Replaces mirror-constant + drift-assert pairs.
- **Relational checks** — `clearance`, `interference`, `tangent_contact`, `allowed_contact`,
  `expected_interference`. These were briefly listed as v0 in [`notes/survey/DIRECTION.md`][survey-direction] §5 because they
  are capability-portable; that was a category error (they take two bodies). The portability
  finding stands: `manifold3d.min_gap` returned exactly 7.5, and intersection volume was
  exact on both tiers.
- **`JointWindow` phase gating** — an allowed contact valid only during a joint-angle
  window, gated on **joint angle rather than animation `t`**, so re-timing cannot invalidate
  a claim. Outside its window it collapses to no-interference rather than going blind.
- **`drop_contact_shadowed`** — order-free contradiction resolution: a group-expanded
  `NoInterference` yields to a hand-declared `AllowedContact` on the same pair, but a
  hand-written one never does — *"that contradiction is yours to see."*
- **`sweep`** — `factory(t) -> Assembly` as the motion primitive, with bracket-then-bisect
  onset detection and the `angles_at_contact` (inner) vs `angles_bracketing` (outer) bound
  distinction.

**Known ceiling to design around:** cad-khana's interference is unconditional all-pairs OCCT
booleans, documented good to **~20 parts**. Fine for real assemblies; worth knowing before
someone points it at a machine.

**Also needs `Transform` and `Plane`** in the backend value types (`SPEC-backend.md` §2),
deliberately omitted from v0.

---

## 2. `diff` — SHIPPED

Shipped 2026-08-07 (#83). `SPEC-diff.md` owns the design, the outcome vocabulary and the
exit codes; `SPEC-report.md` §7.1 owns the silent-weakening argument that motivated it.


---

## 3. MCP server — SHIPPED

Shipped 2026-08-07/08 (#63, #66, #28; `vdiff` joined in #131). D18 owns the stateless
subprocess-per-call design; `AGENT-CONTRACT.md` owns how an agent drives it, including
which flags the MCP surface does *not* expose.


---

## 4. BREP-tier checks — SHIPPED

All six shipped between 2026-08-07 and 2026-08-09 and are specified in `SPEC-contract.md`
§4.5–§4.10: `hole_diameter` (#80), bolt circle (#81), `fillet_radius` (#82), `draft_angle`
(#137), `self_intersection_free` (#138), `step_roundtrip` (#139). All `unsupported` on
mesh, irreducibly — no conversion recovers them.

One prediction from this section is worth keeping because it failed twice and then came
true. These were expected to be the first checks to exercise the `approximate` machinery;
`hole_diameter` landed exact (a BREP cylinder's radius is a surface parameter, not an
estimate), and so did the next four. The obligation was discharged by `min_wall` (§5).

Still open here: a mesh-side self-intersection answer that is neither GPL (libigl/CGAL) nor
heavyweight (pymeshlab) — a dependency question (D14), not a design one.

---

## 5. `min_wall` — SHIPPED on the BREP tier

Shipped 2026-08-09 (#140); `SPEC-contract.md` §4.11 owns the measurand, the bound, the
five recorded escapes and the calibration. Two things belong here rather than there,
because they are backlog facts:

- **The mesh tier's refusal stands, with executed evidence.** Sampling is one-sided by
  construction — more samples can only ever find a *thinner* wall — so no principled `lo`
  exists there, and every erosion-style candidate was executed and refused. Shipping this
  on mesh needs a new method, not more effort.
- **cad-khana's `min_wall_alignment` was reconstructed and falsified**: a shallow taper
  measures alignment 0.995, indistinguishable from a slab, so the scalar cannot separate a
  wedge from a wall. The structural shared-edge rule replaces it.

This is also where §4's `approximate` obligation was discharged.

---

## 6. Printability

`overhang` is mesh-native and *better* on mesh than on BREP (per-triangle normals vs point
sampling), so it is cheap. Deferred only because printability is a different concern from
dimensional intent and would widen v0's story.

Also: trapped-volume detection by voxel flood-fill, and the commercial DFM advisories worth
reimplementing (*part too big*, *small gap <0.75 mm*, *thin wall*, *material left behind*).

**There is no open-source DFM check library to adopt** — slicers do no DFM at all, and
`dfm-checker`/`AMDFM` do not exist. PySLM (trimesh-based) is the closest reusable component.
That gap is a genuine opportunity if this project ever wants one.

---

## 7. Smaller items

- **`geometry.distinct_normals` on the OCCT tier** — currently mesh-only. Would need a deliberate
  tessellation, which is a design choice rather than a measurement.
- ~~**Per-component vector statuses** (`SPEC-report.md` Q8)~~ — shipped 2026-08-07 as
  `checks[].components` (#84).
- **`skipped` vs `unsupported` exit codes** (Q1) — currently share `2`; they differ in kind.
- **`--allow-incomplete`** — withheld deliberately, not forgotten. Add only if the dogfood
  run shows a case where `incomplete` is genuinely a part's right long-term state rather
  than a gap to close.
- **A benchmark suite** — the `journal-decision-engine` idiom (`gold-set.json`, `scorecard`,
  `just scorecard-diff baseline candidate`) is ready to reuse. Deliberately after dogfooding,
  which gives the same failure-mode information far more cheaply.
- **PartCAD as a parts source** — out of scope for v0 (D12), but its `interfaces:`/mating
  model remains the best existing prior art for declaring mechanical interfaces as data, and
  is the natural reference when assemblies land.

---

## 8. In-process batching — SHIPPED

Shipped with batch mode (#29). The normative rule is `SPEC-report.md` §6.2 (§5 rule 4 is the no-early-abort rule), and the
eviction machinery is `engines/pycad.py`'s module registry — whose two recorded ceilings
(a same-second same-length edit defeating CPython's pyc validation, and the registry's
refusal to sweep by directory) are the part worth remembering.

[survey-absorption]: https://github.com/heibench/partspec/blob/main/notes/survey/03-cad-khana-absorption.md
[survey-direction]: https://github.com/heibench/partspec/blob/main/notes/survey/DIRECTION.md
