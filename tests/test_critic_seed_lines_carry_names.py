"""Every seed line in the critic prompt names its concept.

A seed is never among the KG-expanded candidates: workflow.py deduplicates the KG
results against ``seen = set(seed_ids)`` before the critic runs, so the critic's
"seed matched a KG concept" branch never fires and every seed was rendered as a bare
id. In the 2026-10-09 arm-A rebuild all 88 critic requests carried such a line. For
'Type 1 diabetes mellitus' the critic saw ``- ID: 201254 | Relationship: seed (vector
search top match)`` -- with no hint that 201254 IS Type 1 diabetes mellitus -- next to
43 named KG candidates, 26 of them other diabetes types, and accepted 11 off-target
concepts.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2.critic import ConceptCritic


def _kg(concept_id: int, name: str) -> MagicMock:
    c = MagicMock()
    c.concept_id = concept_id
    c.concept_name = name
    c.domain_id = "Condition"
    c.vocabulary_id = "SNOMED"
    c.relationship = "sibling"
    return c


@pytest.fixture
def critic() -> ConceptCritic:
    with patch.dict(os.environ, {"AGENT2_CRITIC_SELF_REFLECT": "false"}), \
         patch("src.agents.agent2.critic.get_llm", return_value=MagicMock()):
        return ConceptCritic()


def _rendered_candidates(critic: ConceptCritic, seed_ids, kg, concept_rows) -> str:
    """The candidates_text the critic would send, with the LLM and the DB stubbed."""
    chain = MagicMock()
    chain.invoke.return_value = {"selected_concepts": [], "overall_reasoning": ""}
    critic._default_chain = chain
    with patch.object(critic, "_cache") as cache, \
         patch("src.agents.agent2.critic.select_critic_model", return_value=None), \
         patch("src.agents.agent2.critic._concept_rows", create=True,
               side_effect=concept_rows):
        cache.get.return_value = None
        critic.evaluate("Type 1 diabetes mellitus", seed_ids, kg, domain_hint="Condition")
    return chain.invoke.call_args.args[0]["candidates_text"]


def test_should_name_a_seed_when_it_is_not_among_the_kg_candidates(critic):
    rows = {201254: ("Type 1 diabetes mellitus", "Condition", "SNOMED")}
    text = _rendered_candidates(
        critic, [201254], [_kg(201826, "Type 2 diabetes mellitus")],
        lambda ids: {i: rows[i] for i in ids if i in rows},
    )
    assert (
        "- ID: 201254 | Name: Type 1 diabetes mellitus | Domain: Condition "
        "| Vocab: SNOMED | Relationship: seed (vector search top match)\n"
    ) in text


def test_should_leave_the_kg_candidate_lines_unchanged_when_naming_seeds(critic):
    rows = {201254: ("Type 1 diabetes mellitus", "Condition", "SNOMED")}
    text = _rendered_candidates(
        critic, [201254], [_kg(201826, "Type 2 diabetes mellitus")],
        lambda ids: {i: rows[i] for i in ids if i in rows},
    )
    assert text.splitlines()[1] == (
        "- ID: 201826 | Name: Type 2 diabetes mellitus | Domain: Condition "
        "| Vocab: SNOMED | Relationship: sibling"
    )


def test_should_keep_the_bare_seed_line_and_warn_when_the_concept_table_lacks_the_id(
    critic, caplog
):
    with caplog.at_level("WARNING", logger="src.agents.agent2.critic"):
        text = _rendered_candidates(
            critic, [999999999], [_kg(201826, "Type 2 diabetes mellitus")],
            lambda ids: {},
        )
    assert "- ID: 999999999 | Relationship: seed (vector search top match)\n" in text
    assert "999999999" in caplog.text
