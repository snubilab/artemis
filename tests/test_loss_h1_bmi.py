"""Recorded EMPA-REG BMI has no stated unit; do not guess one from its name."""

import json
from copy import deepcopy
from pathlib import Path

from src.services.criterion_annotation import applied_value_constraint
from src.utils.circe_lint import (
    convert_value_range_inclusions,
    value_range_inclusion_criteria,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures/loss_h1_bmi.json").read_text())
PROPERTIES = {3038553: "Ratio", 36304833: "Ratio", 40762636: "Percentile"}


def test_should_preserve_the_unresolved_bmi_finding_when_no_unit_is_stated():
    cohort = deepcopy(FIXTURE["cohort"])
    row = FIXTURE["row"]
    assert row["protocolLine"] == "5. Body Mass index <= 45 at Visit 1"
    assert applied_value_constraint(row)["unitText"] == ""
    records = convert_value_range_inclusions(cohort, PROPERTIES)
    assert records[0]["status"] == "declined"
    assert "states no unit" in records[0]["reason"]
    assert cohort["ConceptSets"] == FIXTURE["cohort"]["ConceptSets"]
    assert len(value_range_inclusion_criteria(cohort)) == 1


def test_should_exclude_high_values_when_the_real_bmi_row_has_a_stated_ucum_unit():
    # Conditional replay only: this unit is NOT in the recorded EMPA-REG source.
    cohort = deepcopy(FIXTURE["cohort"])
    entry = cohort["InclusionRules"][0]["expression"]["CriteriaList"][0]
    entry["Criteria"]["Measurement"]["Unit"] = [
        {"CONCEPT_ID": 9531, "CONCEPT_CODE": "kg/m2"}
    ]
    records = convert_value_range_inclusions(cohort, PROPERTIES)
    assert records[0]["status"] == "converted"
    emitted = cohort["InclusionRules"][0]["expression"]["CriteriaList"][0]
    assert emitted["Criteria"]["Measurement"]["ValueAsNumber"] == {"Value": 45.0, "Op": "gt"}
    assert emitted["Occurrence"] == {"Type": 0, "Count": 0}
    assert emitted["StartWindow"] == entry["StartWindow"]
    items = cohort["ConceptSets"][0]["expression"]["items"]
    assert [i["concept"]["CONCEPT_ID"] for i in items] == [3038553, 36304833]
    assert value_range_inclusion_criteria(cohort) == []
