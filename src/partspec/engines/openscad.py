"""Render an OpenSCAD source to a mesh.

Deliberately does not parse `--summary` (D13). That flag omits volume and area
entirely, its `facets` field means different things depending on the render
backend, and — the reason it is banned rather than merely unhelpful — on invalid
geometry it emits JSON with the validity key *absent* while exiting 0. A checker
doing `.get("simple", True)` therefore passes a broken part silently. Export the
mesh and measure that instead; trimesh catches the same case immediately.

Ignoring `--summary` has a second benefit: it removes any reason to care whether
the installed OpenSCAD is the 2021.01 stable or a current nightly, so no nightly
install is a prerequisite.

Spec: SPEC-backend.md section 5, SPEC-contract.md section 3.1.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from ..backend import DEFAULT_TIMEOUT_S, BuildError

__all__ = [
    "Closure",
    "OpenSCADSource",
    "find_executable",
    "include_closure",
    "is_substituted_value",
    "render",
    "render_views",
    "scad_literal",
]


@dataclass(frozen=True, slots=True)
class OpenSCADSource:
    """An OpenSCAD file plus the parameters to build it with."""

    path: Path
    params: dict[str, Any] = field(default_factory=dict)
    method: str | None = None
    """When set, parameters are passed as arguments to a call to this module,
    via a throwaway scratch entry that includes the source. Otherwise they
    override top-level variables via -D. The source file is never modified
    either way."""

    backend: str | None = None
    """OpenSCAD render backend: "Manifold", "CGAL", or None for the engine's
    default (Manifold on current builds, CGAL on 2021.01).

    Selectable because it **changes the artifact**, not merely its speed.
    Measured on a community gridfinity bin: the Manifold backend produced a mesh
    with 4 non-manifold edges where CGAL produced a clean one, from identical
    source. The flag does not exist on 2021.01, so it is only passed when set.
    """


def scad_literal(value: Any) -> str:
    """Render a Python value as an OpenSCAD literal.

    bool is checked before int because in Python `bool` subclasses `int`, so the
    obvious ordering silently turns `True` into `1`. (PartCAD's implementation
    carries the same note, having presumably been bitten by it.)
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    if isinstance(value, Sequence):
        return "[" + ", ".join(scad_literal(v) for v in value) + "]"
    if value is None:
        return "undef"
    raise TypeError(f"cannot render {type(value).__name__} as an OpenSCAD literal: {value!r}")


ENV_EXECUTABLE = "PARTSPEC_OPENSCAD"

# Said "use a 2022+ build with EGL offscreen" until #276's review: a remedy
# naming no way to obtain it, since 2021.01 is the newest OpenSCAD RELEASE
# there has ever been and anything with EGL offscreen is a development
# snapshot. The address is in the hint and not just the README because the
# coupling test can only hold it to what it names — the old wording passed
# that test untouched, `2022+ build` being prose it never looked at.
NO_DISPLAY_HINT = (
    "run under `xvfb-run -a`, or use a development snapshot from "
    "https://files.openscad.org/snapshots/ — 2021.01 has no EGL offscreen path and is "
    "the newest release there is"
)

# The remedy for the likeliest first-run failure there is, so it has to resolve
# from a stranger's machine. It named `workstation-configs` until #276 — the
# maintainer's provisioning repo, which appears in no README, carries no URL,
# and grep finds nowhere else in this tree. install.py states the standard it
# was failing: naming a problem and handing over an answer that does nothing is
# a quieter version of naming a problem and withholding the answer.
#
# One constant because there were two copies of the string and they are read on
# the same fault. `install_hint()` is no help here: it picks between pip and uv
# for a Python package, and this is a system binary.
#
# `openscad@snapshot` and not the bare `openscad` cask: the latter is already
# deprecated (`fails_gatekeeper_check`) and Homebrew disables it on 2026-09-01,
# after which the command errors and installs nothing. It is also an Intel-only
# dmg wanting Rosetta, and it `conflicts_with` the snapshot cask -- so the bare
# form would send a mac reader to a dead end and then block the way out of it.
# openscad.org/downloads.html recommends the snapshot cask for the same reason.
NOT_FOUND_HINT = (
    "install it — `sudo apt install openscad`, `brew install openscad@snapshot`, or a "
    "build from https://openscad.org/downloads.html — or set PARTSPEC_OPENSCAD to an "
    "existing binary"
)


def find_executable() -> str | None:
    """Locate the openscad binary.

    `PARTSPEC_OPENSCAD` wins if set, because **the engine version changes the
    artifact**. Measured on a gear library from `most-scad-libraries`: OpenSCAD
    2021.01 honours the removed `assign()` construct and 2026.08.01 ignores it,
    so the same source yields 648 triangles / 44463 mm3 on one and 120 / 28760
    on the other — a part 35% smaller in every planar dimension. Both exit 0 and
    write clean watertight meshes.

    Deliberately an environment variable rather than a contract field: which
    binary is installed is a property of the *machine*, not of the design. The
    render backend is the opposite — a design choice — and lives in the contract.
    The version is recorded in every report either way.

    Only two rules, in this order: the pin, then `PATH`. An earlier version also
    preferred `~/Applications/openscad/OpenSCAD-nightly.AppImage` — a convenience
    for one machine that had no business in library code. It meant `which
    openscad` reported 2021.01 while every render silently used 2026.08.01, on a
    tool whose own finding is that the version changes the part. A build whose
    engine is chosen by an undeclared path is the thing this function exists to
    prevent; set the pin instead, where the choice is visible.
    """
    pinned = os.environ.get(ENV_EXECUTABLE)
    if pinned:
        return pinned
    return shutil.which("openscad") or shutil.which("openscad-nightly")


def _define_args(params: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for name, value in params.items():
        args.append("-D")
        args.append(f"{name}={scad_literal(value)}")
    return args


def _method_call_source(source: Path, method: str, params: dict[str, Any]) -> str:
    """A scratch entry that includes the source and appends the call.

    An `include <>` of the absolute source path, not a copy of the body:
    OpenSCAD resolves nested `include`/`use` relative to the file *containing*
    the statement, so the source's own relative includes keep working wherever
    the scratch lives. The idea is PartCAD's — invoke a parameterised module
    without the file having a top-level call, never mutating the file.
    """
    args = ", ".join(f"{k} = {scad_literal(v)}" for k, v in params.items())
    return f"include <{source.resolve()}>\n{method}({args});\n"


def _method_scratch(source: OpenSCADSource, out_dir: Path) -> Path | BuildError:
    """Write the scratch entry, preferring the out dir over the source tree.

    The artifact under inspection and the inspector's scratch space must not
    share a directory (#39): the old in-tree copy crashed uncaught on a
    read-only source dir and left a tmp file for any watcher or `git add -A`
    to see. So the entry normally lives under the out dir, `.partspec-`
    prefixed per the report writer's convention.

    One measured exception. Relative `import()`/`surface()` data files
    resolve against the MAIN entry file's directory — not the file containing
    the statement — so an out-dir entry breaks exactly the sources
    `include_closure` flags as `reads_external_data` (adversarial review,
    live on 2021.01: `surface(file = "data.dat")` looked for the file in the
    out dir). Those sources keep their entry beside the source, uniquely
    named, and a read-only source dir becomes a *named* refusal instead of a
    traceback.
    """
    assert source.method is not None
    if ">" in str(source.path.resolve()):
        # `include <>` has no escape syntax; a path OpenSCAD cannot express
        # must refuse here, not surface as "Can't open include file" blaming
        # the model.
        return BuildError(
            f"the source path {source.path.resolve()} contains '>', which an OpenSCAD "
            f"include <> cannot express",
            origin="environment",
        )
    body = _method_call_source(source.path, source.method, source.params)
    if include_closure(source.path).reads_external_data:
        import tempfile

        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=".partspec-", suffix=".scad", dir=source.path.parent
            )
        except OSError as exc:
            return BuildError(
                f"could not write the method scratch file in {source.path.parent}: {exc.strerror}",
                origin="environment",
                hint="this source reads external data files (import()/surface()), which "
                "resolve against the entry file's directory — the scratch must sit beside "
                "the source, and that directory is not writable",
            )
        # `os.fdopen` on the descriptor mkstemp handed back — `Path.open` takes
        # a path and would reopen by name, losing the atomic create. Spelled the
        # way `report._write_json` already spells it, which needs no suppression.
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        return Path(tmp_name)
    scratch = out_dir / f".partspec-{source.path.stem}-{source.method}.scad"
    try:
        scratch.write_text(body, encoding="utf-8")
    except OSError as exc:
        return BuildError(
            f"could not write the method scratch file in {out_dir}: {exc.strerror}",
            origin="environment",
        )
    return scratch


def _output_over_an_input(
    source: OpenSCADSource, stl: Path, closure: Closure, *, would_overwrite: bool
) -> BuildError | None:
    """Refuse, before rendering, when the artifact would land on a file that
    may be an input and nothing later can say whether it is.

    Building in a scratch directory keeps the MEASUREMENT honest — the engine
    reads whatever inputs are on disk, because nothing has been removed — but
    the move into place still writes `<stem>.stl` over whatever holds that
    name, and where the model reads that file the NEXT run measures something
    else. #208's repro is exactly that: `part.scad` imports `part.stl`, a
    destination of the source's own directory derives `part.stl`, and after
    the run the input is the output. Under `check` it was worse than a wrong
    number — a PASS verdict on geometry that was not the part.

    **This guard used to carry that case and no longer does.** An
    `import()`/`surface()` target is named in the engine's own dependency
    output, so #263 moved the question to `_wrote_over_an_input`, which is
    asked after the render and answers exactly which files were read. What is
    left here is the arm no depfile can reach: an **unresolved include**, which
    is listed nowhere at all because the depfile names what was opened and
    never what was asked for. partspec cannot see inside a file it could not
    find, so it cannot know whether that file imports data either — and no
    later signal will tell it. The narrowest condition is all three of:

    1. the destination is the directory the source's relative
       `import()`/`surface()` paths resolve against — its own;
    2. `<stem>.stl` is already there to be destroyed;
    3. an include did not resolve, so inputs exist that partspec cannot
       enumerate and the engine will not enumerate for it.

    (1) and (2) together are `would_overwrite`, which the caller computes
    before anything is written and hands to both guards — the post-render one
    falls back on exactly this condition when the engine cannot name its
    inputs, and by the time it runs, this call has created the file it would
    be asking about.

    Each clause is load-bearing in the direction of NOT over-refusing. Without
    (1) the second run of any such model against the default `outputs/<part-slug>`
    finds run 1's own artifact there and is refused — the ordinary path,
    broken. Without (2) a first run into the source directory is refused over a
    file that does not exist. Without (3) any model rendering twice into its
    own directory is refused on the second run.

    **What clause (1) used to cost, and no longer does.** Scoped this way, the
    old guard under-refused, and the cost was not one file. Where the import
    sat in a subdirectory — `import("sub/part.stl")` with `--out sub` — the
    artifact was REPLACED at that path rather than deleted, so the import still
    resolved and the model ate its own output. Measured then, three identical
    consecutive runs against a 3x7x11 donor:

        run 1  exit 0  bbox [8, 7, 11]   (correct)
        run 2  exit 0  bbox [13, 7, 11]
        run 3  exit 0  bbox [18, 7, 11]

    and `check` with a claim that is FALSE of the real part — `envelope(min=(12,
    7, 11))` — failed at run 1 and **passed at run 2**. So the residue was an
    unbounded series of confident wrong answers — at exit 0 for `measure`, and
    for `check` a verdict computed on geometry that is not the part, whichever
    way the claim points. That is #208's own headline symptom surviving in a
    narrower case, and it is what the post-render guard exists to end: the
    subdirectory import is in the dependency list by full resolved path, so the
    replace is refused wherever the destination sits.

    Scanning the closure for the destination's NAME was the precise alternative
    considered and rejected at the time: it resolves nothing when the path is
    computed, which is the case `reads_external_data` exists to admit, so it
    would refuse in the easy case and stay silent in the hard one. The remedy
    was always a signal that says which files a render actually READ, and that
    signal now exists.
    """
    if not would_overwrite:
        return None
    reason = closure.unresolved_reason
    if reason is None:
        return None
    return BuildError(
        f"the build artifact for {source.path.name} would be written to {stl.resolve()}, "
        f"in the model's own directory, but {source.path.name} {reason}, so partspec "
        f"cannot account for every input and cannot prove {stl.name} is not one of them",
        hint=f"pass an output directory other than the model's own ({source.path.parent}) "
        f"— the artifact lands in it as {stl.name}",
        origin="environment",
    )


def _wrote_over_an_input(
    deps: RenderDeps,
    dest: Path,
    name: str,
    *,
    closure: Closure,
    refuse_unanswered: bool,
    what: str = "build artifact",
) -> BuildError | None:
    """Refuse the move into place when the render itself read `dest`.

    Asked AFTER the render, which is the only time it can be answered, and
    asked only of a model whose closure is PARTIAL — for one that is not, every
    file the engine can reach is a `.scad` partspec has already walked, and the
    destination is an `.stl` no part of it names.

    Partial rather than `reads_external_data`, because the unresolved arm is
    not merely a case the depfile happens to cover as well. An `include` that
    partspec cannot find on ITS search path may resolve on the engine's, and
    the file behind it may hold the `import()` partspec then never saw — so a
    closure reporting `reads_external_data: False` is not a promise that the
    render read no data. It is the depfile, not the regex, that knows.

    **Nothing has been replaced yet**, which is what makes a late refusal
    correct rather than merely tidy: both movers stage into a scratch directory
    and this runs before the rename, so the caller's file is exactly as it was.
    What it costs is a render, and the message says so — the caller could not
    have known, and an error implying otherwise sends them looking for a
    mistake they did not make.

    **`refuse_unanswered` is what to say when the engine did not answer**, and
    it is not a preference: it is the caller keeping its own old behaviour for
    the case this cannot improve on. An engine with no `-d` writes no depfile,
    so `deps` is `absent` — which is not "the render read nothing"
    (`RenderDeps`) — and the exact question is unanswerable there exactly as it
    was before #226. So `render` passes the pre-render answer its conservative
    guard would have given (destination in the model's own directory, name
    already taken), and `cli._build_to_file` passes True, because a
    caller-named file destination was never provable and its refusal is the one
    #208 shipped. Neither loosens on an engine that cannot answer; both become
    exact on one that can.

    **A complete list that CONTRADICTS the source is not an answer either**, and
    this is F13 arriving in a guard. `import_stl()` is deprecated; 2021.01 still
    executes it and the 2026.08.01 snapshot ignores it — so for one source the
    depfile names the data file on one engine and omits it on the other, and
    taking the second at face value would hand back "safe to write" for a file
    the same contract reads on the machine next to it. Where the closure says
    the source reads external data and the render read none, the two disagree,
    and a disagreement is treated exactly as no answer at all: `refuse_unanswered`
    decides, so both callers keep the answer they gave before #263.

    It over-refuses by that clause alone — an `import()` inside a branch the
    render never took reads nothing legitimately — and that is the direction to
    err in, because the cost of the other one is the caller's data.

    `partial` is unreachable from both call sites — a failed render returns
    before either mover is reached — and refuses under the same flag if that
    ever changes.
    """
    if deps.state != "complete":
        if not refuse_unanswered:
            return None
        return BuildError(
            f"the engine did not report the files it read, so partspec cannot prove "
            f"{dest.name} is not one of {name}'s inputs — and {name} reads external "
            f"data (import()/surface())",
            hint=f"this engine does not accept -d, so nothing can name the render's "
            f"inputs; write the artifact somewhere {name} cannot be reading — a "
            f"directory that holds none of its inputs",
            origin="environment",
        )
    if dest.resolve() not in deps.files:
        if not _contradicts(deps, closure):
            return None
        if not refuse_unanswered:
            return None
        return BuildError(
            f"{name} reads external data (import()/surface()) and this render read "
            f"none, so the engine's account of its inputs contradicts the source and "
            f"cannot say whether {dest.name} is one of them",
            hint=f"this engine may ignore the form the source uses, or the read may sit "
            f"in a branch the render did not take; write the artifact somewhere {name} "
            f"cannot be reading — a directory that holds none of its inputs",
            origin="environment",
        )
    return BuildError(
        f"the render of {name} read {dest.resolve()}, so writing the {what} "
        f"there would destroy one of its own inputs — the next run would measure "
        f"this run's output",
        hint=f"only the engine's own dependency list can answer this, so it took a "
        f"render to find out; nothing has been written — name a destination {name} "
        f"does not read",
        origin="environment",
    )


def _contradicts(deps: RenderDeps, closure: Closure) -> bool:
    """The source says it reads data and the render read none of it.

    "None of it" is measured against the static closure: every `.scad` the
    walker already found is subtracted, and what is left is what the render
    opened that no include accounts for — the data files. An empty remainder
    beside `reads_external_data` is the disagreement.
    """
    if not closure.reads_external_data:
        return False
    walked = {f.resolve() for f in closure.files}
    return not any(f.resolve() not in walked for f in deps.files)


def _still_unbound(
    source: OpenSCADSource, unbound: list[str], closure: Closure, deps: RenderDeps
) -> BuildError | None:
    """Ask the parameter question again, from the files the engine opened (#311).

    `unbound` is what the STATIC walk could not account for, on a source whose
    walk was short a file. That verdict is not a fact about the part until the
    list it was drawn from is whole: the engine resolves libraries partspec
    cannot see -- the pinned 2026.08.01 AppImage bundles `MCAD` inside its own
    squashfs -- and it had already proved so, in the depfile, before this is
    called. Re-walking with `engine_inputs` reads the file the walk missed and
    the question is answered by the same rule as everywhere else.

    Three outcomes, and the middle one is the whole point:

    - depfile `absent` or `partial` — nothing better than the static walk is
      available, so #287's honest refusal stands verbatim, `environment`. So
      does the `complete` depfile that names no such file: apt 2021.01 HAS
      `-d` and is as blind to a system library as partspec is, so the common
      case on that engine is a render paid for and an answer unimproved.
    - the re-walk resolves the include and the name IS declared — return None.
      The engine bound it, and refusing would be a false refusal on a correct
      contract over a correct part.
    - the re-walk resolves the include and the name is still not declared — the
      ORDINARY refusal, `model`, because the list is now complete and the
      `-D` really would be dropped. The issue's own reproduction is this arm: a
      transposed `bore_diamter` beside an unread `MCAD/units.scad` must not be
      excused by the unread file.

    Deliberately NOT computed over `deps.files` directly, for two reasons. The
    list is every file the render opened, `import()`/`surface()` targets
    included, and `top_level_variables` would scan a `.dat` or `.dxf` for
    `name =` and invent declarations out of data. And it says nothing about
    whether anything is still missing, which is what picks the sentence below.
    The re-walk answers both with the one mechanism every other closure
    question already uses; the depfile only ever supplies *where does this
    reference live*.
    """
    reasked = (
        include_closure(source.path, engine_inputs=deps.listed)
        if deps.state == "complete"
        else closure
    )
    still = unbound_parameters(source.path, source.params, closure=reasked)
    if not still:
        return None
    named = ", ".join(still)
    known = ", ".join(sorted(top_level_variables(source.path, closure=reasked))) or "none"
    if reasked.unresolved_includes:
        could_not = ", ".join(reasked.unresolved_includes)
        return BuildError(
            f"parameter(s) {named} match no top-level variable partspec could "
            f"read in {source.path.name}, and that list is INCOMPLETE: "
            f"{could_not} could not be opened, so a variable declared there "
            f"would be missing from it",
            hint=f"variables read so far: {known}. Make {could_not} resolvable "
            f"— then partspec can say whether the parameter binds; until it "
            f"opens, neither the name nor the contract can be judged",
            origin="environment",
        )
    return BuildError(
        f"parameter(s) {named} match no top-level variable in "
        f"{source.path.name} or its includes, so -D would be silently dropped",
        hint=f"top-level variables: {known}",
    )


def render(
    source: OpenSCADSource,
    out_dir: Path,
    *,
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
    deps_out: list[RenderDeps] | None = None,
    unresolved_out: list[str] | None = None,
) -> Path | BuildError:
    """Render to binary STL, returning the path or a BuildError.

    `unresolved_out`, when given, receives the stderr lines saying the engine
    built something other than what the source asked for **on a render that
    succeeded** (#286, #308): a name it could not resolve, or a value it could
    not convert and defaulted. OpenSCAD renders an unresolved call's children
    not at all, and substitutes a default where a dimension would not convert,
    and still exits 0 with a well-formed mesh in both cases -- so the artifact
    alone cannot say that the geometry measured is not the geometry the source
    describes, and this return type has no room to say it. Before #286 those
    lines were read only to build a `BuildError`, which is to say only when the
    engine had already failed; the success path discarded `proc.stderr`
    outright and every downstream check reported PASS against a part the engine
    had quietly hollowed out.

    Binary STL specifically: lib3mf cannot read ASCII STL, and OpenSCAD 2021.01
    defaults to ASCII. Choosing the format explicitly means the export does not
    silently change meaning with the installed version.

    **No file this call did not create is touched until there is an artifact to
    put there.** The engine writes into a scratch directory under `out_dir` and
    the result is moved into place with `os.replace`, so the destination holds
    the old file or the new one and never neither. It is the shape
    `cli._build_to_file` settled on for the filename form of `--out` — the
    directory form never got it (#208) — and the one SPEC-backend §5 step 1
    already spells the invocation with (`-o <tmp>.stl`), though the spec is
    illustrating the command rather than requiring the temporary.

    The claim is scoped that way rather than to "nothing in `out_dir`" because
    the scratch directory itself IS created there, before the engine runs. It
    is removed on every exit from the `with`, including exceptions and SIGINT;
    an uncaught signal — SIGTERM, SIGKILL — leaves a `.partspec-build-*`
    behind (measured: exit 143, leftover confirmed). Sweeping older ones is
    deliberately not done here, for `_build_to_file`'s reason: a concurrent
    render in the same directory owns one of them, and this call cannot tell
    which. A symlink at the destination is replaced by the rename rather than
    written through, so its target is untouched.

    An earlier revision unlinked the target up front, so that the
    exists/non-empty guards below could not be answered by a *stale* file from
    a previous run. That reason does not survive the scratch directory: the
    guards now ask about a file in a directory this call created empty
    moments earlier, so no previous run's mesh can be standing in it and there
    is nothing stale to be fooled by. What the unlink did reach was the
    caller's data — `.stl` is an input extension as well as an output one, and
    a model importing `<stem>.stl` built without its import and reported a
    complete, confident, wrong answer at exit 0, `measure` and `check` alike.

    `timeout_s` here is already resolved: a number is the bound, None is
    unbounded (the explicit `--timeout 0` waiver). The None-means-default rule
    lives one layer up, in `effective_timeout`.
    """
    global _DEPS_FLAG_OK

    executable = find_executable()
    if executable is None:
        return BuildError(
            "openscad not found on PATH",
            origin="environment",
            hint=NOT_FOUND_HINT,
        )
    if not source.path.is_file():
        return BuildError(f"source not found: {source.path}", origin="environment")

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return BuildError(
            f"could not create the output directory {out_dir}: {exc.strerror}",
            origin="environment",
        )
    stl = out_dir / f"{source.path.stem}.stl"

    # Walked once and used twice: the pre-render refusal below asks it for the
    # arm no depfile can reach, and the post-render one asks whether to ask the
    # depfile at all.
    closure = include_closure(source.path)
    # Asked before anything is written, because it is the question the guard
    # below the render falls back on when the engine cannot name its inputs,
    # and by then this call has created the name it is asking about.
    would_overwrite = stl.exists() and out_dir.resolve() == source.path.parent.resolve()
    refusal = _output_over_an_input(source, stl, closure, would_overwrite=would_overwrite)
    if refusal is not None:
        return refusal

    scratch: Path | None = None
    # Parameters that bind nothing in the closure partspec could WALK, held
    # back for `_still_unbound` to re-ask once the engine has named its own
    # inputs. Empty on every path where the walk was complete, so the ordinary
    # refusal still happens before a byte is written.
    deferred: list[str] = []
    try:
        if source.method:
            prepared = _method_scratch(source, out_dir)
            if isinstance(prepared, BuildError):
                return prepared
            scratch = prepared
            render_path, defines = scratch, []
        else:
            # A `-D` naming no top-level variable is silently accepted by
            # OpenSCAD and dropped. `openscad("part.scad", bore_diamter=8)` --
            # one transposition -- rendered the file's own default, and the
            # report then listed bore_diamter=8 under `params`, so the artifact
            # positively asserted a value the geometry never saw.
            #
            # The refusal STANDS when partspec could not read an include -- it
            # is the sentence that changes, not the answer. Skipping it instead
            # was tried in review of #310 and traded a loud false error for a
            # silent false pass: an unresolved `use` suppressed the refusal
            # although a `use`d file contributes no top-level variable at all,
            # and `Can't open library` is deliberately not a #286 marker, so a
            # genuinely misspelt `-D` reached `verdict: pass` at exit 0 on both
            # engines. That is the one trade this tool must never make.
            #
            # What #287 actually reports is the SENTENCE: "match no top-level
            # variable in <file> or its includes" is a claim about includes
            # that were never opened. #311 goes one step further: when the
            # engine can open a file partspec cannot -- the pinned AppImage
            # bundles MCAD inside its own squashfs -- refusing on the short
            # list refuses a correct part over a correct contract. So the
            # unread-include arm is DEFERRED to `_still_unbound`, which asks
            # the same question again from the depfile. Nothing is deferred
            # when the walk was whole: there is no better answer coming, and
            # rendering first would only cost time.
            unbound = unbound_parameters(source.path, source.params, closure=closure)
            if unbound and not closure.unresolved_includes:
                known = ", ".join(sorted(top_level_variables(source.path, closure=closure)))
                return BuildError(
                    f"parameter(s) {', '.join(unbound)} match no top-level variable in "
                    f"{source.path.name} or its includes, so -D would be silently dropped",
                    hint=f"top-level variables: {known or 'none'}",
                )
            deferred = unbound
            render_path, defines = source.path, _define_args(source.params)

        backend_args = ["--backend", source.backend] if source.backend else []
        # The scratch directory sits under `out_dir` rather than in the system
        # temp dir, so the move into place is a rename on one filesystem —
        # `_build_to_file` places its own beside the destination for the same
        # reason. The method entry file is NOT moved here: relative
        # `import()`/`surface()` paths resolve against the main entry file's
        # directory, so `_method_scratch` alone decides where that lives.
        with tempfile.TemporaryDirectory(
            dir=out_dir, prefix=".partspec-build-", ignore_cleanup_errors=True
        ) as build_dir:
            staged = Path(build_dir) / stl.name
            wanted_deps = _DEPS_FLAG_OK
            # `-d` inside the scratch directory, which this call created empty
            # and which is removed with it: the engine's own account of what it
            # read is provenance, not an artifact, and it must not appear in a
            # directory the caller owns. Passed unconditionally because it is
            # inert on the render — 2021.01 documents it as
            # `deps_file -generate a dependency file for make`, and an engine
            # that does not accept it is handled where every other rejected
            # option is.
            depfile = Path(build_dir) / "deps"
            cmd = [
                executable,
                "--export-format",
                "binstl",
                *backend_args,
                "-o",
                str(staged),
                *(["-d", str(depfile)] if wanted_deps else []),
                *defines,
                str(render_path),
            ]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout_s, check=False
                )
                rejected = _signal_lines(proc.stderr)
                if (
                    proc.returncode != 0
                    and wanted_deps
                    and _is_unknown_option(proc.stderr)
                    and _DEPS_RE.search(rejected[0])
                ):
                    # This engine has no `-d`. Drop it for the rest of the
                    # process and render again: the depfile is provenance, and
                    # losing it must cost the closure a claim, never the build.
                    _DEPS_FLAG_OK = False
                    wanted_deps = False
                    cmd = [a for a in cmd if a not in ("-d", str(depfile))]
                    proc = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=timeout_s, check=False
                    )
            except subprocess.TimeoutExpired:
                return BuildError(f"openscad timed out after {timeout_s}s", origin="environment")
            except OSError as exc:
                # A mistyped PARTSPEC_OPENSCAD reaches here. The pin is returned
                # as given rather than validated away, because silently falling
                # back to PATH would answer with an engine the user did not choose
                # — and the version is the part (F13). So it fails, by name.
                return BuildError(
                    f"could not run the openscad binary at {executable!r}: {exc.strerror}",
                    origin="environment",
                    hint=f"{ENV_EXECUTABLE} is set to this path"
                    if os.environ.get(ENV_EXECUTABLE)
                    else None,
                )

            # Once, here: every return below this point has the same answer,
            # and `exit 0 but no geometry` is a COMPLETE depfile rather than a
            # failed one — measured, a model whose `include` did not resolve
            # exits 0 and the depfile lists the source alone. Read whether or
            # not a caller wanted it, because the guard below the render wants
            # it too and a second read would be a second answer.
            deps = (
                _read_depfile(depfile, ok=proc.returncode == 0)
                if wanted_deps
                else RenderDeps(state="absent")
            )
            if deps_out is not None:
                deps_out.append(deps)

            if proc.returncode != 0:
                reason = _first_error_line(proc.stderr)
                if _is_unknown_option(proc.stderr):
                    # The engine rejected an option partspec passed, which is a
                    # statement about the ENGINE, not the part. The 2021.01 case is
                    # `backend=`: render backends arrived later, and Debian and
                    # Ubuntu ship 2021.01, so this is the ordinary experience of a
                    # contract written against a newer engine, not an exotic one.
                    #
                    # Measured before this branch existed: `verdict: fail`,
                    # `build_origin: "model"`, hint `unrecognised option
                    # '--backend'`. The hint was right and the origin was wrong,
                    # and the origin is what AGENT-CONTRACT §2.3 routes on — so an
                    # agent was sent to §2.1 "fix the source" over a machine that
                    # simply predates the flag. SPEC-report §6.1 forbids exactly
                    # that: an environment fault MUST NOT be reported as a
                    # statement about the part.
                    # The hint names the option the ENGINE named, never a literal.
                    # It read "(2021.01 has no --backend)", which is true of the
                    # case that prompted this branch and false of every other:
                    # `--export-format` is passed on every render and arrived in
                    # 2021.01, so on an older binary every build lands here and the
                    # hint would have told the reader to drop a flag they never
                    # passed (PR #160 review).
                    return BuildError(
                        f"the openscad binary rejected an option partspec passed: {reason}",
                        hint=f"this engine does not accept it — {reason}. Upgrade openscad, "
                        f"or drop the contract argument that needs it (`backend=` needs a "
                        f"build newer than 2021.01)",
                        origin="environment",
                        stderr=proc.stderr,
                    )
                return BuildError(
                    f"openscad exited {proc.returncode}",
                    hint=reason,
                    stderr=proc.stderr,
                    produced_nothing=_EMPTY_RESULT in proc.stderr,
                    unresolved=_unresolved_lines(proc.stderr),
                )
            # OpenSCAD exits 0 on some degenerate input while writing nothing
            # useful, so the artifact is checked rather than the exit code
            # trusted. It is the STAGED file that is checked: the scratch
            # directory was created empty by this call, so "exists and is
            # non-empty" cannot be answered by a previous run's mesh — which
            # is the whole reason the old up-front unlink existed.
            if not staged.is_file() or staged.stat().st_size == 0:
                return BuildError(
                    "openscad exited 0 but produced no geometry",
                    hint=_first_error_line(proc.stderr),
                    stderr=proc.stderr,
                    # Same outcome by another route, and flagged on both because
                    # which one an empty model takes is a property of the engine
                    # BUILD, not of the part: 2021.01 exits 1 here and the CI
                    # matrix also runs 2026.08.01. Keying on one exit code would
                    # make `empty` answer differently on two engines for one
                    # source, which is F13 all over again.
                    produced_nothing=True,
                    unresolved=_unresolved_lines(proc.stderr),
                )
            if closure.partial:
                # The exact question #223's guard could not ask, asked where it
                # can be answered and while the caller's file is still intact.
                refusal = _wrote_over_an_input(
                    deps,
                    stl,
                    source.path.name,
                    closure=closure,
                    refuse_unanswered=would_overwrite,
                )
                if refusal is not None:
                    return refusal
            if deferred:
                # After the overwrite guard and before the artifact is moved
                # into place: a refusal here must leave nothing behind, exactly
                # as the pre-render one did.
                refusal = _still_unbound(source, deferred, closure, deps)
                if refusal is not None:
                    return refusal
            # Read here, on the path that WORKED, and not only where a
            # BuildError is built: an unresolved name, or a dimension the engine
            # defaulted because it would not convert, does not have to fail the
            # render to have changed the part.
            if unresolved_out is not None:
                unresolved_out.extend(_unresolved_lines(proc.stderr, _SUCCESS_PATH_MARKERS))
            staged.replace(stl)
            return stl
    except OSError as exc:
        # One clause for the scratch directory and for the move, because the
        # caller's question is the same in each: the artifact is not where you
        # asked for it, and that is the environment's doing, not the part's.
        # Same sentence `_build_to_file` uses, for the same failure.
        return BuildError(
            f"could not write the build artifact to {stl}: {exc.strerror}",
            origin="environment",
        )
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)


def render_section_stl(
    stl: Path,
    plane: str,
    offset: float,
    bbox: tuple[tuple[float, ...], tuple[float, ...]],
    out_dir: Path,
    *,
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
) -> Path | BuildError:
    """Cut the exported STL with a half-space and re-export it, kernel-capped.

    The cut subtracts from the ALREADY-EXPORTED mesh rather than the source:
    D15's measurand is the artifact as exported, and importing it back keeps
    every parameter binding exactly as the canonical views saw it — no second
    pass through `-D`/method scratch machinery to drift. The engine does the
    boolean, so the exposed faces are real capped material, not a display
    trick. The discard side per plane follows `raster.SECTION_VIEWS`: the
    material between the section camera and the plane is removed.

    Both files this call writes go into a scratch directory and the result is
    moved into place, the shape `render()` settled on (#208, #224). Neither
    `<stem>.section.stl` nor the `<stem>.section.scad` that produces it is a
    name partspec is the only plausible author of *by extension* — both are
    model extensions — and the old code deleted the first and truncated the
    second in the caller's directory before the engine ran. The cut script is
    safe to relocate because it names the mesh it imports by resolved absolute
    path, so nothing in it resolves against its own directory.
    """
    import json as _json

    executable = find_executable()
    if executable is None:
        return BuildError(
            "openscad not found on PATH",
            origin="environment",
            hint=NOT_FOUND_HINT,
        )
    lo, hi = bbox
    pad = max(*(top - bottom for top, bottom in zip(hi, lo, strict=True)), 1.0)
    axis = {"xy": 2, "xz": 1, "yz": 0}[plane]
    mins = [c - pad for c in lo]
    maxs = [c + pad for c in hi]
    if plane == "xz":
        maxs[axis] = offset  # camera at -Y: discard y < offset
    else:
        mins[axis] = offset  # camera at +Z / +X: discard above the plane
    sizes = [b - a for a, b in zip(mins, maxs, strict=True)]

    out = out_dir / f"{stl.stem}.section.stl"
    try:
        with tempfile.TemporaryDirectory(
            dir=out_dir, prefix=".partspec-build-", ignore_cleanup_errors=True
        ) as build_dir:
            scratch = Path(build_dir) / f"{stl.stem}.section.scad"
            staged = Path(build_dir) / out.name
            scratch.write_text(
                "difference() {\n"
                f"  import({_json.dumps(str(stl.resolve()))});\n"
                f"  translate([{mins[0]!r}, {mins[1]!r}, {mins[2]!r}])"
                f" cube([{sizes[0]!r}, {sizes[1]!r}, {sizes[2]!r}]);\n"
                "}\n"
            )
            try:
                proc = subprocess.run(
                    [executable, "--export-format", "binstl", "-o", str(staged), str(scratch)],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return BuildError(f"openscad timed out after {timeout_s}s", origin="environment")
            except OSError as exc:
                return BuildError(
                    f"could not run the openscad binary at {executable!r}: {exc.strerror}",
                    origin="environment",
                )
            if proc.returncode != 0:
                return BuildError(
                    f"openscad exited {proc.returncode} cutting the {plane} section",
                    hint=_first_error_line(proc.stderr),
                    stderr=proc.stderr,
                )
            # The staged file is the one asked about, for `render()`'s reason:
            # the scratch directory was created empty moments ago, so an empty
            # cut cannot be masked by a previous run's section sitting at `out`.
            if not staged.is_file() or staged.stat().st_size == 0:
                return BuildError(
                    f"the {plane} section at {offset:g} mm discards the whole part",
                    hint=_first_error_line(proc.stderr),
                )
            staged.replace(out)
            return out
    except OSError as exc:
        return BuildError(
            f"could not write the section artifact to {out}: {exc.strerror}",
            origin="environment",
        )


VIEWS: dict[str, tuple[float, float, float]] = {
    "iso": (55.0, 0.0, 25.0),
    "front": (90.0, 0.0, 0.0),
    "top": (0.0, 0.0, 0.0),
    "right": (90.0, 0.0, 90.0),
}
"""The canonical views, as gimbal rotations. Canonical rather than arbitrary
because an agent compares images across iterations, and a camera that moves
makes every comparison ambiguous (#17)."""

IMAGE_SIZE = (800, 800)


def _stl_bbox(stl: Path) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Min/max corners of a binary STL, by scanning its vertices.

    stdlib on purpose: the engine layer renders and the backend layer measures,
    and pulling trimesh in here to answer a framing question would blur that
    seam. Facets are 50 bytes — a 3-float normal, three 3-float vertices, a
    2-byte attribute — after an 80-byte header and a facet count.
    """
    import struct

    data = stl.read_bytes()
    (count,) = struct.unpack_from("<I", data, 80)
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for f in range(count):
        base = 84 + f * 50 + 12  # skip the normal
        for v in range(3):
            x, y, z = struct.unpack_from("<3f", data, base + v * 12)
            for i, c in enumerate((x, y, z)):
                lo[i] = min(lo[i], c)
                hi[i] = max(hi[i], c)
    return tuple(lo), tuple(hi)


def _camera(bbox: tuple[tuple[float, ...], tuple[float, ...]], rot: tuple[float, ...]) -> str:
    """A gimbal camera string derived from the bounding box, so identical
    geometry frames identically on every run."""
    lo, hi = bbox
    center = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
    diagonal = sum((b - a) ** 2 for a, b in zip(lo, hi, strict=True)) ** 0.5
    distance = max(2.2 * diagonal, 1.0)  # a degenerate flat part still gets a frame
    return ",".join(repr(v) for v in (*center, *rot, distance))


_EMPTY_RESULT = "Current top level object is empty"

_UNRESOLVED_NAME_MARKERS = (
    # BOTH spellings, because the engines disagree and matching one is F13 in
    # miniature. Measured by running the same missing-include source under each
    # binary the CI matrix pins:
    #   2021.01     WARNING: Can't open include file 'nowhere/absent.scad'.
    #   2026.08.01  WARNING: Can't find include file 'nowhere/absent.scad'. ...
    # Only the first was listed until PR #306, so on the newer engine this
    # marker had been dead since the day the snapshot leg was added -- silently,
    # because nothing asserted it there. `test_openscad_engine.py` now pins both
    # strings against the matcher directly, which needs no engine to run.
    "Can't open include file",
    "Can't find include file",
    "Ignoring unknown module",
    "Ignoring unknown function",
    "Ignoring unknown variable",
)
"""The diagnostics that name a NAME the engine could not resolve.

Separated from `_UNRESOLVED_MARKERS` because the two sets answer different
questions and only one of them is safe to ask of a render that SUCCEEDED.
Each says a name was looked up and not found; what follows from that differs
by kind. A module or include is direct -- OpenSCAD renders that call's children
not at all, so geometry the source asked for is simply gone. A function or
variable yields `undef` into an expression instead, which may or may not reach
geometry: `echo(nofunc(3))` beside a correct cube is refused on this evidence
even though the cube is right. That is deliberate. stderr cannot say whether
the `undef` reached a dimension, the diagnosis (a name did not resolve) is true
either way, and the remedy is the same -- while a value silently substituted
into a dimension is the case that must not be waved through (#286).

A second success-path shape lives in `_SUBSTITUTED_VALUE_MARKERS` below rather
than here, because the diagnosis differs: no name failed to resolve, a value
failed to CONVERT and the engine put a default in its place. Both sets are read
after a render that succeeded, together, as `_SUCCESS_PATH_MARKERS` (#308).

`undefined operation` is deliberately NOT here. It reports a type error in an
expression, not a lookup that failed, and on the success path it fires on code
whose geometry is completely correct: `echo("holes: " + holes)` -- `+` where
`str()` was meant, and among the most common things in a real .scad -- renders
a perfect part and prints exactly that line. Guarding on it errored that part
at exit 4 while telling the reader a name had not resolved and to check
`OPENSCADPATH`, which was false in every clause. Caught in review of PR #306.

It remains in `_UNRESOLVED_MARKERS` below, where the question is narrower and
the docstring's reasoning holds: there, the render already produced NOTHING,
and `vector * string` is real evidence that a null result is not genuine."""

_SUBSTITUTED_VALUE_MARKERS = (
    # Character-identical on both binaries the CI matrix pins, which is not the
    # assumption the include marker got away with -- measured under each, from
    # the sources named:
    #   cube(size=[o,5,5])     Unable to convert cube(size=[undef, 5, 5], ...)
    #                          parameter to a number or a vec3 of numbers
    #   translate([o,0,0])     Unable to convert translate([undef, 0, 0])
    #                          parameter to a vec3 or vec2 of numbers
    #   square([o,30])         Unable to convert square(size=[undef, 30], ...)
    #                          parameter to a number or a vec2 of numbers
    #   scale(o)               Unable to convert scale(undef) parameter to a
    #                          number, a vec3 or vec2 of numbers or a number
    # each with `o = undef`, each exiting 0 with a clean single-solid mesh.
    "Unable to convert",
    # `rotate()` PARAMETERS THE ENGINE COULD NOT USE AS WRITTEN, which it
    # words differently (#333). Character-identical on both pinned binaries,
    # measured under each -- all three templates, and `o = undef`:
    #   rotate(o)              Problem converting rotate(a=undef) parameter
    #   rotate([o,0,0])        Problem converting rotate(a=[undef, 0, 0])
    #                          parameter
    #   rotate(a=o, v=[0,0,o]) Problem converting rotate(a=undef,
    #                          v=[0, 0, undef]) parameter
    #   rotate(a=45, v="z")    Problem converting rotate(..., v="z") parameter
    # Read the docstring before widening this: the line does NOT always mean a
    # default went in, and it fires beside a byte-identical export in three
    # measured shapes. The prefix stops at `rotate(` because the fourth
    # `Problem converting` template is not about geometry at all.
    "Problem converting rotate(",
)
"""What OpenSCAD says where a value reached a geometry parameter and the engine
could not use it as written.

For `Unable to convert` that always means a default went in instead, and the
paragraphs below are about that line. For `Problem converting rotate(` it does
NOT always mean that -- one of its shapes applies the rotation and substitutes
nothing -- and the rotate section near the end of this docstring states the
difference rather than letting the sentence above stand for both.

This is the discrimination `undefined operation` could not make. That line
reports a type error anywhere in the file, geometry or not, which is why
guarding on it errored correct parts (see above). `Unable to convert` is
emitted at the point of SUBSTITUTION, by the module whose parameter it is, and
names that module and the value it rejected. Measured on both engines, the
`echo("holes: " + holes)` case that killed the wider marker does not emit it --
nothing reached geometry there, so there was nothing to substitute into.

The substitution is total, not partial: `cube(size=[o, 30, 6])` with `o = undef`
exports a 1x1x1 unit cube on both engines -- the 30 and the 6 go with the axis
that did not convert -- watertight, single-solid, exit 0.

What this does NOT cover, measured rather than assumed, and the reason #308's
own headline reproduction is still open: a *scalar* dimension taking `undef`
prints nothing at all. `linear_extrude(undef) square([40,30])` and
`cylinder(h=undef)` are silent on both engines; `linear_extrude(undef + 1)`
prints `undefined operation` and no conversion line. There is no stderr signal
to guard on, so a fix needs another channel entirely -- #332 holds the
measurements.

Nor is "vector-valued" the rule, which an earlier draft of this docstring
asserted and round-1 review disproved. `resize([undef,10,10])`,
`multmatrix(undef)` and `offset(delta=undef)` are silent on BOTH engines while
building a defaulted part. Which modules narrate the substitution is the
engine's own list, not a property anyone can derive; the four above are the
ones measured, `mirror([undef,0,0])` is a fifth, and this set covers what the
engine chooses to say and nothing more. Do not read it as covering every
silently defaulted dimension.

`Problem converting rotate(` is the second marker, added in #333, and it is
NOT simply the first said in other words. It means the engine could not use the
`rotate` parameters as written. Whether anything was substituted, and whether
the mesh is wrong, depends on WHICH way they were unusable -- measured on both
engines, all byte comparisons `cmp -s` against the correct source named:

    rotate(o) cube(5)             the angle is dropped; the part stands at
    rotate([o,0,0]) cube(5)       IDENTITY. The mesh is wrong. This is the
                                  shape #333 was filed for.

    rotate() cube([10,5,2])       a=undef by omission -> identity, which is
                                  what a no-op rotate is FOR. Byte-identical
                                  to `cube([10,5,2])`.

    rotate([90,0,0,0])            NOTHING IS SUBSTITUTED. 2021.01's
      cube([10,5,2])              `src/transform.cc` reads
                                  `default: ok &= false; /* fallthrough */
                                  case 3:`, so an over-long vector still has
                                  its first three components read and applied;
                                  only `ok` is false. Measured bbox
                                  (0,-2,0)..(10,0,5) -- the 90 deg about X the
                                  source asked for -- and byte-identical to
                                  `rotate([90,0,0]) cube([10,5,2])`.

    rotate(a=45, v="z") cube(5)   the angle converts and the DEFAULT AXIS
                                  [0,0,1] goes in. Measured bbox
                                  (-3.536,0,0)..(3.536,7.071,5): rotated 45
                                  deg about Z, NOT identity, and byte-identical
                                  to `rotate(a=45, v=[0,0,1]) cube(5)`.

So three of those five fire beside an export that is byte-identical to the
correct part, on both engines, and this guard refuses all three at exit 4. That
is a REMAINDER, not an oversight, and it is `FAILURE-MODES.md` entry 9b's trade
in a second place: an over-long rotate vector, a string axis and a rotate whose
angle never arrived are all bugs in the SOURCE, the modifier between right and
wrong is one character, and refusing loudly is the safe direction. The refusal
stands because the source is wrong -- never because the mesh was shown to be.
Do not restate it as "a default was substituted"; for the over-long vector that
is false -- which is why `runner.py`'s `_SUBSTITUTED_VALUE_CAUSE` says something
this marker cannot support, tracked as #360.

Added after the probe #308's own carve-out demanded: `Unable to convert` turned
out to have a context where it is true and irrelevant (the GUI camera), so
`Problem converting` was inventoried the same way rather than assumed clean.
Both pinned binaries carry exactly FOUR `Problem converting` templates -- read
out of each binary with `strings`, and the two lists are identical. Three are
the `rotate` templates above (2021.01 `src/transform.cc` 152-177; master
`src/core/TransformNode.cc` 130-163), and they are the marker. The fourth is
`Problem converting this number: %1$s` (2021.01 `src/boost-utils.h` 41; master
`src/utils/boost-utils.h` 38), whose only caller in either version is `rands()`'s
result count (2021.01 `src/func.cc` 134; master `src/core/builtin_functions.cc`
184). That one is not about geometry at all, and it cannot occur beside an
exported mesh: the cast fails only on positive overflow, the engine then sets
the count to SIZE_MAX and tries to build that many results, and it dies before
writing anything. Measured under a 2 GB address-space cap on both engines, from
`r = rands(0, 1, 1e30); cube([40,30,6]);`:

    WARNING: Problem converting this number: 1000000000000000019884624838656.000000
    WARNING: bad numeric conversion: positive overflow
    WARNING: setting result to 18446744073709551615
    2021.01     std::bad_alloc      exit 134, no STL
    2026.08.01  std::length_error   exit 134, no STL

So it needs no `_NON_GEOMETRY_CONVERSIONS` entry -- that tuple is for lines that
are true beside an exported mesh, and there is no exported mesh here. The marker
is narrowed to `Problem converting rotate(` instead, which separates the four by
the engine's own grammar and keeps a crash from being reported as a defaulted
dimension. Same reasoning as the `[` split in `_NON_GEOMETRY_CONVERSIONS`,
spelled as a selection rather than a carve-out because the geometry side is the
enumerable one here.

Not every mis-specified rotation is narrated, which is the #332 shape again
rather than a gap in this marker: `rotate(a=90, v=undef)` is SILENT on both
engines and still exits 0. `undef` is not "defined", so the engine reads it as
"no axis given" and applies its DEFAULT axis -- the part is rotated 90 deg about
Z, byte-identical to both `rotate(a=90, v=[0,0,1])` and `rotate(90)`, measured.
It is not unrotated; a reader told otherwise hunts the wrong symptom.

`_NON_GEOMETRY_CONVERSIONS` carves out the two shapes measured to say this and
mean nothing about the exported mesh: the GUI camera, and a range or step built
in an expression."""

_NON_GEOMETRY_CONVERSIONS = (
    # THE GUI CAMERA. `$vpt`/`$vpr`/`$vpd`/`$vpf`, and no exported mesh depends
    # on any of them. Measured beside a cube that is exactly right, all four
    # variables in both shapes, on both engines:
    #   $vpt = [undef, 0, 0]   Unable to convert $vpt=[undef, 0, 0] to a vec3
    #                          or vec2 of numbers        -- BOTH engines
    #   $vpt = undef           Unable to convert $vpt=undef to a vec3 or vec2
    #                          of numbers                -- 2026.08.01 only
    # and identically for `$vpr`, and for `$vpd`/`$vpf` with `to a number`.
    # The engine split is SCALAR vs VECTOR, not which variable: every vector
    # form warns on both engines, every scalar form is silent on 2021.01. A
    # round-1 review caught this comment claiming the split was `$vpd`/`$vpf`,
    # which was two measurements read as four. No file, no line, on either
    # engine -- the assignment is not a module call.
    "Unable to convert $vp",
    # A RANGE OR STEP THE ENGINE COULD NOT BUILD, which happens in expression
    # evaluation and not in a module assembling geometry -- the same place
    # `len() parameter could not be converted` fires, which this guard has
    # excluded from the start. 2026.08.01 ONLY; the message does not exist on
    # 2021.01, which is why a corpus sweep run on one engine could not see it
    # (round-2 review):
    #   echo("at:", [0 : undef])    Unable to convert [0:...:undef] to a range
    #   echo("at:", [0 : undef : 10])
    #                               Unable to convert [...:undef:...] to a
    #                               step value
    # Both from `core/Expression.cc`; counted in that source, they are the ONLY
    # two of the 21 distinct `Unable to convert` templates that begin with `[`.
    # Every substitution template begins with a module name or a field name --
    # `cube(`, `square(`, `translate(`, `mirror(`, `scale(`, `import(`,
    # `points`, `points[`, `faces`, `faces[`, `paths`, `paths[` -- so the `[`
    # separates the two classes exactly, and does so by the engine's own
    # grammar rather than by a list this file would have to chase.
    "Unable to convert [",
)
"""Conversion warnings that are true and about nothing that is exported.

Two classes, and only the first is unconditionally irrelevant. A viewport
variable is the GUI camera and no exported mesh can depend on it. A range or
step is different, and the difference is a TRADE rather than a fact.

A failed range yields `undef` into the expression, exactly as an unresolved
function does -- and an unresolved function's `undef` IS refused, on the
reasoning `SPEC-report.md` §6.1 gives in as many words. What separates them is
only that this line fires on a correct part often enough to matter and that one
does not. So the honest statement is: **this line cannot distinguish an
expression that reached geometry from one that did not**, correct parts win the
tie, and there is a remainder.

The remainder is real and measured on 2026.08.01, where this line is the ONLY
stderr signal in each case:

    module rail(n = undef) {                    // the loop's geometry vanishes
      cube([40, 8, 6]);
      for (i = [1 : n]) translate([i*8, 0, 6]) cube([6, 8, 4]);
    }
    rail();                                     // `Facets: 6` against 76 for n=4

    n = undef;  r = [0 : n];  h = r[2];         // #308's own headline shape
    linear_extrude(h) square([40, 30]);         // exported bbox z 0..100

`Facets:` is OpenSCAD's own summary vocabulary, quoted rather than measured: the
exported STL carries 12 triangles for the defaulted part and 76 for `n = 4`, so
a reader cross-checking against `partspec measure` sees 12 where the engine says
6. The engine's number is the one printed beside the warning, which is why it is
the one shown; the mesh is what partspec measures (D15).

The second is `linear_extrude` substituting its own default into a dimension --
precisely the fault #308 exists to refuse -- passing at exit 0. Filed as #338.

Carved out anyway, and the precedent is settled: matching this line refused
CORRECT parts (round-2 review of PR #329 found the protected echo case from PR
#306 with a range where the string concat was -- byte-identical export, exit 4
on 2026.08.01 against exit 0 on 2021.01), and `undefined operation` came off
the success path for exactly this reason with #332 holding its remainder. A
loud false error on working code is the worse trade, and this repo has made it
twice and reverted twice.

Both entries are ANCHORED at the head of the engine's sentence, like the marker
itself -- see `_unresolved_lines`."""

_SUCCESS_PATH_MARKERS = (*_UNRESOLVED_NAME_MARKERS, *_SUBSTITUTED_VALUE_MARKERS)
"""What may be read off a render that SUCCEEDED: a name that did not resolve, or
a value that did not convert. Both mean the mesh on disk is not the mesh this
source describes, and both are absent from a correct part."""

_UNRESOLVED_MARKERS = (
    *_SUCCESS_PATH_MARKERS,
    "undefined operation",
)
"""What OpenSCAD says when it did not build what the source asked for — measured
on 2021.01, not guessed. Each was produced from a source written to trigger it:
a missing include, a misspelt module, an unknown function, an undefined
variable, a `vector * string`, and (via `_SUBSTITUTED_VALUE_MARKERS`) a value
that would not convert.

The list exists because an unresolved name and a genuinely null result are
INDISTINGUISHABLE downstream: both exit 1 with `Current top level object is
empty.` and write no STL. A model whose whole top-level object comes from a
failed include renders empty and, without these lines, reads exactly like a
clean pass — which is how `p.empty()` would launder a broken probe into a green
one. So the markers are the evidence, and they are all that separates the two.

Matching on the message rather than a code because OpenSCAD has no distinct
exit code for either; if a future engine version gains one, prefer it and keep
this as the fallback."""


def _unresolved_lines(
    stderr: str, markers: tuple[str, ...] = _UNRESOLVED_MARKERS
) -> tuple[str, ...]:
    """The stderr lines saying the engine built something other than the source.

    Two causes, one list: a name it could not resolve, and a value it could not
    convert and defaulted (#308). `is_substituted_value` tells them apart for a
    caller that has to say which.

    `markers` defaults to the wide set, which is right where the render already
    produced nothing. A caller asking about a render that SUCCEEDED must pass
    `_SUCCESS_PATH_MARKERS` -- see `_UNRESOLVED_NAME_MARKERS` for the one that
    does not survive the move.

    The non-geometry carve-out is applied to every set rather than folded into
    one, because it is a statement about the LINE and not about the caller: a
    `$vpt` or range conversion is read the same way whether the render
    succeeded or produced nothing.

    A substitution marker is matched ANCHORED at the head of the engine's
    sentence, through `is_substituted_value`, and the name markers by
    substring. Two measured reasons, both for the anchor.

    OpenSCAD echoes string literals verbatim into the warning, so an
    unanchored test let the source turn the guard off by naming the carve-out
    (round-1 review):

        translate(["harmless", o, 0]) cube(5);              -> refused, exit 4
        translate(["Unable to convert $vp", o, 0]) cube(5); -> PASSED, exit 0

    And `Unable to convert` is not only a substitution: CGAL says
    `The given mesh is not closed! Unable to convert to CGAL_Nef_Polyhedron.`
    on 2021.01 for a `difference()` over an unclosed polyhedron -- exit 1, no
    STL, no value substituted anywhere -- while 2026.08.01 words the same
    failure `[manifold] Input mesh is not closed!` and never says "convert".
    Unanchored, one source got two different reports on the two pinned
    engines, and the 2021.01 one blamed a defaulted dimension for an unclosed
    mesh. That is F13 with a false cause attached, found sweeping 1503
    third-party library files.

    The matcher shares `is_substituted_value` rather than repeating its test,
    so what is REFUSED and what is DIAGNOSED as a substitution cannot drift
    apart.
    """
    name_like = tuple(m for m in markers if m not in _SUBSTITUTED_VALUE_MARKERS)
    # Only when the CALLER asked for them. `markers` is a set, and a caller
    # passing `_UNRESOLVED_NAME_MARKERS` alone is asking whether a NAME failed
    # to resolve -- a conversion is not one, and answering yes would collapse
    # the two sets this module keeps apart. The first draft of this anchor
    # applied the substitution test unconditionally and
    # `test_the_unresolved_markers_match_both_engine_spellings` caught it.
    wants_substitutions = len(name_like) != len(markers)
    return tuple(
        line.strip()
        for line in stderr.splitlines()
        if (
            any(m in line for m in name_like)
            or (wants_substitutions and is_substituted_value(line))
        )
        and not _reaches_no_geometry(line)
    )


def _message(line: str) -> str:
    """The engine's sentence with its severity prefix removed.

    Both severities, because both occur for one marker: `polygon()` emits the
    conversion warning as `ERROR:` on 2021.01 and as `WARNING:` on 2026.08.01,
    measured, so a test that knew one spelling would be anchored on one engine
    and unanchored on the other.
    """
    message = line.strip()
    for severity in ("WARNING: ", "ERROR: "):
        message = message.removeprefix(severity)
    return message


def _reaches_no_geometry(line: str) -> bool:
    """Whether a conversion warning is true and about nothing that is exported."""
    return _message(line).startswith(_NON_GEOMETRY_CONVERSIONS)


def is_substituted_value(line: str) -> bool:
    """Whether a line reports a value the engine could not CONVERT -- and
    defaulted -- rather than a name it could not resolve.

    Anchored at the head of the engine's sentence: the substitution warnings
    are that whole sentence, and `Unable to convert` appearing further in is
    either the model's own string literal or a different failure entirely (see
    `_unresolved_lines`). This is both the matcher's test and the caller's
    diagnosis, so the two cannot disagree about one line.

    The two causes travel one list, because both mean the mesh on disk is not
    the mesh the source describes and both are read at the same moment. Only
    the diagnosis and the remedy differ, and the caller's sentence has to
    differ with them: "check `OPENSCADPATH`" is useless advice to someone whose
    include resolved fine and whose expression produced `undef` (#308).

    Ask it of the line the caller QUOTES, so the sentence and the evidence
    printed under it always name one cause. A run can produce both kinds.
    """
    return _message(line).startswith(_SUBSTITUTED_VALUE_MARKERS)


def _display_failure(returncode: int, stderr: str) -> bool:
    """Whether a PNG render died for want of a display.

    2021.01 has no EGL offscreen path: headless it prints `Unable to open a
    connection to the X server` / `Can't create OpenGL OffscreenView`, then
    segfaults (139) leaving a 0-byte file. That is an environment fault with a
    known remedy, and reporting it as `openscad exited -11` with a compile-log
    hint sends the reader off to debug their model.
    """
    if "OffscreenView" in stderr or "X server" in stderr:
        return True
    return returncode in (139, -11)


def _absent_input_views(absent: list[str]) -> BuildError:
    """`render` refusing a part the engine built without a file it asked for.

    Cause and hint come from `runner`, which `check` and `measure` read too: one
    engine fact, one diagnosis, whichever verb met it (#308's rule, #355). What is
    local here is that the output is pictures -- `render`'s payload records an
    `origin`, and `None` is the honest one, since whether the path is a typo or
    the file has not been generated yet is not something partspec can tell
    (SPEC-report §6.1).
    """
    from ..runner import _ABSENT_INPUT_CAUSE, _ABSENT_INPUT_HINT

    detail = (
        f"{_ABSENT_INPUT_CAUSE}, so these would be pictures of something other "
        f"than what this source describes: {absent[0]}"
    )
    if len(absent) > 1:
        detail += f" (and {len(absent) - 1} more)"
    return BuildError(detail, hint=_ABSENT_INPUT_HINT, origin=None)


def _hollowed_views(first_line: str) -> BuildError:
    """`render` refusing to draw a part the engine built out of something it lost.

    Sibling of `cli._hollowed_measurements`, and the cause and hint come from
    the same classifier both of those read, so one engine line cannot be
    diagnosed three ways depending on which verb reached it (#308).

    `origin=None`, and that is the point of the change (#307). `render`'s
    failure payload publishes `origin` (#191), and until the field had a third
    spelling this refusal would have published the default `"model"` -- a claim
    that the DESIGN is at fault, on the one failure partspec is certain it
    cannot attribute. `render.json` now carries `origin: null`, matching what
    `check` has always written to `report.build_origin` here (SPEC-report §6.1).
    """
    from ..runner import _unresolved_diagnosis

    cause, hint, artifact_is_wrong = _unresolved_diagnosis(first_line)
    # Hedged with the other three callers, from the one place that selects it (#375):
    # a name that did not resolve and a value not usable as written both export
    # byte-identically to a correct source on both pinned engines, so "would be" is a
    # claim the evidence does not carry. The refusal stands regardless.
    consequence = "would be" if artifact_is_wrong else "may be"
    return BuildError(
        f"{cause}, so these {consequence} views of something other than what this "
        f"source describes: {first_line}",
        hint=hint,
        origin=None,
        unresolved=(first_line,),
    )


def render_views(
    source: OpenSCADSource,
    out_dir: Path,
    *,
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
    deps_out: list[RenderDeps] | None = None,
) -> dict[str, Path] | BuildError:
    """Render the canonical views to PNG, or say exactly why not.

    The STL is rendered first, deliberately: it carries the guards this path
    must not re-invent — unbound `-D` detection, the empty-geometry refusal —
    so a cut that consumed the part is a `BuildError` here, never four blank
    frames that *look* like a rendered part. It also supplies the bounding box
    the camera framing derives from. The images carry no verdict: rendering
    never substitutes for measurement.

    It also carries #286's success-path guard, and since #307 this function
    acts on it: a render whose stderr says the engine could not resolve a name,
    or defaulted a value it could not convert, is refused before the first view
    is drawn rather than published as four pictures of a part the source does
    not describe.

    All four views are rendered into a scratch directory and moved into place
    together, the shape `render()` settled on (#208, #224). Here the hazard the
    old per-view unlink carried was not remote: `surface(file = "...")` reads a
    PNG as a heightmap on both engine versions, so `render --out .` against a
    model reading `renders/iso.png` deleted that heightmap before the engine
    ran, then rendered and reported the part built without it — measured, first
    run, clean directory, exit 0, nothing on stderr.

    A failure while RENDERING leaves the previous set of views untouched. A
    failure while MOVING cannot: there is no atomic rename of four files, so
    the one case that is knowable up front — a destination that is a directory
    — is refused before the first move, and a move that fails anyway reports
    how many were replaced instead of claiming nothing was.

    What survives is the residue `render()` also ships with, and it is not a
    lost file: the move still replaces whatever sits at the destination, so a
    model reading its own view directory renders correctly once and then reads
    its own output forever — but only when `--out` points at a directory
    CONTAINING the file the model reads. OpenSCAD resolves `surface(file = ...)`
    against the entry file's directory, so with `--out` genuinely elsewhere the
    written PNG never lands on the read one and consecutive runs are identical.
    This paragraph omitted that condition until the v0.7.6 pre-tag audit, which
    measured both shapes; the CHANGELOG had already been corrected and the
    docstring left behind, in the same commit.

    Measured on 2021.01 for the case that does compound — a model reading
    `sub/renders/iso.png`, rendered with `--out sub` — run 1 gives a correct
    `render_bbox`, and from run 2 the heightmap IS partspec's own view, so the
    part takes that image's extent: `IMAGE_SIZE` is 800x800 and `surface()`
    spans one unit per pixel gap, giving 799 in x and y, at exit 0 with nothing
    on stderr, on every run after.

    **That is the residue this function no longer ships.** #226 landed the
    signal, #263 applied it to the STL move, and #267 applies it here:
    `_wrote_over_an_input` refuses a destination the render actually read, on
    the engine's own dependency list rather than on a guess. No second `-d`
    pass is needed — a `surface()` target is opened when the source is parsed,
    so the STL pass's depfile already names the heightmap — and the guard is
    asked of every view **before any view moves**, which is the constraint the
    batched move below exists for.

    What survives is the case no depfile reaches: an engine with no `-d` writes
    nothing to ask, and there this path keeps the behaviour it had, which was
    no guard at all. A refusal nothing can justify would be worse than the
    residue.
    """
    # Collected here and forwarded, rather than forwarded and forgotten: the
    # pre-flight below needs the same answer, and a second `-d` pass over four
    # PNG invocations would only re-read what one parse of one source already
    # said.
    stl_deps: list[RenderDeps] = []
    unresolved: list[str] = []
    stl = render(source, out_dir, timeout_s=timeout_s, deps_out=stl_deps, unresolved_out=unresolved)
    if deps_out is not None:
        deps_out.extend(stl_deps)
    if isinstance(stl, BuildError):
        return stl
    if unresolved:
        # HERE, and not in the caller (#307). Below this point the four views
        # are rendered into a scratch directory and moved into place as a
        # batch, so a guard asked after `_render_files` returns leaves four
        # PNGs of the wrong part on disk -- measured during #306's review. This
        # is the seam the docstring's "before any view moves" constraint
        # already names, reached one step earlier: no view has been rendered
        # yet at all, so a previous run's four PNGs are byte-for-byte untouched.
        # Not "writes nothing" -- the STL above IS written, and is how the fault
        # was detected; measured, it replaces the previous run's export. The
        # caller separately removes a stale `render.json`, as it does on every
        # failing render (`cli.py`, #21).
        #
        # A picture is the one output a reader trusts without checking, which
        # is why `render` could not keep the exemption #286 gave it.
        return _hollowed_views(unresolved[0])
    if stl_deps:
        # The same refusal through the other channel (#309, #355). A file the
        # engine asked for and could not open emits no stderr marker -- an
        # absent `import()` target renders as nothing -- so `unresolved` above is
        # empty and the STL is well-formed. `check` refuses this at exit 4 while
        # `render` wrote four PNGs of a part missing a piece.
        #
        # Here for the reason the guard above is here, in as many words: below
        # this point the views are rendered and moved as a batch, so a refusal
        # asked later leaves four pictures of the wrong part on disk. A picture
        # is the one output a reader trusts without checking.
        from ..runner import absent_build_inputs

        absent = absent_build_inputs(source, stl_deps[-1], out_dir, timeout_s, source.path)
        if absent:
            return _absent_input_views(absent)
    closure = include_closure(source.path)
    executable = find_executable()
    assert executable is not None  # render() just used it

    if source.method:
        prepared = _method_scratch(source, out_dir)
        if isinstance(prepared, BuildError):
            return prepared
        scratch, render_path, defines = prepared, prepared, []
    else:
        scratch, render_path, defines = None, source.path, _define_args(source.params)

    bbox = _stl_bbox(stl)
    renders: dict[str, Path] = {}
    finished: list[tuple[Path, Path]] = []
    renders_dir = out_dir / "renders"
    try:
        try:
            renders_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                dir=renders_dir, prefix=".partspec-build-", ignore_cleanup_errors=True
            ) as build_dir:
                for view, rot in VIEWS.items():
                    png = renders_dir / f"{view}.png"
                    staged = Path(build_dir) / png.name
                    cmd = [
                        executable,
                        "--camera",
                        _camera(bbox, rot),
                        "--imgsize",
                        f"{IMAGE_SIZE[0]},{IMAGE_SIZE[1]}",
                        "--projection",
                        "ortho",
                        "--colorscheme",
                        "Cornfield",
                        "-o",
                        str(staged),
                        *defines,
                        str(render_path),
                    ]
                    try:
                        proc = subprocess.run(
                            cmd, capture_output=True, text=True, timeout=timeout_s, check=False
                        )
                    except subprocess.TimeoutExpired:
                        return BuildError(
                            f"openscad timed out after {timeout_s}s", origin="environment"
                        )
                    except OSError as exc:
                        # Caught here rather than by the clause below, which
                        # would report a failure to EXEC as a failure to write.
                        return BuildError(
                            f"could not run the openscad binary at {executable!r}: {exc.strerror}",
                            origin="environment",
                        )
                    if _display_failure(proc.returncode, proc.stderr):
                        return BuildError(
                            "this OpenSCAD cannot render PNG without a display",
                            origin="environment",
                            hint=NO_DISPLAY_HINT,
                            stderr=proc.stderr,
                        )
                    if proc.returncode != 0:
                        return BuildError(
                            f"openscad exited {proc.returncode} rendering the {view} view",
                            hint=_first_error_line(proc.stderr),
                            stderr=proc.stderr,
                        )
                    # Asked of the staged file: the scratch directory is this
                    # call's own and was created empty, so a view the engine
                    # never wrote cannot be answered by the previous run's PNG.
                    if not staged.is_file() or staged.stat().st_size == 0:
                        return BuildError(
                            f"openscad exited 0 but wrote no {view} view",
                            hint=_first_error_line(proc.stderr),
                            stderr=proc.stderr,
                        )
                    finished.append((staged, png))
                    renders[view] = png
                # Every view is moved only once all four exist. Replacing each
                # as it finishes would leave the LATER views reading the
                # EARLIER ones — the same model is re-parsed per view, so a
                # `surface(file = "renders/iso.png")` would see the freshly
                # written iso view from the front view onward, and the four
                # images would depict four different parts.
                #
                # A destination that is a directory is refused BEFORE the first
                # move. `os.replace` cannot replace one, and discovering that on
                # view 3 left views 1-2 fresh and 3-4 stale under a message
                # saying nothing was written — measured, and the exact mix this
                # batch exists to prevent (adversarial review of #230).
                blocked = [
                    png
                    for _, png in finished
                    # NOT `png.is_dir()`: that follows symlinks and `rename(2)`
                    # does not follow its destination, so a symlink pointing at
                    # a directory is replaced by the rename exactly as any
                    # other symlink is — measured. Refusing it turned a working
                    # render into a failure and called a symlink a directory
                    # (adversarial review of #234).
                    if (png.exists() or png.is_symlink()) and stat.S_ISDIR(png.lstat().st_mode)
                ]
                # In the same pre-flight, and for the same reason it exists:
                # every view is asked before any view moves. A per-view
                # refuse-then-continue would let three land and the fourth
                # refuse, leaving a directory of images from two builds — the
                # exact mix the batched move was written to prevent (#234).
                #
                # `refuse_unanswered=False`, so an engine that cannot name its
                # inputs keeps the behaviour this path had before #267: none.
                # The residue documented above survives there rather than
                # becoming a refusal nothing can justify.
                if closure.partial and stl_deps:
                    read = next(
                        (
                            refusal
                            for _, png in finished
                            if (
                                refusal := _wrote_over_an_input(
                                    stl_deps[0],
                                    png,
                                    source.path.name,
                                    closure=closure,
                                    refuse_unanswered=False,
                                    what="view artifact",
                                )
                            )
                            is not None
                        ),
                        None,
                    )
                    if read is not None:
                        return read
                if blocked:
                    return BuildError(
                        f"the view artifacts cannot be moved into place: "
                        f"{', '.join(str(p) for p in blocked)} "
                        f"{'is a directory' if len(blocked) == 1 else 'are directories'}",
                        origin="environment",
                        hint="remove it, or render into a different output directory — "
                        "nothing in the output directory has been touched",
                    )
                # And if one fails anyway — a full disk, a permission change
                # under us — the count is reported rather than the caller being
                # told nothing was written while half the set is new. There is
                # no atomic rename of four files; the honest thing is to say
                # which state the directory is actually in.
                for moved, (staged, png) in enumerate(finished):
                    try:
                        staged.replace(png)
                    except OSError as exc:
                        # Nothing moved yet is its own sentence, and carries the
                        # pre-flight's guarantee. "the 0 view artifact(s)
                        # already moved ... are from this run and the rest are
                        # not" described a corrupted directory that was in fact
                        # untouched -- the thesis inverted, in the branch added
                        # to stop exactly that (adversarial review of #234).
                        if moved == 0:
                            return BuildError(
                                f"no view artifact could be moved into {renders_dir}: "
                                f"replacing {png.name} failed ({exc.strerror})",
                                origin="environment",
                                hint="nothing in the output directory has been touched",
                            )
                        return BuildError(
                            f"the {moved} view artifact(s) already moved into {renders_dir} "
                            f"are from this run and the rest are not: replacing {png.name} "
                            f"failed ({exc.strerror})",
                            origin="environment",
                        )
            return renders
        except OSError as exc:
            return BuildError(
                f"could not write the view artifacts to {renders_dir}: {exc.strerror}",
                origin="environment",
            )
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)


_NOISE = re.compile(
    r"^(Geometries in cache|Geometry cache size|CGAL Polyhedrons in cache|"
    r"CGAL cache size|Total rendering time|Rendering finished|"
    r"Top level object is|Contours:|"
    r"Vertices:|Halfedges:|Edges:|Halffacets:|Facets:|Volumes:|Simple:)"
)
"""Bookkeeping OpenSCAD prints before (and instead of) its diagnosis: cache
statistics on both engine versions, and the geometry-summary block that can
accompany the exit-0-no-geometry branch. Both binaries print `Geometries in
cache:` FIRST, so the first-wins fallback below handed an agent a cache
statistic as the hint — confidently irrelevant — while `Current top level
object is empty.` sat one line down (#37)."""


def _signal_lines(stderr: str) -> list[str]:
    """stderr with blanks and known bookkeeping removed, in order.

    Factored out so the origin and the hint filter noise through ONE list.
    `_first_error_line` then applies its ERROR/WARNING preference over these;
    `_is_unknown_option` takes the first, deliberately not the preference.
    """
    return [
        line.strip()
        for line in stderr.splitlines()
        if line.strip() and not _NOISE.match(line.strip())
    ]


_UNKNOWN_OPTION = re.compile(r"unrecognised option|unrecognized option|unknown option", re.I)
"""The engine rejecting a FLAG rather than the source.

Measured on the apt 2021.01 binary, which is what Debian and Ubuntu ship:

    $ openscad --backend=CGAL -o out.stl m.scad
    unrecognised option '--backend=CGAL'
    Usage: openscad [options] file.scad

Both British and American spellings are matched because the message comes from
boost::program_options in one version and the engine's own parser in another,
and neither is a spelling this project controls. Deliberately narrow: it names
only the failure mode where the ENGINE could not accept what partspec passed,
which is the whole class that must not be blamed on the part."""


def _is_unknown_option(stderr: str) -> bool:
    """Whether the engine rejected an option rather than the model.

    Shares `_first_error_line`'s NOISE FILTER — one list, kept in step by being
    one list — and then takes the first line, which is not what that function
    does. Reading `lines[0]` raw let the two disagree silently: the cache
    statistics both binaries print FIRST would push a rejection to line two,
    reverting the classification to `model` while the hint still named the
    option, which is the bug this branch fixes.

    But delegating to `_first_error_line` wholesale was worse, and briefly
    shipped on this branch: it prefers a line containing `ERROR`/`WARNING`
    ANYWHERE in stderr, so a 58-line usage dump came into scope. Today's
    2021.01 dump survives on letter case alone — it contains "errors)" and
    "Stop on the first warning", both lowercase — and an engine that
    capitalised either word would flip the origin back to `model` with nothing
    to show for it (PR #160 review, R2). A CLI-level rejection is printed
    before any compilation output, so the first signal line is the whole
    question and the dump is never in scope.

    Coupling the filter is the property, not immunity to noise. A line `_NOISE`
    does not know — a Mesa/libEGL warning on a headless box, say — still
    displaces the rejection, and displaces the hint with it, so the report stays
    self-consistent and `build_stderr` carries the whole text either way. The
    fix for such a line is to teach `_NOISE` about it once it is observed;
    guessing at the list here would be a second filter to keep in step.

    One line, not a window. Anything looser reads the `Usage:` dump that
    follows, which lists every allowed option and on some builds contains this
    very phrase: a three-line window classified `ERROR: Parser error` plus a
    usage dump as an engine fault, which is an ordinary compile failure blamed
    on the machine. Both directions are pinned by test.
    """
    lines = _signal_lines(stderr)
    return bool(lines) and _UNKNOWN_OPTION.search(lines[0]) is not None


def _first_error_line(stderr: str) -> str | None:
    """The engine's own diagnosis, preferring its ERROR/WARNING lines.

    The fallback is the point. Matching only ERROR/WARNING silently discarded
    every failure OpenSCAD reports in its own voice — `unrecognised option
    '--backend=CGAL'`, which is exactly what a 2021.01 engine says to a contract
    written against a newer one, reduced to `openscad exited 1` and no hint.
    A failure that is visible but unexplained sends a reader off to guess, which
    is a quieter version of the thing this tool is against.

    First-wins, deliberately: on the 2021.01 `--backend` failure the reason is
    printed first and a long `Allowed options:` usage dump follows, so last-wins
    would return a fragment of the dump. Known noise is filtered before
    selection instead, which needs no special-casing of any message.
    """
    lines = _signal_lines(stderr)
    for line in lines:
        if "ERROR" in line or "WARNING" in line:
            return line
    # CLI-level failures are diagnosed before any compilation output, so the
    # first line is the reason and everything after it is a usage dump.
    return lines[0] if lines else None


# --------------------------------------------------------------------------
# The include closure — what a report's provenance actually has to cover
# --------------------------------------------------------------------------

_INCLUDE_RE = re.compile(r"\b(include|use)\s*<([^>\n]*)>")

_EXTERNAL_DATA_RE = re.compile(
    # Modules and functions whose NAME is the claim that a file is read.
    r"\b(?:import_stl|import_dxf|import_off|import|surface"
    r"|dxf_linear_extrude|dxf_rotate_extrude|dxf_dim|dxf_cross)\s*\("
    # And the two whose name is not: an extrude reads a DXF only when it is
    # given `file=`, and matching the bare name would fire on nearly every
    # OpenSCAD model ever written.
    r"|\b(?:linear_extrude|rotate_extrude)\s*\([^)]*\bfile\s*="
)
"""Every way an OpenSCAD source reads a data file, not just the modern two.

`import()` was the whole pattern until an adversarial review of #187 found
`import_stl(` walking through it: `\\s*\\(` demands the paren straight after
`import`, and 2021.01 — the version this tier targets, and what Debian and
Ubuntu ship — still executes the deprecated spelling, warning and all. Missing
it made `reads_external_data` false for a file the render genuinely reads, so
the closure claimed a completeness it did not have (SPEC-report §8.3), and the
`measure --out` guard that asks this question was answered wrongly: three runs
against `import_stl("input.stl")` ate their own input and reported
`[30,10,10]`, `[50,10,10]`, `[70,10,10]`, each at exit 0.

The deprecated `dxf_*` forms are matched by name because a file is all they
take. `linear_extrude`/`rotate_extrude` are matched only with `file=`, since
the overwhelming majority of their uses extrude a child and read nothing."""


# make-style depfile tokens: runs of non-space, with `\ ` escaping a space.
# A trailing `\` before a newline is a line continuation and matches neither
# alternative, so continuations terminate a token rather than joining into one.
_DEPS_FLAG_OK = True
"""Whether this process has seen the engine accept `-d`.

Set false the first time a build is rejected for it, and that build is retried
without it. `-d` has been in OpenSCAD since long before 2021.01 and is in
current master, so this is expected to stay true — but a `PARTSPEC_OPENSCAD`
pin can name any binary, and the alternative to degrading is that EVERY render
fails on such a build, under a hint telling the reader to drop a contract
argument they never passed. Provenance is not worth a render.
"""


_DEPS_RE = re.compile(r"(?<![\w-])(?:-d|--d)(?![\w-])")
"""The `-d` flag as an engine's REJECTION LINE names it, never as its usage does.

Matched against `_signal_lines(...)[0]` alone, for the reason
`_is_unknown_option` gives at length and this constant re-learned the hard way:
a rejection is followed by a `Usage:` dump listing every allowed option, and on
2021.01 line 46 of it reads `-d [ --d ] arg  deps_file -generate a dependency
file for make`. Searching the whole of stderr therefore matched on EVERY
rejected option — `--backend=CGAL` on 2021.01 is the ordinary case — so any
such build silently disabled depfiles for the rest of the process. Caught by
the suite, not by review, and pinned below.

`deps_file` is deliberately not in the pattern: it appears only in that dump's
prose, never in a rejection.
"""


_DEP_TOKEN = re.compile(r"(?:[^\s\\]|\\.)+")


@dataclass(frozen=True, slots=True)
class RenderDeps:
    """What the engine says it actually read, from `openscad -d`.

    `Closure` is what a *static* reader can see; this is what the render
    resolved. The two are complementary and neither supersedes the other —
    measured on 2021.01, a **missing** `include` is not listed here at all (the
    depfile names what was successfully opened, never what was requested), so
    `include_closure`'s regex stays the only thing that knows an include was
    asked for. What this adds is the half no static reader can have: a
    `surface(file = ...)` target, and an `import(names[i])` whose path is
    computed at render time.
    """

    state: str
    """`complete`, `partial` or `absent` — and `absent` MUST NOT read as `complete`.

    - `complete` — the engine exited 0 and wrote a depfile: its resolved input
      set, in full.
    - `partial` — the engine failed but wrote a depfile: what it had opened
      before it stopped, which is a floor and not the whole set.
    - `absent` — no depfile at all. Nothing may be concluded from it; in
      particular it is not "the render read nothing", which is what an empty
      `files` under any other state would mean.

      **Which failures land here is engine-version-dependent, so do not key on
      the cause.** Measured: 2021.01 writes nothing for a syntax error (exit 1,
      no file) while the 2026.08.01 snapshot writes one anyway, making the same
      broken model `absent` on one engine and `partial` on the other. That is
      F13, and the first cut of this feature shipped a test asserting the
      2021.01 answer as universal. What holds on both is the only thing worth
      asserting: a failed render is never `complete`.
    """

    files: tuple[Path, ...] = ()
    """Resolved dependencies, sorted. Absolute, except where noted in `missing`."""

    listed: tuple[Path, ...] = ()
    """The same dependencies, cwd-joined but **not** resolved.

    `files` is what the render read; this is how the depfile SPELLED it, and
    the difference is the whole of #311's second bug. OpenSCAD writes each
    token as `searchdir + reference`, so the token always carries the
    `include` literal as a suffix -- measured with a library reached through a
    directory symlink and again through a file symlink, both engines, and in
    every case the token was `<searchdir>/MCAD/units.scad`. Resolving it
    throws that away: the symlink's target has a different tail, and a decoy
    among the inputs that still ends with the literal becomes the unique
    match. Suffix matching is exact against `listed` and a guess against
    `files`, so `_from_engine_inputs` is fed this one.

    `files` remains what everything else uses: identity comparisons, the
    overwrite guard and `missing` all need the resolved path, and two spellings
    of one file must not read as two files.
    """

    missing: tuple[Path, ...] = ()
    """Listed dependencies that do not exist on disk.

    Not a contradiction and not a parse failure: a **missing** `import()` target
    is listed by its resolved absolute path (measured), which is strictly more
    than the silence partspec had before — it names a build input the model
    wanted and did not get. Anything hashing this list must treat `ENOENT` as a
    normal outcome.
    """


def _parse_depfile(text: str, cwd: Path, *, resolve: bool = True) -> tuple[Path, ...]:
    """Dependencies from a make-style depfile, entry file included.

    The target is everything up to the first colon and is dropped. Paths are
    joined to `cwd` because they are not uniformly absolute: OpenSCAD
    emits resolved dependencies absolute but **echoes the invoked source as it
    was given**, and partspec passes `source.path` unresolved (`contract.py`
    builds `Source` with a bare `Path(path)`), so a contract saying
    `openscad("part.scad")` puts a relative entry in this list.

    `resolve=False` stops there and keeps the token's own spelling, which is
    what `RenderDeps.listed` is for.
    """
    _, _, body = text.partition(":")
    out: set[Path] = set()
    for match in _DEP_TOKEN.finditer(body):
        token = re.sub(r"\\(.)", r"\1", match.group())
        if token:
            joined = cwd / token
            out.add(joined.resolve() if resolve else joined)
    return tuple(sorted(out))


def _read_depfile(path: Path, *, ok: bool) -> RenderDeps:
    """Grade a render's depfile. `ok` is whether the engine exited zero."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return RenderDeps(state="absent")
    files = _parse_depfile(text, Path.cwd())
    return RenderDeps(
        state="complete" if ok else "partial",
        files=files,
        listed=_parse_depfile(text, Path.cwd(), resolve=False),
        missing=tuple(f for f in files if not f.exists()),
    )


@dataclass(frozen=True, slots=True)
class Closure:
    """Every source file a render reads, and an honest account of the rest.

    A digest over the entry file alone is not an identifier for the build. The
    gridfinity bin in the dogfood corpus is one file of **sixteen**; edit a
    helper three levels down and the part changes while the entry file's hash
    does not. That is the same class of silent drift as F13, and `diff` would
    have inherited it.
    """

    files: tuple[Path, ...]
    """Resolved members, entry file included, in sorted order."""

    unresolved: tuple[str, ...] = ()
    """`include`/`use` targets that could not be found on any search path."""

    unresolved_includes: tuple[str, ...] = ()
    """The subset of `unresolved` reached by `include`, not by `use`.

    The two are one regex and one set everywhere else, and for every other
    question that is right -- neither was read, so neither's contents are
    known. For the *variable list* they differ absolutely: `include` splices a
    file's top-level assignments into the entry and `use` imports only its
    modules and functions, so an unresolved `use` cannot shorten the list of
    names `-D` can bind by even one.

    Distinguished because saying otherwise is a false sentence with an
    actionable-and-wrong remedy: an unresolved `use` was told its variable list
    was short "so a variable declared there would be missing from it", and a
    reader who created that file to satisfy the hint reached `verdict: pass` on
    a `-D` the engine had dropped (review of PR #310).

    Include-*reachability*, not "an include seen anywhere in the walk": `use`
    stops the chain transitively, measured on the engine. See `include_closure`.

    **Not** the report/diff token spelled `unresolved_includes`
    (`runner.py`, `diff.py`), which is emitted from `unresolved` and covers
    `use` too. Same words, wider meaning; wiring one to the other would
    silently narrow the report."""

    reads_external_data: bool = False
    """True if `import()` or `surface()` appears anywhere in the closure.

    Those name STL/DXF/DAT files that are genuinely build inputs, and this does
    not resolve them — the path may be computed at render time, so no static
    reader can. Recorded rather than ignored: the closure must not claim to be
    complete when something it cannot see may have changed.
    """

    @property
    def partial(self) -> bool:
        """True when the closure is known not to cover every input."""
        return bool(self.unresolved) or self.reads_external_data

    @property
    def unresolved_reason(self) -> str | None:
        """Why a *pre-render* guard must refuse, phrased for one — None if it need not.

        One spelling, because two guards ask this question: the file-mode
        `--out` refusal in `cli._measure_resolved` and the source-directory
        one in `render`. A reader who trips both must not be told the same
        thing two ways, and the phrasing is the part of a refusal most likely
        to drift when it is written twice.

        **Narrower than `partial` since #263, and the difference is which
        signal can answer later.** This used to refuse on either arm of
        `partial`, because before the depfile nothing could ever do better. An
        `import()`/`surface()` target now is named in the engine's own
        dependency output, so refusing before the render refuses a case that
        becomes decidable seconds later — that arm moved to
        `_wrote_over_an_input`, which answers it exactly. An **unresolved
        include** is named nowhere: the depfile lists what was opened, never
        what was asked for (`RenderDeps`), so no later signal supersedes this
        one and refusing early is the only honest answer there is.

        For THIS guard, which is about not writing over a file the render may
        read. The *variable-list* question an unresolved include also spoils is
        answered later, by `_still_unbound` (#311) — a suffix match back from
        the opened path recovers the reference, which is enough to name a
        variable and not enough to prove a destination is not an input.
        """
        if self.unresolved:
            return f"has include(s) partspec could not resolve ({', '.join(self.unresolved)})"
        return None


_ASSIGNMENT = re.compile(r"([A-Za-z_$][A-Za-z0-9_]*)\s*=")
_DIRECTIVE = re.compile(r"\b(?:include|use)\s*<[^>]*>")


def top_level_variables(entry: Path, *, closure: Closure | None = None) -> set[str]:
    """Names assignable by `-D`, across the include closure.

    OpenSCAD's `-D name=value` overrides a **top-level** variable. If no such
    variable exists it is not an error there — the define is simply accepted and
    dropped, and the render proceeds with the file's own defaults.

    Only depth-zero assignments count: `bore_d` inside a module body is a local
    and `-D bore_d=...` does not reach it. Comments and string interiors are
    blanked first, so `// bore_d = 8` and `x = "wall = 2"` are not mistaken for
    declarations — a false positive here would re-open the hole rather than
    merely widen it.

    Read across the whole closure rather than the entry alone, because a
    library's parameters routinely live in an included `standard.scad`.

    `closure` is an already-walked closure to read instead of walking again —
    in particular one walked with `engine_inputs`, which sees a library only
    the engine could open (#311).
    """
    names: set[str] = set()
    for path in (closure if closure is not None else include_closure(entry)).files:
        try:
            text = _strip_noise(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue  # provenance is best-effort; see include_closure
        # `include <a.scad>` carries no semicolon, so it would otherwise merge
        # with the statement after it and hide that statement's assignment.
        text = _DIRECTIVE.sub(" ", text)
        depth = 0
        for statement in text.replace("\n", " ").split(";"):
            head: list[str] = []
            for ch in statement:
                if ch in "{([":
                    depth += 1
                elif ch in "})]":
                    depth = max(depth - 1, 0)
                elif depth == 0:
                    head.append(ch)
            if depth == 0:
                match = _ASSIGNMENT.match("".join(head).strip())
                if match:
                    names.add(match.group(1))
    return names


def unbound_parameters(
    entry: Path, params: dict[str, Any], *, closure: Closure | None = None
) -> list[str]:
    """Declared parameters that no top-level variable would receive.

    Special variables (`$fn`, `$fa`, `$fs`) are exempt: they are built in, so a
    file need not assign one for `-D` to take effect.

    `closure` is passed straight to `top_level_variables`.
    """
    declared = top_level_variables(entry, closure=closure)
    return sorted(n for n in params if not n.startswith("$") and n not in declared)


def _strip_noise(text: str) -> str:
    """Blank out comments and string interiors before scanning.

    Strings must be *tracked* rather than skipped, or a `//` inside one starts a
    comment that swallows the rest of the line. Their contents must not be
    scanned, or `x = "include <a.scad>"` is read as a dependency and reported
    unresolved — a false alarm, which is its own kind of dishonesty.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append('""')
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            out.append(" ")
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def library_path() -> list[Path]:
    """Where OpenSCAD looks for a library, after the including file's directory."""
    dirs = [Path(p) for p in os.environ.get("OPENSCADPATH", "").split(os.pathsep) if p]
    dirs.append(Path.home() / ".local/share/OpenSCAD/libraries")
    dirs.append(Path("/usr/share/openscad/libraries"))
    return dirs


def _from_engine_inputs(ref: str, engine_inputs: Sequence[Path]) -> Path | None:
    """The one file the render opened whose path ends with `ref`, or None.

    A depfile names what was successfully opened and never what was asked for
    (`RenderDeps`), so the suffix is the only way back from a listed path to
    the `include` that wanted it. Ambiguity is not resolved by guessing: two
    candidates ending in `MCAD/units.scad` leave the reference unresolved and
    the caller keeps #287's honest refusal, which is the answer that does not
    require knowing which one the engine spliced.

    The suffix only means anything against the token as the depfile SPELLED
    it, which is why the caller passes `RenderDeps.listed` and not `files`.
    OpenSCAD writes each token as `searchdir + reference`, so the literal is
    always a suffix of it; resolving first throws that away, and a library
    reached through a symlink arrives under its real name while a decoy that
    still ends with the literal becomes the unique hit. Measured, that read
    one library's variables behind another library's name: an artifact for a
    `-D` that never reached the geometry, and in a second shape an
    `origin="model"` verdict blaming a correct contract off the decoy's
    contents (#311, review round 2).

    Two spellings of ONE file are not an ambiguity, so the count is over
    resolved identity: a render that opened the same file by two search paths
    has still opened one file.
    """
    want = tuple(part for part in PurePosixPath(ref).parts if part not in ("", "."))
    if not want or ".." in want:
        return None
    hits = [f for f in engine_inputs if f.parts[-len(want) :] == want and f.is_file()]
    return hits[0] if len({f.resolve() for f in hits}) == 1 else None


def include_closure(entry: Path, *, engine_inputs: Sequence[Path] = ()) -> Closure:
    """Walk `include`/`use` transitively from `entry`.

    Resolution follows OpenSCAD's own rule: relative to the directory of the
    file containing the statement — *not* the top-level file — then the library
    path. Cycles are legal in OpenSCAD and terminate here on the visited set.

    A file that cannot be read is skipped rather than raised on: this is
    provenance, and failing a check because provenance was awkward would be the
    tail wagging the dog.

    `engine_inputs` is a *last resort* search path: the files a render reported
    opening (`RenderDeps.files`), consulted only where the ordinary rule finds
    nothing. It exists because an engine can read a library partspec cannot —
    the pinned 2026.08.01 AppImage carries `MCAD` inside its own squashfs, so
    `include <MCAD/units.scad>` resolves for the render and for nothing else
    (#311). Passing it makes the walk answer the question the render already
    answered; passing nothing leaves the walk exactly as static as before.
    """
    entry = entry.resolve()
    seen: set[Path] = {entry}
    unresolved: set[str] = set()
    unresolved_includes: set[str] = set()
    external = False
    # The flag is whether this file's top-level assignments reach the ENTRY's
    # top level, which needs an unbroken chain of `include`. Measured rather
    # than reasoned: with `entry` -> use -> include of a file declaring `X`,
    # the engine prints `Ignoring unknown variable 'X'`, where including that
    # file directly renders it. So `use` stops the chain even transitively, and
    # a set of "includes seen anywhere in the walk" would claim the entry's
    # variable list was shortened by a file that could never have widened it.
    spliced: set[Path] = {entry}
    queue: deque[tuple[Path, bool]] = deque([(entry, True)])
    search = library_path()

    while queue:
        current, reaches_entry = queue.popleft()
        try:
            text = _strip_noise(current.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if _EXTERNAL_DATA_RE.search(text):
            external = True
        for keyword, raw in _INCLUDE_RE.findall(text):
            ref = raw.strip()
            if not ref:
                continue
            spliced_here = reaches_entry and keyword == "include"
            found = next(
                (c for c in ((b / ref) for b in (current.parent, *search)) if c.is_file()), None
            )
            if found is None:
                found = _from_engine_inputs(ref, engine_inputs)
            if found is None:
                unresolved.add(ref)
                if spliced_here:
                    unresolved_includes.add(ref)
                continue
            resolved = found.resolve()
            if resolved not in seen:
                seen.add(resolved)
                if spliced_here:
                    spliced.add(resolved)
                queue.append((resolved, spliced_here))
            elif spliced_here and resolved not in spliced:
                # Reached first through a `use` and now through an `include`:
                # the second visit is what makes its own includes splice, and
                # `seen` alone would have swallowed it. Bounded -- a file is
                # queued at most twice, and never again once spliced.
                spliced.add(resolved)
                queue.append((resolved, True))

    return Closure(
        files=tuple(sorted(seen)),
        unresolved=tuple(sorted(unresolved)),
        unresolved_includes=tuple(sorted(unresolved_includes)),
        reads_external_data=external,
    )


def version(executable: str | None = None) -> str:
    """Report the engine version, for the report's provenance block."""
    exe = executable or find_executable()
    if exe is None:
        return "unknown"
    try:
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    # OpenSCAD prints its version to stderr.
    text = (proc.stderr or proc.stdout).strip()
    return text.replace("OpenSCAD version", "").strip() or "unknown"
