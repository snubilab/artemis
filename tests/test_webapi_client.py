import copy
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "pipeline" / "webapi_client.py"
SPEC = importlib.util.spec_from_file_location("webapi_client_under_test", MODULE_PATH)
webapi_client = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(webapi_client)

WebAPIClient = webapi_client.WebAPIClient
prune_unused_concept_sets = webapi_client.prune_unused_concept_sets


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _sample_expression():
    return {
        "PrimaryCriteria": {
            "CriteriaList": [{"DrugEra": {"CodesetId": 45}}],
            "ObservationWindow": {"PriorDays": 180, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "EndStrategy": {"CustomEra": {"DrugCodesetId": 47, "GapDays": 7, "Offset": 0}},
        "CensoringCriteria": [{"DrugExposure": {"CodesetId": 43}}],
        "ConceptSets": [
            {"id": 43, "name": "clopidogrel", "expression": {"items": []}},
            {"id": 45, "name": "ticagrelor", "expression": {"items": []}},
            {"id": 47, "name": "ticagrelor era", "expression": {"items": []}},
            {"id": 99, "name": "unused", "expression": {"items": []}},
        ],
    }


def test_prune_unused_concept_sets_keeps_only_referenced_ids():
    expression = _sample_expression()

    pruned = prune_unused_concept_sets(expression)

    assert [concept_set["id"] for concept_set in pruned["ConceptSets"]] == [43, 45, 47]
    assert [concept_set["id"] for concept_set in expression["ConceptSets"]] == [43, 45, 47, 99]


def test_create_cohort_definition_prunes_payload_without_mutating_input():
    client = WebAPIClient(base_url="http://example.test")
    client.list_cohort_definitions = lambda: []

    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout
        return _DummyResponse({"id": 123})

    client.session.post = fake_post

    expression = _sample_expression()
    original = copy.deepcopy(expression)

    result = client.create_cohort_definition("PLATO test", expression)

    assert result["id"] == 123
    assert captured["url"].endswith("/cohortdefinition")
    posted_expression = captured["payload"]["expression"]
    assert [concept_set["id"] for concept_set in posted_expression["ConceptSets"]] == [43, 45, 47]
    assert "_cacheBust" in posted_expression
    assert expression == original
    assert "_cacheBust" not in expression
