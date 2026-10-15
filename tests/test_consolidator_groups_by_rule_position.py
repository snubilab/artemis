"""The consolidator groups a rule's sub-criteria by the rule's position, not by its name.

``_collect_rule_entities`` used to key each sub-criterion's ``parent_rule`` on the rule's
lower-cased name, and the consolidator merges every mapped set sharing a key. Two rules carrying
the same name -- LEADER's Agent 1 IR (``tests/fixtures/rfc016_leader_ir_target.json``, verbatim)
has inclusion rules 2 and 3 named identically, and a target and comparator arm repeat every rule
name -- were merged into ONE concept set, and the second rule lost its own.

Reachable only from the scripts' CohortPipeline / ArtemisPipeline path (no API route, TTEService
method or delivery script reaches ``_step2_5_consolidate``).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from src.agents.agent2.map_entity import EntityMappingResult
from src.agents.consolidator.consolidator import ConceptSetConsolidator
from src.models.ir import CohortDefinition, GapReport
from src.pipeline.supervisor import Agent2MappingTelemetry, PipelineSupervisor

LEADER_TARGET = json.loads(
    (Path(__file__).parent / "fixtures" / "rfc016_leader_ir_target.json").read_text()
)["target"]


def _consolidated(entities: list[dict]) -> list[dict]:
    outcomes = [
        {
            "index": i,
            "entity": entity,
            "emr": EntityMappingResult(concept_ids=[1000 + i], route_path="fast"),
            "processing_time_ms": 0.0,
        }
        for i, entity in enumerate(entities)
    ]
    mapped = PipelineSupervisor._build_mapped_sets_and_gap(
        outcomes, GapReport(), Agent2MappingTelemetry(entity_count=len(entities))
    )
    ontology = MagicMock()
    ontology.get_ancestors.side_effect = lambda cid, max_levels=5: [1]  # one shared ancestor
    ontology.get_concept_name.return_value = None
    return ConceptSetConsolidator(ontology_search=ontology).consolidate(mapped)


def test_should_keep_one_set_per_rule_when_two_rules_share_a_name():
    cohort = CohortDefinition.model_validate(LEADER_TARGET)
    rules = cohort.inclusion_rules
    assert rules[2].name == rules[3].name and rules[2].sub_criteria
    entities = PipelineSupervisor._collect_cohort_entities(cohort, "target")
    grouped_rules = {
        e["entity_key"].rsplit(":", 1)[0] for e in entities if e.get("parent_rule")
    }
    merged = [ms for ms in _consolidated(entities) if "merged_from" in ms]
    # rules 2, 3, 13 and 14 each have several sub-criteria; one merged set per rule
    assert len(merged) == len(grouped_rules) == 4
    assert sorted(ms["parent_rule"] for ms in merged) == sorted(grouped_rules)


def test_should_not_merge_target_and_comparator_sets_when_the_arms_repeat_a_rule():
    cohort = CohortDefinition.model_validate(LEADER_TARGET)
    entities = PipelineSupervisor._collect_cohort_entities(
        cohort, "target"
    ) + PipelineSupervisor._collect_cohort_entities(cohort, "comparator")
    merged = [ms for ms in _consolidated(entities) if "merged_from" in ms]
    assert {ms["source"] for ms in merged} == {"target", "comparator"}
    assert len(merged) == 8
