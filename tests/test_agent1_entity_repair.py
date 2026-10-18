"""A leaf Agent 1 returned without ``entity_text`` is re-asked for it, once per trial.

Measured on the P6 SEG-OFF arm: ARISTOTLE's extraction left ``entity_text`` empty on 27 of
31 non-demographic leaves, and two fresh draws on the identical input (prompt hash
275a22924d82b790) reproduced all 27 -- a property of prompt + input, not a single draw. An
empty entity costs twice: the mapper seeds on the LLM-written ``name`` instead, and the
planner skips the row (``planner/decomposer.py``: "Skip if entity_text is None"), so a
compound lab line ("ALT or AST > 2X ULN or a Total Bilirubin >= 1.5X ULN") is never split.

The trigger is structural (the field is empty); what the entity is, the model says.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.agents.agent1.parser import LogicDecomposer


class _Stub:
    def __init__(self, reply):
        self.reply = reply
        self.prompts: list[str] = []

    def invoke(self, messages):
        self.prompts.append(messages[-1].content)
        return SimpleNamespace(content=self.reply, response_metadata={}, usage_metadata=None)


def _decomposer(stub) -> LogicDecomposer:
    dec = LogicDecomposer.__new__(LogicDecomposer)
    dec.llm = stub
    dec.model_name = "stub"
    return dec


def _data():
    return {
        "target": {
            "inclusion_rules": [
                {"name": "Hypertension requiring treatment", "domain": "Condition", "entity_text": None,
                 "source_text": "Hypertension requiring pharmacological treatment"},
                {"name": "Age", "domain": "Demographics", "entity_text": "Age", "source_text": "Age >= 18"},
            ],
            "exclusion_rules": [
                {"name": "Liver tests", "domain": "Measurement", "entity_text": None, "group_type": "ANY",
                 "source_text": "ALT or AST > 2X ULN",
                 "sub_criteria": [{"name": "ALT", "domain": "Measurement", "entity_text": "",
                                   "source_text": "ALT or AST > 2X ULN"}]},
            ],
        },
        "comparator": {"inclusion_rules": [], "exclusion_rules": []},
    }


def test_should_not_ask_when_every_leaf_has_its_entity():
    stub = _Stub("{}")
    data = {"target": {"inclusion_rules": [{"name": "Age", "domain": "Demographics", "entity_text": "Age",
                                            "source_text": "Age >= 18"}]}}
    assert _decomposer(stub)._repair_missing_entity_text(data, "NCT0") == data
    assert stub.prompts == []


def test_should_fill_each_empty_leaf_with_the_entity_the_model_names():
    stub = _Stub(json.dumps({"entities": [
        {"id": "E1", "entity_text": "Hypertension"},
        {"id": "E2", "entity_text": "Alanine aminotransferase"},
    ]}))
    data = _decomposer(stub)._repair_missing_entity_text(_data(), "NCT0")
    inc = data["target"]["inclusion_rules"]
    assert inc[0]["entity_text"] == "Hypertension"
    assert inc[1]["entity_text"] == "Age"
    group = data["target"]["exclusion_rules"][0]
    assert group["entity_text"] is None, "a parent with sub_criteria is not a leaf"
    assert group["sub_criteria"][0]["entity_text"] == "Alanine aminotransferase"
    assert "Hypertension requiring pharmacological treatment" in stub.prompts[0]
    assert len(stub.prompts) == 1


def test_should_ignore_an_identifier_it_did_not_offer_and_keep_the_leaf_empty():
    stub = _Stub(json.dumps({"entities": [{"id": "E9", "entity_text": "x"}, {"id": "E1", "entity_text": ""}]}))
    data = _decomposer(stub)._repair_missing_entity_text(_data(), "NCT0")
    assert data["target"]["inclusion_rules"][0]["entity_text"] is None


def test_should_return_the_draw_unchanged_when_the_answer_is_unreadable():
    data = _decomposer(_Stub("not json"))._repair_missing_entity_text(_data(), "NCT0")
    assert data == _data()
