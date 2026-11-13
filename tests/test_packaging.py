"""What the published artifact promises, held against what it contains.

The publish surface is the one place this project's thesis could fail without
any test noticing, because nothing else in the suite installs the wheel or
reads the release path. Two properties here were actually wrong: a typed
package that shipped no type marker, and a release workflow whose entire
safety argument rested on a convention it did not enforce.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text())
GATE = REPO / "scripts" / "assert_tag_on_main.sh"


def _live_lines(path: Path) -> str:
    """A workflow with comment lines removed.

    A grep over YAML cannot tell a live step from prose about one: deleting
    the gate step while leaving its words in a comment passed the first
    version of these tests.
    """
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def test_the_package_ships_its_type_marker():
    """PEP 561: without `py.typed`, a downstream type checker does not check
    partspec *less* — it skips the package entirely and reports nothing.

    Measured before the marker existed, with a deliberate type error in a
    one-line consumer against the installed wheel:

        without:  Skipping analyzing "partspec": module is installed, but
                  missing library stubs or py.typed marker
        with:     error: Incompatible types in assignment

    The consumer's real error was not reported at all. That is this project's
    own thesis — silence reading as success — on its PyPI surface.
    """
    assert (REPO / "src" / "partspec" / "py.typed").is_file()


# ---------------------------------------------------------------------------
# the release gate, exercised rather than grepped
# ---------------------------------------------------------------------------


def _repo_with_history(root: Path) -> tuple[str, str]:
    """A throwaway git repo: returns (commit on main, commit off main)."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("init", "--quiet", "--initial-branch=main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (root / "f").write_text("1\n")
    git("add", "f")
    git("commit", "--quiet", "-m", "one")
    on_main = git("rev-parse", "HEAD")

    git("checkout", "--quiet", "-b", "sidebranch")
    (root / "f").write_text("2\n")
    git("commit", "--quiet", "-am", "two")
    off_main = git("rev-parse", "HEAD")
    git("checkout", "--quiet", "main")
    return on_main, off_main


def _run_gate(root: Path, commit: str, main_ref: str = "main") -> subprocess.CompletedProcess:
    return subprocess.run([str(GATE), commit, main_ref], cwd=root, capture_output=True, text=True)


def test_the_release_gate_publishes_a_commit_on_main(tmp_path: Path):
    on_main, _ = _repo_with_history(tmp_path)
    assert _run_gate(tmp_path, on_main).returncode == 0


def test_the_release_gate_blocks_a_commit_that_is_not_on_main(tmp_path: Path):
    """The hole this closes: `release.yml` runs no tests, so main's `ok` gate
    is the only thing between a commit and PyPI. A tag pointing anywhere else
    published code no gate ever saw.

    Exercised against a real repository rather than grepped out of the YAML,
    because a grep proves a string is present, not that anything blocks —
    dropping one `!` from the old inline version left it green and inert.
    """
    _, off_main = _repo_with_history(tmp_path)
    result = _run_gate(tmp_path, off_main)
    assert result.returncode == 1
    assert f"{off_main} is not on main" in result.stdout


def test_the_release_gate_on_the_shape_production_actually_uses(tmp_path: Path):
    """Every other fixture here names the ref `main`; production passes
    `origin/main`, a remote-tracking ref. The combination that matters most —
    resolvable origin/main AND true ancestry — was the one no test covered,
    which would have made release day its first execution.
    """
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    on_main, off_main = _repo_with_history(upstream)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", str(upstream), str(clone)], check=True)
    assert _run_gate(clone, on_main, "origin/main").returncode == 0
    assert _run_gate(clone, off_main, "origin/main").returncode == 1


def test_the_release_gate_refuses_rather_than_assumes_when_it_cannot_tell(tmp_path: Path):
    """A shallow checkout has no `origin/main` to compare against. Answering
    "fine" there would defeat the gate exactly when it is least able to
    judge, so it fails closed and names the cause."""
    on_main, _ = _repo_with_history(tmp_path)
    result = _run_gate(tmp_path, on_main, main_ref="origin/main")
    assert result.returncode == 1
    assert "cannot resolve" in result.stdout
    assert "fetch-depth: 0" in result.stdout


def test_the_release_workflow_calls_the_gate_and_gives_it_the_history_it_needs():
    """The gate itself is exercised above; this holds the wiring.

    Comment lines are stripped first, because a grep over YAML cannot tell a
    live step from prose about one — deleting the step while leaving the
    words in a comment passed the first version of this test.
    """
    live = _live_lines(REPO / ".github" / "workflows" / "release.yml")

    # Anchored to the whole line. An unanchored match is satisfied by a call
    # ending `|| true`, which is one token from inert — the same one-character
    # neutering the gate was moved into a script to prevent, relocated to the
    # call site.
    assert re.search(
        r'^\s*(?:run: )?scripts/assert_tag_on_main\.sh "\$GITHUB_SHA" origin/main\s*$',
        live,
        re.M,
    ), "the gate must be called, unqualified, with the tagged commit and main"
    assert "continue-on-error" not in live, "a gate that cannot fail the job is not a gate"
    assert "fetch-depth: 0" in live, "ancestry cannot be checked against a shallow clone"
    assert "does not match version" in live, "the tag must match the declared version"
    assert re.search(r"^\s*needs: \[build\]", live, re.M), (
        "publish must depend on the job that runs the gate"
    )


def test_the_workflows_declare_their_permissions_and_serialise_releases():
    release = _live_lines(REPO / ".github" / "workflows" / "release.yml")
    ci = _live_lines(REPO / ".github" / "workflows" / "ci.yml")
    for name, text in (("release.yml", release), ("ci.yml", ci)):
        assert re.search(r"^permissions:\n  contents: read$", text, re.M), (
            f"{name} must declare read-only permissions rather than inherit a repo setting"
        )
    assert re.search(r"^  group: release$", release, re.M), (
        "one release at a time across ALL tags; `release-${{ github.ref }}` is per-tag "
        "and serialises nothing between two different versions"
    )


def test_every_pypi_publish_action_is_pinned_to_a_digest():
    """The one action holding the OIDC identity for PyPI. `@release/v1` is a
    mutable branch: whatever it points at on the day of a release is what runs
    with permission to publish.

    Every occurrence, not the first — checking only `re.search` let a second,
    unpinned publish step be appended below the pinned one.
    """
    workflow = (REPO / ".github" / "workflows" / "release.yml").read_text()
    uses = re.findall(r"uses:\s*pypa/gh-action-pypi-publish@(\S+)", workflow)
    assert uses, "the publish step must still exist"
    unpinned = [ref for ref in uses if not re.fullmatch(r"[0-9a-f]{40}", ref)]
    assert not unpinned, f"publish actions must be SHA-pinned, not {unpinned}"


def test_every_action_in_the_release_workflow_is_pinned_to_an_exact_ref():
    """The claim the `setup-uv` comment makes about its neighbours, enforced.

    That comment justified its exact pin by saying `@v9` would fail "the
    floating-major form every other action here uses" — and no action in the
    file used one: the rest were `@v7.0.1`, `@v7.0.1`, `@v8.0.1` and a SHA
    (#218). The conclusion was right and the stated reason described a
    convention this file does not have, which is worse than saying nothing:
    the next reader concludes the exact pins are the anomaly and tidies them
    into real floating majors.

    **The first version of this test checked less than the comment claimed**,
    which is the same defect it was written to close. It rejected `@vN` alone,
    so `@main` — the most mutable ref there is — passed, on the checkout step
    the release gate's whole safety argument runs from, directly beneath a
    sentence saying every action here is pinned exactly. So did `@latest`,
    `@7`, `@V7`, and the quoted `"…@v7"` form, which is valid YAML and slipped
    the regex because `(\\S+)` swallowed the closing quote (adversarial review
    of #231). The rule is now the comment's rule: a 40-hex SHA, or an exact
    patch version (major.minor.patch), so no upstream release can move under
    it. Anything else — a branch, a tag alias, a bare major, a two-part `vN.N`
    — is rejected by not matching, rather than by being on a list of forms
    someone thought of.

    This sentence said "at least a major AND a minor" until the v0.7.6 pre-tag
    audit. The regex was tightened to three parts in review, and the summary
    was left spelling the pre-tightening rule — directly contradicting the
    inline comment ten lines below it, and telling the next reader `@v7.0` is
    acceptable on the checkout step the release gate's safety argument runs
    from.
    """
    # Comments stripped, for `_live_lines`'s reason turned around: the
    # paragraph this test defends *discusses* `@v9`, and a check that read the
    # raw file would eventually fail on prose about a pin rather than a pin.
    workflow = _live_lines(REPO / ".github" / "workflows" / "release.yml")
    refs = re.findall(r"uses:\s*(\S+)@(\S+)", workflow)
    assert refs, "the workflow must still use actions"
    # Major.minor.patch, or a 40-hex SHA in either case. NOT `vN.N`: the
    # comment this enforces says "an exact patch or a SHA", and a two-part tag
    # is a published moving alias in some action repos — the pattern was looser
    # than the sentence it is cited by (adversarial review of #234). A
    # prerelease suffix (`v1.2.3-beta`) is exact and is allowed.
    exact = re.compile(r"(?:[0-9a-fA-F]{40}|v?\d+\.\d+\.\d+(?:[-+][\w.]+)?)")
    loose = [
        f"{action}@{ref}".strip("\"'")
        # Quotes stripped from the ref, not matched around it: `uses: "a/b@v7"`
        # is valid YAML and the closing quote otherwise rides along and makes
        # every form fail to match the exact pattern... in the safe direction
        # for `@v7.0.1` but not for the reader, who would see a passing test
        # for a reason unrelated to the pin.
        for action, ref in refs
        if not exact.fullmatch(ref.strip("\"'"))
    ]
    assert not loose, (
        f"release.yml says every action here is pinned to an exact patch or a SHA: {loose}"
    )


# ---------------------------------------------------------------------------
# the sdist
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sdist_names(tmp_path_factory) -> set[str]:
    """Every path inside the built sdist, package-prefix stripped.

    Skipped outside a checkout, or without the build frontend. These two
    tests ask what THIS repository publishes; inside the published artifact
    the question is already answered, and a distro packager building offline
    without `uv` would otherwise see the only two tests about their own use
    case error out.
    """
    import shutil

    # `.git` must be a DIRECTORY, not merely present. In a git worktree it is
    # a file, hatchling cannot read the VCS ignores through it, and the sdist
    # ships everything — so these two tests report a leak that exists only in
    # the worktree, and this repo's own tooling creates worktrees under
    # `.claude/worktrees/` (adversarial review of #234). Skipping is right
    # rather than adapting: the question is what THIS repository publishes, and
    # a build that cannot see the ignore rules is not answering it.
    if shutil.which("uv") is None or not (REPO / ".git").is_dir():
        pytest.skip(
            "inspects what this checkout publishes; needs the uv frontend and a checkout "
            "whose .git is a directory (in a worktree hatchling cannot read the ignores)"
        )
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    tarball = next(out.glob("*.tar.gz"))
    with tarfile.open(tarball) as archive:
        return {name.split("/", 1)[1] for name in archive.getnames() if "/" in name}


def test_the_sdist_carries_everything_the_suite_reads(sdist_names: set[str]):
    """`tests/` ships so a downstream packager can run the suite, and that
    claim is only worth making if it holds. The first draft of the exclude
    list cut `.github/`, `evals/` and `notes/` and broke five tests inside
    the sdist — two of them tests added by the same commit — which is the
    same failure this slice exists to fix, committed while fixing it.

    `evals/` and `notes/` are off this list as of #150, and the route matters:
    not skip-guarded, but no longer read at all. The tests that read them
    asserted phrases were present in prose, which cannot tell a true claim
    from a false one, so they were deleted rather than made conditional. A
    path leaves this list when nothing reads it — never because reading it
    became inconvenient.

    These are the repo paths the suite actually reads, found by grepping the
    tests for their own fixtures.
    """
    required = [
        "tests/conftest.py",
        "docs/SPEC-contract.md",
        "docs/FAILURE-MODES.md",
        "examples/bearing-block/claims.py",
        "skills/contract-authoring/SKILL.md",
        ".github/workflows/release.yml",
        "scripts/assert_tag_on_main.sh",
        # Read by `test_the_generated_doc_blocks_are_current`, which runs it as
        # a subprocess. Listed because that test's own guard is a `skip` when
        # the script is missing: without this row, a later PR excluding
        # `scripts/` from the sdist would break nothing visibly — the packaging
        # test would not require the path and the docs test would skip with a
        # reassuring message (PR #156 review, finding B).
        "scripts/gen_docs.py",
        "src/partspec/py.typed",
    ]
    missing = [path for path in required if path not in sdist_names]
    assert not missing, f"the suite reads these and the sdist does not carry them: {missing}"


def test_no_test_shells_out_to_git_without_a_checkout_guard():
    """The invariant behind the claim above, since nothing enforces the claim.

    `tests/` ships so a downstream packager can run the suite, and
    `pyproject.toml` argues that only holds if the suite passes from an sdist —
    which has no `.git`. It did not hold from #151 until PR #155:
    `test_docs.py` called `git ls-files` with `check=True` and errored out with
    exit 128 there. Rebuilding an sdist to catch the next one would double CI, so
    this asserts the property that actually breaks instead: a test that runs git
    must also know it might not be in a checkout.

    Textual on purpose — it is a lint over test sources, not a behaviour — and
    scoped to `["git"` because that is how every current caller spells it. A
    caller that builds its argv some other way slips past; the point is to catch
    the copy-paste shape that has now caused this once, not to be a type system.
    """
    offenders = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        text = path.read_text()
        if '["git"' in text and '".git"' not in text:
            offenders.append(path.name)
    assert not offenders, (
        "these shell out to git with no `(ROOT / '.git').exists()` guard, so they "
        f"error rather than skip in an unpacked sdist: {offenders}"
    )


def test_only_a_module_that_cannot_import_gates_at_import():
    """The other way a test disappears: `pytest.importorskip` at module scope.

    It raises during collection, so pytest reports the whole file as ONE
    skipped line and every test inside it — including the ones that needed
    nothing — is gone from the count. `test_diff.py` reported `1 skipped` for
    34 tests, 32 of which needed no engine (#163, which removed eight such
    gates). The ten that survived were measured in #165: they hid 11 tests
    that pass with no extras at all, and four `the mesh tier refuses with the
    tier named` tests, invisible under `pip install partspec[mesh]` — the one
    install where the mesh tier is the only tier there is.

    A per-test `needs_*` marker costs a line and keeps the skip visible and
    counted. Three modules genuinely cannot be imported without their extra;
    they are listed with the reason, because a reason in an allowlist is read
    and a reason in a comment is not.
    """
    allowed = {
        "test_mcp.py": "every test drives the MCP adapter",
        "test_occt_backend.py": "a module-level bd.Box(...) inside a parametrize",
        "test_raster.py": "partspec.raster imports numpy at module scope",
    }
    gated: dict[str, list[int]] = {}
    for path in sorted((REPO / "tests").glob("test_*.py")):
        for node in ast.parse(path.read_text()).body:
            call = node.value if isinstance(node, ast.Assign | ast.Expr) else None
            if isinstance(call, ast.Call) and ast.unparse(call.func) == "pytest.importorskip":
                gated.setdefault(path.name, []).append(node.lineno)
    assert set(gated) == set(allowed), (
        "a module-level importorskip collapses a whole file to one skip line. "
        f"Gating: {gated}. Allowed, with the reason each one cannot be avoided: {allowed}"
    )


def test_the_sdist_leaves_out_what_a_consumer_cannot_use(sdist_names: set[str]):
    """`uv.lock` pins this repo's dev environment, which says nothing about the
    package's own requirements, so a consumer cannot use it.

    Excluding it saves ~160 KiB, ~23% of the tarball — measured by building both
    ways. This docstring said "27% ... half a megabyte" until PR #155's review
    found the same two figures already corrected in `pyproject.toml` and not
    here, in the test that actually enforces the exclusion. The absolute sizes
    are deliberately absent: four measurements taken while editing this PR's own
    prose gave four different answers, because every line added to the repo lands
    in the tarball. Only the delta and the share hold still."""
    assert "uv.lock" not in sdist_names
    assert "CLAUDE.md" not in sdist_names

    # Repo archaeology, dropped in #150. Asserted by PREFIX, not by naming the
    # two files the old required-list happened to mention: the exclusion is
    # "this tree does not ship", and a check that only knew `notes/dogfood-
    # results.md` would pass while the other 300 KB of transcripts rode along.
    archaeology = sorted(n for n in sdist_names if n.startswith(("notes/", "evals/")))
    assert not archaeology, (
        "the sdist carries repo archaeology a consumer cannot use: "
        f"{archaeology[:5]}{'...' if len(archaeology) > 5 else ''}"
    )

    assert "pyproject.toml" in sdist_names, "and the things a build needs are still there"
    assert "README.md" in sdist_names


def test_the_sdist_ships_nothing_at_the_top_level_that_is_not_on_the_list(
    sdist_names: set[str],
):
    """The denylist above cannot catch the leak it has not been told about.

    It asserts by NAME — `uv.lock`, `CLAUDE.md`, the `notes/`/`evals/` prefixes
    — so each new tree that should not ship gets in for free until someone
    notices. `.claude/scheduled_tasks.lock` did (#218): it sat in
    `.git/info/exclude`, which is local to one clone and which hatchling does
    not read, so a dev-built sdist and a CI-built one were different tarballs —
    and being able to reproduce the published artifact locally is the whole
    point of building one. The published artifact was never affected;
    `release.yml` builds from a clean checkout.

    An allowlist inverts the default: a new top level has to be argued for
    here. Scoped to the TOP LEVEL because that is the granularity that holds
    still — a per-file allowlist would fail on every module added, which is a
    test nobody keeps.

    **The second clause exists because the first one alone was not enough.**
    Top-level scoping shares a blind spot with a root-anchored `.gitignore`
    entry, and #231 shipped both: `examples/.claude/scheduled_tasks.lock` still
    reached the tarball with this test green (adversarial review, measured).
    Dot-directories are where tool and agent state always lands, at whatever
    depth, so they are allowlisted by NAME anywhere in a path rather than only
    at the root. That is a rule an editor or agent nobody has heard of still
    trips over, which a list of known offenders is not.
    """
    top = {name.split("/", 1)[0] + ("/" if "/" in name else "") for name in sdist_names}
    allowed = {
        # What a consumer builds and reads.
        "pyproject.toml",
        "PKG-INFO",
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "AGENTS.md",
        # The trust boundary (#278). Not in the wheel -- a `pip install` user
        # meets it through README, which PyPI renders as the description. It is
        # here because the sdist is the complete-source distribution and a
        # downstream packager redistributing partspec should carry the policy
        # with it.
        "SECURITY.md",
        "src/",
        # What the suite needs in order to pass from an unpacked sdist, which
        # is the claim `tests/` shipping at all rests on.
        "tests/",
        "docs/",
        "examples/",
        "skills/",
        "scripts/",
        ".github/",
        # Read by hatchling to decide this very list, and by the suite.
        ".gitignore",
        "justfile",
    }
    assert top <= allowed, f"the sdist ships an unargued top level: {sorted(top - allowed)}"
    # Not vacuous on an empty tarball, which `top <= allowed` alone would call
    # a clean sdist. The denylist test asserts the same two, deliberately: this
    # one must stand on its own or its name overstates it.
    assert {"pyproject.toml", "src/"} <= top, f"the sdist is missing the package itself: {top}"

    # Dot-DIRECTORIES at any depth, which the top-level clause cannot see.
    dot_dirs = sorted(
        {
            part
            for name in sdist_names
            for part in name.split("/")[:-1]  # directories only; the last part is the file
            if part.startswith(".")
        }
    )
    assert dot_dirs == [".github"], (
        f"the sdist carries tool or agent state: {dot_dirs}. Dot-directories are where "
        f"editors and agents write per-checkout state; add it to .gitignore rather than here"
    )


def test_an_untracked_file_at_the_top_level_does_not_reach_the_sdist(tmp_path):
    """The test above judges the sdist this checkout builds, so it cannot tell
    a leak in the build config from a stray file in one clone. #444 was the
    second: a sandboxed agent session mounts `.bashrc`, `.mcp.json` and nine
    more at the root as device nodes, hatchling reads the directory rather than
    the index, and the top-level test failed on every local run there.

    So build from a fresh clone, carrying this checkout's `pyproject.toml`,
    with a stray, unignored root file planted, and require that it stays
    out. Without `only-include` in `pyproject.toml` it ships.
    """
    import shutil

    if shutil.which("uv") is None or not (REPO / ".git").is_dir():
        pytest.skip("builds from a clone of this checkout; needs uv and a .git directory")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", str(REPO), str(clone)],
        capture_output=True,
        text=True,
        check=True,
    )
    # The clone has HEAD's build config; judge this checkout's instead.
    shutil.copyfile(REPO / "pyproject.toml", clone / "pyproject.toml")
    (clone / ".bashrc").write_text("")
    out = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(out)],
        cwd=clone,
        capture_output=True,
        text=True,
        check=True,
    )
    with tarfile.open(next(out.glob("*.tar.gz"))) as archive:
        names = {name.split("/", 1)[1] for name in archive.getnames() if "/" in name}
    assert "pyproject.toml" in names, f"the build produced no package: {sorted(names)[:5]}"
    assert ".bashrc" not in names, "an untracked root file rode into the sdist"


def test_the_ok_gate_waits_for_every_job_in_the_workflow():
    """`ok` is the branch-protection gate, so a job missing from its `needs`
    is a job that cannot block a merge.

    Nothing checked this, and it is silent in the worst way: the absent job
    still runs, still goes red on the PR page, and the merge button still
    turns green because the one required check passed without waiting for it.
    A job that cannot fail the gate is a job that reads as success — this
    repo's thesis, applied to its own CI (found adding `no-extras`).

    Parsed with a regex rather than PyYAML on purpose: `yaml` is not in the
    dependency tree, and this suite must pass in a no-extras install, which
    the `no-extras` job itself now proves.
    """
    text = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    body = text.split("\njobs:\n", 1)
    assert len(body) == 2, "ci.yml no longer has a top-level `jobs:` block"
    # A GitHub job id may start with any letter or `_`, and this file comments
    # heavily around job keys. Anchoring to lowercase-and-`:$` made `Build:` or
    # `  mutant:  # new` invisible — a gate-checker reading as success for an
    # unguarded job, which is the failure it exists to prevent (review M4/M5).
    jobs = re.findall(r"^  ([A-Za-z_][\w-]*):\s*(?:#.*)?$", body[1], re.M)
    assert "ok" in jobs, "the gate job is named `ok` everywhere else that matters"

    gate = re.search(r"^  ok:$.*?^    needs: \[([^\]]+)\]", body[1], re.M | re.S)
    assert gate is not None, "`ok` has no `needs:` list; it gates nothing"
    waited_for = {n.strip() for n in gate.group(1).split(",")}

    unguarded = sorted(set(jobs) - waited_for - {"ok"})
    assert not unguarded, (
        f"these jobs run but cannot block a merge: {unguarded}. Add them to `ok`'s `needs:` list."
    )


def test_every_changelog_version_is_a_link_and_unreleased_starts_at_the_last_one():
    """Keep a Changelog renders each version heading as a link to its diff.

    A heading whose definition is missing does not fail — it renders as the
    literal text `[0.7.0]`, sitting between neighbours that are links, on the
    file `pyproject.toml` advertises as the project's Changelog URL. That is
    what v0.7.0 shipped, and it is this repo's own failure mode: the broken
    thing looks like the working thing.

    The `Unreleased` range is checked too, because it is wrong by default. It
    keeps whatever tag it was written with, so the release that adds a version
    heading and forgets this line leaves `Unreleased` spanning the release it
    just cut — v0.7.0 shipped `v0.6.0...HEAD` (PR #162 review, HIGH-3).
    """
    # Fenced code is stripped first, in both directions. A heading inside a
    # fence is an example, not a section; a DEFINITION inside one defines
    # nothing, and counting it would let the very defect this test exists to
    # catch pass (PR #162 review, LOW-E).
    raw = (REPO / "CHANGELOG.md").read_text()
    lines, fenced = [], False
    for line in raw.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            lines.append("")
            continue
        lines.append("" if fenced else line)
    text = "\n".join(lines)

    headings = re.findall(r"^## \[([^\]]+)\]", text, re.M)
    # The URL may carry an optional title (`[x]: <url> "title"`), which is
    # valid CommonMark; `(\S+)$` rejected it and failed a correct file.
    defined = dict(re.findall(r'^\[([^\]]+)\]: *(\S+)(?: +["\'(].*)?$', text, re.M))

    undefined = [h for h in headings if h not in defined]
    assert not undefined, (
        f"these headings render as literal text, not links: {undefined}. "
        f"Add a definition at the foot of CHANGELOG.md."
    )

    # One section per change type, checked on `[Unreleased]`. Two `### Fixed`
    # blocks under one version is not a formatting nit: a reader scanning for
    # what changed stops at the first, and a tool grouping by heading keeps
    # one. It happened here and six green gates did not notice (PR #164
    # review) — the thesis pointed at the release notes.
    #
    # `[Unreleased]` ONLY, and that is where it bites: a release is cut from
    # this section, so guarding it stops the defect before it becomes history.
    # The released sections are not retrofitted — `[0.1.0]` carries five
    # `### Fixed` blocks from the pre-1.0 scramble, and merging them would
    # reorder historical entries, which is more than the form-only edit
    # AGENTS.md permits on a released section.
    if "Unreleased" in headings:
        block = text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        kinds = re.findall(r"^### (\w+)", block, re.M)
        dupes = sorted({k for k in kinds if kinds.count(k) > 1})
        assert not dupes, (
            f"[Unreleased] has more than one '### {dupes[0]}' section ({kinds}); "
            f"fold the bullets into one before this is cut into a release"
        )

    versions = [h for h in headings if h != "Unreleased"]
    assert versions, "a changelog with no released version is not one this test understands"
    if "Unreleased" in headings:
        # Highest, not first. Reading position assumes the file is in reverse
        # chronological order, and a version inserted in the wrong place would
        # then be compared against — so the ordering is derived rather than
        # trusted (review LOW-F).
        def key(v: str) -> tuple:
            head = v.split("-")[0]
            return tuple(int(p) if p.isdigit() else 0 for p in head.split("."))

        newest = max(versions, key=key)
        assert defined["Unreleased"].endswith(f"compare/v{newest}...HEAD"), (
            f"[Unreleased] compares from {defined['Unreleased'].rsplit('/', 1)[-1]}, but the "
            f"newest released version is {newest}; the range spans a release already cut"
        )


def test_the_project_urls_point_at_things_that_exist():
    """Presence of the keys is not the claim; the claim is that a reader
    following them arrives somewhere. The two that name in-repo files are
    checked against the repo."""
    urls = PYPROJECT["project"]["urls"]
    assert {"Repository", "Issues", "Changelog", "Documentation"} <= set(urls)
    assert urls["Changelog"].endswith("/CHANGELOG.md")
    assert (REPO / "CHANGELOG.md").is_file()
    assert urls["Documentation"].rstrip("/").endswith("/docs")
    assert (REPO / "docs").is_dir()


def test_every_throwaway_install_recipe_ignores_this_repos_uv_config():
    """`uv pip` applies `[tool.uv]` from the pyproject.toml it finds by walking
    up from the CWD — to whatever it is installing, published wheel included.
    These recipes exist to measure what a CONSUMER gets, and a consumer never
    has this repo's `override-dependencies` in scope.

    Without `--no-config` the measurement is of our own resolution wearing a
    consumer's clothes. That is not a hypothetical: it produced #109, ten days
    of a self-inflicted strand recorded as an upstream uv bug, a README
    paragraph telling every uv user to avoid a command that works, and two
    recipes carrying a plain-pip workaround for a cause that was never real.

    Scoped to the justfile alone on its first outing, which left the one
    install that matters most uncovered: `release.yml`'s cold smoke-test of
    the built wheel, the last thing to touch an artifact before PyPI. It ran
    in the checkout and read the override like everything else. Anywhere a
    consumer's install is being reproduced counts, so the search is over
    every file that runs one.
    """
    sources = [REPO / "justfile", *sorted((REPO / ".github" / "workflows").glob("*.yml"))]
    lines = [
        (path.name, stripped)
        for path in sources
        for line in path.read_text().splitlines()
        # A comment is prose ABOUT an install, not one — both the justfile and
        # ci.yml discuss this very command in comments that must not be read
        # as commands. `VIRTUAL_ENV=... uv pip install` is one, so the match
        # is anywhere in the line, not at its start.
        if "uv pip install" in (stripped := line.strip()) and not stripped.startswith("#")
    ]
    assert lines, "no `uv pip install` anywhere — this guard has lost its subject"
    missing = [f"{name}: {line}" for name, line in lines if "--no-config" not in line]
    assert not missing, (
        "these installs read this repo's [tool.uv] and so cannot measure what a "
        f"consumer gets — add --no-config: {missing}"
    )


def test_no_runtime_message_tells_the_reader_to_run_bare_pip():
    """A remedy naming an installer the reader does not have is not a remedy.

    A `uv venv` ships no `pip`, and on a distro that packages one the word
    still resolves — to `/usr/bin/pip`, bound to the SYSTEM interpreter. So
    `pip install --force-reinstall --no-deps cadquery-ocp`, the whole answer to
    the two-provider clobber, ran clean and installed OCP where the failing
    3.12 venv could never see it. The user follows the instruction and the next
    run prints a byte-identical diagnosis.

    That is the tool's own thesis turned inside out: not silence read as
    success, but an answer that does nothing read as an answer. Found on the
    v0.7.3 cold verify, in the very install shape the README documents.

    Scoped to the property rather than to the line where it was found, which is
    the lesson #109's guard learned the expensive way: every live string in the
    package, not the four hints that happened to be wrong. Prose is exempt —
    a bare string statement is documentation, never a message — so a docstring
    may still discuss `pip install partspec`, and several do.
    """
    package = REPO / "src" / "partspec"
    offenders, uses = [], 0
    for path in sorted(package.rglob("*.py")):
        text = path.read_text()
        if path.name == "install.py":
            continue  # its own definition is not a use of it
        uses += text.count("install_hint(")
        tree = ast.parse(text)
        prose = {
            id(stmt.value)
            for stmt in ast.walk(tree)
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
        }
        offenders += [
            f"{path.relative_to(package)}:{node.lineno}: {node.value!r}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in prose
            and "pip install" in node.value
        ]
    assert uses, "nothing calls install_hint — this guard has lost its subject"
    assert not offenders, (
        "these messages name an installer that may not exist where they are read; "
        f"phrase them with install_hint(): {offenders}"
    )


def test_the_install_hint_names_the_installer_this_interpreter_has(monkeypatch):
    """Detection is `find_spec`, and `shutil.which` would be wrong.

    Measured in a uv venv on this machine: `find_spec("pip")` is None and
    `which("pip")` is `/usr/bin/pip` — a real file, for another interpreter.
    `which` answers "does the word resolve", and the question a hint has to
    answer is "can THIS interpreter install".
    """
    from partspec.install import install_hint

    real = importlib.util.find_spec

    def without_pip(name, *a, **kw):
        return None if name == "pip" else real(name, *a, **kw)

    monkeypatch.setattr(importlib.util, "find_spec", without_pip)
    assert install_hint("'partspec[mesh]'") == "uv pip install 'partspec[mesh]'"
    assert install_hint("--force-reinstall x", "--reinstall-package x x") == (
        "uv pip install --reinstall-package x x"
    ), "where the two installers disagree on flags, uv gets its own spelling"

    monkeypatch.setattr(importlib.util, "find_spec", real)
    if real("pip") is not None:  # pragma: no cover - depends on the venv
        assert install_hint("'partspec[mesh]'") == "pip install 'partspec[mesh]'"


# ---------------------------------------------------------------------------
# the wheel
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def wheel_names(tmp_path_factory) -> set[str]:
    """Every path inside the built wheel.

    Same guards as `sdist_names`, and the `.git`-is-a-directory one matters
    here for a different reason: this asks what THIS repository publishes, and
    a worktree cannot answer it.
    """
    import shutil
    import zipfile

    if shutil.which("uv") is None or not (REPO / ".git").is_dir():
        pytest.skip(
            "inspects what this checkout publishes; needs the uv frontend and a checkout "
            "whose .git is a directory (in a worktree hatchling cannot read the ignores)"
        )
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    with zipfile.ZipFile(next(out.glob("*.whl"))) as archive:
        return set(archive.namelist())


def test_the_wheel_carries_exactly_the_documents_git_tracks(wheel_names: set[str]):
    """#349, both halves: the documents ship, and only the tracked ones do.

    The first half is the bug as filed — on 0.7.6, `find` over an installed
    tree for `AGENT-CONTRACT.md` returned nothing, so every spec citation in
    every diagnostic and the contract's own routing line were dead paths for
    anyone who installed rather than cloned.

    The second half is the hazard the fix introduces. `force-include` copies
    what is on DISK, not what git tracks: measured, by adding `examples/` to
    the block and building, ten untracked `outputs/` artifacts landed in the
    wheel. Not `__pycache__`, which hatchling excludes on its own — this
    docstring said `outputs/` and `__pycache__` until the review re-ran the
    probe and found the `.pyc` files on disk and absent from the zip. A
    dev-built wheel differing from a CI-built one is #218 again, on the
    artifact that reaches PyPI where inspection cannot catch it later.

    Set EQUALITY, therefore, rather than a subset in either direction. What
    that catches is an UNTRACKED file, not a generated one: three specs carry
    generated blocks and are committed, and they ship exactly as tracked.
    """
    tracked = set(
        subprocess.run(
            ["git", "ls-files", "docs", "skills"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    )
    assert tracked, "no tracked documents at all; this test has lost its subject"

    prefix = "partspec/_bundled/"
    bundled = {name[len(prefix) :] for name in wheel_names if name.startswith(prefix)}
    assert bundled == tracked, (
        "the wheel's bundled documents are not the tracked ones:\n"
        f"  missing from the wheel: {sorted(tracked - bundled)}\n"
        f"  in the wheel, untracked: {sorted(bundled - tracked)}"
    )

    # Non-vacuous in the direction that matters: the two files the corpus
    # routes to first, named outright.
    for entry in ("docs/AGENT-CONTRACT.md", "skills/contract-authoring/SKILL.md"):
        assert prefix + entry in wheel_names, f"the wheel does not carry {entry}"
    assert "partspec/cli.py" in wheel_names, "and it is still a package, not a docs bundle"


def test_the_installed_wheel_locates_the_documents_it_carries(tmp_path: Path):
    """The claim the whole slice rests on, executed against an install.

    Everything else about #349 is checked from inside a checkout, where the
    paths always resolved — and `docs_root()`'s installed branch (`_bundled`)
    is dead code there, because every throwaway recipe installs `-e '.'` and
    takes the `src/` branch instead. Coverage said so outright: that line was
    executed by nothing in the suite (PR #350 review, finding 9).

    What only this can catch is the WHEEL and the LOCATOR disagreeing. The
    example first written here was wrong and the review re-ran it: retargeting
    force-include to `partspec/docs` fails the namelist test above too, because
    that test filters on the literal `partspec/_bundled/` prefix. The mutation
    that isolates this one is a mismatch — leave the wheel shipping `_bundled/`
    and have `docs_root()` look for `_bundle/`:

        force-include destination -> partspec/docs   : BOTH tests fail
        docs_root() -> package / "_bundle"           : only this one fails,
                                                       exit 4 from the install

    Which is the shape a rename would really take, and no zip listing can see
    it: the archive is correct and every install still refuses.

    `--no-config`, like every other throwaway install here: `uv pip` reads
    `[tool.uv]` from the nearest pyproject.toml above the CWD and would apply
    this repo's OCP overrides to the wheel under test.
    """
    import shutil

    if shutil.which("uv") is None or not (REPO / ".git").is_dir():
        pytest.skip("needs the uv frontend and a checkout, like the wheel fixture")

    out = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", "--no-config", str(venv)], capture_output=True, check=True)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--no-config",
            "--python",
            str(venv / "bin" / "python"),
            str(next(out.glob("*.whl"))),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # PYTHONPATH is scrubbed, not inherited. The point of this test is that an
    # INSTALLED copy locates its own documents, and `partspec --docs` in a
    # subprocess honours whatever `PYTHONPATH` the parent had -- so a developer
    # who exports one (pointing at a checkout, which is the usual reason to)
    # makes the installed entry point import that checkout instead, take
    # `docs_root()`'s `src/` branch, and print the repository root. The
    # assertions below then fail on a correct install. Found by running the
    # suite with `PYTHONPATH` set at a merged tree; CI passes only because it
    # happens not to set one, which is the kind of accident this file exists to
    # stop relying on.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    located = subprocess.run(
        [str(venv / "bin" / "partspec"), "--docs"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert located.returncode == 0, f"--docs failed on an install: {located.stderr}"
    root = Path(located.stdout.strip())
    assert root.is_dir(), f"--docs named {root}, which is not a directory"
    assert venv in root.parents, f"--docs named {root}, which is outside the install"
    for entry in ("docs/AGENT-CONTRACT.md", "skills/contract-authoring/SKILL.md"):
        assert (root / entry).is_file(), f"the install cannot open {entry} under {root}"


# ---------------------------------------------------------------------------
# what binds a document to a version (#300)
# ---------------------------------------------------------------------------


VERSIONED_DOCS = (
    "docs/SPEC-contract.md",
    "docs/SPEC-report.md",
    "docs/SPEC-backend.md",
    "docs/SPEC-diff.md",
    "docs/AGENT-CONTRACT.md",
    "docs/LINT.md",
    "docs/FAILURE-MODES.md",
)
"""The normative surface: every document that describes a release."""

UNVERSIONED_DOCS = frozenset({"DECISIONS.md", "POST-V0.md", "PLAN.md", "README.md"})
"""Exempt, each for its own reason. `DECISIONS.md` and `POST-V0.md` are
reasoning that outlives any release; `PLAN.md` says **HISTORICAL** in its own
second line; `README.md` is a router whose claims are about the other files
rather than about the tool.

Named rather than merely omitted. The first version of this gate was a
whitelist with a prose aside, and `docs/README.md` was in neither -- so a new
`docs/SPEC-*.md` file could be added with no `Applies to:` line and all four
gates passed (executed, PR #363 review MEDIUM-1). A partition forces the next
person to classify.
"""


def _declared_version() -> str:
    return PYPROJECT["project"]["version"]


def test_the_changelog_names_the_version_the_package_declares():
    """`pyproject` and the changelog were two claims with nothing between them.

    Two gates already existed and neither covered this: `release.yml`'s
    tag-vs-version check, and the changelog's own link-definition test. Bump
    `pyproject` to a version with no `## [x.y.z]` section, tag it, and both
    pass — the release then publishes a version the changelog never described.
    """
    headings = re.findall(r"^## \[([^\]]+)\]", (REPO / "CHANGELOG.md").read_text(), re.M)
    released = [h for h in headings if h != "Unreleased"]
    assert released, "no released sections at all; this test has lost its subject"
    assert released[0] == _declared_version(), (
        f"pyproject declares {_declared_version()} and the newest changelog section is "
        f"{released[0]}; a release must not describe a version nobody can install"
    )


def test_the_readme_and_agents_status_lines_name_that_same_version():
    """`AGENTS.md` says status claims are "part of the gate". Nothing gated them.

    Asserted as "the declared version appears in the status line", not as an
    exact sentence: the prose around it is narrative and moves every release,
    while the number is the part that must not drift.
    """
    version = _declared_version()
    for name in ("README.md", "AGENTS.md"):
        text = (REPO / name).read_text()
        status = next(
            (line for line in text.splitlines() if "Status:" in line and "pre-alpha" in line),
            None,
        )
        assert status is not None, f"{name} has no status line to check"
        assert re.search(rf"\bv?{re.escape(version)}\b", status), (
            f"{name}'s status line does not name {version}: {status.strip()!r}"
        )


def test_every_normative_document_says_which_version_it_describes():
    """The root cause #300 names: nothing bound a document to a version.

    Seven documents carried a `Status:` line with a draft number and a date, and
    five of the seven were stale against their own last content commit — one by
    24 days, across three releases. The date could not discriminate: `git show
    v0.7.0:docs/SPEC-contract.md` and `git show v0.7.6:` printed the identical
    line while the documents differed by whole sections.

    So the date is not what is gated. An **Applies to:** line naming the
    declared version is, because it is the claim a reader actually needs — which
    release this text describes — and it is mechanically checkable. The
    `Status:` line stays as provenance: when the document was last revised in
    substance, which is a fact about history rather than a claim about currency.
    """
    version = _declared_version()
    # rglob, keyed on the path relative to `docs/`: a flat glob missed
    # `docs/adr/SPEC-newthing.md` entirely, which is MEDIUM-1's own defect one
    # level down (PR #363 review, NEW-2). `docs/` is flat today, so this is
    # latent rather than live -- which is exactly when it is cheap to close.
    present = {p.relative_to(REPO / "docs").as_posix() for p in (REPO / "docs").rglob("*.md")}
    classified = UNVERSIONED_DOCS | {n[len("docs/") :] for n in VERSIONED_DOCS}
    assert present == classified, (
        "every document in docs/ must be classified as versioned or exempt; "
        f"unclassified: {sorted(present - classified)}, "
        f"named but absent: {sorted(classified - present)}"
    )

    missing, stale = [], []
    for name in VERSIONED_DOCS:
        head = "\n".join((REPO / name).read_text().splitlines()[:12])
        match = re.search(r"^\*\*Applies to:\*\* (.+)$", head, re.M)
        if match is None:
            missing.append(name)
        elif not re.search(rf"\bv?{re.escape(version)}\b", match.group(1)):
            stale.append(f"{name} -> {match.group(1).strip()}")
    assert not missing, f"no `Applies to:` line in: {missing}"
    assert not stale, (
        f"these describe a version other than the declared {version}:\n  " + "\n  ".join(stale)
    )
