"""Command-line entry point.

CLI first, MCP later (D5) — and the reason matters: the real contract is the
report schema plus the exit code, not the verbs. If `check` printed prose for
humans, an MCP layer would become a parser and the tool would be built twice.
With machine-readable output first, MCP is a thin adapter and `diff`, CI
annotations and a scorecard all fall out of the same artifact.

argparse rather than a CLI framework: a handful of subcommands does not justify a
dependency, and the core package is deliberately stdlib-only.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys
import traceback
from pathlib import Path
from typing import Any, cast

from .backend import DEFAULT_TIMEOUT_S, BuildError, effective_timeout
from .contract import Part
from .docs import DOCS_URL, docs_root
from .install import install_hint
from .report import tool_version, write_placeholder
from .runner import run
from .status import EXIT_USAGE, ContractError, Status, Verdict, exit_code
from .target import Target, TargetError, resolve

__all__ = ["main"]

ENV_TIMEOUT = "PARTSPEC_TIMEOUT"
MAX_TIMEOUT_S = 1e8  # ~3 years; anything past this is "unbounded", said honestly


def _timeout_arg(text: str) -> float:
    """argparse type for --timeout: seconds >= 0, where 0 waives the bound."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds") from None
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(
            f"the budget must be a finite number of seconds >= 0 (0 waives it), got {text}"
        )
    if value > MAX_TIMEOUT_S:
        # setitimer overflows platform time_t far above this; refused here so
        # the failure is a usage message, not a traceback from the timer.
        raise argparse.ArgumentTypeError(
            f"a budget over {MAX_TIMEOUT_S:g}s is not a budget; use --timeout 0 to waive it"
        )
    return value


class _TimeoutUsage(Exception):
    """PARTSPEC_TIMEOUT holds something that is not a budget."""


def _timeout_s(explicit: float | None) -> float:
    """Resolve the run's build budget: flag, then environment, then default.

    Fully resolved here — never left implicit — so `invocation.timeout_s`
    always names the budget that actually governed a CLI run, including the
    default; a run stopped by a budget nobody typed must still be attributable
    to it from the artifact alone. A garbage `PARTSPEC_TIMEOUT` raises
    `_TimeoutUsage` rather than being silently ignored, because a
    machine-level bound that quietly stopped applying is the unbounded run
    wearing a configured one's clothes.
    """
    if explicit is not None:
        return explicit
    raw = os.environ.get(ENV_TIMEOUT)
    if raw is None or not raw.strip():
        return DEFAULT_TIMEOUT_S
    try:
        return _timeout_arg(raw)
    except argparse.ArgumentTypeError as exc:
        raise _TimeoutUsage(f"{ENV_TIMEOUT} is unusable: {exc}") from None


# One spelling of the `--out` default for the three CLI helps that share it,
# because documenting it three times and adding a test that the phrase appears
# is forbidden by AGENTS.md and rightly: a substring search reports that a
# string is present, which is not a claim anyone wanted to make, and
# `assert "outputs/<part-slug>" in help` passed a mutation that inverted the
# sentence around it into the exact error #277 exists to prevent.
#
# It does not reach everywhere the default is written -- the MCP docstrings,
# both docs and other prose still spell it out, none of them pinned to
# anything. `grep -rn "outputs/"` finds them.
#
# No enumeration here on purpose. Four drafts of this comment tried to say
# which copies existed -- "nothing to keep in step", then "the MCP pair", then
# "five", then a list of categories -- and every one was short, each missing a
# copy the next reviewer found with that grep. A description of the other
# copies is itself a copy, and goes stale the same way.
#
# What `tests/test_cli.py` pins is this constant's own text, against the
# directory `_out_dir` actually builds: setting it to "the current working
# directory" passed the entire suite before that pin existed, and inverting
# its anchor clause is caught now. It reaches nothing else. Nothing stops a
# help appending a sentence that restates the anchor, or one that contradicts
# it -- both were tried, both stayed green.
OUT_DEFAULT_DOC = (
    "<contract dir>/outputs/<part-slug>, beside the contract rather than in the working directory"
)


def _docs_epilog() -> str:
    """`--help`'s last lines: where the cited specs are, for this copy.

    Computed rather than constant because the answer differs between an
    install and a checkout, and a constant would have to name whichever one
    its author had.

    Hard-wrapped, and the parser takes `RawDescriptionHelpFormatter` for it.
    The default formatter re-fills the epilog to the terminal width, which
    broke the path across a line — measured at COLUMNS=80 against a real
    `uv tool install` root, where it spanned two lines, splitting at the
    hyphen already inside `site-packages`. Nothing inserted that hyphen and
    the path rejoins exactly, which is what makes the break hard to see and
    the line unselectable in one go. A located path that cannot be copied is
    barely better than the URL it replaced, and being pasteable is this
    line's whole value. (The "three lines" first written here came from a
    long scratchpad venv path, not the root this sentence names. The
    "inserted hyphen" half came from nowhere: no root length produces one,
    and both renders rejoin exactly — PR #350 review, NEW-B.)
    """
    root = docs_root()
    if root is None:
        return (
            "Specs cited in diagnostics (SPEC-report.md, SPEC-contract.md, ...) are\n"
            "not installed with this copy. On `main`, which may describe a release\n"
            f"other than this one:\n  {DOCS_URL}"
        )
    return (
        "Specs cited in diagnostics (SPEC-report.md, SPEC-contract.md, ...) ship\n"
        "with this copy, under `docs/` and `skills/` of:\n"
        f"  {root}\n"
        f"which `partspec --docs` prints. The same documents on `main`, which may be\n"
        f"ahead of this copy:\n  {DOCS_URL}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="partspec",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Verify CAD-as-code parts against declared engineering intent.",
        # Diagnostics cite the specs by section ("SPEC-report.md 7.1"), and for
        # anyone who installed rather than cloned every one of those citations
        # was a dead pointer unless the tool said where the documents are.
        # Found by dropping an agent on a cold install: it went looking for
        # SPEC-contract.md, could not find it, and inferred the API from
        # `inspect.getdoc` instead. The URL answered that; the wheel now
        # carries the documents themselves (#349), so the epilog names the
        # directory when there is one to name, and says there is not when
        # there is not.
        epilog=_docs_epilog(),
    )
    parser.add_argument("--version", action="version", version=f"partspec {tool_version()}")
    parser.add_argument(
        "--docs",
        action="store_true",
        help="print the directory the documents' own citations resolve against "
        "(`docs/AGENT-CONTRACT.md`, `skills/contract-authoring/SKILL.md`), and exit",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    check = sub.add_parser("check", help="build parts and check them against their contracts")
    check.add_argument(
        "targets",
        nargs="+",
        metavar="target",
        help="<module-path>[:<factory>] — several targets share one process, "
        "one report each, exit by the worst verdict",
    )
    check.add_argument(
        "--out",
        type=Path,
        default=None,
        # The shape change is deliberate — one directory cannot hold N reports
        # at one deterministic name — but it was undocumented, so a caller who
        # built paths against the single-target shape had them move underneath
        # on adding a second target.
        help="report directory: DIR/report.json for one target, "
        "DIR/<part-slug>/report.json for several "
        f"(default: {OUT_DEFAULT_DOC}). On a tier that builds a file the "
        "artifact lands here too, beside the report",
    )
    check.add_argument("--quiet", action="store_true", help="suppress the human summary")
    check.add_argument(
        "--render",
        action="store_true",
        help="also write the canonical views and record their paths in the "
        "report; with several targets, into each part's own report directory",
    )
    check.add_argument(
        "--timeout",
        type=_timeout_arg,
        default=None,
        metavar="SECONDS",
        help=f"build budget in seconds (default {DEFAULT_TIMEOUT_S:g}, or "
        f"{ENV_TIMEOUT}; 0 waives the bound)",
    )
    pin_group = check.add_mutually_exclusive_group()
    pin_group.add_argument(
        "--expect",
        type=Path,
        default=None,
        metavar="LOCK",
        help="fail (error, exit 4) unless the declared claims match this pin exactly",
    )
    pin_group.add_argument(
        "--pin",
        type=Path,
        default=None,
        metavar="LOCK",
        help="write the declared claims to this pin file, then check normally",
    )

    measure = sub.add_parser(
        "measure",
        help="dump every quantity the backend can honestly produce (no verdict)",
    )
    measure.add_argument("target", help="<module-path>[:<factory>]")
    # NOT `check`'s "report directory", and the bare flag read as if it were:
    # `measure` writes no report by design (SPEC-report.md scope — the payload
    # is stdout), so `--out DIR` on the OCCT tier accepted a path, exited 0 and
    # created nothing. Same flag name, different noun, no help text to tell
    # them apart. The help that fixed that reading invited the next one (#187):
    # "where the .stl goes" reads as a filename, and a filename made a
    # DIRECTORY of that name — so a `.stl` filename is now honoured as one.
    #
    # `str`, not `type=Path`, alone among the `--out` flags: this is the one
    # that has to tell a file from a directory, and `Path` erases the single
    # syntactic signal that settles it — `Path("run.2026-08-13/")` is
    # indistinguishable from `Path("run.2026-08-13")`, so a trailing separator
    # could not mean what every shell user means by it.
    measure.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help="where the engine's build artifact goes: a PATH ending in .stl IS "
        "the artifact, replaced only once the build succeeds, so a failed run "
        "leaves what was there. Any other PATH — a trailing "
        f"{os.sep!r}, an existing directory, any other suffix — is a directory "
        "to write <source>.stl in, and the MODEL'S OWN directory is refused "
        "when that name is already taken and the source closure is partial (it "
        "reads external data, or has includes partspec could not resolve). A "
        "file is refused when nothing would be written to it (the OCCT tier "
        "builds in memory) or when that same closure is partial, because an "
        "import()ed .stl is an input, not an output. Omitted, PATH defaults to "
        f"{OUT_DEFAULT_DOC} — on a tier that builds a file at all. The OCCT "
        "tier builds in memory, so it writes nothing there and creates not "
        "even the directory, `measure` having no report to put in it. The "
        "measurements themselves go to stdout — this verb emits no report "
        "file",
    )
    measure.add_argument(
        "--timeout",
        type=_timeout_arg,
        default=None,
        metavar="SECONDS",
        help=f"build budget in seconds (default {DEFAULT_TIMEOUT_S:g}, or "
        f"{ENV_TIMEOUT}; 0 waives the bound)",
    )

    render = sub.add_parser(
        "render",
        help="write the canonical views (iso, front, top, right) as PNGs — no verdict",
    )
    render.add_argument("target", help="<module-path>[:<factory>]")
    render.add_argument(
        "--out",
        type=Path,
        default=None,
        # The only --out in this parser that carried no help at all, which is
        # the one place the #187 mistake -- passing a filename and getting a
        # directory of that name -- had no text standing in front of it.
        help="directory for render.json and the view PNGs, plus the build "
        f"artifact on a tier that writes one (default: {OUT_DEFAULT_DOC})",
    )
    render.add_argument(
        "--section",
        default=None,
        metavar="PLANE[:OFFSET]",
        help="also render a cut through xy, xz or yz at OFFSET mm "
        "(default: the bounding-box centre) — internal features made visible",
    )
    render.add_argument(
        "--timeout",
        type=_timeout_arg,
        default=None,
        metavar="SECONDS",
        help=f"build budget in seconds (default {DEFAULT_TIMEOUT_S:g}, or "
        f"{ENV_TIMEOUT}; 0 waives the bound)",
    )

    lint = sub.add_parser(
        "lint",
        help="advisory findings about CAD source — never a verdict on the part",
    )
    lint.add_argument("sources", nargs="+", type=Path, metavar="source", help=".scad or .py")

    vdiff = sub.add_parser(
        "vdiff",
        help="compare two runs' renders visually (exit 0 identical, 1 different, 2 indeterminate)",
    )
    vdiff.add_argument("old", type=Path, help="a render.json / report.json, or its directory")
    vdiff.add_argument("new", type=Path, help="the later run's artifact or directory")
    vdiff.add_argument(
        "--out",
        type=Path,
        default=None,
        help="directory for the per-view diff images (default: `vdiff` beside "
        "`new` — inside it when `new` is a directory, in its parent when `new` is a "
        "file; relative to the run compared, not to any contract)",
    )

    diff = sub.add_parser(
        "diff",
        help="compare two reports of one part semantically (exit 0 identical, "
        "1 different, 2 indeterminate)",
    )
    diff.add_argument("old", type=Path, help="the earlier report.json")
    diff.add_argument("new", type=Path, help="the later report.json")

    return parser


def _out_dir(target_spec: str, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    target = Target.parse(target_spec)
    return target.path.resolve().parent / "outputs" / target.slug


_SOURCE_ROOT = Path(__file__).resolve().parent


def _is_partspec_frame(frame: traceback.FrameSummary) -> bool:
    if frame.filename.startswith("<"):
        # `<string>` is usually a dataclass-generated `__init__` and
        # `<frozen ...>` the import machinery — partspec's implementation
        # under another name, with no source line to show. A contract MODULE
        # always has a real path (the loader imports it from a file), but code
        # the contract itself compiles does not, so this also hides frames
        # that are the reader's. They are counted in the marker, and where the
        # exception is not partspec's own they take the whole stack
        # unfiltered: the conservative side of a distinction the frame does
        # not carry.
        return True
    return Path(frame.filename).resolve().is_relative_to(_SOURCE_ROOT)


def _print_contract_traceback(exc: BaseException) -> None:
    """Print the traceback of an exception a contract raised, with partspec's
    own frames dropped (#188).

    The traceback stays because a contract is arbitrary Python: for a `TypeError`
    in user code it is the only thing that says *where*. What the reader did not
    ask for is partspec's call path to that line — six internal frames around one
    useful one, and for a `ContractError` (deliberately raised, with a message
    written for the reader) the internals are never the answer.

    Frames from a third-party library the contract called are kept: they are not
    partspec explaining itself, and a CadQuery operation that raised four calls
    deep is genuinely where the failure happened.

    What survives is printed *contiguously*, so every gap carries a
    `[N frames hidden]` marker. Without it the reprint reads as a direct call
    chain that never happened, and the reader most likely to be misled is an
    agent parsing it.

    Four cases print the whole thing unfiltered, because a filter that hides a
    partspec bug is the silence this tool exists to refuse:

    - **No contract frames at all** — the exception came from inside partspec
      before user code ran, so its frames are all there is.
    - **A partspec frame at or below the contract's own** and the exception is
      not partspec's — partspec code participated in the failure rather than
      merely reaching the contract, so an `AttributeError` from `region.py` is
      a partspec bug and its frames are the bug report. The leading frames that
      only got the process to the contract (`cli`, `target`) do not count: they
      are on every stack and are what #188 is about. A `ContractError` from the
      same position is a diagnosis written for the reader, and its frames are
      noise — the exception's own module is what separates the two.
    - **An exception group** — `format_exception_only` renders a group as its
      header alone ("2 sub-exceptions"), losing every sub-exception *and* the
      contract frames inside them, which is the opposite of the point.
    - **A chained exception** (`raise ... from`, or one raised while handling
      another) — the other segments of the chain are information.

    The chain case is a real limitation, not a rounding error: a contract doing
    `try/except → raise ContractError(...)` is idiomatic, and implicit
    `__context__` chaining sends it here. Filtering each segment independently
    was considered and refused for v1 — walking the chain means reproducing
    CPython's connector prose and its group tree by hand, and a filter that
    prints a *misleading* chain is worse than one that prints a noisy true one.

    Presentation only: the exit code (`EXIT_ERROR`), the "the contract is wrong,
    not the part" classification and the report on disk are untouched. Nothing
    is filtered out of an artifact — this path's report is `write_placeholder`'s,
    and the diagnosis lives on stderr alone (`AGENT-CONTRACT.md` §2.3), which is
    the only reason its shape is worth this much care.
    """
    frames = traceback.extract_tb(exc.__traceback__)
    first_contract = next((i for i, f in enumerate(frames) if not _is_partspec_frame(f)), None)
    chained = exc.__cause__ is not None or (
        exc.__context__ is not None and not exc.__suppress_context__
    )
    partspec_raised_it = type(exc).__module__.split(".")[0] == "partspec"
    partspec_in_the_failure = first_contract is not None and any(
        _is_partspec_frame(f) for f in frames[first_contract:]
    )
    if (
        first_contract is None
        or chained
        or isinstance(exc, BaseExceptionGroup)
        or (partspec_in_the_failure and not partspec_raised_it)
    ):
        # `print_exception`, not `print_exc`: the exception is passed in, so
        # the fallback must not depend on being inside its `except` block.
        traceback.print_exception(exc)
        return

    out = ["Traceback (most recent call last):\n"]
    hidden = 0
    # Surviving frames are formatted in RUNS, never one at a time:
    # `[Previous line repeated N more times]` is something `format_list`
    # can only see across a list, and formatting frame by frame deletes it.
    # A recursive contract printed 1995 stderr lines that way against 20
    # collapsed ones — a 125x amplification out of a change whose whole
    # purpose is removing six lines of noise, and it would reach the MCP
    # adapter as a stderr tail (`mcp.py`) holding nothing but identical
    # frames.
    run: list[traceback.FrameSummary] = []
    for frame in frames:
        if _is_partspec_frame(frame):
            out.extend(traceback.format_list(run))
            run = []
            hidden += 1
            continue
        out.append(_hidden_marker(hidden))
        hidden = 0
        run.append(frame)
    out.extend(traceback.format_list(run))
    out.append(_hidden_marker(hidden))
    out.extend(traceback.format_exception_only(exc))
    sys.stderr.write("".join(out))


def _hidden_marker(hidden: int) -> str:
    if hidden == 0:
        return ""
    # Not "partspec frames": a `<string>` frame the CONTRACT generated is
    # hidden by the same rule, and the count would be honest while the word
    # was not.
    return f"  [{hidden} frame{'s' if hidden > 1 else ''} hidden]\n"


ARTIFACT_SUFFIX = ".stl"
"""The one thing `measure --out` can name. The OpenSCAD tier exports binary
STL and nothing else (`--export-format binstl`, SPEC-backend §5 step 1), so
this is the whole set of filenames the flag can honour — not a default among
several.

Matched exactly, so `--out UP.STL` is a directory. partspec only ever writes
the lowercase form, which makes an uppercase `.STL` almost always a file that
came from somewhere else — hand-authored or downloaded — and those are the
ones least likely to be output and most expensive to lose."""


REFUSED_OUT_HINT = (
    "only the OpenSCAD tier writes a build artifact — drop --out; on this tier "
    "no --out path receives one, whatever its shape, and the measurements go to stdout"
)
"""The remedy for `--out <file>` on a tier that exports nothing.

Named rather than inlined because its exact words are a decision, not a
phrasing: `test_measure_refuses_a_filename_on_the_tier_that_exports_nothing`
asserts EQUALITY against its own literal copy, so changing this string fails a
test and the change gets read by someone. That is deliberate, and it is the
second attempt. The first pinned `"pass a directory" not in hint`, which pins
one spelling of the advice rather than the advice: an adversarial review put
"use a directory instead" back into the hint and the whole suite still
reported 950 passed."""


def _names_the_artifact(raw: str) -> bool:
    """Whether `measure --out` names the .stl rather than a directory for it.

    `measure` writes exactly one file, so a caller reading "where the .stl
    goes" passes the .stl. That used to make a *directory* called `a.stl`
    holding `spacer.stl` and exit 0 — a run that reported success having done
    something else — while the same path existing as a file exited 4 (#187):
    the same question answered by prior state instead of by the flag.

    Three rules, in order, and each closes a way of getting this wrong:

    1. A trailing separator is directory intent, stated by the caller. This
       is why the flag keeps the raw string.
    2. An existing directory is a directory, whatever it is called.
    3. Otherwise the *suffix the engine actually writes* decides — nothing
       else. "Any suffix" was the first attempt and it was worse than the bug
       it fixed: `--out run.2026-08-13/` made a mesh file where a dated output
       directory was asked for, and `--out spacer.scad` overwrote the run's
       own source with 13 KB of STL at exit 0. A path whose name the engine
       cannot produce is not a filename this flag understands, so it falls
       through to the directory rule and, if it exists, is refused there.
    """
    if raw.endswith(("/", os.sep)):
        return False
    path = Path(raw)
    if path.is_dir():
        return False
    return path.suffix == ARTIFACT_SUFFIX


def _hollowed_measurements(first_line: str) -> BuildError:
    """`measure` refusing a part the engine built out of something it lost.

    A `BuildError` rather than a bespoke branch so both `--out` forms end at
    the one `isinstance(artifact, BuildError)` arm, with one message. `origin`
    is never read on this path -- `_measure_failure` takes the message and hint
    directly -- so the default does not become a claim the way it would in
    `render`'s payload, which records one (#307).

    The cause and the hint come from `runner._unresolved_diagnosis`, which
    `check` reads too: a name that did not resolve and a value that would not
    convert are different faults with different remedies, and `measure` must
    not describe one of them differently from `check` (#308). What is local to
    this verb is the middle clause -- there is no report here to be wrong, only
    numbers that would be taken off the wrong part.
    """
    from .runner import _unresolved_diagnosis

    cause, hint = _unresolved_diagnosis(first_line)
    return BuildError(
        f"{cause}, so these would be measurements of something other than what "
        f"this source describes: {first_line}",
        hint=hint,
    )


def _absent_input_refusal(absent: list[str]) -> BuildError:
    """`measure` or `render` refusing a part built without a file it asked for.

    The cause and the hint come from `runner`, which `check` reads too: one
    engine fact must not be described differently depending on the verb (#308's
    rule, #355). What is local here is the middle clause -- there is no report on
    these paths to be wrong, only numbers and pictures that would be taken off
    the wrong part.

    `origin=None` deliberately. Whether the path is a typo or the file simply has
    not been generated yet is not something partspec can tell, so neither "model"
    nor "environment" may be asserted (SPEC-report §6.1) -- the same answer
    `check` gives by leaving `build_origin` null.
    """
    from .runner import _ABSENT_INPUT_CAUSE, _ABSENT_INPUT_HINT

    detail = (
        f"{_ABSENT_INPUT_CAUSE}, so these would be measurements of something "
        f"other than what this source describes: {absent[0]}"
    )
    if len(absent) > 1:
        detail += f" (and {len(absent) - 1} more)"
    return BuildError(detail, hint=_ABSENT_INPUT_HINT, origin=None)


def _build_to_file(
    backend: Any,
    source: Any,
    dest: Path,
    timeout_s: float,
    deps_out: list[Any] | None = None,
    *,
    closure: Any | None = None,
    refusal_out: list[BuildError] | None = None,
    unresolved_out: list[str] | None = None,
) -> Any | BuildError:
    """Build so the artifact lands at exactly `dest`, and only if it exists.

    **Nothing touches `dest` until there is an artifact to put there.** The
    engine runs in a scratch directory and the result is moved into place with
    `os.replace`, so the destination holds the old file or the new one and
    never neither: a failed build, a blown timeout or a Ctrl-C leaves whatever
    was there before, untouched.

    An earlier revision unlinked `dest` up front, reasoning that
    `openscad.render` does the same to its target so "a failed render leaves
    nothing behind for a later reader to pick up". That was wrong twice.
    `notes/FINDINGS.md` W9 states the remedy as an either/or — unlink the
    target *or* render to a fresh temp path and move it into place — and this
    function is the second branch, which is also the one FINDINGS praises
    `report.py` for. And the staleness W9 describes cannot arise here at all:
    the build happens in a fresh empty directory and the measurement is loaded
    from there, so `dest` is write-only for the whole run. What the unlink did
    reach was the caller's data. `.stl` is an *input* extension as well as an
    output one — SPEC-report §8.3 calls `import()`/`surface()` targets files
    that "genuinely are build inputs" — so deleting `dest` before the engine
    ran made a model importing it build without its import and report a
    confident, complete, wrong answer at exit 0. That is the defect #187
    exists to abolish, reintroduced by its own fix. `_measure_resolved`
    refuses a file destination for a model whose includes did not resolve, and
    this function refuses one the render is then found to have read (#263);
    neither removes anything it did not create.

    **The build happens in a scratch directory beside `dest`.** The engine
    names its export after the source file, so building straight into
    `dest.parent` would export `<source-stem>.stl` there first and unlink
    whatever the caller already had under that name — `--out models/a.stl`
    would destroy `models/spacer.stl`. Beside, rather than in the system temp
    dir, so the move into place is a rename on one filesystem. A symlink at
    `dest` is replaced by that rename rather than written through, so its
    target is untouched.

    The scratch directory is removed on every exit from this function,
    including exceptions and SIGINT; an uncaught signal — SIGTERM, SIGKILL —
    leaves a `.partspec-build-*` behind. Sweeping older ones is deliberately
    not done here: a concurrent `measure` writing another file in the same
    directory owns one of them, and this function cannot tell which.
    """
    import tempfile

    # One clause for every way the filesystem can refuse — an uncreatable
    # parent, an unwritable one, a failed move — because the caller's question
    # is the same in each: the artifact is not where you asked for it, and
    # that is the environment's doing, not the part's.
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=dest.parent, prefix=".partspec-build-", ignore_cleanup_errors=True
        ) as scratch:
            built = backend.build(
                source,
                Path(scratch),
                timeout_s=timeout_s,
                deps_out=deps_out,
                unresolved_out=unresolved_out,
            )
            if isinstance(built, BuildError):
                return built
            if closure is not None and closure.partial:
                # Asked here rather than before the build because here is where
                # it can be answered, and asked before the rename so that a
                # refusal leaves `dest` exactly as the caller left it. The
                # engine renders into a scratch directory of its own inside
                # this one, so the destination it was given was never `dest`
                # and its own copy of this guard cannot have fired.
                #
                # Reported through `refusal_out` as well as returned, because
                # this is the one failure here that is the CALLER'S ARGUMENT
                # rather than the environment: `--out` names a file the model
                # reads, and the remedy is a different path. It exited
                # `EXIT_USAGE` when the same invocation was refused statically
                # and it still does; a build failure and a bad argument are not
                # the same answer, and the exit code is the part of a refusal a
                # script reads.
                from .engines.openscad import RenderDeps, _wrote_over_an_input

                # An unpopulated `deps_out` is `absent`, not "no question to
                # ask". Reading a missing answer as a passing one is the shape
                # of failure this whole guard exists to refuse, and it would be
                # invisible: the artifact would land and the run would exit 0.
                #
                # Gated on the whole of `partial`, matching `render`, even
                # though the unresolved arm cannot reach here — the static
                # refusal above returns first. Passing the narrower question
                # would be true only for as long as that stays true.
                refusal = _wrote_over_an_input(
                    deps_out[-1] if deps_out else RenderDeps(state="absent"),
                    dest,
                    source.path.name,
                    closure=closure,
                    refuse_unanswered=True,
                )
                if refusal is not None:
                    if refusal_out is not None:
                        refusal_out.append(refusal)
                    return refusal
            if unresolved_out:
                # Before the rename, like the guard above and for the reason
                # this function's docstring gives: a refusal must leave `dest`
                # exactly as the caller left it. Asked after it, the "refusal"
                # replaced a good 272-facet artifact with the 12-facet hollowed
                # one and then declined to measure it (round-2 review of #306).
                #
                # AFTER the destination guard, not before, and the order is
                # load-bearing on one engine. `import_stl()` is a name
                # 2026.08.01 does not resolve, so both guards fire on
                # `imports_stl_data.scad` there and only there. The destination
                # question is the more urgent of the two -- it is about not
                # writing over the caller's file -- and its `EXIT_USAGE` is
                # pinned deliberately, so a script reading the exit code does
                # not see a build failure where an argument is what is wrong.
                # Answering it first keeps that answer identical on both
                # engines; this one still fires whenever the destination is
                # fine, which is every other case.
                return _hollowed_measurements(unresolved_out[0])
            if deps_out:
                # #286's failure through the other channel (#309, #355). The build
                # SUCCEEDED and the depfile is complete, so `unresolved_out` above
                # is empty by construction -- the engine had nothing to complain
                # about. What it could not open is visible only in the depfile, and
                # an `import()` of an absent target renders as nothing, so the mesh
                # is well-formed and it is not the part.
                #
                # Here rather than in the caller, and before the rename, for the
                # same reason as the two guards above: a refusal must leave `dest`
                # exactly as the caller left it. `check` refuses this at exit 4
                # while `measure` returned a number an agent would write into a
                # contract that then passes forever.
                from .runner import absent_build_inputs

                absent = absent_build_inputs(
                    source, deps_out[-1], Path(scratch), timeout_s, source.path
                )
                if absent:
                    return _absent_input_refusal(absent)
            (Path(scratch) / f"{source.path.stem}{ARTIFACT_SUFFIX}").replace(dest)
            return built
    except OSError as exc:
        return BuildError(
            f"could not write the build artifact to {dest}: {exc.strerror}",
            origin="environment",
        )


def _resolve_or_report(spec: str) -> tuple[Part, Target] | int:
    """Resolve a target, turning any failure into an exit code rather than a
    traceback.

    The second clause is the load-bearing one. A contract is Python, so it can
    raise anything — a typo in a keyword argument raises `TypeError` — and an
    uncaught exception leaves the interpreter exiting **1**, which is this
    tool's code for *the part failed its contract*. A broken question would
    report as a wrong answer, and in CI the two are indistinguishable. It is
    `EXIT_ERROR` for the same reason a `ContractError` raised during a run is:
    nothing was evaluated, so nothing may be said about the part.

    Resolution is also snapshot for the model-module registry: a CONTRACT that
    imports a helper beside the model puts it into `sys.modules` before the
    build's own snapshot, and PR #104's review reproduced POST-V0 §8's
    stale-helper build through exactly that path. Recording resolve-time
    additions against the model's directory closes it.
    """
    from .engines.pycad import record_model_modules

    modules_before = set(sys.modules)
    try:
        part, target = resolve(spec)
        # The CONTRACT's sibling imports too, for every engine: a shared
        # claims.py cached from directory A silently supplied directory B's
        # checks in one process (PR #112 review) — the same stale-module
        # class as the model-helper case, one loader over. Recording for the
        # model dir happens here; the contract dir is recorded in the finally,
        # so a contract that raises AFTER its sibling import succeeded still
        # has that sibling on the books (#114).
        if part.source.engine != "openscad":
            record_model_modules(part.source.path, modules_before)
        return part, target
    except TargetError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\npartspec: interrupted", file=sys.stderr)
        return 130
    except BaseException as exc:  # noqa: BLE001 - a contract may raise anything
        # BaseException, not Exception. A contract calling `sys.exit(0)` raises
        # SystemExit, which sailed past an `except Exception` and exited the
        # process **0** -- green, silent, zero checks evaluated. Worse, the code
        # was the contract's to choose: `sys.exit(2)` read as `incomplete` and
        # `sys.exit(3)` as `empty`. No exit code from user code may become a
        # partspec verdict. Scoped to resolution, so argparse's own SystemExit
        # (`--version`, a usage error) is untouched.
        _print_contract_traceback(exc)
        print(f"\npartspec: the contract raised {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  the contract is wrong, not the part", file=sys.stderr)
        return exit_code(Verdict.ERROR)
    finally:
        # Parseable without resolution, so the record exists on every outcome.
        record_model_modules(Target.parse(spec).path, modules_before)


_EXIT_PRECEDENCE = (130, EXIT_USAGE, 4, 3, 1, 2, 0)
"""Batch exit order: interrupt, usage, then SPEC-report §6.1's verdict
precedence (error, empty, fail, incomplete, pass). `empty` outranking `fail`
is the spec's call, not an accident: a contract that asserts nothing is the
vacuous-green case, and a batch hiding one behind a mere failure would bury
the more dangerous signal."""

_EXIT_WORD = {0: "pass", 1: "fail", 2: "incomplete", 3: "empty", 4: "error", EXIT_USAGE: "usage"}


def _batch_exit(codes: list[int]) -> int:
    for code in _EXIT_PRECEDENCE:
        if code in codes:
            return code
    return max(codes, default=0)


def _out_dir_for(spec: str, explicit: Path | None, *, batch: bool) -> Path:
    if explicit is not None and batch:
        # One directory cannot hold N reports at one deterministic name each;
        # every part gets its slug as a subdirectory.
        return explicit / Target.parse(spec).slug
    return _out_dir(spec, explicit)


def _cmd_check(args: argparse.Namespace, argv: list[str]) -> int:
    targets: list[str] = args.targets
    batch = len(targets) > 1

    # Invocation-SHAPE refusals come before anything touches disk: a shape
    # the tool won't run never meant to re-check anything. The collision
    # guard must precede the placeholder fan-out, or the fan-out itself
    # performs the shared-path overwrite the guard exists to refuse (PR #104
    # re-review, finding 7).
    #
    # `--render` was refused here too, as "single-target for now" — and the
    # "for now" was right: nothing under it was load-bearing. Every target
    # already gets its own `out` from `_out_dir_for`, renders land in that
    # directory's `renders/`, and each report records paths relative to
    # itself. Fleet agents in two arms hit the refusal, plus one in the
    # earlier spike; each dropped `--render` from the batch check and
    # rendered target by target through the standalone `render` subcommand,
    # which writes `render.json` and no report at all — a1's frozen log
    # carries 20 of them (#189).
    if batch and args.out is not None:
        slugs = [Target.parse(spec).slug for spec in targets]
        collisions = sorted({s for s in slugs if slugs.count(s) > 1})
        if collisions:
            # Refuse rather than let the last part silently overwrite the
            # first's report under one deterministic path.
            print(
                f"partspec: --out with several targets needs distinct slugs, and "
                f"{', '.join(collisions)} collide{'s' if len(collisions) == 1 else ''}; "
                f"rename a factory or drop --out for per-contract output directories",
                file=sys.stderr,
            )
            return EXIT_USAGE

    # EVERY target's placeholder goes down before ANY target runs — not per
    # target inside the loop. An invocation that dies mid-flight (garbage
    # PARTSPEC_TIMEOUT below, interrupt during part two) meant to re-check
    # the later targets too, and their previous `verdict: "pass"` sitting
    # untouched at the deterministic path is a stale artifact reading as
    # current — the worst failure in the system (SPEC-report 5, rules 1-2;
    # PR #104 review). `_out_dir_for` only parses the target string, so it
    # needs no resolved Part.
    for spec in targets:
        write_placeholder(_out_dir_for(spec, args.out, batch=batch), contract=spec, argv=argv)

    try:
        timeout_s = _timeout_s(args.timeout)
    except _TimeoutUsage as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    expect_lock: dict[str, dict[str, str]] | None = None
    if args.expect is not None:
        from .expectation import LockError, read_lock

        try:
            expect_lock = read_lock(args.expect)
        except LockError as exc:
            print(f"partspec: {exc}", file=sys.stderr)
            return EXIT_USAGE

    if expect_lock is not None:
        _warn_uncovered_before_building(targets, expect_lock, quiet=args.quiet)

    pinned_parts: dict[str, dict[str, str]] = {}
    covered_ids: set[str] = set()
    # Targets that were SUPPLIED and did not resolve. A target that failed has
    # no `part.id`, so it can cover nothing — and the coverage check below
    # cannot tell "you deleted this part" from "the target that makes it
    # crashed" without knowing one happened (#201).
    unresolved: list[str] = []
    codes: list[int] = []

    # The lock as it stood when the run BEGAN, read before the first target so
    # each part's own report can carry what the re-pin overwrites (#294). Every
    # report is written inside the loop below while the lock write comes after
    # it, so a read taken there would arrive after the artifact it belongs in.
    #
    # This snapshot answers for the REPORTS only. The guard and the stderr
    # confession re-read at the point of the write, because a build is seconds
    # long and this one is not: reusing it there let a part another process
    # added mid-run be compared away and dropped from the lock without the
    # `dropped` line `main` prints (adversarial review of #377, N1). Reports
    # are the one consumer that cannot re-read, having already been written.
    #
    # A lock that will not parse leaves this None, so no report carries the
    # block. That arrival is named in SPEC-report §7.1: absence means "nothing
    # was overwritten" only for a run whose lock was READABLE, and the
    # unreadable one is confessed on stderr at the write below.
    previous_pin: dict[str, dict[str, str]] | None = None
    if args.pin is not None and args.pin.is_file():
        from .expectation import LockError, read_lock

        try:
            previous_pin = read_lock(args.pin)
        except LockError:
            previous_pin = None

    for spec in targets:
        code = _check_one(
            spec,
            args,
            argv,
            timeout_s,
            batch=batch,
            expect_lock=expect_lock,
            pins=pinned_parts,
            covered_ids=covered_ids,
            unresolved=unresolved,
            previous_pin=previous_pin,
        )
        if code == 130:
            # The user's own abort is the one failure that DOES stop a batch.
            return 130
        codes.append(code)

    if args.pin is not None and pinned_parts:
        from .expectation import LockError, read_lock, repin_differences, write_lock

        # The previous pin is read on EVERY re-pin over an existing lock, not
        # only when a target crashed. Until #294 the read lived inside the
        # `unresolved` guard below, so the ordinary path — lock present, every
        # target resolved, a claim loosened — rewrote the claim set and printed
        # `pinned 1 part(s)`. Measured on 0.7.6: `envelope max=[40,30,6]`
        # became `max=[40,30,9]` in the lock at exit 0 with no other output.
        # `compare()` was already in this function, computing exactly the line
        # `--expect` prints one flag over, and unused on this branch.
        #
        # Re-read HERE, immediately before the write, rather than reusing the
        # pre-loop snapshot the reports were given. The two reads answer
        # different questions: the reports say what this run's claims moved
        # against the lock it started from, and cannot be rewritten afterwards;
        # the guard and the confession must speak for the file about to be
        # overwritten. Measured with a concurrent writer adding a part 2 s into
        # a 4 s build, the snapshot made the guard fail OPEN -- the added part
        # was written out of the lock with neither the `dropped` line nor a
        # refusal (adversarial review of #377, N1).
        previous: dict[str, dict[str, str]] | None = None
        unreadable: LockError | None = None
        if args.pin.is_file():
            try:
                previous = read_lock(args.pin)
            except LockError as exc:
                unreadable = exc

        # A lock that SHRINKS because a target crashed is silent weakening, and
        # `expectation.py` states the design goal it violates: "the tool's job
        # is to make the weakening IMPOSSIBLE to do silently, not impossible to
        # do." #201 removed the advice to do this and left the act itself
        # unguarded one flag over — measured, a crashed target dropped a part
        # from an existing lock with only `pinned 2 part(s)` on stdout
        # (adversarial review of #243).
        #
        # Refused rather than warned: `--pin` overwrites, so by the time a
        # warning is read the claim set is already gone.
        if unresolved and args.pin.is_file():
            if unreadable is not None:
                # NOT `{}`. Inside `is_file()` a LockError means unreadable,
                # malformed, or a schema this build does not know — never "no
                # lock yet", which the branch already excluded. Treating it as
                # empty said "nothing can be lost" about precisely the locks
                # whose contents cannot be checked, and then overwrote them:
                # measured, a schema-2 lock covering two parts was silently
                # rewritten as a one-part schema-1 lock because a target
                # crashed (round-3 review of #243). Failing open is the one
                # direction this guard must not fail.
                print(
                    f"partspec: refusing to re-pin: {unreadable}, so partspec cannot tell "
                    f"whether writing it would drop a claim set — and {
                        ', '.join(repr(s) for s in sorted(set(unresolved)))
                    } did not resolve",
                    file=sys.stderr,
                )
                print(
                    "  hint: fix the failing target and re-run, or delete the lock to "
                    "re-pin from scratch",
                    file=sys.stderr,
                )
                codes.append(exit_code(Verdict.ERROR))
                return _batch_exit(codes)
            assert previous is not None
            lost = sorted(previous.keys() - pinned_parts.keys())
            if lost:
                failed = ", ".join(repr(s) for s in sorted(set(unresolved)))
                print(
                    f"partspec: refusing to re-pin: {failed} did not resolve, and writing "
                    f"{args.pin} now would drop "
                    f"{', '.join(repr(p) for p in lost)} from it",
                    file=sys.stderr,
                )
                print(
                    "  hint: fix the failing target and re-run. If the removal is "
                    "deliberate, delete the lock and re-pin from scratch — a lock cannot "
                    "be written in part, so partspec cannot keep the deliberate half "
                    "while a target is unresolved",
                    file=sys.stderr,
                )
                codes.append(exit_code(Verdict.ERROR))
                return _batch_exit(codes)

        write_lock(args.pin, pinned_parts)
        if not args.quiet:
            print(f"pinned {len(pinned_parts)} part(s) -> {args.pin}")
            # Flushed so the differences below land UNDER that line and not
            # above it: stdout is block-buffered whenever it is not a tty, and
            # a confession that sorts above the headline it qualifies reads as
            # belonging to the previous target in a batch.
            sys.stdout.flush()

        # stderr, and NOT suppressed by --quiet, like every other confession on
        # this branch. A re-pin under `--quiet` is exactly the invocation a
        # weakening would use, and #294's requirement is that the move be
        # impossible to make SILENTLY — not that it be refused, which §4 of the
        # agent contract permits.
        if unreadable is not None:
            print(
                f"partspec: rewrote {args.pin}, which could not be read first "
                f"({unreadable}), so partspec cannot say which claims moved",
                file=sys.stderr,
            )
        elif previous is not None:
            moved = repin_differences(previous, pinned_parts)
            if moved:
                print(
                    f"partspec: --pin rewrote claims the previous {args.pin} already covered:",
                    file=sys.stderr,
                )
                for line in moved:
                    print(f"    {line}", file=sys.stderr)
                print(
                    f"  hint: the lock's diff is the whole record of this change "
                    f"— review it as you would the contract edit itself "
                    f"(docs/AGENT-CONTRACT.md §4). `git diff {args.pin}` shows it; "
                    f"`git checkout {args.pin}` undoes it",
                    file=sys.stderr,
                )

    if batch and not args.quiet:
        # Tallied before the coverage check joins `codes`: the synthetic
        # uncovered-pin error is not a part, and "3 parts" on a 2-target
        # invocation is a false count (PR #105 re-review, N1).
        tally: dict[str, int] = {}
        for code in codes:
            word = _EXIT_WORD.get(code, str(code))
            tally[word] = tally.get(word, 0) + 1
        summary = ", ".join(f"{n} {word}" for word, n in tally.items())
        print(f"BATCH: {len(codes)} parts — {summary}")

    if expect_lock is not None:
        # The pin must be covered, not merely consulted: dropping a pinned
        # part's target from the invocation is "delete the check" at part
        # granularity, and it read green until PR #105's review demonstrated
        # it. No report exists for a part no target produced, so this is the
        # one expectation failure that lives on stderr and in the exit alone.
        uncovered = sorted(expect_lock.keys() - covered_ids)
        if uncovered:
            names = ", ".join(repr(p) for p in uncovered)
            it = "it" if len(uncovered) == 1 else "them"
            # A target resolves to at most one part, so N failures can
            # account for at most N uncovered ids. Everything beyond that is
            # PROVABLY deleted, whatever crashed — and blanket-declining there
            # installs the mirror of #201's defect: a guard refusing a
            # conclusion it has earned, suppressing the correct remedy for
            # parts the failure cannot explain (adversarial review of #243).
            # `len(unresolved)`, not `len(set(...))`. The bound is "one target
            # accounts for at most one part", so deduping the TARGET STRINGS
            # breaks it: the same spec twice, with a factory that is not pure
            # (which SPEC-contract nowhere forbids), is two targets and two
            # possible parts. Dedupe is for the display list only (round-3
            # review of #243).
            certain = len(uncovered) - len(unresolved)
            if unresolved and certain <= 0:
                # Nothing is provable: the failures could account for all of
                # them. Name the failures and decline.
                failed = ", ".join(repr(s) for s in sorted(set(unresolved)))
                those = "those failures" if len(set(unresolved)) > 1 else "that failure"
                sets = "that claim set" if len(uncovered) == 1 else "those claim sets"
                print(
                    f"partspec: the pin covers {names} and nothing in this invocation "
                    f"produced {it} — but {failed} did not resolve, so this may be "
                    f"{those} rather than a deletion",
                    file=sys.stderr,
                )
                print(
                    f"  hint: fix the target and re-run before deciding. Re-pinning "
                    f"now would write a lock without {names} — partspec refuses that "
                    f"while a target is unresolved, and {sets} would otherwise be gone",
                    file=sys.stderr,
                )
            elif unresolved:
                # Some are provable. Say how many, and keep the real remedy for
                # them rather than withholding it because something else broke.
                failed = ", ".join(repr(s) for s in sorted(set(unresolved)))
                print(
                    f"partspec: the pin covers {names} and nothing in this invocation "
                    f"produced {it}. {failed} did not resolve and can account for at "
                    f"most {len(unresolved)} of them, so at least {certain} "
                    f"{'was' if certain == 1 else 'were'} deleted",
                    file=sys.stderr,
                )
                print(
                    "  hint: fix the failing target first — re-pinning now would write "
                    "a lock without any of them, and only the deleted ones should go. "
                    "partspec refuses that write while a target is unresolved",
                    file=sys.stderr,
                )
            else:
                print(
                    f"partspec: the pin covers {names} but no "
                    f"target in this invocation produced "
                    f"{it}; a deleted part is a deleted "
                    f"claim set (re-pin with --pin if the removal is deliberate)",
                    file=sys.stderr,
                )
            codes.append(exit_code(Verdict.ERROR))

    return _batch_exit(codes)


def _warn_uncovered_before_building(
    targets: list[str], expect_lock: dict[str, dict[str, str]], *, quiet: bool
) -> None:
    """Say, before the first build, that this invocation cannot cover its pin.

    The authoritative check is after the loop and stays there. This one exists
    because the answer is knowable at the start and was being delivered at the
    end: a `check a b c --expect lock.json` whose lock also covers a deleted
    `d` builds every surviving target first — 56 to 108 s each on the OCCT tier
    — and only then says the invocation could never have covered its pin. A
    human who is told at second one can abort; the exit code, the reports and
    the verdict are unchanged for one who does not (#202).

    **Coverage needs the RESOLVED set, and resolution is engine-free**, which
    is the whole reason this is affordable: a mismatch run measures 0.095 s
    against a build measured in minutes. What it costs is running the contract
    factory twice, and `SPEC-contract.md` nowhere requires a factory to be
    pure — so this takes nothing from the second resolve, holds no `Part`, and
    lets the loop's own resolve be the one that counts.

    **Silent whenever anything is uncertain.** A target that fails to resolve
    here is not reported here: the post-loop check knows how to weigh a
    failure against a missing part (#201, #243) and this does not, so any
    failure abandons the preview entirely rather than guessing. Which also
    means this cannot contradict the authoritative answer — it declines
    instead.

    **Silent under `--quiet`**, which the authoritative check is not. The whole
    purpose here is "you can stop this now", and that is meaningless to a
    non-interactive caller; the failure itself still reaches CI, once, from the
    place that owns the exit code. Doubling a diagnosis nobody can act on is
    noise, and noise on stderr is how a real one gets missed.

    Model modules are evicted between resolutions, because a contract's
    sibling import cached from one target must not answer for the next
    (#114, #101). That is the same sequence `_check_one` already uses.
    """
    from .engines.pycad import invalidate_model_modules

    ids: set[str] = set()
    for spec in targets:
        try:
            part, target = resolve(spec)
        except BaseException:  # noqa: BLE001 - a contract may raise anything
            # The failed resolve may have cached sibling imports before
            # raising, and they must not answer for the loop that follows.
            with contextlib.suppress(TargetError):
                invalidate_model_modules(Target.parse(spec).path)
            return
        ids.add(part.id)
        # `_invalidate_after`'s sequence, for the same reason it exists: only
        # the id is wanted here, so the `Part` is dropped and the per-target
        # eviction the build loop relies on is left exactly as it was.
        _invalidate_after(part, target)

    uncovered = sorted(expect_lock.keys() - ids)
    if not uncovered or quiet:
        return
    names = ", ".join(repr(p) for p in uncovered)
    print(
        f"partspec: the pin covers {names}, which no target in this invocation "
        f"resolves to — the targets given are checked anyway, and this is reported "
        f"again at the end",
        file=sys.stderr,
    )


def _check_one(
    spec: str,
    args: argparse.Namespace,
    argv: list[str],
    timeout_s: float,
    *,
    batch: bool,
    expect_lock: dict[str, dict[str, str]] | None = None,
    pins: dict[str, dict[str, str]] | None = None,
    covered_ids: set[str] | None = None,
    unresolved: list[str] | None = None,
    previous_pin: dict[str, dict[str, str]] | None = None,
) -> int:
    # Before the contract is resolved, because resolving it IMPORTS it: a
    # contract's own imports are this part's, and a snapshot taken any later
    # would report them as inherited. Names only — `sys.modules` keys cost
    # nothing here, and an OpenSCAD target never turns them into an inventory
    # (SPEC-report §8.3 rule 7).
    loaded_before = frozenset(sys.modules)

    # The placeholder is already on disk — written by `_cmd_check` for every
    # target before any ran — so a resolution failure here (a contract that
    # raises on import, a typo in a keyword argument) leaves an artifact
    # saying the run died, never the previous run's `verdict: "pass"`.
    out = _out_dir_for(spec, args.out, batch=batch)

    resolved = _resolve_or_report(spec)
    if isinstance(resolved, int):
        # The failed resolve may have cached sibling imports before raising;
        # they must not answer for a later run in this directory (#114).
        from .engines.pycad import invalidate_model_modules

        invalidate_model_modules(Target.parse(spec).path)
        if unresolved is not None:
            # Recorded here rather than inferred from the exit code, which
            # cannot tell a resolution failure from a failing check (#201).
            unresolved.append(spec)
        return resolved
    part, target = resolved

    expected_claims: dict[str, str] | None = None
    if expect_lock is not None:
        # An absent part entry passes an empty pin down: the pin does not
        # vouch for any of these claims, and every one reports as unpinned.
        expected_claims = expect_lock.get(part.id, {})
    if covered_ids is not None:
        covered_ids.add(part.id)
    repinned: list[str] | None = None
    if pins is not None and args.pin is not None:
        from .expectation import claims_of, compare

        declared = claims_of(part)
        pins[part.id] = declared
        if previous_pin is not None and part.id in previous_pin:
            # A part the lock did not cover is a FIRST pin, not an overwrite,
            # and reporting each of its claims as `added` is how the loud case
            # stops being read — the same exclusion `repin_differences` makes
            # for the stderr half. `compare()` and not `repin_differences()`
            # because this report speaks for one part: the part-id prefix and
            # the dropped-part lines belong to the run, which is stderr's.
            repinned = compare(previous_pin[part.id], declared) or None

    try:
        return _check_resolved(
            spec,
            args,
            argv,
            timeout_s,
            part,
            target,
            out,
            expected_claims,
            loaded_before,
            batch=batch,
            repinned=repinned,
        )
    finally:
        # Every exit path evicts — an early `--render` refusal (the
        # engine-tier one, "requires an OpenSCAD source", not the batch
        # refusal #189 removed) used to return with the sibling record cached
        # but not evicted (#114).
        _invalidate_after(part, target)


def _check_resolved(
    spec: str,
    args: argparse.Namespace,
    argv: list[str],
    timeout_s: float,
    part: Part,
    target: Target,
    out: Path,
    expected_claims: dict[str, str] | None,
    loaded_before: frozenset[str],
    *,
    batch: bool,
    repinned: list[str] | None = None,
) -> int:
    built: list[object] = []
    report = run(
        part,
        out_dir=out,
        argv=argv,
        contract_path=target.path,
        factory=target.factory,
        timeout_s=timeout_s,
        expected_claims=expected_claims,
        repinned_claims=repinned,
        artifact_out=built,
        loaded_before=loaded_before,
    )

    render_error = None
    # Renders depict the run's OWN successful build, or nothing (PR #133
    # review, F1/F2): the old `report.error is None` gate let a failing
    # build be rebuilt just for pictures, and a parameter-blocked run —
    # whose report says the build was never evaluated — build anyway and
    # ship images of it. `builds` passing is the one signal that is true
    # on both tiers.
    built_ok = any(c.kind == "builds" and c.status is Status.PASS for c in report.checks)
    if args.render and report.error is None and built_ok:
        result = _render_files(part, out, timeout_s, prebuilt=built[0] if built else None)
        if isinstance(result, BuildError):
            render_error = result
        else:
            views, meta = result
            # Relative to the report's own directory, POSIX-separated — the
            # same portability rule part.source follows (SPEC-report.md §8).
            report.renders = {v: p.relative_to(out).as_posix() for v, p in views.items()}
            report.render_bbox = cast("dict | None", meta.get("render_bbox"))
            report.render_tessellation = cast("dict | None", meta.get("render_tessellation"))

    path = report.write(out)

    if not args.quiet:
        _summarise(report, path)
    if render_error is not None:
        # The report speaks for the part; this exit speaks for the run. A
        # requested render that failed must not exit as if it were delivered,
        # and the report carries no renders block — absence, not a lie.
        #
        # Named in a batch, because this message stopped being unambiguous the
        # moment `--render` accepted N targets: "cannot tessellate" against
        # four parts and one exit code says nothing about which one (#189).
        where = f"{spec}: " if batch else ""
        print(f"partspec: {where}{render_error.message}", file=sys.stderr)
        if render_error.hint:
            print(f"  hint: {render_error.hint}", file=sys.stderr)
        return exit_code(Verdict.ERROR)
    return report.exit_code


def _invalidate_after(part: Part, target: Target) -> None:
    """Evict what this run's resolve and build cached — the contract's
    sibling imports for every engine, the model's for the Python tiers —
    after the artifact is final (#29; PR #112 review for the contract half).
    A stale module served to the NEXT run is the failure class."""
    from .engines.pycad import invalidate_model_modules

    invalidate_model_modules(target.path)
    if part.source.engine != "openscad":
        invalidate_model_modules(part.source.path)


def _cmd_measure(args: argparse.Namespace) -> int:
    """The adoption path: measure first, then decide which numbers are *intent*.

    Emits nothing that would be unsupported, and produces no verdict. partspec
    deliberately does not auto-generate checks from this — a check the tool wrote
    is a check nobody decided.
    """
    try:
        timeout_s = _timeout_s(args.timeout)
    except _TimeoutUsage as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    resolved = _resolve_or_report(args.target)
    if isinstance(resolved, int):
        from .engines.pycad import invalidate_model_modules

        invalidate_model_modules(Target.parse(args.target).path)
        return resolved
    part, target = resolved

    try:
        return _measure_resolved(args, part, target, timeout_s)
    finally:
        _invalidate_after(part, target)


def _measure_failure(
    part: Part, target: Target, backend: Any, message: str, hint: str | None
) -> None:
    """Emit `measure`'s failure artifact: the identity prefix, then the reason.

    The failure is an artifact too (#47): a caller parsing stdout used to get
    an empty string and a bare exit code, with the reason living only on
    stderr — machine-invisible exactly where a machine is the audience. Same
    identity prefix as the success payload, so the consumer can tell WHICH
    file and revision failed to measure.

    Every build outcome and every `--out` refusal comes through here, which is
    what SPEC-report.md's Scope requires ("On any failure after the target
    resolves, both MUST emit a JSON object carrying that identity plus
    `error`/`hint`") — the refusals exit 64 rather than 4 but are no less a
    thing a machine has to understand. The exit code stays the caller's to
    choose; this only says what happened.

    One post-resolution path still prints stderr alone: an unknown engine
    (`_backend_for` raising `ContractError`), which cannot reach here because
    it has no backend to describe one with, and which the contract layer makes
    unreachable anyway.
    """
    from .report import SCHEMA_VERSION
    from .runner import engine_block, identity

    failed: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "payload": "measure",
        "tool": {"name": "partspec", "version": tool_version()},
        "part": identity(part, target.path, factory=target.factory),
        "engine": engine_block(part, backend),
        "params": dict(part.source.params),
        # Empty rather than absent, mirroring the report's failure shape:
        # the spec's identity-prefix claim stays exact on both verbs.
        "geometry": {},
        "error": message,
        "hint": hint,
    }
    print(json.dumps(failed, indent=2, allow_nan=False))
    print(f"partspec: {message}", file=sys.stderr)
    if hint:
        print(f"  hint: {hint}", file=sys.stderr)


def _measure_resolved(
    args: argparse.Namespace, part: Part, target: Target, timeout_s: float
) -> int:
    from .backend import Unsupported
    from .report import SCHEMA_VERSION
    from .runner import _backend_for, _engine_source, engine_block, identity

    try:
        backend = _backend_for(part.source.engine)
        engine_deps: list[Any] = []
        engine_unresolved: list[str] = []
    except ContractError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    source = _engine_source(part)
    if args.out is not None and _names_the_artifact(args.out):
        dest = Path(args.out)
        if part.source.engine != "openscad":
            # Refused, not warned: the caller asked for a file this tier
            # cannot produce, and exiting 0 with nothing at that path is the
            # silent success this tool exists to refuse (#187).
            #
            # The hint no longer offers "pass a directory". It appeared to work
            # while a directory was silently accepted; #204 makes that same
            # request state that nothing was written, so following the old
            # advice now lands the reader in the state one line of output
            # complains about. `drop --out` is the whole remedy on this tier.
            #
            # It names no path of any shape, rather than naming a directory to
            # disclaim it. Two reasons, both learned here. A disclaimed remedy
            # still reads as a remedy to someone skimming for a path. And the
            # earlier phrasing said nothing is written "to it", which
            # presupposes the directory exists — it is never created, which is
            # the #204 myth this very PR spent six CHANGELOG lines refuting.
            _measure_failure(
                part,
                target,
                backend,
                f"--out {dest} names a file, but the {part.source.engine} tier builds "
                f"in memory and exports nothing to write there",
                REFUSED_OUT_HINT,
            )
            return EXIT_USAGE
        from .engines.openscad import include_closure

        # `.stl` is an INPUT extension too — `import()` reads one — so a
        # destination that looks like this run's output may be one of its
        # inputs. Writing the artifact over an input changes what the NEXT run
        # measures, so this is refused rather than guessed at, and the refusal
        # says which two files it cannot tell apart.
        #
        # The question asked is the UNRESOLVED-include arm alone, not the whole
        # of `partial`. A closure that cannot see inside a file cannot know
        # whether that file imports data either, and nothing later will tell it
        # — the depfile names what the render opened, never what it asked for —
        # so this is the case where refusing before the render is the only
        # honest answer available. The other arm, `reads_external_data`, is now
        # answered exactly after the render by `_build_to_file`, which knows
        # which files were read instead of guessing that any of them might be
        # `dest` (#263). Phrased in one place because `openscad.render` refuses
        # on the same grounds (#208).
        closure = include_closure(source.path)
        reason = closure.unresolved_reason
        if reason is not None:
            _measure_failure(
                part,
                target,
                backend,
                f"--out {dest} names a file, but {source.path.name} {reason}, so partspec "
                f"cannot account for every input and cannot prove {dest.name} is not one "
                f"of them",
                # "other than the model's own". The bare "pass a directory"
                # always worked until #223 gave the DIRECTORY form its own
                # refusal on the same grounds — so following this hint with the
                # obvious directory (`.`) landed the reader in a second refusal,
                # at a different exit code, with a different message. A remedy
                # that routes into another refusal is an answer that does
                # nothing reading as an answer (v0.7.6 pre-tag audit).
                f"pass a directory other than the model's own "
                f"({source.path.parent}) — the artifact lands in it as "
                f"{source.path.stem}{ARTIFACT_SUFFIX}",
            )
            return EXIT_USAGE
        dest_refusal: list[BuildError] = []
        artifact = _build_to_file(
            backend,
            source,
            dest,
            timeout_s,
            engine_deps,
            closure=closure,
            refusal_out=dest_refusal,
            unresolved_out=engine_unresolved,
        )
        if dest_refusal:
            _measure_failure(part, target, backend, dest_refusal[0].message, dest_refusal[0].hint)
            return EXIT_USAGE
        written_to = dest
        build_dir = dest.parent
    else:
        out = _out_dir(args.target, Path(args.out) if args.out is not None else None)
        build_dir = out
        artifact = backend.build(
            source,
            out,
            timeout_s=timeout_s,
            deps_out=engine_deps,
            unresolved_out=engine_unresolved,
        )
        # The name inside the directory is partspec's, not the caller's, which
        # is the whole of #225: the caller chose `out` and cannot know the rest
        # without re-deriving a rule this tool owns and has already changed once
        # (#187). Spelled from `ARTIFACT_SUFFIX` for the same reason the
        # filename refusal above is, and pinned against a real build rather
        # than asserted, so the payload cannot promise a path nothing wrote.
        written_to = (
            out / f"{source.path.stem}{ARTIFACT_SUFFIX}"
            if part.source.engine == "openscad"
            else None
        )
    if engine_unresolved and not isinstance(artifact, BuildError):
        # `measure` is the surface an author turns into a contract, so a number
        # taken off a part the engine hollowed out does not merely mislead this
        # run -- it gets written down as a claim and passes forever after. The
        # quantities are real; they are measurements of something other than
        # the source. `measure` promises every quantity the backend can
        # HONESTLY produce, and these do not qualify (#286). The `--out FILE`
        # form has already refused inside `_build_to_file`, before its rename.
        artifact = _hollowed_measurements(engine_unresolved[0])
    elif engine_deps and not isinstance(artifact, BuildError):
        # The same hazard through the other channel (#309, #355). A file the
        # engine asked for and could not open leaves no stderr marker at all --
        # `import()` of an absent target renders as nothing -- so `unresolved`
        # above is empty and the mesh is well-formed. `check` refuses this at
        # exit 4; `measure` reported a number off a part that is missing a piece,
        # and an agent writes that number into a contract that passes forever.
        #
        # Reached only by the directory form: the `--out FILE` form has already
        # refused inside `_build_to_file`, before its rename, because a refusal
        # there must leave the caller's file untouched.
        from .runner import absent_build_inputs

        absent = absent_build_inputs(source, engine_deps[-1], build_dir, timeout_s, source.path)
        if absent:
            artifact = _absent_input_refusal(absent)
    if isinstance(artifact, BuildError):
        _measure_failure(part, target, backend, artifact.message, artifact.hint)
        return exit_code(Verdict.ERROR)

    measurements: dict[str, object] = {}
    refused: dict[str, str] = {}
    # Which of the two things `refused` conflates happened, per name. The block
    # carries both "the part defeated this measurement" and "partspec could not
    # perform it", and until #371 the only discriminator was the English in the
    # reason -- so an agent had to string-match to tell a defect in the part from
    # a defect in this tool. A separate block rather than widening `refused`'s
    # value: adding a field is non-breaking (SPEC-report 7.1), changing
    # `dict[str, str]` to `dict[str, object]` is not.
    refused_by: dict[str, str] = {}
    unavailable: list[str] = []

    # `is_valid` and `topology_counts` are here but are not check kinds — the
    # first because its meaning differs by tier, the second because it is
    # answerable on only one. Both are useful to *see* while writing a contract,
    # which is what this verb is for.
    for name in (
        "bbox",
        "volume",
        "area",
        "center_of_mass",
        "is_valid",
        "watertight",
        "self_intersection_free",
        "min_wall",
        "solid_count",
        "cavities",
        "genus",
        "topology_counts",
        "bores",
        "blend_radii",
    ):
        if name not in backend.capabilities():
            unavailable.append(name)
            continue
        try:
            result = getattr(backend, name)(artifact)
        except ContractError as exc:
            # A backend that constructs an impossible `Measurement` -- a
            # non-finite value, an approximate one without bounds -- raises, and
            # before #365 that raise escaped this loop and ended the run: one
            # name aborted the verb and emitted NOTHING, `area` and `bbox`
            # included, on a part whose other thirteen quantities were perfectly
            # well defined. The backend is where such an inability belongs
            # (AGENTS.md: return `Unsupported`, never a plausible-looking
            # number), and the mesh tier's own case is fixed there; this is the
            # bound on what the next one can cost, which is one name.
            #
            # `refused`, not `unavailable`: SPEC-report.md 7.3 makes
            # `unavailable` a property of the TIER -- "the same list every time
            # that backend measures anything" -- and this name is one the tier
            # answers for other parts. What defeated it arrived with this
            # artifact, which is what `refused` is for.
            refused[name] = f"the {backend.kind} backend could not measure {name} here: {exc}"
            refused_by[name] = "tool"
            continue
        if isinstance(result, Unsupported):
            refused[name] = result.reason
            refused_by[name] = "part"
            continue
        entry: dict[str, object] = {
            "value": list(result.value) if result.is_vector else result.value,
            "unit": result.unit,
            "exactness": "exact" if result.exact else "approximate",
        }
        if result.bounds is not None:
            # The interval is the honesty (PR #144 review, F6): an
            # approximate value without its bounds reads more certain than
            # it is, in the verb whose job is showing the numbers.
            entry["bounds"] = list(result.bounds)
        if result.axes is not None:
            # Presence, not truthiness: a measurement is vector iff `value` is
            # an array (status.py), so an empty array is a vector and SPEC-report
            # 2.1 makes `axes` REQUIRED on it. Truthiness dropped the field on
            # exactly the parts that are simplest -- a part with no bores (#346).
            entry["axes"] = list(result.axes)
        measurements[name] = entry

    measured: dict[str, object] = {
        # The identity prefix mirrors the report's field order exactly
        # (schema_version, payload, tool, part, engine, params, geometry), so a
        # consumer of one artifact can orient in the other — and `payload` is
        # what tells the two apart once it has (#295). `built=True`:
        # a Python model's imports are only knowable once it has run.
        "schema_version": SCHEMA_VERSION,
        "payload": "measure",
        "tool": {"name": "partspec", "version": tool_version()},
        "part": identity(
            part,
            target.path,
            factory=target.factory,
            built=True,
            engine_deps=engine_deps[0] if engine_deps else None,
        ),
        "engine": engine_block(part, backend),
        "params": dict(part.source.params),
        "geometry": backend.provenance(artifact),
        "measurements": measurements,
    }
    # Two different silences, separated because conflating them is a bug this
    # verb once had. `unavailable` is a property of the tier and the same for
    # every part it measures; `refused` is a property of *this* part, and its
    # reason names the defect. Before D17 only the first kind existed and
    # dropping it was honest. Now an open mesh drops `volume`, `genus` and
    # `center_of_mass`, and a reader writing their first contract from this
    # output would see no volume and decline to claim one — the omission
    # teaching exactly the wrong lesson, in the verb that exists for adoption.
    if refused:
        measured["refused"] = refused
        # Emitted with `refused` and keyed identically, so a consumer never has to
        # ask whether a name is present in one and not the other.
        measured["refused_by"] = refused_by
    if unavailable:
        measured["unavailable"] = unavailable

    # An unfulfillable `--out` is an entry, never an absence (#204). The
    # filename form of this same request exits 64 and says why; the directory
    # form accepted the path, wrote nothing and exited 0 in silence — two
    # spellings of "put the artifact here" on a tier that has no artifact, one
    # named and one not. The exit stays 0 because the MEASUREMENT succeeded and
    # is this verb's product: discarding it over an unfulfillable side-request
    # costs the caller more than the no-op flag does. The filename form keeps
    # its 64, because there the caller named a path they will go looking for.
    #
    # In BOTH channels. Stderr is for the human, and the payload for the
    # machine, because `measure`'s whole design principle is that a fact living
    # only on stderr is machine-invisible exactly where a machine is the
    # audience (#47). One `reason` string feeds both, so the two cannot drift.
    #
    # Only when `--out` was passed: nothing was asked for otherwise, and there
    # is nothing to report. `check --out` is untouched — it writes `report.json`
    # into that directory on every tier, so the flag is no no-op there.
    # Additive key, so `SCHEMA_VERSION` does not move.
    reason = (
        f"the {part.source.engine} tier builds in memory and exports nothing to put there"
        if args.out is not None and part.source.engine != "openscad"
        else None
    )
    if args.out is not None:
        # `written` states the outcome as a value rather than leaving it to be
        # inferred from the key's presence — which is what made the true case
        # cost nothing to add (#225): the key means "what happened to your
        # --out", not "your --out could not be honoured", and the narrower
        # reading was only ever an artefact of `false` being the first case
        # shipped. A consumer still reads one field.
        measured["artifact"] = (
            {"requested": args.out, "written": False, "reason": reason}
            if reason is not None
            else {"requested": args.out, "written": True, "path": str(written_to)}
        )

    print(json.dumps(measured, indent=2, allow_nan=False))
    if reason is not None:
        print(
            f"partspec: --out {args.out} names a directory for the build artifact, but {reason}",
            file=sys.stderr,
        )
        print(
            f"  hint: nothing was created at {args.out}; the measurements on stdout are "
            f"this verb's whole product, and only the OpenSCAD tier also writes an artifact",
            file=sys.stderr,
        )
    tool_faults = sorted(n for n, by in refused_by.items() if by == "tool")
    if tool_faults:
        # `measure` decides nothing about the part, and this does not decide
        # anything about the part either -- it says partspec failed to do its job
        # for these names. Exit 0 asserted the run was fine, in a block whose
        # other entries mean "the part defeated this measurement", so a tool fault
        # read as a statement about the part (#371). Exit 4 is the code this verb
        # already returns when it could not measure what it was given.
        #
        # The payload is still printed, in full, above. #369's gain -- one raising
        # backend costs one name and not the other thirteen -- is a property of
        # the OUTPUT, and is untouched: the numbers are there, and the exit code
        # says one of them is missing for partspec's own reason.
        print(
            f"partspec: this tool could not measure {', '.join(tool_faults)} "
            f"and the failure is partspec's, not the part's",
            file=sys.stderr,
        )
        print(
            "  hint: read `refused_by` in the payload; the other measurements stand",
            file=sys.stderr,
        )
        return exit_code(Verdict.ERROR)
    return 0


def _cmd_lint(args: argparse.Namespace) -> int:
    """Source lint (#26, #118): advisory, machine-readable, never a verdict.

    Tier 1 is engine-free; tier 2 reads the engine's `.csg` export and
    reports `unsupported` by name when it cannot run. Both surfaces carry
    that -- the payload per file, and the courtesy stream one line per
    distinct cause (#288).

    Exit 0 says the lint RAN; the findings are data in the payload — an
    advisory that failed the process would be a verdict the source never
    earned (the issue's bullet 3, verbatim: "advisory and never a verdict on
    the part"). 64 is reserved for inputs that cannot be linted at all.
    """
    import hashlib

    from .lint import LINT_SCHEMA_VERSION, LintError, lint_path

    # Deduped on the resolved path, order kept: the same file twice is one
    # file, not doubled counts (#120).
    unique: list[Path] = []
    seen: set[Path] = set()
    for source in args.sources:
        resolved = source.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(source)

    from .engines.openscad import find_executable
    from .lint import lint_scad_tier2

    scad_engine = find_executable()
    files = []
    courtesy: list[str] = []
    # Grouped by REASON rather than one line per entry. With no engine every
    # `.scad` refuses every tier-2 rule for the same cause, so per-entry lines
    # would put three identical sentences per file on the console -- 75 of them
    # over this repo's 25 sources -- and a courtesy stream nobody reads is the
    # same silence it exists to break. One line per distinct cause names the
    # rules and the files, the latter bounded the way `diff` bounds its own
    # name lists (#288).
    refused: dict[str, tuple[list[str], set[str]]] = {}
    try:
        for source in unique:
            findings = lint_path(source)
            entry: dict[str, object] = {
                # Identity per file (#120, the #47 pattern): which bytes
                # produced these findings — a clean file is a visible
                # entry with a digest, not an absence.
                "file": str(source),
                "digest": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
                "findings": [f.to_json() for f in findings],
            }
            if source.suffix == ".scad":
                tier2, unsupported = lint_scad_tier2(source, scad_engine)
                findings = [*findings, *tier2]
                entry["findings"] = [f.to_json() for f in findings]
                if unsupported:
                    # Refusals are entries, never absences (#118): a rule
                    # that could not run must not read as a clean bill.
                    entry["unsupported"] = unsupported
                    for u in unsupported:
                        refused.setdefault(u["reason"], ([], set()))
                        seen_files, rules = refused[u["reason"]]
                        if str(source) not in seen_files:
                            seen_files.append(str(source))
                        rules.add(u["rule"])
            courtesy.extend(f"  {f.rule}  {f.file}:{f.line}  {f.message}" for f in findings)
            files.append(entry)
    except LintError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    total = sum(len(f["findings"]) for f in files)
    # Counted per (file, rule), matching what `unsupported[]` holds, so the
    # tally and the blocks cannot disagree. Additive key: a consumer reading
    # `findings` alone is unaffected, and `LINT_SCHEMA_VERSION` does not move
    # -- the same rule `--out`'s `written` followed (#225).
    unsupported_total = sum(len(f.get("unsupported", ())) for f in files)
    payload = {
        "schema_version": LINT_SCHEMA_VERSION,
        "payload": "lint",
        "tool": {"name": "partspec-lint", "version": tool_version()},
        "files": files,
        "counts": {
            "files": len(files),
            "findings": total,
            "unsupported": unsupported_total,
        },
    }
    print(json.dumps(payload, indent=2, allow_nan=False))
    for line in courtesy:
        print(line, file=sys.stderr)
    # Names the files, bounded — `diff`'s `_bounded` rule (SPEC-diff.md 1),
    # because a bare count tells a reader something was skipped and gives them
    # no way to find out which. Live on this repo: with an engine present, four
    # of its own sources refuse for string content.
    #
    # `diff`'s constant, imported rather than repeated: LINT.md and the
    # CHANGELOG both say this line follows `diff`'s rule, and a second copy of
    # the number would let that go false silently.
    from .diff import _SUMMARY_NAME_LIMIT

    for reason, (where, rules) in refused.items():
        shown = ", ".join(where[:_SUMMARY_NAME_LIMIT]) + (
            f", +{len(where) - _SUMMARY_NAME_LIMIT} more"
            if len(where) > _SUMMARY_NAME_LIMIT
            else ""
        )
        print(f"  {', '.join(sorted(rules))}  {shown}  not run: {reason}", file=sys.stderr)
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    """Evidence, not judgement: images the report can reference (#20), framed
    deterministically from the bounding box so iterations are comparable. No
    verdict rides with them — rendering never substitutes for measurement."""
    try:
        timeout_s = _timeout_s(args.timeout)
    except _TimeoutUsage as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    section = None
    if args.section is not None:
        section = _parse_section(args.section)
        if section is None:
            # Usage, before any work: the ask itself is malformed.
            print(
                f"partspec: --section takes xy, xz or yz with an optional "
                f":offset in mm, got {args.section!r}",
                file=sys.stderr,
            )
            return EXIT_USAGE

    # Before resolution (PR #131 review, F4): a failed resolve exits 64
    # with no artifact, and the previous run's render.json must not sit
    # there answering a later vdiff as if it were this run's. The images
    # without it are unreachable through the vdiff loader. An unparseable
    # target is the resolve path's message to give, hence the suppress.
    with contextlib.suppress(TargetError, OSError):
        (_out_dir(args.target, args.out) / "render.json").unlink(missing_ok=True)

    resolved = _resolve_or_report(args.target)
    if isinstance(resolved, int):
        from .engines.pycad import invalidate_model_modules

        invalidate_model_modules(Target.parse(args.target).path)
        return resolved
    part, target = resolved

    try:
        return _render_resolved(args, part, target, timeout_s, section)
    finally:
        # The render verb resolves contracts too; it leaked its sibling
        # records on every exit path until PR #124's review demonstrated it.
        _invalidate_after(part, target)


def _parse_section(text: str) -> tuple[str, float | None] | None:
    """`xy` | `xy:5.5` → (plane, offset); None when it is not a section ask."""
    plane, sep, tail = text.partition(":")
    if plane not in ("xy", "xz", "yz"):
        return None
    if not sep:
        return plane, None
    try:
        offset = float(tail)
    except ValueError:
        return None
    if not math.isfinite(offset):
        return None
    return plane, offset


_AXIS_NAMES = ("x", "y", "z")


def _render_files(
    part: Part,
    out: Path,
    timeout_s: float,
    section: tuple[str, float | None] | None = None,
    prebuilt: Any | None = None,
    deps_out: list[Any] | None = None,
) -> tuple[dict[str, Path], dict[str, object]] | BuildError:
    """The view files for either tier — one dispatcher, so the `render` verb
    and `check --render` cannot drift apart (#18).

    OpenSCAD parts render through the engine's own viewer; OCCT-tier parts
    build through the same backend `check`/`measure` use and are rasterized
    from the tessellation (`raster.py`) — headless, deterministic, no GPU.
    A section (#19) is cut by the kernel that owns the geometry — OpenSCAD
    subtracts a half-space from its exported STL, the OCCT tier booleans the
    shape — and both are rasterized by the same code, cut faces distinct.
    Returns (views, meta) where meta carries `render_bbox` always and
    `render_tessellation` / `section` when they apply, in payload order.
    Raises `ContractError` when the engine has no backend, as `measure` would.
    """
    from .runner import _backend_for, _engine_source

    if part.source.engine == "openscad":
        from .engines import openscad

        views = openscad.render_views(
            _engine_source(part), out, timeout_s=effective_timeout(timeout_s), deps_out=deps_out
        )
        if isinstance(views, BuildError):
            return views
        # The framing bbox rides with every render (#21): framing scales with
        # the part, so two sizes render identical pixels and the bbox is the
        # only witness. The STL is render_views's own export.
        from .backend import bbox_block

        stl = out / f"{_engine_source(part).path.stem}.stl"
        bbox = openscad._stl_bbox(stl)
        meta: dict[str, object] = {"render_bbox": bbox_block(*bbox)}
        if section is None:
            return views, meta
        plane, offset = section
        # The stale-artifact rule, hoisted (PR #130 review, F1): every
        # refusal below returns before the rasterizer's own unlink, and a
        # failing section must not leave the previous run's image to be
        # read as this run's.
        (out / "renders" / f"section_{plane}.png").unlink(missing_ok=True)
        try:
            import numpy  # noqa: F401
        except ModuleNotFoundError:
            return BuildError(
                "the section rasterizer needs numpy, and this environment has none",
                origin="environment",
                hint=(
                    "any partspec engine extra brings it, e.g. " + install_hint("'partspec[mesh]'")
                ),
            )
        from . import raster

        axis = raster.SECTION_VIEWS[plane][1]
        resolved = _resolve_offset(offset, bbox[0][axis], bbox[1][axis], plane)
        if isinstance(resolved, BuildError):
            return resolved
        cut_stl = openscad.render_section_stl(
            stl, plane, resolved, bbox, out, timeout_s=effective_timeout(timeout_s)
        )
        if isinstance(cut_stl, BuildError):
            return cut_stl
        points, faces = raster.read_stl(cut_stl)
        frame_points, _ = raster.read_stl(stl)
        png, cut_n = raster.render_section(points, faces, plane, resolved, frame_points, out)
        views[f"section_{plane}"] = png
        meta["section"] = {"plane": plane, "offset_mm": resolved, "cut_triangles": cut_n}
        return views, meta

    backend = _backend_for(part.source.engine)
    # `check --render` hands over the artifact its run just built (#129):
    # rebuilding a model the process holds in memory doubled side effects
    # and let a nondeterministic model's renders silently disagree with the
    # geometry the report measured.
    artifact = (
        prebuilt
        if prebuilt is not None
        else backend.build(_engine_source(part), out, timeout_s=timeout_s)
    )
    if isinstance(artifact, BuildError):
        return artifact
    # Imported only after the build delivered a shape: raster pulls in numpy,
    # and with the occt extra missing that import would crash HERE — a raw
    # traceback shadowing the honest environment BuildError the build's
    # import classification exists to produce (PR #127 review, F1).
    from . import raster

    result = raster.render_views(artifact, out)
    if isinstance(result, BuildError):
        return result
    views, tessellation, render_bbox = result
    meta = {"render_bbox": render_bbox, "render_tessellation": tessellation}
    if section is None:
        return views, meta

    import numpy as np

    plane, offset = section
    # Same hoisted stale-artifact rule as the OpenSCAD branch (F1).
    (out / "renders" / f"section_{plane}.png").unlink(missing_ok=True)
    frame_points = np.array(
        [(v.X, v.Y, v.Z) for v in artifact.tessellate(raster.TESSELLATION_TOLERANCE_MM)[0]]
    )
    axis = raster.SECTION_VIEWS[plane][1]
    lo, hi = frame_points.min(axis=0), frame_points.max(axis=0)
    resolved = _resolve_offset(offset, float(lo[axis]), float(hi[axis]), plane)
    if isinstance(resolved, BuildError):
        return resolved

    import build123d as bd

    pad = float(max(*(hi - lo), 1.0))
    mins = [float(c) - pad for c in lo]
    maxs = [float(c) + pad for c in hi]
    if plane == "xz":
        maxs[axis] = resolved  # camera at -Y: discard y < offset
    else:
        mins[axis] = resolved  # camera at +Z / +X: discard above the plane
    sizes = [b - a for a, b in zip(mins, maxs, strict=True)]
    middle = tuple((a + b) / 2 for a, b in zip(mins, maxs, strict=True))
    cut_shape = artifact - bd.Location(middle) * bd.Box(sizes[0], sizes[1], sizes[2])
    try:
        vertices, faces = cut_shape.tessellate(raster.TESSELLATION_TOLERANCE_MM)
    except ValueError:
        vertices, faces = [], []
    if not faces:
        return BuildError(f"the {plane} section at {resolved:g} mm discards the whole part")
    points = np.array([(v.X, v.Y, v.Z) for v in vertices])
    png, cut_n = raster.render_section(points, faces, plane, resolved, frame_points, out)
    views[f"section_{plane}"] = png
    meta["section"] = {"plane": plane, "offset_mm": resolved, "cut_triangles": cut_n}
    return views, meta


def _resolve_offset(offset: float | None, lo: float, hi: float, plane: str) -> float | BuildError:
    """The section offset, resolved and range-checked — never left implicit.

    A plane outside the part would render the uncut part with zero cut faces:
    an image that *looks fine*, which is precisely the failure this project
    documents. Refused with the range instead."""
    from . import raster

    axis = raster.SECTION_VIEWS[plane][1]
    resolved = (lo + hi) / 2.0 if offset is None else offset
    if not (lo - 1e-9 <= resolved <= hi + 1e-9):
        return BuildError(
            f"the {plane} section at {resolved:g} mm misses the part "
            f"({_AXIS_NAMES[axis]} spans {lo:g} mm to {hi:g} mm)"
        )
    return resolved


def _render_resolved(
    args: argparse.Namespace,
    part: Part,
    target: Target,
    timeout_s: float,
    section: tuple[str, float | None] | None = None,
) -> int:
    from .report import SCHEMA_VERSION
    from .runner import _backend_for, engine_block, identity

    if part.source.engine == "openscad":
        from .engines import openscad

        # The section-7 subset that applies here: no measurement tier is
        # involved, so no `backend` key — but method/param_mode still decide
        # what was built, and their absence made a method= render ambiguous
        # (#73).
        engine: dict[str, object] = {
            "kind": "openscad",
            "version": openscad.version(),
            "render_backend": part.source.backend,
            "method": part.source.method,
            "param_mode": "call" if part.source.method else "define",
        }
    else:
        # The OCCT tier builds through its backend to render (#18), so the
        # full engine block is true here — `backend` names a tier that ran.
        try:
            backend = _backend_for(part.source.engine)
        except ContractError as exc:
            print(f"partspec: {exc}", file=sys.stderr)
            return EXIT_USAGE
        engine = engine_block(part, backend)

    # The identity prefix mirrors the report's field order (#103, the #47
    # pattern): render was the last verb whose payload named its part with a
    # bare id string — no digests, no closure — so its images could not be
    # tied to the revision that produced them. This `part` seeds the key
    # ORDER: both branches below replace it with `_identity()` once the build
    # has run, since a Python model's imports are only knowable then.
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "payload": "render",
        "tool": {"name": "partspec", "version": tool_version()},
        "part": identity(part, target.path, factory=target.factory),
        "engine": engine,
        "params": dict(part.source.params),
    }

    out = _out_dir(args.target, args.out)
    # The same stale-artifact rule as every render file: a failing run must
    # not leave the previous run's payload to be read as this run's (#21).
    (out / "render.json").unlink(missing_ok=True)
    render_deps: list[Any] = []
    result = _render_files(part, out, timeout_s, section, deps_out=render_deps)

    def _identity() -> dict[str, Any]:
        # `built=True`: a Python model's imports are only knowable once it has
        # run. On BOTH branches, because the STL renders before the views do:
        # a headless box fails at the image stage with the engine's account of
        # its inputs already in hand, and discarding it there made `render`'s
        # failure payload disagree with `check`'s report on a machine with no
        # display — which is the only kind CI has.
        return identity(
            part,
            target.path,
            factory=target.factory,
            built=True,
            engine_deps=render_deps[0] if render_deps else None,
        )

    if isinstance(result, BuildError):
        # The failure is an artifact too (#47): this path used to print to
        # stderr and return a bare 4 — machine-invisible exactly where a
        # machine is the audience. Empty rather than absent, mirroring
        # measure's failure shape: the identity prefix stays exact.
        payload["part"] = _identity()
        payload["renders"] = {}
        payload["error"] = result.message
        payload["hint"] = result.hint
        # And WHOSE fault it was. #191 asked for "the same origin discipline
        # every other engine-side failure gets", and this payload had no
        # `origin` at all — so a consumer could not tell a degenerate solid
        # from an OCCT library that would not load, which is the distinction
        # SPEC-report §6.1 exists to force. `check`'s report has carried it
        # since #47; `render`'s did not (adversarial review of #241).
        payload["origin"] = result.origin
        print(json.dumps(payload, indent=2, allow_nan=False))
        print(f"partspec: {result.message}", file=sys.stderr)
        if result.hint:
            print(f"  hint: {result.hint}", file=sys.stderr)
        return exit_code(Verdict.ERROR)

    views, meta = result
    payload["part"] = _identity()
    payload["renders"] = {view: str(path) for view, path in views.items()}
    payload.update(meta)
    # The payload, on disk beside the images (#21): stdout serves the
    # invoker, but a later `vdiff` needs the engine version and framing
    # bbox of a PAST run, and stdout is gone. Renders relativized to the
    # file's own directory, the report's portability rule (§8 rule 4).
    disk = dict(payload)
    disk["renders"] = {v: p.relative_to(out).as_posix() for v, p in views.items()}
    (out / "render.json").write_text(json.dumps(disk, indent=2, allow_nan=False) + "\n")
    print(json.dumps(payload, indent=2, allow_nan=False))
    return 0


_ICON = {
    Status.PASS: "ok  ",
    Status.FAIL: "FAIL",
    Status.APPROXIMATE: "~?  ",
    Status.UNSUPPORTED: "n/a ",
    Status.SKIPPED: "--  ",
}


def _refs_carried() -> str:
    """The standards `partspec.refs` actually carries, asked rather than typed.

    This advisory is the one place the tool tells an author where to get an
    attributed number, so a hardcoded list here goes stale the moment `refs`
    grows — and stale in the direction that matters, since the whole point is
    to route someone to a table they did not know existed. It said
    "iso15, nema17" for as long as those were the only two, and #194 made that
    false without a single test noticing.
    """
    from . import refs

    return ", ".join(sorted(refs.__all__))


def _summarise(report, path: Path) -> None:
    """A human summary on stderr. stdout stays clean for the report path.

    Deliberately terse: this is a courtesy, not the contract. Anything a
    consumer needs is in the JSON.
    """
    # One run-level fault is one fact about the run, not a fact about each
    # check. When the build fails for an environment reason, every declared
    # check is skipped carrying the SAME sentence as its detail, so a ten-check
    # contract printed an identical forty-word packaging diagnosis ten times
    # and `report.error` — the thing that actually happened — not once. The
    # detail stays in the artifact untouched, where a per-check consumer needs
    # it; only the console stops repeating itself.
    echoed = f"not evaluated: {report.error}" if report.error else None
    for check in report.checks:
        line = f"  {_ICON[check.status]} {check.id}"
        if check.detail and check.detail != echoed:
            line += f" — {check.detail}"
        print(line, file=sys.stderr)

    counts = report.counts()
    summary = ", ".join(f"{n} {name}" for name, n in counts.items() if name != "total" and n)
    print(f"\n{report.verdict.upper()}: {summary or 'no checks'}", file=sys.stderr)

    if echoed:
        # Said once, here, now that the per-check lines no longer say it. The
        # console never printed `report.error` at all before: on an
        # environment fault the only account of what happened was N copies of
        # it wearing a check's name.
        print(f"  {report.error}", file=sys.stderr)

    if report.hint:
        # `measure` and `render` have always printed their hint; `check` — the
        # verb people actually run — did not, so the one line saying what to DO
        # reached only `report.json`. A run with a hint is a run that proved
        # nothing about the part: the contract did not match its pin, the
        # contract raised, or the build failed. On the environment branch of
        # that last one the audience is necessarily a human at a terminal, and
        # the hint is the whole remedy — no machine repairs its own OCP
        # install. This does not make the console the contract (it is still a
        # courtesy, and the JSON is still ground truth); it stops the courtesy
        # from naming a problem and withholding its answer.
        print(f"  hint: {report.hint}", file=sys.stderr)

    if report.verdict is Verdict.EMPTY:
        print(
            f"  {report.part_id!r} declares no checks. That is an unasked question, "
            f"not a passing design.",
            file=sys.stderr,
        )

    attribution = report.attribution()
    if attribution["dimensional"] and not attribution["attributed"]:
        # The circular-contract warning (#50, SPEC-contract.md 6): a bound
        # recomputed from the model's own constants cannot fail however the
        # design moves, and nothing in a single green run distinguishes that
        # from a real proof. Attribution is the distinguisher, and its total
        # absence is worth one line — same channel as the empty-contract
        # warning, because both are a green that proved less than it looks.
        print(
            f"  every dimensional limit on {report.part_id!r} is unattributed: "
            f"bounds derived from the model's own numbers prove the model matches "
            f"itself — cite the source instead: partspec.refs for a standard it "
            f'carries ({_refs_carried()}), else partspec.Referenced(value, {{"standard": '
            f'..., "subject": ..., "field": ...}}) for anything it does not '
            f"(SPEC-contract.md 10)",
            file=sys.stderr,
        )
    print(f"  {path}", file=sys.stderr)


def _cmd_vdiff(args: argparse.Namespace) -> int:
    """What changed in the part's appearance (#21) — the pair of `diff`'s
    what-changed-in-the-claims. Same artifact-to-stdout, summary-to-stderr,
    outcome-to-exit-code shape."""
    from .vdiff import VdiffUsageError, diff_renders, exit_code_of, load_run, summary_of

    # Inputs first, numpy second: loading and validating the artifacts is
    # stdlib-only, so a numpy-less environment (the mcp-only install) still
    # names a bad ask precisely instead of leading with its own limitation.
    try:
        old = load_run(args.old)
        new = load_run(args.new)
    except VdiffUsageError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        import numpy  # noqa: F401
    except ModuleNotFoundError:
        print(
            "partspec: vdiff compares pixels, which needs numpy — any partspec "
            "engine extra brings it",
            file=sys.stderr,
        )
        return EXIT_USAGE

    out = args.out
    if out is None:
        base = args.new if args.new.is_dir() else args.new.parent
        out = base / "vdiff"
    try:
        doc = diff_renders(old, new, out, tool_version=tool_version())
    except VdiffUsageError as exc:
        # An unreadable or foreign image mid-diff: the ask was malformed,
        # nothing was compared — usage, never a fabricated outcome.
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (KeyError, ValueError, AttributeError, TypeError) as exc:
        # A parseable file that is not a well-formed render artifact (no
        # part block, no engine) is unusable input — 64, never the
        # catch-all's ERROR, mirroring `diff`'s boundary (PR #131, F2).
        print(
            f"partspec: these inputs are not well-formed render artifacts "
            f"({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return EXIT_USAGE
    json.dump(doc, sys.stdout, indent=2)
    sys.stdout.write("\n")
    print(summary_of(doc), file=sys.stderr)
    return exit_code_of(doc["outcome"])


def _cmd_diff(args: argparse.Namespace) -> int:
    """Compare two reports. The artifact goes to stdout — it is the product
    and it pipes; the courtesy summary goes to stderr (SPEC-diff.md 1)."""
    from .diff import DiffUsageError, diff_reports, exit_code_of, summary_of

    reports = []
    for path in (args.old, args.new):
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except OSError as exc:
            print(f"partspec: cannot read {path}: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except json.JSONDecodeError as exc:
            print(f"partspec: {path} is not a report: {exc}", file=sys.stderr)
            return EXIT_USAGE

    try:
        doc = diff_reports(reports[0], reports[1], tool_version=tool_version())
    except DiffUsageError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (KeyError, ValueError, AttributeError, TypeError) as exc:
        # A parseable file that is not a well-formed report (a check without
        # an id, a status outside the enum, a JSON array) is unusable input —
        # exit 64, never the catch-all's ERROR, and never a finding.
        print(
            f"partspec: these inputs are not well-formed reports ({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return EXIT_USAGE

    json.dump(doc, sys.stdout, indent=2)
    sys.stdout.write("\n")
    print(summary_of(doc, reports[1]), file=sys.stderr)
    return exit_code_of(doc["outcome"])


def _cmd_docs() -> int:
    """The path on stdout and nothing else, or a refusal on stderr.

    A caller writes `cd "$(partspec --docs)"`, so stdout carries the path
    alone -- and when there is no path, it carries nothing at all and the exit
    is non-zero. Printing the URL to stdout instead would substitute a string
    no shell can enter for the answer, which is the silence-reading-as-success
    shape this tool exists to refuse. ERROR rather than a usage code: the
    arguments were fine, the tool could not answer them.
    """
    root = docs_root()
    if root is None:
        print(
            "partspec: this copy carries no documents; read them at " + DOCS_URL,
            file=sys.stderr,
        )
        return exit_code(Verdict.ERROR)
    # The root, not `root / "docs"`: `skills/` is under it too, and the
    # citations that made this flag necessary are written from here.
    print(root)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args_list = argv if argv is not None else sys.argv[1:]
    if not args_list:
        parser.print_help()
        return EXIT_USAGE

    try:
        args = parser.parse_args(args_list)
    except SystemExit as exc:
        # argparse exits 2 on a usage error, and 2 is this tool's exit for
        # `incomplete` — a forgotten argument must not read as a verdict.
        # --help and --version exit 0 and pass through untouched.
        raise SystemExit(EXIT_USAGE if exc.code == 2 else exc.code) from None

    # The catch-all sits here, around the dispatch, and not inside `run`. Several
    # of the ways this fires never reach `run` at all: `--out` pointing at an
    # unwritable directory or an existing file dies in `write_placeholder`
    # (report.py) before the engine is touched. Left unguarded, every one of them
    # exited **1** -- this tool's code for "the part failed its contract" --
    # while the placeholder already on disk said `verdict: "error"`. The exit
    # code and the artifact contradicted each other, and exit 1 is the one an
    # agent is most likely to answer by editing the model.
    #
    # Reproduced with a `str` parameter (TypeError in adjudication), a
    # `PosixPath` parameter (TypeError rendering the -D literal), and both
    # `--out` cases. Deliberately not an isinstance ladder: the point is that
    # *unanticipated* failures land on ERROR rather than on a verdict about the
    # part. Placed after `parse_args`, so argparse keeps its own SystemExit.
    if args.docs:
        # Refused rather than silently won. `--version` discards a command the
        # same way, but `partspec --docs check foo` would have printed a path
        # and exited **0** having checked nothing -- and exit 0 on a check the
        # caller asked for is the one reading this tool exists to refuse. It is
        # also what the shape already does without a target, where argparse
        # rejects the subcommand's missing argument at 64 (PR #350 review).
        if args.command is not None:
            print(
                f"partspec: --docs locates the documents and runs nothing; "
                f"drop `{args.command}` or drop --docs",
                file=sys.stderr,
            )
            return EXIT_USAGE
        return _cmd_docs()

    try:
        if args.command == "check":
            return _cmd_check(args, args_list)
        if args.command == "measure":
            return _cmd_measure(args)
        if args.command == "render":
            return _cmd_render(args)
        if args.command == "lint":
            return _cmd_lint(args)
        if args.command == "diff":
            return _cmd_diff(args)
        if args.command == "vdiff":
            return _cmd_vdiff(args)
    except KeyboardInterrupt:
        print("\npartspec: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - the last resort before the shell
        traceback.print_exc()
        print(f"\npartspec: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  this is a partspec failure, not a verdict on the part", file=sys.stderr)
        return exit_code(Verdict.ERROR)

    parser.print_help()
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
