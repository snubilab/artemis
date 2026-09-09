"""The census is anchored to the store, not only to itself.

`3a3581b` taught the gate to read `_generationCensus`, and every check it grew reads
the census against the census: the balance identity
`total == mapped + unmapped + demographicRules + skipped`, the two counter-vs-list
cross-checks, the `mappable == mapped + unmapped` identity. Each term in all four is
written by the artifact being checked, so all four can be satisfied by an artifact that
lost criteria and did not say so -- self-consistency is exactly what a producer that
stops writing a record list is able to restore.

Measured on the real 12-file batch at `output/site_gap/2026-09-09/deliver_v3`, before
this module was written:

  * strike every `_unmappedCriteria` row, set `unmapped: 0`, decrement `total` only
    -> all 12 files still FAIL, on `mappable != mapped + unmapped`;
  * do the same and decrement `mappable` too -> 8 of the 12 PASS, `leader_treatment`
    among them, reading "35 mapped, 0 unmapped, 8 skipped (all permitted)".

The 4 that still failed did so on the stranded skip and the asserted-bound detector,
neither of which reads the census -- so they were never evidence the hole was closed.

The anchor is `len(criteria_index(study))`: the store study's own criteria rows, the
one referent outside the file. On that same batch the two sides agree exactly on every
file -- aristotle 39/39, carmelina 39/39, carolina 114/114, empa-reg 73/73, leader
49/49, plato 46/46 -- so the anchor adds no failure the batch did not already carry.

That anchor shipped as a LOWER bound with two holes named in the commit, and both are
closed here.

The bound is defeatable by inflating the census before decrementing it: pad `total`,
`mappable` and `mapped` by twice the loss and give half back, and everything stays
self-consistent while `total` lands ABOVE the store, where `total < len(index)` never
looks. Measured on the same batch, that shape passes 8 of the 12 files against the
lower bound and fails all 12 against the equality. It is an equality now, and the 11
gate-test fixtures whose synthetic censuses claimed 31-41 criteria over stores of 2-15
-- every one of them the over-count direction, none of them loss -- derive `mapped`
from their own store rather than naming a number.

The second hole is a swap rather than a count, so no anchor over `total` can see it:
strike an `_unmappedCriteria` row and book the criterion as `mapped`. `total` never
moves, the balance and the mappable identity hold, and the criterion merely changes
which side of the partition it sits on -- so the residual set identity below moves with
it too. Measured on that batch it passes 8 of the 12 files. What does not follow the
criterion across is the concept set, because none was ever minted for it, so `mapped`
is anchored to `_criterionConceptSetRefs`: one role-keyed entry per criterion the
producer actually built a set for. On all 71 artifacts under `output/` that carry both
keys, `mapped` equals the count of those entries exactly.

That link is CONDITIONAL, and the limit is real: 73 of the 144 census-carrying
artifacts carry no refs map, the previous day's whole delivery among them, because the
draft path pops the key. Failing them would fail a correct batch, so the check runs
when the key is there and the row says so when it is not.

Between the two, the outcomes are also reconciled as SETS: the two record buckets name
their criterion ids, `mapped` and `demographicRules` are the only outcomes left, so
what the buckets do not name must be exactly what those two counters claim. That sees a
criterion recorded under two outcomes at once, and a record naming a criterion the
store does not carry while a real one goes unaccounted for -- neither of which changes
a count.

Two smaller fail-open paths in the same file are covered here too, neither of which has
an instance in that batch (0 non-dict record rows, 0 group labels without a `groupId`
across all 12 files):

  * a `_skippedCriteria` entry that is not a dict was passed over in silence, while
    `unmapped_criteria_violations` reports the same malformation one channel over --
    and `census.skipped` counts it either way, so the balance and the anchor both still
    hold while the criterion it stands for names no permit anyone can read;
  * a `group-label` permit whose store row carries no `groupId` returned before the
    stranded-threshold re-derivation and before the all-members-lost check, granting
    the permit on the record's own word.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.utils.criterion_refusal import REFUSAL_UNMAPPABLE_PLACEHOLDER


def _criterion(
    criterion_id: int,
    label: str,
    *,
    domain: str = "Drug",
    is_group_label: bool = False,
    group_id: str | None = None,
) -> dict[str, Any]:
    """One store criterion row, in the shape `_record_skip` reads it from."""
    return {
        "id": criterion_id,
        "sourceText": label,
        "domain": domain,
        "isGroupLabel": is_group_label,
        "groupId": group_id,
        "valueConstraint": None,
    }


#: Six criteria, and every one of them reaches an outcome in `CLEAN_RECORDS` below:
#: three mapped, two built into demographic rules, one skipped as a group label whose
#: single member (#4) emitted.
STORE_INCLUSION = [
    _criterion(1, "Type 2 diabetes", domain="Condition"),
    _criterion(2, "Age >= 18", domain="Demographics"),
    _criterion(3, "Renal impairment group", domain="Measurement", is_group_label=True, group_id="g-renal"),
    _criterion(4, "eGFR", domain="Measurement", group_id="g-renal"),
]
STORE_EXCLUSION = [
    _criterion(5, "Pregnancy", domain="Demographics"),
    _criterion(6, "Investigational drug use"),
]

#: The store study's criteria count, which the census `total` is anchored to.
STORE_CRITERIA = len(STORE_INCLUSION) + len(STORE_EXCLUSION)


def _study(*, inclusion: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The minimal two-arm store study the delivery-gate tests use, plus criteria."""
    return {
        "id": 3,
        "name": "Study 3",
        "comparisonMode": "target_minus_treatment",
        "treatmentArms": [{"name": "apixaban"}, {"name": "warfarin"}],
        "eligibility": {
            "inclusionCriteria": json.loads(
                json.dumps(STORE_INCLUSION if inclusion is None else inclusion)
            ),
            "exclusionCriteria": json.loads(json.dumps(STORE_EXCLUSION)),
            "structuredExpression": {
                "ConceptSets": [
                    {
                        "id": 1,
                        "name": "apixaban",
                        "expression": {
                            "items": [
                                {
                                    "concept": {
                                        "CONCEPT_ID": 43013024,
                                        "CONCEPT_NAME": "apixaban",
                                        "DOMAIN_ID": "Drug",
                                        "VOCABULARY_ID": "RxNorm",
                                        "CONCEPT_CLASS_ID": "Ingredient",
                                        "CONCEPT_CODE": "1",
                                    },
                                    "includeDescendants": True,
                                    "isExcluded": False,
                                }
                            ]
                        },
                    }
                ],
                "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
                "InclusionRules": [
                    {"name": "rule one", "expression": {"Type": "ALL", "CriteriaList": []}},
                    {"name": "rule two", "expression": {"Type": "ALL", "CriteriaList": []}},
                ],
            },
        },
    }


#: The one skip in the clean shape: criterion #3 labels the renal group, whose member
#: #4 emitted, so the container row lost nothing.
GROUP_LABEL_SKIP = {
    "criterionId": "3",
    "role": "inclusion",
    "label": "Renal impairment group",
    "domain": "Measurement",
    "isGroupLabel": True,
    "reason": "group-label",
}


def _records(
    *,
    mapped: int,
    demographic_rules: int,
    skipped: list[Any],
    skipped_by_reason: dict[str, int] | None = None,
    unmapped: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The three record keys, balanced by construction against the counters given.

    `total` and `mappable` are DERIVED from the parts, which is what makes these
    fixtures the shape the gate could not previously tell apart from a lossless one:
    every self-consistency check holds by construction, whatever the parts say.
    """
    unmapped = unmapped or []
    by_reason = skipped_by_reason
    if by_reason is None:
        by_reason = {}
        for record in skipped:
            if isinstance(record, dict):
                by_reason[record["reason"]] = by_reason.get(record["reason"], 0) + 1
    return {
        "_unmappedCriteria": unmapped,
        "_skippedCriteria": skipped,
        "_generationCensus": {
            "total": mapped + len(unmapped) + demographic_rules + len(skipped),
            "mappable": mapped + len(unmapped),
            "mapped": mapped,
            "unmapped": len(unmapped),
            "demographicRules": demographic_rules,
            "skipped": len(skipped),
            "skippedByReason": by_reason,
        },
    }


#: Every one of the store's 6 criteria reaches an outcome: #1/#4/#6 mapped, #2/#5 built
#: into demographic rules, #3 skipped as a group label. total == 6 == STORE_CRITERIA.
CLEAN_RECORDS = _records(mapped=3, demographic_rules=2, skipped=[GROUP_LABEL_SKIP])

#: The reproduction, in miniature. Criterion #6 was refused, its `_unmappedCriteria`
#: row struck, `unmapped` zeroed and the difference taken off `total` AND `mappable`.
#: The balance holds (2 + 0 + 2 + 1 == 5), both counter-vs-list cross-checks hold, the
#: breakdown sums, and `mappable == mapped + unmapped` -- and one criterion of the six
#: is now accounted for nowhere.
STRUCK_UNMAPPED_ROW_RECORDS = _records(
    mapped=2, demographic_rules=2, skipped=[GROUP_LABEL_SKIP]
)

#: The clean shape's three mapped criteria (#1, #4, #6), each with the concept set the
#: producer minted for it. Written role-keyed AND bare, exactly as
#: `_build_seeded_target_circe` writes them; only the role-keyed half is read, because
#: inclusion and exclusion ids are independent sequences and a bare key cannot tell
#: `inclusion:6` from `exclusion:6`.
CLEAN_CONCEPT_SET_REFS = {
    "inclusion:1": 2,
    "1": 2,
    "inclusion:4": 3,
    "4": 3,
    "exclusion:6": 4,
    "6": 4,
}

CLEAN_RECORDS_WITH_LINKS = {
    **CLEAN_RECORDS,
    "_criterionConceptSetRefs": json.loads(json.dumps(CLEAN_CONCEPT_SET_REFS)),
}

#: The residual `0d80c94` named and could not close. Criterion #6 was refused; instead
#: of decrementing `total`, the producer struck the `_unmappedCriteria` row and booked
#: the criterion as `mapped`. `total` never moved, so the census here is BYTE-IDENTICAL
#: to `CLEAN_RECORDS` -- the balance, both cross-checks, the mappable identity, the
#: store anchor and the residual set identity all hold, because the criterion simply
#: changed which side of the partition it sits on.
#:
#: The one thing that did not follow it is the concept set: nothing was ever minted for
#: #6, so its entry is missing from the refs map, and that is the only record in the
#: file that distinguishes the two artifacts.
BOOKED_AS_MAPPED_RECORDS = {
    **CLEAN_RECORDS,
    "_criterionConceptSetRefs": {"inclusion:1": 2, "1": 2, "inclusion:4": 3, "4": 3},
}

#: A skip naming a criterion id the store does not carry. The counters stay whole --
#: `census.skipped` counts the row, so `total` still equals the store's 6 -- while the
#: store criterion it was standing in for reaches no outcome at all.
PHANTOM_SKIP = {
    "criterionId": "99",
    "role": "inclusion",
    "label": "A criterion the store does not carry",
    "domain": "Measurement",
    "isGroupLabel": True,
    "reason": "group-label",
}


@pytest.fixture
def gate(monkeypatch, tmp_path, capsys):
    """Run the delivery gate over a directory carrying `records` on both arms."""

    def _run(records: dict[str, Any], study: dict[str, Any] | None = None) -> tuple[int, str]:
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = study if study is not None else _study()
        core = study["eligibility"]["structuredExpression"]
        for role in ("treatment", "comparator"):
            payload = json.loads(json.dumps(core))
            payload.update(json.loads(json.dumps(records)))
            (tmp_path / f"aristotle_{role}.circe.json").write_text(json.dumps(payload))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(store), "--map", "aristotle=3"])
        return rc, capsys.readouterr().out

    return _run


class TestTheCensusIsAnchoredToTheStore:
    def test_should_fail_when_the_census_accounts_for_fewer_criteria_than_the_store_carries(
        self, gate
    ):
        rc, out = gate(STRUCK_UNMAPPED_ROW_RECORDS)

        assert rc == 1
        assert f"census accounts for 5 of the store study's {STORE_CRITERIA} criteria" in out
        assert "1 criterion(s) left the study with no outcome recorded anywhere" in out

    def test_should_name_the_anchor_alone_when_every_self_consistency_check_still_holds(
        self, gate
    ):
        """The point of the fixture: nothing else in the census has anything to say.

        If any of the four self-consistency checks fired on this shape, the anchor
        would not be what caught the loss and this module would be proving nothing.
        """
        _rc, out = gate(STRUCK_UNMAPPED_ROW_RECORDS)

        assert "census does not balance" not in out
        assert "census counter disagrees" not in out
        assert "census is missing a counter" not in out

    def test_should_pass_when_every_store_criterion_reaches_a_recorded_outcome(self, gate):
        rc, out = gate(CLEAN_RECORDS)

        assert rc == 0, out
        assert "PASS" in out
        assert "census accounts for" not in out


class TestASkipRecordThatIsNotARecordIsReported:
    def test_should_fail_when_a_skipped_entry_is_not_a_record(self, gate):
        """The counters stay whole; only the row itself is unreadable.

        `census.skipped` counts it, so the balance holds and `total` still equals the
        store's 6 criteria -- the anchor above cannot see this one, and before this
        check the summary read "1 skipped (all permitted)" over a permit no one could
        read.
        """
        rc, out = gate(
            _records(
                mapped=3,
                demographic_rules=2,
                skipped=["Renal impairment group"],
                skipped_by_reason={"group-label": 1},
            )
        )

        assert rc == 1
        assert "_skippedCriteria carries 1 entry(ies) that are not records" in out
        assert "'Renal impairment group'" in out
        assert "census accounts for" not in out
        assert "census does not balance" not in out


class TestAGroupLabelPermitWithNoGroupIsUnreJudgeable:
    def test_should_fail_when_a_group_label_skip_names_a_store_row_carrying_no_group_id(
        self, gate
    ):
        """No `groupId` means no members, and the permit is exactly a claim about them.

        Neither the stranded-threshold re-derivation nor the all-members-lost check can
        run, so the permit would be granted on the record's own word.
        """
        orphaned = json.loads(json.dumps(STORE_INCLUSION))
        orphaned[2]["groupId"] = None

        rc, out = gate(CLEAN_RECORDS, study=_study(inclusion=orphaned))

        assert rc == 1
        assert "is recorded as group-label but the store row carries no groupId" in out
        assert "nothing shows the group survived in them" in out

    def test_should_pass_a_group_label_skip_whose_store_row_names_its_group(self, gate):
        """The negative control: the same permit, re-derived, over an intact store row."""
        rc, out = gate(CLEAN_RECORDS)

        assert rc == 0, out
        assert "no groupId" not in out


class TestARefusalBookedAsMappedIsSeenByTheConceptSetLink:
    """The residual `0d80c94` recorded and could not close.

    Striking an `_unmappedCriteria` row and booking the criterion as `mapped` moves it
    from one side of the partition to the other and touches no counter that any check
    reads: the balance holds, `mappable == mapped + unmapped` holds, the store anchor
    holds because `total` never moved, and the residual set identity holds because the
    id left the refused bucket and entered the residual, so both sides grew together.

    `mapped` therefore has to be anchored to a record of a PARTICULAR criterion having
    emitted, and `_criterionConceptSetRefs` is the only one the file carries. Measured
    on the 12-file 2026-09-09 batch, this swap passes 8 of 12 files against the
    pre-change gate -- `leader_treatment` among them, reading "37 mapped, 0 unmapped,
    8 skipped (all permitted)" -- and fails all 12 after it.
    """

    def test_should_show_the_swap_leaves_the_census_byte_identical(self):
        """Not a gate run: the premise of every test below it.

        If the two censuses differed anywhere, some existing self-consistency check
        could have caught the swap and the link would be proving nothing.
        """
        assert (
            BOOKED_AS_MAPPED_RECORDS["_generationCensus"]
            == CLEAN_RECORDS_WITH_LINKS["_generationCensus"]
        )
        assert BOOKED_AS_MAPPED_RECORDS["_unmappedCriteria"] == []

    def test_should_fail_when_a_criterion_is_booked_as_mapped_with_no_concept_set(self, gate):
        rc, out = gate(BOOKED_AS_MAPPED_RECORDS)

        assert rc == 1
        assert "census books 3 criteria as mapped but only 2 of them carry a concept-set" in out
        assert "nothing in the file shows a concept set was ever minted for them" in out

    def test_should_name_the_link_alone_when_every_other_check_still_holds(self, gate):
        """The point of the fixture, and the reason it is worth a check of its own."""
        _rc, out = gate(BOOKED_AS_MAPPED_RECORDS)

        assert "census does not balance" not in out
        assert "census counter disagrees" not in out
        assert "census accounts for" not in out
        assert "are named by no refusal record and no skip record" not in out

    def test_should_pass_when_every_mapped_criterion_carries_a_concept_set(self, gate):
        """The negative control the link check lives or dies by: the same census as the
        fixture above, differing only in that the third concept set is there."""
        rc, out = gate(CLEAN_RECORDS_WITH_LINKS)

        assert rc == 0, out
        assert "3 of 3 mapped concept-set linked" in out
        assert "carry a concept-set reference" not in out
        assert "per-criterion references" not in out

    def test_should_fail_when_a_concept_set_reference_names_a_refused_criterion(self, gate):
        """The other direction: the file minted a set for a criterion it also refused.

        The refusal is a PERMITTED one, so the row itself ships and nothing else on the
        page objects -- the contradiction between the two records is the whole finding.
        """
        records = _records(
            mapped=2,
            demographic_rules=2,
            skipped=[GROUP_LABEL_SKIP],
            unmapped=[
                {
                    "criterionId": "6",
                    "role": "exclusion",
                    "label": "Investigational drug use",
                    "domain": "Drug",
                    "reason": "names no clinical entity",
                    "refusalCode": REFUSAL_UNMAPPABLE_PLACEHOLDER,
                }
            ],
        )
        records["_criterionConceptSetRefs"] = json.loads(json.dumps(CLEAN_CONCEPT_SET_REFS))

        rc, out = gate(records)

        assert rc == 1
        assert "while a record says they were refused or skipped" in out
        assert "exclusion #6" in out

    def test_should_say_on_the_row_when_the_file_carries_no_links_at_all(self, gate):
        """73 of the 144 census-carrying artifacts under `output/` have no refs map --
        including all 12 files of the previous day's delivery -- because the draft path
        pops the key. Failing them would fail a correct batch, so the check does not
        run; saying nothing would make a popped key indistinguishable from a clean one,
        so the row says which happened."""
        rc, out = gate(CLEAN_RECORDS)

        assert rc == 0, out
        assert "no concept-set links recorded" in out


class TestTheStoreAnchorIsAnEqualityInBothDirections:
    """`0d80c94` shipped `total < len(index)` and named the asymmetry as deliberate.

    It is defeatable: a census inflated first and then decremented stays above the
    bound, so the bound only ever closed the loss direction against a producer that
    did not also inflate. On the real batch, inflating by the loss and giving half of
    it back passes 8 of 12 files against the lower bound and fails all 12 against the
    equality.
    """

    def test_should_fail_when_the_census_accounts_for_more_outcomes_than_the_store_has(
        self, gate
    ):
        # Inflated by 2 phantom mapped criteria and balanced around them, exactly as a
        # census that was padded before the loss was taken off it would read.
        records = _records(mapped=5, demographic_rules=2, skipped=[GROUP_LABEL_SKIP])

        rc, out = gate(records)

        assert rc == 1
        assert f"census accounts for {STORE_CRITERIA + 2} outcomes over the store study's " in out
        assert "2 more outcome(s) are booked than the study has criteria" in out

    def test_should_not_report_a_shortfall_on_an_over_count(self, gate):
        """The two directions are different defects and say different things."""
        _rc, out = gate(_records(mapped=5, demographic_rules=2, skipped=[GROUP_LABEL_SKIP]))

        assert "left the study with no outcome recorded anywhere" not in out


class TestTheOutcomesAreReconciledAsSetsNotOnlyAsCounts:
    def test_should_fail_when_a_record_names_a_criterion_outside_the_store(self, gate):
        """`total` still equals the store's 6, so the count anchor has nothing to say.

        The record accounts for a criterion the study does not carry, which means one
        it DOES carry is accounted for by nothing -- visible only over the ids.
        """
        records = _records(
            mapped=2, demographic_rules=2, skipped=[GROUP_LABEL_SKIP, PHANTOM_SKIP]
        )

        rc, out = gate(records)

        assert rc == 1
        assert "census books 2 mapped + 2 demographic rule(s) = 4 criteria as having emitted" in out
        assert f"5 of the store study's {STORE_CRITERIA} criteria are named by no refusal" in out
        assert "census accounts for" not in out

    def test_should_fail_when_one_criterion_is_recorded_under_two_outcomes(self, gate):
        """Refused and skipped at once: the balance counts it twice, so a second
        criterion is missing from the file and the totals still add up."""
        records = _records(
            mapped=2,
            demographic_rules=2,
            skipped=[GROUP_LABEL_SKIP],
            unmapped=[
                {
                    "criterionId": "3",
                    "role": "inclusion",
                    "label": "Renal impairment group",
                    "domain": "Measurement",
                    "reason": "names no clinical entity",
                    "refusalCode": REFUSAL_UNMAPPABLE_PLACEHOLDER,
                }
            ],
        )

        rc, out = gate(records)

        assert rc == 1
        assert "1 criterion(s) are recorded BOTH as refused and as skipped" in out
        assert "inclusion #3" in out


class TestTheAnchorReportsItselfOnAPassingRow:
    def test_should_name_the_store_anchor_and_the_link_on_a_passing_row(self, gate):
        """`0d80c94` held both silent to prove the anchor added no failure to the real
        batch. That is proved, and a check whose only output is silence cannot be told
        from a check that never ran."""
        rc, out = gate(CLEAN_RECORDS_WITH_LINKS)

        assert rc == 0, out
        assert f"{STORE_CRITERIA} of {STORE_CRITERIA} store criteria accounted for" in out
        assert "3 of 3 mapped concept-set linked" in out
