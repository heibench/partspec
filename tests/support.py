"""Shared test helpers."""

from __future__ import annotations

import importlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from partspec.backend import Unsupported
from partspec.engines import openscad
from partspec.status import Measurement

__all__ = [
    "FIXTURES",
    "OPENSCAD",
    "check_of",
    "decode_png",
    "forced_open_solid",
    "measured",
    "needs_build123d",
    "needs_mesh",
    "needs_numpy",
    "needs_openscad",
    "needs_scad_tier",
    "openscad_supports_backend_flag",
    "optional_module",
    "py_target",
    "refused",
    "report_of",
    "scad_target",
    "sew_into_solid",
]

FIXTURES = Path(__file__).parent / "fixtures"

OPENSCAD = openscad.find_executable()

needs_openscad = pytest.mark.skipif(OPENSCAD is None, reason="openscad binary not installed")
"""Skip when there is no engine — but see `conftest.py`, which turns that skip
into a hard failure under `PARTSPEC_REQUIRE_ENGINES=1`. A skip is the right
local behaviour and the wrong CI behaviour, and the difference is worth a
switch rather than a habit."""


def openscad_supports_backend_flag() -> bool:
    """Whether the installed engine has `--backend` at all.

    2021.01 does not: render backends arrived later. This is a real portability
    boundary rather than a quirk — 2021.01 is what Debian and Ubuntu ship — so
    tests branch on it and assert both sides.
    """
    if OPENSCAD is None:
        return False
    proc = subprocess.run([OPENSCAD, "--help"], capture_output=True, text=True, check=False)
    return "--backend" in proc.stdout + proc.stderr


def measured(result: Measurement | Unsupported) -> Measurement:
    """Assert a primitive answered, and narrow the type for the type checker.

    Worth an assertion rather than a cast. Several primitives now refuse when
    their precondition fails, so "this returned a number" is a real claim about
    the fixture — and a test that silently type-ignored a refusal would pass
    while measuring nothing.
    """
    assert not isinstance(result, Unsupported), f"unexpectedly refused: {result.reason}"
    return result


def refused(result: Measurement | Unsupported) -> Unsupported:
    """Assert a primitive refused, and narrow the type."""
    assert isinstance(result, Unsupported), f"expected a refusal, got {result!r}"
    return result


needs_scad_tier = pytest.mark.skipif(
    OPENSCAD is None or importlib.util.find_spec("trimesh") is None,
    reason="the scad tier needs the openscad binary AND the mesh extra",
)
"""For a test that drives an OpenSCAD part all the way to a measurement.

`needs_openscad` alone is not enough, and the gap was invisible: OpenSCAD
exports an STL and `backends/mesh.py` measures it, so the scad tier needs
`trimesh` as much as it needs the binary. On a machine with the binary and no
mesh extra — `pip install partspec`, the first minute of use — 23 tests marked
only `needs_openscad` did not skip. They ran, got exit 4, and FAILED.

CI never saw it because no job ran the WHOLE suite without extras: `check` and
`test` install all of them, and `mesh-only`/`mcp-only` ran a single module
each. So the one environment that would show it was the one nothing ran in.
`just test-no-extras` runs everything there now, and `just test-mesh-only`
was widened to the whole suite for the same reason.

Use `needs_openscad` alone only for a test that stops at the engine — a build
error, a usage refusal — and never reaches a measurement.
"""

needs_build123d = pytest.mark.skipif(
    importlib.util.find_spec("build123d") is None, reason="occt extra not installed"
)
needs_mesh = pytest.mark.skipif(
    importlib.util.find_spec("trimesh") is None, reason="mesh extra not installed"
)
needs_numpy = pytest.mark.skipif(
    importlib.util.find_spec("numpy") is None,
    reason="numpy (it arrives with trimesh and with both OCCT-tier engines) not installed",
)
"""One spelling for "this test needs an extra", and never at module scope.

The suite spelled it five ways — `importorskip` in 38 bodies, `find_spec`
skipifs in three idioms, and six hand-rolled `if OPENSCAD is None:
pytest.skip(...)`. These markers are the one to reach for; 51 in-body
`importorskip` calls remain in modules that are otherwise engine-free, and
converting them is tidying rather than a fix, because a body-level skip still
collects and still counts.

What is not tolerated is a **module-level** gate, which does not:
`test_packaging.py::test_only_a_module_that_cannot_import_gates_at_import`
enforces that, and names the three modules that genuinely cannot import
without their extra.
"""


class _NotInstalled:
    """Stands in for an absent extra, and says so the moment it is touched."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attr: str) -> Any:
        raise AssertionError(
            f"reached {self._name}.{attr} with {self._name} not installed — "
            f"this test needs a needs_* marker (tests/support.py)"
        )


def optional_module(name: str) -> Any:
    """Bind a CAD module that may not be installed, without gating the file.

    A module-level `pytest.importorskip` raises at *import*, so pytest reports
    the whole file as one skipped line. That hid 11 tests needing no engine at
    all, and — worse — four `the mesh tier refuses with the tier named` tests,
    invisible in `pip install partspec[mesh]`, the one install where the mesh
    tier is the only tier (#165). Binding the name here lets the module import
    everywhere; each test that drives the kernel carries its own `needs_*`
    marker, and one that forgets fails by name instead of measuring nothing.
    """
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return _NotInstalled(name)


def scad_target(
    tmp_path: Path, *, source: str | Path, claims: str = "", part_id: str = "subject"
) -> str:
    """The OpenSCAD equivalent. `source` may name a file in tests/fixtures."""
    src = Path(source)
    src = src if src.is_absolute() else FIXTURES / src
    name = src.name
    shutil.copy(src, tmp_path / name)
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        f"    p = Part({part_id!r}, openscad({name!r}))\n"
        f"{claims}"
        "    return p\n"
    )
    return f"{spec}:make"


def py_target(
    tmp_path: Path, *, model: str = "m.py", claims: str = "", part_id: str = "subject"
) -> str:
    """The build123d equivalent of `scad_target`, for a model the test wrote.

    Deliberately NOT a mirror: `scad_target` copies a `.scad` out of
    `tests/fixtures`, while a build123d test almost always authors its model
    inline, because the model body IS the thing under test. So this writes the
    contract only and takes the model's filename.

    Written once for the occt half of #153 and then deleted unused, on the
    grounds that shipping a helper nothing calls is the slop that slice was
    removing. It is back with 16 real callers.
    """
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        f"    p = Part({part_id!r}, build123d({model!r}))\n"
        f"{claims}"
        "    return p\n"
    )
    return f"{spec}:make"


def report_of(out: Path) -> dict:
    """The `report.json` written under `out`, parsed.

    This read appeared 38 times across eight files (#153): 27 spelled
    `json.loads((out / "report.json").read_text())` verbatim, 11 the same shape
    over a different directory. The path is the tool's own convention —
    `SPEC-report.md` §5.5 derives it from the target — so every one of those
    sites carried a second copy of a fact the tool owns.

    Named for what it returns rather than what it does, and kept next to
    `check_of` so the pair reads as "the whole document" / "one check of it".

    The missing-file assertion is the reason this is worth a helper rather than
    an alias: `read_text()` on an absent report raises `FileNotFoundError`,
    which says the file is missing but not that the run failed to write one —
    and a report is written even when the run fails, so its absence is the
    finding.

    That message names the WRITER, not `partspec check`. Four call sites in
    `test_report.py` drive `Report.write()` / `write_placeholder()` directly and
    never invoke the CLI, so a message blaming `check --out` would point a
    reader — plausibly a downstream packager running the shipped suite from an
    sdist, with no repo to read — at a command the failing test never ran.
    """
    path = out / "report.json"
    if not path.is_file():
        present = sorted(p.name for p in out.iterdir()) if out.is_dir() else "no such directory"
        raise AssertionError(
            f"no report at {path}; the writer produces one even when the run "
            f"fails (SPEC-report.md 5.5). Present: {present}"
        )
    return json.loads(path.read_text())


def check_of(out: Path, kind: str) -> dict:
    """The one check of `kind` from the report written under `out`.

    Replaces the report reads that selected a check by kind through a
    `next(c for c in ... if c["kind"] == ...)` generator.

    Raises rather than returning None: an absent check is a test bug, and
    `StopIteration` inside a generator expression reads as a confusing error.
    """
    doc = report_of(out)
    matching = [c for c in doc["checks"] if c["kind"] == kind]
    assert matching, (
        f"no {kind!r} check in the report; kinds present: {[c['kind'] for c in doc['checks']]}"
    )
    assert len(matching) == 1, f"{len(matching)} checks of kind {kind!r}; name one by id instead"
    return matching[0]


def sew_into_solid(faces):
    """Sew loose faces and force the result into a `Solid`, valid or not.

    The idiom three test files spelled out: it is how you build a shape the
    kernel would never produce, which is the only way to test what happens
    when one arrives. Needs build123d, so callers must be marked.
    """
    import build123d as bd
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeSolid,  # pyright: ignore[reportAttributeAccessIssue]
        BRepBuilderAPI_Sewing,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.TopoDS import TopoDS

    sew = BRepBuilderAPI_Sewing()
    for face in faces:
        sew.Add(face.wrapped)
    sew.Perform()
    return bd.Solid(BRepBuilderAPI_MakeSolid(TopoDS.Shell(sew.SewedShape())).Solid())  # pyright: ignore[reportAttributeAccessIssue]


def forced_open_solid():
    """Five faces of a box sewn into a "solid" — ill-formed on purpose, and
    the executed STEP degrader: the reader's healing drops it entirely.

    Two files built this identically; a third sews a tetrahedron, which is a
    different fixture sharing only the idiom above.
    """
    import build123d as bd

    return sew_into_solid(bd.Box(10, 10, 10).faces()[:5])


def decode_png(path: Path) -> tuple[int, int, bytes]:
    """A written PNG's `(width, height, rgb_bytes)`.

    Four copies of this walk existed — three in `test_raster.py`, one inside
    `test_cli._cut_pixels` which also reimplemented the shade formula.

    **For PNGs written by `partspec.raster.write_png` only.** That writer emits
    filter 0 on every row, which is what makes a decoder this short correct.
    OpenSCAD's writer uses libpng's adaptive filtering — measured on real
    scad-tier output: `{1: 277, 2: 350, 4: 173}` across one image's rows — so
    this refuses rather than misdecoding it. The scad tier's `--section` path
    is safe because the cut is rasterized by partspec, not by OpenSCAD.

    Deliberately not `partspec.vdiff.read_png`: a test that decoded with the
    same code the product decodes with would prove only self-consistency.
    """
    import struct
    import zlib

    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    # The stride below assumes 8-bit truecolour RGB; without this check any
    # other format decodes to plausible-looking garbage.
    assert (data[24], data[25], data[28]) == (8, 2, 0), (
        f"{path.name} is not non-interlaced 8-bit truecolour RGB"
    )

    idat = b""
    pos = 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        if kind == b"IDAT":
            idat += data[pos + 8 : pos + 8 + length]
        pos += 12 + length

    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    rows = [raw[y * stride : (y + 1) * stride] for y in range(height)]
    assert all(row[0] == 0 for row in rows), (
        f"{path.name} uses PNG row filters. partspec's own writer emits filter 0 on "
        "every row; OpenSCAD's does not, and this decoder is only for the former"
    )
    return width, height, b"".join(row[1:] for row in rows)
