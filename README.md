# partspec

Verify CAD-as-code parts against declared engineering intent.

> **Status: pre-alpha; v0.7.8 is on PyPI.** It runs end to end and is dogfooded on real
> parts. Expect the Python API to move: the stable surface is the report schema plus the
> exit codes. What changed in each release is in
> [CHANGELOG.md](https://github.com/heibench/partspec/blob/main/CHANGELOG.md).

`partspec.run()` is internal: it is importable, it is not in `__all__`, and its signature may
change without a major bump. The package is fully annotated and ships a `py.typed` marker, so a
consumer type-checks against it rather than being handed `Any` — before v0.7.0 it shipped none,
which gave downstream not weaker checking but silently none at all.

## Install

```sh
pip install 'partspec[mesh]'      # OpenSCAD parts — the smallest useful install
```

Or for development, from a clone:

```sh
uv sync --all-extras     # or: just setup
uv run partspec check examples/spacer/spec.py:spacer
```

Engines are optional extras — `mesh`, `occt`, `cadquery` — so `uv sync --extra mesh` is
enough for OpenSCAD-only work. The `mcp` extra adds `partspec-mcp`, a stdio MCP server
exposing `check`, `measure`, `render` and `vdiff` as stateless tools: each call runs the CLI in a
fresh subprocess and returns its artifact, per the boundary in [D18](https://github.com/heibench/partspec/blob/main/docs/DECISIONS.md).

The `openscad` binary is a system dependency and is not on the wheel's dependency list,
and installing both Python engines under plain `pip` needs one extra step —
[Setting up the engines](#setting-up-the-engines) has both.

### Enforcing it in CI

The committed claims pin is what makes a contract enforceable by a machine: it
records the *claim set*, so a run whose contract has drifted from it fails
before the engine starts. `examples/spacer/` carries the worked copy —
[`claims.lock`](https://github.com/heibench/partspec/blob/main/examples/spacer/claims.lock)
beside the contract, and
[its README](https://github.com/heibench/partspec/blob/main/examples/spacer/README.md)
walks the `--pin` / `--expect` loop end to end. This repository's own CI runs
that exemplar on every pull request and on every push to `main`, so the snippet
below is a shape that is gated rather than one that is merely written down.

```yaml
# .github/workflows/partspec.yml
name: partspec
on: [push, pull_request]
jobs:
  parts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - run: sudo apt-get update && sudo apt-get install -y --no-install-recommends openscad
      - run: pip install 'partspec[mesh]'
      # Non-zero fails the job. --expect adjudicates the claim set before the
      # engine starts, so a weakened contract costs no build.
      - run: partspec check parts/spec.py:spacer --expect parts/claims.lock
      - if: always()
        uses: actions/upload-artifact@v4
        with: {name: partspec-reports, path: "**/outputs/**/report.json"}
```

What a red job means, and it is not one thing — the codes are enumerated once,
[below](#what-it-is-for), and what each *obliges a reader to do* is
[`docs/AGENT-CONTRACT.md`](https://github.com/heibench/partspec/blob/main/docs/AGENT-CONTRACT.md)
§2. The distinction this job turns on: `1` is a verdict about the **part** (a
declared limit was violated — fix the model), while `2`, `3`, `4` and `64` are
statements about the **run** (nothing was proven — the checks could not be
evaluated, the contract asserted nothing, the contract raised, or the
invocation was wrong). Only `0` is green, and a `2` is not a soft pass:
`incomplete` exits non-zero precisely so that silence cannot read as success.
Upload the report on `always()` — it is the product surface, and on a check
that ran it is what says which check failed and by how much. It is not
sufficient on its own: a `64` never gets that far, and the report at the
deterministic path is then a placeholder with `counts.total: 0` while the
diagnosis is on stderr alone. Watch the exit code, not only the artifacts
(`docs/AGENT-CONTRACT.md` §4).

### A contract is code

`check`, `measure` and `render` **import and execute** the module you name, and then the
model it points at: a Python model is `exec()`'d in this process, and a `.scad` is handed
to the `openscad` binary, which evaluates it and everything it `include`s. `lint` is
narrower but not outside this — its tier-1 rules only parse, while the three `csg-*`
tier-2 rules export the file through the same binary, so linting an untrusted `.scad`
runs it too. Only `diff` and `vdiff` execute nothing; they parse JSON and compare images.

That is not an implementation detail to be sandboxed away later: executing the contract is
how partspec learns what you claimed, and executing the model is the build. There is no
sandbox, and none is planned.

Import-scope code runs before partspec validates anything, so it runs even on a contract
the tool then rejects:

```console
$ ls
handed_to_me.py
$ partspec check handed_to_me.py:widget
Traceback (most recent call last):
  ... elided ...
partspec: the contract raised TypeError: Part.__init__() got an unexpected keyword argument 'model'
  the contract is wrong, not the part
$ echo $?
4
$ ls
EVIDENCE.txt  handed_to_me.py  outputs
```

So treat a contract exactly as you would treat any other Python you were handed: read it
before you run it. This matters most where partspec is most useful — an agent pointed at
"the contract in this repo", or the MCP server, where the caller sees a tool list and
nothing else. [SECURITY.md](https://github.com/heibench/partspec/blob/main/SECURITY.md)
states the boundary in full and says how to report something that crosses it.

## What runs today

`check`, `measure` and `render` work across all three engines, with `--section` cuts on both
tiers; `diff` compares two reports and `vdiff` two runs' renders. The vocabulary covers real
mechanical intent:
keep-out/keep-in regions, `hole_diameter`, `bolt_circle`, `fillet_radius`, `draft_angle`,
`self_intersection_free`, `step_roundtrip` and `min_wall` on the OCCT tier — the last of which
answers with a guaranteed interval and says `approximate` rather than guess when a limit falls
inside it. The loop is built to run unattended: every build is bounded (`--timeout`), `check`
takes many targets in one process, a committed claims pin (`--pin`/`--expect`) catches a
contract that shrank with no baseline in hand, and the rules an agent follows are
[`docs/AGENT-CONTRACT.md`](https://github.com/heibench/partspec/blob/main/docs/AGENT-CONTRACT.md).
And the repo teaches the craft it verifies: `partspec lint` (advisory; tier 1 is engine-free,
the three `csg-*` tier-2 rules need the OpenSCAD binary and refuse without it), three authoring
skills, worked exemplars, the observed [failure
catalogue](https://github.com/heibench/partspec/blob/main/docs/FAILURE-MODES.md), and a
[recorded
before/after](https://github.com/heibench/partspec/blob/main/evals/AUTHORING.md) showing
what the guidance changes.
[`docs/POST-V0.md`](https://github.com/heibench/partspec/blob/main/docs/POST-V0.md)
records what is still withheld and why.

## Engines

| engine | tier | notes |
|---|---|---|
| OpenSCAD | mesh | via binary STL, measured with trimesh |
| build123d | OCCT | native |
| CadQuery | OCCT | adopted into the build123d backend via `.wrapped` — same kernel, no conversion |

One contract, evaluated identically wherever it can be, with honest degradation where it
cannot.

## Setting up the engines

### The OpenSCAD binary

`partspec[mesh]` installs the Python side. The `openscad` binary itself is a system
dependency and is not on the wheel's dependency list — install it separately:

```sh
sudo apt install openscad             # Debian/Ubuntu — 2021.01
brew install openscad@snapshot        # macOS — a current snapshot
# or a build from https://openscad.org/downloads.html
```

`openscad@snapshot` rather than the bare `openscad` cask: that one is deprecated and
Homebrew disables it on 2026-09-01, after which it installs nothing.

`PARTSPEC_OPENSCAD` pins which binary is used, and the version is recorded in every report
because it changes the artifact — the same model can build a different part on a different
OpenSCAD, so the engine is part of the answer rather than a detail of how it was obtained.

### Headless

**2021.01 cannot write a PNG without a display** — it has no EGL offscreen path, so it
segfaults leaving a 0-byte file, which partspec reports as an environment fault rather
than a verdict on your part. This affects `render` and `check --render`; plain `check` and
`measure` are unaffected, because they export STL and that needs no GL context.

Either run those under `xvfb-run -a`, or use a build with EGL offscreen support. Note what
the second option means in practice: **2021.01 is the newest OpenSCAD release there has
ever been**, so a build with EGL offscreen is a development snapshot. On macOS the
`openscad@snapshot` cask above already is one. On Linux the AppImage needs more than a
download —

```sh
# It links a graphics stack it does not bundle, and will not answer --version without it.
sudo apt install -y libegl1 libgl1 libopengl0 libgbm1 libwayland-client0 \
                    libfontconfig1 libharfbuzz0b libgmp10

cd /somewhere/outside/your/repo   # --appimage-extract writes squashfs-root/ into the CWD
curl -fsSL -o openscad.AppImage \
  https://files.openscad.org/snapshots/OpenSCAD-2026.08.19-x86_64.AppImage
chmod +x openscad.AppImage && ./openscad.AppImage --appimage-extract >/dev/null
export PARTSPEC_OPENSCAD=$PWD/squashfs-root/AppRun
```

Extracted rather than run in place because mounting it needs `libfuse2`, and outside your
repo because that `squashfs-root/` contains a whole Python stdlib that every linter you
run will then walk. Snapshots are pruned on a rolling window, so pick a date currently
listed at <https://files.openscad.org/snapshots/> rather than the one above — that
address is also named in the hint partspec prints on this fault, and a test holds the two
together, so keep it spelled that way here. `.github/workflows/ci.yml` follows this same
procedure to pin the second engine leg (at its own pinned date, not the one above).

**Installing both Python engines with plain `pip`** needs one extra step:

```sh
pip install 'partspec[occt,cadquery]'
pip install --force-reinstall --no-deps cadquery-ocp   # re-assert the VTK build

# or, under uv
uv pip install 'partspec[occt,cadquery]'
uv pip install --no-deps --reinstall-package cadquery-ocp cadquery-ocp
```

build123d wants `cadquery-ocp-novtk` and CadQuery wants `cadquery-ocp`. Both wheels install
the same top-level `OCP/` package, neither pip nor uv detects the conflict, and whichever
lands last wins — when novtk wins, CadQuery cannot import at all. This repo drops novtk with
a `[tool.uv]` override, but that is a workspace setting and is not carried in wheel
metadata, so a `pip` install has no override in scope. Which one wins is install-order luck
and the two installers do not agree — `just test-cadquery-only` passed for a month on pip
and failed on its first CI run under uv — so the second line is not optional advice. If you
skip it, partspec tells you: the clobber is reported as an environment fault with that
command as the hint, not as a failing part — and it hints whichever of the two lines above
fits the environment it is running in, because a `uv venv` ships no `pip` and the word then
resolves to the system one, which installs somewhere the failing interpreter cannot see.

**`uv pip install 'partspec[occt]'` works.** Earlier releases of this README said it did
not — that no `OCP` module landed and you had to fall back to plain `pip` (#109). That was
wrong, and the cause was ours: `uv pip` reads `[tool.uv]` from the nearest pyproject.toml
above the working directory and applies it to whatever it is installing, so every
measurement taken from inside a partspec checkout inherited this repo's
`override-dependencies`, which drops `cadquery-ocp-novtk` on purpose. One directory over,
the same command has always worked. If you are installing *from* a clone, pass
`--no-config`.

That leaves one real way to reach an engine with no OCP behind it, and partspec names it
rather than blaming your part —

```
$ partspec check spec.py:stepper_bracket        # exit 4, verdict "error"
  --   builds — not evaluated: build123d is not importable: No module named
       'OCP'; no OCP provider is installed (cadquery-ocp-proxy 7.9.3.1.1 is
       present, but it ships no OCP) — something dropped cadquery-ocp-novtk
       from the resolution
  --   watertight — not evaluated: build123d is not importable: <the same>

ERROR: 2 skipped
  hint: pip install cadquery-ocp-novtk; if you installed from a partspec
        checkout, `uv pip` applied this repo's [tool.uv] override — re-run it
        with --no-config. See partspec issue #109
  outputs/spec-stepper_bracket/report.json
```

(Captured from a run, then wrapped to fit this page; the real lines are one
each. The hint names `pip` because that run had one — in a `uv venv` the same
hint reads `uv pip install`. Every declared check is `skipped` and `builds` is not reported as
failing, because an absent OCP disproves nothing about the design —
`build_origin: "environment"` in the report is the machine-readable form of
that distinction.)

## What it is for

You already write down what a part has to be true of — a minimum wall, a bolt circle, a
bore that has to clear an 8 mm shaft. Usually it lives in a README, a comment, or your
head, and nothing checks it. `partspec` lets you declare it next to the model and enforce
it in CI.

This is [`examples/spacer/spec.py`](https://github.com/heibench/partspec/blob/main/examples/spacer/spec.py) — the whole contract, minus
docstrings and formatting:

```python
from partspec import Part, openscad

PLATE = (40.0, 30.0, 6.0)
BORE_D = 8.0
WALL_MIN = 2.0


def spacer() -> Part:
    p = Part("example-spacer", openscad(
        "spacer.scad",
        plate_x=PLATE[0], plate_y=PLATE[1], plate_z=PLATE[2],
        bore_d=BORE_D, wall=WALL_MIN,
    ))

    # Parameter phase — arithmetic over the inputs, no engine needed.
    p.requires("bore_d + 2 * wall <= plate_y")
    p.requires("bore_d > 0")
    p.param("plate_z", min=1.0)

    # Geometry phase.
    p.envelope(max=PLATE)
    p.watertight()
    p.solid_count(1)
    p.genus(1)  # one bore straight through

    return p
```

```console
$ partspec check examples/spacer/spec.py:spacer
  ok   bore_d_2_wall_le_plate_y
  ok   bore_d_gt_0
  ok   param:plate_z
  ok   builds
  ok   envelope
  ok   watertight
  ok   solid_count
  ok   genus

PASS: 8 pass
  every dimensional limit on 'example-spacer' is unattributed: bounds derived from the model's own numbers prove the model matches itself — cite the source instead: partspec.refs for a standard it carries (iso15, iso_metric_thread, nema17), else partspec.Referenced(value, {"standard": ..., "subject": ..., "field": ...}) for anything it does not (SPEC-contract.md 10)
  /home/user/partspec/examples/spacer/outputs/spec-spacer/report.json
```

The JSON report is the actual product surface; the console summary is a courtesy.

<!-- BEGIN GENERATED: exit-codes -->
Exit codes: `0` pass, `1` fail, `2` incomplete, `3` empty, `4` error, `64` bad usage.
<!-- END GENERATED: exit-codes -->

(`130` is the SIGINT convention, not a verdict.)

That last warning line is the tool being honest about its own example: every bound above
is derived from the same constants the model is built from, so this contract proves the
model matches itself — real external footing looks like
`p.hole_diameter(iso15.bearing(608).od)`, where the number arrives from `partspec.refs`
with its citation recorded in the report.

`partspec lint` gives advisory findings about the source itself — magic numbers,
unused parameters, oversize modules — before a render is ever attempted; the rules and
their exact predicates are
[`docs/LINT.md`](https://github.com/heibench/partspec/blob/main/docs/LINT.md).
How to write a contract that proves something — check selection, limit provenance, the
retrofit path — is
[`skills/contract-authoring/`](https://github.com/heibench/partspec/tree/main/skills/contract-authoring).
The source-side rules are split by engine, and the contract skill routes you: OpenSCAD to
[`skills/openscad-authoring/`](https://github.com/heibench/partspec/tree/main/skills/openscad-authoring),
build123d and CadQuery to
[`skills/build123d-authoring/`](https://github.com/heibench/partspec/tree/main/skills/build123d-authoring)
— the Python engines fail by selection drift where OpenSCAD fails by silent geometry loss,
so the two sets do not transfer.
Worked exemplars beyond the spacer live in
[`examples/`](https://github.com/heibench/partspec/tree/main/examples) — a cited
NEMA 17 bracket, a two-engine bearing-seat family, a sealed enclosure — each with a README
saying what to imitate and why.

Writing a contract for a part you did not model? `partspec measure` dumps every quantity
the backend can honestly produce, with no verdict — so you can see the numbers before
deciding which of them are *intent*. It will not write the checks for you: a check the tool
wrote is a check nobody decided.

**If the author is an AI agent, `partspec` is the gate at the end of its loop.** The
authoring session owns making the part; `partspec` proves the result against intent the
model does not contain, and persists the proof — that boundary is
[D18](https://github.com/heibench/partspec/blob/main/docs/DECISIONS.md). The `mcp`
extra puts the gate in the agent's tool list: `check` returns the same report the CLI
writes, `measure`, `render` and `vdiff` the same output as their verbs, every call a
fresh stateless evaluation. And the loop is measured, not assumed: in the seeded-defect eval suite
([`evals/`](https://github.com/heibench/partspec/tree/main/evals)), an agent shown
only the report — no shell, no hints, contract frozen — repaired all five defect classes in
a single edit each, without once weakening its contract. The rules of that loop — bounded
attempts, what each exit code instructs, greppable escalation, and the guards watching the
weakening moves — are
[`docs/AGENT-CONTRACT.md`](https://github.com/heibench/partspec/blob/main/docs/AGENT-CONTRACT.md).

## The idea it is built around

A verification tool that reports a green result it has not earned is worse than no tool,
because it converts an open question into a false assurance. So `partspec` has five check
statuses and **only one of them is green**:

| status | meaning |
|---|---|
| `pass` | evaluated and satisfied, conclusively |
| `fail` | evaluated and violated, conclusively |
| `approximate` | evaluated, but the error interval straddles the limit — indeterminate |
| `unsupported` | this backend cannot evaluate this check on this geometry at all |
| `skipped` | not evaluated |

A part with **even one** unavailable check exits `2`, not `0` — `verdict_of` folds any
non-pass to `incomplete`, so this is not a threshold. A contract that asserts nothing exits
`3`. Neither is a pass, because neither established anything.

This matters most across engines. OpenSCAD emits a triangle mesh, which has no cylindrical
faces — so a hole diameter is genuinely unanswerable there, and `partspec` says so instead
of fitting a circle to the facets and reporting a confident wrong number. (An OpenSCAD
`cylinder($fn=16)` is a real 16-sided prism: fitting recovers Ø10.000 for a bore that
actually clears Ø9.808, and the error is always in the unsafe direction.)

It also matters on broken output. A CAD engine will happily exit `0` having written a mesh
that is open or non-manifold, and most measurement libraries will then hand you a volume
for it — a number that is not a bad estimate, but not a volume at all. Every measurement
here states its precondition and refuses when it fails, naming the defect:

```console
n/a  volume — volume is the integral over a closed surface; this mesh has 4 non-manifold edge(s)
```

Refusal is kept as narrow as the mathematics allows. An *open* mesh still determines its own
body count, so `solid_count` still answers there; only a non-manifold junction, where
counting through and counting across disagree, makes it refuse. An unnecessary
`unsupported` is its own way of failing to answer an answerable question.

## Documentation

Start at [`docs/README.md`](https://github.com/heibench/partspec/blob/main/docs/README.md),
which routes by what you are trying to do. **These documents install with the package** —
`partspec --docs` prints the directory holding `docs/` and `skills/`, so an agent working
from an install reads them without the network. Citations pointing outside those two trees
(`notes/`, `tests/`, `examples/`, the source) still need the repository. The full set,
of which the four `SPEC-*` documents are normative and were written before the
implementation:

- [`docs/AGENT-CONTRACT.md`](https://github.com/heibench/partspec/blob/main/docs/AGENT-CONTRACT.md) — how to drive the tool: read the
  report, not the console, and what each exit code obliges you to do.
- [`docs/SPEC-report.md`](https://github.com/heibench/partspec/blob/main/docs/SPEC-report.md) — the report schema and exit codes. This is
  the actual contract; the CLI verbs are not.
- [`docs/SPEC-contract.md`](https://github.com/heibench/partspec/blob/main/docs/SPEC-contract.md) — the Python contract API and check
  vocabulary.
- [`docs/SPEC-backend.md`](https://github.com/heibench/partspec/blob/main/docs/SPEC-backend.md) — the geometry backend protocol.
- [`docs/SPEC-diff.md`](https://github.com/heibench/partspec/blob/main/docs/SPEC-diff.md) — the semantic report comparator.
- [`docs/LINT.md`](https://github.com/heibench/partspec/blob/main/docs/LINT.md) — the advisory source rules and their tiers.
- [`docs/FAILURE-MODES.md`](https://github.com/heibench/partspec/blob/main/docs/FAILURE-MODES.md) — the observed CAD-as-code failure catalogue: what wrong parts look like when they're green.
- [`docs/DECISIONS.md`](https://github.com/heibench/partspec/blob/main/docs/DECISIONS.md) — every design decision, with its reasoning.
- [`docs/PLAN.md`](https://github.com/heibench/partspec/blob/main/docs/PLAN.md) — **historical**: how v0 was built and what was
  known then, not what the tool does now.
- [`docs/POST-V0.md`](https://github.com/heibench/partspec/blob/main/docs/POST-V0.md) — what is deliberately not here yet, and why.

## Prior art

`partspec` owes its assertion model to [cad-khana](https://github.com/cyberchitta/cad-khana)
(Apache-2.0), which arrived at declaring claims alongside the model, tri-state results, and
a diagnostics-first CLI independently and first.
[PartCAD](https://github.com/partcad/partcad) is the reference for engine-neutral part
packaging, and its `-D` parameter-passing approach is adopted directly.
[build123d-mcp](https://github.com/pzfreo/build123d-mcp) is the complement on the authoring
side — a stateful interactive session an agent designs *in*; `partspec` is the stateless
gate the result must pass, and deliberately does not own that loop
([D18](https://github.com/heibench/partspec/blob/main/docs/DECISIONS.md)).
[sca2d](https://gitlab.com/bath_open_instrumentation_group/sca2d) (GPLv3) is the
`.scad`-side static analyser — scoping and style, no geometry — and FreeCAD's
[importCSG](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/OpenSCAD/importCSG.py)
(LGPL) proved the `.csg` grammar small before `partspec lint`'s tier-2 reader was
hand-rolled (#118's survey records why neither could be depended on).

## License

Apache-2.0.
