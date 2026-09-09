"""A refusal is permitted for being IRREDUCIBLE, never for being deliberate.

`11da5f6` gave every deliberate mapper refusal a `refusalCode` from a closed set, and
`criterion_refusal`'s own docstring says why: a consumer "has to decide whether the loss
was DELIBERATE ... or a FAILURE ... the first can be permitted with its reason on file,
the second must never pass". The classification landed and nothing read it — the gate
failed on any `_unmappedCriteria` row at all, so a correctly recorded refusal failed
exactly like a silent breakage.

The axis that decides permission is NOT deliberateness. Every code in `REFUSAL_CODES` is
deliberate, so permitting on that would permit every recorded loss in the batch. The axis
is whether the loss is IRREDUCIBLE given a correct pipeline — and the code that shipped,
`no-concept-mapping`, straddles exactly that line. Verbatim from the 2026-09-08 delivery:

    'Risk factor 1'          (LEADER incl 27)     irreducible — a numbered placeholder
    'Table II criteria'      (PLATO incl 21)      irreducible — a document pointer
    'Preexisting Conditions
     Count'                  (PLATO incl 29)      irreducible — a count, not an entity
    'Contraindication'       (EMPA-REG excl 32)   irreducible — names no substance
    'Contraindication to
     clopidogrel'            (PLATO excl 16)      REDUCIBLE — names a real substance
    'Aspirin and thienopy-
     ridine combination'     (ARISTOTLE excl 26)  REDUCIBLE — real drugs

All six produce, or will produce, one code. One code, two opposite verdicts — so the
split is made at the producer, which can see the seed, and the gate permits exactly the
new code and applies no judgement of its own. A gate-side heuristic over English was the
alternative and it is the failure shape `docs/mistakes.md` records: it would silently
permit row five the day its seed happened to read placeholder-shaped.

The producer half has NOT landed (`tte_service.py` is frozen while a regeneration runs),
so today every row carries `refusalCode: None` or `no-concept-mapping` and every one of
them still blocks. `TestTheGateHalfChangesNoVerdictUntilTheProducerSplits` pins that.

The second module here is the laundering guard's stale premise. `997da1b` gave
`resolve_group_member_constraint` a `member_analyte` keyword, so an absolute group bound
now reaches the members measured in its unit. The gate still asked the pre-997da1b
question — `resolve_group_member_constraint(label_constraint, None)` — whose answer is
"strands everything" for any absolute bound. On CAROLINA 44 and EMPA-REG 56 that gave the
right verdict by accident (HbA1c genuinely is stranded), but a group whose members are
ALL unit-compatible was reported as a loss the build never incurred.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts.verify_circe_delivery import PERMITTED_REFUSAL_CODES
from src.services.value_constraint import (
    STRANDED_GROUP_CONSTRAINT_REASON,
    resolve_group_member_constraint,
)
from src.utils.criterion_refusal import (
    REFUSAL_CODES,
    REFUSAL_INTENT_UNPARSED,
    REFUSAL_NO_CONCEPT_MAPPING,
    REFUSAL_UNMAPPABLE_PLACEHOLDER,
)

#: The real CAROLINA exclusion-44 / EMPA-REG exclusion-56 label threshold: "> 240 mg/dL"
#: written once on a group of glucose analytes. Absolute and unit-bearing.
ABSOLUTE_GLUCOSE_BOUND = {
    "op": "gt",
    "value": 240.0,
    "unitText": "mg/dL",
    "referenceBound": "absolute",
    "unitConceptId": None,
}


def _criterion(
    criterion_id: int,
    source_text: str,
    *,
    domain: str = "Drug",
    is_group_label: bool = False,
    group_id: str | None = None,
    value_constraint: Any | None = None,
) -> dict[str, Any]:
    return {
        "id": criterion_id,
        "sourceText": source_text,
        "domain": domain,
        "isGroupLabel": is_group_label,
        "groupId": group_id,
        "valueConstraint": value_constraint,
    }


DEFAULT_EXCLUSION = [
    _criterion(16, "Contraindication to clopidogrel", domain="Condition"),
    _criterion(21, "Table II criteria", domain="Condition"),
]

#: What the census `total` is anchored to; `_study` carries no inclusion criteria.
#: `_records` derives `mapped` from it rather than naming a number, so a census here
#: cannot claim more outcomes than the store it is checked against has criteria.
STORE_CRITERIA = len(DEFAULT_EXCLUSION)


def _study(*, exclusion: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The minimal two-arm store study the delivery-gate tests build against."""
    return {
        "id": 3,
        "name": "Study 3",
        "comparisonMode": "target_minus_treatment",
        "treatmentArms": [{"name": "apixaban"}, {"name": "warfarin"}],
        "eligibility": {
            "inclusionCriteria": [],
            "exclusionCriteria": json.loads(
                json.dumps(DEFAULT_EXCLUSION if exclusion is None else exclusion)
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
    criterion_id: str,
    label: str,
    *,
    reason: str = "No concept mapping found",
    role: str = "exclusion",
    **code: Any,
) -> dict[str, Any]:
    """One `_unmappedCriteria` row.

    `refusalCode` is passed through `**code` rather than defaulted, so a test that means
    "the key is absent entirely" -- the pre-11da5f6 artifact shape, and the shape every
    row of the 2026-09-08 batch actually has -- can say so without writing `None` and
    accidentally testing the other case.
    """
    record = {
        "criterionId": criterion_id,
        "role": role,
        "label": label,
        "domain": "Condition",
        "reason": reason,
    }
    record.update(code)
    return record


def _records(
    *,
    unmapped: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    mapped: int | None = None,
    store_criteria: int = STORE_CRITERIA,
) -> dict[str, Any]:
    """The three record keys, balanced against a store of `store_criteria` rows.

    `mapped` is the RESIDUAL by default -- `store_criteria` less the refused and the
    skipped -- so `total` comes out equal to the store's criteria count, which the
    gate anchors it to in both directions. A test building against a custom store
    passes its size rather than restating the census by hand.
    """
    unmapped = unmapped or []
    skipped = skipped or []
    if mapped is None:
        mapped = store_criteria - len(unmapped) - len(skipped)
    by_reason: dict[str, int] = {}
    for record in skipped:
        by_reason[record["reason"]] = by_reason.get(record["reason"], 0) + 1
    return {
        "_unmappedCriteria": unmapped,
        "_skippedCriteria": skipped,
        "_generationCensus": {
            "total": mapped + len(unmapped) + len(skipped),
            "mappable": mapped + len(unmapped),
            "mapped": mapped,
            "unmapped": len(unmapped),
            "demographicRules": 0,
            "skipped": len(skipped),
            "skippedByReason": by_reason,
        },
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


class TestTheOnlyPermittedLossIsAnIrreducibleOne:
    def test_should_permit_a_row_refused_as_an_unmappable_placeholder(self, gate):
        """"Table II criteria" is a pointer into the PLATO protocol. No vocabulary entry
        can ever exist for it, so no better mapper recovers it and the delivery is not
        made worse by shipping without it."""
        rc, out = gate(
            _records(
                unmapped=[
                    _unmapped(
                        "21",
                        "Table II criteria",
                        reason="No concept mapping found for 'Table II criteria'",
                        refusalCode=REFUSAL_UNMAPPABLE_PLACEHOLDER,
                    )
                ]
            )
        )
        assert rc == 0, out
        assert "1 unmapped (all permitted)" in out

    def test_should_block_the_same_row_when_it_is_refused_as_no_concept_mapping(self, gate):
        """The code that shipped, and the reason the split had to be made upstream: it
        is what 'Contraindication to clopidogrel' carries too, and that one names a real
        substance a better mapper finds."""
        rc, out = gate(
            _records(
                unmapped=[
                    _unmapped(
                        "16",
                        "Contraindication to clopidogrel",
                        refusalCode=REFUSAL_NO_CONCEPT_MAPPING,
                    )
                ]
            )
        )
        assert rc == 1, out
        assert "unmapped criteria (1)" in out
        assert REFUSAL_NO_CONCEPT_MAPPING in out
        assert "criterion loss a correct pipeline would not incur" in out

    def test_should_block_a_row_refused_as_intent_unparsed(self, gate):
        """The temporal qualifier belongs in the criterion's `window`. The defect is
        fixable upstream at extraction, and permitting the code would hide the four real
        CARMELINA losses that carry it."""
        rc, out = gate(
            _records(
                unmapped=[
                    _unmapped(
                        "16",
                        "Cancer other than nonmelanoma skin cancer within 3 years",
                        reason="Temporal logic detected in criterion",
                        refusalCode=REFUSAL_INTENT_UNPARSED,
                    )
                ]
            )
        )
        assert rc == 1, out
        assert REFUSAL_INTENT_UNPARSED in out

    @pytest.mark.parametrize(
        "code", sorted(REFUSAL_CODES - PERMITTED_REFUSAL_CODES), ids=lambda c: str(c)
    )
    def test_should_block_every_code_the_permit_does_not_name(self, gate, code):
        """Enumerated from the vocabulary rather than listed by hand, so a code added to
        `REFUSAL_CODES` later is blocked here until somebody deliberately permits it."""
        rc, out = gate(_records(unmapped=[_unmapped("16", "Whatever", refusalCode=code)]))
        assert rc == 1, out
        assert "unmapped criteria (1)" in out

    def test_should_keep_the_permit_to_exactly_one_code(self):
        """A permit list that grew would be the whole defect coming back. Pinned so that
        widening it is a deliberate edit to this assertion, not a quiet import change."""
        assert PERMITTED_REFUSAL_CODES == frozenset({REFUSAL_UNMAPPABLE_PLACEHOLDER})
        assert PERMITTED_REFUSAL_CODES <= REFUSAL_CODES


class TestARowThatDidNotDeliberatelyRefuseIsNeverPermitted:
    def test_should_block_a_row_whose_refusal_code_key_is_absent(self, gate):
        """Every row of the 2026-09-08 batch has this shape -- the artifacts predate
        `refusalCode`. Absent means nothing deliberately refused, which is a failure."""
        rc, out = gate(_records(unmapped=[_unmapped("16", "Contraindication to clopidogrel")]))
        assert rc == 1, out
        assert "carries no refusalCode" in out

    def test_should_block_a_row_whose_refusal_code_is_explicitly_none(self, gate):
        """The `str(e) == ""` defect: `describe_mapping_failure` writes `refusalCode:
        None` for any exception that is not a `CriterionRefused`, and the one that
        happened was a 5-second Stage 1 search timeout booked as a mapping verdict."""
        rc, out = gate(
            _records(
                unmapped=[
                    _unmapped("16", "Contraindication to clopidogrel", refusalCode=None)
                ]
            )
        )
        assert rc == 1, out
        assert "carries no refusalCode" in out

    def test_should_block_a_row_whose_refusal_code_is_not_in_the_vocabulary(self, gate):
        """A typo at a raise site is a record-integrity failure, not a clinical verdict,
        so it is reported as one and names where the vocabulary lives."""
        rc, out = gate(
            _records(unmapped=[_unmapped("16", "Whatever", refusalCode="no_concept_mapping")])
        )
        assert rc == 1, out
        assert "not in the vocabulary" in out
        assert "criterion_refusal.py" in out

    def test_should_still_block_a_permitted_code_carrying_no_reason(self, gate):
        """The two integrity lines are independent of the permit. A refusal that does
        not say why it refused cannot be re-judged by anything, whatever its code."""
        rc, out = gate(
            _records(
                unmapped=[
                    _unmapped(
                        "21",
                        "Table II criteria",
                        reason="",
                        refusalCode=REFUSAL_UNMAPPABLE_PLACEHOLDER,
                    )
                ]
            )
        )
        assert rc == 1, out
        assert "carries no reason" in out

    def test_should_still_block_a_permitted_code_the_store_cannot_answer_for(self, gate):
        rc, out = gate(
            _records(
                unmapped=[
                    _unmapped("999", "Ghost", refusalCode=REFUSAL_UNMAPPABLE_PLACEHOLDER)
                ]
            )
        )
        assert rc == 1, out
        assert "the store study does not carry" in out


class TestTheGateHalfChangesNoVerdictUntilTheProducerSplits:
    def test_should_still_block_every_shape_the_current_producer_emits(self, gate):
        """`tte_service.py` raises `no-concept-mapping` for all four irreducible seeds
        and records `refusalCode: None` for everything that broke. Neither is permitted,
        so wiring the permit in cannot pass anything that failed before it."""
        rc, out = gate(
            _records(
                unmapped=[
                    _unmapped("21", "Table II criteria", refusalCode=REFUSAL_NO_CONCEPT_MAPPING),
                    _unmapped("16", "Contraindication to clopidogrel", reason=""),
                ]
            )
        )
        assert rc == 1, out
        assert "unmapped criteria (2)" in out


class TestAnAbsoluteGroupBoundIsJudgedPerMember:
    def test_should_confirm_the_probe_analytes_split_the_way_the_resolver_says(self):
        """The two fixtures below rest on this, so it is called rather than assumed."""
        for analyte in ("Fasting Plasma Glucose", "Random Plasma Glucose"):
            resolution = resolve_group_member_constraint(
                ABSOLUTE_GLUCOSE_BOUND, None, member_analyte=analyte
            )
            assert resolution.refusal_reason is None
        assert (
            resolve_group_member_constraint(
                ABSOLUTE_GLUCOSE_BOUND, None, member_analyte="Hemoglobin A1c"
            ).refusal_reason
            == STRANDED_GROUP_CONSTRAINT_REASON
        )

    def test_should_pass_a_group_whose_members_are_all_unit_compatible(self, gate):
        """The stale premise. Asking the resolver with `member_analyte=None` answers
        "strands everything" for ANY absolute bound, so this group -- where "> 240
        mg/dL" reaches both members and nothing is lost -- was reported as a loss the
        build never incurred."""
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
                _criterion(
                    45, "Fasting Plasma Glucose", domain="Measurement", group_id="g-glucose"
                ),
                _criterion(46, "Random Plasma Glucose", domain="Measurement", group_id="g-glucose"),
            ]
        )
        records = _records(
            skipped=[
                {
                    "criterionId": "44",
                    "role": "exclusion",
                    "label": "Glucose",
                    "domain": "Measurement",
                    "isGroupLabel": True,
                    "reason": "group-label",
                }
            ],
            store_criteria=len(study["eligibility"]["exclusionCriteria"]),
        )
        rc, out = gate(records, study)
        assert rc == 0, out
        assert STRANDED_GROUP_CONSTRAINT_REASON not in out

    def test_should_still_fail_the_real_carolina_group_and_name_the_stranded_member(self, gate):
        """CAROLINA exclusion 44 as it actually is: two glucoses the bound reaches and
        an HbA1c it does not. The verdict is unchanged by the fix -- what changes is
        that the line now says WHICH member the threshold failed to reach."""
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
                _criterion(
                    46, "Fasting Plasma Glucose", domain="Measurement", group_id="g-glucose"
                ),
                _criterion(47, "Random Plasma Glucose", domain="Measurement", group_id="g-glucose"),
            ]
        )
        records = _records(
            skipped=[
                {
                    "criterionId": "44",
                    "role": "exclusion",
                    "label": "Glucose",
                    "domain": "Measurement",
                    "isGroupLabel": True,
                    "reason": "group-label",
                }
            ],
            store_criteria=len(study["eligibility"]["exclusionCriteria"]),
        )
        rc, out = gate(records, study)
        assert rc == 1, out
        assert STRANDED_GROUP_CONSTRAINT_REASON in out
        assert "1 of its 3 member(s) ('Hemoglobin A1c')" in out
