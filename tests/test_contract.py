"""The contract API, the expression evaluator, and target resolution."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from partspec import Part, contract, openscad
from partspec.contract import GEOMETRY_KINDS
from partspec.expr import evaluate, operands_of
from partspec.status import ContractError
from partspec.target import Target, TargetError, resolve


def _part(**params) -> Part:
    return Part("p", openscad("x.scad", **params))


# --------------------------------------------------------------------------
# expression evaluation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "why"),
    [
        ("bore_d + 2 * wall - plate_y", "reads like a clearance; truthy for all but equality"),
        ("a - b", "an arithmetic value, not a claim"),
        ("not (a - b)", "UnaryOp(Not) always yields a real bool, so no result guard sees it"),
        (
            "a <= b and c",
            "BoolOp with a non-bool leaf; short-circuits, so a post-hoc check misses it",
        ),
        ("a == a", "compared with itself — true whatever it equals"),
        ("b >= b", "the same tautology through a different operator"),
    ],
)
def test_a_requires_that_is_not_a_predicate_is_refused(expr: str, why: str):
    """`requires("1")` passed. So did `requires("bore_d + 2*wall - plate_y")`,
    which reads like a clearance and is truthy for every value except exact
    equality — decorative, and green.

    The rule has to be recursive: a top-level-node rule admits both `not (...)`
    and `... and c`, and `not X` always returns a genuine bool so nothing
    downstream can catch it. Rejection must also be value-independent, which is
    why the bool-leaf check runs before eval rather than on the result.
    """
    with pytest.raises(ContractError):
        evaluate(expr, {"a": 1, "b": 2, "c": 3, "bore_d": 40, "wall": 2, "plate_y": 30})


def test_a_bool_leaf_is_a_predicate_but_a_number_is_not():
    """Bool parameters are a supported type, so `is_threaded and pitch > 0` is an
    honest claim and must not be caught by the net above."""
    ok, _ = evaluate("is_threaded and pitch > 0", {"is_threaded": True, "pitch": 1.5})
    assert ok is True
    with pytest.raises(ContractError, match="not a bool"):
        evaluate("pitch and is_threaded", {"is_threaded": True, "pitch": 1.5})


def test_the_bool_leaf_check_does_not_depend_on_the_values():
    """`a <= b and c` short-circuits, so whether `c` is ever bound depends on the
    parameters. A guard that fired only sometimes would be worse than none."""
    for binding in ({"a": 1, "b": 2, "c": 3}, {"a": 3, "b": 2, "c": 3}):
        with pytest.raises(ContractError, match="not a bool"):
            evaluate("a <= b and c", binding)


def test_a_requires_that_reads_no_parameter_claims_nothing():
    with pytest.raises(ContractError, match="reads no declared parameter"):
        evaluate("1 > 0", {"a": 1})


def test_evaluate_returns_result_and_operands():
    ok, operands = evaluate("a + b <= c", {"a": 1, "b": 2, "c": 5, "unused": 99})
    assert ok is True
    assert operands == {"a": 1, "b": 2, "c": 5}, "only the names actually read"


def test_chained_comparisons_record_every_operand():
    ok, operands = evaluate("0 < angle < 360 / pins", {"angle": 40, "pins": 2})
    assert ok is True
    assert operands == {"angle": 40, "pins": 2}


def test_operand_order_follows_the_source():
    """Not ast.walk order, which is breadth-first and would give (z, m, a).
    The order reaches a report that gets diffed, so it should match what the
    author wrote."""
    assert operands_of("z + a * z + m") == ("z", "a", "m")


def test_failure_reports_the_inputs_that_caused_it():
    ok, operands = evaluate("r + t/2 <= shell", {"r": 1.0, "t": 0.2, "shell": 1.0})
    assert ok is False
    assert operands == {"r": 1.0, "t": 0.2, "shell": 1.0}


def test_undeclared_name_is_a_contract_error_not_a_failure():
    """A claim the tool cannot evaluate has not been disproven."""
    with pytest.raises(ContractError, match="undeclared"):
        evaluate("a < b", {"a": 1})


@pytest.mark.parametrize(
    "expr",
    [
        "max(a, b) > 1",  # calls
        "a.b > 1",  # attribute access
        "a[0] > 1",  # subscript
        "(lambda: 1)() > 0",  # lambda
        "1 if a else 2",  # conditional
    ],
)
def test_grammar_is_restricted_for_legibility(expr):
    """Not a security boundary — the contract is already arbitrary Python. The
    point is that an expression whose operands can be printed is worth more than
    one that can only be reported as false."""
    with pytest.raises(ContractError):
        evaluate(expr, {"a": 1, "b": 2})


def test_syntax_error_is_reported_with_the_expression():
    with pytest.raises(ContractError, match="could not parse"):
        evaluate("a <", {"a": 1})


def test_division_by_zero_is_a_contract_error():
    with pytest.raises(ContractError, match="division by zero"):
        evaluate("1 / n > 0", {"n": 0})


# --------------------------------------------------------------------------
# declaration
# --------------------------------------------------------------------------


def test_checks_record_their_phase():
    p = _part(a=1.0)
    p.requires("a > 0")
    p.envelope(max=(10, 10, 10))
    assert [c.phase for c in p.checks] == ["parameter", "geometry"]


def test_declaration_order_is_preserved():
    """The report lists checks in declaration order, so this is load-bearing."""
    p = _part(a=1.0)
    p.watertight().requires("a > 0").solid_count(1)
    assert [c.id for c in p.checks] == ["watertight", "a_gt_0", "solid_count"]


def test_the_builds_id_is_reserved(tmp_path):
    """#134: the runner emits its own `builds` check; a contract shadowing
    the id put two same-id checks in one report and let a passing parameter
    check impersonate a failed build to check --render's gate."""
    p = _part(w=5.0)
    with pytest.raises(ContractError, match="reserved for the runner"):
        p.requires("w > 0", id="builds")
    with pytest.raises(ContractError, match="reserved for the runner"):
        p.watertight(id="builds")


def test_a_non_string_check_id_is_refused_where_it_is_written():
    """`CheckResult.id: str` is an annotation, not an enforcement.

    `p.param("wall", min=2.0, id=3)` was accepted, `check` wrote `"id": 3`, and
    #148's uniqueness guard in `diff` then refused that report at exit 64 —
    blaming the artifact for a mistake made in a contract two commands earlier,
    and falsifying two written claims that `partspec` cannot emit a report
    `diff` will refuse. Caught here now, beside the reserved-id and clash
    refusals, which is what makes those claims true (PR #157 review).
    """
    # `list[Any]`, not a bare tuple literal: pyright is correct that these are
    # not `str | None`, and that is the point of the test — the annotation is
    # what a caller with types on ignores, and this asserts what happens at
    # runtime when they do. Widening the local is honest; a `# type: ignore`
    # per call would suppress a diagnosis that is right.
    wrong_types: list[Any] = [3, 3.0, True, ("a",)]
    for bad in wrong_types:
        with pytest.raises(ContractError, match="not a string"):
            _part(wall=2.0).param("wall", min=1.0, id=bad)

    # The guard reaches only TRUTHY non-strings, because `id or <derived>` in
    # every caller short-circuits first. That is not a hole — the derived id is
    # always a string, so no out-of-spec report can result — but it is a
    # fall-through worth documenting rather than leaving for someone to
    # rediscover: an explicit `id=0` is silently ignored and replaced, with no
    # diagnostic. Recorded here so moving the type check into the defaulting,
    # where `""` and `None` would need distinguishing, fails this line first
    # (PR #157 review).
    falsy_values: list[Any] = [0, 0.0, False, [], (), ""]
    for falsy in falsy_values:
        derived = _part(wall=2.0).param("wall", min=1.0, id=falsy)
        assert derived.checks[0].id == "param:wall", (
            f"id={falsy!r} no longer falls through to the derived id"
        )

    # `None` is NOT in the refused list: it is the default and means "derive the id",
    # so it never reaches `_add` as an id. Asserted rather than left implicit,
    # because a guard written as `if not isinstance(spec.id, str)` placed before
    # the defaulting would refuse every ordinary check, and this is the line
    # that would say so.
    auto = _part(wall=2.0).param("wall", min=1.0, id=None)
    assert auto.checks[0].id == "param:wall"


def test_duplicate_ids_are_refused():
    """Ids are the join key a report diff relies on."""
    p = _part()
    p.watertight()
    with pytest.raises(ContractError, match="duplicate check id"):
        p.watertight()


def test_duplicate_kinds_are_fine_with_explicit_ids():
    p = _part()
    p.volume(min=1).volume(max=99, id="volume_ceiling")
    assert len(p.checks) == 2


def test_param_must_name_a_declared_parameter():
    """Catches a typo at declaration rather than reporting a mystery failure."""
    p = _part(bore_d=8.0)
    with pytest.raises(ContractError, match="not a declared parameter"):
        p.param("bore_diameter", min=1)


def test_a_part_needs_an_id():
    with pytest.raises(ContractError):
        Part("", openscad("x.scad"))


# --------------------------------------------------------------------------
# topology — the one check a tier cannot answer
# --------------------------------------------------------------------------


def test_topology_records_the_axes_it_was_given():
    p = _part()
    p.topology(faces=6, edges=12, vertices=8)
    assert p.checks[0].kind == "topology"
    assert p.checks[0].limit is not None
    assert p.checks[0].limit.equals == (6, 12, 8)


def test_topology_may_constrain_a_subset():
    """A face count is often the whole claim; edge and vertex counts move with
    modelling choices that are not intent."""
    p = _part()
    p.topology(faces=6)
    assert p.checks[0].limit is not None
    assert p.checks[0].limit.equals == (6, None, None)


def test_topology_claiming_nothing_is_refused():
    """Caught at declaration, not left to adjudication: `equals=(None, None,
    None)` is a limit that constrains nothing, and a check that claims nothing
    must never be able to report pass."""
    p = _part()
    with pytest.raises(ContractError, match="at least one of faces"):
        p.topology()


def test_the_tier_specific_kinds_are_exactly_the_declared_ones():
    """v0 shipped `topology` as the single deliberate tier-gated kind, to make
    the capability-refusal path reachable; `hole_diameter` is the first BREP
    dimension that machinery existed for. Everything else must stay
    tier-neutral — a kind that silently becomes OCCT-only is a portability
    regression this pins."""
    from partspec.backends.mesh import CAPABILITIES as MESH
    from partspec.backends.occt import CAPABILITIES as OCCT

    occt_only = {
        "topology",
        "hole_diameter",
        "bolt_circle",
        "fillet_radius",
        "draft_angle",
        "self_intersection_free",
        "step_roundtrip",
        "min_wall",
    }
    for kind in occt_only:
        assert GEOMETRY_KINDS[kind] in OCCT
        assert GEOMETRY_KINDS[kind] not in MESH
    others = {v for k, v in GEOMETRY_KINDS.items() if k not in occt_only}
    assert others <= MESH & OCCT, "no other check may depend on the tier"

    # And GEOMETRY_KINDS' own docstring must name the same set. It said
    # "topology and hole_diameter are the entries" long after there were
    # eight. The docstring carries no numeral, deliberately: a count beside
    # the data it counts is a second thing to forget, and this assertion
    # holds only what it can — the list.
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "partspec" / "contract.py").read_text()
    paragraph = re.search(
        r"^These entries have primitives.*?is how the first version rotted", source, re.S | re.M
    )
    assert paragraph, "GEOMETRY_KINDS must still explain its tier-asymmetric members"
    # Equality, not containment: `>=` let the docstring ADD a both-tiers kind
    # to the list and stay green (PR #152 review, MK4). Equality also pins the
    # set size without a numeral anywhere, which is the point.
    assert set(re.findall(r"`(\w+)`", paragraph.group(0))) == occt_only, (
        "the docstring's list and the code's OCCT-only set must be the same set"
    )


def test_source_records_the_engine_explicitly():
    """Never inferred from the file extension: a .py could be either Python
    engine, and guessing is the implicitness this project removes."""
    assert openscad("a.scad").engine == "openscad"


# --------------------------------------------------------------------------
# target resolution
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "path", "factory"),
    [
        ("a/b.py:lock", "a/b.py", "lock"),
        ("a/b.py", "a/b.py", None),
        ("./rel.py:x", "rel.py", "x"),  # Path normalises the leading ./
    ],
)
def test_target_parse(spec, path, factory):
    t = Target.parse(spec)
    assert (str(t.path), t.factory) == (path, factory)


def test_target_slug_distinguishes_factories():
    """So co-located targets never clobber each other's report."""
    assert Target.parse("a/spec.py:lock").slug == "spec-lock"
    assert Target.parse("a/spec.py:pin").slug == "spec-pin"


def test_missing_contract_is_a_target_error():
    with pytest.raises(TargetError, match="not found"):
        resolve("does/not/exist.py")


def test_naming_a_scad_model_prints_a_contract_that_resolves_to_it(tmp_path: Path):
    """The refusal used to be `could not load contract: c.scad` and nothing
    else (#439). What it prints now is run here, not read: saved beside the
    model, the contract it offers resolves to a Part over that model."""
    model = tmp_path / "c.scad"
    model.write_text("cube(10);\n")

    with pytest.raises(TargetError) as exc:
        resolve(str(model))
    message = str(exc.value)

    offered = textwrap.dedent(message[message.index("\n\n") :]).strip() + "\n"
    (tmp_path / "probe.py").write_text(offered)
    part, _ = resolve(str(tmp_path / "probe.py"))
    assert part.source.path.resolve() == model.resolve()


def test_naming_any_other_file_says_what_a_target_is(tmp_path: Path):
    """An agent refused on a `.scad` guessed a YAML contract next and met the
    same bare message (#439). There is no model to wrap here, so no contract
    is offered — only what a target is."""
    other = tmp_path / "c.yaml"
    other.write_text("part: c\n")

    with pytest.raises(TargetError) as exc:
        resolve(str(other))
    assert "<file>.py[:<factory>]" in str(exc.value)
    assert "def " not in str(exc.value)


def test_ambiguity_lists_the_available_factories(tmp_path: Path):
    """The error message is the discovery mechanism — no separate list verb."""
    module = tmp_path / "many.py"
    module.write_text(
        "from partspec import Part, openscad\n"
        "def first() -> Part: return Part('a', openscad('x.scad'))\n"
        "def second() -> Part: return Part('b', openscad('x.scad'))\n"
    )
    with pytest.raises(TargetError) as exc:
        resolve(str(module))
    assert "many.py:first" in str(exc.value)
    assert "many.py:second" in str(exc.value)


def test_a_lone_factory_needs_no_name(tmp_path: Path):
    module = tmp_path / "one.py"
    module.write_text(
        "from partspec import Part, openscad\n"
        "def only() -> Part: return Part('a', openscad('x.scad'))\n"
    )
    part, _ = resolve(str(module))
    assert part.id == "a"


def test_unannotated_helpers_are_not_factories(tmp_path: Path):
    """The `-> Part` annotation is the declaration; a helper that happens to
    build a Part stays private to the contract."""
    module = tmp_path / "helper.py"
    module.write_text(
        "from partspec import Part, openscad\n"
        "def helper(): return Part('h', openscad('x.scad'))\n"
        "def real() -> Part: return Part('r', openscad('x.scad'))\n"
    )
    part, _ = resolve(str(module))
    assert part.id == "r"


def test_no_factories_is_a_target_error(tmp_path: Path):
    module = tmp_path / "none.py"
    module.write_text("VALUE = 1\n")
    with pytest.raises(TargetError, match="no part factories"):
        resolve(str(module))


def test_relative_source_anchors_to_the_contract_not_the_cwd(tmp_path: Path):
    """Otherwise a contract works or fails depending on the shell's history."""
    (tmp_path / "model.scad").write_text("cube(1);\n")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n"
        "def p() -> Part: return Part('p', openscad('model.scad'))\n"
    )
    part, _ = resolve(str(module))
    assert part.source.path == (tmp_path / "model.scad").resolve()
    assert part.source.path.is_file()


def test_absolute_source_is_left_alone(tmp_path: Path):
    target = tmp_path / "abs.scad"
    target.write_text("cube(1);\n")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n"
        f"def p() -> Part: return Part('p', openscad({str(target)!r}))\n"
    )
    part, _ = resolve(str(module))
    assert part.source.path == target


def test_contract_raising_on_import_is_a_target_error(tmp_path: Path):
    module = tmp_path / "boom.py"
    module.write_text("raise ValueError('bang')\n")
    with pytest.raises(TargetError, match="raised on import"):
        resolve(str(module))


# --------------------------------------------------------------------------
# requires() slugs (#38)
# --------------------------------------------------------------------------


def test_each_comparison_operator_slugs_distinctly():
    # The id is the join key a future diff relies on; two different claims
    # must never alias. Pinned per operator.
    from partspec.contract import _slug

    assert _slug("x > 5") == "x_gt_5"
    assert _slug("x < 5") == "x_lt_5"
    assert _slug("x >= 5") == "x_ge_5"
    assert _slug("x <= 5") == "x_le_5"
    assert _slug("x == 5") == "x_eq_5"
    assert _slug("x != 5") == "x_ne_5"


def test_a_bracketing_pair_of_bounds_coexists():
    p = _part(x=1.0)
    p.requires("x > 0").requires("x < 10")
    assert [c.id for c in p.checks] == ["x_gt_0", "x_lt_10"]


def test_a_residual_collision_names_both_expressions():
    p = _part(x=1.0)
    long = "x > " + "0" * 80
    p.requires(long)
    with pytest.raises(ContractError) as exc:
        p.requires(long + "1")  # same 60-char prefix after truncation
    message = str(exc.value)
    assert long in message and long + "1" in message


# --------------------------------------------------------------------------
# hole_diameter declaration (#80)
# --------------------------------------------------------------------------


def test_hole_diameter_records_band_and_count():
    p = _part()
    p.hole_diameter(8.0, count=2, tol=0.1)
    spec = p.checks[0]
    assert spec.kind == "hole_diameter"
    assert spec.id == "hole_d8"
    assert spec.hole == {"d": 8.0, "count": 2}
    assert spec.limit is not None
    assert spec.limit.min == pytest.approx(7.9) and spec.limit.max == pytest.approx(8.1)


def test_hole_diameter_default_band_is_the_comparison_epsilon():
    from partspec.status import epsilon

    p = _part()
    p.hole_diameter(8.5)
    spec = p.checks[0]
    assert spec.id == "hole_d8_5", "a dot in an id would break the diff join key style"
    assert spec.limit is not None
    assert spec.limit.max - spec.limit.min == pytest.approx(2 * epsilon(8.5))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"d": 0}, "d > 0"),
        ({"d": -8.0}, "d > 0"),
        ({"d": float("nan")}, "d > 0"),
        ({"d": 8.0, "count": 0}, "count >= 1"),
        ({"d": 8.0, "count": 2.0}, "count >= 1"),
        ({"d": 8.0, "count": True}, "count >= 1"),
        ({"d": 8.0, "tol": 0.0}, "tol must be > 0"),
        ({"d": 8.0, "tol": float("nan")}, "tol must be > 0"),
    ],
)
def test_degenerate_hole_claims_are_refused(kwargs, match):
    with pytest.raises(ContractError, match=match):
        _part().hole_diameter(kwargs.pop("d"), **kwargs)


def test_hole_diameter_gates_on_the_bores_primitive():
    assert GEOMETRY_KINDS["hole_diameter"] == "bores"


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"d": 0, "count": 4, "bcd": 40.0}, "d > 0"),
        ({"d": 5.0, "count": 1, "bcd": 40.0}, "count >= 2"),
        ({"d": 5.0, "count": True, "bcd": 40.0}, "count >= 2"),
        ({"d": 5.0, "count": 4, "bcd": 4.0}, "bcd > d"),
        ({"d": 5.0, "count": 4, "bcd": 40.0, "tol": 0.0}, "tol must be > 0"),
    ],
)
def test_degenerate_bolt_circle_claims_are_refused(kwargs, match):
    with pytest.raises(ContractError, match=match):
        _part().bolt_circle(kwargs.pop("d"), **kwargs)


def test_bolt_circle_records_the_callout():
    p = _part()
    p.bolt_circle(5.0, count=4, bcd=40.0, tol=0.2)
    spec = p.checks[0]
    assert spec.id == "bolt_circle_4x_d5"
    assert spec.hole == {"d": 5.0, "count": 4, "bcd": 40.0}
    assert spec.limit is not None
    assert spec.limit.min == pytest.approx(39.8) and spec.limit.max == pytest.approx(40.2)


def test_a_positional_band_wider_than_the_hole_is_refused():
    """PR #89 review, blocker 2: with no datum the claim is existential, and a
    wide band is satisfiable by circles no drawing describes — a cherry-picked
    centre passed 8-on-the-circle as 'exactly 4' at tol=21."""
    with pytest.raises(ContractError, match="must not exceed d"):
        _part().bolt_circle(5.0, count=4, bcd=40.0, tol=21.0)


def test_fillet_radius_must_bound_something():
    with pytest.raises(ContractError, match="claims nothing"):
        _part().fillet_radius()
    with pytest.raises(ContractError, match="min must be > 0"):
        _part().fillet_radius(min=0)


# --------------------------------------------------------------------------
# MEASURANDS — the one column of SPEC-contract §4.2 that no other code knows
#
# §4.2's table is generated from the code (`scripts/gen_docs.py`), so nothing
# below reads markdown. Method, kind and tier are derived at generation and
# cannot disagree with anything. Shape and unit are declared in `MEASURANDS`,
# and unit is the half that reality can answer — so it is asked here, against
# the functions that actually attach it.
#
# This replaces `test_the_unit_table_lists_every_unit_a_measurement_can_carry`,
# which compared a markdown table against an AST walk. Same walk, no markdown,
# and per-kind rather than set-wide: that test would have passed with `volume`
# documented in `mm2`.
# --------------------------------------------------------------------------

SRC = Path(__file__).resolve().parent.parent / "src"

# Kinds whose unit is attached somewhere other than the primitive named in
# `GEOMETRY_KINDS`: four the runner composes from other primitives, and
# `min_wall`, whose backend method delegates to a helper. Asserted for equality
# below, never merely tolerated — a kind that quietly stops being covered by the
# primitive walk has to appear here or fail.
_UNIT_ATTACHED_ELSEWHERE = {
    "keep_out": "_run_region_check",
    "keep_in": "_run_region_check",
    "bolt_circle": "_run_bolt_circle_check",
    "step_roundtrip": "_run_step_check",
    "min_wall": "_min_wall_measurement",
}


def _units_by_function() -> dict[str, set[str]]:
    """Every `Measurement(value, "unit")` in `src/`, keyed by enclosing function.

    Static rather than executed because the alternative is building a part that
    exercises all seventeen kinds on the OCCT tier, which is a much slower test
    that would skip on the mesh-only path — where a wrong unit is just as wrong.
    """
    import ast

    found: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and getattr(call.func, "id", None) == "Measurement"
                    and len(call.args) >= 2
                    and isinstance(call.args[1], ast.Constant)
                    and isinstance(call.args[1].value, str)
                ):
                    found.setdefault(node.name, set()).add(call.args[1].value)
    assert found, "the walk found no Measurement call at all"
    return found


def test_every_declared_unit_is_the_unit_the_code_emits():
    """`MEASURANDS[kind].unit` equals the unit the answering function attaches."""
    from partspec.contract import MEASURANDS

    emitted = _units_by_function()
    composed = set()
    for kind, primitive in GEOMETRY_KINDS.items():
        units = emitted.get(primitive, set())
        if not units:
            composed.add(kind)
            continue
        assert len(units) == 1, f"`{primitive}` emits more than one unit: {sorted(units)}"
        assert MEASURANDS[kind].unit == next(iter(units)), (
            f"MEASURANDS says `{kind}` is {MEASURANDS[kind].unit!r}; "
            f"`{primitive}` emits {next(iter(units))!r}"
        )

    # The five whose unit lives elsewhere, through the function that attaches it.
    assert composed == set(_UNIT_ATTACHED_ELSEWHERE), (
        f"kinds no primitive measures, and not recorded as composed: "
        f"{sorted(composed - set(_UNIT_ATTACHED_ELSEWHERE))}; "
        f"recorded as composed but now measured directly: "
        f"{sorted(set(_UNIT_ATTACHED_ELSEWHERE) - composed)}"
    )
    for kind, handler in _UNIT_ATTACHED_ELSEWHERE.items():
        units = emitted[handler]
        assert units == {MEASURANDS[kind].unit}, (
            f"MEASURANDS says `{kind}` is {MEASURANDS[kind].unit!r}; "
            f"`{handler}` emits {sorted(units)}"
        )


def test_the_declared_units_are_exactly_the_units_the_tool_emits():
    """Both directions, which is the failure `bool` and `rel` actually were:
    the tool emitted them and the table described a smaller vocabulary. A
    subset check in one direction cannot see that."""
    from partspec.contract import MEASURANDS

    emitted = {u for units in _units_by_function().values() for u in units}
    declared = {m.unit for m in MEASURANDS.values() if m.unit is not None}
    assert declared == emitted, (
        f"declared and never emitted: {sorted(declared - emitted)}; "
        f"emitted and undeclared: {sorted(emitted - declared)}"
    )


def test_the_extra_primitives_match_what_the_runner_calls():
    """`EXTRA_PRIMITIVES` is derived from the runner, not remembered.

    A kind's tier is computed from every primitive it needs. `GEOMETRY_KINDS`
    records one per kind, and the region checks are composed in the runner from
    two — so `EXTRA_PRIMITIVES` carries the remainder. That started as a third
    hand-written copy of a fact already in `runner.py` and in SPEC-contract §4.4,
    with nothing holding it to either (PR #156 review, finding C). The failure it
    invites is silent: a later composed check lands with a `GEOMETRY_KINDS` entry
    and no `EXTRA_PRIMITIVES` entry, and §4.2's tier cell answers from half the
    work while every test stays green.

    So the map is checked against the handlers. For each `_run_<x>_check` in the
    runner, the declared primitives it calls must be exactly the ones the two
    maps promise for the kinds it serves.
    """
    import ast

    from partspec.backends import mesh, occt
    from partspec.contract import EXTRA_PRIMITIVES, GEOMETRY_KINDS

    primitives = occt.CAPABILITIES | mesh.CAPABILITIES
    runner = ast.parse((SRC / "partspec" / "runner.py").read_text())

    called: dict[str, set[str]] = {}
    for node in ast.walk(runner):
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("_run_")):
            continue
        for call in ast.walk(node):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
                continue
            if call.func.attr in primitives:
                called.setdefault(node.name, set()).add(call.func.attr)
    assert called, "the walk found no primitive call in any runner handler"

    # Every kind whose handler reaches past its recorded primitive must say so.
    recorded = {k: {GEOMETRY_KINDS[k], *EXTRA_PRIMITIVES.get(k, ())} for k in GEOMETRY_KINDS}
    for handler, used in called.items():
        owners = [k for k, need in recorded.items() if GEOMETRY_KINDS[k] in used]
        if not owners:
            continue
        for kind in owners:
            missing = used - recorded[kind]
            assert not missing, (
                f"`{handler}` calls {sorted(missing)} for `{kind}`, which neither "
                f"GEOMETRY_KINDS nor EXTRA_PRIMITIVES records — so §4.2's tier cell "
                f"for `{kind}` is computed from less than the check actually needs"
            )

    # And no entry survives that the runner stopped needing.
    for kind, extra in EXTRA_PRIMITIVES.items():
        anywhere = {p for used in called.values() for p in used}
        stale = set(extra) - anywhere
        assert not stale, (
            f"EXTRA_PRIMITIVES[{kind!r}] names {sorted(stale)}, which no handler calls"
        )


@pytest.mark.parametrize("name", [["plate_x", "plate_y"], {"plate_x": 1}, {"plate_x"}])
def test_an_unhashable_parameter_name_gets_partspecs_own_message(name):
    """The third site of #199's hole, found by sweeping the public API after
    the first two were fixed (adversarial review of #240).

    `name not in self.source.params` hashes `name`, so an unhashable value died
    inside the guard with `cannot use 'list' as a dict key` — and, unlike the
    other two, it also lost #188's traceback trimming, so the reader got
    partspec's internal frames as well as its internal data structure.

    `p.param(["plate_x", "plate_y"], min=1.0)` — bounding two parameters in one
    call — is at least as plausible as the `axis=(0, 0, 1)` that motivated the
    issue. (An earlier draft called `param` "the most-used method in the
    contract API"; counted across `tests/`, `docs/` and `examples/` it is
    seventh, behind `watertight` by about 4x. The finding did not need the
    superlative.)
    """
    from partspec import Part, openscad

    part = Part("x", openscad("m.scad", plate_x=1.0))
    # Matched on the TYPE, not on the phrasing. `REFUSED_OUT_HINT`'s docstring
    # forty lines from the code this touches records why: pinning one spelling
    # of advice pins the spelling, not the advice, and an adversarial review
    # put the forbidden wording back under a synonym with the suite still green
    # (round-2 review of #240).
    with pytest.raises(ContractError, match=f"not {type(name).__name__}"):
        part.param(name, min=1.0)
    # And the ordinary wrong-name case keeps its own sentence.
    with pytest.raises(ContractError, match="is not a declared parameter"):
        part.param("nope", min=1.0)


def test_a_refused_argument_is_quoted_but_not_pasted_whole():
    """All three #199 guards quote the operand, and on `main` the unhashable
    value died before it could be formatted.

    So the fix made the message worse before it made it better:
    `cylinder(axis=[0.0] * 2000)` produced a 10 KB error and a 20 KB CLI run
    against main's 1.4 KB, putting the actionable half of the sentence ten
    kilobytes from the start of the line — 15x the token cost of the bug it
    explains, for an agent reading stderr (round-2 review of #240).
    """
    from partspec import Part, openscad, region
    from partspec.refs import iso15

    # The wrong type is the point, so the ignores are the test.
    big: Any = list(range(2000))
    raised = []
    for call in (
        lambda: region.cylinder(d=5, h=5, axis=big),
        lambda: iso15.bearing(big),
        lambda: Part("x", openscad("m.scad", w=1.0)).param(big, min=1.0),
    ):
        with pytest.raises(ContractError) as caught:
            call()
        raised.append(str(caught.value))

    for message in raised:
        assert len(message) < 400, f"{len(message)} chars: {message[:120]}"
        assert "chars)" in message, "and it says the quote was cut rather than pretending"


# --------------------------------------------------------------------------
# build_input (#215)
# --------------------------------------------------------------------------


def test_a_module_name_is_refused_with_the_distribution_that_ships_it():
    """`build_input` takes a DISTRIBUTION, because that is what `imports` keys
    a RECORD-owned entry by. `OCP` is one keystroke from right, and a value
    that close must be routed rather than accepted and quietly ignored — an
    accepted-and-ignored declaration would leave the author believing they had
    coverage they do not have, which is the failure the field exists to close.

    Answerable at the call site because `packages_distributions()` reads
    installed metadata, not imports — so this fails where the mistake is,
    rather than after a build.
    """
    pytest.importorskip("OCP", reason="occt extra not installed")
    p = Part("p", openscad("x.scad"))
    with pytest.raises(ContractError) as excinfo:
        p.build_input("OCP")

    assert "OCP is the module" in str(excinfo.value)
    assert "cadquery-ocp" in str(excinfo.value)
    assert p.build_inputs == [], "a refused declaration must not be recorded"


def test_a_declaration_is_not_a_check():
    """It declares provenance — how hard to look at an input — and never what
    the part must be. So it adds no `CheckSpec`, cannot pass or fail, and has
    no row in §4's vocabulary (`contract.PROVENANCE_METHODS`)."""
    p = Part("p", openscad("x.scad")).build_input("partspec")
    assert p.checks == []
    assert p.build_inputs == ["partspec"]
    assert "build_input" in contract.PROVENANCE_METHODS


@pytest.mark.parametrize("bad", ["", "   ", None, 7])
def test_a_declaration_needs_a_name(bad):
    p = Part("p", openscad("x.scad"))
    with pytest.raises(ContractError, match="non-empty string"):
        p.build_input(bad)


def test_resolving_a_single_factory_records_the_symbol_without_moving_the_slug(tmp_path: Path):
    """#343. `part.contract` is the only field separating two targets in one
    module, and `diff` can only compare it where one target has ONE spelling —
    so the factory is resolved whether or not the invocation named it.

    The slug is the constraint on that, pinned here beside it: it decides the
    default `--out` directory, and `partspec check spec.py` has written
    `outputs/spec` since v0. A slug derived from the resolved symbol would
    silently move every such user's reports — the `--pin` baselines and the
    `diff` inputs among them — to `outputs/spec-spacer`.
    """
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, openscad\n\n\n"
        "def spacer() -> Part:\n"
        "    return Part('solo', openscad('spacer.scad'))\n"
    )

    _, target = resolve(str(tmp_path / "spec.py"))
    assert target.factory == "spacer", "the resolved symbol is recorded, not just called"
    assert target.inferred is True, "and it is marked as inferred rather than named"
    assert target.slug == "spec", "the default --out directory MUST NOT move (#343)"

    _, named = resolve(f"{tmp_path / 'spec.py'}:spacer")
    assert (named.factory, named.inferred) == ("spacer", False)
    assert named.slug == "spec-spacer", "a NAMED factory still gets its own directory"
