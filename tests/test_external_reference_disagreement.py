"""Recorded loss D: disagreement cannot be recoded as an external reference."""

import json
from copy import deepcopy
from pathlib import Path

from scripts.verify_circe_delivery import unmapped_refusal_block_reason
from src.services.criterion_annotation import agree, stated_no_entity, validate_annotation
from src.services.tte_service import _refuse_line_naming_no_entity

RECORDED = json.loads(
    (Path(__file__).parent / "fixtures/external_reference_disagreement.json").read_text()
)


def test_should_preserve_disagreement_when_replaying_the_recorded_external_reference():
    row = RECORDED["rows"]["24"]
    first, _ = validate_annotation(RECORDED["first"]["payload"], row["protocolLine"])
    second, _ = validate_annotation(RECORDED["second"]["payload"], row["protocolLine"])
    fields, kept, dropped = agree(first, second, row["protocolLine"])
    assert fields["no_entity"] is None
    assert "no_entity" not in kept
    assert dropped == row["_annotationAgreement"]["dropped"]
    assert stated_no_entity(row) is None
    assert _refuse_line_naming_no_entity(row, row["sourceText"]) is None
    assert unmapped_refusal_block_reason(RECORDED["refusal"], row) is not None


def test_should_reject_external_reference_when_the_span_is_not_in_the_protocol():
    row = deepcopy(RECORDED["rows"]["24"])
    payload = {**RECORDED["first"]["payload"], "no_entity_span": "not in the recorded line"}
    fields, rejected = validate_annotation(payload, row["protocolLine"])
    row["annotation"] = fields
    assert any(entry["field"] == "no_entity" for entry in rejected)
    assert stated_no_entity(row) is None
    refusal = {**RECORDED["refusal"], "refusalCode": "unmappable-placeholder",
               "refusalDetail": payload["no_entity_span"]}
    assert unmapped_refusal_block_reason(refusal, row) is not None


def test_should_reject_external_reference_when_disagreeing_judgments_have_no_evidence():
    row = deepcopy(RECORDED["rows"]["24"])
    payload = {**RECORDED["first"]["payload"], "no_entity_span": None}
    first, rejected = validate_annotation(payload, row["protocolLine"])
    second, _ = validate_annotation(RECORDED["second"]["payload"], row["protocolLine"])
    fields, _, _ = agree(first, second, row["protocolLine"])
    row["annotation"] = fields
    assert any(entry["field"] == "no_entity" for entry in rejected)
    assert stated_no_entity(row) is None
    assert _refuse_line_naming_no_entity(row, row["sourceText"]) is None


def test_should_not_infer_external_reference_when_a_recorded_criterion_names_a_drug():
    row = RECORDED["concrete_control"]
    assert stated_no_entity(row) is None
    assert _refuse_line_naming_no_entity(row, row["sourceText"]) is None
    refusal = {**RECORDED["refusal"], "refusalCode": "no-concept-mapping"}
    assert unmapped_refusal_block_reason(refusal, row) is not None
