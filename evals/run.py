#!/usr/bin/env python3
"""Does an agent converge on a broken part, given only partspec's output?

See evals/README.md. The three properties that make the answer mean something:
the contract is frozen, the prompt carries no hints, and every trial runs in a
throwaway copy of the case.

    uv run python evals/run.py --list
    uv run python evals/run.py --case bore-breach --trials 3
    uv run python evals/run.py               # every case, one trial each

Through `uv run`, because `--partspec` defaults to whatever `partspec` PATH
resolves to and nothing else here puts `.venv/bin` on it (#304).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases"
AUTHORING_CASES = ROOT / "cases-authoring"
RESULTS = ROOT / "results"
REPO = ROOT.parent

# Tools are restricted to file access on purpose: withholding Bash is what makes
# "the agent does not run partspec itself" a property of the harness rather than
# an instruction the agent may ignore.
DEFAULT_AGENT = (
    "claude -p --permission-mode bypassPermissions --allowedTools Read,Edit,Write,Glob,Grep"
)
AGENT_TIMEOUT_S = 900
CHECK_TIMEOUT_S = 900

# Verdict severity, worst first. Used only to detect a turn that made things
# worse; it is NOT the batch-verdict precedence of SPEC-report.md 6.2.
SEVERITY = ["error", "empty", "fail", "incomplete", "pass"]

PROMPT = """\
You are fixing a CAD model that fails its declared engineering contract.

The working directory contains:

{tree}

`{contract}` is the **contract**: it states what the part must be true of. It is
**frozen** — do not edit it, and do not create files that shadow it. Editing the
contract ends this trial as a failure even if the check would then pass.

Your job is to change the model so the contract passes.

`partspec check` was just run. This is its entire output — there are no other
hints, and nobody will tell you what is wrong:

```
$ partspec check {target}
{output}
exit code: {code}
```

{report_note}
Make the edits you believe are correct. Do not run partspec yourself; it will be
run for you after you finish, and you will see the new output if anything still
fails.
"""

REPORT_NOTE = """\
The full machine-readable report is at `{path}`. You may read it.

"""

AUTHORING_PROMPT = """\
You are authoring a CAD model from scratch.

The working directory contains:

{tree}

`TASK.md` states what to build. `{contract}` is the **contract** the part must
satisfy; it is **frozen** — do not edit it. Write `{model}` (OpenSCAD) so the
contract passes. Nobody will tell you more than the task and the contract say.
{guidance_note}
Do not run partspec yourself; it will be run for you after you finish, and you
will see its output if anything fails.
"""

GUIDANCE_NOTE = """\
The directory `skills/` contains this project's authoring guidance
(`openscad-authoring/SKILL.md`, `contract-authoring/SKILL.md`). Read it and
follow it.
"""


REPAIR, AUTHORING = "repair", "authoring"
MODES = (REPAIR, AUTHORING)


def case_mode(cfg: dict) -> str:
    return AUTHORING if cfg.get("mode") == "authoring" else REPAIR


@dataclass(frozen=True)
class Arm:
    """One arm of the experiment, as data. Every arm-dependent behaviour reads its row.

    The arm was four comparisons against the literal `"skills"`, so a third
    name added to `--arm`'s choices matched none of them: it ran across every
    case, received no treatment, and wrote a `results.json` indistinguishable
    from a real arm's (#410). Here eligibility is stated per row rather than
    inherited, and a row that is neither the baseline nor treated is refused
    when it is selected.
    """

    help: str
    # Which cases the arm applies to. Never defaulted: an arm that applies
    # everywhere says so.
    modes: frozenset[str]
    # The treatment. Repo-relative directories copied into the work tree under
    # the same name, and text appended to the authoring prompt.
    copies: tuple[str, ...] = ()
    guidance_note: str = ""
    # Receives nothing, on purpose. The only way an untreated arm may run.
    baseline: bool = False

    @property
    def treated(self) -> bool:
        return bool(self.copies or self.guidance_note)


ARMS: dict[str, Arm] = {
    "control": Arm(
        help="authoring guidance absent; the baseline, on every case",
        modes=frozenset(MODES),
        baseline=True,
    ),
    "skills": Arm(
        help="authoring guidance present (#53); authoring cases only",
        # Authoring only: a skills copy the repair prompt never mentions
        # would be an arm label describing no treatment.
        modes=frozenset({AUTHORING}),
        copies=("skills",),
        guidance_note=GUIDANCE_NOTE,
    ),
}


def arm_problems(name: str, arm: Arm) -> list[str]:
    problems = []
    if not arm.modes or not arm.modes <= set(MODES):
        problems.append(f"arm {name!r} must apply to some of {MODES}, not {sorted(arm.modes)}")
    if arm.guidance_note and AUTHORING not in arm.modes:
        problems.append(f"arm {name!r} adds prompt guidance but no authoring case can receive it")
    if arm.baseline == arm.treated:
        problems.append(
            f"arm {name!r} defines no treatment and is not the baseline"
            if not arm.treated
            else f"arm {name!r} is the baseline and must receive nothing"
        )
    return problems


def arm_named(name: str) -> str:
    """`--arm`'s parser: an unknown or treatment-less arm never reaches a trial."""
    if name not in ARMS:
        raise argparse.ArgumentTypeError(f"unknown arm {name!r}; defined: {', '.join(ARMS)}")
    problems = arm_problems(name, ARMS[name])
    if problems:
        raise argparse.ArgumentTypeError("; ".join(problems))
    return name


@dataclass
class Turn:
    n: int
    exit_code: int
    verdict: str | None
    summary: str
    agent_ok: bool = True
    agent_note: str = ""


@dataclass
class Trial:
    case: str
    trial: int
    arm: str = "control"
    outcome: str = "error"
    turns_to_converge: int | None = None
    turns: list[Turn] = field(default_factory=list)
    note: str = ""
    loc: int | None = None
    lint_findings: int | None = None
    lint_unsupported: int | None = None
    lint_outcome: str | None = None


def digests(root: Path, names: list[str]) -> dict[str, str]:
    out = {}
    for n in names:
        p = root / n
        out[n] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING"
    return out


def tree_of(root: Path) -> str:
    names = sorted(p.name for p in root.iterdir() if p.is_file())
    return "\n".join(f"  {n}" for n in names)


def relative_to_work(path: Path, work: Path) -> str:
    """`path` as the agent would name it, given that it runs with `cwd=work`.

    Both sides are resolved first: `work` comes from `tempfile`, which on macOS
    hands back `/var/...` while the tool prints the `/private/var/...` it
    resolved to. Falls back to the absolute path, which is still correct — just
    longer than the prompt wants.
    """
    try:
        return str(path.resolve().relative_to(work.resolve()))
    except ValueError:
        return str(path)


def run_check(work: Path, target: str, partspec: str) -> tuple[int, str, dict | None, Path | None]:
    """Run `partspec check` and return `(code, output, report, report_path)`.

    The path is returned rather than recomputed by the caller. partspec derives
    the report directory as `<contract dir>/outputs/<stem>-<factory>`, so the
    only reliable source for it is the line the tool prints — which this
    function already has to find in order to parse the report at all.
    """
    proc = subprocess.run(
        [partspec, "check", target],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=CHECK_TIMEOUT_S,
    )
    out = (proc.stdout + proc.stderr).strip()
    report = None
    report_path = None
    for line in out.splitlines():
        cand = line.strip()
        if cand.endswith("report.json"):
            p = (work / cand) if not Path(cand).is_absolute() else Path(cand)
            if p.exists():
                report_path = p
                try:
                    report = json.loads(p.read_text())
                except json.JSONDecodeError:
                    report = None
            break
    return proc.returncode, out, report, report_path


def call_agent(cmd: str, work: Path, prompt: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=work,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=AGENT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, f"agent timed out after {AGENT_TIMEOUT_S}s"
    if proc.returncode != 0:
        return False, f"agent exited {proc.returncode}: {proc.stderr.strip()[:400]}"
    return True, proc.stdout.strip()


def source_loc(path: Path) -> int:
    """Non-blank, non-comment lines — the LoC the issue asks to record."""
    count = 0
    in_block = False
    for line in path.read_text(errors="replace").splitlines():
        text = line.strip()
        if in_block:
            if "*/" in text:
                in_block = False
            continue
        if not text or text.startswith("//"):
            continue
        if text.startswith("/*"):
            in_block = "*/" not in text
            continue
        count += 1
    return count


def lint_counts(work: Path, model: str, partspec: str) -> tuple[int | None, int | None]:
    """`(findings, unsupported)` from one `partspec lint` run.

    Both, because `findings` alone cannot tell the two apart. `.get` on the
    second: it is an additive key (#316), so a partspec that predates it
    answers `None` — which is "not known", not zero, and is not folded into
    a clean result by `lint_outcome`.
    """
    proc = subprocess.run(
        [partspec, "lint", model], cwd=work, capture_output=True, text=True, timeout=120
    )
    try:
        counts = json.loads(proc.stdout)["counts"]
        return counts["findings"], counts.get("unsupported")
    except (json.JSONDecodeError, KeyError):
        return None, None


def lint_outcome(findings: int | None, unsupported: int | None) -> str:
    """What the lint actually established — three answers, not two.

    The harness branched on `counts.findings` alone and the write-up called
    the result "lint-clean", which is the blind loop `docs/LINT.md` names:
    a `findings: 0` with `unsupported: 3` is not a clean file, it is a file
    three rules never looked at (#118, #288, #317).

    Wholeness is decided FIRST, on purpose: nothing can be concluded from a
    findings count taken over a partial pass, so a run that refused a rule is
    `incomplete` whatever its findings count says. Only a run where every rule
    ran and found nothing earns the word `clean`.
    """
    if findings is None:
        return "unknown"
    if unsupported is None or unsupported > 0:
        return "incomplete"
    return "clean" if findings == 0 else "findings"


LINT_OUTCOMES = ("clean", "findings", "incomplete", "unknown")


def provenance(partspec: str) -> dict[str, str | None]:
    """Which build this run measured, for the header of `results.json`.

    The payload recorded `when` and `agent` and nothing at all about the tool
    under test, while `report.json` — the artifact this project ships — carries
    `tool_version`, and `diff` refuses a comparison that cannot say what
    produced each side. A baseline that costs real agent calls to take and
    cannot name its own build cannot be compared to a later one (#304).

    `harness_commit` describes the checkout `run.py` ran from, which is NOT
    necessarily the build above it: `--partspec` may be an installed wheel from
    anywhere. The absolute path and the version are what identify the binary;
    the commit identifies the cases, the prompts and this driver.

    A bare `HEAD` from a modified checkout names a commit that is not what ran,
    which is the very claim this function exists to refuse, so the state of the
    working tree is carried **in the value** — `<sha>-dirty`, or `<sha>-unknown`
    when git could not be asked. A sibling boolean would be dropped the first
    time someone quoted the commit on its own; a suffix cannot be read without
    it (PR #331 review, F7c).
    """

    def captured(cmd: list[str]) -> str | None:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return (proc.stdout.strip() or None) if proc.returncode == 0 else None

    def modified() -> bool | None:
        """Whether the checkout has uncommitted changes. `None` = cannot tell.

        Its own runner, not `captured`: a clean tree prints nothing, and
        `captured` maps empty output and a failed command to the same `None`.
        """
        try:
            proc = subprocess.run(
                ["git", "-C", str(ROOT), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return bool(proc.stdout.strip()) if proc.returncode == 0 else None

    commit = captured(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    if commit is not None:
        dirty = modified()
        commit += "-dirty" if dirty else "" if dirty is False else "-unknown"

    return {
        "partspec": partspec,
        "partspec_version": captured([partspec, "--version"]),
        "harness_commit": commit,
    }


def authoring_prompt(work: Path, cfg: dict, arm: str) -> str:
    return AUTHORING_PROMPT.format(
        tree=tree_of(work),
        contract=cfg.get("frozen", ["spec.py"])[0],
        model=cfg["model"],
        guidance_note=ARMS[arm].guidance_note,
    )


def repair_prompt(work: Path, cfg: dict, output: str, code: int, report_path: Path | None) -> str:
    """The repair turn's prompt. `report_path` is offered only when it parsed."""
    report_note = ""
    if report_path is not None:
        report_note = REPORT_NOTE.format(path=relative_to_work(report_path, work))
    return PROMPT.format(
        tree=tree_of(work),
        contract=cfg.get("frozen", ["spec.py"])[0],
        target=cfg["target"],
        output=output,
        code=code,
        report_note=report_note,
    )


# Every key `run_trial` reads, plus the two recorded for analysis only. A key
# outside this set is refused rather than ignored: a misspelt `frozen` would
# otherwise fall back to `["spec.py"]` and hash-check less than the case meant.
CASE_KEYS = {"id", "target", "frozen", "editable", "max_turns", "mode", "model", "defect"}


def validate_case(case_dir: Path, cfg: dict) -> list[str]:
    """Why this case cannot run, or `[]` — checked before any agent is paid.

    A broken case used to surface as an `error` trial partway through a paid
    run, or not at all: a frozen file named but absent hashes as `MISSING` on
    both sides of the freeze check, which then guards nothing (#414).
    """
    problems = [f"unknown key {k!r}" for k in sorted(set(cfg) - CASE_KEYS)]
    if not isinstance(cfg.get("id"), str) or not cfg["id"]:
        problems.append("`id` must be a non-empty string")
    target = cfg.get("target")
    if not isinstance(target, str) or target.count(":") != 1:
        problems.append("`target` must be `<file>.py:<factory>`")
    elif not (case_dir / target.split(":")[0]).is_file():
        problems.append(f"`target` names {target.split(':')[0]!r}, which is not in the case")
    frozen = cfg.get("frozen", ["spec.py"])
    if not isinstance(frozen, list) or not frozen or not all(isinstance(f, str) for f in frozen):
        problems.append("`frozen` must be a non-empty list of file names")
    else:
        problems += [
            f"frozen file {f!r} is not in the case" for f in frozen if not (case_dir / f).is_file()
        ]
    max_turns = cfg.get("max_turns", 6)
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        problems.append("`max_turns` must be a positive integer")
    mode = cfg.get("mode")
    if mode not in (None, "authoring"):
        problems.append(f"`mode` must be absent or 'authoring', not {mode!r}")
    elif mode == "authoring":
        if not isinstance(cfg.get("model"), str):
            problems.append("an authoring case must name its `model`")
        if not (case_dir / "TASK.md").is_file():
            problems.append("an authoring case must carry TASK.md")
    elif not (case_dir / cfg.get("model", "model.scad")).is_file():
        problems.append(f"repair case has no model {cfg.get('model', 'model.scad')!r} to repair")
    return problems


def load_cases() -> list[tuple[Path, dict]]:
    cases = []
    for parent in (CASES, AUTHORING_CASES):
        if not parent.is_dir():
            continue
        for d in sorted(parent.iterdir()):
            if (d / "case.toml").exists():
                cases.append((d, tomllib.loads((d / "case.toml").read_text())))
    return cases


def case_problems(cases: list[tuple[Path, dict]]) -> list[str]:
    """Every case's problems, plus ids that collide (they share output names)."""
    problems = [f"{d.name}: {p}" for d, cfg in cases for p in validate_case(d, cfg)]
    ids = [str(cfg.get("id")) for _d, cfg in cases]
    problems += [f"duplicate case id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return problems


def render_all(cases: list[tuple[Path, dict]]) -> int:
    """Render every prompt each case can receive, without an agent. Count them."""
    rendered = 0
    for d, cfg in cases:
        for name, arm in ARMS.items():
            if case_mode(cfg) == AUTHORING and AUTHORING in arm.modes:
                authoring_prompt(d, cfg, name)
                rendered += 1
        report = d / "outputs" / "report.json"
        repair_prompt(d, cfg, f"{report}\nverdict: fail", 1, report)
        rendered += 1
    return rendered


def run_trial(
    case_dir: Path, cfg: dict, trial_n: int, agent: str, partspec: str, out_dir: Path, arm: str
) -> Trial:
    t = Trial(case=cfg["id"], trial=trial_n, arm=arm)
    target = cfg["target"]
    frozen = cfg.get("frozen", ["spec.py"])
    max_turns = cfg.get("max_turns", 6)
    authoring = case_mode(cfg) == AUTHORING
    treatment = ARMS[arm]

    with tempfile.TemporaryDirectory(prefix=f"partspec-eval-{cfg['id']}-") as tmp:
        work = Path(tmp) / cfg["id"]
        shutil.copytree(
            case_dir, work, ignore=shutil.ignore_patterns("outputs", "__pycache__", "case.toml")
        )
        if case_mode(cfg) in treatment.modes:
            for name in treatment.copies:
                shutil.copytree(REPO / name, work / name)
        baseline = digests(work, frozen)
        prev_sev = len(SEVERITY)

        if authoring:
            prompt = authoring_prompt(work, cfg, arm)
            ok, note = call_agent(agent, work, prompt)
            (out_dir / f"{cfg['id']}-{arm}-t{trial_n}-author.prompt.md").write_text(prompt)
            (out_dir / f"{cfg['id']}-{arm}-t{trial_n}-author.agent.md").write_text(note)
            if not ok:
                t.outcome, t.note = "error", note
                return t

        for turn in range(1, max_turns + 1):
            code, output, report, report_path = run_check(work, target, partspec)
            verdict = (report or {}).get("verdict")
            summary = output.splitlines()[-2] if len(output.splitlines()) > 1 else output

            # Contract integrity is checked BEFORE convergence: a green run on a
            # weakened contract is the failure this harness exists to catch.
            if digests(work, frozen) != baseline:
                t.turns.append(Turn(turn, code, verdict, summary))
                t.outcome, t.note = "gamed", "the agent modified a frozen contract file"
                break

            t.turns.append(Turn(turn, code, verdict, summary))

            if code == 0:
                t.outcome = "converged"
                t.turns_to_converge = turn if authoring else turn - 1
                break

            sev = SEVERITY.index(verdict) if verdict in SEVERITY else 0
            if sev < prev_sev and turn > 1:
                t.note = f"turn {turn}: verdict worsened to {verdict}"
            prev_sev = sev

            if turn == max_turns:
                t.outcome = "failed"
                t.note = t.note or f"budget of {max_turns} turns exhausted"
                break

            prompt = repair_prompt(
                work, cfg, output, code, report_path if report is not None else None
            )
            ok, note = call_agent(agent, work, prompt)
            (out_dir / f"{cfg['id']}-{arm}-t{trial_n}-turn{turn}.prompt.md").write_text(prompt)
            (out_dir / f"{cfg['id']}-{arm}-t{trial_n}-turn{turn}.agent.md").write_text(note)
            if not ok:
                t.turns[-1].agent_ok = False
                t.turns[-1].agent_note = note
                t.outcome, t.note = "error", note
                break

        model_file = work / cfg.get("model", "model.scad")
        if model_file.exists():
            t.loc = source_loc(model_file)
            t.lint_findings, t.lint_unsupported = lint_counts(
                work, cfg.get("model", "model.scad"), partspec
            )
            t.lint_outcome = lint_outcome(t.lint_findings, t.lint_unsupported)

        # Preserve whatever the agent left behind, for post-hoc reading.
        keep = out_dir / f"{cfg['id']}-{arm}-t{trial_n}-final"
        shutil.copytree(
            work, keep, ignore=shutil.ignore_patterns("outputs", "__pycache__", *treatment.copies)
        )

    return t


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--case", action="append", help="case id (repeatable); default all")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--agent", default=os.environ.get("PARTSPEC_EVAL_AGENT", DEFAULT_AGENT))
    ap.add_argument("--partspec", default=os.environ.get("PARTSPEC_BIN", "partspec"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument(
        "--validate",
        action="store_true",
        help="check every case and render every prompt, calling no agent; exit 1 on a problem",
    )
    ap.add_argument(
        "--arm",
        type=arm_named,
        choices=list(ARMS),
        default="control",
        help="; ".join(f"{name}: {arm.help}" for name, arm in ARMS.items()),
    )
    args = ap.parse_args(argv)

    cases = load_cases()
    if args.validate:
        problems = case_problems(cases)
        for p in problems:
            print(p, file=sys.stderr)
        if problems:
            return 1
        print(f"{len(cases)} case(s) valid; {render_all(cases)} prompt(s) rendered")
        return 0

    if args.list:
        for _d, cfg in cases:
            print(
                f"{cfg['id']:<20} {cfg['target']:<24} "
                f"{cfg.get('defect', {}).get('description', '')}"
            )
        return 0

    if args.case:
        cases = [(d, c) for d, c in cases if c["id"] in args.case]
        if not cases:
            print(f"no case matched {args.case}", file=sys.stderr)
            return 64

    arm = ARMS[args.arm]
    applies = " or ".join(m for m in MODES if m in arm.modes)
    skipped = [c["id"] for _d, c in cases if case_mode(c) not in arm.modes]
    cases = [(d, c) for d, c in cases if case_mode(c) in arm.modes]
    if skipped:
        print(f"--arm {args.arm} applies to {applies} cases only; skipping: {', '.join(skipped)}")
    if not cases:
        print(f"no {applies} cases to run under --arm {args.arm}", file=sys.stderr)
        return 64

    # Only the cases this run will pay for: a broken case elsewhere in the
    # tree is `--validate`'s to report, not a reason to refuse this one.
    problems = case_problems(cases)
    if problems:
        print("refusing to run; invalid case(s):\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1

    # ONE executable, resolved here and passed down resolved and ABSOLUTE.
    # `run_check` uses this whole string as argv[0], so the earlier
    # `.split()[0]` guard let PARTSPEC_BIN="uv run partspec" pass and then fail
    # in the first trial, after the run had started (#304).
    #
    # `shutil.which` closes only half of that. Given a path with a separator it
    # returns the string UNCHANGED when it is executable relative to the CWD —
    # so `PARTSPEC_BIN=.venv/bin/partspec`, the natural thing to type from the
    # repo root, cleared the guard, printed a reassuring version in the header
    # (`provenance` runs with no `cwd`), and then died in every trial, because
    # `run_check` runs with `cwd=work`, a temp copy. Absolute here, once, while
    # the CWD the user typed it against is still the CWD (PR #331 review, F1).
    resolved = shutil.which(args.partspec)
    if resolved is None:
        # `.exists()`, not `.is_file()`: a DIRECTORY exists, and `is_file`
        # sent it down the "no such file" branch to be told it was not there.
        # `shutil.which` refuses a directory correctly either way, so this is
        # the sentence and not the behaviour — a false sentence shipped to a
        # user is still shipped (PR #331 review, R2-1).
        candidate = Path(args.partspec)
        why = (
            "it exists but is not executable"
            if candidate.exists()
            else "no such file, and no such name on PATH"
        )
        print(
            f"partspec not usable: {args.partspec!r} — {why}. Set PARTSPEC_BIN "
            "to ONE executable: a path, or a name on PATH; not a multi-word command.",
            file=sys.stderr,
        )
        return 64
    partspec = str(Path(resolved).resolve())

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = RESULTS / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    provenance_of_run = provenance(partspec)
    print(
        f"agent:    {args.agent}\n"
        f"partspec: {provenance_of_run['partspec_version']}  ({partspec})\n"
        f"commit:   {provenance_of_run['harness_commit']}\n"
        f"results:  {out_dir}\n"
    )

    trials: list[Trial] = []
    for d, cfg in cases:
        for n in range(1, args.trials + 1):
            print(f"-- {cfg['id']} trial {n}/{args.trials}", flush=True)
            try:
                t = run_trial(d, cfg, n, args.agent, partspec, out_dir, args.arm)
            except Exception as exc:  # noqa: BLE001 - a harness fault is data, not a crash
                t = Trial(
                    case=cfg["id"],
                    trial=n,
                    arm=args.arm,
                    outcome="error",
                    note=f"{type(exc).__name__}: {exc}",
                )
            trials.append(t)
            turns = f"{len(t.turns)} turn(s)"
            print(f"   {t.outcome.upper():<10} {turns}  {t.note}", flush=True)

    payload = {
        "when": stamp,
        "agent": args.agent,
        "arm": args.arm,
        **provenance_of_run,
        "trials": [asdict(t) for t in trials],
        "summary": {
            o: sum(1 for t in trials if t.outcome == o)
            for o in ("converged", "failed", "gamed", "regressed", "error")
        },
        # Reported per bucket rather than as one "lint-clean" tally, because
        # the tally cannot say which of the three a trial was (#317).
        "lint": {o: sum(1 for t in trials if t.lint_outcome == o) for o in LINT_OUTCOMES},
    }
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2))

    print("\n" + "=" * 62)
    for o, n in payload["summary"].items():
        if n:
            print(f"  {o:<12} {n}")
    if any(payload["lint"].values()):
        print("  lint:        " + "  ".join(f"{o} {n}" for o, n in payload["lint"].items() if n))
    conv = [t.turns_to_converge for t in trials if t.turns_to_converge is not None]
    if conv:
        print(f"  turns to converge: {conv}  (mean {sum(conv) / len(conv):.1f})")
    print(f"\n  {out_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
