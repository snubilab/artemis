"""
Unit tests for the shared Agent 2 map_entity module.
DB/LLM 의존성 없음. Mock 기반.
"""
import os
import pytest
from unittest.mock import MagicMock, patch

from src.agents.agent2.map_entity import (
    EntityMappingResult,
    map_single_entity,
)


class TestEntityMappingResult:

    def test_success_true_with_concepts(self):
        emr = EntityMappingResult(concept_ids=[1, 2, 3])
        assert emr.success is True

    def test_success_false_when_empty(self):
        emr = EntityMappingResult(concept_ids=[])
        assert emr.success is False

    def test_success_false_with_error(self):
        emr = EntityMappingResult(concept_ids=[1], error="something broke")
        assert emr.success is False

    def test_to_meta_dict_keys(self):
        emr = EntityMappingResult(
            processing_time_ms=123.4,
            fast_path_count=1,
            slow_path_count=2,
            gap_count=0,
        )
        d = emr.to_meta_dict()
        assert d["processing_ms"] == 123.4
        assert d["fast_path"] == 1
        assert d["slow_path"] == 2
        assert d["gaps"] == 0
        assert "error" not in d

    def test_to_meta_dict_includes_error(self):
        emr = EntityMappingResult(error="timeout")
        d = emr.to_meta_dict()
        assert d["error"] == "timeout"

    def test_to_mapped_set_structure(self):
        emr = EntityMappingResult(
            concept_ids=[10, 20],
            overbroad_concept_ids=[20],
            route_path="slow",
            atc_expanded=False,
            critic_skipped=True,
            domain_overridden=None,
        )
        ms = emr.to_mapped_set(
            entity_id=5,
            entity_text="Metformin",
            domain="Drug",
            source="target",
            parent_rule="drug_therapy",
        )
        assert ms["id"] == 5
        assert ms["name"] == "Metformin"
        assert ms["domain"] == "Drug"
        assert ms["concept_ids"] == [10, 20]
        assert ms["overbroad_concept_ids"] == [20]
        assert ms["route_path"] == "slow"
        assert ms["critic_skipped"] is True
        assert ms["parent_rule"] == "drug_therapy"
        assert ms["source"] == "target"

    def test_to_mapped_set_no_parent_rule(self):
        emr = EntityMappingResult(concept_ids=[1])
        ms = emr.to_mapped_set(entity_id=1, entity_text="T2DM", domain="Condition")
        assert "parent_rule" not in ms

    def test_to_mapped_set_with_entity_key(self):
        emr = EntityMappingResult(concept_ids=[1, 2])
        ms = emr.to_mapped_set(
            entity_id=1, entity_text="Metformin", domain="Drug",
            entity_key="target:inclusion:0:0",
        )
        assert ms["entity_key"] == "target:inclusion:0:0"

    def test_to_mapped_set_without_entity_key(self):
        emr = EntityMappingResult(concept_ids=[1])
        ms = emr.to_mapped_set(entity_id=1, entity_text="T2DM", domain="Condition")
        assert "entity_key" not in ms


class TestMapSingleEntity:

    def test_successful_mapping(self):
        mock_result = MagicMock()
        mock_result.concept_ids = [100, 200]
        mock_result.overbroad_concept_ids = []
        mock_result.route_path = "slow"
        mock_result.atc_expanded = False
        mock_result.critic_skipped = False
        mock_result.domain_overridden = None
        mock_result.processing_time_ms = 42.0
        mock_result.fast_path_count = 0
        mock_result.slow_path_count = 1
        mock_result.gap_report.total_criteria = 1
        mock_result.gap_report.mapped_count = 1

        mock_agent2 = MagicMock()
        mock_agent2.process_with_details.return_value = mock_result

        emr = map_single_entity("Metformin", domain_hint="Drug", agent2=mock_agent2)
        assert emr.success is True
        assert emr.concept_ids == [100, 200]
        assert emr.route_path == "slow"
        mock_agent2.process_with_details.assert_called_once_with(
            "Metformin", context=None, domain_hint="Drug", force_slow_path=False,
        )

    def test_with_rule_context(self):
        mock_result = MagicMock()
        mock_result.concept_ids = [1]
        mock_result.overbroad_concept_ids = []
        mock_result.route_path = "fast"
        mock_result.atc_expanded = False
        mock_result.critic_skipped = True
        mock_result.domain_overridden = None
        mock_result.processing_time_ms = 10.0
        mock_result.fast_path_count = 1
        mock_result.slow_path_count = 0
        mock_result.gap_report.total_criteria = 1
        mock_result.gap_report.mapped_count = 1

        mock_agent2 = MagicMock()
        mock_agent2.process_with_details.return_value = mock_result

        emr = map_single_entity(
            "Aspirin", domain_hint="Drug", rule_context="Antiplatelet therapy", agent2=mock_agent2,
        )
        mock_agent2.process_with_details.assert_called_once_with(
            "Aspirin", context="Antiplatelet therapy", domain_hint="Drug", force_slow_path=False,
        )
        assert emr.success is True
        assert emr.critic_skipped is True

    def test_error_handling(self):
        mock_agent2 = MagicMock()
        mock_agent2.process_with_details.side_effect = RuntimeError("DB down")

        emr = map_single_entity("BadQuery", agent2=mock_agent2)
        assert emr.success is False
        assert "DB down" in emr.error
        assert emr.concept_ids == []
        assert emr.processing_time_ms > 0

    def test_force_slow_path_passes_explicit_override_without_env_mutation(self, monkeypatch):
        mock_result = MagicMock()
        mock_result.concept_ids = [200]
        mock_result.overbroad_concept_ids = []
        mock_result.route_path = "slow"
        mock_result.atc_expanded = False
        mock_result.critic_skipped = False
        mock_result.domain_overridden = None
        mock_result.processing_time_ms = 1.0
        mock_result.fast_path_count = 0
        mock_result.slow_path_count = 1
        mock_result.gap_report.total_criteria = 1
        mock_result.gap_report.mapped_count = 1

        mock_agent2 = MagicMock()
        mock_agent2.process_with_details.return_value = mock_result

        monkeypatch.delenv("FORCE_SLOW_PATH", raising=False)

        emr = map_single_entity(
            "Hypertension",
            domain_hint="Condition",
            force_slow_path=True,
            agent2=mock_agent2,
        )

        mock_agent2.process_with_details.assert_called_once_with(
            "Hypertension",
            context=None,
            domain_hint="Condition",
            force_slow_path=True,
        )
        assert emr.route_path == "slow"
        assert emr.concept_ids == [200]
        assert os.environ.get("FORCE_SLOW_PATH") is None
