"""The report artifact: the thing that actually is the contract.

Per D5 the CLI verbs are not the product surface — the report schema plus the exit
code is. Everything else (an MCP layer, `diff`, CI annotations, a scorecard) is a
consumer of this file. So it is defined before any geometry, and it is written on
every terminal outcome including a crash.

Spec: SPEC-report.md sections 5, 6, 7, 8.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from .status import Limit, Measurement, Status, Verdict, exit_code, verdict_of

__all__ = [
    "SCHEMA_VERSION",
    "TOOL_VERSION_FALLBACK",
    "CheckResult",
    "Report",
    "tool_version",
    "write_placeholder",
]

SCHEMA_VERSION = 1
"""Bumped only on a breaking change. Adding a field is NOT breaking — consumers
must ignore unknown fields (SPEC-report.md 7.1) — so additive evolution is free.
Removing or re-typing one is breaking. Consumers must reject an unknown version
rather than best-effort parse it."""

REPORT_FILENAME = "report.json"


def _measurement_json(m: Measurement | None) -> dict[str, Any] | None:
    if m is None:
        return None
    out: dict[str, Any] = {
        "value": list(m.value) if m.is_vector else m.value,
        "unit": m.unit,
        "exactness": "exact" if m.exact else "approximate",
    }
    if m.bounds is not None:
        out["bounds"] = [list(b) for b in m.bounds] if m.is_vector else list(m.bounds)
    if m.axes is not None:
        out["axes"] = list(m.axes)
    return out


def _limit_json(limit: Limit | None) -> dict[str, Any] | None:
    if limit is None:
        return None
    out: dict[str, Any] = {}
    if limit.min is not None:
        out["min"] = limit.min
    if limit.max is not None:
        out["max"] = limit.max
    if limit.equals is not None:
        out["equals"] = limit.equals
    if limit.choices is not None:
        out["in"] = list(limit.choices)
    return out


IMPLICIT_CHECK_KINDS = ("builds",)
"""Check kinds partspec adds itself rather than the author declaring them.

Module-level because `diff` needs it too: it asks whether a report declared any
claim at all, and answering that with its own private copy is how the copy stops
matching (round-2 review of #239, which found the copy's stated rationale — "a
comparator must not import the writer's constants" — contradicted by `diff`
importing `SCHEMA_VERSION` from this module fifteen lines earlier)."""


@dataclass(slots=True)
class CheckResult:
    """One adjudicated claim.

    `measurement` is populated whenever the check was evaluated, *including when
    it passed*. That is non-obvious and load-bearing: it is what lets a future
    `diff` report drift on checks whose pass/fail state did not change. A wall
    thinning from 2.9mm to 2.1mm against a 2.0mm minimum is two passes and one
    very important trend, and nothing else in the system can see it.

    `expr` / `operands` replace measurement/limit for parameter predicates
    (SPEC-contract.md 5). Recording the operands means a failure reports the
    inputs that produced it rather than a bare `false`.
    """

    id: str
    kind: str
    phase: str  # "parameter" | "geometry"
    status: Status
    measurement: Measurement | None = None
    limit: Limit | None = None
    components: dict[str, Status] | None = None
    """Axis -> status for a vector check, so a failure names which component to
    act on instead of leaving a consumer to re-derive it from the vectors.
    Recorded on pass too (the §7.2 principle); an unconstrained axis is absent
    because an omitted claim has no status. Additive per §7.1."""
    expr: str | None = None
    operands: dict[str, Any] | None = None
    region: dict[str, Any] | None = None
    """The declared region and shell of a `keep_out` / `keep_in` check, so the
    report states what was claimed, not just how it went. Additive per §7.1."""
    intrusion: dict[str, Any] | None = None
    """How far a failing `keep_out` region clause was breached, and by how much.

    Volume alone cannot tell faceting noise from interference — it scales with
    the area of the contact and only linearly with depth (#207). Carries
    `volume_mm3`; `min_depth_mm`, a depth the material was PROVEN to reach with
    no upper bound implied; `search_resolution_mm` and `detected_above_mm3`,
    the two limits of the search that found it; `depth_limited_by_region`, set
    when the region ran out before the material did; and `facet_floor_mm`, how
    much intrusion this region's own faceting would show against a perfectly
    circular feature. Diagnostic, not adjudicated: the claim is
    still "no material here", and this says what the material did. Additive per
    §7.1.
    """

    edges: dict[str, Any] | None = None
    """Where a failing `watertight` check's mesh is open or non-manifold:
    `{"boundary": ..., "non_manifold": ...}`, each `{"count", "edges", "bbox"}`
    with up to 20 edges as coordinate pairs and the bounding box of all of them
    (#440). Mesh tier only, and diagnostic like `intrusion`. Additive per §7.1.
    """
    hole: dict[str, Any] | None = None
    """The declared bore of a `hole_diameter` check — `{"d": ..., "count": ...}`
    — on the same principle as `region`. Additive per §7.1."""
    source: dict[str, Any] | None = None
    """Provenance of referenced bounds: field -> {"standard", "subject",
    "field"} — the report states not just what was claimed but on whose
    authority (SPEC-contract.md 10). Absent for bare literals. Additive."""
    direction: list[float] | None = None
    """The declared pull axis of a `draft_angle` check (normalised), on the
    same what-was-claimed principle as `region` and `hole`. Additive per
    SPEC-report.md 7.1."""
    step: dict[str, Any] | None = None
    """The `step_roundtrip` exchange record — `{"schema": ...}` — because
    the writer schema changes the artifact (the F13 lesson). Additive per
    SPEC-report.md 7.1."""
    detail: str | None = None
    requires: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "phase": self.phase,
            "status": str(self.status),
            "measurement": _measurement_json(self.measurement),
            "limit": _limit_json(self.limit),
        }
        if self.components is not None:
            out["components"] = {axis: str(s) for axis, s in self.components.items()}
        if self.expr is not None:
            out["expr"] = self.expr
            out["operands"] = self.operands or {}
        if self.region is not None:
            out["region"] = self.region
        if self.direction is not None:
            out["direction"] = self.direction
        if self.step is not None:
            out["step"] = self.step
        if self.intrusion is not None:
            out["intrusion"] = self.intrusion
        if self.edges is not None:
            out["edges"] = self.edges
        if self.hole is not None:
            out["hole"] = self.hole
        if self.source is not None:
            out["source"] = self.source
        out["detail"] = self.detail
        if self.requires is not None:
            out["requires"] = self.requires
        return out


@dataclass(slots=True)
class Report:
    """A single part's result. One report per part, never per invocation."""

    part_id: str
    contract: str
    tool_version: str
    contract_digest: str | None = None
    source: str | None = None
    source_digest: str | None = None
    source_closure: dict[str, Any] | None = None
    """Every source file the build reads, not just the entry point.

    `source_digest` covers one file. For an OpenSCAD part that is routinely a
    small fraction of the input — the gridfinity bin in the dogfood corpus is
    one of sixteen — so two builds can share a `source_digest` and be different
    parts. This closes that for the engine where it was demonstrated; see
    `SPEC-report.md` §8.3 for what it does and does not cover.
    """

    engine: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    geometry: dict[str, Any] = field(default_factory=dict)
    renders: dict[str, str] = field(default_factory=dict)
    """View name -> image path, relative to the report's own directory.

    Populated only when a run actually produced images (`check --render`);
    absent otherwise — never an empty block, and never an empty-string path
    that reads as a file (SPEC-report.md §8.4). The images carry no verdict.
    """
    render_bbox: dict[str, Any] | None = None
    """The framing bbox (`{min, max}`, mm) when the run produced renders:
    framing scales with the part, so two sizes render identical pixels and
    the bbox is the scale witness a visual diff needs (#21)."""
    render_tessellation: dict[str, Any] | None = None
    """`{tolerance_mm, triangles}` when the renders came from a tessellation
    (the OCCT tier, #18) — under D15 the tessellation is what was shown, so
    its quality rides with the images. Absent for OpenSCAD renders, where the
    engine draws its own geometry."""
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None
    hint: str | None = None
    build_origin: str | None = None
    """Why a build failed, when one did: `"environment"` or `"model"`.

    A field rather than prose in `detail`, so a consumer can branch on it. A
    design that does not compile is a statement about the part; no engine on
    PATH is not, and reporting both as `builds: fail` told a CI run with no
    OpenSCAD installed that the design was disproven.
    """
    build_stderr: str | None = None
    """The engine's full stderr when a build failed — the unabridged version
    of `hint`, so a filtered hint can never lose the diagnosis (#37)."""
    duration_ms: int | None = None
    argv: list[str] = field(default_factory=list)
    expectation: dict[str, Any] | None = None
    """The claims-pin adjudication (#31), present only when a run was invoked
    with `--expect`: `{claims, matched[, differences]}`. In the artifact and
    not just on stderr for the same reason `attribution` is — the audience of
    "this contract is not the one reviewed" reads reports, not consoles."""
    timeout_s: float | None = None
    """The build budget this run was invoked with, in seconds — the requested
    value, before `effective_timeout` resolves it (so `0` records an explicit
    waiver and `null` records that no caller chose). A run stopped by its
    budget must be attributable to that budget from the artifact alone."""

    IMPLICIT_KINDS = IMPLICIT_CHECK_KINDS
    """Checks partspec adds itself. They are real results, but they are not
    something the author *asserted*, so they must not satisfy the emptiness
    test — see `verdict`. Aliases the module-level constant, which `diff` reads
    too: two copies of this list is how one of them stops matching."""

    @property
    def verdict(self) -> Verdict:
        """Verdict, with the vacuous-green guard applied to *declared* checks.

        `builds` is added by the tool, so a contract that asserts nothing still
        produces one passing check. Counting it toward emptiness would let the
        single most important guard in the tool be defeated by the tool itself:
        a contract with no claims would exit 0 and read as a proven part.
        """
        if self.error is not None:
            return Verdict.ERROR
        declared = [c for c in self.checks if c.kind not in self.IMPLICIT_KINDS]
        if not declared:
            return Verdict.EMPTY
        return verdict_of([c.status for c in self.checks])

    @property
    def exit_code(self) -> int:
        return exit_code(self.verdict)

    def attribution(self) -> dict[str, int]:
        """How many dimensional checks there are, and how many carry a source.

        Run-level and in the artifact, because the artifact is the product
        surface: the CLI warning derives from this, and an MCP consumer —
        exactly the agent #50's motivating scenario describes — reads the
        report, never stderr. `dimensional > 0 and attributed == 0` is the
        circular-contract signal; deriving it any other way would require the
        consumer to know DIMENSIONAL_KINDS, which the report does not carry.
        """
        from .contract import DIMENSIONAL_KINDS

        dimensional = [c for c in self.checks if c.kind in DIMENSIONAL_KINDS]
        return {
            "dimensional": len(dimensional),
            "attributed": sum(1 for c in dimensional if c.source is not None),
        }

    def counts(self) -> dict[str, int]:
        """Status tally. `total` equals len(checks) and the five statuses sum to it.

        Redundant by construction and emitted anyway: it is the cheapest signal
        that a contract lost checks between two runs.
        """
        tally = {s.value: 0 for s in Status}
        for c in self.checks:
            tally[c.status.value] += 1
        return {"total": len(self.checks), **tally}

    def to_json(self) -> dict[str, Any]:
        """Serialise in the field order the spec fixes (SPEC-report.md 8.1)."""
        part: dict[str, Any] = {"id": self.part_id, "contract": self.contract}
        if self.contract_digest:
            part["contract_digest"] = self.contract_digest
        if self.source:
            part["source"] = self.source
        if self.source_digest:
            part["source_digest"] = self.source_digest
        if self.source_closure:
            part["source_closure"] = self.source_closure

        # `payload` names WHICH artifact this is (#295). `measure` and
        # `render` share this identity prefix by design, so until this field
        # existed the three were distinguishable only by guessing from the keys
        # further down: same `tool.name`, same `schema_version`, three shapes.
        # Additive, so every report written before it has none and a consumer
        # MUST tolerate its absence (SPEC-report.md 7.1).
        doc: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "payload": "report",
            "tool": {"name": "partspec", "version": self.tool_version},
            "part": part,
            "engine": self.engine,
            "params": self.params,
            "geometry": self.geometry,
        }
        if self.renders:
            doc["renders"] = self.renders
            if self.render_bbox is not None:
                doc["render_bbox"] = self.render_bbox
            if self.render_tessellation is not None:
                doc["render_tessellation"] = self.render_tessellation
        doc |= {
            "verdict": str(self.verdict),
            "counts": self.counts(),
            "attribution": self.attribution(),
        }
        if self.expectation is not None:
            doc["expectation"] = self.expectation
        doc |= {
            "checks": [c.to_json() for c in self.checks],
            "error": self.error,
            "hint": self.hint,
            "build_origin": self.build_origin,
            "build_stderr": self.build_stderr,
            "environment": self._environment(),
            "invocation": {"argv": self.argv, "timeout_s": self.timeout_s},
        }
        return doc

    def _environment(self) -> dict[str, Any]:
        """Volatile data, quarantined by field rather than by block.

        Only `duration_ms` and `platform` vary between two runs of identical
        inputs. There is no `timestamp` field: its absence is what lets a
        comparator quarantine volatility field-by-field (SPEC-report §8 rule 2
        names `duration_ms`) instead of excluding the whole block. The report
        is NOT byte-reproducible — `duration_ms` alone sees to that.

        `packages` deliberately does NOT vary — it is exactly what
        distinguishes "a dependency upgrade moved this number" from "the design
        changed", so a comparator that excludes the whole block loses the ability
        to explain its own findings.

        That non-variance is why `packages` enumerates what is *installed* and
        not what this process imported. Several targets share one interpreter
        (`cli.py`'s batch loop), so an import-keyed field would make a part's
        recorded environment depend on which unrelated target ran before it:
        measured, the OpenSCAD-tier `examples/spacer` recorded 6 distributions
        alone and 41 in a batch behind a build123d part — the same part, the
        same venv, the same second, and `diff` reporting 35 packages
        "appeared". An environment is a property of the venv. What *this part*
        loaded belongs in `part.source_closure`, which is where byte-level
        identity lives — and which reads the same shared `sys.modules`, so it
        over-reports in a batch and names what it cannot attribute in
        `preloaded` (SPEC-report §8.3 rule 7). Scoping the question to the
        part is what made that bound statable; it did not remove it (#190).
        """
        env: dict[str, Any] = {
            "python": platform.python_version(),
            "packages": _installed_versions(),
            "platform": f"{sys.platform}-{platform.machine()}",
        }
        if self.duration_ms is not None:
            env["duration_ms"] = self.duration_ms
        return env

    def write(self, directory: Path) -> Path:
        return _write_json(directory / REPORT_FILENAME, self.to_json())


@cache
def _installed_distributions() -> tuple[tuple[str, str], ...]:
    """Every distribution installed in this environment, name and version.

    One pass over the `dist-info` metadata on `sys.path`. First occurrence
    wins, matching `importlib.metadata.version()`, which resolves against the
    same order — so the report and a hand-run `version()` cannot disagree.

    Cached for the life of the process, which is sound precisely because the
    answer does not depend on process state: nothing installs a distribution
    between two targets of one `partspec check`. The MCP layer gets no benefit
    — it runs the CLI as a subprocess per call by design — so it pays the cold
    cost every time.

    Returned as a tuple of pairs, not a dict: a cached mutable value reaches
    the report artifact by reference, and one caller's edit would silently
    rewrite every later report's environment.
    """
    from importlib.metadata import distributions

    found: dict[str, str] = {}
    for dist in distributions():
        metadata = dist.metadata
        name, dist_version = metadata["Name"], metadata["Version"]
        if not name or not dist_version or name in found:
            continue
        found[name] = dist_version
    # Sorted: SPEC-report §8 rule 1 — a derived collection is ordered by a
    # stated key, here the distribution name.
    return tuple(sorted(found.items()))


def _installed_versions() -> dict[str, str]:
    """The distributions installed in this environment, name -> version.

    Widened from a hardcoded five-name allowlist of engine packages
    (`build123d`, `cadquery`, `cadquery-ocp`, `trimesh`, `manifold3d`), which
    could not see the library a contract wraps: the fleet-01 study that
    produced #190 evaluated `cqgridfinity`, and no report it wrote ever named
    it, so a bump of the one dependency the part had moved a measurement with
    nothing in the report to explain it (#211).

    Keyed on what is **installed**, not on what this process imported. The
    field lives in the `environment` block and SPEC-report §8 rule 2 admits
    only `duration_ms` and `platform` as varying between two runs of identical
    inputs; a `sys.modules`-derived value fails that, because the batch loop
    shares one interpreter and a part would inherit whatever an unrelated
    earlier target happened to import. What *this part* loaded belongs to
    `part.source_closure` (#190), not to the environment — where the shared
    interpreter is stated as a bound rather than escaped (§8.3 rule 7).

    Measured on this repo's 114-distribution full-extras venv: 57 ms cold (page
    cache evicted), 26 ms warm; on the fleet's 84-distribution cadquery venv,
    45 ms cold, 25 ms warm. Cold matters most on the OpenSCAD tier, where a
    ~0.5 s run has no 956 ms build to hide behind.
    """
    return dict(_installed_distributions())


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    """Write atomically: temp file in the destination directory, then rename.

    A partially written report that happens to parse is worse than none.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".partspec-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # allow_nan=False: a bare NaN/Infinity literal is not JSON and no
            # conforming parser will read it back. Measurement refuses
            # non-finite values already; this is the backstop that keeps an
            # unreadable artifact from ever reaching disk.
            json.dump(payload, fh, indent=2, allow_nan=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def write_placeholder(
    directory: Path, *, contract: str, argv: list[str], part_id: str = "unresolved"
) -> Path:
    """Write an `error` report BEFORE the engine is invoked.

    A try/finally cannot survive a native fault: an OCP segfault or an OOM kill
    takes the process down with no Python unwinding, leaving yesterday's
    `verdict: "pass"` sitting at a deterministic path where both a human and an
    agent will trust it. Writing this first means the worst case is a report
    saying the run died — never one saying the part was fine.

    Only the in-process OCCT tier is exposed to a native fault; OpenSCAD runs as
    a subprocess whose crash the parent observes normally. The placeholder is
    written regardless, because the cost is one file write.

    `part_id` defaults because this is written **before the contract is
    resolved**, and resolving is itself something that can fail: a contract that
    raises on import never produced a part id, and used to leave the previous
    run's report untouched for exactly that reason. A run that got far enough to
    name its part overwrites this with the real id.
    """
    payload = Report(
        part_id=part_id,
        contract=contract,
        tool_version=tool_version(),
        argv=argv,
        error="run did not complete: no result was written for this run",
        hint="the contract failed to resolve, or the process died before finishing "
        "(a native segfault/OOM in the CAD kernel)",
    ).to_json()
    return _write_json(directory / REPORT_FILENAME, payload)


TOOL_VERSION_FALLBACK = "0.0.0+unknown"
"""What the tool calls itself when it is not installed — a source tree.

Public and single because it was written three times, in three modules, with
the fallback spelled two ways and the function named two ways, and the string
reaches the artifact as `tool.version`. Two copies drifting is a provenance
defect: a report would claim a version the run did not have.
"""


def tool_version() -> str:
    """The installed version of partspec, for the artifact's provenance."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("partspec")
    except PackageNotFoundError:  # running from a source tree without an install
        return TOOL_VERSION_FALLBACK
