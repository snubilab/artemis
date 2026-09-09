"""A recorded skip is a permit the gate re-judges, not a word it takes.

`3a3581b` taught the gate to read `_unmappedCriteria` / `_skippedCriteria`, and
`ALLOWED_SKIP_REASONS` decides which recorded skips are loss. Read on its own that
allowlist is an amnesty: the reason string is written by the artifact being checked,
so a producer that stopped recording `group-label-absolute-constraint-stranded` and
wrote plain `group-label` instead would launder four real losses past a gate whose
own test pins that reason OFF the list. Nothing re-derived the claim.

`b6a4f2f` solved the same problem one channel over. `_droppedCriteria` is not
forgiven, it is RECONCILED: `reconcile_dropped_rules` replays each record onto the
store's rule multiset and `dropped_criteria_violations` re-judges the
`(criteria type, attribute)` pair with the producer's own predicate, so a drop is
excused exactly as far as a record explains it. This module holds the same standard
against the two record channels that were still taken on trust.

What is re-derived, per allowed reason:

  * `group-label` — the store row must actually be `isGroupLabel`; the label's own
    threshold must not be one `resolve_group_member_constraint` refuses to hand down
    (that is the stranded case, which is loss); and at least one member of its group
    must have emitted.
  * `demographic-no-rule` — the store row must be demographic-domain and must carry
    no numeric bound. A demographics row that DID carry a number is a lost age bound,
    whatever the record says.
  * the two restated-* reasons — the file must carry a collapse record naming the
    criterion as dropped, whose survivor exists in the store and was not itself lost.

And `_unmappedCriteria` gains no allowlist at all. "No concept mapping found for 'X'"
is byte-for-byte the same shape for a placeholder the mapper was right to refuse
("Table II criteria", a pointer to a table in the PLATO protocol) and for a data-gap
miss ("Contraindication to clopidogrel", whose concepts are standard and simply
absent from the index), so no reason string can be allowlisted without allowlisting
real loss. What IS added is a record-integrity line: 6 rows of the 2026-09-08 batch
(ARISTOTLE 26/27, PLATO 16, x2 arms) carry `reason: ""`, because the producer records
`str(e)` and `str(TimeoutError())` is the empty string. A refusal that does not say
why it refused cannot be re-judged by anything.

Measured on the real 12-file batch before this module was written: 92 `group-label`,
14 `demographic-no-rule`, 4 `restated-demographics-duplicate` and 28
`restated-distinctness-duplicate` rows all reconcile with zero violations, so the
reconciliation adds no failure the batch did not already carry.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

# The producer's own spelling, imported and never retyped (AGENTS.md, wire-format
# constants): a guessed reason string silently reconciles nothing.
from src.services.restated_demographics import COLLAPSE_REASON as RESTATED_DEMOGRAPHICS_REASON
from src.services.restated_distinctness import COLLAPSE_REASON as RESTATED_DISTINCTNESS_REASON
from src.services.value_constraint import STRANDED_GROUP_CONSTRAINT_REASON, is_reference_relative

#: The real CAROLINA exclusion-44 / EMPA-REG exclusion-56 label threshold: "> 240
#: mg/dL" written once on a group whose members are HbA1c, fasting and random plasma
#: glucose. Absolute and unit-bearing, so it is meaningless on HbA1c and the producer
#: refuses to hand it down.
ABSOLUTE_GLUCOSE_BOUND = {
    "op": "gt",
    "value": 240.0,
    "unitText": "mg/dL",
    "referenceBound": "absolute",
    "unitConceptId": None,
}

#: The ARISTOTLE exclusion-9 shape: a ratio against the row's own reference range,
#: which IS analyte-independent and therefore is handed down. A label carrying this
#: strands nothing, so it is an ordinary `group-label`.
REFERENCE_RELATIVE_BOUND = {
    "op": "gt",
    "value": 3.0,
    "unitText": "x ULN",
    "referenceBound": "absolute",
    "unitConceptId": None,
}

#: A demographics bound the producer could have built a rule from.
AGE_BOUND = {
    "op": "between",
    "value": 40.0,
    "unitText": "years",
    "referenceBound": "absolute",
    "unitConceptId": None,
}


def _criterion(
    criterion_id: int,
    label: str,
    *,
    domain: str = "Drug",
    is_group_label: bool = False,
    group_id: str | None = None,
    value_constraint: Any | None = None,
) -> dict[str, Any]:
    """One store criterion row, in the shape `_record_skip` reads it from."""
    return {
        "id": criterion_id,
        "sourceText": label,
        "domain": domain,
        "isGroupLabel": is_group_label,
        "groupId": group_id,
        "valueConstraint": value_constraint,
    }


#: The store criteria the clean shape below reconciles against. Ids are ints here and
#: strings in the records, exactly as the producer writes them.
CLEAN_INCLUSION = [
    _criterion(2, "Age and AF with risk factors", domain="Demographics"),
    _criterion(5, "Stroke risk factor OR group", is_group_label=True, group_id="g-risk"),
    _criterion(6, "Prior stroke", group_id="g-risk"),
]
CLEAN_EXCLUSION = [
    _criterion(
        9,
        "Liver enzyme elevation or bilirubin",
        domain="Measurement",
        is_group_label=True,
        group_id="g-liver",
        value_constraint=REFERENCE_RELATIVE_BOUND,
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


#: What the census `total` is anchored to for the default store. `_records` derives
#: `mapped` from it rather than naming a number, so no fixture here can claim more
#: outcomes than the store it is checked against has criteria.
STORE_CRITERIA = len(CLEAN_INCLUSION) + len(CLEAN_EXCLUSION)


def _store_criteria(study: dict[str, Any]) -> int:
    """How many criteria rows a store study carries, for a test building a custom one."""
    eligibility = study["eligibility"]
    return len(eligibility["inclusionCriteria"]) + len(eligibility["exclusionCriteria"])


def _study(
    *,
    inclusion: list[dict[str, Any]] | None = None,
    exclusion: list[dict[str, Any]] | None = None,
    study_id: int = 3,
) -> dict[str, Any]:
    """The minimal two-arm store study the delivery-gate tests use, plus criteria."""
    return {
        "id": study_id,
        "name": f"Study {study_id}",
        "comparisonMode": "target_minus_treatment",
        "treatmentArms": [{"name": "apixaban"}, {"name": "warfarin"}],
        "eligibility": {
            "inclusionCriteria": json.loads(
                json.dumps(CLEAN_INCLUSION if inclusion is None else inclusion)
            ),
            "exclusionCriteria": json.loads(
                json.dumps(CLEAN_EXCLUSION if exclusion is None else exclusion)
            ),
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


def _unmapped(
    criterion_id: str, label: str, *, role: str = "exclusion", reason: str = "boom"
) -> dict[str, Any]:
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
    *,
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


def _collapse(
    *, role: str = "exclusion", survivor_id: int, dropped_ids: list[int], reason: str
) -> dict[str, Any]:
    """One `_restated*Collapse` record, in the producer's shape."""
    return {
        "role": role,
        "domain": "Demographics",
        "survivorId": survivor_id,
        "droppedIds": list(dropped_ids),
        "survivorRule": "first-in-document-order",
        "reason": reason,
    }


def _records(
    *,
    unmapped: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    mapped: int | None = None,
    demographic_rules: int = 2,
    store_criteria: int = STORE_CRITERIA,
    collapses: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """The three record keys plus any collapse lists, balanced by construction.

    `mapped` is the RESIDUAL by default -- `store_criteria` less the refused, the
    skipped and the demographic rules -- so `total` comes out equal to the store's
    criteria count, which the gate anchors it to in both directions. A test building
    against a custom store passes `store_criteria=_store_criteria(study)`.
    """
    unmapped = unmapped or []
    skipped = skipped or []
    if mapped is None:
        mapped = store_criteria - len(unmapped) - len(skipped) - demographic_rules
    by_reason: dict[str, int] = {}
    for record in skipped:
        by_reason[record["reason"]] = by_reason.get(record["reason"], 0) + 1
    payload: dict[str, Any] = {
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
    payload.update(collapses or {})
    return payload


#: Every allowed reason at once, each reconciled: three group labels (one carrying a
#: reference-relative threshold that IS handed down), one demographics row with no
#: bound, and the two collapses with survivors that emitted.
CLEAN_RECORDS = _records(
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
        _skip(
            "31",
            "GLP-1 receptor agonists (restated)",
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
    collapses={
        "_restatedDistinctnessCollapse": [
            _collapse(survivor_id=30, dropped_ids=[31], reason=RESTATED_DISTINCTNESS_REASON)
        ],
        "_restatedDemographicsCollapse": [
            _collapse(survivor_id=32, dropped_ids=[33], reason=RESTATED_DEMOGRAPHICS_REASON)
        ],
    },
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


class TestAnUnmappedRecordMustSayWhyItRefused:
    """`str(e)` of an exception with no message is `""`. Six rows of the 2026-09-08
    batch carry it, and the log shows why: a 5-second Neo4j timeout on the Stage 1
    search was booked as a mapping refusal. A refusal with no reason cannot be
    re-judged by anything, so it is a record-integrity violation on its own line."""

    def test_should_fail_with_a_named_integrity_line_when_an_unmapped_reason_is_empty(self, gate):
        rc, out = gate(
            _records(
                unmapped=[_unmapped("26", "Aspirin and thienopyridine combination", reason="")]
            )
        )
        assert rc == 1, out
        assert "carries no reason" in out
        assert "_unmappedCriteria[0]" in out

    def test_should_fail_with_a_named_integrity_line_when_an_unmapped_reason_is_only_spaces(
        self, gate
    ):
        rc, out = gate(
            _records(unmapped=[_unmapped("27", "Investigational drug use", reason="   \t ")])
        )
        assert rc == 1, out
        assert "carries no reason" in out

    @pytest.mark.parametrize(
        "reason",
        [
            "No concept mapping found for 'Table II criteria'",
            "No concept mapping found for 'Cancer other than nonmelanoma skin cancer "
            "within 3 years'. Temporal logic detected in criterion.",
        ],
    )
    def test_should_keep_failing_an_unmapped_criterion_whatever_its_reason_says(self, gate, reason):
        """No allowlist. The placeholder the mapper was right to refuse and the
        clinically mappable criterion it stopped short of produce the same string."""
        rc, out = gate(_records(unmapped=[_unmapped("26", "Whatever", reason=reason)]))
        assert rc == 1, out
        assert "unmapped criteria (1)" in out

    def test_should_fail_when_an_unmapped_record_names_a_criterion_the_store_lacks(self, gate):
        """A record the store cannot be asked about is unverifiable, so it fails closed."""
        rc, out = gate(_records(unmapped=[_unmapped("999", "Ghost", reason="No concept mapping")]))
        assert rc == 1, out
        assert "the store study does not carry" in out


class TestAGroupLabelSkipIsReDerivedFromTheStore:
    def test_should_confirm_the_reference_relative_probe_is_reference_relative(self):
        """The fixture below rests on this predicate, so it is called, not assumed."""
        assert is_reference_relative(REFERENCE_RELATIVE_BOUND) is True
        assert is_reference_relative(ABSOLUTE_GLUCOSE_BOUND) is False

    def test_should_fail_when_a_group_label_skip_hides_a_stranded_threshold(self, gate):
        """The laundering case: a producer that stopped recording the stranded reason
        and wrote plain `group-label` would slip four real losses past the allowlist."""
        study = _study(
            exclusion=[
                _criterion(
                    44,
                    "Glucose",
                    domain="Measurement",
                    is_group_label=True,
                    group_id="g-glucose",
                    value_constraint=ABSOLUTE_GLUCOSE_BOUND,
                ),
                _criterion(45, "Hemoglobin A1c", domain="Measurement", group_id="g-glucose"),
            ]
        )
        records = _records(
            skipped=[_skip("44", "Glucose", "group-label")],
            demographic_rules=0,
            store_criteria=_store_criteria(study),
        )
        rc, out = gate(records, study)
        assert rc == 1, out
        assert STRANDED_GROUP_CONSTRAINT_REASON in out

    def test_should_pass_a_group_label_whose_threshold_is_reference_relative(self, gate):
        """"> 3x ULN" IS handed down, so the label strands nothing and is a container."""
        study = _study(
            exclusion=[
                _criterion(
                    9,
                    "Liver enzyme elevation",
                    domain="Measurement",
                    is_group_label=True,
                    group_id="g-liver",
                    value_constraint=REFERENCE_RELATIVE_BOUND,
                ),
                _criterion(
                    10, "Alanine aminotransferase", domain="Measurement", group_id="g-liver"
                ),
            ]
        )
        records = _records(
            skipped=[_skip("9", "Liver enzyme elevation", "group-label")],
            demographic_rules=0,
            store_criteria=_store_criteria(study),
        )
        rc, out = gate(records, study)
        assert rc == 0, out

    def test_should_fail_when_a_group_label_skip_has_no_emitted_member(self, gate):
        """A container row loses nothing because its members emit. When every member
        was itself lost, the whole group left the cohort and nothing carries it."""
        study = _study(
            exclusion=[
                _criterion(11, "Malignant neoplasm", is_group_label=True, group_id="g-cancer"),
                _criterion(12, "Breast cancer", group_id="g-cancer"),
            ]
        )
        records = _records(
            skipped=[_skip("11", "Malignant neoplasm", "group-label")],
            unmapped=[
                _unmapped("12", "Breast cancer", reason="No concept mapping found")
            ],
            demographic_rules=0,
            store_criteria=_store_criteria(study),
        )
        rc, out = gate(records, study)
        assert rc == 1, out
        assert "none of its 1 member" in out

    def test_should_fail_when_a_group_label_skip_names_a_row_that_is_not_a_group_label(self, gate):
        study = _study(exclusion=[_criterion(26, "Aspirin and thienopyridine combination")])
        records = _records(
            skipped=[_skip("26", "Aspirin", "group-label")],
            demographic_rules=0,
            store_criteria=_store_criteria(study),
        )
        rc, out = gate(records, study)
        assert rc == 1, out
        assert "the store row is not a group label" in out


class TestADemographicNoRuleSkipIsReDerivedFromTheStore:
    def test_should_fail_when_a_demographic_no_rule_skip_carried_a_bound(self, gate):
        """The producer had a number and built no rule from it: that is a lost age
        bound, not a row with nothing to carry."""
        study = _study(
            inclusion=[
                _criterion(2, "Age 40 to 80", domain="Demographics", value_constraint=AGE_BOUND)
            ]
        )
        records = _records(
            skipped=[
                _skip(
                    "2",
                    "Age 40 to 80",
                    "demographic-no-rule",
                    role="inclusion",
                    domain="Demographics",
                    is_group_label=False,
                )
            ],
            store_criteria=_store_criteria(study),
        )
        rc, out = gate(records, study)
        assert rc == 1, out
        assert "recorded as demographic-no-rule" in out

    def test_should_pass_when_a_demographic_no_rule_skip_carried_no_bound(self, gate):
        study = _study(
            inclusion=[_criterion(2, "Age and Sex", domain="Demographics", value_constraint=None)]
        )
        records = _records(
            skipped=[
                _skip(
                    "2",
                    "Age and Sex",
                    "demographic-no-rule",
                    role="inclusion",
                    domain="Demographics",
                    is_group_label=False,
                )
            ],
            store_criteria=_store_criteria(study),
        )
        rc, out = gate(records, study)
        assert rc == 0, out

    def test_should_fail_when_a_demographic_no_rule_skip_names_a_non_demographic_row(self, gate):
        study = _study(inclusion=[_criterion(2, "Prior stroke", domain="Condition")])
        records = _records(
            skipped=[
                _skip(
                    "2",
                    "Prior stroke",
                    "demographic-no-rule",
                    role="inclusion",
                    domain="Condition",
                    is_group_label=False,
                )
            ],
            store_criteria=_store_criteria(study),
        )
        rc, out = gate(records, study)
        assert rc == 1, out
        assert "is not a demographic domain" in out


class TestARestatedSkipIsReconciledAgainstItsCollapseRecord:
    def test_should_fail_when_a_restated_skip_has_no_collapse_record(self, gate):
        records = _records(
            skipped=[
                _skip(
                    "31",
                    "GLP-1 receptor agonists (restated)",
                    RESTATED_DISTINCTNESS_REASON,
                    domain="Drug",
                    is_group_label=False,
                )
            ],
            collapses={"_restatedDistinctnessCollapse": []},
        )
        rc, out = gate(records)
        assert rc == 1, out
        assert "no collapse record names it as dropped" in out

    def test_should_fail_when_the_collapse_list_is_absent(self, gate):
        """The collapse is the only evidence the restatement landed on a survivor."""
        records = _records(
            skipped=[
                _skip(
                    "31",
                    "GLP-1 receptor agonists (restated)",
                    RESTATED_DISTINCTNESS_REASON,
                    domain="Drug",
                    is_group_label=False,
                )
            ]
        )
        rc, out = gate(records)
        assert rc == 1, out
        assert "carries no _restatedDistinctnessCollapse" in out

    def test_should_fail_when_the_survivor_was_itself_unmapped(self, gate):
        """Collapsing onto a survivor that never emitted loses both."""
        records = _records(
            skipped=[
                _skip(
                    "31",
                    "GLP-1 receptor agonists (restated)",
                    RESTATED_DISTINCTNESS_REASON,
                    domain="Drug",
                    is_group_label=False,
                )
            ],
            unmapped=[
                _unmapped("30", "GLP-1 receptor agonists", reason="No concept mapping found")
            ],
            collapses={
                "_restatedDistinctnessCollapse": [
                    _collapse(survivor_id=30, dropped_ids=[31], reason=RESTATED_DISTINCTNESS_REASON)
                ]
            },
        )
        rc, out = gate(records)
        assert rc == 1, out
        assert "survivor" in out

    def test_should_fail_when_the_collapse_record_names_a_survivor_the_store_lacks(self, gate):
        records = _records(
            skipped=[
                _skip(
                    "31",
                    "GLP-1 receptor agonists (restated)",
                    RESTATED_DISTINCTNESS_REASON,
                    domain="Drug",
                    is_group_label=False,
                )
            ],
            collapses={
                "_restatedDistinctnessCollapse": [
                    _collapse(
                        survivor_id=999, dropped_ids=[31], reason=RESTATED_DISTINCTNESS_REASON
                    )
                ]
            },
        )
        rc, out = gate(records)
        assert rc == 1, out
        assert "survivor" in out

    def test_should_pass_when_the_collapse_record_names_an_emitted_survivor(self, gate):
        records = _records(
            skipped=[
                _skip(
                    "33",
                    "Pre-menopausal women",
                    RESTATED_DEMOGRAPHICS_REASON,
                    domain="Demographics",
                    is_group_label=False,
                )
            ],
            collapses={
                "_restatedDemographicsCollapse": [
                    _collapse(survivor_id=32, dropped_ids=[33], reason=RESTATED_DEMOGRAPHICS_REASON)
                ]
            },
        )
        rc, out = gate(records)
        assert rc == 0, out


class TestTheReconciliationDoesNotOverFire:
    def test_should_pass_the_reconciled_clean_shape(self, gate):
        """All four allowed reasons at once, each re-derived from the store."""
        rc, out = gate(CLEAN_RECORDS)
        assert rc == 0, out
        assert "all permitted" in out

    def test_should_report_the_summary_prefix_unchanged_on_a_passing_row(self, gate):
        rc, out = gate(CLEAN_RECORDS)
        assert rc == 0, out
        assert "criterion accounting: 6 mapped, 0 unmapped, 7 skipped (all permitted)" in out


class TestTheReconciliationIsNotBlind:
    """b6a4f2f's control: remove the records the gate reconciles against and the
    failures must come back. A check that passes with its evidence deleted is not
    reading it."""

    def test_should_fail_the_clean_shape_when_the_collapse_records_are_stripped(self, gate):
        records = json.loads(json.dumps(CLEAN_RECORDS))
        del records["_restatedDistinctnessCollapse"]
        del records["_restatedDemographicsCollapse"]
        rc, out = gate(records)
        assert rc == 1, out
        assert "carries no _restatedDistinctnessCollapse" in out
        assert "carries no _restatedDemographicsCollapse" in out

    def test_should_fail_the_clean_shape_when_a_stranded_label_is_relabelled_group_label(
        self, gate
    ):
        study = _study(
            exclusion=CLEAN_EXCLUSION
            + [
                _criterion(
                    44,
                    "Glucose",
                    domain="Measurement",
                    is_group_label=True,
                    group_id="g-glucose",
                    value_constraint=ABSOLUTE_GLUCOSE_BOUND,
                ),
                _criterion(45, "Hemoglobin A1c", domain="Measurement", group_id="g-glucose"),
            ]
        )
        records = json.loads(json.dumps(CLEAN_RECORDS))
        records["_skippedCriteria"].append(_skip("44", "Glucose", "group-label"))
        records["_generationCensus"]["skipped"] += 1
        records["_generationCensus"]["total"] += 1
        records["_generationCensus"]["skippedByReason"]["group-label"] += 1
        rc, out = gate(records, study)
        assert rc == 1, out
        assert STRANDED_GROUP_CONSTRAINT_REASON in out
        assert "not reconciled" in out


class TestTheExporterRefusesToShipAnUnreconciledSkip:
    """The exporter shares `criterion_accounting` with the gate, so a laundered skip
    must stop the batch there too: no manifest, non-zero exit."""

    @staticmethod
    def _install_fake_service(monkeypatch, study, records):
        import src.pipeline.webapi_client as webapi_client
        import src.services.tte_service as tte_service
        import src.services.tte_store as tte_store

        expression = json.loads(json.dumps(study["eligibility"]["structuredExpression"]))
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
                        None, f"TTE {study_id} {labels[role]}", expression
                    )
                return {"generationDiagnostics": []}

        monkeypatch.setattr(tte_service, "TTEService", _Service)
        monkeypatch.setattr(tte_store, "TTEStore", _Store)

    def _export(self, monkeypatch, tmp_path, capsys, study, records):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
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

    def test_should_write_no_manifest_when_a_stranded_label_is_hidden_as_a_group_label(
        self, tmp_path, monkeypatch, capsys
    ):
        study = _study(
            exclusion=[
                _criterion(
                    44,
                    "Glucose",
                    domain="Measurement",
                    is_group_label=True,
                    group_id="g-glucose",
                    value_constraint=ABSOLUTE_GLUCOSE_BOUND,
                ),
                _criterion(45, "Hemoglobin A1c", domain="Measurement", group_id="g-glucose"),
            ]
        )
        records = _records(
            skipped=[_skip("44", "Glucose", "group-label")],
            demographic_rules=0,
            store_criteria=_store_criteria(study),
        )
        rc, err, out_dir = self._export(monkeypatch, tmp_path, capsys, study, records)
        assert rc == 1, err
        assert "criterion_loss" in err
        assert STRANDED_GROUP_CONSTRAINT_REASON in err
        assert not (out_dir / "manifest.json").exists()

    def test_should_write_a_manifest_when_every_skip_reconciles(
        self, tmp_path, monkeypatch, capsys
    ):
        rc, err, out_dir = self._export(monkeypatch, tmp_path, capsys, _study(), CLEAN_RECORDS)
        assert rc == 0, err
        assert (out_dir / "manifest.json").exists()
