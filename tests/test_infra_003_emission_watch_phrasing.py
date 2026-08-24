"""SPEC-INFRA-003 REQ-006: a watch must survive the model rephrasing what it counts.

The M3 instrument measured the pre-fix baseline correctly and then misreported the very
run it exists to judge. Its M4-iteration-1 post-fix report read `VANISHED` -- every run
emitted nothing -- for CAROLINA exclusion #17 and EMPA-REG exclusion #11. Read directly,
the run stores held one criterion for EMPA-REG (converged, the fix working) and two for
CAROLINA (unchanged). Neither sentence had vanished; the watches had stopped matching.

**Why they stopped.** Both were keyed on pre-fix *phrasing*.

- CAROLINA's `stem_watch` keyed on the stem `Pre-menopausal women/Nursing/Pregnant/Not
  using contraception`. Post-fix the model wrote `... /Uncontrolled Contraception`. The
  stem is an exact-equality test, so a reworded tail is a total miss.
- EMPA-REG's `description_watch` keyed on `^Pre-menopausal women\\b`. Post-fix the model
  led with `Pregnancy/...`, so the anchored pattern never fired.

**Why that is worse than a wrong number.** A watch that only matches pre-fix phrasing can
report on exactly one thing: whether the old bug's exact wording is gone. It cannot report
on whether the sentence converged, which is the question AC-008 asks. And it fails in the
most expensive direction available: `VANISHED` names total loss of an exclusion, so the
instrument turned a converged sentence into a louder alarm than the defect it replaced.
The measurement had to be redone by hand against the raw JSON.

**The fix.** Key a watch on what the sentence is *about* -- its domain plus the topic
vocabulary of the clinical cluster -- rather than on the words one run happened to choose.
`topic_watch` is that key, and `SPEC_2_1_WATCHES` uses it for all three sentences.

The narrow constructors stay. `stem_watch` is what `watches_from_clusters` builds from a
detector run, where keying on the observed stem is the whole point: those watches are
derived from one run and consumed against it. The first two tests below pin their
brittleness so the reason `SPEC_2_1_WATCHES` no longer uses them is recorded next to
them rather than in a commit message.

Fixtures are the descriptions the runs actually emitted, read out of
`output/stability/{pre,post}-fix/run-*/studies.json` (5 runs each side, byte-identical
descriptions within a side).
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.emission_stability import (
    SPEC_2_1_WATCHES,
    count_watched,
    description_watch,
    stem_watch,
    topic_watch,
)

# Study ids as the reingest entry point's target table assigns them.
EMPA_REG = 8
CARMELINA = 9
CAROLINA = 10

# ---------------------------------------------------------------------------
# What the runs actually emitted (Demographics exclusion criteria only).
#
# Pre-fix and post-fix each held these descriptions identically in all 5 runs, so one
# tuple per (side, study) is the whole observation rather than a sample of it.
# ---------------------------------------------------------------------------

PRE_FIX_DESCRIPTIONS: dict[int, tuple[str, ...]] = {
    EMPA_REG: (
        "Pre-menopausal women criteria",
        "Pre-menopausal women contraception/pregnancy status",
    ),
    CARMELINA: (
        "Pregnancy/Nursing/Uncontrolled Contraception",
        "Pregnancy/Nursing/Uncontrolled Contraception (<= 1 year)",
        "Pregnancy/Nursing/Uncontrolled Contraception (General)",
    ),
    CAROLINA: (
        "Pre-menopausal women/Nursing/Pregnant/Not using contraception",
        "Pre-menopausal women/Nursing/Pregnant/Not using contraception",
    ),
}

POST_FIX_DESCRIPTIONS: dict[int, tuple[str, ...]] = {
    EMPA_REG: ("Pregnancy/Nursing/Uncontrolled Contraception",),
    CARMELINA: (
        "Pregnancy/Nursing/Uncontrolled Contraception",
        "Pregnancy/Nursing/Uncontrolled Contraception (Exclusion)",
    ),
    CAROLINA: (
        "Pregnancy/Nursing/Uncontrolled Contraception",
        "Pre-menopausal women/Nursing/Pregnant/Uncontrolled Contraception",
    ),
}

# The counts the orchestrator established by reading the run stores directly, which is
# the ground truth these watches have to reproduce.
PRE_FIX_TRUTH = {EMPA_REG: 2, CARMELINA: 3, CAROLINA: 2}
POST_FIX_TRUTH = {EMPA_REG: 1, CARMELINA: 2, CAROLINA: 2}

WATCH_LABEL = {
    EMPA_REG: "EMPA-REG exclusion #11",
    CARMELINA: "CARMELINA exclusion #10",
    CAROLINA: "CAROLINA exclusion #17",
}


def _criterion(
    *,
    id: int,
    description: str,
    domain: str = "Demographics",
    value_constraint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a top-level IR criterion in the shape `spec.md` §2.1 documents.

    Args:
        id: Criterion id. Varied deliberately, because nothing here may key on it.
        description: The paraphrased description. `sourceText` is empty on every
            affected criterion, so this is all a watch has to go on.
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


def _run(study_id: int, descriptions: tuple[str, ...], **kwargs: Any) -> dict:
    """Build one run's output holding one study's exclusion criteria.

    Args:
        study_id: The study these criteria belong to.
        descriptions: One description per emitted criterion, in emission order.
        **kwargs: Passed through to `_criterion` for every criterion built.

    Returns:
        Run output shaped study id -> role -> criteria.
    """
    return {
        study_id: {
            "inclusion": [],
            "exclusion": [
                _criterion(id=index, description=description, **kwargs)
                for index, description in enumerate(descriptions, start=1)
            ],
        }
    }


def _watch_for(study_id: int):
    """Return the `SPEC_2_1_WATCHES` entry watching one study.

    Args:
        study_id: The study whose watch is wanted.

    Returns:
        That study's watch.
    """
    return next(w for w in SPEC_2_1_WATCHES if w.study_id == study_id)


# ---------------------------------------------------------------------------
# Characterization: why the narrow constructors cannot key SPEC_2_1_WATCHES
# ---------------------------------------------------------------------------


def test_stem_watch_should_stop_counting_when_the_model_rewords_the_tail():
    """A stem watch is exact equality, so CAROLINA's reworded tail is a total miss.

    This is the M4-iteration-1 defect verbatim: two criteria present, watch reports zero,
    report reads VANISHED. Pinned rather than fixed -- `watches_from_clusters` builds stem
    watches from a detector run and consumes them against that same run, where exact
    equality on the observed stem is correct.
    """
    watch = stem_watch(
        label="CAROLINA exclusion #17 (pre-fix phrasing)",
        study_id=CAROLINA,
        role="exclusion",
        domain="Demographics",
        stem="Pre-menopausal women/Nursing/Pregnant/Not using contraception",
    )

    pre = _run(CAROLINA, PRE_FIX_DESCRIPTIONS[CAROLINA])
    post = _run(CAROLINA, POST_FIX_DESCRIPTIONS[CAROLINA])

    assert count_watched(watch, pre) == PRE_FIX_TRUTH[CAROLINA]
    # Both criteria are still there; only the wording moved.
    assert count_watched(watch, post) == 0


def test_description_watch_should_stop_counting_when_the_model_rewords_the_lead():
    """An anchored description watch misses once the model leads with another phrase.

    EMPA-REG's half of the same defect, and the more misleading one: the sentence had
    actually converged to exactly one criterion -- the outcome AC-003 asks for -- and the
    watch reported it as a lost exclusion.
    """
    watch = description_watch(
        label="EMPA-REG exclusion #11 (pre-fix phrasing)",
        study_id=EMPA_REG,
        role="exclusion",
        domain="Demographics",
        pattern=r"^Pre-menopausal women\b",
    )

    pre = _run(EMPA_REG, PRE_FIX_DESCRIPTIONS[EMPA_REG])
    post = _run(EMPA_REG, POST_FIX_DESCRIPTIONS[EMPA_REG])

    assert count_watched(watch, pre) == PRE_FIX_TRUTH[EMPA_REG]
    assert count_watched(watch, post) == 0


# ---------------------------------------------------------------------------
# Regression: the shipped watches count both sides correctly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("study_id", sorted(POST_FIX_TRUTH))
def test_shipped_watch_should_count_post_fix_criteria_when_phrasing_changed(study_id: int):
    """Every `SPEC_2_1_WATCHES` entry reproduces the hand-verified post-fix count.

    The exact case that broke. `2` for CARMELINA and CAROLINA is not a pass -- both are
    still emitting a second copy, which is what AC-001 and AC-002 fail on -- but it is the
    honest count, and telling `2` apart from `0` is the instrument's entire job.
    """
    watch = _watch_for(study_id)
    run = _run(study_id, POST_FIX_DESCRIPTIONS[study_id])

    assert count_watched(watch, run) == POST_FIX_TRUTH[study_id]


@pytest.mark.parametrize("study_id", sorted(PRE_FIX_TRUTH))
def test_shipped_watch_should_reproduce_pre_fix_counts_when_watch_key_changed(study_id: int):
    """Rekeying the watches leaves the stored pre-fix baseline still comparable.

    AC-008 reports the two sides next to each other, and the pre-fix side was measured
    with the old narrow watches and serialized before this change. Had the new key scored
    the pre-fix descriptions differently, that stored column would silently stop meaning
    what its header says and the comparison would be between two instruments rather than
    two runs.
    """
    watch = _watch_for(study_id)
    run = _run(study_id, PRE_FIX_DESCRIPTIONS[study_id])

    assert count_watched(watch, run) == PRE_FIX_TRUTH[study_id]


def test_shipped_watches_should_cover_the_three_sentences_ac_008_names():
    """The watch list is the three `spec.md` §2.1 sentences, one apiece."""
    assert {w.study_id for w in SPEC_2_1_WATCHES} == {EMPA_REG, CARMELINA, CAROLINA}
    assert {w.label for w in SPEC_2_1_WATCHES} == set(WATCH_LABEL.values())
    assert {w.role for w in SPEC_2_1_WATCHES} == {"exclusion"}


# ---------------------------------------------------------------------------
# Precision: the loosened key must not reach past the cluster it names
# ---------------------------------------------------------------------------


def test_topic_watch_should_ignore_criterion_when_domain_differs():
    """The domain gate holds, so a topic term elsewhere cannot be counted here.

    "Negative pregnancy test required" is a Measurement, not this Demographics sentence,
    and it carries the topic vocabulary. Without the domain gate the watch would fold a
    genuinely distinct criterion into the count it reports for one sentence.
    """
    watch = _watch_for(CARMELINA)
    run = {
        CARMELINA: {
            "inclusion": [],
            "exclusion": [
                _criterion(id=1, description="Pregnancy/Nursing/Uncontrolled Contraception"),
                _criterion(id=2, description="Negative pregnancy test", domain="Measurement"),
            ],
        }
    }

    assert count_watched(watch, run) == 1


def test_topic_watch_should_ignore_criterion_when_no_topic_term_appears():
    """An unrelated Demographics exclusion is not counted as this sentence.

    The three trials measured so far put nothing but this cluster in the Demographics
    exclusion bucket, so the live runs cannot distinguish a precise topic key from a bare
    domain key. This is the case that separates them, and it is the one a fourth trial
    would supply for free.
    """
    watch = _watch_for(CARMELINA)
    run = {
        CARMELINA: {
            "inclusion": [],
            "exclusion": [
                _criterion(id=1, description="Pregnancy/Nursing/Uncontrolled Contraception"),
                _criterion(id=2, description="Age over 80 years"),
                _criterion(id=3, description="Institutionalized patients"),
            ],
        }
    }

    assert count_watched(watch, run) == 1


@pytest.mark.parametrize(
    "description",
    [
        "Pregnancy/Nursing/Uncontrolled Contraception",
        "Pregnancy/Nursing/Uncontrolled Contraception (Exclusion)",
        "Pre-menopausal women/Nursing/Pregnant/Uncontrolled Contraception",
        "Pre-menopausal women criteria",
        "Women of childbearing potential",
        "Breast feeding",
        "Lactating women",
        "PREGNANT OR NURSING",
    ],
    ids=lambda d: d[:32],
)
def test_topic_watch_should_count_criterion_when_cluster_reworded(description: str):
    """Every rewording of the cluster seen or plausible is counted.

    The first three are the post-fix descriptions, the fourth a pre-fix one, and the rest
    are rewordings this key is meant to survive -- the point of the change being that the
    next rewording must not need a code edit to stay measured. The last checks the match
    is case-insensitive, since nothing constrains the model's capitalization.
    """
    watch = _watch_for(CARMELINA)
    run = _run(CARMELINA, (description,))

    assert count_watched(watch, run) == 1


def test_topic_watch_should_refuse_when_topic_set_empty():
    """An empty topic set matches every criterion in the domain.

    That watch would report the size of the Demographics exclusion bucket while its label
    claims one sentence -- a plausible number, wrong for a reason nothing downstream could
    see. Cheaper to refuse than to explain later.
    """
    with pytest.raises(ValueError, match="at least one topic"):
        topic_watch(
            label="empty",
            study_id=CARMELINA,
            role="exclusion",
            domain="Demographics",
            topics=(),
        )


def test_topic_watch_should_count_criterion_when_value_constraint_present():
    """A criterion that gained a constraint is still counted, unlike a stem watch.

    `stem_watch` inherits the §2.5 `valueConstraint: null` gate because it shares the
    detector's key. This watch is outside that signal by construction, and inheriting the
    gate would make a criterion that acquired a constraint drop silently out of the count
    -- a change worth seeing rather than hiding.
    """
    watch = _watch_for(CARMELINA)
    run = _run(
        CARMELINA,
        ("Pregnancy/Nursing/Uncontrolled Contraception",),
        value_constraint={"op": "gte", "value": 1.0, "unitText": "year"},
    )

    assert count_watched(watch, run) == 1
