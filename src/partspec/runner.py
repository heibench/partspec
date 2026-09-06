"""Run a contract against a part and produce a report.

The phase order and its consequences are the whole of this module:

    parameter checks -> (short-circuit?) -> build -> geometry checks -> report

A failing parameter check stops the engine from running, because building
geometry from inputs already known to be invalid wastes time and produces a
shape whose measurements describe something the contract has already rejected.
The geometry checks then appear as `skipped` rather than vanishing — an absent
check is indistinguishable from one that was never declared, which is the
vacuous-green failure wearing a different hat.

Spec: SPEC-report.md sections 4, 5, 6; SPEC-contract.md sections 4, 6.
"""

from __future__ import annotations

import hashlib
import re
import sys
import time
from pathlib import Path
from typing import Any

from . import expr as expr_mod
from . import imports
from .backend import BuildError, Unsupported, effective_timeout
from .contract import GEOMETRY, GEOMETRY_KINDS, CheckSpec, Part
from .region import CylinderRegion
from .report import CheckResult, Report, tool_version
from .status import (
    ContractError,
    Limit,
    Measurement,
    Status,
    adjudicate,
    adjudicate_components,
    component_limit,
    epsilon,
    worst,
)

__all__ = ["identity", "run"]


def run(
    part: Part,
    *,
    out_dir: Path,
    argv: list[str] | None = None,
    contract_path: Path | None = None,
    factory: str | None = None,
    timeout_s: float | None = None,
    expected_claims: dict[str, str] | None = None,
    repinned_claims: list[str] | None = None,
    artifact_out: list[Any] | None = None,
    loaded_before: frozenset[str] = frozenset(),
) -> Report:
    """Evaluate every declared check and return the report.

    `timeout_s` bounds the build (`effective_timeout` semantics: None defaults,
    0 waives, positive is the budget) and is recorded in `invocation` — a
    stopped run must say what budget stopped it.

    `expected_claims` is the part's entry from a claims pin (#31): when given,
    the declared claim set must match it exactly BEFORE anything is evaluated.
    A mismatch is `error`, never a verdict about the part — the question
    changed identity, so no answer about the part may be given — and the
    differences are named in the artifact, because "the contract is not the
    one reviewed" must survive `--quiet` and MCP the same way `attribution`
    does. An empty dict means the pin does not vouch for this part at all.

    `repinned_claims` is the other arrival at the same block (#294): the
    differences between a lock `--pin` is about to overwrite and the claims
    this contract declares. It adjudicates nothing -- §4 of the agent contract
    permits a deliberate re-pin -- so the run proceeds to a real verdict and
    the block only records what moved. It cannot arrive with `expected_claims`
    from the CLI, where the two flags are mutually exclusive; a library caller
    passing both gets the adjudicating form, which is the one that can refuse.

    `factory` is the symbol the target resolved to — the CLI passes it whether
    the invocation named it or the module's single factory was inferred (#343)
    — and `None` only from a library caller that names none. It reaches
    `part.contract`; see `identity`.

    `loaded_before` is `sys.modules` as it stood before this target's contract
    was resolved, and only the caller that owns the loop can take it — by the
    time this function runs, the contract has been imported and its imports
    are this part's own. Empty says "one target in this process", which is
    true of every entry point but `check`'s batch loop.
    """
    started = time.perf_counter()
    ident = identity(part, contract_path, factory=factory)
    report = Report(
        part_id=part.id,
        contract=ident["contract"],
        tool_version=tool_version(),
        contract_digest=ident.get("contract_digest"),
        source=ident.get("source"),
        source_digest=ident.get("source_digest"),
        source_closure=ident.get("source_closure"),
        params=dict(part.source.params),
        argv=argv or [],
        timeout_s=timeout_s,
    )

    if repinned_claims:
        # Before the `--expect` block, so the adjudicating form wins if a
        # library caller supplies both: only that one can refuse, and a
        # `matched: false` this overwrote would be a mismatch with no verdict
        # attached. Nothing else about the run changes -- a re-pin is
        # permitted, and this is the artifact half of saying it happened.
        report.expectation = {"repinned": list(repinned_claims)}

    if expected_claims is not None:
        from . import expectation

        declared = expectation.claims_of(part)
        differences = expectation.compare(expected_claims, declared)
        report.expectation = {"claims": len(expected_claims), "matched": not differences}
        if differences:
            report.expectation["differences"] = differences
            report.error = "the contract does not match its claims pin: " + "; ".join(differences)
            report.hint = (
                "a deliberate contract change is re-pinned with --pin; anything else "
                "is the contract quietly not being the one that was reviewed"
            )
            report.checks = [
                _skipped(spec, "not evaluated: the contract does not match its pin")
                for spec in _all_specs(part)
            ]
            report.duration_ms = int((time.perf_counter() - started) * 1000)
            return report

    try:
        _evaluate(
            part,
            report,
            out_dir,
            contract_path,
            timeout_s=timeout_s,
            artifact_out=artifact_out,
            loaded_before=loaded_before,
        )
    except ContractError as exc:
        # A malformed question has no answer: every declared check is reported
        # as skipped rather than failed, and the verdict is error.
        report.error = f"{type(exc).__name__}: {exc}"
        report.hint = "the contract is wrong, not the part"
        report.checks = [
            _skipped(spec, "not evaluated: the contract raised") for spec in _all_specs(part)
        ]
    finally:
        # After the closure was read, never before: `_python_closure` is what
        # consumes `sys.modules`, and this is what keeps a later run in the
        # same process from building with this model's cached helpers (#29).
        if part.source.engine != "openscad":
            from .engines.pycad import invalidate_model_modules

            invalidate_model_modules(part.source.path)

    report.duration_ms = int((time.perf_counter() - started) * 1000)
    return report


# --------------------------------------------------------------------------


def _evaluate(
    part: Part,
    report: Report,
    out_dir: Path,
    contract_path: Path | None = None,
    *,
    timeout_s: float | None = None,
    artifact_out: list[Any] | None = None,
    loaded_before: frozenset[str] = frozenset(),
) -> None:
    parameter_specs = [s for s in part.checks if s.phase != GEOMETRY]
    geometry_specs = [s for s in part.checks if s.phase == GEOMETRY]

    results = [_run_parameter_check(spec, part.source.params) for spec in parameter_specs]

    blocker = next((r for r in results if r.status is Status.FAIL), None)
    if blocker is not None:
        reason = f"not evaluated: parameter check {blocker.id!r} failed"
        results.append(_skipped(_builds_spec(), reason))
        results.extend(_skipped(spec, reason) for spec in geometry_specs)
        report.checks = results
        return

    backend = _backend_for(part.source.engine)
    report.engine = engine_block(part, backend)

    engine_deps: list[Any] = []
    engine_unresolved: list[str] = []
    artifact = backend.build(
        _engine_source(part),
        out_dir,
        timeout_s=timeout_s,
        deps_out=engine_deps,
        unresolved_out=engine_unresolved,
    )
    if isinstance(artifact, BuildError):
        report.hint = artifact.hint
        report.build_origin = artifact.origin
        report.build_stderr = artifact.stderr

        if artifact.origin != "model":
            # Not a statement about the part, on either of the two ways to get
            # here -- and the branch is written as "not `model`" rather than
            # "is `environment`" precisely so the third state cannot fall
            # through (#307). `"environment"` is no engine on PATH, a mistyped
            # pin, a missing package, an absent source, a render out of time:
            # none of these disprove anything, and reporting them as
            # `builds: fail` made a CI run on a machine without OpenSCAD say the
            # *design* was disproven. `None` is "partspec cannot attribute
            # this", and an if/else on `== "environment"` would have adjudicated
            # it as a MODEL fault -- the misattribution the field exists to
            # prevent, and the reason widening the type was not a one-liner.
            # Both land here: `builds` is not emitted as failing at all, every
            # declared check is skipped, the verdict is `error`.
            #
            # Stated as a negation rather than as `in ("environment", None)` so
            # it fails CLOSED: `builds: fail` is the only arm that makes a
            # claim about the design, so it is the arm that must be reached
            # deliberately. A fourth origin added later is adjudicated as
            # unattributable until someone decides otherwise, which is the
            # direction this tool errs in everywhere else.
            report.error = artifact.message
            reason = f"not evaluated: {artifact.message}"
            results.append(_skipped(_builds_spec(), reason))
            results.extend(_skipped(spec, reason) for spec in geometry_specs)
            report.checks = results
            return

        empty_specs = [spec for spec in geometry_specs if spec.kind == "empty"]
        if empty_specs and artifact.produced_nothing and not artifact.unresolved:
            # The engine ran, completed, and the result was empty -- which this
            # contract declared as the intent (SPEC-contract 4.12). `builds`
            # passes because the engine produced what it was asked for; the part
            # IS the empty set. Nothing else can be measured, so every other
            # geometry check is skipped and the verdict is `incomplete` rather
            # than a pass bought by silence.
            results.append(
                CheckResult(id="builds", kind="builds", phase=GEOMETRY, status=Status.PASS)
            )
            results.extend(
                CheckResult(id=spec.id, kind="empty", phase=GEOMETRY, status=Status.PASS)
                for spec in empty_specs
            )
            results.extend(
                _skipped(spec, "not evaluated: the part is empty, as declared")
                for spec in geometry_specs
                if spec.kind != "empty"
            )
            report.checks = results
            return

        results.append(
            CheckResult(
                id="builds",
                kind="builds",
                phase=GEOMETRY,
                status=Status.FAIL,
                detail=artifact.message,
            )
        )
        for spec in empty_specs:
            # Declared, and not satisfied. Two ways to get here and they are not
            # the same fault, so the detail says which: the engine failed before
            # it could produce anything, or it produced nothing BECAUSE a name
            # did not resolve, or a value did not convert -- a probe whose
            # geometry never existed to be intersected. The latter is the case
            # this check exists to refuse, and it is invisible in the exit code
            # (#237). The cause clause comes from the same classifier `check`
            # and `measure` use, so one engine line cannot be diagnosed two ways
            # depending on which path reached it (#308).
            results.append(
                CheckResult(
                    id=spec.id,
                    kind="empty",
                    phase=GEOMETRY,
                    status=Status.FAIL,
                    detail=(
                        f"the result is empty, but "
                        f"{_unresolved_diagnosis(artifact.unresolved[0])[0]}, "
                        f"so the geometry never existed to be empty of: "
                        f"{artifact.unresolved[0]}"
                        if artifact.unresolved
                        else f"declared empty, but the part did not build: {artifact.message}"
                    ),
                )
            )
        results.extend(
            _skipped(spec, "not evaluated: the part did not build")
            for spec in geometry_specs
            if spec.kind != "empty"
        )
        report.checks = results
        return

    if engine_unresolved:
        # The build SUCCEEDED and the artifact is well-formed -- and it is not
        # the part. OpenSCAD renders an unresolved call's children not at all,
        # so a misspelt module or an include that did not open silently removes
        # geometry and still exits 0 (`docs/FAILURE-MODES.md` §1); and where a
        # value will not convert it substitutes the module's own default, so a
        # dimension nobody wrote is exported just as quietly (#308). Every
        # geometry check downstream would then be measuring a different part
        # than the contract describes, and before #286 every one of them
        # reported PASS.
        #
        # Skipped rather than failed, and no `build_origin`: the source
        # compiled, so `builds: fail` would be a statement about the design
        # that partspec has not earned (SPEC-report §6.1). Whose fault the name
        # is -- a typo in the source, or a library absent from this machine --
        # is exactly what partspec cannot tell, so it claims neither and says
        # what it does know: it did not measure the part it was given.
        #
        # Diagnosed from the line that is QUOTED, so the sentence and the
        # evidence under it always name one cause even when both kinds are in
        # the list; the `(and N more)` suffix is what says the list is longer.
        cause, report.hint = _unresolved_diagnosis(engine_unresolved[0])
        report.error = (
            f"{cause}, so the geometry measured is not the geometry this "
            f"source describes: {engine_unresolved[0]}"
        )
        if len(engine_unresolved) > 1:
            report.error += f" (and {len(engine_unresolved) - 1} more)"
        reason = f"not evaluated: {report.error}"
        results.append(_skipped(_builds_spec(), reason))
        results.extend(_skipped(spec, reason) for spec in geometry_specs)
        report.checks = results
        return

    # After the build, not before: a Python model's imports are only knowable
    # once it has run, and helpers imported lazily inside the factory would be
    # invisible to a snapshot taken any earlier.
    if part.source.engine != "openscad":
        report.source_closure = _python_closure(
            part.source, contract_path, loaded_before, tuple(part.build_inputs)
        )
        unmet = _unmet_build_inputs(part, report.source_closure)
        if unmet:
            # A run-level fault, not a failing check (SPEC-contract §10.2 rule
            # 2). The contract described a build it did not get, which says
            # nothing about the geometry — and silence is clearly wrong, since
            # the declaration's whole purpose is to strengthen coverage, so a
            # typo would quietly WEAKEN it while looking like it was asked for.
            report.error = (
                f"the contract declares build input(s) that were never imported: {', '.join(unmet)}"
            )
            report.hint = (
                "build_input() names a distribution this build must byte-hash; remove "
                "the declaration, or fix the name if the model does import it"
            )
            reason = f"not evaluated: {report.error}"
            results.append(_skipped(_builds_spec(), reason))
            results.extend(_skipped(spec, reason) for spec in geometry_specs)
            report.checks = results
            return
    elif engine_deps:
        # The OpenSCAD half of the same idea (#226). `_closure` ran before the
        # build from a static read of the source; the engine has since said what
        # it actually opened, which is the one thing no static reader can know.
        report.source_closure = _closure(part.source, engine_deps[0])

        absent = absent_build_inputs(
            _engine_source(part), engine_deps[0], out_dir, timeout_s, part.source.path
        )
        if absent:
            # The build SUCCEEDED, the depfile is `complete` -- a success-path
            # read is never anything else -- and the complete answer is that a
            # file the model asked for is not on disk. `import()` of an absent
            # target renders as nothing and `surface()` the same, so this is
            # #286's failure through a different channel: the artifact is
            # well-formed and it is not the part (#309).
            #
            # This is why `unseen` could never have caught it. That token is
            # emitted only when `engine_inputs.state` is NOT `complete` --
            # "the gap is then closed by evidence rather than assumed away"
            # (SPEC-report §8.3) -- and here the evidence IS the state, so the
            # one field that would hold the verdict below `pass` is empty
            # precisely because the engine answered in full. The list is read
            # instead, at the point it comes into hand.
            #
            # Skipped rather than failed, and no `build_origin`, for §6.1's
            # reason: the source compiled, and whether the path is a typo or
            # the file simply has not been generated yet is not something
            # partspec can tell.
            report.hint = _ABSENT_INPUT_HINT
            report.error = (
                f"{_ABSENT_INPUT_CAUSE}, so the geometry measured is not the "
                f"geometry this source describes: {sorted(absent)[0]}"
            )
            if len(absent) > 1:
                report.error += f" (and {len(absent) - 1} more)"
            reason = f"not evaluated: {report.error}"
            results.append(_skipped(_builds_spec(), reason))
            results.extend(_skipped(spec, reason) for spec in geometry_specs)
            report.checks = results
            return

    results.append(CheckResult(id="builds", kind="builds", phase=GEOMETRY, status=Status.PASS))
    if artifact_out is not None:
        # The built artifact, for the caller that asked (#129): check
        # --render used to rebuild the model it had in memory moments
        # earlier, doubling side effects and letting a nondeterministic
        # model's renders silently disagree with its measured geometry.
        artifact_out.append(artifact)
    report.geometry = backend.provenance(artifact)
    results.extend(
        # A declared `empty` that reaches here is disproven: the engine built
        # something. Answered from the build rather than from a primitive --
        # `empty` is `builds`' sibling, decided before any backend is asked, and
        # is deliberately absent from `GEOMETRY_KINDS` for that reason.
        CheckResult(
            id=spec.id,
            kind="empty",
            phase=GEOMETRY,
            status=Status.FAIL,
            detail="declared empty, but the part built geometry",
        )
        if spec.kind == "empty"
        else _run_geometry_check(spec, backend, artifact)
        for spec in geometry_specs
    )
    report.checks = results


def identity(
    part: Part,
    contract_path: Path | None,
    *,
    factory: str | None = None,
    built: bool = False,
    engine_deps: Any = None,
) -> dict[str, Any]:
    """The part-identity block, shared by `check`'s report and `measure` (#47).

    One builder, because the two verbs had already drifted once before (#73,
    engine block) and `measure` shipped with no identity at all — a consumer
    could not tell which file, which revision, or which parameter set produced
    the numbers it was about to turn into checks, in the verb whose stated
    purpose is bootstrapping contracts. Same keys, same omission rules, same
    path portability as `Report.to_json`'s `part` block; a pinned test holds
    the two equal.

    `built=True` after a Python-engine build swaps in the imports-derived
    closure, mirroring the runner's own post-build upgrade — a Python model's
    inputs are only knowable once it has run.

    `factory` is the symbol the invocation named, and it is what keeps two
    targets in one module apart (#297). Without it, two factories returning
    Parts with the same id produced BYTE-IDENTICAL `part` blocks — same
    module-scoped `contract_digest`, same source, same closure — so nothing in
    either artifact recorded which one was invoked. The path stays in the frame
    #45 fixed on: relative to the contract's own directory, which for the
    contract itself is its filename. A module with a single factory needs no
    name to resolve, and `target.resolve` supplies the resolved symbol anyway
    so that `diff` has one spelling per target to compare (#343) — but a
    library caller may still pass none, so `<module>` and `<module>:<factory>`
    are both well-formed values and a consumer MUST parse the suffix as
    optional (SPEC-report.md 7.1).
    """
    contract = _relative(contract_path, contract_path) if contract_path else "<in-memory>"
    out: dict[str, Any] = {
        "id": part.id,
        "contract": f"{contract}:{factory}" if factory else contract,
    }
    contract_digest = _digest(contract_path)
    if contract_digest:
        out["contract_digest"] = contract_digest
    source = _relative(part.source.path, contract_path)
    if source:
        out["source"] = source
    source_digest = _digest(part.source.path)
    if source_digest:
        out["source_digest"] = source_digest
    closure = _closure(part.source, engine_deps)
    if built and part.source.engine != "openscad":
        closure = _python_closure(part.source, contract_path)
    if closure:
        out["source_closure"] = closure
    return out


def engine_block(part: Part, backend: Any) -> dict[str, Any]:
    """The engine provenance block, in the exact section-7 order.

    One constructor, used by `check` here and by the `measure` verb — the two
    had already drifted apart (#73: measure emitted kind/backend/version in
    the wrong order and omitted everything below it). Field notes:

    - `render_backend` is always present, pinned string or null — the
      unpinned run is exactly the one whose backend a reader cannot infer,
      because the engine default varies by version (CGAL on 2021.01, Manifold
      on current builds) and F10 is a mesh-validity difference between them
      (#41). Null means "the default, whichever this version chose".
    - `method` is always present, mirroring adopted_via: null states "the
      default entry", not "unrecorded" (#40). On OpenSCAD, `param_mode` says
      how parameters reached the geometry, and on the call path
      `source_rendered: "derived"` records that the engine's entry was a
      derived scratch, not the digested file.
    """
    block: dict[str, Any] = {
        "kind": part.source.engine,
        "version": backend.engine_version,
        "backend": backend.kind,
        "render_backend": part.source.backend,
        "adopted_via": "wrapped" if part.source.engine == "cadquery" else None,
        "method": part.source.method,
    }
    if part.source.engine == "openscad":
        block["param_mode"] = "call" if part.source.method else "define"
        if part.source.method:
            block["source_rendered"] = "derived"
    return block


def _run_parameter_check(spec: CheckSpec, params: dict[str, Any]) -> CheckResult:
    if spec.kind == "requires":
        assert spec.expr is not None
        ok, operands = expr_mod.evaluate(spec.expr, params)
        return CheckResult(
            id=spec.id,
            kind=spec.kind,
            phase=spec.phase,
            status=Status.PASS if ok else Status.FAIL,
            expr=spec.expr,
            operands=operands,
            detail=None if ok else expr_mod.describe(spec.expr, operands),
        )

    if spec.kind == "param_range":
        assert spec.expr is not None and spec.limit is not None
        value = params[spec.expr]
        measurement = Measurement(value, spec.unit or _unit_for(value), exact=True)
        status = adjudicate(measurement, spec.limit)
        return CheckResult(
            id=spec.id,
            kind=spec.kind,
            phase=spec.phase,
            status=status,
            measurement=measurement,
            limit=spec.limit,
            source=dict(spec.source) if spec.source is not None else None,
            detail=None
            if status is Status.PASS
            # `_number`, not `repr`. Routing only `_render` through the shared
            # formatter made THIS line the two-notation case it was meant to
            # remove: `p.param("hole_d", max=1e9)` printed
            # `hole_d=10000000000.0 outside max=1e+09` (adversarial review of
            # #232). A parameter value is whatever the contract passed, so
            # `_number`'s non-numeric fallback carries the rest.
            else f"{spec.expr}={_number(value)} outside {_render(spec.limit)}",
        )

    raise ContractError(f"unknown parameter check kind: {spec.kind!r}")


def _refused(common: dict[str, Any], outcome: Unsupported) -> CheckResult:
    """The check result a backend refusal becomes.

    One function because it was written out eight times, and every copy has
    to remember `requires=` — the field that tells an author WHICH tier would
    answer, which is the entire point of refusing by name rather than
    failing. Eight places to forget it is eight chances to turn an
    actionable refusal into a dead end.
    """
    return CheckResult(
        **common,
        status=Status.UNSUPPORTED,
        detail=outcome.reason,
        requires=outcome.requires,
    )


def _run_geometry_check(spec: CheckSpec, backend: Any, artifact: Any) -> CheckResult:
    primitive_name = GEOMETRY_KINDS.get(spec.kind)
    if primitive_name is None:
        raise ContractError(f"unknown geometry check kind: {spec.kind!r}")

    common: dict[str, Any] = {
        "id": spec.id,
        "kind": spec.kind,
        "phase": spec.phase,
        "limit": spec.limit,
    }
    if spec.region is not None:
        # Attached before any early return: a refusal must still state what was
        # claimed, or the reader cannot judge what went unanswered.
        common["region"] = {**spec.region.to_json(), "shell": spec.shell}
    if spec.hole is not None:
        common["hole"] = dict(spec.hole)
    if spec.source is not None:
        common["source"] = dict(spec.source)
    if spec.direction is not None:
        common["direction"] = [round(c, 9) for c in spec.direction]

    # Capability is static and consulted first, so an unanswerable check costs
    # nothing to report. `requires` names the tier that would answer; for the
    # region kinds both tiers declare the primitive, so a backend without it
    # implies no tier and the field stays absent.
    if primitive_name not in backend.capabilities():
        return CheckResult(
            **common,
            status=Status.UNSUPPORTED,
            detail=f"the {backend.kind} backend cannot evaluate {spec.kind}",
            requires="occt" if spec.region is None else None,
        )

    if spec.kind in ("keep_out", "keep_in"):
        return _run_region_check(spec, backend, artifact, common)
    if spec.kind == "hole_diameter":
        return _run_hole_check(spec, backend, artifact, common)
    if spec.kind == "bolt_circle":
        return _run_bolt_circle_check(spec, backend, artifact, common)
    if spec.kind == "fillet_radius":
        return _run_fillet_check(spec, backend, artifact, common)
    if spec.kind == "draft_angle":
        return _run_draft_check(spec, backend, artifact, common)
    if spec.kind == "step_roundtrip":
        return _run_step_check(spec, backend, artifact, common)
    if spec.kind == "min_wall":
        return _run_min_wall_check(spec, backend, artifact, common)

    outcome = getattr(backend, primitive_name)(artifact)
    if isinstance(outcome, Unsupported):
        return _refused(common, outcome)

    assert spec.limit is not None
    status = adjudicate(outcome, spec.limit)
    components = _components_of(outcome, spec.limit)
    detail = None
    if status is Status.FAIL:
        # A backend that knows something better than the numbers says it —
        # `watertight_detail` distinguishes a hole from a non-manifold junction,
        # which no comparison of value to limit can.
        #
        # The hook contract permits DECLINING (`-> str | None`), and no hook
        # exercises that at a FAIL today: `watertight_detail` returns None iff
        # the mesh IS watertight, which is a pass, and `self_intersection_free_
        # detail` is typed `-> str` with no None path. The chain rather than an
        # `elif` is for the first one that does — as an `elif` it left `detail`
        # None, which is #210's emptiness restored one layer up. Same footing
        # as `_render`'s `choices` branch: written for a caller that does not
        # exist yet, and labelled as such rather than as a live bug. An earlier
        # version of this comment asserted `watertight_detail` already declined
        # that way (adversarial review of #232).
        explain = getattr(backend, f"{spec.kind}_detail", None)
        if explain is not None:
            detail = explain(artifact)
        if detail is None:
            detail = (
                _failing_axes(outcome, spec.limit, components)
                if components is not None
                else _failing_scalar(outcome, spec.limit)
            )
    return CheckResult(
        **common, status=status, measurement=outcome, components=components, detail=detail
    )


def _components_of(outcome: Measurement, limit: Limit) -> dict[str, Status] | None:
    """Axis -> status for a vector measurement; None for scalars.

    Derived from the same `adjudicate_components` call that `adjudicate` folds,
    never recomputed by other means — two adjudications of one claim is one
    adjudication too many.
    """
    if not outcome.is_vector or outcome.axes is None:
        return None
    per = adjudicate_components(outcome, limit)
    return {axis: s for axis, s in zip(outcome.axes, per, strict=True) if s is not None}


def _failing_axes(outcome: Measurement, limit: Limit, components: dict[str, Status]) -> str:
    """Name each non-passing axis with its value and the bound it broke —
    the difference between a report an agent can act on in one edit and one
    it must bisect."""
    values = dict(zip(outcome.axes or (), tuple(outcome.value), strict=True))
    n = len(tuple(outcome.value))
    axis_index = {axis: i for i, axis in enumerate(outcome.axes or ())}
    parts = []
    for axis, status in components.items():
        # Only conclusive violations: "outside" is a claim, and an APPROXIMATE
        # axis is one the tool does not know to be outside. No backend emits
        # vector bounds today, but the message must not be a lie waiting for
        # the first one that does.
        if status is not Status.FAIL:
            continue
        sub = component_limit(limit, axis_index[axis], n)
        assert sub is not None  # a constrained status implies a constraint
        # `_number`, not `:g`: this is the caller the scalar path was modelled on,
        # and it kept the six-figure collapse the scalar path was changed to
        # avoid — a vector `1000.0002` against `max=1000.0` printed
        # `x=1000 outside max=1000.0`, a failure line reading as an equality
        # (adversarial review of #232).
        parts.append(f"{axis}={_number(values[axis])} outside {_render(sub)}")
    return "; ".join(parts)


DIMENSIONLESS = frozenset({"count", "bool"})
"""Units whose name the fail line drops, because it says nothing.

"measured 2 count" reads worse than "measured 2", and the check id already
says what was counted.

One criterion, not two. An earlier version of this said `rel` is excluded
because `step_roundtrip` does not reach this path — unreachability, which
would exclude `bool` too, since the `equals` skip in `_failing_scalar` means a
bool never reaches `_quantity` either. The rule is simply whether the unit
names something a reader needs: `count` and `bool` do not, `rel` does
(a ratio wants saying so). `bool` stays for the same reason the `choices`
branch does — the skip is a property of today's limits, not of the unit.
"""


def _failing_scalar(outcome: Measurement, limit: Limit) -> str | None:
    """The two numbers a scalar failure is about.

    The vector case has said this since `_failing_axes` was written. The scalar
    case said nothing at all, so `FAIL solid_count` was the entire diagnostic
    while `report.json` two feet away held `{"value": 1}` against
    `{"equals": 2}` (#210). The console is a courtesy and the JSON is the
    product, but a courtesy that states only the fact the reader already had —
    that something is wrong — is not one. For `solid_count` the value *is* the
    finding: too few means bodies fused, too many means something fragmented or
    detached, and those point at opposite causes that the bare line cannot
    distinguish.

    Generic rather than per-kind, which `Limit`'s own docstring licenses: a
    closed set of forms exists "so a consumer can render and compare limits
    without knowing the check kind". A backend that knows better still wins —
    `<kind>_detail` is consulted first, which is how the mesh tier's
    `watertight` distinguishes a hole from a non-manifold junction. (Not
    `keep_out`: that returns from `_run_region_check` long before the hook is
    looked up, and builds its sentence itself. An earlier draft of this
    paragraph credited a `keep_out_detail` that does not exist.)

    **A bool with an `equals` limit gets nothing, because there is nothing to
    say.** For a two-valued measurement an `equals` limit plus `FAIL`
    determines the value: failing `equals=true` means false and failing
    `equals=false` means true, in both directions. `measured false, limit
    equals=false` restates the id and the status and adds no fact — the one
    place where the generic renderer produces noise rather than signal, found
    by the adversarial review of #232 on the OCCT tier, which has no
    `watertight_detail` to win ahead of it.

    `:.9g` for `hole_diameter`'s reason, which that check records at its own
    `:.9g`: six significant figures collapse numbers a reader needs to see
    apart. The example there is a tight band printing as an empty interval;
    here it is a measurement and the bound it missed — `1000.0002` against
    `max=1000.0` is a real `FAIL` that `:g` renders as `1000` on both sides.
    (Not "missed by a micron", as this said until the review: `epsilon(2.0)` is
    1.2e-6, so a one-micron miss at that magnitude adjudicates PASS and never
    reaches this function at all.)
    """
    if outcome.unit == "bool" and limit.equals is not None:
        return None
    return f"measured {_quantity(outcome)}, limit {_render(limit)}"


def _number(value: Any) -> str:
    """One numeric format, shared by the measurement and the limit it missed.

    They were formatted differently — `:.9g` here and a bare `str()` in
    `_render` — so a large value printed `measured 1.23456789e+09 mm3, limit
    min=10000000000.0`, two notations for the single comparison the line exists
    to let a reader make (adversarial review of #232). Reachable from the public
    API with `volume(min=1e10)`.

    `bool` before the numeric branch, because `bool` subclasses `int` in Python
    and the obvious ordering renders `True` as `1` — the same trap
    `scad_literal` carries a note about, and the reason `limit equals=True` and
    `measured false` once described one boolean in one sentence two ways.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = f"{value:.9g}"
        # `:.9g` renders 2.0 as "2", and a float limit that prints as an
        # integer loses information the reader uses: `solid_count` limits are
        # ints and `volume` limits are floats, and the existing vector messages
        # have always shown the difference. Restored only where the rendering
        # ends in a digit, so nothing else is touched.
        #
        # That guard is not cosmetic. `Measurement._reject_non_finite` refuses
        # a non-finite VALUE, but `Limit` validates nothing (`__post_init__`
        # only requires a form to be set) and `_reject_non_finite` never looks
        # at `bounds`, so `solid_count(float("inf"))` and a bounds tuple
        # carrying an infinity both reach here from the public API. Without the
        # guard they rendered as `inf.0` and `nan.0` — a number that is not one,
        # wearing a decimal point (adversarial review of #232).
        if text[-1].isdigit() and "." not in text and "e" not in text:
            text += ".0"
        return text
    return str(value)


def _quantity(m: Measurement) -> str:
    """A scalar measurement as one human-readable term.

    `count` and `bool` name no dimension and their unit is dropped: the check
    id already says what was counted, and "measured 2 count" reads worse than
    "measured 2". `MEASURANDS` is the register of units and
    `test_the_dimensionless_units_are_still_the_ones_this_drops` fails when it
    grows one this does not classify.

    The interval rides along whenever `bounds` is present — which is the
    code's condition, not `exact` (an exact measurement MAY carry bounds;
    `Measurement` only forbids the converse). No primitive on this path
    emits bounds today — `_min_wall_measurement` is the only
    `exact=False` site in either backend and `min_wall` returns from its own
    runner before reaching here. It is written anyway, on the `choices` branch's
    principle: an approximate measurement whose WHOLE interval sits outside the
    limit adjudicates to `FAIL` rather than `APPROXIMATE`, so the first backend
    to emit one arrives here with bounds in hand, and printing the point value
    alone would state a single number it never claimed to know (SPEC-report
    3.1). This docstring said the path was "not hypothetical"; it is, and the
    review of #232 said so.
    """
    text = _number(m.value)
    if m.unit not in DIMENSIONLESS:
        text = f"{text} {m.unit}"
    if m.bounds is not None:
        # After the unit, not before it: the interval is in the same unit as
        # the value, and "1.5 (in [1.4, 1.6]) mm" reads as though it were not.
        lo, hi = m.bounds
        text += f" (in [{_number(lo)}, {_number(hi)}])"
    return text


def _run_hole_check(
    spec: CheckSpec, backend: Any, artifact: Any, common: dict[str, Any]
) -> CheckResult:
    """Adjudicate a hole_diameter claim: exactly N detected bores in the band.

    The measurement is the matched diameters themselves, not the count — the
    count is derivable from the vector's length, and the diameters are what a
    comparator tracks drift on when an author uses a real tolerance band. No
    match measured nothing for this claim, so `measurement` is null and the
    detail carries the full bore inventory instead.
    """
    assert spec.limit is not None and spec.hole is not None
    outcome = backend.bores(artifact)
    if isinstance(outcome, Unsupported):
        return _refused(common, outcome)

    all_bores = tuple(float(x) for x in outcome.value)
    lo, hi = spec.limit.min, spec.limit.max
    # Plain interval membership: the band IS the tolerance, already widened by
    # the author's tol or the comparison epsilon at declaration. Applying
    # epsilon again here would tolerance the tolerance.
    matched = tuple(x for x in all_bores if lo <= x <= hi)
    expected = int(spec.hole["count"])

    measurement = None
    if matched:
        measurement = Measurement(
            matched,
            "mm",
            exact=True,
            axes=tuple(f"bore_{i + 1}" for i in range(len(matched))),
        )
    detail = None
    if len(matched) != expected:
        # :.9g, not :g — a tight band rendered as "[8, 8]" reads as an empty
        # interval and hides exactly the sub-micrometre disagreement a tight
        # tol exists to surface.
        inventory = ", ".join(f"Ø{x:.9g}" for x in all_bores) if all_bores else "none"
        detail = (
            f"found {len(matched)} bore(s) with diameter in [{lo:.9g}, {hi:.9g}] mm, "
            f"expected {expected}; bores on this part: {inventory}"
        )
    return CheckResult(
        **common,
        status=Status.PASS if len(matched) == expected else Status.FAIL,
        measurement=measurement,
        detail=detail,
    )


def _run_fillet_check(
    spec: CheckSpec, backend: Any, artifact: Any, common: dict[str, Any]
) -> CheckResult:
    """Adjudicate every blend radius against the bounds — the one bespoke rule
    is the empty set. "Every blend is within bounds" over zero blends is
    vacuously true, and vacuous truth is the green this tool exists to refuse:
    a part with no blends FAILS the check rather than passing it
    (SPEC-contract.md 4.7)."""
    assert spec.limit is not None
    outcome = backend.blend_radii(artifact)
    if isinstance(outcome, Unsupported):
        return _refused(common, outcome)
    if not outcome.value:
        return CheckResult(
            **common,
            status=Status.FAIL,
            detail="no cylindrical blend surfaces detected on this part (toroidal and "
            "spherical blends are not yet detected — SPEC-contract.md 4.7); a claim "
            "about every blend needs at least one, and passing over an empty set "
            "would be vacuous green",
        )
    status = adjudicate(outcome, spec.limit)
    components = _components_of(outcome, spec.limit)
    detail = None
    if status is Status.FAIL and components is not None:
        detail = _failing_axes(outcome, spec.limit, components)
    return CheckResult(
        **common, status=status, measurement=outcome, components=components, detail=detail
    )


def _run_min_wall_check(
    spec: CheckSpec, backend: Any, artifact: Any, common: dict[str, Any]
) -> CheckResult:
    """Adjudicate the guaranteed wall interval (#140). The vacuous case — a
    part where every face pair meets at an edge — FAILS like fillet's empty
    set: "every wall is thick enough" over zero walls is the vacuous green
    this tool refuses, and an author with a corner-only part simply does not
    declare the check."""
    from .backends.occt import _min_wall_measurement

    assert spec.limit is not None
    raw = backend._min_wall_raw(artifact)
    if isinstance(raw, Unsupported):
        return _refused(common, raw)
    if raw.get("vacuous"):
        return CheckResult(
            **common,
            status=Status.FAIL,
            detail="no wall spans exist: every face pair meets at an edge, and "
            "corner features are not walls — a claim about every wall needs at "
            "least one, and passing over an empty set would be vacuous green",
        )
    measurement = _min_wall_measurement(raw)
    status = adjudicate(measurement, spec.limit)
    detail = None
    if status is not Status.PASS:
        thinnest = f"thinnest span {raw['lo']:.6g} mm at {raw['witness']}"
        if status is Status.APPROXIMATE:
            detail = (
                f"{thinnest}; the guaranteed interval "
                f"[{raw['lo']:.6g}, {raw['hi']:.6g}] straddles the limit — "
                "the tool does not know, and will not guess"
            )
        else:
            detail = thinnest
        if raw.get("gap_limited"):
            # On FAIL too (PR #144 re-review, R2): the number named is a
            # void distance, and saying so only on the approximate branch
            # left the fail detail implying a proven thin wall.
            detail += (
                " (the bound is limited by a gap-like pair — a nearby "
                "void, not a proven thin wall; PR #144 review, F2: "
                "excluding such pairs once hid a real wall)"
            )
    return CheckResult(**common, status=status, measurement=measurement, detail=detail)


def _run_step_check(
    spec: CheckSpec, backend: Any, artifact: Any, common: dict[str, Any]
) -> CheckResult:
    """Adjudicate the exchange round-trip. Two gates, deliberately separate:
    topology drift fails at ANY tolerance (a count that changed is a
    different part), and only then are the exact relative deltas held to the
    author's tol. The writer schema rides on the check — it changes the
    artifact (the F13 lesson)."""
    assert spec.limit is not None
    outcome = backend.step_roundtrip(artifact)
    if isinstance(outcome, Unsupported):
        return _refused(common, outcome)

    common["step"] = {"schema": outcome["schema"]}
    measurement = Measurement(
        (outcome["volume_rel"], outcome["area_rel"]),
        "rel",
        exact=True,
        axes=("volume", "area"),
    )
    drifted = [
        f"{name} {before} -> {after}"
        for name in ("solids", "faces", "edges")
        for before, after in [outcome[name]]
        if before != after
    ]
    if drifted:
        return CheckResult(
            **common,
            status=Status.FAIL,
            measurement=measurement,
            detail="the round-trip changed topology: " + ", ".join(drifted),
        )
    # Plain membership, deliberately NOT `adjudicate`: the author's tol IS
    # the tolerance (the hole_diameter principle), and the shared comparison
    # epsilon — an absolute 1e-6 floor designed for mm-scale STL round-trips
    # — silently swallowed any tighter tol on this unitless relative delta,
    # so the report recorded a limit three orders stricter than what was
    # enforced (PR #143 review, F2).
    tol = spec.limit.max
    assert isinstance(tol, float)
    components = {
        axis: (Status.PASS if float(value) <= tol else Status.FAIL)
        for axis, value in zip(("volume", "area"), measurement.value, strict=True)
    }
    status = worst(list(components.values()))
    detail = None
    if status is Status.FAIL:
        failing = ", ".join(
            f"{axis}={float(value):.6g} outside max={tol:.6g}"
            for axis, value in zip(("volume", "area"), measurement.value, strict=True)
            if components[axis] is Status.FAIL
        )
        detail = failing
    return CheckResult(
        **common, status=status, measurement=measurement, components=components, detail=detail
    )


def _run_draft_check(
    spec: CheckSpec, backend: Any, artifact: Any, common: dict[str, Any]
) -> CheckResult:
    """Adjudicate every face's draft against the bounds. No bespoke empty-set
    rule: a solid has faces or it was refused at adoption, and every face gets
    a value (tops measure 90), so there is no vacuous subset to pass."""
    assert spec.limit is not None and spec.direction is not None
    outcome = backend.draft_angle(artifact, spec.direction)
    if isinstance(outcome, Unsupported):
        return _refused(common, outcome)
    status = adjudicate(outcome, spec.limit)
    components = _components_of(outcome, spec.limit)
    detail = None
    if status is Status.FAIL and components is not None:
        detail = _failing_axes(outcome, spec.limit, components)
    return CheckResult(
        **common, status=status, measurement=outcome, components=components, detail=detail
    )


_BOLT_CIRCLE_SEARCH_CAP = 60
"""Candidate bores per direction group before the triple search is refused.
C(60,3) ≈ 34k circumcircles is cheap; a part with more same-diameter parallel
bores than that deserves an honest refusal over an unbounded search."""


def _run_bolt_circle_check(
    spec: CheckSpec, backend: Any, artifact: Any, common: dict[str, Any]
) -> CheckResult:
    """Exactly `count` matching bores, axes parallel, concyclic at `bcd`.

    Subset semantics (SPEC-contract.md 4.6): the claim is that such a circle
    EXISTS, searched over every subset of candidate bores — an unrelated hole
    elsewhere must not break it, and a fifth hole on the claimed circle must.
    Every valid circle through >= 3 points is determined by 3 of its members,
    so searching triples finds it without enumerating subsets.
    """
    assert spec.limit is not None and spec.hole is not None
    table = backend.bore_table(artifact)
    if isinstance(table, Unsupported):
        return _refused(common, table)

    d, count, bcd = spec.hole["d"], int(spec.hole["count"]), spec.hole["bcd"]
    lo, hi = spec.limit.min, spec.limit.max
    band = hi - bcd
    candidates = [b for b in table if abs(b["d"] - d) <= epsilon(d)]

    groups: dict[tuple, list[dict[str, Any]]] = {}
    for bore in candidates:
        groups.setdefault(tuple(round(c, 6) for c in bore["direction"]), []).append(bore)

    fitted, best = None, None  # best: (members_found, circle_diameter) for the detail
    capped = 0
    for group in groups.values():
        if len(group) < count:
            continue
        if len(group) > _BOLT_CIRCLE_SEARCH_CAP:
            # Noted, not returned: a passing circle in another direction group
            # must still be found — the refusal is only the outcome when the
            # whole search ends empty-handed with part of it unexamined.
            capped = max(capped, len(group))
            continue
        points = _plane_coordinates(group)
        fitted, best = _find_circle(points, count, bcd, band, lo, hi, best)
        if fitted is not None:
            break

    if fitted is not None:
        return CheckResult(
            **common, status=Status.PASS, measurement=Measurement(fitted, "mm", exact=True)
        )
    if capped:
        return CheckResult(
            **common,
            status=Status.UNSUPPORTED,
            detail=f"{capped} candidate bores share one axis direction; refusing to "
            f"search beyond {_BOLT_CIRCLE_SEARCH_CAP} rather than answer slowly and "
            f"claim it was exhaustive",
        )
    if best is not None:
        found, circle_d = best
        near = f"; the nearest circle of Ø{circle_d:.9g} holds {found} of them"
    else:
        near = ""
    return CheckResult(
        **common,
        status=Status.FAIL,
        detail=f"no circle of Ø{bcd:.9g} (±{band:.9g}) holds exactly {count} parallel "
        f"bores of Ø{d:g}; {len(candidates)} candidate bore(s) on this part{near}",
    )


def _plane_coordinates(group: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Project each bore centre onto the plane perpendicular to the shared axis."""
    dx, dy, dz = group[0]["direction"]
    # Any vector not parallel to the axis seeds the basis.
    ax, ay, az = (1.0, 0.0, 0.0) if abs(dx) < 0.9 else (0.0, 1.0, 0.0)
    ux, uy, uz = dy * az - dz * ay, dz * ax - dx * az, dx * ay - dy * ax
    norm = (ux * ux + uy * uy + uz * uz) ** 0.5
    ux, uy, uz = ux / norm, uy / norm, uz / norm
    vx, vy, vz = dy * uz - dz * uy, dz * ux - dx * uz, dx * uy - dy * ux
    return [
        (cx * ux + cy * uy + cz * uz, cx * vx + cy * vy + cz * vz)
        for cx, cy, cz in (bore["center"] for bore in group)
    ]


def _find_circle(
    points: list[tuple[float, float]],
    count: int,
    bcd: float,
    band: float,
    lo: float,
    hi: float,
    best: tuple[int, float] | None,
) -> tuple[float | None, tuple[int, float] | None]:
    """Search for a circle of ~bcd holding exactly `count` points.

    Triples only SEED the search: three points determine a circle exactly, but
    band membership is a claim about the *pattern* circle, and a raw
    circumcentre of perturbed points shifts by ~2x the perturbation — enough
    to eject a conforming fourth hole from a band it genuinely sits in (PR #89
    review, blocker 1). Each seed therefore captures loosely (2x band),
    refits the centre by least squares over the capture, and only then
    adjudicates strictly against the refitted centre. Exactness is judged
    against that fitted pattern circle, never against a seed's own centre.

    Returns (fitted diameter or None, best near-miss for the failure detail).
    """
    import itertools
    import math

    def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    if count == 2:
        # Two bolts on a BCD sit diametrically opposite: the circle claim
        # collapses to centre distance == bcd. The closest in-band pair is the
        # measurement — the first found would make the recorded value depend
        # on face-iteration order.
        closest = None
        for a, b in itertools.combinations(points, 2):
            separation = dist(a, b)
            if closest is None or abs(separation - bcd) < abs(closest - bcd):
                closest = separation
        if closest is not None and lo <= closest <= hi:
            return closest, best
        if closest is not None:
            best = (2, closest) if best is None or abs(closest - bcd) < abs(best[1] - bcd) else best
        return None, best

    for triple in itertools.combinations(points, 3):
        centre = _circumcentre(*triple)
        if centre is None:
            continue  # collinear
        if any(abs(2 * dist(centre, p) - bcd) > 2 * band for p in triple):
            continue  # a seed nowhere near the claimed radius cannot converge to it
        for _ in range(8):
            capture = [p for p in points if abs(2 * dist(centre, p) - bcd) <= 2 * band]
            if len(capture) < 3:
                break
            refit = _fit_centre(capture)
            if refit is None or dist(refit, centre) < 1e-12:
                break
            centre = refit
        members = [p for p in points if abs(2 * dist(centre, p) - bcd) <= band]
        if not members:
            continue
        circle_d = 2 * sum(dist(centre, p) for p in members) / len(members)
        if len(members) == count and lo <= circle_d <= hi:
            return circle_d, best
        if best is None or abs(len(members) - count) < abs(best[0] - count):
            best = (len(members), circle_d)
    return None, best


def _fit_centre(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Algebraic least-squares circle centre (Kåsa fit) — linear, stdlib-only."""
    n = len(points)
    sx = sum(p[0] for p in points) / n
    sy = sum(p[1] for p in points) / n
    # Centre the data first: the normal equations are ill-conditioned far
    # from the origin, and bore coordinates routinely sit at ~1e2.
    u = [p[0] - sx for p in points]
    v = [p[1] - sy for p in points]
    suu = sum(a * a for a in u)
    svv = sum(a * a for a in v)
    suv = sum(a * b for a, b in zip(u, v, strict=True))
    suuu = sum(a * a * a for a in u)
    svvv = sum(a * a * a for a in v)
    suvv = sum(a * b * b for a, b in zip(u, v, strict=True))
    svuu = sum(b * a * a for a, b in zip(u, v, strict=True))
    det = suu * svv - suv * suv
    if abs(det) < 1e-12:
        return None  # collinear
    cu = ((suuu + suvv) * svv - (svvv + svuu) * suv) / (2 * det)
    cv = ((svvv + svuu) * suu - (suuu + suvv) * suv) / (2 * det)
    return (cu + sx, cv + sy)


def _circumcentre(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> tuple[float, float] | None:
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = (
        a[0] * a[0] + a[1] * a[1],
        b[0] * b[0] + b[1] * b[1],
        c[0] * c[0] + c[1] * c[1],
    )
    return (
        (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d,
        (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d,
    )


_DEPTH_BISECTIONS = 24
"""Cap on the erosion search's boolean count.

24 halvings take a region of inradius 20 mm to 1.2e-6 mm, well past anything a
mesh boolean resolves. The cap is a COST bound, not an accuracy one: each step
is a boolean, and the whole search measured 0.073 s for 24 on the mesh tier and
3.3 s for 24 on OCCT — 3 ms and 0.14 s each. It is only ever paid on a
failing region clause: 4 `intersect_volume` calls on a passing check against up
to 28 on a failing one, fewer once the interval closes to `_DEPTH_TOLERANCE`
first (22 for a region of inradius 0.15 mm)."""

_DEPTH_TOLERANCE = 1e-6
"""Bracket width at which the search stops early, in mm."""

_MIN_RESOLVING_HALVINGS = 4
"""How finely the search must resolve a region before its answer means anything.

`depth_limited_by_region` asks whether the proven depth is within one search
interval of the region's search ceiling. That distinguishes nothing when the
interval is a sizeable fraction of the ceiling itself, which is what the early
break leaves for a ceiling near `_DEPTH_TOLERANCE`. Four halvings put the
interval at a sixteenth, the coarsest at which "the whole depth" and "part of
it" are different statements.

Keyed on the SEARCH CEILING, not the inradius. The two part company for a
region whose volume barely clears `epsilon(0.0)`: one 200 mm long and 33 nm
thick has an inradius of 16.5 nm — past the guard — and a search ceiling of
0.0675 nm, so it saturated at a depth of zero and satisfied BOTH the
sub-resolution and region-limited branches at once. An earlier draft argued
those two are disjoint, keyed the guard on the inradius, and deleted the test
that pinned their order on the strength of the argument (round-5 review of
#207). Keyed this way they really are disjoint: an overlap needs
`ceiling <= hi - lo <= max(_DEPTH_TOLERANCE, inradius / 2**24)`. The guard puts
`ceiling` over 1.6e-5, so an overlap needs an inradius over `1.6e-5 * 2**24`
= 268 mm — and every extent of such a region is at least 537 mm, whose eroded
volume at `inradius / 2**24` exceeds the threshold by seven orders of
magnitude. (Measured ratio at inradius 268.5, 1000 and 1e5 mm: 1.68e7.)

It excludes regions under 32 nm across — the inradius is a HALF-extent.
"""


def _intrusion_sentence(in_region: float, intrusion: dict[str, Any] | None) -> str:
    """The keep-out breach, with the numbers that make the volume mean something.

    `12.7331 mm3 intrudes` was the whole finding, and it is the same sentence
    for faceting noise and for a rib 1.5 mm into a bore — the two situations an
    engineer most needs told apart (#207).

    **States the comparison and stops there.** An earlier version concluded for
    the reader — "so the intrusion is its discretisation rather than the part" —
    and that conclusion is unsound twice over. The floor accounts for the
    REGION's circumscription only, and on the mesh tier the modelled bore is
    inscribed in its own `$fn`, a second term the contract cannot see and one
    that is zero on an exact backend. How the two COMBINE depends on how the
    polygons are phased — `region term <= depth <= region term + feature term`,
    and measured against a `$fn=128` bore the depth sits at the bottom of that
    bracket at 64 region segments and at 0.9994 of the top at 128. A second
    draft said "…accounts for up to X of that, and the modelled feature's
    tessellation for more" (the top) and a third said the terms select rather
    than sum (the bottom); each is one end asserted as the rule. And `depth <=
    floor` licenses "the region's own faceting COULD account for this", never
    "it did" — measured, a rib genuinely 1.5 mm in was called discretisation
    once the region's height capped the search (reviews of #207). Both numbers
    are printed; the reader draws the conclusion, being the only party in a
    position to.

    "at least", because the search stops when the eroded intersection falls
    below a volume threshold rather than when it empties, so the depth is a
    lower bound.
    """
    volume = f"{in_region:.6g} mm3 of material intrudes into the keep-out region"
    if intrusion is None:
        return volume
    depth, floor = intrusion["min_depth_mm"], intrusion["facet_floor_mm"]
    if depth <= 0.0:
        # Detected, but every probe above the smallest came back under the
        # volume threshold. There is no depth to report and "at least 0 mm" is
        # not a statement. FIRST, because a sub-micron region saturates too and
        # the branch below would print the zero this one exists to suppress
        # (round-3 review of #207).
        return (
            f"{volume}, at a depth below the {intrusion['search_resolution_mm']:.3g} mm "
            f"this search resolves"
        )
    if intrusion["depth_limited_by_region"]:
        # The erosion consumed the whole region, so the number describes the
        # declaration rather than the breach and must not be compared to
        # anything: a 20 mm rib and a 200 mm one both report the region's own
        # half-extent.
        return (
            f"{volume}, reaching at least {depth:.4g} mm past its boundary — the whole "
            f"depth of the region, so how much further it goes is not measurable against "
            f"a region this size"
        )
    reach = f"{volume}, reaching at least {depth:.4g} mm past its boundary"
    if floor <= 0.0:
        return reach
    return (
        f"{reach}; for scale, this region's own faceting would show {floor:.4g} mm "
        f"against a perfectly circular feature"
    )


def _search_ceiling(region: Any) -> float:
    """The deepest value the erosion search can return for this region at all.

    The search stops when the eroded region holds less than `epsilon(0.0)` mm3
    of material. A region eroded nearly to its inradius holds almost nothing
    whatever the part does, so that threshold — not the inradius — is where the
    search runs out, and it runs out at a depth set by the region's SHAPE. For
    an equilateral region the erosion collapses all three dimensions at once
    and the shortfall from the inradius is a constant ~5e-3 mm; for an
    elongated one it collapses fewer and the shortfall is far smaller. A fixed
    relative slack cannot straddle both, which is how a 8x8x8 mm keep-out
    buried in solid material came to report a partial interference while
    8x8x7.99 reported a total one (round-2 review of #207).

    Computed from the declaration alone — `eroded_volume` is closed form on
    both region kinds — so this costs no geometry and is exact. Via
    `eroded_volume` rather than `expand(-mid).volume()` because 60 halvings
    drive `mid` to within `inradius * 2**-60` of the collapse, where a region
    declared at a large offset has `min + mid == max - mid` in double precision
    and the constructor refuses its own eroded copy: measured, an 8 mm-thin
    keep-out at x = 1e5 raised `ContractError` after every boolean had been
    paid (round-3 review of #207).
    """
    lo, hi = 0.0, region.inradius()
    for _ in range(60):
        mid = (lo + hi) / 2
        if region.eroded_volume(mid) > epsilon(0.0):
            lo = mid
        else:
            hi = mid
    return lo


def _max_intrusion_depth(
    backend: Any, artifact: Any, region: Any
) -> tuple[float, float, bool] | None:
    """How far past its boundary the material reaches, as a proven lower bound.

    Volume is the wrong summary on its own: it scales with the AREA of the
    contact and only linearly with depth, so a hair-thin film over a large face
    outweighs a deep local spike, and 12.7 mm3 of faceting noise is
    indistinguishable from 81.0 mm3 of real interference — the two fixtures
    this PR measures, whose volumes differ by 6x while their depths differ by
    61x (#207).

    Posed as an EROSION rather than as a distance. #207 suggests "the largest
    distance any intruding vertex sits inside the region boundary", and that
    understates: depth is a min of linear functions, so it is concave, and a
    concave function's maximum over a polytope is generally interior — measured
    1.2798 mm against a rib built at exactly 1.500. The intersection is also
    non-convex in general, so there is no vertex guarantee at all.

    `sup{ r : the part still meets the region eroded by r }` has no such
    problem, and needs nothing new: `expand(-r)` is already the uniform inward
    offset for both region kinds — a cylinder's flats are TANGENT to the
    declared circle, so `d - 2r` moves every side plane inward by exactly `r` —
    and `intersect_volume` is the primitive the check already runs. Measured
    1.499999 on the same rib.

    Returns `(proven, resolution, saturated)`.

    `proven` is a genuine LOWER BOUND and nothing more: at that erosion the
    region still held measurable material, so the part reaches at least that
    deep. The search's upper end is NOT an upper bound and is not returned —
    it is where the remaining intersection fell below `epsilon(0.0)` mm3, which
    is small rather than empty, so the true depth sits above it by however far
    a sliver of that volume extends. Measured on exact AABB arithmetic: 4.995
    reported against a true 5.0, an error 8400x the search interval. Calling
    that pair a bracket "the depth was proven within" was false in the only
    direction that matters (adversarial review of #207).

    `saturated` says the search returned the deepest value it can return for a
    region this size — see `_search_ceiling`. Past that there is nothing left
    to test, so the number stops being a property of the breach and becomes one
    of the declaration, and the caller must not compare it to anything.

    `None` where the backend cannot answer, which the caller reports as no
    depth rather than as zero depth.
    """
    ceiling = _search_ceiling(region)
    if ceiling <= _DEPTH_TOLERANCE * 2**_MIN_RESOLVING_HALVINGS:
        # Below this the loop breaks on `_DEPTH_TOLERANCE` before it has
        # halved enough times for either number to mean anything, and both
        # come out wrong in the direction that overstates: a region 3e-6 mm
        # thick, breached to a third of its depth, reported "the whole depth
        # of the region", and one 1e-6 mm thick reported the same after ZERO
        # bisections (round-4 review of #207). No depth is the honest answer.
        return None
    lo, hi = 0.0, region.inradius()
    for _ in range(_DEPTH_BISECTIONS):
        if hi - lo <= _DEPTH_TOLERANCE:
            break
        mid = (lo + hi) / 2
        try:
            eroded = region.expand(-mid)
        except ContractError:
            # The eroded region is not REPRESENTABLE at these coordinates, which
            # is not the author's fault and is not a depth. `mid` is strictly
            # below the inradius, so in exact arithmetic the region still
            # encloses volume; what refuses it is that `min + mid` and
            # `max - mid` round to the same double. That needs an elongated
            # region — whose ceiling sits at its inradius, so the search probes
            # to within `inradius * 2**-23` of the degeneracy — declared where
            # the coordinate's ulp exceeds that: measured fine at x = 1e9 and
            # refused at x = 1e10, ~10 000 km out (#245).
            #
            # No depth rather than a ContractError blaming a legal declaration,
            # and rather than a zero that would read as "reaches nowhere" on a
            # clause that is failing. Bounding the probe below the ceiling was
            # the other candidate and does not reach this case at all.
            return None
        outcome = backend.intersect_volume(artifact, backend.region_solid(eroded))
        if isinstance(outcome, Unsupported):
            return None
        if float(outcome.value) > epsilon(0.0):
            lo = mid
        else:
            hi = mid
    # Saturation is judged on what was PROVEN, against the deepest value this
    # region can yield at all. Both halves were wrong before: judging on `hi`
    # missed the buried case entirely (the volume threshold drops `hi` below
    # the inradius even when the part fills the region), and comparing `lo` to
    # `inradius()` on a fixed 0.1% slack made the flag a discontinuous function
    # of the DECLARATION — a 8x8x8 mm keep-out fully buried in solid material
    # reported unsaturated while 8x8x7.99, the same breach, reported saturated
    # (round-2 review of #207). `_search_ceiling` is the exact bound, so the
    # slack is the search's OWN resolution -- `hi - lo`, which is
    # `inradius / 2**24` and exceeds `_DEPTH_TOLERANCE` for any region wider
    # than 33.6 mm. A fixed 1e-6 therefore failed to fire on most buried cubes
    # above 34 mm — 51% of integer sides in 34..100, 88% in 34..1000 — and,
    # being non-monotone in the size, reintroduced the discontinuity it had
    # just removed: side 50 flagged, 60 did not, 100 did,
    # 120 did not (round-3 review of #207). `hi - lo` alone, with no absolute
    # floor under it: where the region runs out first, this loop and
    # `_search_ceiling` are bisecting the SAME predicate, so their brackets
    # coincide and `lo` cannot fall further than one interval short. Against an
    # exact bound the `lo` and `hi` forms agree on every case measured.
    return lo, hi - lo, lo >= ceiling - (hi - lo)


def _run_region_check(
    spec: CheckSpec, backend: Any, artifact: Any, common: dict[str, Any]
) -> CheckResult:
    """Adjudicate a keep_out / keep_in region with its verification shell.

    The core claim and its anti-vacuity guard are decided together
    (SPEC-contract.md 4.4): a keep_out's region must hold no material AND its
    shell must not be entirely empty; a keep_in's region must be entirely
    material AND its shell must not be entirely solid. The pairing is what makes
    a deleted part fail a keep_out and a solid brick fail a keep_in.

    Every volume — including the region's own — is read through
    `intersect_volume`, never from a closed form. The mesh tier's booleans run
    on a float32 reconstruction (see `_manifold`), so a float64 closed-form
    total would disagree with a measured coverage by ~2e-7 relative — above the
    1e-7 comparison epsilon — and a fully-covered keep_in could fail on
    quantisation it did not cause. Measured against itself, the reconstruction
    cancels.
    """
    assert spec.region is not None and spec.shell is not None
    region = spec.region
    outer = region.expand(spec.shell)

    region_solid = backend.region_solid(region)
    outer_solid = backend.region_solid(outer)
    volumes = []
    for a, b in (
        (artifact, region_solid),
        (artifact, outer_solid),
        (region_solid, region_solid),
        (outer_solid, outer_solid),
    ):
        outcome = backend.intersect_volume(a, b)
        if isinstance(outcome, Unsupported):
            return _refused(common, outcome)
        volumes.append(float(outcome.value))
    in_region, in_outer, region_volume, outer_volume = volumes
    in_shell = max(0.0, in_outer - in_region)

    # Each clause's message describes only what that clause measured. The two
    # are independent and can fail together (a lone crumb of material inside
    # the region of an otherwise-deleted part fails both), so a message that
    # asserted the other clause's state would be false exactly on the worst
    # parts.
    intrusion: dict[str, Any] | None = None
    if spec.kind == "keep_out" and in_region > epsilon(0.0):
        # Only on the failing clause, and only for keep_out. Each bisection step
        # is a boolean, so a passing check pays nothing, and `keep_in`'s failure
        # is a DEFICIT of material rather than a breach — "how deep" is not the
        # question there.
        measured = _max_intrusion_depth(backend, artifact, region)
        # A box has no circumscription: its faces ARE the declared planes, so
        # nothing is discretised and there is no floor to compare against. Only
        # the cylinder's polygon stands proud of what was declared.
        floor = region.facet_floor() if isinstance(region, CylinderRegion) else 0.0
        if measured is not None:
            proven, resolution, saturated = measured
            intrusion = {
                "volume_mm3": in_region,
                # A lower bound, named as one. There is no upper: the search
                # stops on a volume threshold, not on emptiness.
                "min_depth_mm": proven,
                "search_resolution_mm": resolution,
                "detected_above_mm3": epsilon(0.0),
                "depth_limited_by_region": saturated,
                "facet_floor_mm": floor,
            }

    if spec.kind == "keep_out":
        failures = [
            _intrusion_sentence(in_region, intrusion) if in_region > epsilon(0.0) else None,
            f"no material lies within the {spec.shell:g} mm shell around the "
            f"region — an absent part satisfies the bare emptiness claim, so an "
            f"empty region alone is not evidence the feature exists"
            if not in_shell > epsilon(0.0)
            else None,
        ]
    else:
        deficit = region_volume - in_region
        shell_volume = max(0.0, outer_volume - region_volume)
        failures = [
            f"the region is missing {deficit:.6g} mm3 of the {region_volume:.6g} mm3 "
            f"of material it must contain"
            if deficit > epsilon(region_volume)
            else None,
            f"the entire {spec.shell:g} mm shell around the region is solid — an "
            f"unbounded block satisfies the bare solidity claim; nothing bounds "
            f"the feature this region describes"
            if not shell_volume - in_shell > epsilon(shell_volume)
            else None,
        ]

    failed = [f for f in failures if f is not None]
    return CheckResult(
        **common,
        status=Status.FAIL if failed else Status.PASS,
        measurement=Measurement((in_region, in_shell), "mm3", exact=True, axes=("region", "shell")),
        # The two clauses are this check's components, same shape as an
        # envelope's axes: the reader learns which side failed without parsing
        # the prose.
        components={
            "region": Status.FAIL if failures[0] is not None else Status.PASS,
            "shell": Status.FAIL if failures[1] is not None else Status.PASS,
        },
        detail="; ".join(failed) if failed else None,
        intrusion=intrusion,
    )


# --------------------------------------------------------------------------


def _backend_for(engine: str) -> Any:
    if engine == "openscad":
        from .backends.mesh import MeshBackend

        return MeshBackend()
    if engine in ("build123d", "cadquery"):
        from .backends.occt import OcctBackend

        return OcctBackend(engine)
    raise ContractError(f"unknown engine: {engine!r}")


def _engine_source(part: Part) -> Any:
    if part.source.engine == "openscad":
        from .engines.openscad import OpenSCADSource

        return OpenSCADSource(
            path=part.source.path,
            params=part.source.params,
            method=part.source.method,
            backend=part.source.backend,
        )

    from .engines.pycad import PyCADSource

    return PyCADSource(
        path=part.source.path,
        engine=part.source.engine,
        params=part.source.params,
        method=part.source.method,
    )


def _builds_spec() -> CheckSpec:
    return CheckSpec(id="builds", kind="builds", phase=GEOMETRY)


def _all_specs(part: Part) -> list[CheckSpec]:
    return [*part.checks, _builds_spec()]


_UNRESOLVED_NAME_CAUSE = "the engine could not resolve a name and rendered without it"
_UNRESOLVED_NAME_HINT = (
    "the engine exited 0 and wrote a mesh, so this is not a compile error — "
    "either the source misspells the name, or whatever defines it is not on "
    "OPENSCADPATH. Fix the name or install the library, then re-run"
)

_CSG_FILE_LITERAL = re.compile(r'\bfile\s*=\s*"([^"\n]*)"')


def _only_in_dropped_subtrees(
    source: Any, missing: tuple[Path, ...], out_dir: Path, timeout_s: float | None
) -> set[Path]:
    """Of `missing`, the entries the export provably did not depend on.

    OpenSCAD **evaluates** a `%` subtree -- so the file is resolved, the engine
    warns it could not open it, and the depfile records it -- and then excludes
    it from the export. Measured on both pinned engines: `cube([10,10,10]);
    %import("mate.stl");` exports the same bytes whether or not `mate.stl` is
    there. Refusing that is refusing more than the mathematics requires (#354
    review, B1); `*` never evaluates and never reaches the depfile at all, so it
    needs nothing here.

    **Why the `.csg` and not stderr.** The warning is worded identically for a
    `%`-ed and a plain `import()`, differing only in the line number, so the
    stderr route needs the line-number correlation #336 ruled against. The
    `.csg` carries the modifier next to the filename on both engines, and
    `csg.parse_csg` already drops `%` and `*` subtrees -- "a %-ed cutter is not
    part of the part" (PR #125 review, F2). The discriminator this needs is the
    one that parser already implements, for the same reason, so nothing in
    `csg.py` changes.

    **The export must be of the model that was BUILT, not of its defaults.**
    A modifier can be behind a parameter -- `if (ghost) { %import(f); } else {
    import(f); }` -- so an export taken without `-D` or without the method
    wrapper adjudicates a different tree than the one the depfile came from,
    and passes a run whose geometry is provably short (#354 round-2, B4). The
    entry is prepared exactly as `render()` prepares it, and a method scratch
    that cannot be written refuses rather than falls back to the defaults.

    **Joined by resolved path, not by suffix.** The depfile entry is
    `.resolve()`d, and the `.csg` literal is not the literal as written either:
    OpenSCAD re-expresses it relative to the ENTRY file's directory. Measured on
    an `import()` inside an included file, where the two engines even disagree
    about where it resolves -- 2021.01 writes `"mate.stl"` and the 2026.08.01
    snapshot `"lib/mate.stl"` -- and each engine's literal, resolved against the
    entry's parent, reproduces that same engine's own depfile entry. So
    `(base / literal).resolve()` is exact where a suffix match is not: a kept
    literal carrying `../` could not match its own resolved path, while a
    shorter dropped literal matched it by accident, and the run passed with a
    real build input missing (#354 round-2, B3).

    **Fail closed at every step.** An export that will not run, will not parse,
    or names no literal that resolves onto a `missing` entry returns nothing,
    and the caller refuses as before. The known parse failure is real and is
    why: the `.csg` prints string contents raw, so `text("say \"hi\"")` is a
    `CsgError` -- a false refusal there is the behaviour that already shipped,
    while a false pass would be the founding-property failure #309 exists to
    close.
    """
    import subprocess
    import tempfile

    from . import csg
    from .engines.openscad import _define_args, _method_scratch, find_executable

    if not missing:
        return set()
    executable = find_executable()
    if executable is None:
        return set()

    scratch: Path | None = None
    if source.method:
        prepared = _method_scratch(source, out_dir)
        if isinstance(prepared, BuildError):
            # No usable entry, so no evidence: refuse. Falling back to
            # `source.path` would export the module definitions without the
            # call that uses them, which is the wrong tree stated confidently.
            return set()
        scratch, render_path, defines = prepared, prepared, []
    else:
        render_path, defines = source.path, _define_args(source.params)

    # A deliberate duplicate of `lint.lint_scad_tier2`'s exporter, not a shared
    # helper. Factoring that out is a refactor of a second module for one
    # caller, and this one needs neither its per-rule refusal vocabulary nor its
    # raw-quote pre-check -- a quote here is simply a `CsgError`, which is
    # already the fail-closed answer. It does differ in one way that matters:
    # the contract's own budget is honoured, because this runs inside a `check`
    # the caller may have bounded with `--timeout` (#354 round-2, L8).
    try:
        with tempfile.TemporaryDirectory(prefix="partspec-csg-") as tmp:
            out = Path(tmp) / "tree.csg"
            try:
                proc = subprocess.run(
                    [executable, "-o", str(out), *defines, str(render_path)],
                    capture_output=True,
                    text=True,
                    timeout=effective_timeout(timeout_s),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return set()
            if proc.returncode != 0 or not out.is_file():
                return set()
            raw = out.read_text(encoding="utf-8", errors="replace")
            try:
                nodes = csg.parse_csg(raw)
            except csg.CsgError:
                return set()
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)

    def _kept(items: list, acc: set[str]) -> set[str]:
        for node in items:
            value = node.kwargs.get("file")
            if isinstance(value, str):
                acc.add(value)
            _kept(node.children, acc)
        return acc

    # Like against like: both sides are `file=` literals out of one `.csg`, so
    # the difference is exactly what the modifier removed. Reading the dropped
    # set off the raw text is the only way to see it -- the parser's whole job
    # here is to not return those nodes.
    kept = _kept(nodes, set())
    dropped = set(_CSG_FILE_LITERAL.findall(raw)) - kept

    base = Path(render_path).resolve().parent

    def _resolved(literals: set[str]) -> set[Path]:
        return {(base / lit).resolve() for lit in literals}

    kept_paths, dropped_paths = _resolved(kept), _resolved(dropped)
    # Exonerated only when the export names it in a dropped subtree AND nowhere
    # else. A file referenced from both is a build input, and an entry matching
    # neither set is unaccounted for and stays refused.
    return {f for f in missing if f in dropped_paths and f not in kept_paths}


def absent_build_inputs(
    engine_source: Any,
    deps: Any,
    out_dir: Path,
    timeout_s: float | None,
    relative_to: Path,
) -> list[str]:
    """Build inputs the engine asked for, could not open, and did not exclude.

    Shared by `check`, `measure` and `render` so one engine fact is not diagnosed
    three ways depending on the verb (#308's rule, #355).

    **The filter is the load-bearing half, not a refinement.** OpenSCAD evaluates
    a `%`-ed subtree, so an absent file inside one reaches the depfile exactly as
    a real dependency does -- `.missing` alone cannot tell them apart. Refusing on
    it would refuse a correct part, which is what `_only_in_dropped_subtrees`
    exists to prevent (#354 review, B1). Measured: `cube(...); %import("gone.stl");`
    and `cube(...); import("gone.stl");` produce identical `missing` entries, and
    only the second is a fault.

    Costs nothing on the ordinary path: `_only_in_dropped_subtrees` returns
    immediately when there is nothing missing, so the extra engine pass is paid
    only where a build input is already known to be absent.
    """
    if not deps.missing:
        return []
    unexported = _only_in_dropped_subtrees(engine_source, deps.missing, out_dir, timeout_s)
    return sorted(_relative(f, relative_to) or f.name for f in deps.missing if f not in unexported)


_ABSENT_INPUT_CAUSE = (
    "the engine asked for a build input that is not on disk and rendered without it"
)
_ABSENT_INPUT_HINT = (
    "the engine exited 0 and wrote a mesh, so this is not a compile error — "
    "an import()/surface() target the model names is absent, and OpenSCAD "
    "renders it as nothing. Create the file or fix the path, then re-run"
)

_SUBSTITUTED_VALUE_CAUSE = "the engine could not convert a value and built a default in place of it"
_SUBSTITUTED_VALUE_HINT = (
    "the engine exited 0 and wrote a mesh, so this is not a compile error — "
    "the warning names the module and the value it rejected, and that module "
    "built its own default instead. Nothing here is about the include path: "
    "trace the value back to whatever left it undefined or the wrong type, "
    "then re-run"
)

_DEFAULTED_VALUE_MARKER = "Unable to convert"
"""The one substitution marker for which a default is CERTAIN.

`engines.openscad._SUBSTITUTED_VALUE_MARKERS` carries two, measured on both
pinned engines, and only this one always means a default went in. The other,
`Problem converting rotate(`, substitutes nothing at all in ONE of its five
measured shapes -- 2021.01's `transform.cc` reads
`default: ok &= false; /* fallthrough */ case 3:`, so `rotate([90,0,0,0])`
has its first three components read and applied, and its export is
byte-identical (`cmp -s`, both pinned engines) to `rotate([90,0,0])`'s. One is
enough: the sentence asserts a MECHANISM, and a mechanism that did not occur
once is a sentence that is false once (#360). How many of the five leave a
correct mesh is a different count, and not the one this constant turns on.

Named here rather than imported because the choice being made is which
SENTENCE to print, which is this module's, and because the fallback is the
weaker one: a marker added to that tuple and not to this constant lands on the
sentence that claims less, not on the one that claims a mechanism nobody
observed. `_message` is borrowed rather than re-implemented so the test is
anchored at the head of the engine's own sentence -- unanchored, a model can
put this string in a literal and pick its own diagnosis (see
`_unresolved_lines`)."""

_UNUSABLE_VALUE_CAUSE = "the engine could not use a value as written"
_UNUSABLE_VALUE_HINT = (
    "the engine exited 0 and wrote a mesh, so this is not a compile error — "
    "the warning names the parameter the engine would not take as written, and "
    "stderr does not say what it did next: it may have applied the value "
    "anyway, substituted a default, or dropped the transform entirely. Nothing "
    "here is about the include path. The source is wrong either way "
    "(docs/FAILURE-MODES.md 9b): fix the parameter, then re-run"
)


def _unresolved_diagnosis(line: str) -> tuple[str, str]:
    """The (cause, hint) pair for one success-path marker line.

    One function and one set of strings for four callers, because `check`,
    `measure` and `render` refusing the same engine line must not drift into
    three accounts of it. Their SENTENCES differ -- a report's `error` against
    a refusal to measure or to draw -- and the cause and the remedy do not, so
    only the sentences live at the call sites.

    Three causes now. There was one until #308, which added a value the engine
    could not convert, so it substituted a default into a dimension: told to
    check `OPENSCADPATH` for that, a reader goes looking for a library that is
    not missing. Naming a name that did not resolve is equally wrong in the
    other direction, so the name text is unchanged and pinned.

    #333 then put `Problem converting rotate(` into the same marker tuple, and
    the substitution sentence was printed for it too -- asserting a default
    that an over-long `rotate` vector never takes, over an export that is
    byte-identical to the correct source's (#360). So the third cause: the
    engine could not use the value AS WRITTEN, which is all that line supports.
    The substitution text is unchanged for the marker it was measured on, and
    the weaker text is what an unrecognised substitution marker falls to.
    """
    from .engines.openscad import _message, is_substituted_value

    if is_substituted_value(line):
        if _message(line).startswith(_DEFAULTED_VALUE_MARKER):
            return _SUBSTITUTED_VALUE_CAUSE, _SUBSTITUTED_VALUE_HINT
        return _UNUSABLE_VALUE_CAUSE, _UNUSABLE_VALUE_HINT
    return _UNRESOLVED_NAME_CAUSE, _UNRESOLVED_NAME_HINT


def _skipped(spec: CheckSpec, reason: str) -> CheckResult:
    return CheckResult(
        id=spec.id,
        kind=spec.kind,
        phase=spec.phase,
        status=Status.SKIPPED,
        limit=spec.limit,
        expr=spec.expr if spec.kind == "requires" else None,
        operands={} if spec.kind == "requires" else None,
        region={**spec.region.to_json(), "shell": spec.shell} if spec.region is not None else None,
        hole=dict(spec.hole) if spec.hole is not None else None,
        source=dict(spec.source) if spec.source is not None else None,
        detail=reason,
    )


def _relative(path: Path | None, contract_path: Path | None) -> str:
    """A path expressed against the contract's directory, POSIX-separated.

    `part.source` was absolute after `_anchor` resolved it, so the committed
    example report leaked a developer home directory -- and two checkouts of the
    same tree at different locations produced different reports. That undoes at
    the path layer exactly the machine-independence `source_closure` was built
    to have: "a comparator's whole purpose is comparing runs from CI and a
    laptop".

    The contract's directory is the frame `_anchor` already resolves against, so
    this round-trips with no new concept. A source outside that subtree stays
    absolute and says so, rather than emitting a `../../..` chain that is no more
    portable and much harder to read.
    """
    if path is None:
        return ""
    if contract_path is None:
        return path.as_posix()
    base = contract_path.resolve().parent
    resolved = path.resolve()
    try:
        return resolved.relative_to(base).as_posix()
    except ValueError:
        return resolved.as_posix()


def _unit_for(value: Any) -> str:
    """Deliberately not inferred from the Python literal type.

    It used to be: `bool` and `int` gave "count", `float` gave "mm". So
    `plate_x=40` and `plate_y=30.0` came out as `count` and `mm` in the same
    report, on the same plate, and editing a declared parameter from `40` to
    `40.0` changed the recorded unit without changing the design -- the exact
    spurious drift SPEC-report.md 7.2 exists to keep out.

    No verdict was ever wrong (`adjudicate` never reads `unit`). What makes it
    worth fixing before the tag rather than after is that `schema_version: 1`
    freezes `measurement.unit` as a compatibility surface.

    v0 has one length unit, so `mm` is the default and a genuine count is
    declared with `p.param(..., unit="count")`.
    """
    return "mm"


def _render(limit: Limit) -> str:
    """Every form `Limit` defines, because it defines a CLOSED set.

    `choices` was missing and is unreachable through the contract API today —
    no check constructs one. It is rendered anyway rather than left out with a
    note: `Limit.__post_init__` guarantees at least one form is set, so the
    first check to use `choices` would otherwise render the empty string, and a
    line reading `measured "x", limit ` states a bound that is not there. A
    renderer over a closed set that handles three of its four members is the
    silent gap this project exists to refuse, waiting for a caller.

    Values go through `_number`, the same formatter the measurement uses, so
    the two halves of one comparison are in one notation. `choices` renders its
    members bare for the same reason: `repr` quoted a string that `equals`
    renders unquoted, so one value wore two spellings depending on which form
    held it.

    Joined with `and`, not a comma, because the caller puts a comma between the
    measurement and the limit — `measured 5640 mm3, limit min=1e6, max=2e6` has
    one separator doing two jobs, and `_failing_axes` already avoids that by
    joining axes with `;`. `choices` braces its members for the same reason: it
    is the one form with an internal list, so `limit one of a, b` reproduced
    the ambiguity two lines after removing it (round-2 review of #232).
    """
    parts = []
    if limit.min is not None:
        parts.append(f"min={_number(limit.min)}")
    if limit.max is not None:
        parts.append(f"max={_number(limit.max)}")
    if limit.equals is not None:
        parts.append(f"equals={_number(limit.equals)}")
    if limit.choices is not None:
        parts.append("one of {" + ", ".join(_number(c) for c in limit.choices) + "}")
    return " and ".join(parts)


def _digest(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _unmet_build_inputs(part: Part, closure: dict[str, Any]) -> list[str]:
    """Declared distributions that no entry of `imports` turned out to be.

    Compared on the NORMALISED name, because the entry is keyed as the
    installer spells it and the author may have written either form — matching
    raw strings would fail `cadquery_ocp` as "never imported" when it was
    imported, which is a false run-level error and worse than the silence it
    replaced.
    """
    resolved = {
        imports.normalize(name)
        for name, entry in closure.get("imports", {}).items()
        if entry.get("declared")
    }
    return [name for name in part.build_inputs if imports.normalize(name) not in resolved]


def _python_closure(
    source: Any,
    contract_path: Path | None,
    loaded_before: frozenset[str] = frozenset(),
    declared: tuple[str, ...] = (),
) -> dict[str, Any]:
    """The local modules a Python model actually imported.

    Scoped to the model's own directory, which is not an arbitrary boundary:
    `engines/pycad.py` puts exactly that directory on `sys.path` before exec'ing
    the model, precisely so a model can import helpers beside it. Those helpers
    are build inputs by design, and until now nothing recorded them — editing
    one changed the part and left `source_digest` identical, which is F13's
    failure class on the tier where it had not been closed.

    Read from `sys.modules` rather than parsed, so it reports what was imported
    instead of what appears importable. The contract file is excluded: it is
    already `contract_digest`, and folding it in here would make the *source*
    closure move whenever a claim changed.

    `imports` covers what the model imported from outside that directory —
    the third-party library a wrapper contract exists to check (#190). Without
    it the closure of the fleet-01 gridfinity bin was `files: 1`, and the
    seventeen files that produced the geometry appeared nowhere.

    `preloaded` names the entries of `imports` that were already in
    `sys.modules` when this target began, and it exists because `imports` is
    read from a **process** while the closure describes a **part**. Several
    targets share one interpreter, so a Python part behind another one
    inherits its imports: measured, the same build123d cube recorded 38
    imports alone and 44 behind a CadQuery target, `cadquery` among them.
    Keeping the over-report is deliberate — a snapshot delta would drop a
    library the second target genuinely uses because the first loaded it
    first, which is the under-reporting direction §8.3 refuses. So the map
    stays wide and this field says which of it this run cannot claim
    (SPEC-report §8.3 rule 7).

    `loaded_before` is the caller's snapshot of `sys.modules` from before the
    contract was resolved, because resolving it imports it and a contract's
    own imports ARE this part's. Empty by default, which is the truth for a
    process that runs one target — `measure`, `render` and MCP's
    subprocess-per-call — and what the `check` batch loop overrides per
    target.

    `partial` is derived from `unseen` and stays unconditionally true, because
    `native_reads` is always there: a C extension can read a file with no
    Python event to observe it, measured directly on `OCP.StlAPI_Reader`. An
    earlier draft of `SPEC-report.md` §8.3 concluded that this uncertainty
    argued for emitting nothing at all. That was the wrong call: silence is not
    the absence of a claim here, because `source_digest` is still sitting in the
    report asserting that one file identifies the build. A `partial` closure is
    the shape the spec already defines for known-incomplete coverage, and it
    makes a comparator treat sameness as inconclusive rather than proven.
    """
    root = source.path.resolve().parent
    excluded = {contract_path.resolve()} if contract_path is not None else set()

    members: set[Path] = set()
    roots: set[str] = set()
    for name, module in list(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path in excluded or not path.is_relative_to(root) or not path.is_file():
            continue
        members.add(path)
        # The model and the helpers beside it are where a reach walk starts:
        # they are this target's own code, whoever else is resident.
        roots.add(name)

    found = imports.inventory(
        skip_tree=root, exclude=frozenset(excluded), declared=frozenset(declared)
    )
    unseen = ["native_reads"]
    if any(entry["identity"] == imports.UNIDENTIFIED for entry in found.values()):
        unseen.append("unidentified_imports")

    hashes = sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in members)
    closure: dict[str, Any] = {
        "digest": "sha256:" + hashlib.sha256("".join(hashes).encode()).hexdigest(),
        "files": len(hashes),
        "scope": "model_directory",
        "partial": bool(unseen),
        "imports": found,
        "preloaded": sorted(imports.names_of(loaded_before) & found.keys()),
        "reached": sorted(imports.names_of(imports.reached_from(frozenset(roots))) & found.keys()),
        "unseen": sorted(unseen),
    }
    if declared:
        # Recorded even when it changed nothing (#215 Q3): a reader must be
        # able to tell coverage that was ASKED FOR from coverage that happened
        # to be free. Names as the author wrote them, so the report echoes the
        # contract rather than partspec's normalisation of it.
        closure["declared"] = sorted(declared)
    return closure


def _closure(source: Any, deps: Any = None) -> dict[str, Any] | None:
    """Digest every file the build reads, not just the entry point.

    OpenSCAD only — the Python tier is handled after its build, by
    `_python_closure`, because its imports are not knowable until the model has
    run.

    The digest is over **content hashes, sorted** — not over paths — so it is
    identical on two machines that check the same tree out at different
    locations. A comparator's whole purpose is comparing runs from CI and a
    laptop, and a path-sensitive digest would differ on every one of them.
    """
    if source.engine != "openscad" or not source.path.is_file():
        return None

    from .engines.openscad import include_closure

    closure = include_closure(source.path)
    covered = [f for f in closure.files if f.is_file()]

    # What the engine reported reading that the static walk could not see: the
    # `import()`/`surface()` targets. Resolved on both sides before comparing,
    # because a depfile echoes the invoked source as it was GIVEN while
    # `include_closure` resolves everything.
    engine_state = getattr(deps, "state", None)
    seen_paths = {f.resolve() for f in closure.files}
    data_files = [f for f in getattr(deps, "files", ()) if f.resolve() not in seen_paths]

    # Hashed into the digest, not merely listed. Naming a data file while
    # leaving it out of the digest would claim a coverage the digest does not
    # have: edit the STL and the closure would say `identical`. A model that
    # reads no external data has nothing here, so its digest is unchanged.
    covered += [f for f in data_files if f.is_file()]
    members = sorted(hashlib.sha256(f.read_bytes()).hexdigest() for f in covered)

    unseen = []
    if closure.reads_external_data and engine_state != "complete":
        # Dropped only on a COMPLETE engine report. `partial` is a floor on what
        # the render opened, and `absent` is not "nothing was read" — neither
        # closes the gap, and reading either as closure is the failure this
        # field exists to prevent.
        unseen.append("external_data_reads")
    if closure.unresolved:
        # `closure.unresolved`, deliberately, not `closure.unresolved_includes`
        # -- the token is a closed-vocabulary name in the REPORT (SPEC-report
        # §8) and covers `use` as well, which is what `diff` glosses it as. The
        # narrower field answers a different question (whether the entry's
        # top-level variable list got shorter) and shares only its spelling;
        # wiring this to it would silently narrow the report.
        unseen.append("unresolved_includes")

    out: dict[str, Any] = {
        "digest": "sha256:" + hashlib.sha256("".join(members).encode()).hexdigest(),
        "files": len(members),
    }
    if closure.unresolved:
        out["unresolved"] = list(closure.unresolved)
    if closure.reads_external_data:
        out["reads_external_data"] = True
    if engine_state is not None:
        # Framed against the MODEL's directory rather than the contract's:
        # OpenSCAD resolves `import()`/`surface()` relative to the entry file,
        # so that is the frame these paths are meaningful in — and relative
        # keeps them machine-independent, which is the property the whole block
        # is built to have.
        block: dict[str, Any] = {"state": engine_state}
        if data_files:
            block["data_files"] = sorted(_relative(f, source.path) or f.name for f in data_files)
        if deps.missing:
            # Listed by the engine and not on disk. A build input the model
            # asked for and did not get, which is strictly more than the
            # silence this field replaces.
            block["missing"] = sorted(_relative(f, source.path) or f.name for f in deps.missing)
        out["engine_inputs"] = block
    if unseen:
        # Stated positively so a consumer cannot mistake absence of the two
        # fields above for a guarantee it never made. Derived from `unseen`,
        # which names the same two gaps: `Closure.partial` is
        # `bool(unresolved) or reads_external_data`, so the boolean is
        # unchanged in every case (#190).
        out["partial"] = True
    # An empty map, never an absent one: this tier renders in a subprocess and
    # imports nothing, and that is a different statement from "not recorded",
    # which is what an absent `imports` means in a pre-0.7.5 report.
    out["imports"] = {}
    out["unseen"] = sorted(unseen)
    return out
