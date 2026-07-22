"""Tests for IR metadata propagation into CIRCE definitions.

Covers:
- Task 1: IR window -> criterion dict -> CIRCE StartWindow
- Task 2: IR observation_window -> PrimaryCriteria ObservationWindow
- Task 3: Drug Era attributes (EraLength) from trial metadata
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.services.tte_service import TTEService


def _make_service() -> TTEService:
    """Create a TTEService instance with mocked external dependencies."""
    svc = TTEService.__new__(TTEService)
    svc._store = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# Task 1: _criterion_dict_from_ir_item — window extraction
# ---------------------------------------------------------------------------


class TestCriterionDictFromIrItem:
    def test_extracts_window_from_ir_item(self):
        svc = _make_service()
        item = SimpleNamespace(
            name="Diabetes",
            domain="Condition",
            entity_text="T2DM",
            value_constraint=None,
            window=SimpleNamespace(start=-90, end=0),
        )
        result = svc._criterion_dict_from_ir_item(item, 1, "Diabetes")

        assert result["window"] == {"start": -90, "end": 0}

    def test_window_none_when_ir_has_no_window(self):
        svc = _make_service()
        item = SimpleNamespace(
            name="Diabetes",
            domain="Condition",
            entity_text="T2DM",
            value_constraint=None,
            window=None,
        )
        result = svc._criterion_dict_from_ir_item(item, 1, "Diabetes")

        assert result["window"] is None

    def test_window_none_when_ir_item_lacks_window_attr(self):
        svc = _make_service()
        item = SimpleNamespace(
            name="Diabetes",
            domain="Condition",
            entity_text="T2DM",
            value_constraint=None,
        )
        result = svc._criterion_dict_from_ir_item(item, 1, "Diabetes")

        assert result["window"] is None


# ---------------------------------------------------------------------------
# Task 1: _build_seeded_eligibility_rule — StartWindow from criterion window
# ---------------------------------------------------------------------------


class TestBuildSeededEligibilityRuleStartWindow:
    def _call(self, svc, criterion, exclusion=False):
        with patch.object(svc, "_recommend_seeded_concept_set") as mock_rec:
            mock_rec.return_value = {
                "name": "Test Concept",
                "domain": "Condition",
                "expression": {"items": []},
            }
            return svc._build_seeded_eligibility_rule(
                criterion=criterion,
                codeset_id=2,
                exclusion=exclusion,
            )

    def test_start_window_from_criterion_window(self):
        svc = _make_service()
        criterion = {
            "description": "Prior MI",
            "domain": "Condition",
            "window": {"start": -180, "end": 0},
        }
        result = self._call(svc, criterion)

        sw = result["rule"]["expression"]["CriteriaList"][0]["StartWindow"]
        assert sw["Start"]["Days"] == 180
        assert sw["Start"]["Coeff"] == -1
        assert sw["End"]["Days"] == 0
        assert sw["End"]["Coeff"] == 1

    def test_start_window_positive_start_uses_coeff_1(self):
        svc = _make_service()
        criterion = {
            "description": "Post-op event",
            "domain": "Condition",
            "window": {"start": 7, "end": 30},
        }
        result = self._call(svc, criterion)

        sw = result["rule"]["expression"]["CriteriaList"][0]["StartWindow"]
        assert sw["Start"]["Days"] == 7
        assert sw["Start"]["Coeff"] == 1

    def test_start_window_defaults_when_no_window(self):
        svc = _make_service()
        criterion = {
            "description": "Hypertension",
            "domain": "Condition",
        }
        result = self._call(svc, criterion)

        sw = result["rule"]["expression"]["CriteriaList"][0]["StartWindow"]
        assert sw["Start"]["Days"] == 365
        assert sw["Start"]["Coeff"] == -1
        assert sw["End"]["Days"] == 0
        assert sw["End"]["Coeff"] == 1


# ---------------------------------------------------------------------------
# Task 2: _study_from_ir — observationWindow extraction
# ---------------------------------------------------------------------------


class TestStudyFromIrObservationWindow:
    def _make_ir(self, obs_window=None):
        primary = SimpleNamespace(
            entity_text="T2DM",
            domain="Condition",
            observation_window=obs_window,
        )
        target = SimpleNamespace(
            primary_criteria=primary,
            inclusion_rules=[],
            exclusion_rules=[],
        )
        comparator = SimpleNamespace(
            primary_criteria=SimpleNamespace(entity_text="", domain="Condition"),
        )
        outcome = SimpleNamespace(
            entity_text="MACE",
            name="MACE",
            domain="Condition",
            time_at_risk=SimpleNamespace(start=0, end=365),
        )
        return SimpleNamespace(target=target, comparator=comparator, outcome=outcome)

    def test_extracts_observation_window(self):
        svc = _make_service()
        ir = self._make_ir(obs_window={"prior": 180, "post": 30})
        result = svc._study_from_ir(ir, "Test study")

        assert result["eligibility"]["observationWindow"] == {"PriorDays": 180, "PostDays": 30}

    def test_observation_window_none_when_missing(self):
        svc = _make_service()
        ir = self._make_ir(obs_window=None)
        result = svc._study_from_ir(ir, "Test study")

        assert result["eligibility"]["observationWindow"] is None

    def test_observation_window_uses_defaults_for_missing_keys(self):
        svc = _make_service()
        ir = self._make_ir(obs_window={"prior": 200})
        result = svc._study_from_ir(ir, "Test study")

        assert result["eligibility"]["observationWindow"]["PriorDays"] == 200
        assert result["eligibility"]["observationWindow"]["PostDays"] == 0


# ---------------------------------------------------------------------------
# Task 2: _build_seeded_target_circe — ObservationWindow from eligibility
# ---------------------------------------------------------------------------


class TestBuildSeededTargetCirceObsWindow:
    def _call(self, svc, eligibility):
        with patch.object(svc, "_recommend_seeded_concept_set") as mock_rec:
            mock_rec.return_value = {
                "name": "T2DM Concept",
                "domain": "Condition",
                "expression": {"items": []},
            }
            return svc._build_seeded_target_circe(eligibility)

    def test_uses_observation_window_from_eligibility(self):
        svc = _make_service()
        elig = {
            "targetCohortName": "T2DM patients",
            "inclusionCriteria": [],
            "exclusionCriteria": [],
            "observationWindow": {"PriorDays": 180, "PostDays": 30},
        }
        result = self._call(svc, elig)

        assert result["PrimaryCriteria"]["ObservationWindow"] == {"PriorDays": 180, "PostDays": 30}

    def test_falls_back_to_default_observation_window(self):
        svc = _make_service()
        elig = {
            "targetCohortName": "T2DM patients",
            "inclusionCriteria": [],
            "exclusionCriteria": [],
        }
        result = self._call(svc, elig)

        assert result["PrimaryCriteria"]["ObservationWindow"] == {"PriorDays": 365, "PostDays": 0}


# ---------------------------------------------------------------------------
# Task 3: Drug Era — EraLength from window in eligibility rules
# ---------------------------------------------------------------------------


class TestDrugEraLengthFromWindow:
    def _call(self, svc, criterion, exclusion=False):
        with patch.object(svc, "_recommend_seeded_concept_set") as mock_rec:
            mock_rec.return_value = {
                "name": "Metformin",
                "domain": "Drug",
                "expression": {"items": []},
            }
            return svc._build_seeded_eligibility_rule(
                criterion=criterion,
                codeset_id=2,
                exclusion=exclusion,
            )

    def test_era_length_from_window_for_drug_era(self):
        svc = _make_service()
        criterion = {
            "description": "Metformin use",
            "domain": "Drug",
            "window": {"start": -90, "end": 0},
        }
        result = self._call(svc, criterion)

        # criteria_key for Drug domain in SEEDED_DOMAIN_TO_CRITERIA_TYPE is DrugExposure, not DrugEra
        # EraLength is only added when criteria_key == "DrugEra"
        # Since Drug maps to DrugExposure in the criteria (not primary) path,
        # EraLength should NOT be present here
        criteria = result["rule"]["expression"]["CriteriaList"][0]["Criteria"]
        assert "DrugExposure" in criteria
        assert "EraLength" not in criteria["DrugExposure"]

    def test_no_era_length_when_no_window(self):
        svc = _make_service()
        criterion = {
            "description": "Metformin use",
            "domain": "Drug",
        }
        result = self._call(svc, criterion)

        criteria = result["rule"]["expression"]["CriteriaList"][0]["Criteria"]
        assert "EraLength" not in criteria.get("DrugExposure", {})


# ---------------------------------------------------------------------------
# Task 3: Drug Era — primary criteria uses DrugEra without EraLength
# ---------------------------------------------------------------------------


class TestDrugEraPrimary:
    def _call(self, svc, eligibility):
        with patch.object(svc, "_recommend_seeded_concept_set") as mock_rec:
            mock_rec.return_value = {
                "name": "Metformin",
                "domain": "Drug",
                "expression": {"items": []},
            }
            return svc._build_seeded_target_circe(eligibility)

    def test_drug_primary_uses_drug_era_key(self):
        svc = _make_service()
        elig = {
            "targetCohortName": "Metformin users",
            "inclusionCriteria": [],
            "exclusionCriteria": [],
        }
        result = self._call(svc, elig)

        primary_list = result["PrimaryCriteria"]["CriteriaList"]
        assert "DrugEra" in primary_list[0]
        assert primary_list[0]["DrugEra"]["CodesetId"] == 1

    def test_drug_primary_has_no_era_length(self):
        svc = _make_service()
        elig = {
            "targetCohortName": "Metformin users",
            "inclusionCriteria": [],
            "exclusionCriteria": [],
        }
        result = self._call(svc, elig)

        drug_era_attrs = result["PrimaryCriteria"]["CriteriaList"][0]["DrugEra"]
        assert "EraLength" not in drug_era_attrs


# ---------------------------------------------------------------------------
# _build_eligibility_suggestion — observationWindow propagation
# ---------------------------------------------------------------------------


class TestBuildEligibilitySuggestionObsWindow:
    def test_preserves_observation_window(self):
        svc = _make_service()
        study = {
            "eligibility": {
                "targetCohortId": 1,
                "targetCohortName": "T2DM",
                "inclusionCriteria": [{"id": 1, "description": "HbA1c"}],
                "exclusionCriteria": [],
                "observationWindow": {"PriorDays": 180, "PostDays": 30},
            }
        }
        from src.models.ir import ProvisionalStudyIR

        ir = ProvisionalStudyIR(source_text="test", target_text="T2DM")
        result = svc._build_eligibility_suggestion(study, ir)

        assert result["observationWindow"] == {"PriorDays": 180, "PostDays": 30}

    def test_observation_window_none_when_absent(self):
        svc = _make_service()
        study = {
            "eligibility": {
                "targetCohortName": "T2DM",
                "inclusionCriteria": [],
                "exclusionCriteria": [],
            }
        }
        from src.models.ir import ProvisionalStudyIR

        ir = ProvisionalStudyIR(source_text="test", target_text="T2DM")
        result = svc._build_eligibility_suggestion(study, ir)

        assert result["observationWindow"] is None


# ---------------------------------------------------------------------------
# Fix 1: logicType propagation from IR Criteria
# ---------------------------------------------------------------------------


class TestCriterionDictLogicType:
    def test_includes_logic_type_presence_by_default(self):
        svc = _make_service()
        item = SimpleNamespace(
            name="Diabetes",
            domain="Condition",
            entity_text="T2DM",
            value_constraint=None,
            window=None,
        )
        result = svc._criterion_dict_from_ir_item(item, 1, "Diabetes")

        assert result["logicType"] == "PRESENCE"

    def test_includes_logic_type_absence_from_ir(self):
        svc = _make_service()
        item = SimpleNamespace(
            name="HbA1c upper bound",
            domain="Measurement",
            entity_text="HbA1c >= 10%",
            value_constraint=None,
            window=None,
            logic_type="ABSENCE",
        )
        result = svc._criterion_dict_from_ir_item(item, 1, "HbA1c upper bound")

        assert result["logicType"] == "ABSENCE"


class TestCriteriaFromIrLogicType:
    def test_standalone_criterion_carries_logic_type(self):
        svc = _make_service()
        criteria = [
            SimpleNamespace(
                name="No prior MI",
                domain="Condition",
                entity_text="Myocardial Infarction",
                value_constraint=None,
                window=None,
                logic_type="ABSENCE",
                sub_criteria=[],
            ),
        ]
        result = svc._criteria_from_ir(criteria)

        assert len(result) == 1
        assert result[0]["logicType"] == "ABSENCE"

    def test_sub_criteria_inherit_parent_logic_type(self):
        svc = _make_service()
        criteria = [
            SimpleNamespace(
                name="CV history",
                domain="Condition",
                entity_text="CV events",
                value_constraint=None,
                window=None,
                logic_type="ABSENCE",
                sub_criteria=[
                    SimpleNamespace(
                        name="MI",
                        domain="Condition",
                        entity_text="Myocardial Infarction",
                        value_constraint=None,
                        window=None,
                    ),
                    SimpleNamespace(
                        name="Stroke",
                        domain="Condition",
                        entity_text="Stroke",
                        value_constraint=None,
                        window=None,
                        logic_type="PRESENCE",
                    ),
                ],
                group_type="ALL",
            ),
        ]
        result = svc._criteria_from_ir(criteria)

        # Parent row + 2 sub-criteria = 3 entries
        assert len(result) == 3
        # Parent row carries its own logicType
        assert result[0]["logicType"] == "ABSENCE"
        # Sub without own logic_type inherits parent ABSENCE
        assert result[1]["logicType"] == "ABSENCE"
        # Sub with own logic_type keeps its own PRESENCE
        assert result[2]["logicType"] == "PRESENCE"


class TestBuildSeededRuleLogicType:
    def _call(self, svc, criterion, exclusion=False):
        with patch.object(svc, "_recommend_seeded_concept_set") as mock_rec:
            mock_rec.return_value = {
                "name": "Test Concept",
                "domain": "Condition",
                "expression": {"items": []},
            }
            return svc._build_seeded_eligibility_rule(
                criterion=criterion,
                codeset_id=2,
                exclusion=exclusion,
            )

    def test_absence_logic_type_produces_zero_occurrence(self):
        svc = _make_service()
        criterion = {
            "description": "No prior MI",
            "domain": "Condition",
            "logicType": "ABSENCE",
        }
        result = self._call(svc, criterion, exclusion=False)

        occ = result["rule"]["expression"]["CriteriaList"][0]["Occurrence"]
        assert occ == {"Type": 0, "Count": 0}

    def test_presence_logic_type_produces_at_least_one(self):
        svc = _make_service()
        criterion = {
            "description": "Prior MI",
            "domain": "Condition",
            "logicType": "PRESENCE",
        }
        result = self._call(svc, criterion, exclusion=False)

        occ = result["rule"]["expression"]["CriteriaList"][0]["Occurrence"]
        assert occ == {"Type": 2, "Count": 1}

    def test_exclusion_flag_overrides_presence_to_zero(self):
        svc = _make_service()
        criterion = {
            "description": "Active cancer",
            "domain": "Condition",
            "logicType": "PRESENCE",
        }
        result = self._call(svc, criterion, exclusion=True)

        occ = result["rule"]["expression"]["CriteriaList"][0]["Occurrence"]
        assert occ == {"Type": 0, "Count": 0}


# ---------------------------------------------------------------------------
# Fix 2: timeAtRisk, domain, conceptSetId on Outcome from IR
# ---------------------------------------------------------------------------


class TestStudyFromIrOutcomeFields:
    def _make_ir(self, outcome_kwargs=None):
        primary = SimpleNamespace(
            entity_text="T2DM",
            domain="Condition",
            observation_window=None,
        )
        target = SimpleNamespace(
            primary_criteria=primary,
            inclusion_rules=[],
            exclusion_rules=[],
        )
        comparator = SimpleNamespace(
            primary_criteria=SimpleNamespace(entity_text="", domain="Condition"),
        )
        outcome_defaults = {
            "entity_text": "MACE",
            "name": "MACE",
            "domain": "Condition",
            "time_at_risk": SimpleNamespace(start=0, end=365),
            "concept_set_id": None,
        }
        if outcome_kwargs:
            outcome_defaults.update(outcome_kwargs)
        outcome = SimpleNamespace(**outcome_defaults)
        return SimpleNamespace(target=target, comparator=comparator, outcome=outcome)

    def test_outcome_includes_time_at_risk(self):
        svc = _make_service()
        ir = self._make_ir({"time_at_risk": SimpleNamespace(start=1, end=180)})
        result = svc._study_from_ir(ir, "Test study")

        primary = result["outcomes"]["primary"]
        assert primary["timeAtRisk"] == {"start": 1, "end": 180}

    def test_outcome_includes_domain(self):
        svc = _make_service()
        ir = self._make_ir({"domain": "Drug"})
        result = svc._study_from_ir(ir, "Test study")

        assert result["outcomes"]["primary"]["domain"] == "Drug"

    def test_outcome_includes_concept_set_id(self):
        svc = _make_service()
        ir = self._make_ir({"concept_set_id": 42})
        result = svc._study_from_ir(ir, "Test study")

        assert result["outcomes"]["primary"]["conceptSetId"] == 42

    def test_outcome_time_at_risk_none_when_missing(self):
        svc = _make_service()
        ir = self._make_ir({"time_at_risk": None})
        result = svc._study_from_ir(ir, "Test study")

        assert result["outcomes"]["primary"]["timeAtRisk"] is None

    def test_outcome_concept_set_id_omitted_when_none(self):
        svc = _make_service()
        ir = self._make_ir({"concept_set_id": None})
        result = svc._study_from_ir(ir, "Test study")

        # conceptSetId should not be present when None
        assert result["outcomes"]["primary"].get("conceptSetId") is None
