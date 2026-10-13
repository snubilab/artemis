"""The mapping-quality gate pairs each entity with its own mapping outcome by id.

`PipelineSupervisor.post_agent2_check` is reached from the API: POST
/tte/studies/{id}/suggest-eligibility -> TTEService.suggest_eligibility ->
_run_section_suggestion -> _build_real_mapping_quality_signal -> post_agent2_check.

It used to pair entities with mapped sets by lower-cased text. Two different criteria
that carry the same description then share one outcome: LEADER's inclusion "chronic
heart failure" (protocol line 18, PRESENCE, concept set 25) and exclusion "Chronic heart
failure (NYHA class IV)" (protocol line 8, ABSENCE, concept set 38) are both described
"Chronic heart failure" in the store. When the inclusion maps and the exclusion does not,
the text join reads the exclusion as mapped and the gate says "ok".
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from src.api.main import create_app
from src.api.tte import get_tte_service
from src.services.tte_service import TTEService
from testclient_compat import CompatTestClient

FIXTURE = Path(__file__).parent / "fixtures" / "dormant_join_rows.json"
UNMAPPED_ITEM_ID = "eligibility_exclusion_0"


def _real_pair() -> dict:
    return json.loads(FIXTURE.read_text())["leader_chf_inclusion_exclusion_pair"]


def _install_agent2_that_leaves_one_entity_unmapped(monkeypatch) -> None:
    """Agent 2 stand-in: every call returns one concept, except the call for the entity
    whose item_id is UNMAPPED_ITEM_ID. Which call that is comes from the entity list the
    service itself built (recorded by a spy), so the stand-in reads no text."""
    built: list[list[dict]] = []
    original = TTEService._build_mapping_entities_for_section

    def spy(self, study, provisional_ir, section_key):
        entities = original(self, study, provisional_ir, section_key)
        built.append(entities)
        return entities

    monkeypatch.setattr(TTEService, "_build_mapping_entities_for_section", spy)

    class Agent2:
        def __init__(self) -> None:
            self.calls = 0

        def process_with_details(self, *_args, **_kwargs):
            position = self.calls
            self.calls += 1
            unmapped_position = [e["item_id"] for e in built[-1]].index(UNMAPPED_ITEM_ID)
            return types.SimpleNamespace(
                concept_ids=[] if position == unmapped_position else [4229440],
                route_path="fast",
                critic_skipped=False,
                domain_overridden=False,
            )

    module = types.ModuleType("src.agents.agent2.workflow")
    module.get_agent2 = Agent2
    monkeypatch.setitem(sys.modules, "src.agents.agent2.workflow", module)


def test_should_report_the_unmapped_exclusion_when_an_inclusion_with_the_same_description_mapped(
    monkeypatch, tmp_path
):
    pair = _real_pair()
    assert pair["inclusion_row"]["description"] == pair["exclusion_row"]["description"]
    _install_agent2_that_leaves_one_entity_unmapped(monkeypatch)
    monkeypatch.setenv("TTE_STORE_PATH", str(tmp_path / "tte" / "studies.json"))
    get_tte_service.cache_clear()
    client = CompatTestClient(create_app())

    created = client.post(
        "/tte/studies",
        json={
            "name": pair["study_name"],
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "inclusionCriteria": [pair["inclusion_row"]],
                "exclusionCriteria": [pair["exclusion_row"]],
            },
        },
    )
    assert created.status_code in (200, 201), created.text
    response = client.post(f"/tte/studies/{created.json()['id']}/suggest-eligibility")
    assert response.status_code == 200, response.text
    artifact = client.get(f"/tte/artifacts/{response.json()['artifactId']}").json()
    quality = artifact["payload"]["meta"]["mappingQuality"]

    assert quality["retryReasons"] == ["empty"]
    assert quality["reason"] == "empty_mapping"
    assert quality["status"] == "warning"

