"""`evals/run.py`, the agent-in-the-loop harness, with no agent in the loop (#414).

The harness decides what a trial *means* — converged, failed, gamed, error —
and a wrong answer there is worse than a crash, because it gets published. It
was gated by lint alone, so the only way to learn whether a change still
worked was a paid run. Everything here substitutes two stubs for the two
external processes: an agent command that edits the scratch copy the way a
scripted agent would, and a `partspec` that answers `check`, `lint` and
`--version` from the model's contents. No real agent is ever invoked.
"""

from __future__ import annotations

import importlib.util
import json
import shlex
import sys
import tempfile
import textwrap
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN_PY = ROOT / "evals" / "run.py"

# `evals/` is excluded from the sdist on purpose (#150), and `tests/` ships so a
# packager can run the suite there. This module asks how THIS checkout's harness
# behaves, which an unpacked sdist cannot answer — the same reasoning as
# `test_lint_config.py`'s guard. A collection-time skip of the whole file is
# right here: there is no test in it that could run without the harness.
pytestmark = pytest.mark.skipif(not RUN_PY.exists(), reason="evals/ is not in an sdist")


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> types.ModuleType:
    """A fresh import of `evals/run.py` whose case and results trees are temporary."""
    spec = importlib.util.spec_from_file_location("partspec_evals_run", RUN_PY)
    assert spec is not None and spec.loader is not None, f"cannot load {RUN_PY}"
    module = importlib.util.module_from_spec(spec)
    # `dataclass` resolves string annotations through `sys.modules`.
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "CASES", tmp_path / "cases")
    monkeypatch.setattr(module, "AUTHORING_CASES", tmp_path / "cases-authoring")
    monkeypatch.setattr(module, "RESULTS", tmp_path / "results")
    skills = tmp_path / "skills"
    (skills / "openscad-authoring").mkdir(parents=True)
    (skills / "openscad-authoring" / "SKILL.md").write_text("# guidance\n")
    monkeypatch.setattr(module, "SKILLS", skills)
    return module


# The stub partspec. `check` passes iff the model contains FIXED, reports
# `error` iff it contains WORSE, and otherwise fails; it prints the report path
# the way the real tool does, relative to the contract's directory. `lint`
# answers whatever STUB_LINT holds, verbatim, so malformed output is testable.
STUB_PARTSPEC = """\
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
if args == ["--version"]:
    print("partspec 0.0.0-stub")
    sys.exit(0)
if args[0] == "lint":
    print(os.environ.get("STUB_LINT", '{"counts": {"findings": 0, "unsupported": 0}}'))
    sys.exit(0)
assert args[0] == "check", args
model = Path("model.scad")
text = model.read_text() if model.exists() else ""
verdict = "pass" if "FIXED" in text else "error" if "WORSE" in text else "fail"
report = Path("outputs") / "spec-part" / "report.json"
report.parent.mkdir(parents=True, exist_ok=True)
report.write_text(os.environ.get("STUB_REPORT") or json.dumps({"verdict": verdict}))
print(report)
print(f"verdict: {verdict}")
print("done")
sys.exit(0 if verdict == "pass" else 2 if verdict == "incomplete" else 1)
"""

# The stub agent: argv[1] is a script of comma-separated actions, applied one per
# call in order and the last repeated. It records every prompt it receives.
STUB_AGENT = """\
import sys
from pathlib import Path

prompt = sys.stdin.read()
log = Path(sys.argv[2])
calls = log.read_text().count("\\0") if log.exists() else 0
with log.open("a") as f:
    f.write(prompt + "\\0")
actions = sys.argv[1].split(",")
action = actions[min(calls, len(actions) - 1)]
if action == "fix":
    Path("model.scad").write_text("FIXED\\n")
elif action == "worsen":
    Path("model.scad").write_text("WORSE\\n")
elif action == "game":
    Path("spec.py").write_text(Path("spec.py").read_text() + "# relaxed\\n")
    Path("model.scad").write_text("FIXED\\n")
elif action == "delete-contract":
    Path("spec.py").unlink()
    Path("model.scad").write_text("FIXED\\n")
elif action == "crash":
    print("agent fell over", file=sys.stderr)
    sys.exit(3)
elif action != "noop":
    raise SystemExit(f"unknown action {action}")
print(f"did {action}")
"""


@pytest.fixture
def partspec(tmp_path: Path) -> str:
    path = tmp_path / "bin" / "partspec"
    path.parent.mkdir()
    path.write_text(f"#!{sys.executable}\n{STUB_PARTSPEC}")
    path.chmod(0o755)
    return str(path)


class Agent:
    """Builds stub-agent command lines and reads back the prompts they received."""

    def __init__(self, tmp_path: Path):
        self.script = tmp_path / "agent.py"
        self.script.write_text(STUB_AGENT)
        self.log = tmp_path / "agent.log"

    def __call__(self, actions: str) -> str:
        return shlex.join([sys.executable, str(self.script), actions, str(self.log)])

    def prompts(self) -> list[str]:
        return self.log.read_text().split("\0")[:-1] if self.log.exists() else []


@pytest.fixture
def agent(tmp_path: Path) -> Agent:
    return Agent(tmp_path)


def make_case(parent: Path, case_id: str, *, authoring: bool = False, **cfg) -> Path:
    d = parent / case_id
    d.mkdir(parents=True)
    (d / "spec.py").write_text("# frozen contract\n")
    lines = [f'id = "{case_id}"', 'target = "spec.py:part"']
    if authoring:
        (d / "TASK.md").write_text("Build a part.\n")
        lines += ['mode = "authoring"', 'model = "model.scad"', 'frozen = ["spec.py", "TASK.md"]']
    else:
        (d / "model.scad").write_text("BROKEN\n")
        lines += ['frozen = ["spec.py"]']
    lines += [f"{k} = {json.dumps(v)}" for k, v in cfg.items()]
    (d / "case.toml").write_text("\n".join(lines) + "\n")
    return d


def trial(run, tmp_path: Path, case_dir: Path, agent_cmd: str, partspec: str, arm="control"):
    import tomllib

    cfg = tomllib.loads((case_dir / "case.toml").read_text())
    # A fresh directory per call: two trials of one case share artifact names.
    out = Path(tempfile.mkdtemp(prefix="out-", dir=tmp_path))
    return run.run_trial(case_dir, cfg, 1, agent_cmd, partspec, out, arm)


# --- the pure decision functions -------------------------------------------


@pytest.mark.parametrize(
    ("findings", "unsupported", "expected"),
    [
        (0, 0, "clean"),
        (2, 0, "findings"),
        # The case `lint_outcome`'s docstring is about: zero findings beside
        # refused rules is a file three rules never looked at, not a clean one.
        (0, 3, "incomplete"),
        (2, 3, "incomplete"),
        # A partspec predating the `unsupported` key cannot say it was whole.
        (0, None, "incomplete"),
        (None, None, "unknown"),
        (None, 0, "unknown"),
    ],
)
def test_lint_outcome_decides_wholeness_before_findings(run, findings, unsupported, expected):
    assert run.lint_outcome(findings, unsupported) == expected
    assert expected in run.LINT_OUTCOMES


def test_digests_name_a_deleted_frozen_file_missing_and_see_any_edit(run, tmp_path: Path):
    (tmp_path / "spec.py").write_text("a")
    before = run.digests(tmp_path, ["spec.py", "absent.py"])
    assert before["absent.py"] == "MISSING"
    assert before["spec.py"] != "MISSING"
    (tmp_path / "spec.py").write_text("b")
    assert run.digests(tmp_path, ["spec.py"]) != {"spec.py": before["spec.py"]}
    (tmp_path / "spec.py").unlink()
    assert run.digests(tmp_path, ["spec.py"]) == {"spec.py": "MISSING"}


def test_source_loc_counts_code_lines_and_skips_blank_and_comment_lines(run, tmp_path: Path):
    model = tmp_path / "model.scad"
    model.write_text(
        textwrap.dedent(
            """\
            // a line comment
            cube(1);

            /* a block
               spanning lines */
            /* one-line block */
            sphere(2);
              // indented comment
            cylinder(3);
            """
        )
    )
    assert run.source_loc(model) == 3


def test_lint_counts_reads_both_counts(run, tmp_path: Path, partspec, monkeypatch):
    monkeypatch.setenv("STUB_LINT", '{"counts": {"findings": 4, "unsupported": 1}}')
    assert run.lint_counts(tmp_path, "model.scad", partspec) == (4, 1)


def test_lint_counts_reports_an_absent_unsupported_key_as_unknown_not_zero(
    run, tmp_path: Path, partspec, monkeypatch
):
    monkeypatch.setenv("STUB_LINT", '{"counts": {"findings": 0}}')
    assert run.lint_counts(tmp_path, "model.scad", partspec) == (0, None)


@pytest.mark.parametrize("output", ["not json", '{"no_counts": 1}', '{"counts": {}}', ""])
def test_lint_counts_answers_none_for_output_it_cannot_parse(
    run, tmp_path: Path, partspec, monkeypatch, output
):
    monkeypatch.setenv("STUB_LINT", output)
    assert run.lint_counts(tmp_path, "model.scad", partspec) == (None, None)


def test_run_check_finds_the_report_from_the_line_the_tool_printed(run, tmp_path, partspec):
    (tmp_path / "model.scad").write_text("BROKEN")
    code, output, report, path = run.run_check(tmp_path, "spec.py:part", partspec)
    assert code == 1
    assert "verdict: fail" in output
    assert report == {"verdict": "fail"}
    assert path == tmp_path / "outputs" / "spec-part" / "report.json"


def test_run_check_keeps_the_path_but_no_report_when_the_report_is_malformed(
    run, tmp_path, partspec, monkeypatch
):
    monkeypatch.setenv("STUB_REPORT", "{truncated")
    _code, _output, report, path = run.run_check(tmp_path, "spec.py:part", partspec)
    assert report is None
    assert path is not None and path.exists()


def test_call_agent_reports_a_nonzero_exit_as_a_failure_with_its_stderr(run, tmp_path, agent):
    ok, note = run.call_agent(agent("crash"), tmp_path, "prompt")
    assert not ok
    assert note.startswith("agent exited 3") and "agent fell over" in note


def test_call_agent_reports_a_timeout_rather_than_raising(run, tmp_path, monkeypatch):
    monkeypatch.setattr(run, "AGENT_TIMEOUT_S", 0.2)
    ok, note = run.call_agent(
        f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(5)'", tmp_path, ""
    )
    assert not ok
    assert "timed out" in note


# --- outcome assignment, through run_trial with both stubs ------------------


def test_a_repair_fixed_on_the_first_agent_turn_converges_in_one_turn(
    run, tmp_path, agent, partspec
):
    case = make_case(tmp_path / "cases", "c")
    t = trial(run, tmp_path, case, agent("fix"), partspec)
    assert t.outcome == "converged"
    # Repair counts AGENT turns: check 1 failed, the agent edited, check 2 passed.
    assert t.turns_to_converge == 1
    assert [turn.exit_code for turn in t.turns] == [1, 0]
    assert len(agent.prompts()) == 1


def test_a_repair_that_already_passes_converges_in_zero_turns(run, tmp_path, agent, partspec):
    case = make_case(tmp_path / "cases", "c")
    (case / "model.scad").write_text("FIXED\n")
    t = trial(run, tmp_path, case, agent("noop"), partspec)
    assert (t.outcome, t.turns_to_converge) == ("converged", 0)
    assert agent.prompts() == []


def test_an_agent_that_never_fixes_it_fails_on_the_turn_budget(run, tmp_path, agent, partspec):
    case = make_case(tmp_path / "cases", "c", max_turns=3)
    t = trial(run, tmp_path, case, agent("noop"), partspec)
    assert t.outcome == "failed"
    assert t.turns_to_converge is None
    assert len(t.turns) == 3
    assert t.note == "budget of 3 turns exhausted"
    # The last check is not followed by an agent call the budget cannot use.
    assert len(agent.prompts()) == 2


def test_a_green_run_on_an_edited_contract_is_gamed_not_converged(run, tmp_path, agent, partspec):
    case = make_case(tmp_path / "cases", "c")
    t = trial(run, tmp_path, case, agent("game"), partspec)
    assert t.outcome == "gamed"
    assert t.turns_to_converge is None
    # The check that caught it DID pass: integrity is decided before convergence.
    assert t.turns[-1].exit_code == 0
    assert "frozen" in t.note


def test_deleting_a_frozen_file_is_gamed(run, tmp_path, agent, partspec):
    case = make_case(tmp_path / "cases", "c")
    t = trial(run, tmp_path, case, agent("delete-contract"), partspec)
    assert t.outcome == "gamed"


def test_an_agent_that_crashes_ends_the_trial_as_error(run, tmp_path, agent, partspec):
    case = make_case(tmp_path / "cases", "c")
    t = trial(run, tmp_path, case, agent("crash"), partspec)
    assert t.outcome == "error"
    assert t.turns[-1].agent_ok is False
    assert "agent exited 3" in t.turns[-1].agent_note


def test_a_worsened_verdict_is_noted_but_does_not_change_the_outcome(
    run, tmp_path, agent, partspec
):
    case = make_case(tmp_path / "cases", "c", max_turns=3)
    t = trial(run, tmp_path, case, agent("worsen,noop"), partspec)
    assert t.outcome == "failed"
    assert t.note == "turn 2: verdict worsened to error"


def test_the_trial_never_mutates_the_case_directory(run, tmp_path, agent, partspec):
    case = make_case(tmp_path / "cases", "c")
    before = {p.name: p.read_bytes() for p in case.iterdir()}
    trial(run, tmp_path, case, agent("game"), partspec)
    assert {p.name: p.read_bytes() for p in case.iterdir()} == before


def test_an_authored_model_passing_first_time_converges_in_one_turn(run, tmp_path, agent, partspec):
    case = make_case(tmp_path / "cases-authoring", "a", authoring=True)
    t = trial(run, tmp_path, case, agent("fix"), partspec)
    # Authoring counts the first write as a turn.
    assert (t.outcome, t.turns_to_converge) == ("converged", 1)
    assert t.loc == 1
    assert (t.lint_findings, t.lint_unsupported, t.lint_outcome) == (0, 0, "clean")


def test_an_authoring_agent_that_crashes_on_the_first_write_is_error(
    run, tmp_path, agent, partspec
):
    case = make_case(tmp_path / "cases-authoring", "a", authoring=True)
    t = trial(run, tmp_path, case, agent("crash"), partspec)
    assert t.outcome == "error"
    assert t.turns == []


def test_the_skills_arm_copies_skills_and_says_so_and_control_does_neither(
    run, tmp_path, agent, partspec
):
    case = make_case(tmp_path / "cases-authoring", "a", authoring=True)
    trial(run, tmp_path, case, agent("fix"), partspec, arm="control")
    trial(run, tmp_path, case, agent("fix"), partspec, arm="skills")
    control, skills = agent.prompts()
    assert "skills/" not in control and "skills/" in skills
    assert run.GUIDANCE_NOTE in skills


def test_a_repair_prompt_offers_the_report_only_when_it_parsed(
    run, tmp_path, agent, partspec, monkeypatch
):
    case = make_case(tmp_path / "cases", "c")
    trial(run, tmp_path, case, agent("fix"), partspec)
    assert (
        "The full machine-readable report is at `outputs/spec-part/report.json`"
        in agent.prompts()[0]
    )
    monkeypatch.setenv("STUB_REPORT", "{truncated")
    trial(run, tmp_path, case, agent("fix"), partspec)
    assert "machine-readable report" not in agent.prompts()[1]


# --- main: the results schema, arm filtering, and refusals -----------------


def results(tmp_path: Path) -> dict:
    (path,) = (tmp_path / "results").glob("*/results.json")
    return json.loads(path.read_text())


def test_results_json_carries_the_header_every_trial_and_both_tallies(
    run, tmp_path, agent, partspec
):
    make_case(tmp_path / "cases", "fixable")
    make_case(tmp_path / "cases", "gameable")
    # One agent script for both cases; per-case behaviour comes from the action list.
    rc = run.main(["--agent", agent("game"), "--partspec", partspec, "--trials", "2"])
    assert rc == 0
    payload = results(tmp_path)
    assert set(payload) == {
        "when",
        "agent",
        "arm",
        "partspec",
        "partspec_version",
        "harness_commit",
        "trials",
        "summary",
        "lint",
    }
    assert payload["arm"] == "control"
    assert payload["partspec"] == str(Path(partspec).resolve())
    assert payload["partspec_version"] == "partspec 0.0.0-stub"
    assert list(payload["summary"]) == ["converged", "failed", "gamed", "regressed", "error"]
    assert payload["summary"]["gamed"] == 4
    assert sum(payload["summary"].values()) == len(payload["trials"]) == 4
    assert list(payload["lint"]) == list(run.LINT_OUTCOMES)
    assert payload["lint"]["clean"] == 4
    assert set(payload["trials"][0]) == {
        "case",
        "trial",
        "arm",
        "outcome",
        "turns_to_converge",
        "turns",
        "note",
        "loc",
        "lint_findings",
        "lint_unsupported",
        "lint_outcome",
    }
    assert set(payload["trials"][0]["turns"][0]) == {
        "n",
        "exit_code",
        "verdict",
        "summary",
        "agent_ok",
        "agent_note",
    }


def test_a_harness_exception_is_recorded_as_an_error_trial_not_a_crash(
    run, tmp_path, agent, partspec, monkeypatch
):
    make_case(tmp_path / "cases", "c")

    def boom(*_a, **_k):
        raise RuntimeError("harness fault")

    monkeypatch.setattr(run, "run_trial", boom)
    assert run.main(["--agent", agent("fix"), "--partspec", partspec]) == 0
    (t,) = results(tmp_path)["trials"]
    assert (t["outcome"], t["note"]) == ("error", "RuntimeError: harness fault")


def test_the_skills_arm_runs_authoring_cases_only(run, tmp_path, agent, partspec, capsys):
    make_case(tmp_path / "cases", "repair")
    make_case(tmp_path / "cases-authoring", "author", authoring=True)
    rc = run.main(["--agent", agent("fix"), "--partspec", partspec, "--arm", "skills"])
    assert rc == 0
    assert "skipping: repair" in capsys.readouterr().out
    payload = results(tmp_path)
    assert payload["arm"] == "skills"
    assert [(t["case"], t["arm"]) for t in payload["trials"]] == [("author", "skills")]


def test_the_control_arm_runs_every_case(run, tmp_path, agent, partspec):
    make_case(tmp_path / "cases", "repair")
    make_case(tmp_path / "cases-authoring", "author", authoring=True)
    assert run.main(["--agent", agent("fix"), "--partspec", partspec]) == 0
    assert [t["case"] for t in results(tmp_path)["trials"]] == ["repair", "author"]


def test_the_skills_arm_with_no_authoring_case_refuses(run, tmp_path, agent, partspec):
    make_case(tmp_path / "cases", "repair")
    assert run.main(["--agent", agent("fix"), "--partspec", partspec, "--arm", "skills"]) == 64
    assert agent.prompts() == []


def test_an_unknown_arm_is_refused_at_parse_time(run, tmp_path, agent, partspec):
    make_case(tmp_path / "cases", "repair")
    with pytest.raises(SystemExit) as exc:
        run.main(["--agent", agent("fix"), "--partspec", partspec, "--arm", "no-tool"])
    assert exc.value.code == 2
    assert agent.prompts() == []


def test_an_unmatched_case_is_refused(run, tmp_path, agent, partspec):
    make_case(tmp_path / "cases", "repair")
    assert run.main(["--agent", agent("fix"), "--partspec", partspec, "--case", "nope"]) == 64


def test_a_partspec_that_is_not_one_executable_is_refused_before_any_trial(
    run, tmp_path, agent, partspec
):
    make_case(tmp_path / "cases", "repair")
    assert run.main(["--agent", agent("fix"), "--partspec", f"{partspec} check"]) == 64
    assert agent.prompts() == []
    assert not (tmp_path / "results").exists()


# --- case validation and the free smoke run ---------------------------------


def test_the_committed_cases_validate_and_every_prompt_renders(monkeypatch, capsys):
    """The CI `evals` job runs this same path through the CLI."""
    spec = importlib.util.spec_from_file_location("partspec_evals_run_real", RUN_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert module.main(["--validate"]) == 0, capsys.readouterr().err
    cases = module.load_cases()
    assert cases, "no committed cases were found, so nothing was validated"


def test_no_committed_prompt_carries_the_seeded_defect(monkeypatch):
    """README rule 2: the defect description is recorded for analysis only."""
    spec = importlib.util.spec_from_file_location("partspec_evals_run_real", RUN_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    for d, cfg in module.load_cases():
        defect = cfg.get("defect", {})
        prompt = module.repair_prompt(d, cfg, "output", 1, None)
        for field in ("description", "detected_by", "natural_cheat"):
            if field in defect:
                assert defect[field] not in prompt, f"{cfg['id']} leaks its {field}"


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        ({"froze": ["spec.py"]}, "unknown key 'froze'"),
        ({"frozen": ["spec.py", "gone.py"]}, "frozen file 'gone.py' is not in the case"),
        ({"frozen": []}, "`frozen` must be a non-empty list"),
        ({"target": "spec.py"}, "`target` must be"),
        ({"target": "other.py:part"}, "`target` names 'other.py'"),
        ({"max_turns": 0}, "`max_turns` must be a positive integer"),
        ({"mode": "authorng"}, "`mode` must be absent or 'authoring'"),
    ],
)
def test_validate_case_names_what_is_wrong(run, tmp_path, edit, problem):
    case = make_case(tmp_path / "cases", "c")
    cfg = {"id": "c", "target": "spec.py:part", "frozen": ["spec.py"], **edit}
    found = run.validate_case(case, cfg)
    assert any(problem in p for p in found), found


def test_validate_case_accepts_both_committed_shapes(run, tmp_path):
    repair = make_case(tmp_path / "cases", "r")
    author = make_case(tmp_path / "cases-authoring", "a", authoring=True)
    assert run.validate_case(repair, {"id": "r", "target": "spec.py:part"}) == []
    cfg = {"id": "a", "target": "spec.py:part", "mode": "authoring", "model": "m.scad"}
    assert run.validate_case(author, cfg) == []


def test_an_authoring_case_without_its_task_or_model_is_invalid(run, tmp_path):
    case = make_case(tmp_path / "cases-authoring", "a", authoring=True)
    (case / "TASK.md").unlink()
    found = run.validate_case(case, {"id": "a", "target": "spec.py:part", "mode": "authoring"})
    assert any("TASK.md" in p for p in found) and any("`model`" in p for p in found)


def test_duplicate_case_ids_are_invalid(run, tmp_path):
    make_case(tmp_path / "cases", "same")
    make_case(tmp_path / "cases-authoring", "same", authoring=True)
    assert "duplicate case id 'same'" in run.case_problems(run.load_cases())


def test_validate_exits_nonzero_on_a_broken_case(run, tmp_path, capsys):
    make_case(tmp_path / "cases", "c", froze=["spec.py"])
    assert run.main(["--validate"]) == 1
    assert "unknown key 'froze'" in capsys.readouterr().err


def test_a_run_over_a_broken_case_is_refused_before_any_agent_call(run, tmp_path, agent, partspec):
    make_case(tmp_path / "cases", "c", froze=["spec.py"])
    assert run.main(["--agent", agent("fix"), "--partspec", partspec]) == 1
    assert agent.prompts() == []
    assert not (tmp_path / "results").exists()
