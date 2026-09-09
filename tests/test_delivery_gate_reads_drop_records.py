"""The delivery gate must read the drop records the generator already writes.

`_build_seeded_target_circe` records every criterion that did not become a rule:
`_unmappedCriteria` (the mapper raised), `_skippedCriteria` (a branch dropped it
before the mapper was called) and `_generationCensus` (the balance identity over
both). All three travel out inside the delivered `*.circe.json`.

Nothing read them. `rg -c _unmappedCriteria scripts/verify_circe_delivery.py
scripts/export_seeded_cohorts.py` exited 1 — zero matches in either script — so
the records were written, shipped, and never consulted. Measured on the real
artifact:

    output/anchor_after/aristotle_comparator.circe.json
      _unmappedCriteria: 26 "Aspirin and thienopyridine combination" (exclusion)
                         27 "Investigational drug use"              (exclusion)
      gate verdict:      PASS

Check (b) cannot see it. It compares the file's rule names against the store
`structuredExpression` produced by the SAME generation, so both sides are missing
the same two exclusions and the multiset matches exactly.

Two protocol exclusions absent from a delivered cohort widen it past the protocol,
which is the same failure class the gate already catches elsewhere (a no-op rule, a
domain-mismatched criterion): the definition looks complete and silently admits
patients the trial excluded.

`skipped > 0` is NOT that failure. Most skips are structural and lose nothing:

  * `group-label` — a container row. Its members map and emit as one grouped rule;
    the label itself never carried a concept set.
  * `demographic-no-rule` — a Demographics row with no single usable
    `valueConstraint` ("Age and Sex", "Age >= 50 with prior CVD"). The components
    emit on their own.
  * `restated-demographics-duplicate` / `restated-distinctness-duplicate` — a
    restatement deliberately collapsed onto its retained sibling, which does emit.
    Both reasons are recorded again under `_restatedDemographicsCollapse` /
    `_restatedDistinctnessCollapse`.

So the failure condition is `unmapped > 0`, plus `skipped > 0` for any reason NOT
on that allowlist. The allowlist is a permit list, so an unrecognised reason fails
closed: a new silent `continue` in the producer, or a renamed reason string, stops
the delivery instead of passing through it.

`group-label-absolute-constraint-stranded` is deliberately NOT on it. It records a
group label whose absolute threshold reached no member, so the members emit
unconstrained -- and measured in the delivered file that is an OVER-exclusion, not a
weaker one: the unfiltered absence rule contradicts an HbA1c presence inclusion over
the same window. It occurs in the real 2026-09-08 batch
(`output/site_gap/2026-09-08/deliver_20260908/`, CAROLINA exclusion 44 and EMPA-REG
exclusion 56, "Glucose").

An allowed reason is not taken on trust either. Each one is re-derived from the store
criterion it names and from the file beside it -- see
`tests/test_delivery_gate_reconciles_skip_records.py` -- so the store study here
carries the criteria rows every record below points at.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

# The producer's own spelling of the two collapse reasons and of the stranded-
# constraint reason. Imported, never retyped -- a guessed spelling makes every
# probe against the census return False (AGENTS.md, wire-format constants).
from src.services.restated_demographics import COLLAPSE_REASON as RESTATED_DEMOGRAPHICS_REASON
from src.services.restated_distinctness import COLLAPSE_REASON as RESTATED_DISTINCTNESS_REASON
from src.services.value_constraint import STRANDED_GROUP_CONSTRAINT_REASON


def _criterion(
    criterion_id: int,
    label: str,
    *,
    domain: str = "Drug",
    is_group_label: bool = False,
    group_id: str | None = None,
) -> dict[str, Any]:
    """One store criterion row, in the shape `_record_skip` reads it from.

    Every record in this module names one of these. The gate re-derives an allowed
    skip against the store row rather than trusting the reason string, so a record
    naming a criterion the store does not carry is unverifiable and fails closed --
    which is why these rows exist here at all.
    """
    return {
        "id": criterion_id,
        "sourceText": label,
        "domain": domain,
        "isGroupLabel": is_group_label,
        "groupId": group_id,
        "valueConstraint": None,
    }


#: One row per criterion any record below names, plus a non-label member for each
#: group label (a container row loses nothing only because its members emit) and a
#: survivor for each collapse. None of the members or survivors appears in a record,
#: so all of them count as emitted.
STORE_INCLUSION_CRITERIA = [
    _criterion(2, "Age and AF with risk factors", domain="Demographics"),
    _criterion(5, "Stroke risk factor OR group", is_group_label=True, group_id="g-risk"),
    _criterion(6, "Prior stroke", group_id="g-risk"),
]
STORE_EXCLUSION_CRITERIA = [
    _criterion(
        9,
        "Liver enzyme elevation or bilirubin",
        domain="Measurement",
        is_group_label=True,
        group_id="g-liver",
    ),
    _criterion(10, "Alanine aminotransferase", domain="Measurement", group_id="g-liver"),
    _criterion(11, "Malignant neoplasm", is_group_label=True, group_id="g-cancer"),
    _criterion(12, "Breast cancer", group_id="g-cancer"),
    _criterion(14, "Uncontrolled hypertension", is_group_label=True, group_id="g-htn"),
    _criterion(15, "Systolic blood pressure", domain="Measurement", group_id="g-htn"),
    _criterion(26, "Aspirin and thienopyridine combination"),
    _criterion(27, "Investigational drug use"),
    _criterion(30, "GLP-1 receptor agonists"),
    _criterion(31, "GLP-1 receptor agonists (restated)"),
    _criterion(32, "Pregnancy", domain="Demographics"),
    _criterion(33, "Pre-menopausal women", domain="Demographics"),
]

#: What the census `total` is anchored to. Every `_records` call below derives `mapped`
#: from it rather than naming a number, so a criterion added to either list above stays
#: accounted for without a second edit -- and so no fixture can drift back to claiming
#: more outcomes than this store has criteria, which is what these censuses did until
#: the anchor became an equality.
STORE_CRITERIA = len(STORE_INCLUSION_CRITERIA) + len(STORE_EXCLUSION_CRITERIA)


def _study(study_id: int = 3, arm_names: tuple[str, ...] = ("apixaban", "warfarin")) -> dict:
    """The minimal two-arm store study the other delivery-gate tests use."""
    return {
        "id": study_id,
        "name": "Study " + str(study_id),
        "comparisonMode": "target_minus_treatment",
        "treatmentArms": [{"name": n} for n in arm_names],
        "eligibility": {
            "inclusionCriteria": json.loads(json.dumps(STORE_INCLUSION_CRITERIA)),
            "exclusionCriteria": json.loads(json.dumps(STORE_EXCLUSION_CRITERIA)),
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
            }
        },
    }


def _unmapped(
    criterion_id: str, label: str, role: str = "exclusion", reason: str = "No concept mapping found"
) -> dict[str, Any]:
    """An unmapped record. The reason is non-empty by default: an empty one is a
    record-integrity violation of its own now, checked in
    `tests/test_delivery_gate_reconciles_skip_records.py`, and these cases are about
    the loss the record reports rather than about the record being unreadable."""
    return {
        "criterionId": criterion_id,
        "role": role,
        "label": label,
        "domain": "Drug",
        "reason": reason,
    }


def _skip(
    criterion_id: str,
    label: str,
    reason: str,
    role: str = "exclusion",
    domain: str = "Measurement",
    is_group_label: bool = True,
) -> dict[str, Any]:
    return {
        "criterionId": criterion_id,
        "role": role,
        "label": label,
        "domain": domain,
        "isGroupLabel": is_group_label,
        "reason": reason,
    }


def _records(
    *,
    unmapped: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    mapped: int | None = None,
    demographic_rules: int = 2,
    total: int | None = None,
    store_criteria: int = STORE_CRITERIA,
    collapses: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """The three record keys, balanced by construction unless `total` overrides.

    `mapped` defaults to the RESIDUAL of `store_criteria` -- what is left once the
    refused, the skipped and the demographic rules are taken off -- so `total` comes
    out equal to the store's criteria count, which the gate now anchors it to in both
    directions. Passing it explicitly states an over- or under-count on purpose.

    `collapses` carries the `_restated*Collapse` lists a restated-* skip is now
    reconciled against: the gate re-derives that the collapse actually names the
    criterion as dropped and that its survivor exists in the store and emitted."""
    unmapped = unmapped or []
    skipped = skipped or []
    if mapped is None:
        mapped = store_criteria - len(unmapped) - len(skipped) - demographic_rules
    by_reason: dict[str, int] = {}
    for record in skipped:
        by_reason[record["reason"]] = by_reason.get(record["reason"], 0) + 1
    balanced = mapped + len(unmapped) + demographic_rules + len(skipped)
    payload: dict[str, Any] = {
        "_unmappedCriteria": unmapped,
        "_skippedCriteria": skipped,
        "_generationCensus": {
            "total": balanced if total is None else total,
            "mappable": mapped + len(unmapped),
            "mapped": mapped,
            "unmapped": len(unmapped),
            "demographicRules": demographic_rules,
            "skipped": len(skipped),
            "skippedByReason": by_reason,
        },
    }
    payload.update(collapses or {})
    return payload


#: The real ARISTOTLE records, transcribed from
#: output/anchor_after/aristotle_comparator.circe.json.
ARISTOTLE_RECORDS = _records(
    unmapped=[
        _unmapped("26", "Aspirin and thienopyridine combination"),
        _unmapped("27", "Investigational drug use"),
    ],
    skipped=[
        _skip("5", "Stroke risk factor OR group", "group-label", role="inclusion"),
        _skip("9", "Liver enzyme elevation or bilirubin", "group-label"),
        _skip("11", "Malignant neoplasm", "group-label"),
        _skip("14", "Uncontrolled hypertension", "group-label"),
        _skip(
            "2",
            "Age and AF with risk factors",
            "demographic-no-rule",
            role="inclusion",
            domain="Demographics",
            is_group_label=False,
        ),
    ],
    demographic_rules=2,
)

#: The same shape with the two exclusions mapped -- the CAROLINA case, which is
#: clean despite 32 skips.
CLEAN_RECORDS = _records(
    skipped=ARISTOTLE_RECORDS["_skippedCriteria"]
    + [
        _skip(
            "31",
            "GLP-1 receptor agonists",
            RESTATED_DISTINCTNESS_REASON,
            domain="Drug",
            is_group_label=False,
        ),
        _skip(
            "33",
            "Pre-menopausal women",
            RESTATED_DEMOGRAPHICS_REASON,
            domain="Demographics",
            is_group_label=False,
        ),
    ],
    demographic_rules=2,
    collapses={
        "_restatedDistinctnessCollapse": [
            {
                "role": "exclusion",
                "domain": "Drug",
                "survivorId": 30,
                "droppedIds": [31],
                "survivorRule": "first-in-document-order",
                "reason": RESTATED_DISTINCTNESS_REASON,
            }
        ],
        "_restatedDemographicsCollapse": [
            {
                "role": "exclusion",
                "domain": "Demographics",
                "survivorId": 32,
                "droppedIds": [33],
                "survivorRule": "first-in-document-order",
                "reason": RESTATED_DEMOGRAPHICS_REASON,
            }
        ],
    },
)


def _write_arms(directory, study: dict, records: dict[str, Any] | None) -> None:
    """One file per arm, each the store expression plus the given record keys."""
    core = study["eligibility"]["structuredExpression"]
    for role in ("treatment", "comparator"):
        payload = json.loads(json.dumps(core))
        if records is not None:
            payload.update(json.loads(json.dumps(records)))
        (directory / f"aristotle_{role}.circe.json").write_text(json.dumps(payload))


@pytest.fixture
def gate(monkeypatch, tmp_path, capsys):
    """Run the delivery gate over a directory carrying `records` on both arms."""

    def _run(records: dict[str, Any] | None, study: dict | None = None) -> tuple[int, str]:
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = study or _study()
        _write_arms(tmp_path, study, records)
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(store), "--map", "aristotle=3"])
        return rc, capsys.readouterr().out

    return _run


class TestTheAllowlistNamesTheProducersOwnReasons:
    """The permit list is spelled with the producer's constants, not with guesses."""

    def test_should_allowlist_both_collapse_reasons_when_read_from_the_producer(self):
        from scripts.verify_circe_delivery import ALLOWED_SKIP_REASONS

        assert RESTATED_DEMOGRAPHICS_REASON in ALLOWED_SKIP_REASONS
        assert RESTATED_DISTINCTNESS_REASON in ALLOWED_SKIP_REASONS

    def test_should_not_allowlist_the_stranded_group_constraint_when_it_loses_a_threshold(self):
        """A label threshold that reached no member is loss, not a container row.

        Not merely a weaker exclusion: measured in the real
        `carolina_treatment.circe.json`, the three stranded members emit as UNFILTERED
        absence criteria (Occurrence Type 0 / Count 0, window [-180, 0]) -- "no glucose
        measurement of ANY value in the last 180 days" -- while inclusion rule 5
        REQUIRES an HbA1c in the same window, and the two codesets overlap on 4 of the 6
        presence concepts. The emitted shape over-excludes. `empa-reg_treatment` rules
        3/5 against rule 25 are the same. Check (f) cannot see it: it tests absence
        against the ENTRY set only."""
        from scripts.verify_circe_delivery import ALLOWED_SKIP_REASONS

        assert STRANDED_GROUP_CONSTRAINT_REASON not in ALLOWED_SKIP_REASONS


class TestTheGateFailsOnRecordedCriterionLoss:
    def test_should_fail_when_a_delivered_file_records_an_unmapped_criterion(self, gate):
        """The measured ARISTOTLE shape: two protocol exclusions, gate said PASS."""
        rc, out = gate(ARISTOTLE_RECORDS)
        assert rc == 1, out
        assert "unmapped criteria (2)" in out
        assert "Aspirin and thienopyridine combination" in out
        assert "Investigational drug use" in out

    def test_should_fail_when_a_criterion_is_skipped_for_a_reason_off_the_allowlist(self, gate):
        """The real 2026-09-08 shape: CAROLINA/EMPA-REG "Glucose"."""
        records = _records(
            skipped=[_skip("41", "Glucose", STRANDED_GROUP_CONSTRAINT_REASON)],
        )
        rc, out = gate(records)
        assert rc == 1, out
        assert STRANDED_GROUP_CONSTRAINT_REASON in out
        assert "Glucose" in out

    def test_should_fail_when_an_unrecognised_skip_reason_appears(self, gate):
        """A permit list fails closed: a new silent branch stops the delivery."""
        records = _records(skipped=[_skip("44", "Something new", "some-new-branch")])
        rc, out = gate(records)
        assert rc == 1, out
        assert "some-new-branch" in out


class TestTheGateChecksTheCensusBalancesOnTheDeliveredFile:
    """`tests/test_generation_census_accounts_for_every_criterion.py` asserts the
    identity against the generator. Nothing re-checked it at the delivery boundary,
    where the file has been pruned, copied and possibly hand-edited since."""

    def test_should_fail_when_the_census_total_does_not_equal_its_parts(self, gate):
        # `total` alone is overridden, so the parts still describe this store and the
        # only thing wrong with the census is the identity this test is about. It is
        # also, unavoidably, an over-count against the store -- 41 outcomes over 15
        # criteria -- and the store anchor says so on its own line beside this one.
        rc, out = gate(_records(total=41))
        assert rc == 1, out
        assert "census does not balance" in out

    def test_should_fail_when_a_counter_disagrees_with_its_own_record_list(self, gate):
        """A stripped list with the counter left behind reads as clean otherwise."""
        records = _records(unmapped=[_unmapped("26", "Aspirin and thienopyridine")])
        records["_unmappedCriteria"] = []
        rc, out = gate(records)
        assert rc == 1, out
        assert "census counter disagrees" in out

    def test_should_fail_when_only_part_of_the_record_set_is_present(self, gate):
        """The three keys are emitted together; a partial set means one was removed."""
        records = _records(skipped=[_skip("5", "Stroke risk factor OR group", "group-label")])
        del records["_skippedCriteria"]
        rc, out = gate(records)
        assert rc == 1, out
        assert "_skippedCriteria" in out


class TestTheGateDoesNotOverFire:
    def test_should_pass_when_every_criterion_maps_or_is_skipped_for_a_permitted_reason(
        self, gate
    ):
        """32 skips and still clean -- the measured CAROLINA batch."""
        rc, out = gate(CLEAN_RECORDS)
        assert rc == 0, out
        assert "unmapped criteria" not in out

    def test_should_report_the_accounting_summary_on_a_passing_row(self, gate):
        """A silent pass cannot be told from an unchecked one, so the row says it."""
        rc, out = gate(CLEAN_RECORDS)
        assert rc == 0, out
        assert "criterion accounting: 6 mapped, 0 unmapped, 7 skipped" in out

    def test_should_report_the_store_anchor_on_a_passing_row(self, gate):
        """The anchor is the one check here with a referent outside the file.

        It said nothing at all on a passing row until now, which is indistinguishable
        from an anchor that never ran -- the same reason the accounting summary above
        is printed rather than kept for failures.
        """
        rc, out = gate(CLEAN_RECORDS)
        assert rc == 0, out
        assert f"{STORE_CRITERIA} of {STORE_CRITERIA} store criteria accounted for" in out

    def test_should_say_accounting_was_not_recorded_when_the_file_predates_it(self, gate):
        """Artifacts built before `_generationCensus` existed carry none of the three
        keys. They cannot be checked, and the row says so rather than reading clean."""
        rc, out = gate(None)
        assert rc == 0, out
        assert "criterion accounting: NOT RECORDED" in out


class TestTheExporterRefusesToShipRecordedCriterionLoss:
    """The exporter writes no manifest on a lint violation. Recorded criterion loss
    is the same class: the batch is not what it claims to be."""

    @staticmethod
    def _install_fake_service(monkeypatch, study, records):
        import src.pipeline.webapi_client as webapi_client
        import src.services.tte_service as tte_service
        import src.services.tte_store as tte_store

        expression = json.loads(json.dumps(study["eligibility"]["structuredExpression"]))
        if records is not None:
            expression.update(json.loads(json.dumps(records)))

        class _Store:
            def __init__(self, *a, **k):
                pass

            def get_study(self, study_id):
                return study

        class _Service:
            def __init__(self, store):
                self.store = store

            def _build_seeded_cohort_artifact_payload(self, study_id, study_arg):
                labels = {"treatment": "Treatment - drug", "comparator": "Comparator - No drug"}
                for role in ("treatment", "comparator"):
                    webapi_client.WebAPIClient.create_cohort_definition(
                        None, "TTE " + str(study_id) + " " + labels[role], expression
                    )
                return {"generationDiagnostics": []}

        monkeypatch.setattr(tte_service, "TTEService", _Service)
        monkeypatch.setattr(tte_store, "TTEStore", _Store)

    def _export(self, monkeypatch, tmp_path, capsys, records):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _study()
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))
        self._install_fake_service(monkeypatch, study, records)
        out_dir = tmp_path / "out"

        from scripts.export_seeded_cohorts import main

        rc = main([
            "--store", str(store), "--out", str(out_dir),
            "--study-id", "3", "--slug-map", "3=aristotle",
        ])
        return rc, capsys.readouterr().err, out_dir

    def test_should_write_no_manifest_when_a_criterion_is_recorded_unmapped(
        self, tmp_path, monkeypatch, capsys
    ):
        rc, err, out_dir = self._export(monkeypatch, tmp_path, capsys, ARISTOTLE_RECORDS)
        assert rc == 1, err
        assert "criterion_loss" in err
        assert "Investigational drug use" in err
        assert not (out_dir / "manifest.json").exists()

    def test_should_write_a_manifest_when_every_criterion_is_accounted_for(
        self, tmp_path, monkeypatch, capsys
    ):
        rc, err, out_dir = self._export(monkeypatch, tmp_path, capsys, CLEAN_RECORDS)
        assert rc == 0, err
        assert (out_dir / "manifest.json").exists()
