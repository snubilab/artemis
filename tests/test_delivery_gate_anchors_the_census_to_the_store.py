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

It is a LOWER bound. `total` short of the store is loss; `total` over the store is a
different defect and is not judged here (see `criterion_accounting` for why).

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
