"""Semantic comparison of two reports of one part.

The consumer `SPEC-report.md` §7.2 recorded measurements-on-pass for, and the
comparison §7.1's silent-weakening gap was waiting on: a deleted check is
invisible inside one green report and unmissable between two.

Spec: SPEC-diff.md.
"""

from __future__ import annotations

from typing import Any

from .report import IMPLICIT_CHECK_KINDS, SCHEMA_VERSION
from .status import _SEVERITY, Status, comparison_exit_code, epsilon

__all__ = [
    "CLAIM_FIELDS",
    "DIFF_SCHEMA_VERSION",
    "NON_CLAIM_FIELDS",
    "DiffUsageError",
    "diff_reports",
    "exit_code_of",
    "summary_of",
]

DIFF_SCHEMA_VERSION = 2
"""This artifact's own version — never the report's (SPEC-diff.md §4).

Bumped to 2 by #190 stage 3: `source` gained `imports`, `unseen`, `covered`
and `closure_digest_changed`, and `source.closure` keys on named gaps rather
than on the `partial` boolean; `source.imports.unattributable` landed in the
same unreleased version.
It is diff's *output* contract, so no stored report is refused by the change.
"""

CLAIM_FIELDS = ("kind", "expr", "limit", "region", "hole", "source", "direction")
"""The fields that make a check the claim it is.

Public and named because SPEC-diff.md §3 enumerates them and two tests hold
the three lists in step. The list has drifted three times unnoticed, each
time in the direction that reads a weakened contract as `identical`:
`direction` arrived with `draft_angle` and was never documented; `kind` was
never compared at all, so swapping `genus` for `cavities` under one id passed
as no difference; and `expr` — the entire predicate of a `requires` check —
was missing, so `wall >= 2.0` becoming `wall >= 0.2` was invisible.

Every other key `CheckResult.to_json` emits is deliberately NOT here, and
`NON_CLAIM_FIELDS` says which and why, so the next field added to the report
has to be classified rather than silently ignored.
"""

NON_CLAIM_FIELDS = {
    "id": "the join key itself — a changed id is a removed check plus an added one",
    "status": "a result, compared separately and reported as regressed/fixed",
    "measurement": "a result, compared separately and reported as drifted",
    "operands": "a result — the values the expression saw, compared separately",
    "components": "a result, derived from measurement against limit",
    "detail": "prose about a result, not a claim",
    "intrusion": (
        "how far a failing keep_out was breached — a result, and a derived one. "
        "The claim is the region and its shell, which `region` carries; this is "
        "what the material did about it. Deliberately NOT a claim field: the "
        "depth is a search resolution away from the truth and its floor is a "
        "function of `segments`, so comparing it would report `different` on a "
        "declaration that was merely re-faceted. (Three identical runs measured "
        "bit-identical on the mesh tier, so run-to-run drift is NOT the reason "
        "— round-2 review of #207.)"
    ),
    "edges": (
        "where a failing watertight mesh is open or non-manifold -- a result, "
        "derived from the exported triangles, as `detail` is; not a claim (#440)"
    ),
    "phase": (
        "structural, and cannot move without kind or expr moving with it. Not inert, "
        "though: it is the input deciding which tolerance `_value_delta` applies, so it "
        "is read by this comparison without ever being a difference in it (#335)"
    ),
    "requires": "which tier would answer a refusal — environment, like engine.version",
    "step": (
        "the STEP writer schema — tool-chosen, not author-declared, so not a claim. "
        "Note it is not surfaced anywhere else either: unlike engine.version it does "
        "NOT reach the environment block, so a schema change beside a drifted "
        "round-trip measurement goes unexplained. A known gap, stated rather than "
        "implied by calling it environment"
    ),
}
"""Why each non-claim field is not compared as a claim.

The reverse of `CLAIM_FIELDS`, and the reason the pair is testable: a claim
that the comparator covers "every field that makes a check the claim it is"
can only be checked if the fields it does NOT cover are enumerated too. PR
#147 made that claim in three places while `expr` was missing from both
lists, and no test could have noticed.
"""


class DiffUsageError(Exception):
    """The inputs cannot be compared at all — a usage error (exit 64), never a
    finding. Unreadable input, unknown schema, or two different parts."""


def exit_code_of(outcome: str) -> int:
    """The shared policy (`status.comparison_exit_code`), re-exported so both
    verbs keep their own name for it."""
    return comparison_exit_code(outcome)


_CONCLUSIVE = frozenset({Status.PASS, Status.FAIL})
"""The statuses that mean the check was evaluated to a conclusion.

Named as a membership rather than as a list of the three it excludes, because
enumerating them is how two drafts of #325 got the bound wrong — the first
omitting `approximate`, the second admitting only transitions out of `fail`.
`Status`'s own docstrings draw the line: `pass` is "evaluated and satisfied,
conclusively" and `fail` is "evaluated and violated, conclusively", while
`approximate` is "indeterminate ... the tool does not know", `unsupported` is
"cannot evaluate this check ... at all", and `skipped` is "not evaluated".

`_SEVERITY` is a different question and is untouched: its ordering is right
for `verdict_of`, since a run with a skipped check is not worse than one with
a failing check. What was wrong is `diff` reusing that ordering to name a
DIRECTION of change without saying which kind of change it was.
"""


def _values_equal(old: Any, new: Any) -> bool:
    """Equality under the adjudication epsilon, old value as reference.

    Exact float equality would report the ~1e-13 coordinate noise a different
    transform-composition order produces, burying signal (SPEC-diff.md §3).
    """
    if isinstance(old, list) and isinstance(new, list):
        return len(old) == len(new) and all(
            _values_equal(a, b) for a, b in zip(old, new, strict=True)
        )
    if (
        isinstance(old, int | float)
        and isinstance(new, int | float)
        and not isinstance(old, bool)
        and not isinstance(new, bool)
    ):
        return abs(float(new) - float(old)) <= epsilon(float(old))
    return old == new


def _value_delta(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any] | None:
    """The movement in a check's recorded `measurement.value`, or None.

    The twin of `_operands_delta`, and separate from it for the same reason
    the two are separate fields: one is what the check measured, the other is
    what its expression read, and an entry may carry both.

    **The tolerance keys on `phase`** (§3, #335). A parameter-phase value is
    read from the declared parameters before any engine runs, so it is the
    same kind of number an operand is and compares exactly; a geometry-phase
    value is measured off an exported artifact and gets `epsilon`.

    Not keyed on `measurement.exactness`, which looks like the right field and
    is not: `exact` distinguishes a point value from a bounded interval
    (`bounds` is required iff not `exact`) and says nothing about
    reproducibility. Measured on the mesh tier, `cube([120.3, 80.7, 40.1])`
    reports `exactness: "exact"` beside `120.30000305175781` — ±3.052e-06 of
    float32 quantisation, absorbed by `epsilon(120.3) = 1.303e-05`.
    `SPEC-backend.md` §5.2 permits the mesh tier to collapse that quantisation
    *because* this epsilon is wider than it, so keying here on `exactness`
    would withdraw the tolerance that permission rests on and report a rebuild
    of identical geometry as drift.

    `parameter` on EITHER side is enough. The exact comparison can only report
    more differences, never fewer, and §2's rule is that "no differences
    found" is the positive claim — so a pair that disagrees about its own
    provenance fails toward reporting. A report carrying no `phase` gets the
    epsilon: silence is not evidence of parameter provenance, so a value this
    comparison cannot place is treated as the kind that carries noise. Not a
    migration path — `phase` is REQUIRED, has been emitted unconditionally
    since the scaffolding commit, and `schema_version` has never left 1, so no
    report partspec has written lacks it. It governs a hand-written or
    third-party document, which is the same reason the id guards below exist:
    the comparator does not get to assume it produced its own input.
    """
    old_value = (old.get("measurement") or {}).get("value")
    new_value = (new.get("measurement") or {}).get("value")
    if "parameter" in (old.get("phase"), new.get("phase")):
        moved = old_value != new_value
    else:
        moved = not _values_equal(old_value, new_value)
    return {"old": old_value, "new": new_value} if moved else None


def _operands_delta(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any] | None:
    """The movement in a `requires` check's recorded operands, or None.

    Lifted out of the `drifted` branch so both callers share one comparison.
    `SPEC-diff.md` §3 names `operands` as *the* value of a `requires` check —
    it is what `measurement.value` is for every other kind — so it is subject
    to the same rule, and a second implementation of "did the operands move"
    is how the two branches would drift apart again (#326).

    **Compared exactly, and deliberately not through `_values_equal`.** The
    adjudication epsilon is sized for a measurement: §3 justifies it by
    transform-order noise at ~1e-13 and `SPEC-report.md` §3.3 sizes it for a
    binary-STL float32 round-trip. An operand is neither. `runner` builds
    these straight out of the contract's declared parameters
    (`expr.evaluate`'s namespace is `params[name]`), before any build, so two
    runs of one contract reproduce them bit for bit — and the predicate over
    them is adjudicated **exactly**, with no epsilon anywhere in `expr`.
    Borrowing the measurement tolerance therefore opened a dead band never
    narrower than seven orders of magnitude, and unbounded above, in which the
    predicate flips and the operands are called unmoved. Measured against that
    ~1e-13: `epsilon` is 1e-06 at the floor (7.0 orders), 3.6e-06 at 26 (7.6),
    1.01e-04 at 1000 (9.0) — the expression is minimised at 0, so seven is the
    floor and no operand magnitude falls below it. And the flip itself:
    `bore_d + 2 * wall <= plate_y` goes true -> false between `bore_d=26.0`
    and `26.000001`, inside `epsilon(26.0)`, and the entry printed the status
    change with none of the numbers — the very artifact #326 calls the defect
    (review round 1).
    """
    old_ops, new_ops = old.get("operands") or {}, new.get("operands") or {}
    return {"old": old.get("operands"), "new": new.get("operands")} if old_ops != new_ops else None


def _check_entry(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any] | None:
    """The difference one joined check pair contributes, or None."""
    base = {"id": new["id"], "kind": new["kind"]}
    # `source` is part of the claim: a bound whose citation was stripped —
    # same number, authority gone — is the quiet half of the weakening move,
    # and "no semantic differences" over it would be exactly the silence this
    # verb exists to refuse (#92).
    # `kind` and `expr` are claim fields too, and both were missing. Swapping
    # `genus` for `cavities` under one id turns "no through-holes" into "one
    # sealed void"; loosening `wall >= 2.0` to `wall >= 0.2` rewrites the
    # predicate outright. Both read as `identical`, exit 0, until PR #147 and
    # its review each found one. `expectation._claim_slug` already covered
    # kind and expr and said so in its docstring; the two agree now.
    claim_fields = [f for f in CLAIM_FIELDS if old.get(f) != new.get(f)]
    claim = (
        {
            "old": {f: old.get(f) for f in claim_fields},
            "new": {f: new.get(f) for f in claim_fields},
        }
        if claim_fields
        else None
    )
    value = _value_delta(old, new)
    operands = _operands_delta(old, new)
    # Every delta this comparison computed, in the order the artifact shows
    # them. One mapping, built once and spread onto whichever entry is
    # returned, so no branch can carry a subset of what was measured (§3).
    deltas = {
        name: delta
        for name, delta in (("claim", claim), ("value", value), ("operands", operands))
        if delta is not None
    }

    if old["status"] != new["status"]:
        # A status change does not get to hide what else moved: loosening a
        # limit until a failing check passes is the flagship weakening move,
        # and an entry saying only "fixed" would report the attack as an
        # improvement (#326). That reason is about what a reader is told, so
        # it never belonged to this branch alone — `deltas` above is the whole
        # of it, spread here and on the entry below alike.
        worse = _SEVERITY[Status(new["status"])] > _SEVERITY[Status(old["status"])]
        # Keyed on the NEW status alone: whether this report answers the check
        # is a fact about this report, and where it came from is already in
        # `status`. So `unsupported` -> `skipped` is recorded though it was
        # answered on neither side — the headline calls it `fixed` just the
        # same — and `pass` -> `skipped` is recorded though it is bucketed
        # `regressed`, because the fact is true of it (§3, #325).
        answered = (
            None
            if Status(new["status"]) in _CONCLUSIVE
            else {"old": Status(old["status"]) in _CONCLUSIVE, "new": False}
        )
        return {
            **base,
            "change": "regressed" if worse else "fixed",
            "status": {"old": old["status"], "new": new["status"]},
            **({} if answered is None else {"answered": answered}),
            **deltas,
        }

    if not deltas:
        return None

    # The bucket names the most significant thing that changed; it does not
    # decide what the entry may carry (§3). Written as one dict spread rather
    # than as per-branch attachment because the per-branch version is what
    # dropped things: each branch returned as soon as it knew its own NAME,
    # one delta into a chain of three, so `limit_changed` shipped the contract
    # edit without the drift it was covering and `drifted` shipped a moved
    # measurement without the operands beside it — both computed above, both
    # discarded (#330).
    return {
        **base,
        "change": "limit_changed" if claim is not None else "drifted",
        "status": old["status"],
        **deltas,
    }


_IRREDUCIBLE_GAPS = frozenset({"native_reads"})
"""The `unseen` tokens that never block the `identical` claim (#190 stage 3).

An irreducible gap is a property of the *tier*, not of the comparison: a C
extension can read a file with no Python event to observe it — measured on
`OCP.StlAPI_Reader`, zero `open` events for a real STL read — so
`native_reads` is present in every Python-tier report that will ever be
written. A signal constant across every possible input cannot discriminate
between two of them, and a verdict that cannot discriminate is not evidence.
Keying `inconclusive` on it made `diff` permanently indeterminate for every
contract wrapping a third-party library: fleet-01 measured 3/3 CadQuery
replicates indeterminate against 0/3 OpenSCAD ones, same command, same
version, and all three CadQuery agents wrote shell to suppress the exit 2
rather than go and look. A universally suppressed verdict protects less than
a universally printed caveat, so the honesty is kept by `summary_of` printing
this on every outcome, permanently — never by dropping it.

Every other token is **bounded** and blocks `identical`, *including one this
version does not recognise*. SPEC-report.md §8.3 makes that a MUST: closed
vocabularies leak, and an older reader of a newer report must go inconclusive
rather than silently ignore a gap it cannot name.
"""

_GAP_REMEDIES = {
    "imports_not_recorded": (
        "re-record the baseline with this version — run `partspec check` over the old "
        "side again and keep that report — so both sides carry an import map"
    ),
}
"""What a reader can actually DO about a bounded gap, where anything can be.

`SPEC-diff.md` §2 rule 3 says this comparison "names re-recording the baseline
as the fix"; through v0.7.4 it named the cause and stopped, in the output and
in the artifact alike, and this is the one exit 2 that every upgrading user
meets. Two releases in a row were about exactly that gap — naming a fault and
withholding its remedy — which is why the remedy travels with the token
instead of being appended to a sentence: the gap phrase ends where the caller
chains its own `so` clause (`SPEC-diff.md` §2 rule 3 fixes that sentence
verbatim), so a remedy spliced in there would read as the consequence of the
remedy rather than of the gap.

Most tokens are deliberately absent. `native_reads` is irreducible;
`unidentified_imports` is a property of how a package is distributed and no
partspec option closes it; `malformed_closure` and `unnamed_partial` are
reports that violate §8.3, whose fix is not a step this tool can name. An
invented remedy is worse than none — it sends a reader to do work that cannot
help, which is what the `imports_not_recorded` cause alone already did.
"""


def _gap_tokens(closure: dict[str, Any]) -> set[str]:
    """The gaps a closure names, synthesising them for pre-0.7.5 reports.

    `unseen` is the answer where the closure carries one. Where it does not,
    the closure was written before the question was asked (SPEC-report §8.3),
    and the absence rule applies **only where the field could have carried an
    answer** — which is the Python tier, `scope: "model_directory"`. There the
    synthesised `imports_not_recorded` reproduces today's exit 2 exactly,
    since `partial` was unconditionally true on that tier.

    Applying it to both tiers would have been wrong in the one direction that
    matters: a pre-0.7.5 OpenSCAD closure that was complete carries no
    `partial` key at all and yields exit 0 today, and flipping those users to
    exit 2 on upgrade is a false alarm about a question their tier never had.
    Stage 2 emits `"imports": {}` for OpenSCAD precisely so that absence stays
    unambiguous. So an old OpenSCAD closure is classified from the legacy
    fields it does carry, which is today's rule with the gaps given names.

    Three separate states are kept separate here, because collapsing any two
    of them opens a hole that fails **open**, and every one of these was a
    live defect in the first cut of this function:

    - a field **absent** is "written before the question was asked", and only
      that. It is what `imports_not_recorded` may claim, and claiming it for a
      0.7.5 report with a malformed field would name a false cause and a
      remedy — re-record the baseline — that would not help.
    - a field **present and the wrong shape** is a closure this reader cannot
      interpret. It is `malformed_closure`, and it must be reached from both
      tiers: routing it through the pre-0.7.5 branch let a non-list `unseen`
      on an OpenSCAD closure yield no tokens at all and exit 0, while the
      identical malformation on a Python closure blocked, via the `scope`
      guard. One malformation, two verdicts, and the permissive one on the
      tier with no other gap to catch it.
    - `partial` **disagreeing with `unseen`** violates §8.3's own invariant,
      `partial == bool(unseen)`. `partial: true` with `unseen: []` exited 0
      here while exiting 2 on v0.7.4 — the malformation closest to the real
      vocabulary was the one that escaped. The check is last and applies to
      every branch, so no route past it exists.
    """
    tokens: set[str] = set()
    unseen = closure.get("unseen")
    if _malformed_fields(closure):
        tokens.add("malformed_closure")
    if isinstance(unseen, list):
        tokens.update(str(token) for token in unseen)
        if "imports" not in closure:
            # `unseen` without `imports` is half an answer, and SPEC-report
            # §8.3 names both fields in the same breath.
            tokens.add("imports_not_recorded")
    elif "unseen" not in closure:
        if closure.get("scope") == "model_directory":
            tokens.add("imports_not_recorded")
        else:
            if closure.get("unresolved"):
                tokens.add("unresolved_includes")
            if closure.get("reads_external_data"):
                tokens.add("external_data_reads")
    if closure.get("partial") and not tokens:
        tokens.add("unnamed_partial")
    return tokens


def _malformed_fields(closure: dict[str, Any]) -> list[str]:
    """The stage-2 fields a closure carries in a shape §8.3 does not define.

    `preloaded` is here for the reason the other two are, and its omission
    failed in the one direction that matters: a non-list read as "nothing
    preloaded" let `_preloaded` return an empty set, which put the entry back
    in the appeared group and printed `inputs appeared: cadquery 2.8.0` at
    exit 0 — the exact positive claim the field exists to prevent, made out
    of a field the reader could not interpret.

    `reached` is here on the same argument turned the other way up. A non-list
    read as "nothing reached" is *safe* — it lifts nothing out of
    `unattributable` — but a malformed one is still a producer this reader
    cannot interpret, and letting it through would mean a later field of the
    same shape got the benefit of a precedent it should not have.

    Presence is what is checked, never absence, which is what keeps this off
    every older producer: a pre-0.7.5 closure carries no `preloaded`, and
    neither does a 0.7.5 OpenSCAD one, whose render imports nothing (§8.3
    rule 7). Absence dates nothing and means nothing here; only a producer
    that writes the field in a shape §8.3 does not define is refused, and no
    released partspec ever has.
    """
    return [
        field
        for field, shape in (
            ("unseen", list),
            ("imports", dict),
            ("preloaded", list),
            ("reached", list),
        )
        if field in closure and not isinstance(closure[field], shape)
    ]


def _sides_label(sides: set[str]) -> tuple[str, bool]:
    """ "the old report" / "the new report" / "the old and new reports", plural."""
    if len(sides) == 2:
        return "the old and new reports", True
    return f"the {next(iter(sides))} report", False


def _unidentified_names(sides: set[str], closures: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        {
            name
            for side in sides
            for name, entry in (closures[side].get("imports") or {}).items()
            if isinstance(entry, dict) and entry.get("identity") == "unidentified"
        }
    )


def _gap_phrase(token: str, sides: set[str], closures: dict[str, dict[str, Any]]) -> str:
    """What a gap token says to a reader, named rather than counted.

    The unknown-token branch is the fail-closed one: it states the token it
    could not interpret, because "this diff is older than the report it read"
    is a different remedy from any of the gaps above it.
    """
    label, plural = _sides_label(sides)
    if token == "native_reads":
        return "files read inside C extensions — irreducible on the Python tier"
    if token == "unidentified_imports":
        names = _unidentified_names(sides, closures)
        if not names:
            return "an import could not be identified, and the map does not say which"
        # The remedy clause is there because there is no remedy to look for,
        # and a reader who hit this would otherwise go hunting for a flag: the
        # gap is a property of how that package is distributed, not of any
        # setting. Measured frequency across five fleet venvs is zero.
        if len(names) == 1:
            return (
                f"1 import could not be identified ({names[0]}: a namespace package, "
                "which has no file on disk for partspec to hash, and no partspec option "
                "closes that)"
            )
        return (
            f"{len(names)} imports could not be identified ({_bounded(names)}: namespace "
            "packages, which have no file on disk for partspec to hash, and no partspec "
            "option closes that)"
        )
    if token == "external_data_reads":
        # Phrased as a fact about THIS RUN, not about the engine, because it
        # has to stay true of a report written before 0.7.7 — those carry no
        # `engine_inputs` at all, and saying "the engine did not report" would
        # assert something about a render this reader has no record of. The
        # remedy is named because since #226 there is one: the gap survives
        # only where the engine's own dependency output is missing or partial.
        return (
            "the model reads external data (import()/surface()) and this run carries no "
            "complete engine-reported input set, so which files those were is unrecorded "
            "(a successful render on an engine that accepts -d records them)"
        )
    if token == "unresolved_includes":
        return "the model include()s or use()s files partspec could not find on any search path"
    if token == "imports_not_recorded":
        return (
            f"{label} {'were' if plural else 'was'} written before partspec recorded imports "
            f"(0.7.4 or earlier): {'their' if plural else 'its'} source identity covers one "
            "directory"
        )
    if token == "unnamed_partial":
        return (
            f"{label} {'carry' if plural else 'carries'} a closure marked partial without "
            "naming what it missed"
        )
    if token == "malformed_closure":
        fields = sorted({field for side in sides for field in _malformed_fields(closures[side])})
        return (
            f"{label} {'carry' if plural else 'carries'} a source closure this diff cannot "
            f"read ({' and '.join(fields)} {'is' if len(fields) == 1 else 'are'} not the shape "
            "SPEC-report.md §8.3 defines), and a closure that cannot be read is read as a gap"
        )
    return (
        f"{label} name{'' if plural else 's'} a gap this diff does not recognise ({token}), "
        "and an unrecognised gap is read as a gap"
    )


def _import_moved(old: Any, new: Any) -> bool:
    """Whether one distribution's entry describes a different build input.

    `identity` is part of the comparison rather than a gap: an entry that is
    `metadata` on one side and `content` on the other is an ordinary install
    against an editable one or a `sys.path` checkout, and that genuinely *is*
    a different build input. The two digests are also over different things —
    RECORD rows against bytes on disk — so they cannot be compared for
    sameness, and `changed` is the only honest reading.

    `files` is compared too, though `imports._content_digest` derives both
    from one walk and they cannot honestly disagree. Where they do, the entry
    is self-inconsistent, and reading "all unchanged" off the digest of a
    tree whose file count moved is the failing-open direction.
    """
    if not isinstance(old, dict) or not isinstance(new, dict):
        return old != new
    return any(old.get(key) != new.get(key) for key in ("identity", "version", "digest", "files"))


def _imports_delta(
    old_closure: dict[str, Any] | None, new_closure: dict[str, Any] | None
) -> dict[str, Any]:
    """Compare the `imports` maps entry by entry, in three groups.

    The split is the one `_packages_delta` already draws, for the same reason
    and one layer down (design risk R4): a distribution whose *version moved*
    is a changed build input and explains a moved measurement, while one
    present on a single side is usually two machines resolving different
    transitive dependency sets. Folding them together leaves the reader to
    separate them by hand.

    A side with no usable map yields `uncomparable`, never an empty delta: an
    omission would read as "no build input moved", which is a claim this
    comparison did not make.

    `unattributable` names the entries whose appearance or disappearance
    either side already said it could not attribute to its own target
    (`preloaded`, SPEC-report §8.3 rule 7). They stay in `added`/`removed` —
    they really are on one side only — but they are the one movement this
    comparison must not report as a *finding*, because it cannot tell which of
    two things produced it: a part behind another one in a batch inherits its
    imports, AND a part that genuinely started importing a library the earlier
    target also loads looks identical from here. Measured: a follower whose
    model began importing a shared module, at batch position 2 of 2 in both
    runs, is a real new build input landing in exactly this set. What this
    field carries is the inability, never a cause.

    It does not follow that the closure is `same`. The two reports recorded
    different maps, which is an observed fact and is what `closure: "changed"`
    states; whose import it was is the separate question this field answers.
    The batch-contamination case therefore reports `changed` too — 44 entries
    against 38, nothing in the model moved — and that is correct: the recorded
    maps did differ, and what the tool cannot say is whether the part's inputs
    did. The summary line carries that distinction in words.

    Only `added` and `removed` can be affected. A `changed` entry is present
    on both sides with something moved between them, which is a fact about the
    distribution whoever loaded it.
    """
    old_imports = (old_closure or {}).get("imports")
    new_imports = (new_closure or {}).get("imports")
    if not isinstance(old_imports, dict) or not isinstance(new_imports, dict):
        missing = [
            side
            for side, entries in (("old", old_imports), ("new", new_imports))
            if not isinstance(entries, dict)
        ]
        where = "both sides" if len(missing) == 2 else f"the {missing[0]} side"
        return {
            "uncomparable": f"no source_closure.imports map on {where}, so whether an "
            "imported distribution moved is unknown"
        }
    added = {name: e for name, e in sorted(new_imports.items()) if name not in old_imports}
    removed = {name: e for name, e in sorted(old_imports.items()) if name not in new_imports}
    # An entry this target's own module graph provably reached is ITS build
    # input, whoever imported it first (#216). `preloaded` records an inability
    # to attribute; `reached` is the part of that inability the object graph
    # can actually settle, so it is subtracted rather than added to. An entry
    # that is merely absent from `reached` is not proven unreached and stays
    # exactly where it was.
    carried = (_preloaded(old_closure) | _preloaded(new_closure)) - (
        _reached(old_closure) | _reached(new_closure)
    )
    return {
        "changed": {
            name: {"old": entry, "new": new_imports[name]}
            for name, entry in sorted(old_imports.items())
            if name in new_imports and _import_moved(entry, new_imports[name])
        },
        "added": added,
        "removed": removed,
        "unattributable": sorted((added.keys() | removed.keys()) & carried),
    }


def _reached(closure: dict[str, Any] | None) -> set[str]:
    """What a closure says this target's own modules provably reached.

    Absent on every report before this field existed, and on the OpenSCAD tier,
    whose render imports nothing. Absence means the question was not asked, and
    an empty set is the right reading of that here: nothing is lifted out of
    `unattributable`, which is exactly what those readers already did.
    """
    names = (closure or {}).get("reached")
    return {str(name) for name in names} if isinstance(names, list) else set()


def _preloaded(closure: dict[str, Any] | None) -> set[str]:
    """What a closure says was already loaded when its target began.

    Absent on the OpenSCAD tier, whose render is a subprocess that imports
    nothing, and on every report written before 0.7.5 — both of which already
    reach this comparator through `imports`, so absence needs no synthesised
    gap here. Empty means the target ran first, or alone.
    """
    names = (closure or {}).get("preloaded")
    return {str(name) for name in names} if isinstance(names, list) else set()


def _attributed(imports: dict[str, Any], group: str) -> dict[str, Any]:
    """One group of the imports delta, minus what no side could attribute."""
    carried = set(imports.get("unattributable") or ())
    return {name: e for name, e in (imports.get(group) or {}).items() if name not in carried}


def _covered_clause(
    new_closure: dict[str, Any], imports: dict[str, Any], digest_moved: bool
) -> str:
    """What the comparison *did* cover — the other half of naming the gaps."""
    scope = "model directory" if new_closure.get("scope") == "model_directory" else "source closure"
    files = new_closure.get("files")
    where = (
        f"{scope} ({files} file{'' if files == 1 else 's'})" if isinstance(files, int) else scope
    )
    parts = [f"{where}, changed" if digest_moved else where]
    entries = new_closure.get("imports")
    if isinstance(entries, dict) and entries and "uncomparable" not in imports:
        groups = (("changed", "changed"), ("added", "appeared"), ("removed", "disappeared"))
        counts = [
            f"{len(attributed)} {word}"
            for group, word in groups
            if (attributed := _attributed(imports, group))
        ]
        if carried := imports.get("unattributable"):
            counts.append(f"{len(carried)} not attributable")
        parts.append(
            f"{len(entries)} imported distribution{'' if len(entries) == 1 else 's'}, "
            + (", ".join(counts) if counts else "all unchanged")
        )
    return "; ".join(parts)


def _moved_phrases(
    new_closure: dict[str, Any], imports: dict[str, Any], digest_moved: bool
) -> list[str]:
    """What this comparison actually observed move, named for a message.

    Counts rather than names for the imports, because `_imports_clause` puts
    the names on the same line; the point here is that the *reason* string
    stands up on its own in the artifact, where no clause follows it.

    An unattributable entry is phrased as the qualification it is rather than
    counted as movement: it belongs here because something was observed and
    the reason must not then claim nothing was seen, and it is worded apart
    from the three groups because what was observed cannot be attributed —
    which is a statement about this comparison, not about the batch.
    """
    scope = (
        "the model directory digest"
        if new_closure.get("scope") == "model_directory"
        else "the source closure digest"
    )
    phrases = [f"{scope} moved"] if digest_moved else []
    if "uncomparable" not in imports:
        for group, noun, verb in (
            ("changed", "imported distribution", "moved"),
            ("added", "import", "appeared"),
            ("removed", "import", "disappeared"),
        ):
            if count := len(_attributed(imports, group)):
                phrases.append(f"{count} {noun}{'' if count == 1 else 's'} {verb}")
        if count := len(imports.get("unattributable") or ()):
            phrases.append(
                f"{count} import{'' if count == 1 else 's'} on one side only cannot be "
                "attributed to either target"
            )
    return phrases


def _closure_delta(old_part: dict[str, Any], new_part: dict[str, Any]) -> dict[str, Any]:
    """The state of the source closure, the gaps by class, and what moved.

    SPEC-diff §2 rule 3, rewritten by #190 stage 3: the old rule keyed
    `inconclusive` on the `partial` boolean, which the Python tier sets
    unconditionally, so every comparison of a contract wrapping an installed
    library was indeterminate whatever it found. It now keys on the *class* of
    the named gaps — bounded blocks the claim, irreducible is printed — and
    compares the `imports` map alongside the digest.
    """
    old_closure = old_part.get("source_closure")
    new_closure = new_part.get("source_closure")
    old_closure = old_closure if isinstance(old_closure, dict) else None
    new_closure = new_closure if isinstance(new_closure, dict) else None
    imports = _imports_delta(old_closure, new_closure)

    if old_closure is None or new_closure is None:
        # One run recorded a closure and the other did not — or neither did,
        # the ordinary v0.1.0 upgrade path for every Python part, since its
        # closure landed after the tag. "Changed" would be a claim about the
        # source and nothing here supports one; calling it changed let the
        # identical claim through unearned (PR #88 review, B1). Both-absent is
        # the same case and was returning early past this rule until #88, at
        # which point `identical` rested on `source_digest` alone — the
        # overclaim SPEC-report §8.3 reversed itself to prevent.
        missing = [
            side
            for side, closure in (("old", old_closure), ("new", new_closure))
            if closure is None
        ]
        where = (
            "neither report carries a source closure"
            if len(missing) == 2
            else f"the {missing[0]} report carries no source closure"
        )
        # No trailing `so` clause: the caller appends one, and this branch
        # read "…beyond its entry file, so nothing this diff can see changed"
        # — two consequences chained off one observation.
        return {
            "state": "inconclusive",
            "blocking": [
                f"{where}, leaving source_digest — one file — as the whole of the input's identity"
            ],
            "moved": [],
            "digest_changed": None,
            "imports": imports,
            "unseen": {"irreducible": {}, "bounded": {}},
            "remedies": [],
            "covered": None,
        }

    closures = {"old": old_closure, "new": new_closure}
    sides_of: dict[str, set[str]] = {}
    for side, closure in closures.items():
        for token in _gap_tokens(closure):
            sides_of.setdefault(token, set()).add(side)
    classified = {
        token: _gap_phrase(token, sides, closures) for token, sides in sorted(sides_of.items())
    }
    irreducible = {t: p for t, p in classified.items() if t in _IRREDUCIBLE_GAPS}
    bounded = {t: p for t, p in classified.items() if t not in _IRREDUCIBLE_GAPS}

    digest_moved = old_closure.get("digest") != new_closure.get("digest")
    # Every recorded difference, attributable or not. `changed` is a statement
    # about what the two reports RECORDED, and two maps that differ differ;
    # `unattributable` is the statement about attribution, and neither field
    # needs the other's job. Suppressing here made the artifact assert `same`
    # over a difference it was carrying in `imports.added` in the same object
    # — the B2 finding of the stage-3 review, one field over: what the
    # comparison actually saw stays in the artifact, and the verdict rule
    # decides separately what to do about it. `different` is computed from
    # checks alone and only `inconclusive` is outcome-bearing, so a `changed`
    # closure falls through to `identical` and no exit code moves.
    imports_moved = "uncomparable" not in imports and any(
        imports[group] for group in ("changed", "added", "removed")
    )
    if bounded:
        state = "inconclusive"
    elif digest_moved or imports_moved:
        state = "changed"
    else:
        state = "same"

    return {
        "state": state,
        "blocking": list(bounded.values()),
        # Movement is kept even when a bounded gap discards it from the
        # verdict. Dropping it from the verdict is the rule; dropping it from
        # the message let the comparison say "nothing this diff can see
        # changed" one line above a line naming what moved, and dropping it
        # from the artifact left a consumer keying on `source.closure` blind
        # to input movement on every inconclusive comparison.
        "moved": _moved_phrases(new_closure, imports, digest_moved),
        "digest_changed": digest_moved,
        "imports": imports,
        "unseen": {"irreducible": irreducible, "bounded": bounded},
        # Only for the gaps that HAVE one, and only for the gaps that blocked:
        # a remedy printed under a caveat that reached no verdict is work
        # suggested for a state nobody has to act on.
        "remedies": [_GAP_REMEDIES[token] for token in bounded if token in _GAP_REMEDIES],
        # Only where a side knows what coverage means, so two pre-0.7.5
        # reports reach the same outcome and exit code with no coverage block
        # invented for them.
        "covered": _covered_clause(new_closure, imports, digest_moved)
        if any("unseen" in closure for closure in closures.values())
        else None,
    }


def _split_target(contract: str) -> tuple[str, str | None]:
    """A `part.contract` value as (module, factory), the factory `None` when
    the value names none.

    `Target.parse`'s rule: partition on the LAST colon, and take the tail only
    when it is an identifier — so a contract filename that contains one
    (`rev2:spec.py`) is a whole filename and not module `rev2`. One deliberate
    divergence, and it is in the safe direction: an empty head (`:make`) is
    read here as naming no factory, where `Target.parse` accepts it as an empty
    path. Nothing partspec writes takes that shape, and reading it as "no
    factory" declines to compare rather than comparing something unintended.
    """
    head, sep, tail = contract.rpartition(":")
    if head and sep and tail.isidentifier():
        return head, tail
    return contract, None


def _contract_target(old_part: dict[str, Any], new_part: dict[str, Any]) -> dict[str, Any]:
    """What the two `part.contract` values say about which target ran (#343).

    Three findings, and only the first is outcome-bearing.

    **`target_changed` — the FACTORY differs, both sides naming one.** This is
    the whole of what #343 evidences: two factories in one module return parts
    with the same `id`, and the contract digest is module-scoped, so the `part`
    blocks were byte-identical until #297 put the symbol in this field. `diff`
    joins on `part.id` and read the field for nothing, so `same.py:imperial`
    against `same.py:metric` compared `identical` at exit 0.

    **`module_changed` — the module PATH differs. Recorded, never
    outcome-bearing**, and the narrowness is the point. Comparing the whole
    string made a *rename* a difference: measured on two byte-identical
    contract files, `single.py:spacer` against `renamed.py:spacer`, equal
    digests and nothing else moved, reported `different` at exit 1. That
    contradicts the principle §3 already states for the closure digest — it
    identifies contents, not layout — and it turns a committed-baseline CI
    recipe red for a file rename.

    **`target_incomparable` — one side names no factory.** A single-factory
    module resolved without one being typed before this release, so `spec.py`
    and `spec.py:spacer` may be two spellings of ONE run; an unsuffixed side
    cannot say which target it was, so no change may be claimed from it in
    either direction. That is a **stated gap**, not a match: §2's opening makes
    "no differences found" a positive claim rather than a fallthrough, so the
    summary says the comparison declined rather than saying nothing. It does
    not reach the outcome, and §3 gives the argument on its own terms rather
    than borrowing §2 rule 3's taxonomy, which classifies the closure's
    `unseen` vocabulary and reaches nothing else (PR #353 review, R2).
    """
    old_target, new_target = old_part.get("contract"), new_part.get("contract")
    if not (isinstance(old_target, str) and isinstance(new_target, str)):
        return {}
    if old_target == new_target:
        return {}
    old_module, old_factory = _split_target(old_target)
    new_module, new_factory = _split_target(new_target)

    found: dict[str, Any] = {}
    if old_factory is not None and new_factory is not None:
        if old_factory != new_factory:
            found["target_changed"] = {"old": old_target, "new": new_target}
    else:
        found["target_incomparable"] = {"old": old_target, "new": new_target}
    if old_module != new_module:
        found["module_changed"] = {"old": old_module, "new": new_module}
    return found


def _packages_of(environment: Any) -> dict[str, Any] | None:
    """The `environment.packages` map, or None when there is nothing to compare."""
    if not isinstance(environment, dict):
        return None
    packages = environment.get("packages")
    return packages if isinstance(packages, dict) else None


_LEGACY_PACKAGES = frozenset({"build123d", "cadquery", "cadquery-ocp", "trimesh", "manifold3d"})
"""What `environment.packages` held before #211 widened it to every install.

Kept as data because it is the only thing that tells the two halves of an
`added` group apart on the first comparison after an upgrade: a name outside
this set is one the old field COULD NOT have recorded whatever was installed,
while one inside it was genuinely absent from that environment. Reporting all
of them as "recorded for the first time" would misname the second kind —
`trimesh` installed since the baseline is a real appearance, and the whole
point of the split is that a reader can act on the difference.
"""


def _first_recorded(added: dict[str, Any], old_predates_widening: bool) -> list[str]:
    """The `added` names that are the field widening rather than an install.

    `SPEC-diff.md` §3 and the #211 changelog entry both say of this case
    "nothing was installed; re-record the baseline to clear it", and the
    comparator said `packages appeared: PyJWT 2.13.0, PyYAML 6.0.3, +107 more`
    — 109 positive findings, on the first diff every upgrading user runs. It
    could always tell: an old report whose closure carries no `imports` was
    written before 0.7.5, which `_gap_tokens` already reads for the Python
    tier, and this reads it for both because the widening was not tier-bound.
    """
    if not old_predates_widening:
        return []
    return [name for name in added if name not in _LEGACY_PACKAGES]


def _predates_imports(report: dict[str, Any]) -> bool:
    """Whether this report was written before 0.7.5 recorded `imports`.

    Structural rather than a `tool.version` comparison: SPEC-report §8.3
    already rules that a closure with no `imports` was written before the
    question was asked, and a version string is a claim the report makes about
    itself while the missing field is the evidence. A report carrying no
    closure at all cannot be dated this way, and is not claimed to be.
    """
    closure = report.get("part", {}).get("source_closure")
    return isinstance(closure, dict) and "imports" not in closure


def _packages_delta(
    old_env: Any, new_env: Any, *, old_predates_widening: bool = False
) -> dict[str, Any] | None:
    """Compare `environment.packages` — the field SPEC-report §8 rule 2 says in
    bold MUST NOT be excluded, and which this comparator excluded entirely.

    It is the field that distinguishes "a trimesh upgrade moved this number"
    from "the design changed". Without it a dependency bump produced a
    `different` verdict with nothing on the page to explain it, and the reader
    had to guess which of the two had happened — the guess the field exists to
    remove.

    Three groups, not one, because two facts are being reported and they are
    not the same fact. A version that *moved* is a change to a build input and
    explains a moved measurement. A package that *appeared or disappeared* is
    usually two machines resolving different transitive dependency sets — a CI
    runner against a laptop — and explains nothing on its own. Folding them
    together would make the reader do that separation by hand.

    Returns None when nothing differs, matching the other environment keys,
    which are reported only when they changed. When a side carries no usable
    map the result is NOT None: an omission would read as "no package moved",
    which is a claim this comparison did not make.

    `old_predates_widening` splits `first_recorded` out of `added` — the names
    the pre-0.7.5 five-name field could never have carried. They stay in
    `added`, because they are installed on one side only and that is what the
    group means; what they are not is an installation, and the summary says so.
    """
    old_packages, new_packages = _packages_of(old_env), _packages_of(new_env)
    if old_packages is None or new_packages is None:
        missing = [
            label
            for label, packages in (("old", old_packages), ("new", new_packages))
            if packages is None
        ]
        where = "both sides" if len(missing) == 2 else f"the {missing[0]} side"
        return {
            "uncomparable": f"no environment.packages map on {where}, so whether a "
            "dependency moved is unknown"
        }
    changed = {
        name: {"old": version, "new": new_packages[name]}
        for name, version in sorted(old_packages.items())
        if name in new_packages and new_packages[name] != version
    }
    added = {name: v for name, v in sorted(new_packages.items()) if name not in old_packages}
    removed = {name: v for name, v in sorted(old_packages.items()) if name not in new_packages}
    if not (changed or added or removed):
        return None
    return {
        "changed": changed,
        "added": added,
        "removed": removed,
        "first_recorded": _first_recorded(added, old_predates_widening),
    }


def diff_reports(old: dict[str, Any], new: dict[str, Any], *, tool_version: str) -> dict[str, Any]:
    """Compare two parsed reports. Raises DiffUsageError on unusable input."""
    for label, report in (("old", old), ("new", new)):
        if not isinstance(report, dict):
            raise DiffUsageError(f"the {label} input is not a report (top level is not an object)")
        if report.get("schema_version") != SCHEMA_VERSION:
            raise DiffUsageError(
                f"the {label} report has schema_version {report.get('schema_version')!r}; "
                f"this diff understands report schema {SCHEMA_VERSION} and must not "
                f"best-effort parse anything else (SPEC-report.md 7.1)"
            )

        # `schema_version` says the document is readable, not that it is a
        # report: `measure` and `render` deliberately carry the same version
        # and the same `tool`/`part` identity prefix (SPEC-report.md's Scope
        # names them), so both walked through that check, read `checks` as
        # `[]`, and skipped the `counts.total` invariant for want of a
        # `counts` — and two `measure` payloads of a genuinely different part
        # compared clean at exit 0. "No differences found" is a positive claim (SPEC-diff.md 2)
        # and a document that declares nothing cannot support it; being
        # parseable is not being a report (#292).
        #
        # Keyed on what a report HAS rather than on what the other payloads
        # are, because the set of things carrying this prefix is open and a
        # guard naming today's two members would pass tomorrow's third.
        #
        # A null counts as absent, and that is not tidiness: `"counts": null`
        # reached `report.get("counts", {}).get("total")` and raised
        # `AttributeError: 'NoneType' object has no attribute 'get'`. The CLI's
        # catch-all turned that into exit 64, so the code was right and the
        # diagnosis was a Python type name — `these inputs are not well-formed
        # reports (AttributeError: 'NoneType' object has no attribute 'get')`.
        # Naming the defect is this guard's job, the same way the `status`
        # guard below took one off the catch-all.
        if missing := [field for field in ("verdict", "counts") if report.get(field) is None]:
            absent = ", ".join(
                f"no `{field}`" if field not in report else f"a null `{field}`" for field in missing
            )
            # The measure/render sentence is a CAUSE, and §2 rule 3's wording
            # rule applies to it: state the inability, do not state a cause you
            # do not know. A genuine report with `verdict` stripped still
            # carries `checks`, `counts`, `error`, `hint` — and telling its
            # author it is probably a `measure` payload is a confident
            # diagnosis of the wrong defect, contradicted by the field list in
            # the same sentence. That is the shape the id-less-check guard
            # below already carries a comment about (round-1 review).
            cause = (
                "a `measure` or `render` payload carries the same schema_version and "
                "declares no claim, so comparing it would answer `identical` for two "
                "files that never made one"
                if "checks" not in report
                else "a report carries them and this one does not; what it is instead, "
                "this comparison cannot say"
            )
            raise DiffUsageError(
                f"the {label} input is not a check report: {absent}. `diff` compares "
                f"two `partspec check` reports; {cause}. Its top-level fields: "
                f"{', '.join(sorted(report)) or 'none at all'}"
            )
        # `or []` so a literal `"checks": null` reaches the branches below
        # rather than raising `TypeError: object of type 'NoneType' has no
        # len()` out of the counts check. Bound once, above the first reader,
        # because two readers spelling the fallback differently is how the
        # first one ended up not having it.
        #
        # Named `raw_checks`, not `entries`: this function rebinds `entries`
        # further down to the diff's own output list, and one name for two
        # meanings in one scope is a trap for the next edit (PR #157 review).
        raw_checks = report.get("checks") or []

        total = report.get("counts", {}).get("total")
        if total is not None and total != len(raw_checks):
            # counts.total is redundant by construction in an honest report;
            # an input that violates its own invariant is corrupt, and no
            # claim over corrupt input is earned.
            raise DiffUsageError(
                f"the {label} report is corrupt: counts.total is {total} but it "
                f"carries {len(raw_checks)} checks"
            )

        # Everything below is ONE precondition on the join at the bottom of this
        # function: `{c["id"]: c}` must be keyable, and must key each check to
        # itself. Split into branches only so the message names the actual defect.
        if not_objects := [c for c in raw_checks if not isinstance(c, dict)]:
            raise DiffUsageError(
                f"the {label} report has {len(not_objects)} entr(y/ies) in `checks` that "
                f"are not objects (first: {not_objects[0]!r}); every check is an object "
                f"with an `id` (SPEC-report.md 7.1)"
            )
        ids = [c.get("id") for c in raw_checks]

        # A check with no id is a MISSING FIELD, not a collision, and saying so
        # matters: mapping it to None first made two id-less checks report as
        # "None appears more than once", which is a confident diagnosis of the
        # wrong defect. Before this guard the join raised `KeyError: 'id'` and
        # the CLI rendered "not well-formed reports", which was less precise but
        # not misleading (PR #157 review).
        absent = sum(1 for i in ids if i is None)
        if absent:
            raise DiffUsageError(
                f"the {label} report has {absent} check(s) with no `id`. "
                f"`checks[].id` is REQUIRED and is the key this comparison joins on "
                f"(SPEC-report.md 7.1)"
            )

        # `status` must be a STRING too, and for a sharper reason than tidiness:
        # the summary reads it into a SET to say what the claims did, so a
        # non-string status equal on BOTH sides sailed past every comparison —
        # `_check_entry` only asks `!=` — and then raised `TypeError: cannot
        # use 'list' as a set element` out of `summary_of`, AFTER the complete
        # diff artifact had been written to stdout. That is exit 4 with a
        # traceback where `SPEC-diff.md` §2 and this module's own contract
        # promise 64 for a malformed report, and where `main` answered 0
        # (round-3 review of #239).
        #
        # Guarded here rather than filtered at the read: the read is one of
        # several, and a report whose status is not a status is unusable input
        # by the same argument `counts.total` is guarded under.
        bad_status = [c.get("status") for c in raw_checks if not isinstance(c.get("status"), str)]
        if bad_status:
            raise DiffUsageError(
                f"the {label} report has {len(bad_status)} check(s) whose `status` is not "
                f"a string (first: {bad_status[0]!r}); SPEC-report.md 7.1 types it as one "
                f"of {', '.join(sorted(s.value for s in Status))}"
            )

        # And the id must be a STRING, which SPEC-report §7.1 types it as.
        #
        # `CheckResult.id: str` is an annotation, not an enforcement, so that
        # alone did not make this safe to assume: `p.param("wall", min=2.0,
        # id=3)` was accepted by authoring and `check` wrote `"id": 3`, which
        # this branch would then have refused at 64 — blaming the artifact for a
        # contract error. `Part._add` now refuses a non-string id where it is
        # written, so nothing partspec emits reaches here (PR #157 review).
        #
        # This replaces a `repr`-keyed uniqueness count, which was a fix for
        # mixed-type and unhashable ids that reopened the very hole this guard
        # exists to close. `repr` compares ids by their RENDERING while the join
        # keys a dict on their VALUE, and the two disagree wherever Python's
        # `==`/`hash` merge distinct JSON literals: `1` and `1.0` (and `true`
        # and `1`) render differently, pass the count, and then collapse onto
        # one another in the join. Measured: a four-check report with ids `1`
        # and `1.0` was joined as three checks, no refusal, exit 1 — the same
        # confident wrong answer described above, reached through the guard
        # meant to prevent it (PR #157 review).
        #
        # Refusing the type instead of routing around it fixes all three at
        # once: a non-string never reaches the sort (no TypeError on mixed
        # types), never reaches the set (no TypeError on an unhashable list),
        # and cannot alias by numeric equality. `isinstance(True, str)` is
        # False, so booleans are covered.
        if malformed := [i for i in ids if not isinstance(i, str)]:
            raise DiffUsageError(
                f"the {label} report has check ids that are not strings "
                f"({', '.join(map(repr, malformed))}); `checks[].id` is typed as a string "
                f"and is the key this comparison joins on (SPEC-report.md 7.1)"
            )

        # Ids must be unique, for the same reason and in the same class (#148).
        # The comparator joins on id, so a report carrying two checks under one
        # id does not merely lose information — it produces a CONFIDENT WRONG
        # answer. Measured before this guard, on the input
        # `test_a_report_with_two_checks_under_one_id_is_corrupt_input` builds:
        # the displaced `param_range` claim vanished from the analysis entirely
        # and the survivor was reported as `limit_changed` from
        # `{"kind": "param_range"}` to `{"kind": "genus"}` — two unrelated
        # claims diffed as one, exit 1.
        #
        # `counts.total` cannot catch this: both reports carried the number of
        # checks they said they did. Uniqueness is a separate invariant.
        #
        # `Part._add` already refuses an id clash at authoring time, so partspec
        # cannot emit such a report. That is exactly why this belongs here: the
        # report schema is the stable product surface (D5), `diff` consumes
        # whatever is handed to it, and a guarantee that holds only for reports
        # we produced is not one the comparator may assume.
        #
        # Counted by value, the same way the join keys — so the guard and the
        # join agree by construction rather than by two implementations
        # happening to match. Safe now that every id is known to be a string.
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise DiffUsageError(
                f"the {label} report is corrupt: check ids must be unique because the "
                f"comparison joins on them, and these appear more than once: "
                f"{', '.join(repr(i) for i in duplicated)}. Two different claims under "
                f"one id are compared as if they were the same claim."
            )
    old_part, new_part = old.get("part", {}), new.get("part", {})
    if old_part.get("id") != new_part.get("id"):
        raise DiffUsageError(
            f"these reports describe different parts ({old_part.get('id')!r} vs "
            f"{new_part.get('id')!r}); diff compares two runs of one part"
        )

    indeterminate: list[dict[str, str]] = []
    for label, report in (("old", old), ("new", new)):
        if report.get("verdict") == "error":
            indeterminate.append(
                {
                    "code": "input_error",
                    "reason": f"the {label} report's run did not complete (verdict: "
                    f"error); its checks measured nothing to compare",
                }
            )

        # `or []` matching the validation loop's fallback: `"checks": null` is a
        # real shape a hand-written report can take, and spelling the fallback two
        # ways is how the counts check ended up raising TypeError past a guard that
        # had already handled it.

    old_checks = {c["id"]: c for c in old.get("checks") or []}
    new_checks = {c["id"]: c for c in new.get("checks") or []}
    removed = [check_id for check_id in old_checks if check_id not in new_checks]
    added = [check_id for check_id in new_checks if check_id not in old_checks]
    entries = [
        entry
        for check_id, old_check in old_checks.items()
        if check_id in new_checks
        for entry in [_check_entry(old_check, new_checks[check_id])]
        if entry is not None
    ]

    closure = _closure_delta(old_part, new_part)
    contract_target = _contract_target(old_part, new_part)
    verdict_changed = old.get("verdict") != new.get("verdict")
    # A `changed` closure is deliberately NOT a difference, and this line is
    # the decision (#190 stage 3). When the library moved and no check moved
    # with it, the outcome is `identical` at exit 0 with the moved
    # distribution named on the summary line — because OpenSCAD already gets
    # exit 0 for a changed `.scad` closure with no moved check, and a
    # different rule for Python would rebuild the arm-A/arm-B asymmetry #190
    # exists to remove.
    # `target_changed` is outcome-bearing where the digests are not, and the
    # distinction is what the two fields ARE. A digest says the module's bytes
    # moved, over a module that may declare several parts; the target says
    # which part was asked for, and two answers to that question are two
    # different questions, not one question answered twice (#343).
    #
    # The FACTORY alone, never the whole `<module>:<factory>` string: a moved
    # module path is a rename, and reporting one as a difference contradicts
    # what §3 says of the closure digest — it identifies contents, not layout.
    # Measured: two byte-identical contract files under different names,
    # `single.py:spacer` vs `renamed.py:spacer`, equal digests, reported
    # `different` at exit 1 until this was narrowed (PR #353 review, F2).
    different = bool(
        removed or added or entries or verdict_changed or contract_target.get("target_changed")
    )
    if indeterminate:
        outcome = "indeterminate"
    elif different:
        outcome = "different"
    elif closure["state"] == "inconclusive":
        # The gap-class rule (SPEC-diff.md §2 rule 3): a bounded gap means
        # "nothing we looked at changed". Claiming `identical` on that
        # evidence is silence-as-success at the provenance layer.
        #
        # Two shapes, because there are two situations and one sentence
        # cannot honestly serve both. Through v0.7.4 `digest != digest`
        # returned `"changed"` BEFORE the partial check, so the sentence
        # below was only ever reachable with matching digests and was always
        # true. Removing that short-circuit — correctly, since `changed` was
        # never outcome-bearing and the exit 0 it produced was unearned — put
        # the sentence on comparisons that had demonstrably seen movement,
        # one line above the line naming what moved. The load-bearing
        # sentence is unchanged and stays verbatim (#190 is explicit that it
        # must); it is now only uttered where it is true.
        indeterminate.append(
            {
                "code": "partial_closure",
                "reason": (
                    "no declared claim changed, but "
                    + " and ".join(closure["moved"])
                    + "; "
                    + "; ".join(closure["blocking"])
                    + " — so the change this diff names is not necessarily all that changed"
                )
                if closure["moved"]
                else (
                    "no differences found, but "
                    + "; ".join(closure["blocking"])
                    + ", so nothing this diff can see changed, which is not the same claim "
                    "as nothing changed"
                ),
            }
        )
        # A separate key, not more prose: the reason ends in a sentence §2
        # rule 3 fixes verbatim, and a consumer that acts on this needs the
        # step by itself rather than by parsing it back out of a paragraph.
        if closure["remedies"]:
            indeterminate[-1]["remedy"] = "; ".join(closure["remedies"])
        outcome = "indeterminate"
    else:
        outcome = "identical"

    environment: dict[str, Any] = {}
    for key, old_value, new_value in (
        ("tool_version", old.get("tool", {}).get("version"), new.get("tool", {}).get("version")),
        (
            "engine_version",
            old.get("engine", {}).get("version"),
            new.get("engine", {}).get("version"),
        ),
        (
            "render_backend",
            old.get("engine", {}).get("render_backend"),
            new.get("engine", {}).get("render_backend"),
        ),
    ):
        if old_value != new_value:
            environment[key] = {"old": old_value, "new": new_value}

    packages = _packages_delta(
        old.get("environment"),
        new.get("environment"),
        old_predates_widening=_predates_imports(old),
    )
    if packages is not None:
        environment["packages"] = packages

    return {
        "schema_version": DIFF_SCHEMA_VERSION,
        # Immediately after `schema_version`, the position the other five
        # artifacts put it in (#295). Additive, so `DIFF_SCHEMA_VERSION` does
        # NOT move — SPEC-report.md §7.1: adding a field is non-breaking and
        # MUST NOT bump the version. Until this landed, §7.1's rule that a
        # missing `payload` means "an older partspec wrote this" drew a false
        # conclusion about every `diff.json` this release had ever written,
        # and a consumer switching on the field had to special-case this one
        # artifact by `tool.name` (#345).
        "payload": "diff",
        "tool": {"name": "partspec-diff", "version": tool_version},
        "part": old_part.get("id"),
        "outcome": outcome,
        "indeterminate": indeterminate,
        "verdict": {"old": old.get("verdict"), "new": new.get("verdict")},
        "counts_total": {
            "old": old.get("counts", {}).get("total"),
            "new": new.get("counts", {}).get("total"),
        },
        "contract": {
            "digest_changed": old_part.get("contract_digest") != new_part.get("contract_digest"),
            # `target_changed`, `module_changed` and `target_incomparable`,
            # each present only when it fires (§4).
            **contract_target,
            "removed": removed,
            "added": added,
        },
        "source": {
            "digest_changed": old_part.get("source_digest") != new_part.get("source_digest"),
            "closure": closure["state"],
            # Separate from `closure`, because a bounded gap collapses that
            # field to `inconclusive` and would otherwise take the only
            # record of a moved closure digest with it. `null` where a side
            # carries no closure and the question cannot be asked.
            "closure_digest_changed": closure["digest_changed"],
            "imports": closure["imports"],
            "unseen": closure["unseen"],
            "covered": closure["covered"],
        },
        "checks": entries,
        "environment": environment,
    }


_SUMMARY_NAME_LIMIT = 2
"""How many distributions the summary's headline names per group.

`environment.packages` now records every distribution the run imported — 15 on
the fleet's cadquery venv, 84 installed — so two runs on different machines can
differ in dozens of entries. Spilling all of them onto the summary line would
bury the finding the line exists to state. The artifact on stdout carries the
complete lists; the line names a couple and counts the rest."""


def _bounded(entries: list[str]) -> str:
    """At most `_SUMMARY_NAME_LIMIT` names, then a count of the remainder."""
    shown = entries[:_SUMMARY_NAME_LIMIT]
    rest = len(entries) - len(shown)
    return ", ".join(shown) + (f", +{rest} more" if rest else "")


def _import_move_label(name: str, old: Any, new: Any) -> str:
    """How one moved distribution is named on the headline.

    A version arrow where there is one, because that is the fact a reader
    acts on. Where there is not — a `content` entry has no version, and a
    tier flip has two digests over different things — the label says which of
    the other two happened rather than leaving a bare name to be read as a
    version bump that did not happen.
    """
    if not isinstance(old, dict) or not isinstance(new, dict):
        return name
    old_version, new_version = old.get("version"), new.get("version")
    if old_version != new_version:
        return f"{name} {old_version or 'unversioned'} → {new_version or 'unversioned'}"
    if old.get("identity") != new.get("identity"):
        return f"{name} {old.get('identity')} → {new.get('identity')} install"
    return f"{name} {new_version} contents moved" if new_version else f"{name} contents moved"


def _import_label(name: str, entry: Any) -> str:
    version = entry.get("version") if isinstance(entry, dict) else None
    return f"{name} {version}" if version else name


def _imports_groups(doc: dict[str, Any]) -> dict[str, Any]:
    imports = doc.get("source", {}).get("imports") or {}
    return {} if "uncomparable" in imports else imports


def _imports_clause(doc: dict[str, Any]) -> str:
    """The summary's `inputs` fragment — the distributions the model loaded.

    This is #190's headline: "the library moved and no declared claim moved
    with it" is the statement the gate exists to make, and naming the moved
    distribution here is the whole of what makes exit 0 acceptable for it.

    It is not a duplicate of the packages clause even where both fire.
    `environment.packages` is what was *installed*; this is what was
    *loaded*, byte-identified — and the fleet's own configuration is the case
    where they disagree, a `sys.path` checkout moving under a version string
    that never changed.

    An entry either side could not attribute to its own target is named in a
    clause of its own and never as an appearance. Reported as one, it is a
    positive finding — *this build input arrived* — drawn from a fact about
    which targets shared an interpreter: measured, one build123d cube diffed
    against itself behind a CadQuery target said `inputs appeared: cadquery
    2.8.0, casadi 3.7.2, +4 more`, and nothing had appeared.

    The clause states the inability and stops. Asserting the cause — "the
    difference is its position in a batch" — is the same defect pointing the
    other way, and it was measured too: a follower whose model began importing
    a shared module, at batch position 2 of 2 in *both* runs, had a genuine
    new build input reported as a non-event. `preloaded` evidences that this
    comparison cannot attribute the entry; it evidences nothing about why the
    entry is on one side.

    Where the movement does not touch that set the wording is unchanged,
    because there the appearance is exactly what it says.
    """
    imports = _imports_groups(doc)
    clauses = []
    if changed := _attributed(imports, "changed"):
        moved = [_import_move_label(n, v["old"], v["new"]) for n, v in changed.items()]
        clauses.append(f"inputs moved: {_bounded(moved)}")
    for group, verb in (("added", "appeared"), ("removed", "disappeared")):
        if group_entries := _attributed(imports, group):
            named = [_import_label(n, e) for n, e in group_entries.items()]
            clauses.append(f"inputs {verb}: {_bounded(named)}")
    if carried := imports.get("unattributable"):
        # Both directions in one clause: naming which side an entry landed on
        # would suggest this comparison knows why it landed there, which is
        # the one thing it does not.
        entries = {**(imports.get("added") or {}), **(imports.get("removed") or {})}
        named = [_import_label(name, entries.get(name)) for name in carried]
        clauses.append(
            f"inputs not attributable: {_bounded(named)} — on one side only, and already "
            "loaded when that target began, so this comparison cannot tell an input that "
            "moved from one inherited from an earlier target"
        )
    return ("; " + "; ".join(clauses)) if clauses else ""


def _packages_clause(doc: dict[str, Any]) -> str:
    """The summary's `packages` fragment, or an empty string when nothing moved.

    A distribution whose version the imports clause already reported as moved
    is dropped from *this* clause's `moved` group, and nowhere else: every
    entry of `source_closure.imports` is also an installed distribution, so a
    library bump would otherwise be reported twice on one line in the exact
    case #190 exists for. Only `changed` against `changed` is a true
    duplicate. Suppressing across groups measured as data loss — an import
    that *appeared* while its installed version *moved* is two facts, and
    matching them by name alone dropped `packages moved: numpy 1.0.0 → 2.0.0`
    from the line entirely, which v0.7.4 printed. The artifact keeps both
    maps whole either way; this is the courtesy line, not the evidence.

    A name the pre-0.7.5 field could not have carried is reported as the
    record widening, with its remedy, and never as a package that appeared.
    Measured on the first diff an upgrading OpenSCAD-tier user runs:
    `identical: example-spacer — no semantic differences; packages appeared:
    PyJWT 2.13.0, PyYAML 6.0.3, +107 more` at exit 0 — 109 installations
    reported, none of which happened, while both `SPEC-diff.md` §3 and the
    #211 entry said "nothing was installed; re-record the baseline to clear
    it".
    """
    packages = doc.get("environment", {}).get("packages")
    if not packages:
        return ""
    if "uncomparable" in packages:
        return f"; packages not compared: {packages['uncomparable']}"
    already_moved = set(_imports_groups(doc).get("changed", {}))
    first_recorded = set(packages.get("first_recorded") or ())

    clauses = []
    if moved := [
        f"{n} {v['old']} → {v['new']}"
        for n, v in packages["changed"].items()
        if n not in already_moved
    ]:
        clauses.append(f"packages moved: {_bounded(moved)}")
    for group, verb in (("added", "appeared"), ("removed", "disappeared")):
        if listed := [f"{n} {v}" for n, v in packages[group].items() if n not in first_recorded]:
            clauses.append(f"packages {verb}: {_bounded(listed)}")
    if widened := [f"{n} {v}" for n, v in packages["added"].items() if n in first_recorded]:
        clauses.append(
            f"{len(widened)} packages recorded for the first time: {_bounded(widened)} — the "
            "baseline predates 0.7.5, when this field held five engine names; nothing was "
            "installed, and re-recording the baseline clears it"
        )
    return ("; " + "; ".join(clauses)) if clauses else ""


def _contract_clause(doc: dict[str, Any]) -> str:
    """The summary's fragments for the contract module: what moved under an
    unchanged part, and what this comparison declined to compare.

    §1's rule — a build input that moved is named on every outcome — reached
    the closure and stopped, and the contract file is the one input the closure
    deliberately EXCLUDES (`SPEC-report.md` §8.3: `contract_digest` already
    covers it). So an edited `.scad` printed `covered: source closure (1 file),
    changed` while an edited contract printed nothing at all: measured, two
    reports of one part whose module differed by one comment gave `identical:
    widget — no semantic differences` with `contract.digest_changed: true` in
    the artifact and no word of it on the line.

    Each fragment stays a fact rather than a finding, and says which. The
    digest is module-scoped, so an edit to a sibling factory that cannot reach
    this part moves it; a moved module path is a rename (§3, "recorded but
    never outcome-bearing").

    **The declined comparison is named too, and that is not optional.** §2's
    opening makes "no differences found" a positive claim requiring comparable
    inputs rather than a fallthrough. Where one side names no factory the
    comparison cannot say which target ran, and reporting `identical` with
    nothing on the line would be the same silence this function was added to
    end, one guard away (PR #353 review, F3).
    """
    contract = doc.get("contract", {})
    clauses = []
    if contract.get("digest_changed"):
        clauses.append(
            "contract module edited: the digest moved — module-scoped, so it over-fires "
            "and is never by itself a difference"
        )
    # Suppressed where the headline already prints both full spellings, which
    # is the one suppression §1 allows: the same fact twice on one line, not
    # two facts one of which is dropped.
    if (moved := contract.get("module_changed")) and not contract.get("target_changed"):
        clauses.append(
            f"contract module path moved: {moved['old']} → {moved['new']} — the recorded "
            "path, not its contents, and never by itself a difference"
        )
    if declined := contract.get("target_incomparable"):
        clauses.append(
            f"which target ran was not compared: {declined['old']} vs {declined['new']} — "
            "one side names no factory, so a single-factory module spelled two ways cannot "
            "be told from a target that changed"
        )
    return ("; " + "; ".join(clauses)) if clauses else ""


def _claims_across_the_change(new_report: dict[str, Any]) -> str:
    """What `identical` plus a moved closure actually licenses saying.

    The sentence used to ignore the claims entirely: a 0.7.5-shaped pair that
    came out `identical` with attributed closure movement got "every declared
    claim held across the change", whatever the claims had done. Two reports
    whose SAME check fails identically on both sides were therefore told the
    claim held (#220). It did not — it failed, twice.

    Unconditional ON THE VERDICT, to be exact: the gate below always had two
    further conditions, a 0.7.5-shaped closure and attributed movement.

    **Two questions, and they take different check sets.** `Report.verdict` is
    the model: `builds` is excluded from the EMPTINESS test, because partspec
    adds it and a contract asserting nothing would otherwise look asserted —
    and then the status collapse runs over EVERY check, `builds` included,
    because a build that failed is a claim that failed. Applying the exclusion
    to both questions is how the second version of this function reported
    `every declared claim held` for a model that does not compile, on two
    reports `partspec check` wrote unmodified (round-2 review of #239). That is
    #220 reproduced by its own fix.

    **Read off the checks, not off `verdict`, and the difference is not
    fastidiousness.** The comparison only ever compares `verdict` against its
    counterpart — `verdict_changed` feeds `different`, and `verdict == "error"`
    feeds `indeterminate` — so it is never read as a FACT about one report, and
    a lie repeated identically on both sides costs the comparison nothing.
    Keying a claim about what the checks did on it made that lie load-bearing
    for the first time, and a forged `pass` reprinted #220's sentence over a
    failing check. `status` is different in kind: it is what `_check_entry`
    already joins, the evidence every `regressed` and `fixed` rests on. (An
    earlier version of this paragraph said `verdict` was "read by nothing else
    in the comparison", which is false twice over — round-3 review of #239.)
    A pair that lies identically about `status`
    has defeated the whole comparator, not this sentence, and no cross-check
    inside one report recovers from that — `counts` can be forged with it.

    So no `counts` guard here. It would stop a careless forger and imply a
    completeness it cannot have. `counts.total` is guarded because a report
    contradicting its own arithmetic is unusable input; `status` is not
    redundant with anything — it IS the input. (`Report.counts()`'s other half,
    the per-status tally, is redundant and unguarded, which is a real gap and a
    different issue from this sentence.)
    """
    checks = new_report.get("checks") or []
    # No `isinstance` filter: `diff_reports` refuses a report whose `checks`
    # holds a non-object before this can be reached, so one here is dead code
    # that reads as a live guard (round-2 review of #239).
    declared = [c for c in checks if c.get("kind") not in IMPLICIT_CHECK_KINDS]
    if not declared:
        return "neither side declared a claim, so none held across the change"
    statuses = {c.get("status") for c in checks}
    if statuses == {"pass"}:
        return "every declared claim held across the change"
    state = "fail" if "fail" in statuses else "incomplete"
    return f"no declared claim changed status across the change — both sides {state}"


def _coverage_lines(doc: dict[str, Any], new_report: dict[str, Any]) -> list[str]:
    """What was covered, and what was not — on every outcome, permanently.

    The irreducible line is the entire mitigation for `_IRREDUCIBLE_GAPS` not
    reaching a verdict: the caveat that used to be an exit code is now a
    sentence, and a sentence that is sometimes printed would be worth less
    than the verdict it replaced.

    Bounded gaps print here too, on the outcomes that do not already state
    them in the headline — which means `different`, where they were silent.
    "This diff is older than the report it read" is a fact about the tool and
    does not stop mattering because a check regressed; and a `different` line
    reading "1 regressed" with no note that the input inventory could not be
    compared invites exactly the reading that the named regression is the
    whole story.
    """
    source = doc.get("source", {})
    unseen = source.get("unseen", {})
    lines = []
    if covered := source.get("covered"):
        lines.append(f"  covered: {covered}")
        # Only under a `covered:` line, which is its antecedent. Two pre-0.7.5
        # reports get no coverage block, and this sentence alone under their
        # headline referred to a change nothing on the screen had named.
        #
        # And only where a change was attributed. `closure: "changed"` is a
        # statement about the recorded maps, which is the right thing for the
        # artifact to say; this sentence names "the change" as the part's, so
        # it needs movement the comparison could attribute — a moved closure
        # digest, or an import move outside `unattributable`. Where the only
        # recorded difference is unattributable, the headline states the
        # inability and there is no change here to hold a claim across.
        imports = _imports_groups(doc)
        attributed = source.get("closure_digest_changed") or any(
            _attributed(imports, group) for group in ("changed", "added", "removed")
        )
        if doc["outcome"] == "identical" and source.get("closure") == "changed" and attributed:
            lines.append("  " + _claims_across_the_change(new_report))
    stated = {entry["reason"] for entry in doc.get("indeterminate", [])}
    lines.extend(
        f"  not covered: {phrase}"
        for phrase in [*unseen.get("irreducible", {}).values(), *unseen.get("bounded", {}).values()]
        if not any(phrase in reason for reason in stated)
    )
    return lines


def summary_of(doc: dict[str, Any], new_report: dict[str, Any]) -> str:
    """The stderr courtesy summary: one headline, then the coverage it rests on.

    `new_report` is the later of the two reports compared, and only the claims
    line uses it — to read what the checks actually did rather than trust the
    `verdict` string copied into the artifact (#220, and #239's reviews of the
    first two fixes).

    Required, not optional. It was optional so that one-argument calls kept
    working, and three of them were assertions that the claims line is ABSENT —
    which the None branch made unconditionally true, silently un-pinning the
    condition this function's own docstring cites as its rebuttal. A default
    that weakens the output is a default that hides a regression.
    """
    # Both clauses ride every outcome, `identical` included. A build input
    # that moved under an unchanged part is precisely the case `identical: no
    # semantic differences` would otherwise report as an unqualified
    # nothing-happened.
    moved = _imports_clause(doc) + _packages_clause(doc) + _contract_clause(doc)
    if doc["outcome"] == "identical":
        headline = f"identical: {doc['part']} — no semantic differences{moved}"
    elif doc["outcome"] == "indeterminate":
        reasons = "; ".join(entry["reason"] for entry in doc["indeterminate"])
        headline = f"indeterminate: {doc['part']} — {reasons}{moved}"
    else:
        contract = doc["contract"]
        parts = []
        # First, because it is the one finding that says the two reports are
        # not two runs of the same question. A check count under it describes
        # a comparison between two different targets, and a reader who does
        # not know that reads every other number wrongly (#343).
        if target := contract.get("target_changed"):
            parts.append(f"the invoked target changed: {target['old']} → {target['new']}")
        if contract["removed"]:
            parts.append(
                f"{len(contract['removed'])} check(s) removed: {', '.join(contract['removed'])}"
            )
        if contract["added"]:
            parts.append(f"{len(contract['added'])} added")
        for change in ("regressed", "fixed", "drifted", "limit_changed"):
            entries = [c for c in doc["checks"] if c["change"] == change]
            if not entries:
                continue
            # §3's reason for making the claim delta ride a status-change entry
            # applies to this line too, and did not reach it: loosen a limit
            # until a failing check passes and the headline said `1 fixed`,
            # reporting the flagship weakening move as an improvement. The
            # artifact carried the delta the whole time; the surface a human
            # reads in a terminal or a PR check did not (#293).
            #
            # Only the status-change buckets take it. `limit_changed` IS the
            # claim moving, so the note restates the bucket's own name; a
            # `drifted` entry cannot carry a claim at all, `_check_entry`
            # returning `limit_changed` before it reaches that branch.
            #
            # `answered` is the second qualifier and not a widening of the
            # first: such an entry carries no `claim` for the first to fire on,
            # and the two answer different questions — whether the author moved
            # the goalposts, and whether anyone was still keeping score (#325).
            notes = []
            if change in ("regressed", "fixed"):
                if with_claim := sum(1 for c in entries if "claim" in c):
                    notes.append(f"{with_claim} with the claim changed")
                if unanswered := sum(1 for c in entries if "answered" in c):
                    notes.append(f"{unanswered} not answered")
            # The bucket keeps its true total and each qualifier is an
            # independent tally over it, not a partition of it: the two count
            # overlapping sets and may sum past the bucket. That is deliberate
            # — `N fixed` is what the spec names and what a reader greps, and a
            # split total would answer "how many were fixed?" with a number
            # that is not the answer.
            note = f" ({', '.join(notes)})" if notes else ""
            parts.append(f"{len(entries)} {change}{note}")
        headline = f"different: {doc['part']} — {'; '.join(parts) or 'verdict changed'}{moved}"
    # Above the coverage block, because it is the one line the reader can act
    # on: `check`'s own diagnostics put `hint:` directly under the fault for
    # the same reason (v0.7.3), and this verb was still stating a cause and
    # stopping.
    remedies = [f"  remedy: {e['remedy']}" for e in doc["indeterminate"] if e.get("remedy")]
    return "\n".join([headline, *remedies, *_coverage_lines(doc, new_report)])
