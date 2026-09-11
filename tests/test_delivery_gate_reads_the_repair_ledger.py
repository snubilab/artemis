"""The repair ledger reaches the delivered store, and the delivery gate reads it.

`9ec4b3a` added `RepairLedger` so that no criterion can leave the rule tree during a
post-parse repair without a record. It protected the parse. It did not protect the
delivery, and the delivery is the half that ships.

Measured on the run that followed it, `output/site_gap/2026-09-13/store/studies.json`:

    artifacts[N].payload.proposedChanges.eligibility._repairAccounting
        32 records across 6 studies
    studies[*].eligibility._repairAccounting
        ABSENT, on every one of the 10 studies

The mechanism is one step downstream of where it looks. `_merge_eligibility_section`
deep-copies the proposed section wholesale, so the `draft_generation` artifact DOES
carry its ledger onto the study. What removes it is the `eligibility_processing`
artifact applied two to four minutes later: its own `proposedChanges.eligibility`
carries no `_repairAccounting`, and a wholesale replace drops the key. Measured on the
same store, every one of the six studies follows that shape -- art_198 (study 1, 9
records) applied 06:57, art_199 applied 07:00 and the ledger was gone.

`structuredExpression` is already carried across that same boundary for the same
reason, and the ledger is carried the same way: a proposal that carries its own ledger
replaces the old one (a fresh parse earns a fresh account), and a proposal that carries
none leaves the standing one alone.

The gate side is check (k). What it can judge, and what it deliberately cannot:

* A **demotion** record says the criterion is still in the tree -- it was moved under a
  synthesised group, not removed. So a demotion naming a criterion the store does NOT
  carry is a departure that no repair recorded: the record says "moved" and the store
  says "gone", and nothing names where it went. That is the CAROLINA shape, and it is
  what this check fails on. Verified against the real ledgers in the 2026-09-13 store
  before it was written: 16 of 16 demotions across five studies name a criterion the
  store still carries, so the check adds no failure to a correct batch.

* A **departure** record is NOT judged on the same axis, and that is measured rather
  than conceded. `merged-into-band` folds two halves of a band into one survivor, and
  the survivor legitimately keeps a departed half's own name -- 5 such rows across
  studies 8, 9 and 10 of that store (2 of 7 departures on CAROLINA alone). Failing a
  departure whose name is still in the store would fail those five real, correct rows.
  Departures are counted and reported instead.

* An unrecognised `disposition`, and a record that is not a record, both FAIL. This is
  a reconciliation, so drift must leave a record unreadable and block the delivery
  rather than pass unread -- the same direction `ALLOWED_SKIP_REASONS` fails in.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.services.tte_service import TTEService
from src.services.tte_store import TTEStore


# --------------------------------------------------------------------------- Task A1
# The ledger survives the apply chain that really removed it.


LEDGER = [
    {
        "disposition": "departure",
        "action": "dropped-as-restatement",
        "reason": "a restatement of a sibling that is retained",
        "criterion": {
            "name": "HbA1c 6.5 - 8.5% (Naive/Intolerant/Treated)",
            "domain": "Measurement",
            "sourceText": "HbA1c 6.5 - 8.5%, inclusive",
        },
        "survivor": None,
    }
]

POPULATED = {
    "targetCohortName": "Patients with type 2 diabetes",
    "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes"}],
    "exclusionCriteria": [{"id": 2, "description": "Pregnancy"}],
}


@pytest.fixture
def service(tmp_path: Path) -> TTEService:
    store_path = tmp_path / "studies.json"
    store_path.write_text(
        json.dumps(
            {
                "next_id": 1,
                "next_artifact_id": 1,
                "next_job_id": 1,
                "studies": [],
                "artifacts": [],
                "jobs": [],
            }
        )
    )
    return TTEService(TTEStore(str(store_path)))


def _artifact(service: TTEService, study: dict, eligibility: dict, *, kind: str) -> dict:
    return service.store.create_artifact(
        {
            "studyId": study["id"],
            "studyVersion": int(study.get("version") or 1),
            "kind": kind,
            "status": "completed",
            "source": "artemis",
            "capability": "generate_from_nct",
            "summary": kind,
            "payload": {"proposedChanges": {"eligibility": eligibility}, "meta": {}},
        }
    )


class TestTheLedgerReachesTheDeliveredStore:
    def test_should_carry_the_ledger_onto_the_study_when_the_draft_supplies_it(
        self, service: TTEService
    ) -> None:
        """The first apply. This half already worked; it is pinned so it stays working."""
        study = service.store.create_study({"name": "CAROLINA", "eligibility": {}})
        artifact = _artifact(
            service, study, {**POPULATED, "_repairAccounting": LEDGER}, kind="draft_generation"
        )

        service.apply_artifact(artifact["id"], ["eligibility"], int(study["version"]))

        after = service.store.get_study(study["id"])["eligibility"]
        assert after["_repairAccounting"] == LEDGER

    def test_should_keep_the_ledger_when_a_later_apply_carries_none(
        self, service: TTEService
    ) -> None:
        """The measured defect: `eligibility_processing` wiped it minutes later.

        Every one of the six ledger-carrying studies in the 2026-09-13 store lost it
        exactly here.
        """
        study = service.store.create_study({"name": "CAROLINA", "eligibility": {}})
        draft = _artifact(
            service, study, {**POPULATED, "_repairAccounting": LEDGER}, kind="draft_generation"
        )
        service.apply_artifact(draft["id"], ["eligibility"], int(study["version"]))

        study = service.store.get_study(study["id"])
        processing = _artifact(service, study, POPULATED, kind="eligibility_processing")
        service.apply_artifact(processing["id"], ["eligibility"], int(study["version"]))

        after = service.store.get_study(study["id"])["eligibility"]
        assert after.get("_repairAccounting") == LEDGER

    def test_should_let_a_fresh_parse_replace_the_standing_ledger(
        self, service: TTEService
    ) -> None:
        """A carry-forward that cannot be overwritten would pin a stale account."""
        study = service.store.create_study({"name": "CAROLINA", "eligibility": {}})
        first = _artifact(
            service, study, {**POPULATED, "_repairAccounting": LEDGER}, kind="draft_generation"
        )
        service.apply_artifact(first["id"], ["eligibility"], int(study["version"]))

        study = service.store.get_study(study["id"])
        second = _artifact(
            service, study, {**POPULATED, "_repairAccounting": []}, kind="draft_generation"
        )
        service.apply_artifact(second["id"], ["eligibility"], int(study["version"]))

        after = service.store.get_study(study["id"])["eligibility"]
        assert after["_repairAccounting"] == []


# --------------------------------------------------------------------------- Task A2
# The gate reads it. The negative case is CAROLINA's, from the real history.


#: Imported lazily so this module still COLLECTS against a tree where check (k) does
#: not exist yet -- otherwise the import error hides the Task A1 failures above behind
#: a collection error, and "failing before the fix" cannot be shown for either half.
def _gate():
    import scripts.verify_circe_delivery as gate

    return gate


REPAIR_ACCOUNTING_KEY = "_repairAccounting"


def repair_ledger_violations(study):
    return _gate().repair_ledger_violations(study)


#: The six CAROLINA drug-therapy criteria, verbatim from
#: `output/site_gap/2026-09-11/store/studies.json` study 10, where they are inclusion
#: criteria 18 to 23. In `output/site_gap/2026-09-12/store/studies.json` the same study
#: carries none of them and no record of any kind names them -- inclusion fell 52 -> 32,
#: and `rg 'Sulfonylurea Monotherapy'` over the 2026-09-13 store finds them only inside
#: two superseded artifacts. That is the loss this check exists to catch.
CAROLINA_DRUG_CRITERIA = [
    (18, "Sulfonylurea Monotherapy"),
    (19, "Glinide Monotherapy"),
    (20, "Metformin + SU Combination"),
    (21, "Metformin + Glinide Combination"),
    (22, "Alpha-glucosidase inhibitor + SU Combination"),
    (23, "Alpha-glucosidase inhibitor + Glinide Combination"),
]

#: The protocol line all six were decomposed FROM, and which stopped being visited when
#: they were moved under a synthesised group -- the mechanism `repair_accounting.py`
#: names in its own module docstring.
CAROLINA_PROTOCOL_LINE = (
    "Pre-treated with sulphonylurea (SU) monotherapy, glinide monotherapy, "
    "metformin plus SU, or metformin plus glinide"
)


def _store_criterion(criterion_id: int, description: str) -> dict[str, Any]:
    return {
        "id": criterion_id,
        "description": description,
        "domain": "Drug",
        "sourceText": CAROLINA_PROTOCOL_LINE,
        "valueConstraint": None,
    }


def _ledger_record(description: str, *, disposition: str) -> dict[str, Any]:
    record = {
        "disposition": disposition,
        "criterion": {
            "name": description,
            "domain": "Drug",
            "sourceText": CAROLINA_PROTOCOL_LINE,
            "valueConstraint": None,
        },
    }
    if disposition == "demotion":
        record["action"] = "demoted-into-pattern-e-group"
        record["groupName"] = "Prior antidiabetic therapy (OR group)"
        record["reason"] = "moved from a top-level rule into a synthesised group"
    else:
        record["action"] = "dropped-as-uncomposed-decomposition"
        record["reason"] = "its protocol line stopped being decomposed"
        record["survivor"] = None
    return record


def _study(*, inclusion: list[dict[str, Any]], ledger: Any) -> dict[str, Any]:
    eligibility: dict[str, Any] = {
        "inclusionCriteria": inclusion,
        "exclusionCriteria": [],
    }
    if ledger is not None:
        eligibility[REPAIR_ACCOUNTING_KEY] = ledger
    return {"id": 10, "name": "CAROLINA", "eligibility": eligibility}


#: The study as it stood on 2026-09-11, with all six present.
PRESENT = [_store_criterion(i, d) for i, d in CAROLINA_DRUG_CRITERIA]


class TestTheGateReadsTheLedger:
    def test_should_fail_when_a_demotion_names_a_criterion_the_store_lost(self) -> None:
        """The CAROLINA shape: recorded as moved into a group, and in fact gone.

        The six are absent from the store and the only record of them says they are
        still in the tree. Nothing names where they went, so the delivery must not ship.
        """
        study = _study(
            inclusion=[],
            ledger=[_ledger_record(d, disposition="demotion") for _, d in CAROLINA_DRUG_CRITERIA],
        )

        violations, summary = repair_ledger_violations(study)

        assert violations, f"gate passed a six-criterion unaccounted loss: {summary}"
        blob = " ".join(violations)
        for _, description in CAROLINA_DRUG_CRITERIA:
            assert description in blob, f"{description!r} is lost and unnamed: {blob}"

    def test_should_pass_once_a_departure_record_names_them(self) -> None:
        """Same absence, recorded as what it actually is. A recorded loss may ship."""
        study = _study(
            inclusion=[],
            ledger=[_ledger_record(d, disposition="departure") for _, d in CAROLINA_DRUG_CRITERIA],
        )

        violations, summary = repair_ledger_violations(study)

        assert violations == [], f"a recorded departure is accounted for: {violations}"
        assert "6" in summary

    def test_should_pass_when_a_demotion_names_a_criterion_the_store_still_carries(
        self,
    ) -> None:
        """A demotion is not a departure: the criterion is still there, under a group.

        16 of 16 real demotions in the 2026-09-13 store are this shape.
        """
        study = _study(
            inclusion=PRESENT,
            ledger=[_ledger_record(d, disposition="demotion") for _, d in CAROLINA_DRUG_CRITERIA],
        )

        violations, _ = repair_ledger_violations(study)

        assert violations == []

    def test_should_not_fail_a_departure_whose_band_survivor_kept_its_name(self) -> None:
        """Measured: 5 real `merged-into-band` rows across studies 8, 9 and 10.

        The survivor of a band merge legitimately carries a departed half's own name, so
        judging a departure on "absent from the store" would fail correct rows.
        """
        survivor = _store_criterion(18, "Sulfonylurea Monotherapy")
        study = _study(
            inclusion=[survivor],
            ledger=[_ledger_record("Sulfonylurea Monotherapy", disposition="departure")],
        )

        violations, _ = repair_ledger_violations(study)

        assert violations == []

    def test_should_fail_an_unrecognised_disposition(self) -> None:
        """A reconciliation that cannot read a record must block, not pass it unread."""
        study = _study(inclusion=[], ledger=[_ledger_record("x", disposition="relocated")])

        violations, _ = repair_ledger_violations(study)

        assert violations
        assert "relocated" in " ".join(violations)

    def test_should_fail_a_record_that_is_not_a_record(self) -> None:
        study = _study(inclusion=PRESENT, ledger=["dropped six drug criteria"])

        violations, _ = repair_ledger_violations(study)

        assert violations

    def test_should_fail_a_ledger_that_is_not_a_list(self) -> None:
        study = _study(inclusion=PRESENT, ledger={"count": 6})

        violations, _ = repair_ledger_violations(study)

        assert violations

    def test_should_report_rather_than_judge_a_store_that_predates_the_ledger(self) -> None:
        """Every store written before `9ec4b3a` carries no ledger and cannot be judged.

        Silence would be indistinguishable from a check that never ran, so the row says
        so -- the same three-state answer the gate already gives `_droppedCriteria`.
        """
        study = _study(inclusion=PRESENT, ledger=None)

        violations, summary = repair_ledger_violations(study)

        assert violations == []
        assert "NOT RECORDED" in summary

    def test_should_distinguish_an_empty_ledger_from_an_absent_one(self) -> None:
        """Present-and-empty is the positive claim that no repair removed anything."""
        study = _study(inclusion=PRESENT, ledger=[])

        violations, summary = repair_ledger_violations(study)

        assert violations == []
        assert "NOT RECORDED" not in summary
        assert "0" in summary


class TestTheGateSurfacesTheLedgerOnEveryRow:
    def test_should_carry_the_ledger_clause_into_criterion_accounting(self) -> None:
        """Check (k) must reach the printed row, or nothing reads it -- again."""
        from scripts.verify_circe_delivery import criterion_accounting

        study = _study(
            inclusion=[],
            ledger=[_ledger_record(d, disposition="demotion") for _, d in CAROLINA_DRUG_CRITERIA],
        )

        violations, summary = criterion_accounting({}, study)

        assert any("demot" in v.lower() for v in violations), violations
