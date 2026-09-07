"""The LLM criteria-validation pass: response contract, loud failure, and merge.

Three contracts used to contradict each other, so this pass could never succeed:
``_get_criteria_llm`` asks ``get_llm(json_mode=True)``, which constrains the model
to a top-level JSON **object**; the prompt asked for a top-level **array**; and the
parser accepted only a top-level **array**. Measured on the completed six-study cold
run (``tmp/tte_cold6_32k_20260907/cold6_32k.log``): 0 occurrences of the success
line, 1 occurrence of ``LLM returned non-list: <class 'dict'>``.

These tests pin the object contract, the bare-list tolerance kept for providers
that ignore ``response_format``, the rejection of genuinely malformed content, and
the distinct log outcome that separates "attempted and produced nothing" from
"never attempted".

``_merge_parsed_items`` is covered here too: it had never executed in production,
because ``llm_items`` was always empty. Fixing the parse is what starts running it.

Order-independence: ``tests/test_parser_paper_status.py`` replaces
``pubmed_fetcher.extract_eligibility_from_text`` with a MagicMock at import time,
so collection order changes module state. Nothing here touches that symbol, and
every LLM collaborator is pinned per-test via monkeypatch.
"""
import importlib.util
import json
import logging
import pathlib

import pytest

from src.agents.agent1.criteria_dedup import (
    OR_GROUP_JOIN,
    OR_GROUP_PREFIX,
    OR_GROUP_SEP,
)


def _load_module_under_test():
    """Load pubmed_fetcher from source, bypassing ``sys.modules`` entirely.

    ``tests/test_parser_paper_status.py`` installs a MagicMock at
    ``sys.modules["src.agents.agent1.pubmed_fetcher"]`` at import time and never
    removes it, so a plain import here returns a mock or the real module purely
    according to collection order. Loading from the file path is deterministic in
    both orders. The module name is deliberately distinct so this copy never
    replaces the real entry for anything else.
    """
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "src" / "agents" / "agent1" / "pubmed_fetcher.py")
    spec = importlib.util.spec_from_file_location("_pubmed_fetcher_under_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pf = _load_module_under_test()


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Returns a canned body; records the prompt it was handed."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.prompts: list = []

    def invoke(self, messages):
        self.prompts.append(messages[0].content)
        return _FakeResponse(self._content)


@pytest.fixture
def pin_llm(monkeypatch):
    """Pin ``_get_criteria_llm`` to a fake returning ``content``."""

    def _pin(content: str) -> _FakeLLM:
        fake = _FakeLLM(content)
        monkeypatch.setattr(pf, "_get_criteria_llm", lambda: fake)
        return fake

    return _pin


# The real 384-char CARMELINA inclusion fragment. This is where the gate actually
# opens today: data/papers/NCT01897532/jama_2019_carmelina_supplement.pdf yields a
# 7419-char eligibility section whose inclusion side the regex splits into 3 items.
CARMELINA_FRAGMENT = (
    "1) Documented diagnosis of type 2 diabetes before visit 1 (screening).\n"
    "2) Male or female patients who are drug-naive or pre-treated with any antidiabetic\n"
    "background therapy, excluding treatment with GLP-1 receptor agonists, DPP-4 inhibitors\n"
    "or SGLT-2 inhibitors if >= 7 consecutive days.\n"
    "3) Stable antidiabetic background medication (unchanged daily dose) for at least 8 weeks\n"
    "prior to visit 1.\n"
)


# ---------------------------------------------------------------- prompt contract


def test_should_ask_for_a_json_object_when_the_llm_is_constrained_to_json_object():
    """The prompt must agree with ``json_mode=True``, which forbids a top-level array."""
    prompt = pf._LLM_CRITERIA_PROMPT
    assert "JSON object" in prompt, prompt
    assert '"criteria"' in prompt, prompt
    assert "JSON array of strings" not in prompt, prompt


# ------------------------------------------------------------------ parser: accept


def test_should_extract_criteria_when_llm_returns_json_object_with_criteria_key(pin_llm):
    pin_llm(json.dumps({"criteria": [
        "Documented diagnosis of type 2 diabetes before visit 1",
        "Stable antidiabetic background medication for at least 8 weeks",
    ]}))

    assert pf._llm_parse_criteria(CARMELINA_FRAGMENT) == [
        "Documented diagnosis of type 2 diabetes before visit 1",
        "Stable antidiabetic background medication for at least 8 weeks",
    ]


def test_should_extract_criteria_when_llm_returns_bare_list(pin_llm):
    """Kept: some providers ignore ``response_format`` and emit the array anyway."""
    pin_llm(json.dumps(["Age 18 years or older", "Type 2 diabetes mellitus"]))

    assert pf._llm_parse_criteria(CARMELINA_FRAGMENT) == [
        "Age 18 years or older",
        "Type 2 diabetes mellitus",
    ]


def test_should_extract_criteria_when_object_is_wrapped_in_a_markdown_fence(pin_llm):
    pin_llm('```json\n{"criteria": ["Age 18 years or older"]}\n```')

    assert pf._llm_parse_criteria(CARMELINA_FRAGMENT) == ["Age 18 years or older"]


def test_should_extract_criteria_when_object_uses_a_different_single_list_key(pin_llm):
    """One key, one list: unambiguous, so read it rather than discard the pass."""
    pin_llm(json.dumps({"eligibility_criteria": ["Age 18 years or older"]}))

    assert pf._llm_parse_criteria(CARMELINA_FRAGMENT) == ["Age 18 years or older"]


# ------------------------------------------------------------------ parser: reject


def test_should_return_empty_when_llm_returns_unparseable_text(pin_llm):
    pin_llm("Here are the criteria: age 18+, type 2 diabetes.")

    assert pf._llm_parse_criteria(CARMELINA_FRAGMENT) == []


def test_should_return_empty_when_object_carries_no_list_value(pin_llm):
    pin_llm(json.dumps({"criteria": "age 18 or older", "count": 1}))

    assert pf._llm_parse_criteria(CARMELINA_FRAGMENT) == []


def test_should_return_empty_when_object_is_ambiguous_with_several_lists(pin_llm):
    """Two candidate lists and no ``criteria`` key: guessing would be silent damage."""
    pin_llm(json.dumps({"inclusion": ["Age 18 or older"], "exclusion": ["Type 1 diabetes"]}))

    assert pf._llm_parse_criteria(CARMELINA_FRAGMENT) == []


def test_should_return_empty_when_llm_invocation_raises(monkeypatch):
    class _Boom:
        def invoke(self, messages):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(pf, "_get_criteria_llm", lambda: _Boom())

    assert pf._llm_parse_criteria(CARMELINA_FRAGMENT) == []


# -------------------------------------------------------------------- loud failure


def test_should_log_a_distinct_outcome_when_the_pass_is_attempted_but_yields_nothing(
    pin_llm, caplog
):
    """An attempted pass that produced nothing must not read like "nothing to add"."""
    pin_llm("Here are the criteria: age 18+, type 2 diabetes.")

    with caplog.at_level(logging.WARNING, logger=pf.logger.name):
        assert pf._llm_parse_criteria(CARMELINA_FRAGMENT) == []

    assert pf.LLM_REASON_UNPARSEABLE in caplog.text, caplog.text


def test_should_name_the_rejection_reason_when_the_response_shape_is_unusable(
    pin_llm, caplog
):
    pin_llm(json.dumps({"criteria": "age 18 or older"}))

    with caplog.at_level(logging.WARNING, logger=pf.logger.name):
        pf._llm_parse_criteria(CARMELINA_FRAGMENT)

    assert pf.LLM_REASON_SHAPE in caplog.text, caplog.text
    assert pf.LLM_REASON_SHAPE == "unrecognised-shape"


def test_should_not_log_the_empty_marker_when_the_pass_succeeds(monkeypatch, caplog):
    monkeypatch.setattr(
        pf, "_llm_parse_criteria",
        lambda text: ["Written informed consent obtained prior to any study procedure"],
    )

    with caplog.at_level(logging.INFO, logger=pf.logger.name):
        items = pf._parse_criteria_items(CARMELINA_FRAGMENT)

    assert "Written informed consent obtained prior to any study procedure" in items
    assert pf.LLM_PASS_EMPTY_MARKER not in caplog.text, caplog.text


def test_should_record_the_outcome_at_the_gate_when_the_pass_returns_nothing(
    monkeypatch, caplog
):
    """The caller must distinguish "attempted, nothing usable" from "never attempted"."""
    monkeypatch.setattr(pf, "_llm_parse_criteria", lambda text: [])

    with caplog.at_level(logging.WARNING, logger=pf.logger.name):
        items = pf._parse_criteria_items(CARMELINA_FRAGMENT)

    assert items, "regex-only result must still be returned"
    assert pf.LLM_PASS_EMPTY_MARKER in caplog.text, caplog.text


def test_should_not_mention_the_llm_pass_when_the_gate_never_opens(caplog):
    text = "\n".join(
        f"{i}) Criterion number {i} about a documented condition." for i in range(1, 9)
    )

    with caplog.at_level(logging.INFO, logger=pf.logger.name):
        pf._parse_criteria_items(text)

    assert "LLM" not in caplog.text, caplog.text


# ---------------------------------------------------------------- merge behaviour


def test_should_append_llm_item_when_it_is_not_similar_to_any_regex_item():
    regex_items = ["Documented diagnosis of type 2 diabetes before visit 1"]
    llm_items = ["Stable antidiabetic background medication for at least 8 weeks"]

    assert pf._merge_parsed_items(regex_items, llm_items) == [
        "Documented diagnosis of type 2 diabetes before visit 1",
        "Stable antidiabetic background medication for at least 8 weeks",
    ]


def test_should_drop_llm_item_when_it_near_duplicates_a_regex_item():
    regex_items = ["Documented diagnosis of type 2 diabetes before visit 1"]
    llm_items = ["Documented diagnosis of type 2 diabetes before visit 1 (screening)"]

    assert pf._merge_parsed_items(regex_items, llm_items) == regex_items


def test_should_return_regex_items_unchanged_when_llm_items_are_empty():
    regex_items = ["Age 18 years or older", "Type 2 diabetes mellitus"]

    assert pf._merge_parsed_items(regex_items, []) == regex_items


def test_should_preserve_regex_item_order_when_appending_llm_items():
    regex_items = [
        "Documented diagnosis of type 2 diabetes before visit 1",
        "Body-mass index of 45 or less at screening",
    ]
    llm_items = ["Written informed consent obtained prior to any study procedure"]

    merged = pf._merge_parsed_items(regex_items, llm_items)

    assert merged[:2] == regex_items
    assert merged[2] == "Written informed consent obtained prior to any study procedure"


def test_should_drop_llm_item_when_it_restates_an_or_group_alternative():
    """The LLM is handed raw, uncollapsed text, so it re-flattens the hierarchy the
    collapse just built. Whole-string similarity cannot catch that -- an alternative
    is far shorter than the group line containing it."""
    or_group = (
        f"{OR_GROUP_PREFIX}Documented cardiovascular disease{OR_GROUP_JOIN}"
        f"prior myocardial infarction{OR_GROUP_SEP}prior ischaemic stroke"
    )
    regex_items = [or_group]

    assert pf._merge_parsed_items(regex_items, ["prior myocardial infarction"]) == regex_items
