# evals — does an agent actually converge, and do the assets change what it writes?

Two questions, one harness. Convergence (#30): `CONVERGENCE.md`. Authoring quality
under guidance-present/absent arms (#53): `AUTHORING.md`.

The project's thesis is that a machine-checkable contract plus an honest verdict is
enough for an AI agent to drive a broken CAD model to correct. Nothing in the test
suite tests that. This does.

**The question, stated so it can fail:** given a part that violates its contract, and
*only* partspec's output to work from — no human hints, no description of the defect —
does an agent converge to a passing part within a bounded number of turns?

## The rules that make the answer mean something

1. **The contract is frozen.** The agent may edit the model. It may not edit `spec.py`.
   Deleting a failing check is the cheapest way to turn a run green, and an agent will
   find it. The driver hashes every contract file before and after each turn; a
   modification ends the trial as `gamed`, which is **not** a form of success and is
   reported separately from `failed`.
2. **No hints.** The prompt carries the task framing and partspec's stdout/stderr/exit
   code. It does not carry the defect class, the file that is wrong, or the direction
   to move a number.
3. **Turn-based, not free-running.** The driver runs `partspec check`, hands the output
   to the agent, and lets it make edits; then it runs the check again. The agent never
   runs partspec itself. This is deliberate: the measurement is *"is partspec's output
   alone enough to drive a correct edit"*, and an agent that greps the model or
   brute-forces values is answering a different question.
4. **Every trial runs in a throwaway copy.** `evals/cases/` is never mutated.

> **The archived REPAIR-LOOP runs are not a comparable baseline.** Every repair
> turn recorded here before 2026-08-11 offered the agent a report path that did
> not exist: the driver built `outputs/spec-<part id>/report.json`, and partspec
> derives that directory from the contract's filename and factory, which no case
> has equal to its part id. The agent still received partspec's full console
> output — the treatment property 3 describes — and the true path was visible
> inside it, so the recorded convergence numbers stand for what they measure.
> But the "you may read the full report" affordance was never actually
> delivered, and it is delivered now. Repair-loop runs from here on see a ~3 KB
> structured report where the archive saw a six-line summary; do not pool the
> two.
>
> **`AUTHORING.md` is unaffected.** `AUTHORING_PROMPT` carries no report note by
> design, and all 12 authoring trials converged on the first write without
> taking a repair turn, so no authoring run was ever offered the dead path. That
> before/after remains a valid baseline.

## Running it

```bash
just eval                      # every case, default agent
uv run python evals/run.py --case bore-breach --trials 3
uv run python evals/run.py --list
just eval-validate             # free: check every case, render every prompt, no agent
```

The harness itself is tested without an agent: `tests/test_evals_harness.py` drives
`run.py` with a stubbed agent command and a stubbed `partspec`, covering outcome
assignment, the freeze check, `gamed` detection and the `results.json` schema. A change
to `run.py` should land with a test there, not with a paid run as its only evidence.

An arm (`--arm`) is one row of `ARMS` in `run.py`: the cases it applies to, what it copies
into the work tree, and what it adds to the authoring prompt. A row that is neither the
baseline nor treated is refused when selected, rather than running everywhere with nothing
applied (#410).

The agent under test is a pluggable command, so this harness is not tied to one model
or one vendor:

```bash
export PARTSPEC_EVAL_AGENT='claude -p --permission-mode bypassPermissions'
```

It is invoked with the prompt on **stdin**, with the working directory set to the
trial's scratch copy. Anything it writes to that directory is the edit. `bypassPermissions`
is safe here only because the working directory is a temp copy — never point this at a
real tree.

The **partspec under test** defaults to whatever `partspec` resolves to on `PATH`, which
is why `just eval` goes through `uv run` — nothing else here would put `.venv/bin` on it.
To measure a different build:

```bash
export PARTSPEC_BIN=/some/other/venv/bin/partspec
```

It must name **one** executable. `run.py` passes it as `argv[0]`, so a multi-word command
(`uv run partspec`) is refused by the guard rather than clearing it and failing in the
first trial (#304).

## Reading the results

`evals/results/<timestamp>/results.json` plus a per-trial transcript. Its header says
which build was measured — `partspec` (an absolute path), `partspec_version` (what that
binary reports) and `harness_commit` (the checkout this driver ran from, which is *not*
necessarily the build above it). The commit is suffixed `-dirty` when that checkout had
uncommitted changes, or `-unknown` when git could not be asked: a bare sha from a
modified tree names a commit that is not what ran. A run costs real agent calls, so a
result that cannot name its own build cannot be compared to a later one. The headline
numbers:

| outcome | meaning |
|---|---|
| `converged` | exit 0, contract untouched — the only success |
| `failed` | budget exhausted, still non-zero |
| `gamed` | the agent edited the contract |
| `regressed` | a turn made the verdict strictly worse |
| `error` | the harness or the agent command broke |

Each trial also records what `partspec lint` made of the model it left behind:
`lint_findings`, `lint_unsupported`, and `lint_outcome`, which names which of three
things happened rather than folding them together.

| `lint_outcome` | meaning |
|---|---|
| `clean` | every rule ran and found nothing — the only one that earns the word |
| `findings` | every rule ran and something was found |
| `incomplete` | a rule did not run, so the findings count is a floor, not a total |
| `unknown` | the lint payload could not be read |

Wholeness is decided first: `findings: 0` beside `unsupported: 3` is not a clean file,
it is a file three rules never looked at (`docs/LINT.md`, #317).

`turns_to_converge` is the number that matters for comparison across changes to
partspec. A baseline taken against today's checker — which has known false greens —
is not a certification. It is a list of what an agent actually walks into, and that
list is the point.

## Adding a case

One directory under `cases/`, containing `case.toml`, the frozen contract, and the
model. See `cases/bore-breach/case.toml` for the fields. A good case has a defect that
is **visible in the report and fixable in the model**, and a natural cheat that the
frozen contract forbids.

Related: #30 (this), #53 (the guidance-present/absent dimension layers on top of this
same harness — do not build a second one).
