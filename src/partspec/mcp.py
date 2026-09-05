"""MCP server over the same primitives as the CLI.

D5 deferred this until the report was machine-readable and the CLI had real
use; D18 fixes what it may be: **stateless verbs over `check` and `measure`**.
Every call is a fresh evaluation of a contract against a source on disk,
returning the same artifact the CLI writes. No tool holds geometry between
calls — the interactive authoring session belongs to authoring tools.

Each call runs the CLI in a subprocess rather than calling into the runner
in-process, for two reasons that are load-bearing, not stylistic:

- `POST-V0.md` §8: `sys.modules` caches a model's helper modules, so a
  long-lived process that re-checks an edited model can build the *previous*
  version of a helper while digesting the new one from disk — a stale build
  reported as fresh. A process per call makes that impossible; #27 owns
  deciding whether an invalidation story is worth the startup cost it saves.
- The exit code is part of the contract (`SPEC-report.md`). A subprocess
  returns the CLI's own, unlaundered; an in-process call would re-derive it.

The `mcp` dependency is an extra, imported lazily inside `build_server` —
`import partspec` stays stdlib-only, and this module is imported only by the
`partspec-mcp` entry point and its tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .install import install_hint
from .status import EXIT_USAGE

if TYPE_CHECKING:
    from mcp.server import MCPServer

__all__ = ["build_server", "main"]

# Enough stderr to carry a traceback and the CLI's own diagnosis; not enough
# to flood a model's context when an engine dumps its life story.
_STDERR_TAIL = 4000

_INSTRUCTIONS = """\
partspec verifies CAD-as-code parts against engineering intent declared in a
Python contract. `check`, `measure` and `render` import and execute the
contract module they are given, and the model it points at -- a Python model
directly, a `.scad` through the `openscad` binary, which also evaluates
everything it includes. Do not point them at a contract you would not run as a
script. `vdiff` takes no contract and executes nothing. Only the verdict
`pass` is green. `incomplete` means checks
could not be evaluated — unproven, not failing. `empty` means the contract
asserts nothing. `error` means the tool or environment failed and says nothing
about the part. Never weaken a contract to make it pass: a green report on a
weakened contract proves nothing, and the report records enough to detect it.

These four tools are the whole surface, and it is a WEAKER loop than the one
partspec specifies for an agent. `--expect` and `--pin` (the claims pin, which
is what catches a contract that shrank), `--timeout`, and the `diff` and `lint`
verbs are CLI-only and unreachable from here — so the pin-and-compare remedy
cannot be run through these tools and needs a shell.

Only `check` produces a report artifact: its result carries `report` — the
parsed `report.json` — and `report_path`, and its CLI call passes `--quiet`, so
read the report rather than any console text. `measure`, `render` and `vdiff`
write no report and return their JSON payload directly, under `measured`,
`rendered` and `vdiff` respectively; that value is the product, so do not hunt
for a report beside it. `render` does leave files — `render.json`, the view
PNGs its payload's `renders` names by path, and on the OpenSCAD tier the
exported artifact — and `vdiff` takes exactly those: a `render.json` or
`report.json` path, or the directory holding one. Every result also carries
`exit_code`, and carries `stderr` instead of a payload when the run produced
none.

The documents these tools cite by section — AGENT-CONTRACT.md for the repair
loop, SPEC-contract.md for authoring, SPEC-report.md for the artifact — ship
with the package: `partspec --docs`, in a shell, prints the directory holding
them — `docs/AGENT-CONTRACT.md` and `skills/contract-authoring/SKILL.md` are
underneath it (#349). An MCP client has a tool list
and nothing else, so this paragraph is the only place it can learn that. They
are also at https://github.com/heibench/partspec/tree/main/docs
"""


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "partspec", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _check(target: str, out: str | None, render: bool = False) -> dict[str, Any]:
    # Private import, deliberately: the report's location is the CLI's rule and
    # duplicating it here would let the two drift apart silently. This comment
    # spelled the rule out anyway, and had drifted -- a sentence about the
    # danger of a second copy, being a second copy. `Target.parse` is total, so
    # this cannot raise — resolution failures happen in the subprocess, which
    # leaves its placeholder artifact behind for the read below.
    from .cli import _out_dir

    out_dir = _out_dir(target, Path(out) if out is not None else None)

    args = ["check", target, "--quiet"]
    if out is not None:
        args += ["--out", out]
    if render:
        args.append("--render")
    proc = _run_cli(args)

    result: dict[str, Any] = {
        "exit_code": proc.returncode,
        "report": None,
        "report_path": str(out_dir / "report.json"),
    }
    try:
        result["report"] = json.loads((out_dir / "report.json").read_text())
    except (OSError, json.JSONDecodeError):
        # No artifact — the CLI's own failure path. stderr is the only
        # evidence there is, so it rides along; when a report exists it is
        # the whole story and stderr would only restate it.
        result["report_path"] = None
        result["stderr"] = proc.stderr[-_STDERR_TAIL:]
    return result


def _render(target: str, out: str | None, section: str | None = None) -> dict[str, Any]:
    # The whole payload, like measure's: since #103 the render output carries
    # the part's identity and a JSON failure artifact, and extracting just the
    # view map here would strip both — the error would arrive as a bare exit
    # code, machine-invisible exactly where a machine is the audience.
    args = ["render", target]
    if out is not None:
        args += ["--out", out]
    if section is not None:
        args += ["--section", section]
    proc = _run_cli(args)
    result: dict[str, Any] = {"exit_code": proc.returncode, "rendered": None}
    try:
        result["rendered"] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result["stderr"] = proc.stderr[-_STDERR_TAIL:]
    return result


def _vdiff(old: str, new: str, out: str | None = None) -> dict[str, Any]:
    args = ["vdiff", old, new]
    if out is not None:
        args += ["--out", out]
    proc = _run_cli(args)
    result: dict[str, Any] = {"exit_code": proc.returncode, "vdiff": None}
    try:
        result["vdiff"] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result["stderr"] = proc.stderr[-_STDERR_TAIL:]
    return result


def _measure(target: str) -> dict[str, Any]:
    proc = _run_cli(["measure", target])
    result: dict[str, Any] = {"exit_code": proc.returncode, "measured": None}
    try:
        result["measured"] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result["stderr"] = proc.stderr[-_STDERR_TAIL:]
    return result


def build_server() -> MCPServer:
    from mcp.server import MCPServer

    server = MCPServer("partspec", instructions=_INSTRUCTIONS)

    # The verbs match the CLI by name and meaning — agents use the same
    # commands as humans (D5).

    @server.tool()
    def check(target: str, out: str | None = None, render: bool = False) -> dict[str, Any]:
        """Build a part and check it against its contract.

        `target` is `<module-path>[:<factory>]`, e.g. `specs/bracket.py:bracket`.
        `out` is the report directory; omit it and the report lands in
        `<contract dir>/outputs/<part-slug>`, beside the contract rather than
        in the working directory. Either way `report_path` in the result says
        where it went.
        Returns the report the CLI writes, its path, and the exit code:
        0 pass, 1 fail, 2 incomplete (unproven, not failing), 3 empty
        (the contract asserts nothing), 4 error (partspec or the environment
        failed — no verdict on the part), 64 bad usage. With `render=True`
        the report also records the canonical view images it produced.
        """
        return _check(target, out, render)

    @server.tool()
    def measure(target: str) -> dict[str, Any]:
        """Dump every quantity the backend can honestly produce. No verdict.

        The adoption path: see the numbers before deciding which of them are
        intent. `refused` quantities name this part's defect; `unavailable`
        ones name the tier's limit. It will not write checks for you — a
        check the tool wrote is a check nobody decided.
        """
        return _measure(target)

    @server.tool()
    def render(target: str, out: str | None = None, section: str | None = None) -> dict[str, Any]:
        """Write the canonical views (iso, front, top, right) as PNGs.

        Deterministically framed from the bounding box, so two runs of the
        same geometry are comparable. `out` is the directory for `render.json`
        and the view PNGs; omit it and they land in
        `<contract dir>/outputs/<part-slug>`, beside the contract rather than
        in the working directory. `section` ("xy"|"xz"|"yz", optionally
        ":offset" in mm, default the bounding-box centre) adds a cut view —
        internal features made visible, cut faces in a distinct colour.
        Returns the render payload: the part's identity, the engine block,
        and `renders` mapping view name -> file path (empty, beside an
        `error`, when rendering failed). The images are evidence, not
        judgement — no verdict rides with them, and rendering never
        substitutes for measurement.
        """
        return _render(target, out, section)

    @server.tool()
    def vdiff(old: str, new: str, out: str | None = None) -> dict[str, Any]:
        """Compare two runs' renders of one part visually.

        `old`/`new` are render.json / report.json paths (or the directories
        holding them, i.e. a previous render's `out`). `out` here is the
        directory for the per-view diff images; omitted, it is `vdiff` beside
        `new` -- inside it when `new` is a directory, in its parent when `new`
        is a file. That is relative to the run being compared and not to a
        contract, because the inputs are artifacts rather than a target, and
        every `image` path in the result is absolute either way. Returns the
        vdiff document: per-view changed-pixel fractions with diff images, the
        bbox delta (pure scale is invisible to framed pixels — the bbox is
        the witness), and a scalar `magnitude`. Exit 0 identical, 1
        different, 2 indeterminate — a pair it cannot honestly compare
        (different engine versions, sizes, parts) is refused, never scored.
        """
        return _vdiff(old, new, out)

    return server


def main() -> int:
    try:
        server = build_server()
    except ImportError as exc:
        print(f"partspec-mcp: the MCP SDK is not importable: {exc}", file=sys.stderr)
        print("  hint: " + install_hint("'partspec[mcp]'"), file=sys.stderr)
        return EXIT_USAGE
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
