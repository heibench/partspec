"""Resolve `<module-path>[:<factory>]` to a Part.

The error message is the discovery mechanism: asked for a module with several
part factories, the failure lists them rather than saying "ambiguous". Borrowed
from cad-khana, where the same idea means you never need a separate `list` verb
to find out what a file offers.

Spec: SPEC-contract.md section 2.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType

from .contract import Part, Source

__all__ = ["ContractImportError", "Target", "TargetError", "factories", "resolve"]


class TargetError(Exception):
    """The target could not be resolved. Exits 64 and writes no report."""


class ContractImportError(TargetError):
    """The contract's own code raised while it was being imported (#438).

    A `TargetError` so that callers suppressing resolution failures still do,
    but the CLI does not route it to 64: the file was found and is a contract,
    so the invocation was right and the contract is wrong. That is exit 4, the
    same as the same raise inside a factory. The original exception is
    `__cause__`.
    """


@dataclass(frozen=True, slots=True)
class Target:
    path: Path
    factory: str | None = None
    inferred: bool = False
    """True when `resolve` filled `factory` in because the module declares
    exactly one, rather than the invocation having named it (#343).

    `factory` is what reaches `part.contract`, and it is resolved ALWAYS so
    that a single-factory module records its symbol too: `diff` compares that
    field, and it can only do so where one target has one spelling.

    What this flag protects is `slug` — but NOT, today, the CLI's default
    `--out`, and the difference matters to anyone changing either. Every
    production slug is taken from a **parsed, unresolved** target
    (`cli._out_dir`, `_out_dir_for`, and the batch collision guard all call
    `Target.parse(spec).slug`), which never sees an inferred factory, so
    dropping this flag would leave `partspec check spec.py` writing
    `outputs/spec` and only `tests/test_contract.py`'s unit assertion would
    fail (PR #353 review, F1). It keeps `slug` answering the same question on
    a resolved target as on a parsed one — the factory the INVOCATION named —
    so a library caller holding the resolved target gets `outputs/spec` too,
    and so `_out_dir` may be moved onto the resolved target later without
    silently relocating every existing user's reports.
    """

    @staticmethod
    def parse(spec: str) -> Target:
        head, sep, tail = spec.rpartition(":")
        if sep and tail.isidentifier():
            return Target(Path(head), tail)
        return Target(Path(spec))

    @property
    def slug(self) -> str:
        """Report directory name — distinct per factory so co-located targets
        never clobber each other's report.

        Keyed on the factory the INVOCATION named, never an inferred one:
        `partspec check spec.py` on a single-factory module has written
        `outputs/spec` since v0, and a slug derived from the resolved symbol
        would move every such user's reports to `outputs/spec-spacer` —
        the `--pin` baselines and the stored `diff` inputs among them.
        See `inferred` for which callers that rule actually reaches, and
        `tests/test_contract.py::
        test_resolving_a_single_factory_records_the_symbol_without_moving_the_slug`
        for the pin.
        """
        if self.factory is None or self.inferred:
            return self.path.stem
        return f"{self.path.stem}-{self.factory}"


_CONTRACT_MODULE_PREFIX = "_partspec_contract_"
"""What `_load` names the modules it synthesises.

Shared with the diagnostic below rather than spelled twice: the name embeds
`hash()`, which is salted per process, so a class defined in the contract
itself carries a DIFFERENT `__module__` on every run. A message qualifying
such a class by its module would print unstable noise where it promised a
locus (PR #340 review, F4).
"""


def _not_a_contract(path: Path) -> str:
    """The refusal for a file the import machinery will not load as Python.

    It used to be `could not load contract: <path>`, which names no way
    forward, and it was the commonest first-run error in the agent sessions
    reviewed: seven calls met it, and one agent refused on a `.scad` tried a
    YAML contract next and read the same sentence again (#439).

    For a `.scad` the way forward is three lines, so they are printed with the
    path filled in -- SPEC-contract 7's probe, which `measure` and `render`
    accept as it stands. Any other suffix gets the form of a target and
    nothing more: there is no saying which engine would read it.
    """
    what = (
        f"{path} is not a contract: a target is a Python module that declares "
        f"a part, <file>.py[:<factory>]"
    )
    if path.suffix.lower() != ".scad":
        return f"{what} (SPEC-contract.md 2)"
    return (
        f"{what}. The smallest contract for this model, saved beside it "
        f"(SPEC-contract.md 7):\n\n"
        f"    from partspec import Part, openscad\n\n\n"
        f"    def probe() -> Part:\n"
        f'        return Part("probe", openscad({path.name!r}))'
    )


def _load(path: Path) -> ModuleType:
    if not path.is_file():
        raise TargetError(f"contract not found: {path}")

    module_name = f"{_CONTRACT_MODULE_PREFIX}{abs(hash(str(path.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise TargetError(_not_a_contract(path))

    module = importlib.util.module_from_spec(spec)
    # Registered before exec so that dataclasses and typing inside the contract
    # can resolve the module by name during import.
    sys.modules[module_name] = module
    # The contract's own directory goes on the path so it can import helpers
    # that live beside it.
    parent = str(path.resolve().parent)
    added = parent not in sys.path
    if added:
        sys.path.insert(0, parent)
    try:
        # Compiled from source, never from the bytecode cache. CPython
        # validates a .pyc by (mtime seconds, size), so a same-length edit
        # within one second re-executes the OLD contract under the NEW
        # contract_digest — an agent's rapid edit loop hits exactly that, and
        # the claims pin (#31) would adjudicate bytecode the file no longer
        # contains. Contracts are small; the pyc saves nothing worth that.
        code = compile(path.read_bytes(), str(path), "exec")
        exec(code, module.__dict__)  # noqa: S102 - executing the contract IS the product
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        # BaseException: `sys.exit(0)` at contract import scope is user code
        # choosing our exit status, and it chose green.
        raise ContractImportError(
            f"contract raised on import: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if added:
            sys.path.remove(parent)
    return module


def factories(module: ModuleType) -> tuple[str, ...]:
    """Public callables defined in `module` and annotated `-> Part`.

    The return annotation is the declaration: a helper that happens to build a
    Part but is not annotated stays private to the contract, which is usually
    what the author meant.
    """
    found: list[str] = []
    for name, obj in vars(module).items():
        if name.startswith("_") or not callable(obj):
            continue
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        try:
            hints = inspect.signature(obj).return_annotation
        except (TypeError, ValueError):
            continue
        if hints is Part or hints in ("Part", "partspec.Part"):
            found.append(name)
    return tuple(found)


def resolve(spec: str) -> tuple[Part, Target]:
    """Resolve a target string to a Part.

    Records whatever the contract's import pulled in from beside it, so a
    later `invalidate_model_modules(target.path)` can evict it. The recording
    used to live only in `cli._cmd_check`, which meant a library caller —
    or a test — that reached `resolve()` directly left its siblings cached
    under bare names like `claims` with nothing tracking them. The deslop
    audit found exactly that: an exemplar's `claims.py` outlived its test and
    answered for a later one in a different directory, breaking the five
    tests that exist to prove that cannot happen. Bookkeeping belongs with
    the import that causes it.

    In a `finally`, because the case that most needs the record is the one
    where the contract imports its sibling and THEN raises (#114 path 1):
    recording after a successful `_load` leaves the leak untracked on
    exactly the path `cli._cmd_check`'s own `finally` was written for.
    """
    from .engines.pycad import record_model_modules

    target = Target.parse(spec)
    modules_before = set(sys.modules)
    try:
        module = _load(target.path)
    finally:
        record_model_modules(target.path, modules_before)
    available = factories(module)

    if target.factory is not None:
        factory = getattr(module, target.factory, None)
        if factory is None:
            raise TargetError(
                f"{target.path}: no factory named {target.factory!r}. "
                f"Available: {', '.join(available) or 'none'}"
            )
    elif len(available) == 1:
        factory = getattr(module, available[0])
        # Recorded, not merely called. `part.contract` is the only field that
        # separates two targets in one module (#297), and `diff` compares it
        # (#343) — which it can only do where one target has ONE spelling.
        # Emitting the symbol solely when the invocation typed it made
        # `spec.py` and `spec.py:spacer` two strings for one run, and a
        # comparator cannot tell that pair from a genuine change. `inferred`
        # keeps this target's `slug` reading as it did before, so the rule
        # holds whichever target a caller takes the slug from.
        target = replace(target, factory=available[0], inferred=True)
    elif not available:
        raise TargetError(
            f"{target.path} declares no part factories. A factory is a public "
            f"function annotated `-> Part`."
        )
    else:
        raise TargetError(
            f"{target.path} declares several part factories, so one must be named: "
            + ", ".join(f"{target.path}:{name}" for name in available)
        )

    # Called with its own defaults — a factory's defaults are the master design.
    part = factory()
    if not isinstance(part, Part):
        # QUALIFIED with the defining module, because the collision is the
        # common case rather than an exotic one: build123d and CadQuery each
        # export a `Part` too, so an author who points `check` or `measure` at
        # the MODEL used to be told it "returned Part, not a Part" -- the same
        # word twice, naming no way forward and reading as a tool bug (#282).
        # The second line says what to do, because the model IS discovered as
        # a factory here: `_load` compiles and execs, which leaves every
        # annotation a string, so `-> Part` in a build123d model is
        # indistinguishable from a contract's by the annotation alone.
        got = type(part)
        where = (
            f"{got.__qualname__} defined in {target.path.name}"
            if got.__module__.startswith(_CONTRACT_MODULE_PREFIX)
            else f"{got.__module__}.{got.__qualname__}"
        )
        raise TargetError(
            f"{target.path}:{getattr(factory, '__name__', '?')} returned "
            f"{where}, not partspec.Part"
            f"\n  hint: check and measure take the CONTRACT, not the model it "
            f"builds. Write a contract declaring this model as its source "
            f"(SPEC-contract.md 3), then name that file."
        )
    part.source = _anchor(part.source, target.path.resolve().parent)
    return part, target


def _anchor(source: Source, contract_dir: Path) -> Source:
    """Resolve a relative source path against the contract's directory.

    `openscad("spacer.scad")` in a contract means the file sitting beside it, not
    a file relative to wherever the user happened to run the command from. The
    alternative — resolving against the process CWD — makes a contract work or
    fail depending on the shell's history, which is exactly the kind of
    action-at-a-distance a reproducibility tool should not ship with.
    """
    if source.path.is_absolute():
        return source
    return replace(source, path=(contract_dir / source.path).resolve())
