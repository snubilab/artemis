"""SPEC-INFRA-003 REQ-006: the emitted criterion count for one sentence is stable.

Agent1's decomposition is not deterministic. An earlier regeneration of CARMELINA from
the same protocol text produced 2 criteria where the current reference store holds 3
(`spec.md` §2.4). That was recorded as an observed property and never re-measured, so
"the prompt fix converged" currently has no instrument that could say otherwise -- and a
single post-fix run showing 1 is indistinguishable from a lucky draw.

REQ-006 asks for the instrument. AC-008: N >= 5 repeated agent1 runs on identical input,
the emitted top-level criterion count recorded per run for each `spec.md` §2.1 cluster,
pre-fix and post-fix distributions reported side by side.

**The identity problem.** Criterion ids are not stable across runs -- a run emitting 2
where another emits 3 renumbers everything after it -- so the count cannot be keyed on
ids. It is keyed instead on what `spec.md` §2.5 already established as run-independent:
the `(domain, stem)` pair, gated on `valueConstraint: null`.

**Why the M2 detector cannot be the instrument on its own.** `detect_restated_clusters`
reports sets of *two or more*. Post-fix a converged sentence emits one criterion and the
detector correctly reports nothing -- which is byte-identical to what it reports for a
sentence that vanished entirely. Stability measurement needs the count including 1 and 0,
so it shares the §2.5 key function and drops the >= 2 threshold.

The pipeline invocation is injected (`run_once`), so everything here runs against
constructed run outputs. The live N-run execution needs the container and the vLLM
backend and is driven by `scripts/measure_emission_stability.py`.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from src.services.emission_stability import (
    MINIMUM_RUNS,
    SPEC_2_1_WATCHES,
    SentenceWatch,
    WatchDistribution,
    count_watched,
    criteria_from_study_record,
    description_watch,
    measure_emission_stability,
    render_comparison,
    report_from_dict,
    report_to_dict,
    stem_watch,
    watches_from_clusters,
)
from src.services.restated_clusters import detect_all_restated_clusters

# ---------------------------------------------------------------------------
# Fixture helpers -- field shape per spec.md §2.1
# ---------------------------------------------------------------------------

CARMELINA = 9
EMPA_REG = 8


def _criterion(
    *,
    id: int,
    description: str,
    domain: str = "Demographics",
    value_constraint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a top-level IR criterion in the shape `spec.md` §2.1 documents.

    Args:
        id: Criterion id, unique within a (study, role) scope. Deliberately varied
            across the fixtures below, because nothing here may key on it.
        description: The paraphrased description; `sourceText` is empty on every
            affected criterion, so this is what the mapper and the stem both see.
        domain: OMOP-ish domain label.
        value_constraint: `{op, value, unitText}` when the criterion carries one.

    Returns:
        A criterion dict.
    """
    return {
        "id": id,
        "description": description,
        "domain": domain,
        "groupId": None,
        "valueConstraint": value_constraint,
        "logicType": "ABSENCE",
        "isGroupLabel": False,
        "sourceText": "",
    }


def _run(*, study_id: int, inclusion: list | None = None, exclusion: list | None = None):
    """Build one run's output for a single study.

    Args:
        study_id: The study the criteria belong to.
        inclusion: Top-level inclusion criteria, defaulting to none.
        exclusion: Top-level exclusion criteria, defaulting to none.

    Returns:
        A run mapping in the shape `run_once` is contracted to return.
    """
    return {study_id: {"inclusion": inclusion or [], "exclusion": exclusion or []}}


# The CARMELINA exclusion #10 cluster, `spec.md` §2.5.1: domain Demographics, stem
# "Pregnancy/Nursing/Uncontrolled Contraception", suffixes "(<= 1 year)" / "(General)".
_CARMELINA_STEM = "Pregnancy/Nursing/Uncontrolled Contraception"
_CARMELINA_WATCH = stem_watch(
    label="CARMELINA exclusion #10",
    study_id=CARMELINA,
    role="exclusion",
    domain="Demographics",
    stem=_CARMELINA_STEM,
)


class TestCountingOneSentence:
    """The count is per watched sentence, per run, and keyed on nothing run-specific."""

    def test_should_count_three_when_the_sentence_emits_three_restatements(self):
        # The pre-fix reference store: `spec.md` §2.1 CARMELINA {11, 12, 18}.
        run = _run(
            study_id=CARMELINA,
            exclusion=[
                _criterion(id=11, description=f"{_CARMELINA_STEM} (<= 1 year)"),
                _criterion(id=12, description=f"{_CARMELINA_STEM} (General)"),
                _criterion(id=18, description=_CARMELINA_STEM),
            ],
        )

        assert count_watched(_CARMELINA_WATCH, run) == 3

    def test_should_count_one_when_the_sentence_has_converged(self):
        # This is the case the M2 detector cannot report: one member is not a cluster,
        # so `detect_restated_clusters` returns nothing for it. The target state has to
        # be observable as the number 1, not as an absence.
        run = _run(
            study_id=CARMELINA,
            exclusion=[_criterion(id=11, description=_CARMELINA_STEM)],
        )

        assert count_watched(_CARMELINA_WATCH, run) == 1

    def test_should_count_zero_when_the_sentence_vanished(self):
        # Also indistinguishable from convergence through the detector, and a regression
        # rather than a success: the exclusion stopped being emitted at all.
        run = _run(study_id=CARMELINA, exclusion=[
            _criterion(id=11, description="Type 1 diabetes mellitus", domain="Condition"),
        ])

        assert count_watched(_CARMELINA_WATCH, run) == 0

    def test_should_count_a_restatement_whose_id_is_unlike_any_id_in_the_spec(self):
        # Ids renumber between runs. A run emitting 2 where another emits 3 shifts every
        # id after it, so an id-keyed instrument would measure the renumbering.
        run = _run(
            study_id=CARMELINA,
            exclusion=[
                _criterion(id=904, description=f"{_CARMELINA_STEM} (General)"),
                _criterion(id=905, description=_CARMELINA_STEM),
            ],
        )

        assert count_watched(_CARMELINA_WATCH, run) == 2


class TestCountingRespectsTheSignalConditions:
    """The stem watch is the §2.5 key, so its three conditions all still gate."""

    def test_should_not_count_a_criterion_carrying_a_value_constraint(self):
        # Condition 2, `spec.md` §2.3.3. The analyte triple differs from a restatement
        # only here: same domain, same surface suffix shape, but a bound constraint.
        run = _run(
            study_id=CARMELINA,
            exclusion=[
                _criterion(id=11, description=_CARMELINA_STEM),
                _criterion(
                    id=12,
                    description=f"{_CARMELINA_STEM} (General)",
                    value_constraint={"op": "gte", "value": 3.0, "unitText": "x ULN"},
                ),
            ],
        )

        assert count_watched(_CARMELINA_WATCH, run) == 1

    def test_should_not_count_a_criterion_from_another_domain(self):
        # Condition 1. Same stem, different domain, is not the same sentence.
        run = _run(
            study_id=CARMELINA,
            exclusion=[
                _criterion(id=11, description=_CARMELINA_STEM),
                _criterion(id=12, description=_CARMELINA_STEM, domain="Condition"),
            ],
        )

        assert count_watched(_CARMELINA_WATCH, run) == 1

    def test_should_not_count_a_criterion_in_the_other_role(self):
        # Clusters never span roles (`spec.md` §2.5), and neither does a watch.
        run = _run(
            study_id=CARMELINA,
            inclusion=[_criterion(id=3, description=_CARMELINA_STEM)],
            exclusion=[_criterion(id=11, description=_CARMELINA_STEM)],
        )

        assert count_watched(_CARMELINA_WATCH, run) == 1

    def test_should_not_count_a_criterion_from_another_study(self):
        run = {
            CARMELINA: {"inclusion": [], "exclusion": [
                _criterion(id=11, description=_CARMELINA_STEM),
            ]},
            EMPA_REG: {"inclusion": [], "exclusion": [
                _criterion(id=27, description=_CARMELINA_STEM),
            ]},
        }

        assert count_watched(_CARMELINA_WATCH, run) == 1


class TestUnmeasuredIsNotZero:
    """A study the run never produced is a missing measurement, not a count of zero."""

    def test_should_raise_when_the_run_carries_no_record_for_the_watched_study(self):
        # Recording 0 here would read as "the sentence emitted nothing" -- a
        # converged-looking, fully green result for a study that was never run. The
        # reingest entry point already refuses this shape for the same reason: a study
        # id with no target yielded a loop that ran zero times and exited 0.
        run = _run(study_id=EMPA_REG, exclusion=[])

        with pytest.raises(LookupError, match="study 9"):
            count_watched(_CARMELINA_WATCH, run)


class TestEnumeratedWatchForTheStemlessShape:
    """EMPA-REG {27, 28} shares no stem, so it is watched by enumeration (§2.5.2)."""

    def test_should_count_both_the_heading_and_the_merged_content_criterion(self):
        # `spec.md` §2.1: id 27 is the heading emitted as a criterion
        # ("Pre-menopausal women criteria") and id 28 already merges both sub-bullets
        # ("Pre-menopausal women contraception/pregnancy status"). Their stems differ,
        # which is exactly why the §2.5 signal does not flag them (§2.5.2) and why this
        # sentence needs a matcher of its own to be measurable at all.
        watch = description_watch(
            label="EMPA-REG exclusion #11",
            study_id=EMPA_REG,
            role="exclusion",
            domain="Demographics",
            pattern=r"^Pre-menopausal women\b",
        )
        run = _run(
            study_id=EMPA_REG,
            exclusion=[
                _criterion(id=27, description="Pre-menopausal women criteria"),
                _criterion(
                    id=28,
                    description="Pre-menopausal women contraception/pregnancy status",
                ),
                _criterion(id=29, description="Type 1 diabetes mellitus", domain="Condition"),
            ],
        )

        assert count_watched(watch, run) == 2

    def test_should_count_one_when_the_heading_criterion_is_no_longer_emitted(self):
        # AC-003's target for this sentence: drop the heading, keep the merged content.
        watch = description_watch(
            label="EMPA-REG exclusion #11",
            study_id=EMPA_REG,
            role="exclusion",
            domain="Demographics",
            pattern=r"^Pre-menopausal women\b",
        )
        run = _run(
            study_id=EMPA_REG,
            exclusion=[
                _criterion(
                    id=27,
                    description="Pre-menopausal women contraception/pregnancy status",
                ),
            ],
        )

        assert count_watched(watch, run) == 1


class TestWatchShape:
    """A watch is data naming one protocol sentence, and it says which one."""

    def test_should_carry_the_label_study_and_role_it_was_built_with(self):
        assert isinstance(_CARMELINA_WATCH, SentenceWatch)
        assert _CARMELINA_WATCH.label == "CARMELINA exclusion #10"
        assert _CARMELINA_WATCH.study_id == CARMELINA
        assert _CARMELINA_WATCH.role == "exclusion"


# ---------------------------------------------------------------------------
# REQ-006: the distribution across runs, which is the thing being claimed about
# ---------------------------------------------------------------------------

def _distribution(label: str, counts: list[int]) -> WatchDistribution:
    """Build a distribution directly, bypassing pipeline invocation.

    Args:
        label: The watched sentence's name.
        counts: One emitted-criterion count per run, in run order.

    Returns:
        The distribution those counts describe.
    """
    return WatchDistribution(label=label, counts=tuple(counts))


class TestDistributionShape:
    """REQ-006 asks how many times a sentence produced N criteria. That is the artifact."""

    def test_should_report_how_many_runs_produced_each_count(self):
        dist = _distribution("s", [3, 2, 3, 3, 2])

        assert dist.distribution == {3: 3, 2: 2}

    def test_should_report_the_observed_range(self):
        dist = _distribution("s", [3, 2, 3, 3, 2])

        assert (dist.minimum, dist.maximum) == (2, 3)

    def test_should_report_no_single_mode_for_a_tied_distribution(self):
        # 2 and 3 each once is the historical record exactly, and naming either one
        # "the" count would invent a majority the two observations do not support.
        dist = _distribution("s", [2, 3])

        assert dist.distribution == {2: 1, 3: 1}


class TestVerdicts:
    """Four outcomes, and the two that look alike are the reason this is measured."""

    def test_should_call_disagreeing_counts_unstable(self):
        assert _distribution("s", [3, 2, 3, 3, 2]).verdict == "UNSTABLE"

    def test_should_call_every_run_emitting_one_converged(self):
        # The AC-008 target state.
        assert _distribution("s", [1, 1, 1, 1, 1]).verdict == "CONVERGED"

    def test_should_call_every_run_emitting_the_same_wrong_count_stable(self):
        # Stable is not converged. A sentence reliably emitting 3 is deterministic and
        # still the defect this SPEC exists to fix, so REQ-006 can pass while REQ-001
        # fails and the report has to be able to say so.
        assert _distribution("s", [3, 3, 3, 3, 3]).verdict == "STABLE"

    def test_should_call_every_run_emitting_nothing_vanished(self):
        # All-zero is perfectly stable and is a regression: the sentence stopped being
        # emitted. Folding it into STABLE would report a lost exclusion as a success,
        # and it is the same nothing the M2 detector reports for a converged sentence.
        assert _distribution("s", [0, 0, 0, 0, 0]).verdict == "VANISHED"

    def test_should_not_call_a_run_of_zeros_and_ones_vanished(self):
        assert _distribution("s", [0, 1, 1, 1, 1]).verdict == "UNSTABLE"


class TestHistoricalNonDetermination:
    """The one real observation on record, kept as a fixture so it stays reproducible."""

    def test_should_report_the_recorded_two_versus_three_disagreement_as_unstable(self):
        # `spec.md` §2.4: an earlier regeneration of CARMELINA from the same protocol
        # text produced 2 entries where the current store holds 3. This is the shape the
        # harness exists to catch, and the only pre-fix evidence that exists -- two runs,
        # not five, which is why AC-008 wants the measurement redone properly.
        dist = _distribution("CARMELINA exclusion #10", [2, 3])

        assert dist.distribution == {2: 1, 3: 1}
        assert dist.verdict == "UNSTABLE"
        assert not dist.stable
        assert not dist.converged


class TestMeasuring:
    """The pipeline is invoked N times and every run is counted for every watch."""

    def test_should_invoke_the_pipeline_once_per_run(self):
        seen: list[int] = []

        def run_once(index: int):
            seen.append(index)
            return _run(study_id=CARMELINA, exclusion=[
                _criterion(id=11, description=_CARMELINA_STEM),
            ])

        measure_emission_stability(watches=[_CARMELINA_WATCH], run_once=run_once, runs=5)

        assert seen == [0, 1, 2, 3, 4]

    def test_should_record_one_count_per_run_in_run_order(self):
        emitted = [3, 3, 2, 3, 2]

        def run_once(index: int):
            return _run(study_id=CARMELINA, exclusion=[
                _criterion(id=900 + n, description=f"{_CARMELINA_STEM} ({n})")
                for n in range(emitted[index])
            ])

        report = measure_emission_stability(
            watches=[_CARMELINA_WATCH], run_once=run_once, runs=5
        )

        assert report.runs == 5
        assert report.for_label("CARMELINA exclusion #10").counts == (3, 3, 2, 3, 2)
        assert report.for_label("CARMELINA exclusion #10").verdict == "UNSTABLE"

    def test_should_measure_every_watch_against_the_same_runs(self):
        empa_watch = description_watch(
            label="EMPA-REG exclusion #11",
            study_id=EMPA_REG,
            role="exclusion",
            domain="Demographics",
            pattern=r"^Pre-menopausal women\b",
        )

        def run_once(index: int):
            return {
                CARMELINA: {"inclusion": [], "exclusion": [
                    _criterion(id=11, description=_CARMELINA_STEM),
                ]},
                EMPA_REG: {"inclusion": [], "exclusion": [
                    _criterion(id=27, description="Pre-menopausal women criteria"),
                    _criterion(id=28, description="Pre-menopausal women contraception"),
                ]},
            }

        report = measure_emission_stability(
            watches=[_CARMELINA_WATCH, empa_watch], run_once=run_once, runs=5
        )

        assert [d.label for d in report.distributions] == [
            "CARMELINA exclusion #10",
            "EMPA-REG exclusion #11",
        ]
        assert report.for_label("CARMELINA exclusion #10").verdict == "CONVERGED"
        assert report.for_label("EMPA-REG exclusion #11").verdict == "STABLE"

    def test_should_report_converged_only_when_every_watch_converged(self):
        empa_watch = description_watch(
            label="EMPA-REG exclusion #11",
            study_id=EMPA_REG,
            role="exclusion",
            domain="Demographics",
            pattern=r"^Pre-menopausal women\b",
        )

        def run_once(index: int):
            return {
                CARMELINA: {"inclusion": [], "exclusion": [
                    _criterion(id=11, description=_CARMELINA_STEM),
                ]},
                EMPA_REG: {"inclusion": [], "exclusion": [
                    _criterion(id=27, description="Pre-menopausal women criteria"),
                    _criterion(id=28, description="Pre-menopausal women contraception"),
                ]},
            }

        report = measure_emission_stability(
            watches=[_CARMELINA_WATCH, empa_watch], run_once=run_once, runs=5
        )

        assert not report.converged


class TestRunFloor:
    """AC-008 says N >= 5, so fewer is refused rather than reported."""

    def test_should_refuse_to_measure_fewer_than_five_runs(self):
        def run_once(index: int):  # pragma: no cover - must never be reached
            raise AssertionError("run_once invoked despite an insufficient run count")

        with pytest.raises(ValueError, match="at least 5"):
            measure_emission_stability(
                watches=[_CARMELINA_WATCH], run_once=run_once, runs=4
            )

    def test_should_default_to_the_acceptance_criterion_floor(self):
        assert MINIMUM_RUNS == 5

        seen: list[int] = []

        def run_once(index: int):
            seen.append(index)
            return _run(study_id=CARMELINA, exclusion=[])

        measure_emission_stability(watches=[_CARMELINA_WATCH], run_once=run_once)

        assert len(seen) == MINIMUM_RUNS

    def test_should_refuse_to_measure_with_no_watches(self):
        # An empty watch list yields a report with nothing in it, whose `converged`
        # is vacuously true -- a fully green result asserting nothing at all.
        def run_once(index: int):  # pragma: no cover - must never be reached
            raise AssertionError("run_once invoked despite an empty watch list")

        with pytest.raises(ValueError, match="at least one watch"):
            measure_emission_stability(watches=[], run_once=run_once, runs=5)


class TestFailingRunIsNotAMeasurement:
    """A run that raised is not a run that emitted zero."""

    def test_should_propagate_a_pipeline_failure_rather_than_record_a_count(self):
        def run_once(index: int):
            if index == 2:
                raise RuntimeError("generate_from_nct returned status=failed")
            return _run(study_id=CARMELINA, exclusion=[
                _criterion(id=11, description=_CARMELINA_STEM),
            ])

        with pytest.raises(RuntimeError, match="generate_from_nct"):
            measure_emission_stability(
                watches=[_CARMELINA_WATCH], run_once=run_once, runs=5
            )


# ---------------------------------------------------------------------------
# AC-008: "the report records the observed pre-fix and post-fix distributions
# side by side"
# ---------------------------------------------------------------------------

def _report(counts_by_label: dict[str, list[int]]) -> Any:
    """Build a report directly from per-label counts.

    Args:
        counts_by_label: Watched sentence name -> one count per run.

    Returns:
        A `StabilityReport` over those counts.
    """
    from src.services.emission_stability import StabilityReport

    distributions = tuple(
        WatchDistribution(label=label, counts=tuple(counts))
        for label, counts in counts_by_label.items()
    )
    runs = len(next(iter(counts_by_label.values())))
    return StabilityReport(runs=runs, distributions=distributions)


class TestSideBySideReport:
    """One row per sentence, both measurements on it, and the verdict for each."""

    def test_should_put_the_pre_and_post_distributions_on_one_row(self):
        pre = _report({"CARMELINA exclusion #10": [3, 3, 2, 3, 2]})
        post = _report({"CARMELINA exclusion #10": [1, 1, 1, 1, 1]})

        rendered = render_comparison(pre=pre, post=post)

        row = next(
            line for line in rendered.splitlines()
            if line.startswith("| CARMELINA exclusion #10")
        )
        assert "3x3" in row and "2x2" in row
        assert "UNSTABLE" in row
        assert "1x5" in row
        assert "CONVERGED" in row

    def test_should_say_a_side_was_not_measured_rather_than_leave_it_blank(self):
        # M3 measures the pre-fix baseline; the post-fix column does not exist yet. A
        # blank there is indistinguishable from a measurement that found nothing.
        pre = _report({"CARMELINA exclusion #10": [3, 3, 2, 3, 2]})

        rendered = render_comparison(pre=pre, post=None)

        row = next(
            line for line in rendered.splitlines()
            if line.startswith("| CARMELINA exclusion #10")
        )
        assert "not measured" in row

    def test_should_include_a_sentence_only_one_side_measured(self):
        pre = _report({"CARMELINA exclusion #10": [3, 3, 3, 3, 3]})
        post = _report({"EMPA-REG exclusion #11": [1, 1, 1, 1, 1]})

        rendered = render_comparison(pre=pre, post=post)

        assert "| CARMELINA exclusion #10" in rendered
        assert "| EMPA-REG exclusion #11" in rendered

    def test_should_state_how_a_distribution_cell_reads(self):
        # "3x3" is unreadable without saying which number is which.
        rendered = render_comparison(pre=_report({"s": [3, 3, 2, 3, 2]}), post=None)

        assert "criteria" in rendered and "runs" in rendered

    def test_should_refuse_to_render_a_comparison_of_nothing(self):
        with pytest.raises(ValueError, match="at least one"):
            render_comparison(pre=None, post=None)


# ---------------------------------------------------------------------------
# Composition with M2: any detected cluster becomes a watch
# ---------------------------------------------------------------------------

class TestWatchesFromDetectedClusters:
    """A cluster the detector reported names a sentence worth watching."""

    def test_should_build_one_watch_per_detected_cluster(self):
        criteria = [
            _criterion(id=11, description=f"{_CARMELINA_STEM} (<= 1 year)"),
            _criterion(id=12, description=f"{_CARMELINA_STEM} (General)"),
            _criterion(id=18, description=_CARMELINA_STEM),
            _criterion(id=4, description="Alcohol or drug abuse", domain="Observation"),
            _criterion(id=40, description="Alcohol or drug abuse (12 months)",
                       domain="Observation"),
        ]
        clusters = detect_all_restated_clusters(
            inclusion_criteria=[], exclusion_criteria=criteria
        )

        watches = watches_from_clusters(clusters, study_id=CARMELINA, study_label="T")

        assert len(watches) == 2
        assert all(w.study_id == CARMELINA and w.role == "exclusion" for w in watches)

    def test_should_keep_counting_a_cluster_after_it_collapses_to_one(self):
        # The whole reason a watch is derived from a cluster rather than reusing the
        # detector: the detector reports sets of two or more, so once the fix lands it
        # reports nothing for this sentence -- the same nothing it reports for a
        # sentence that vanished. The watch keeps counting and says 1.
        pre_fix = [
            _criterion(id=11, description=f"{_CARMELINA_STEM} (<= 1 year)"),
            _criterion(id=12, description=f"{_CARMELINA_STEM} (General)"),
            _criterion(id=18, description=_CARMELINA_STEM),
        ]
        clusters = detect_all_restated_clusters(
            inclusion_criteria=[], exclusion_criteria=pre_fix
        )
        [watch] = watches_from_clusters(clusters, study_id=CARMELINA, study_label="T")

        post_fix = _run(
            study_id=CARMELINA,
            exclusion=[_criterion(id=11, description=_CARMELINA_STEM)],
        )

        assert detect_all_restated_clusters(
            inclusion_criteria=[], exclusion_criteria=post_fix[CARMELINA]["exclusion"]
        ) == []
        assert count_watched(watch, post_fix) == 1

    def test_should_distinguish_a_collapsed_cluster_from_a_vanished_one(self):
        pre_fix = [
            _criterion(id=11, description=f"{_CARMELINA_STEM} (<= 1 year)"),
            _criterion(id=12, description=_CARMELINA_STEM),
        ]
        clusters = detect_all_restated_clusters(
            inclusion_criteria=[], exclusion_criteria=pre_fix
        )
        [watch] = watches_from_clusters(clusters, study_id=CARMELINA, study_label="T")

        vanished = _run(study_id=CARMELINA, exclusion=[])

        assert count_watched(watch, vanished) == 0


# ---------------------------------------------------------------------------
# AC-008 subject: the three spec.md §2.1 sentences
# ---------------------------------------------------------------------------

class TestEnumeratedSpecWatches:
    """AC-008 names the §2.1 clusters, so the shipped watch set is those three."""

    def test_should_watch_the_three_enumerated_sentences(self):
        assert [w.label for w in SPEC_2_1_WATCHES] == [
            "CARMELINA exclusion #10",
            "CAROLINA exclusion #17",
            "EMPA-REG exclusion #11",
        ]
        assert all(w.role == "exclusion" for w in SPEC_2_1_WATCHES)

    def test_should_count_the_pre_fix_reference_store_shape(self):
        # `spec.md` §2.1: 3 criteria for CARMELINA, 2 byte-identical for CAROLINA,
        # 2 for EMPA-REG (heading + merged content).
        run = {
            9: {"inclusion": [], "exclusion": [
                _criterion(id=11, description=f"{_CARMELINA_STEM} (<= 1 year)"),
                _criterion(id=12, description=f"{_CARMELINA_STEM} (General)"),
                _criterion(id=18, description=_CARMELINA_STEM),
            ]},
            10: {"inclusion": [], "exclusion": [
                _criterion(id=21, description="Pre-menopausal women/Nursing/Pregnant/"
                                              "Not using contraception"),
                _criterion(id=53, description="Pre-menopausal women/Nursing/Pregnant/"
                                              "Not using contraception"),
            ]},
            8: {"inclusion": [], "exclusion": [
                _criterion(id=27, description="Pre-menopausal women criteria"),
                _criterion(id=28, description="Pre-menopausal women contraception/"
                                              "pregnancy status"),
            ]},
        }

        counts = {w.label: count_watched(w, run) for w in SPEC_2_1_WATCHES}

        assert counts == {
            "CARMELINA exclusion #10": 3,
            "CAROLINA exclusion #17": 2,
            "EMPA-REG exclusion #11": 2,
        }

    def test_should_count_one_each_at_the_ac_008_target_state(self):
        run = {
            9: {"inclusion": [], "exclusion": [
                _criterion(id=11, description=_CARMELINA_STEM),
            ]},
            10: {"inclusion": [], "exclusion": [
                _criterion(id=21, description="Pre-menopausal women/Nursing/Pregnant/"
                                              "Not using contraception"),
            ]},
            8: {"inclusion": [], "exclusion": [
                _criterion(id=27, description="Pre-menopausal women contraception/"
                                              "pregnancy status"),
            ]},
        }

        assert all(count_watched(w, run) == 1 for w in SPEC_2_1_WATCHES)


# ---------------------------------------------------------------------------
# Reading one run back out of the store
# ---------------------------------------------------------------------------

class TestReadingAStudyRecord:
    """The live driver reads the store; an unprocessed study is not an empty one."""

    def test_should_split_a_study_record_into_its_two_roles(self):
        study = {
            "id": CARMELINA,
            "eligibility": {
                "inclusionCriteria": [_criterion(id=1, description="Type 2 diabetes")],
                "exclusionCriteria": [
                    _criterion(id=11, description=_CARMELINA_STEM),
                    _criterion(id=12, description=f"{_CARMELINA_STEM} (General)"),
                ],
            },
        }

        criteria = criteria_from_study_record(study)

        assert len(criteria["inclusion"]) == 1
        assert len(criteria["exclusion"]) == 2

    def test_should_refuse_a_study_whose_eligibility_was_never_processed(self):
        # Every watch would count 0 and every run would agree, so the report would read
        # VANISHED across the board -- a deterministic-looking regression produced by a
        # pipeline that silently did not run.
        with pytest.raises(ValueError, match="no criteria"):
            criteria_from_study_record({"id": CARMELINA, "eligibility": {}})

    def test_should_refuse_a_study_record_with_no_eligibility_at_all(self):
        with pytest.raises(ValueError, match="no criteria"):
            criteria_from_study_record({"id": CARMELINA})


class TestBaselinePersistence:
    """AC-008 wants both sides side by side, and they are measured months apart."""

    def test_should_round_trip_a_measurement_through_plain_data(self):
        # The pre-fix baseline is recorded at M3 and the post-fix measurement happens
        # after M4's prompt change. If the baseline cannot survive the gap, "side by
        # side" degrades into re-running the pre-fix measurement against a fixed
        # pipeline, which is no longer the pre-fix measurement.
        original = _report({
            "CARMELINA exclusion #10": [3, 3, 2, 3, 2],
            "EMPA-REG exclusion #11": [2, 2, 2, 2, 2],
        })

        restored = report_from_dict(json.loads(json.dumps(report_to_dict(original))))

        assert restored == original
        assert restored.for_label("CARMELINA exclusion #10").verdict == "UNSTABLE"

    def test_should_render_a_restored_baseline_against_a_fresh_measurement(self):
        baseline = report_from_dict(
            json.loads(json.dumps(report_to_dict(
                _report({"CARMELINA exclusion #10": [3, 3, 2, 3, 2]})
            )))
        )
        post = _report({"CARMELINA exclusion #10": [1, 1, 1, 1, 1]})

        row = next(
            line for line in render_comparison(pre=baseline, post=post).splitlines()
            if line.startswith("| CARMELINA exclusion #10")
        )

        assert "UNSTABLE" in row and "CONVERGED" in row
