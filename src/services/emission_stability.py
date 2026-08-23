"""SPEC-INFRA-003 REQ-006: measure whether agent1's emitted criterion count is stable.

Agent1's decomposition is not deterministic. An earlier regeneration of one trial from
identical protocol text produced 2 top-level criteria for a sentence where the current
reference store holds 3 (`spec.md` §2.4). That was recorded as an observed property and
never re-measured, which leaves "the prompt fix converged" with no instrument that could
say otherwise -- a single post-fix run reporting 1 is indistinguishable from a lucky
draw.

This module is that instrument. It supplies the measurement, not the fix.

**What is measured.** Per run, per watched protocol sentence: how many top-level criteria
that sentence emitted. Across N >= 5 runs on identical input: the distribution of those
counts (AC-008).

**How a sentence is identified across runs.** Criterion ids are not stable -- a run
emitting 2 where another emits 3 renumbers everything after it, so an id-keyed instrument
would measure the renumbering. The key is instead `spec.md` §2.5's `(domain, stem)` pair
gated on `valueConstraint: null`, which is derived mechanically from the criterion and
carries no run-specific information. `restated_clusters.cluster_key` is that key,
shared rather than reimplemented.

**Why the M2 detector is not the instrument.** `detect_restated_clusters` reports sets of
two or more, which is right for detecting duplication and wrong for measuring
convergence: a sentence that has converged emits one criterion and a sentence that has
vanished emits none, and a thresholded detector reports both as the same nothing. Hence
the shared key without the threshold, and hence `VANISHED` being a verdict of its own
rather than a flavour of stable.

**Enumerated watches.** One shape has no stem to key on -- a heading emitted as a
criterion alongside a merged-content criterion (`spec.md` §2.5.2), whose two descriptions
share no stem, which is why the §2.5 signal does not flag it either. `spec.md` §2.5.2
resolves this by enumeration rather than by loosening the signal, and `description_watch`
is that escape hatch. Note the asymmetry with the detector: AC-013 forbids the *detector*
from keying on trial identity, because a lookup table there would pass every output
assertion and still be the wrong mechanism. A watch list is the opposite -- naming the
sentences under measurement is its entire job, and AC-008 names them for it.

The pipeline invocation is injected, so this module holds no I/O and no service imports.
`scripts/measure_emission_stability.py` supplies the live `run_once`.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from src.services.restated_clusters import cluster_key

# One run's output: study id -> role -> that role's top-level criteria.
RunCriteria = Mapping[int, Mapping[str, Sequence[dict[str, Any]]]]

# AC-008: "N >= 5 repeated agent1 runs". Fewer cannot distinguish a stable emitter from
# a lucky draw, and the historical evidence is a single 2-vs-3 disagreement, so the
# floor is a hard refusal rather than a warning.
MINIMUM_RUNS = 5


@dataclass(frozen=True)
class SentenceWatch:
    """One protocol sentence to count across runs.

    Attributes:
        label: Human-readable name of the sentence, e.g. "<trial> exclusion #10".
            Carried into the report; never used to match anything.
        study_id: The study whose criteria are searched.
        role: "inclusion" or "exclusion". A sentence never spans roles.
        matches: Predicate deciding whether one criterion came from this sentence.
    """

    label: str
    study_id: int
    role: str
    matches: Callable[[dict[str, Any]], bool]


def stem_watch(
    *,
    label: str,
    study_id: int,
    role: str,
    domain: str,
    stem: str,
) -> SentenceWatch:
    """Build a watch keyed on the `spec.md` §2.5 `(domain, stem)` pair.

    This is the general case, and the one that composes with M2: any cluster the
    detector reports can be turned into a watch by `watches_from_clusters`.

    Args:
        label: Human-readable name of the sentence, carried into the report.
        study_id: The study whose criteria are searched.
        role: "inclusion" or "exclusion".
        domain: The cluster's domain, condition 1 of the signal.
        stem: The description stem, condition 3 of the signal. Members differing only
            by a trailing parenthetical suffix share it.

    Returns:
        A watch counting every criterion whose `cluster_key` equals `(domain, stem)`.
        Criteria carrying a `valueConstraint` have no key and are never counted, which
        is condition 2.
    """
    key = (domain, stem)

    def matches(criterion: dict[str, Any]) -> bool:
        return cluster_key(criterion) == key

    return SentenceWatch(label=label, study_id=study_id, role=role, matches=matches)


def description_watch(
    *,
    label: str,
    study_id: int,
    role: str,
    domain: str,
    pattern: str,
) -> SentenceWatch:
    """Build a watch keyed on a description pattern, for sentences with no shared stem.

    The escape hatch for `spec.md` §2.5.2's known false negative: a heading emitted as a
    criterion and a merged-content criterion describe the same protocol sentence but
    share no stem, so no stem watch can see them as one sentence. `spec.md` §2.5.2 covers
    that shape by enumeration rather than by loosening the signal, and this is the
    enumeration.

    Deliberately *not* gated on `valueConstraint`, unlike `stem_watch`. The gate belongs
    to the §2.5 signal, and this watch is explicitly outside it; adding the gate here
    would silently stop counting a criterion that gained a constraint, which is a change
    worth seeing rather than hiding.

    Args:
        label: Human-readable name of the sentence, carried into the report.
        study_id: The study whose criteria are searched.
        role: "inclusion" or "exclusion".
        domain: Required exact-match domain, so the pattern cannot reach across domains.
        pattern: Regular expression searched against the criterion `description`.

    Returns:
        A watch counting every criterion in the domain whose description matches.
    """
    regex = re.compile(pattern)

    def matches(criterion: dict[str, Any]) -> bool:
        if (criterion.get("domain") or "") != domain:
            return False
        return regex.search(criterion.get("description") or "") is not None

    return SentenceWatch(label=label, study_id=study_id, role=role, matches=matches)


def count_watched(watch: SentenceWatch, run: RunCriteria) -> int:
    """Count the top-level criteria one run emitted for one watched sentence.

    Args:
        watch: The sentence being counted.
        run: One run's output, study id -> role -> criteria.

    Returns:
        The number of matching criteria, which may be 1 (converged) or 0 (the sentence
        stopped being emitted). Both are meaningful and distinct.

    Raises:
        LookupError: When the run carries no record for the watched study. Returning 0
            there would read as "the sentence emitted nothing" -- a converged-looking,
            fully green result for a study that was never run.
    """
    if watch.study_id not in run:
        raise LookupError(
            f"run carries no record for study {watch.study_id} "
            f"(watch {watch.label!r}); refusing to report an unmeasured sentence as zero"
        )
    criteria = (run[watch.study_id] or {}).get(watch.role) or []
    return sum(1 for criterion in criteria if watch.matches(criterion))


@dataclass(frozen=True)
class WatchDistribution:
    """What one watched sentence emitted across every run of one measurement.

    Attributes:
        label: The watched sentence's name.
        counts: One emitted-criterion count per run, in run order. Run order is kept
            rather than summarized away, because a sentence that drifts partway
            through a sequence reads differently from one that alternates.
    """

    label: str
    counts: tuple[int, ...]

    @property
    def distribution(self) -> dict[int, int]:
        """Return how many runs produced each count.

        This is REQ-006's question stated literally -- "how many times did this
        sentence produce N criteria". No single mode is derived from it: the historical
        evidence is one 2 and one 3, and naming either "the" count would invent a
        majority two observations do not support.

        Returns:
            Emitted-criterion count -> number of runs producing it, most frequent first.
        """
        return dict(Counter(self.counts).most_common())

    @property
    def minimum(self) -> int:
        """Return the lowest count any run produced."""
        return min(self.counts)

    @property
    def maximum(self) -> int:
        """Return the highest count any run produced."""
        return max(self.counts)

    @property
    def stable(self) -> bool:
        """Return whether every run agreed, which is REQ-006's actual claim."""
        return len(set(self.counts)) == 1

    @property
    def converged(self) -> bool:
        """Return whether every run emitted exactly one criterion (the AC-008 target)."""
        return set(self.counts) == {1}

    @property
    def verdict(self) -> str:
        """Return the outcome as one of four names.

        The two collapsed cases are the reason this is measured at all. VANISHED is not
        a flavour of STABLE: a sentence that stopped being emitted is perfectly
        deterministic and is a lost exclusion. And STABLE is not CONVERGED: a sentence
        reliably emitting 3 satisfies REQ-006 while still being the defect REQ-001
        exists to fix, so the report has to be able to say both at once.

        Returns:
            "UNSTABLE" when runs disagree, else "VANISHED" (all zero), "CONVERGED"
            (all one), or "STABLE" (all equal, two or more).
        """
        if not self.stable:
            return "UNSTABLE"
        if self.maximum == 0:
            return "VANISHED"
        if self.converged:
            return "CONVERGED"
        return "STABLE"


@dataclass(frozen=True)
class StabilityReport:
    """One measurement: N runs, every watched sentence counted in each.

    Attributes:
        runs: How many runs were executed.
        distributions: One per watch, in the order the watches were given.
    """

    runs: int
    distributions: tuple[WatchDistribution, ...]

    def for_label(self, label: str) -> WatchDistribution:
        """Return the distribution recorded for one watched sentence.

        Args:
            label: The watch label to look up.

        Returns:
            That sentence's distribution.

        Raises:
            LookupError: When no watch by that label was measured.
        """
        for distribution in self.distributions:
            if distribution.label == label:
                return distribution
        raise LookupError(f"no watch labelled {label!r} in this measurement")

    @property
    def converged(self) -> bool:
        """Return whether every watched sentence emitted exactly one in every run."""
        return all(d.converged for d in self.distributions)

    @property
    def stable(self) -> bool:
        """Return whether every watched sentence agreed with itself across runs."""
        return all(d.stable for d in self.distributions)


def measure_emission_stability(
    *,
    watches: Sequence[SentenceWatch],
    run_once: Callable[[int], RunCriteria],
    runs: int = MINIMUM_RUNS,
) -> StabilityReport:
    """Run the pipeline N times over identical input and record what each run emitted.

    A run that raises is not caught. A partial measurement reporting the runs that
    happened to succeed would claim stability from a sample chosen by which runs failed,
    which is the failure mode this instrument exists to rule out.

    Args:
        watches: The protocol sentences to count. Must be non-empty.
        run_once: Invoked with the zero-based run index; returns that run's criteria as
            study id -> role -> criteria. Every invocation must use identical input --
            that is the premise of the measurement, and it is the caller's to keep.
        runs: How many times to run. Must be at least `MINIMUM_RUNS`.

    Returns:
        The distribution of emitted counts per watched sentence.

    Raises:
        ValueError: When `runs` is below the AC-008 floor, or `watches` is empty.
    """
    if runs < MINIMUM_RUNS:
        raise ValueError(
            f"AC-008 requires at least {MINIMUM_RUNS} runs to distinguish a stable "
            f"emitter from a lucky draw; got {runs}"
        )
    if not watches:
        # An empty watch list measures nothing and reports `converged` vacuously true --
        # a fully green result asserting the absence of any assertion.
        raise ValueError("measurement needs at least one watch; got none")

    per_watch: dict[str, list[int]] = {watch.label: [] for watch in watches}
    for index in range(runs):
        run = run_once(index)
        for watch in watches:
            per_watch[watch.label].append(count_watched(watch, run))

    return StabilityReport(
        runs=runs,
        distributions=tuple(
            WatchDistribution(label=watch.label, counts=tuple(per_watch[watch.label]))
            for watch in watches
        ),
    )


def watches_from_clusters(
    clusters: Sequence[Mapping[str, Any]],
    *,
    study_id: int,
    study_label: str,
) -> list[SentenceWatch]:
    """Turn every cluster a detection run reported into a watch for one study.

    This is what makes the instrument general: the M2 detector finds the sentences that
    are duplicating, and each becomes something to measure across runs. The key it
    reports -- `(domain, stem)` -- is exactly what a stem watch needs, so nothing is
    re-derived.

    The threshold is dropped in the process, and that is the point. The detector reports
    sets of two or more, so once a sentence converges it reports nothing for it, which is
    the same nothing it reports for a sentence that stopped being emitted. The watch
    keeps counting and separates 1 from 0.

    Args:
        clusters: `detect_all_restated_clusters` output -- dicts carrying `role`,
            `domain`, and `stem`.
        study_id: The study those clusters were detected in.
        study_label: Short study name used to build readable watch labels.

    Returns:
        One watch per cluster, in the order given.
    """
    return [
        stem_watch(
            label=f"{study_label} {cluster['role']}: {cluster['stem']}",
            study_id=study_id,
            role=str(cluster["role"]),
            domain=str(cluster["domain"]),
            stem=str(cluster["stem"]),
        )
        for cluster in clusters
    ]


# The three sentences AC-008 names, from `spec.md` §2.1. Study ids match the reingest
# entry point's target table. Two are keyed on the §2.5 stem; the third has no stem to
# key on (§2.5.2) and is enumerated instead, which is the disposition §2.5.2 already
# chose for it.
SPEC_2_1_WATCHES: tuple[SentenceWatch, ...] = (
    stem_watch(
        label="CARMELINA exclusion #10",
        study_id=9,
        role="exclusion",
        domain="Demographics",
        stem="Pregnancy/Nursing/Uncontrolled Contraception",
    ),
    stem_watch(
        label="CAROLINA exclusion #17",
        study_id=10,
        role="exclusion",
        domain="Demographics",
        stem="Pre-menopausal women/Nursing/Pregnant/Not using contraception",
    ),
    description_watch(
        label="EMPA-REG exclusion #11",
        study_id=8,
        role="exclusion",
        domain="Demographics",
        pattern=r"^Pre-menopausal women\b",
    ),
)


def criteria_from_study_record(study: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Extract one study's top-level criteria from its stored record.

    Args:
        study: A study record as the store holds it.

    Returns:
        `{"inclusion": [...], "exclusion": [...]}`.

    Raises:
        ValueError: When the record carries no criteria in either role. An unprocessed
            study is not a study that emitted nothing: every watch would count 0, every
            run would agree, and the report would read VANISHED across the board -- a
            deterministic-looking regression produced by a pipeline that silently did
            not run.
    """
    eligibility = study.get("eligibility") or {}
    criteria = {
        "inclusion": list(eligibility.get("inclusionCriteria") or []),
        "exclusion": list(eligibility.get("exclusionCriteria") or []),
    }
    if not criteria["inclusion"] and not criteria["exclusion"]:
        raise ValueError(
            f"study {study.get('id')!r} record carries no criteria in either role; "
            f"refusing to measure an unprocessed study as a study that emitted nothing"
        )
    return criteria


def report_to_dict(report: StabilityReport) -> dict[str, Any]:
    """Serialize a measurement to plain JSON-compatible data.

    The pre-fix baseline is measured before the prompt change and the post-fix
    measurement after it, so AC-008's "side by side" requires the first to survive the
    gap. Re-deriving the pre-fix numbers later against a fixed pipeline would not be the
    pre-fix measurement.

    Args:
        report: The measurement to serialize.

    Returns:
        `{"runs": N, "distributions": [{"label": ..., "counts": [...]}, ...]}`.
    """
    return {
        "runs": report.runs,
        "distributions": [
            {"label": d.label, "counts": list(d.counts)} for d in report.distributions
        ],
    }


def report_from_dict(payload: Mapping[str, Any]) -> StabilityReport:
    """Rebuild a measurement from `report_to_dict` output.

    Args:
        payload: Previously serialized measurement data.

    Returns:
        The measurement it describes.
    """
    return StabilityReport(
        runs=int(payload["runs"]),
        distributions=tuple(
            WatchDistribution(label=str(d["label"]), counts=tuple(int(c) for c in d["counts"]))
            for d in payload.get("distributions") or ()
        ),
    )


def _render_cell(report: StabilityReport | None, label: str) -> tuple[str, str]:
    """Render one report's distribution and verdict for one sentence.

    Args:
        report: The measurement, or None when that side was not measured.
        label: The watched sentence.

    Returns:
        `(distribution text, verdict text)`.
    """
    if report is None:
        return ("not measured", "-")
    try:
        distribution = report.for_label(label)
    except LookupError:
        return ("not measured", "-")
    cells = "; ".join(f"{count}x{runs}" for count, runs in distribution.distribution.items())
    return (cells, distribution.verdict)


def render_comparison(
    *,
    pre: StabilityReport | None,
    post: StabilityReport | None,
) -> str:
    """Render the pre-fix and post-fix distributions side by side (AC-008).

    A side that was not measured says so. M3 produces the pre-fix baseline with no
    post-fix column yet, and a blank cell there would be indistinguishable from a
    measurement that found nothing.

    Args:
        pre: The pre-fix measurement, or None.
        post: The post-fix measurement, or None.

    Returns:
        A markdown table, one row per watched sentence, with a legend for the cell
        format.

    Raises:
        ValueError: When neither side was measured.
    """
    if pre is None and post is None:
        raise ValueError("a comparison needs at least one measured side; got neither")

    labels: list[str] = []
    for report in (pre, post):
        for distribution in (report.distributions if report else ()):
            if distribution.label not in labels:
                labels.append(distribution.label)

    lines = [
        "| Sentence | Pre-fix | Pre-fix verdict | Post-fix | Post-fix verdict |",
        "|---|---|---|---|---|",
    ]
    for label in labels:
        pre_cells, pre_verdict = _render_cell(pre, label)
        post_cells, post_verdict = _render_cell(post, label)
        lines.append(
            f"| {label} | {pre_cells} | {pre_verdict} | {post_cells} | {post_verdict} |"
        )

    lines.append("")
    lines.append(
        "A cell reads `<criteria emitted>x<runs producing that count>`, so `3x3; 2x2` "
        "is five runs, three of which emitted 3 criteria and two of which emitted 2."
    )
    lines.append(
        "CONVERGED = every run emitted 1. STABLE = every run agreed on some other "
        "count. VANISHED = every run emitted none. UNSTABLE = the runs disagreed."
    )
    return "\n".join(lines)
