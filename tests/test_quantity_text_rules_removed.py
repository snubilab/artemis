"""RFC-016 step 3: the English threshold parser and what it fed are gone (A1, A5a, A5b).

Real inputs throughout (``tests/fixtures/rfc016_quantity_rows.json``, with SHA-256s). No LLM.

* A5a -- ``annotate_value_constraints`` parsed each criterion line with English comparator
  spellings and appended a ``[value_constraint] {...}`` line to Agent 1's prompt. The P2 NEW
  run shows the model copying that annotation into ``source_text`` verbatim (30 of 450 IR
  rows, 35 store ``protocolLine``s); the block Agent 1 is handed now numbers the lines and
  adds nothing. Step 6 (the parsed-count warning) and Steps 8a/8b (re-attaching parsed
  constraints) went with it.
* A5b -- the duration / dose / anatomic / statistical / item-count word rejections lived in
  the same parser; ``quantity_kind`` replaces them (``tests/test_quantity_thresholds_in_build.py``).
* The planner's member threshold was a phrase parsed by the same parser; the planner now
  states it as a structured ``value_constraint`` and quotes ``value_constraint_text``, kept
  only when that fragment is a substring of the line.
* A1 -- ``_repair_inclusive_upper_bounds`` read ``<=`` / ``N - M`` out of ``source_text`` to
  rewrite an inclusion ``ABSENCE gte``/``lte`` into ``gt``. Deleted; the operator Agent 1 wrote
  now reaches the store unchanged. That has a cost, pinned below on the row it was built for.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent1 import parser as parser_module
from src.agents.agent1 import prompts

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_quantity_rows.json").read_text()
)
LEADER = FIXTURE["leader_p2_new_ir"]
CARMELINA_BAND = FIXTURE["carmelina_ir_hba1c_band"]["inclusion_rules_4_5"]
CARMELINA_LIVER_LINE = FIXTURE["carmelina_exclusion"][0]["protocolLine"]


class TestAgent1IsHandedTheLinesOnly:
    def test_should_number_the_lines_and_add_nothing(self):
        lines = LEADER["inclusion_criteria_1_3"]
        assert parser_module.LogicDecomposer._format_criteria(lines) == "\n".join(
            f"  {number}. {line}" for number, line in enumerate(lines, start=1)
        )

    def test_should_no_longer_offer_what_the_p2_run_copied_into_source_text(self):
        """The model wrote the injected annotation back into the row's ``source_text``,
        which then became ``protocolLine`` -- the text every span is checked against."""
        copied = LEADER["glycated_hemoglobin_source_text"].split("\n", 1)[1].strip()
        assert copied.startswith("[value_constraint] ")
        block = parser_module.LogicDecomposer._format_criteria(LEADER["inclusion_criteria_1_3"])
        assert copied not in block

    def test_should_not_mention_the_annotation_in_either_prompt(self):
        assert "[value_constraint]" not in prompts.NCT_SYSTEM_PROMPT
        assert "[value_constraint]" not in prompts.NCT_DECOMPOSITION_PROMPT

    def test_should_have_no_threshold_parser_or_reattachment_left(self):
        from src.services import value_constraint

        for name in ("parse_value_constraint", "parse_value_constraints",
                     "annotate_value_constraints"):
            assert not hasattr(value_constraint, name), name
        for name in ("_count_value_constraints", "_repair_dropped_threshold",
                     "_llm_match_dropped_threshold", "_repair_inclusive_upper_bounds"):
            assert not hasattr(parser_module.LogicDecomposer, name), name
        assert not hasattr(prompts, "THRESHOLD_MATCH_PROMPT")


class TestThePlannerStatesItsMembersThreshold:
    """CARMELINA exclusion 10's line: "... ≥ 3 x upper limit of normal (ULN) ..."."""

    SPAN = "≥ 3 x upper limit of normal (ULN)"

    def _member(self, span: Any, constraint: Any) -> dict[str, Any]:
        return {"name": "ALT", "entity_text": "ALT (SGPT)", "domain": "Measurement",
                "value_constraint_text": span, "value_constraint": constraint}

    def test_should_keep_the_threshold_when_its_fragment_is_in_the_line(self):
        from src.agents.planner.decomposer import stated_member_value_constraint

        assert self.SPAN in CARMELINA_LIVER_LINE
        vc = stated_member_value_constraint(
            self._member(self.SPAN, {"op": "gte", "value": 3, "unit_text": None,
                                     "reference_bound": "uln"}),
            CARMELINA_LIVER_LINE,
        )
        assert (vc.op, vc.value, vc.reference_bound) == ("gte", 3.0, "uln")

    @pytest.mark.parametrize(
        ("span", "constraint"),
        [
            ("≥ 3 x ULN", {"op": "gte", "value": 3, "reference_bound": "uln"}),
            (SPAN, {"op": "at least", "value": 3, "reference_bound": "uln"}),
            (SPAN, None),
            (None, {"op": "gte", "value": 3, "reference_bound": "uln"}),
        ],
        ids=["fragment-not-in-line", "op-not-an-op", "no-structure", "no-fragment"],
    )
    def test_should_keep_nothing_otherwise(self, span, constraint):
        from src.agents.planner.decomposer import stated_member_value_constraint

        assert stated_member_value_constraint(
            self._member(span, constraint), CARMELINA_LIVER_LINE
        ) is None


class TestNoRepairReadsAComparatorOutOfTheLine:
    """CARMELINA's HbA1c band, as the shared IR cache holds it: inclusion_rules[4] is
    ``PRESENCE gte 6.5`` and [5] is ``ABSENCE lte 10.0`` off "HbA1c of ≥ 6.5% and ≤ 10.0%".

    A1 read the ``≤`` in that line, flipped [5] to ``gt`` and let the split-band repair
    merge the pair into ``bt 6.5..10.0``. With A1 deleted, [5] stays as Agent 1 wrote it --
    "no HbA1c <= 10", the inverse of the line -- and the pair stays two rules. This is the
    measured cost of the deletion on the row it was written for; no annotation field in
    RFC-016 §3 states a comparison's direction, so nothing replaces it here."""

    def _cohort(self):
        with patch.object(parser_module, "get_llm", return_value=MagicMock()):
            agent1 = parser_module.LogicDecomposer(model_name="vllm/google/gemma-4-E4B-it")
        return agent1._build_cohort_definition(
            {"primary_criteria": {"domain": "Drug", "entity_text": "linagliptin"},
             "inclusion_rules": json.loads(json.dumps(CARMELINA_BAND)),
             "exclusion_rules": []}
        )

    def test_should_leave_the_operator_agent_1_wrote(self):
        cohort = self._cohort()
        ops = [(rule.logic_type, rule.value_constraint.op, rule.value_constraint.value)
               for rule in cohort.inclusion_rules]
        assert ops == [("PRESENCE", "gte", 6.5), ("ABSENCE", "lte", 10.0)]

    def test_should_record_no_inclusive_bound_correction(self):
        actions = {record["action"] for record in self._cohort().repair_accounting or []}
        assert "inclusive-upper-bound-corrected" not in actions
