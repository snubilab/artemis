"""SPEC-INFRA-004 AC-016 / REQ-013: the two collapse paths never both claim one criterion.

`SPEC-INFRA-003`'s Demographics path and this SPEC's generalized path are different
algorithms over different grouping units — the first reduces a **whole role** to one
survivor, the second partitions **one stem group** into classes. An overlap is therefore not
merely redundant work: a whole-role reduction let loose on stem-grouped data can drop a
criterion belonging to a different stem and a different entity.

Nothing prevented both paths from firing on one criterion except a coincidence — every
Demographics criterion the Demographics path claims currently carries empty `sourceText`, so
REQ-004 withheld the generalized path from it. `plan.md` B-1 records that `sourceText`'s
populated/empty status has **already inverted once** between `SPEC-INFRA-003` and this SPEC.
A design resting on it is resting on something that has already moved.

REQ-013 replaces the coincidence with a construction: the generalized path considers a
criterion only where `is_restatable_demographic` returns false, so the two eligible sets are
complementary by definition under any `sourceText` state.

**Fixture 2 is the criterion that matters, and its detection power is itself tested** (see
`TestFixtureTwoCanActuallyDetectAMissingGate`). `acceptance.md` records that populating
`sourceText` from the raw `description` makes this criterion vacuous — it passes identically
with the gate ON and OFF — so the fixture populates from the description **stem** instead,
and the test below proves the distinction empirically rather than trusting the note.
"""
from __future__ import annotations

import pytest

from src.services.restated_demographics import (
    collapse_all_restated_demographics,
    is_restatable_demographic,
)
from src.services.restated_distinctness import (
    collapse_all_restated_criteria,
    considered_by_generalized_path,
)
from tests.infra_004_store_fixture import (
    ROLES,
    criteria,
    populate_demographics_source_text_from_stem,
    studies,
    study_by_nct,
    transform_store,
)

CAROLINA = "NCT01243424"
CARMELINA = "NCT01897532"


def _records(study_list: list[dict]) -> list[tuple]:
    """Generalized-path records across a whole store, as AC-016's comparison tuple.

    The tuple carries survivor **id** and **stem** rather than survivor `sourceText`.
    Fixture 2 mutates `sourceText` on exactly the Demographics-path criteria, so a tuple
    containing it could never match across the two fixtures even for a correct
    implementation — it would manufacture a REQ-013 violation report on every conforming
    run. Comparing on identity fields the transformation does not touch is what makes the
    criterion falsifiable rather than always-failing.
    """
    out = []
    for study in study_list:
        _, records, _ = collapse_all_restated_criteria(
            inclusion_criteria=criteria(study, "inclusion"),
            exclusion_criteria=criteria(study, "exclusion"),
        )
        for r in records:
            out.append(
                (
                    study.get("nctId") or f"study{study['studyId']}",
                    r["role"],
                    r["domain"],
                    r["stem"],
                    r["survivorId"],
                    tuple(sorted(map(str, r["droppedIds"]))),
                )
            )
    return sorted(out)


@pytest.fixture(scope="module")
def fixture_one() -> list[dict]:
    """The real store as it stands."""
    return studies()


@pytest.fixture(scope="module")
def fixture_two() -> list[dict]:
    """The real store with every Demographics-path criterion given a stem `sourceText`."""
    return transform_store(studies(), populate_demographics_source_text_from_stem)


class TestTheTwoPathsConsiderDisjointSets:
    """AC-016's first clause, over fixtures 1 and 2."""

    def test_should_never_let_one_criterion_reach_both_paths_in_the_real_store(self, fixture_one):
        for study in fixture_one:
            for role in ROLES:
                members = criteria(study, role)
                generalized = {id(c) for c in considered_by_generalized_path(members)}
                demographic = {id(c) for c in members if is_restatable_demographic(c)}
                assert not (generalized & demographic)
                assert len(generalized) + len(demographic) == len(members), (
                    "every criterion must be claimed by exactly one path"
                )

    def test_should_still_be_disjoint_once_demographics_source_text_is_populated(self, fixture_two):
        """The regeneration `spec.md` §2.5 warns of. Disjointness is the predicate, not the
        field, so populating `sourceText` must change nothing about the routing."""
        for study in fixture_two:
            for role in ROLES:
                members = criteria(study, role)
                generalized = {id(c) for c in considered_by_generalized_path(members)}
                demographic = {id(c) for c in members if is_restatable_demographic(c)}
                assert not (generalized & demographic)


class TestPopulatingSourceTextChangesNothing:
    """AC-016's second clause — the criterion fixture 2 exists for."""

    def test_should_emit_identical_generalized_records_for_both_fixtures(
        self, fixture_one, fixture_two
    ):
        before, after = _records(fixture_one), _records(fixture_two)
        assert after == before, {
            "only-in-populated": [r for r in after if r not in before],
            "only-in-original": [r for r in before if r not in after],
        }

    def test_should_emit_the_fifteen_records_the_spec_measured(self, fixture_one):
        """`acceptance.md` records 15 generalized-path records with REQ-013 ON. Pinned so a
        change in the count is visible rather than absorbed."""
        assert len(_records(fixture_one)) == 15


class TestFixtureTwoCanActuallyDetectAMissingGate:
    """The test of the test. A fixture that cannot fail proves nothing.

    `acceptance.md` measured that a `description`-populated fixture 2 emits an identical
    record count with the gate ON and OFF, so it passes on a broken implementation. The
    stem-populated form emits one more record when the gate is removed — exactly CARMELINA
    {14,23}. That difference is asserted here, because a criterion whose detection power is
    only claimed is a criterion that has not been checked.
    """

    def test_should_emit_one_extra_record_when_the_gate_is_removed(self, monkeypatch, fixture_two):
        with_gate = _records(fixture_two)
        monkeypatch.setattr(
            "src.services.restated_distinctness.is_restatable_demographic",
            lambda criterion: False,
        )
        without_gate = _records(fixture_two)
        extra = [r for r in without_gate if r not in with_gate]
        assert len(without_gate) == len(with_gate) + 1, (len(with_gate), len(without_gate))
        assert len(extra) == 1
        assert extra[0][0] == CARMELINA
        assert extra[0][1] == "exclusion"
        assert extra[0][3] == "Pregnancy/Nursing/Uncontrolled Contraception"

    def test_should_be_vacuous_when_populated_from_the_raw_description(self, monkeypatch):
        """The measured counter-example, kept as a live test rather than a note.

        Populating from `description` puts CARMELINA {14,23} in different distinctness
        classes — they differ by exactly the trailing `(Exclusion)` the stem operator strips
        — so the generalized path declines them whether or not the gate exists, and the
        record count is identical either way. This is what the stem form avoids.
        """
        import copy

        from src.services.restated_demographics import is_restatable_demographic as gate

        def populate_from_description(members):
            out = copy.deepcopy(members)
            for c in out:
                if gate(c):
                    c["sourceText"] = c.get("description") or ""
            return out

        store = transform_store(studies(), populate_from_description)
        with_gate = _records(store)
        monkeypatch.setattr(
            "src.services.restated_distinctness.is_restatable_demographic",
            lambda criterion: False,
        )
        assert len(_records(store)) == len(with_gate), (
            "the description-populated fixture is expected to be vacuous; if this now "
            "detects the gate, acceptance.md's measurement no longer holds"
        )


class TestFixtureThreeIsNotOrphaned:
    """AC-016's third clause. Disjointness alone is not sufficient — disjointness *without
    orphans* is the requirement.

    A plain `domain != "Demographics"` gate would also achieve disjointness, but CAROLINA
    inclusion `Age >= 70 years` {4,33} is Demographics *and* carries a non-null
    `valueConstraint`, so the Demographics path rejects it on gate 2. Under a domain gate
    that genuine duplicate would be collapsed by neither path.
    """

    def test_should_collapse_carolina_age_seventy_on_the_generalized_path(self):
        carolina = study_by_nct(CAROLINA)
        _, records, _ = collapse_all_restated_criteria(
            inclusion_criteria=criteria(carolina, "inclusion"),
            exclusion_criteria=criteria(carolina, "exclusion"),
        )
        (record,) = [r for r in records if r["stem"] == "Age >= 70 years"]
        assert record["domain"] == "Demographics"
        assert record["role"] == "inclusion"
        assert len(record["droppedIds"]) == 1

    def test_should_emit_no_demographics_path_record_for_it(self):
        carolina = study_by_nct(CAROLINA)
        _, demo_records = collapse_all_restated_demographics(
            inclusion_criteria=criteria(carolina, "inclusion"),
            exclusion_criteria=criteria(carolina, "exclusion"),
        )
        claimed = {
            str(i) for r in demo_records for i in ([r["survivorId"]] + list(r["droppedIds"]))
        }
        age_group = [
            c
            for c in criteria(carolina, "inclusion")
            if (c.get("description") or "").startswith("Age >= 70")
        ]
        assert len(age_group) == 2
        assert not ({str(c["id"]) for c in age_group} & claimed)
