"""A failed refiner lookup refuses the query's expansion; it never lets the expansion through.

ConceptSetRefiner reads ``concept_ancestor`` to decide which KG-added ancestors keep their
descendants (Pass 2), which concepts are too wide (Pass 3 / legacy) and which ancestors a
kept descendant makes redundant (Pass 1). When a read failed, the count came back
``None`` / ``{}`` and the subsumption set came back empty, and each was read as an answer:
a Condition ancestor whose count was unknown kept ``includeDescendants=true``, nothing was
flagged overbroad, nothing was pruned -- the over-wide set 61e15d7 removed from the KG
expander, re-admitted one stage later. These tests point the database at a closed port (no
database is contacted) and stub the graph.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2.concept_set_refiner import ConceptSetRefiner
from src.agents.agent2.kg_expander import KGConcept
from src.settings import settings

REFINER_MARKER = "Refiner lookup failed"
FAMILY_MARKER = "KG expansion failed"

SEED = 10
ANCESTOR, SIBLING = 20, 30


@pytest.fixture
def closed_db(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://postgres:x@127.0.0.1:1/none")
    monkeypatch.setattr(settings, "CDM_SCHEMA", "synthea_cdm")


def _kg(cid, relationship):
    return KGConcept(concept_id=cid, concept_name=f"c{cid}", domain_id="Condition",
                     vocabulary_id="SNOMED", relationship=relationship)


# ── the refiner itself ───────────────────────────────────────


def test_should_raise_with_the_refiner_marker_when_a_single_count_lookup_fails(closed_db):
    with pytest.raises(Exception, match=REFINER_MARKER) as excinfo:
        ConceptSetRefiner()._get_single_descendant_count(ANCESTOR)

    assert "synthea_cdm.concept_ancestor" in str(excinfo.value)
    assert str(ANCESTOR) in str(excinfo.value)


def test_should_raise_with_the_refiner_marker_when_a_batch_count_lookup_fails(closed_db):
    with pytest.raises(Exception, match=REFINER_MARKER):
        ConceptSetRefiner()._batch_get_descendant_counts([ANCESTOR, SIBLING])


def test_should_raise_with_the_refiner_marker_when_the_subsumption_lookup_fails(closed_db):
    with pytest.raises(Exception, match=REFINER_MARKER):
        ConceptSetRefiner()._find_subsumed_ancestors([ANCESTOR], [SIBLING, SEED])


def test_should_not_let_a_condition_ancestor_keep_its_descendants_when_its_count_is_unknown(
    closed_db, monkeypatch
):
    monkeypatch.setenv("INCLUDE_DESC_SEEDS_ONLY", "1")
    monkeypatch.setenv("AGENT2_INCLUDE_DESCENDANTS_AUTO", "true")

    try:
        outcome = ConceptSetRefiner().refine(
            [SEED], [_kg(ANCESTOR, "ancestor")], "q", domain_hint="Condition"
        )
    except Exception as exc:  # the outcome under test
        outcome = exc

    assert isinstance(outcome, Exception) and REFINER_MARKER in str(outcome), (
        f"the refinement was returned as computed: {outcome}"
    )


def test_should_not_pass_every_concept_when_the_footprint_counts_are_unknown(
    closed_db, monkeypatch
):
    monkeypatch.setenv("INCLUDE_DESC_SEEDS_ONLY", "0")

    with pytest.raises(Exception, match=REFINER_MARKER):
        ConceptSetRefiner().refine([SEED], [_kg(SIBLING, "sibling")], "q", domain_hint="Condition")


def test_should_flag_a_wide_ancestor_and_keep_a_narrow_one_when_the_counts_are_read(monkeypatch):
    monkeypatch.setenv("INCLUDE_DESC_SEEDS_ONLY", "1")
    monkeypatch.setenv("AGENT2_INCLUDE_DESCENDANTS_AUTO", "true")
    refiner = ConceptSetRefiner()
    counts = {ANCESTOR: 91_661, SIBLING + 1: 200}

    with patch.object(refiner, "_get_single_descendant_count", side_effect=counts.__getitem__):
        result = refiner.refine(
            [SEED],
            [_kg(ANCESTOR, "ancestor"), _kg(SIBLING + 1, "ancestor_climb")],
            "q",
            domain_hint="Condition",
        )

    assert result.kept_ids == [SEED, ANCESTOR, SIBLING + 1]
    assert result.overbroad_ids == [ANCESTOR]
    assert result.rollback_used is False


# ── workflow: the refusal is the KG expansion's, recorded and counted once ──


class _AnchorExpander:
    """Every seed expands to the same anchors; nothing is cached anywhere."""

    def __init__(self, anchors):
        self.anchors = anchors
        self.saved = 0

    def expand(self, sid, *_a, **_k):
        return [_kg(cid, rel) for cid, rel in self.anchors]

    def save_cache(self):
        self.saved += 1


class _ChainSelectingEverything:
    """A critic chain that keeps every candidate it is shown."""

    def invoke(self, payload):
        ids = []
        for line in payload["candidates_text"].splitlines():
            head = line.split("|")[0]
            ids.append(int(head.replace("- ID:", "").strip()))
        return {
            "selected_concepts": [
                {"concept_id": cid, "relevant": True, "reasoning": "", "confidence": 1.0,
                 "potential_issue": "none", "assessment": "correct",
                 "recommended_action": "keep"}
                for cid in ids
            ],
            "overall_reasoning": "",
        }


def _critic(monkeypatch):
    from src.agents.agent2 import critic as critic_mod

    monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", "follow")
    monkeypatch.setattr(critic_mod, "_concept_rows", lambda ids: {})
    with patch.object(critic_mod, "get_llm", return_value=MagicMock()):
        instance = critic_mod.ConceptCritic()
    instance._default_chain = _ChainSelectingEverything()
    return instance


def _process(monkeypatch, anchors, *, refiner_counts=None):
    from src.agents.agent2 import workflow as wf

    monkeypatch.setenv("KG_EXPAND_MODE", "clinical_anchor")
    monkeypatch.setenv("ENABLE_REFINER", "1")
    monkeypatch.setenv("INCLUDE_DESC_SEEDS_ONLY", "1")
    monkeypatch.setenv("AGENT2_INCLUDE_DESCENDANTS_AUTO", "true")
    monkeypatch.setenv("FOOTPRINT_GUARD_IN_HYBRID", "0")
    expander = _AnchorExpander(anchors)
    monkeypatch.setattr(wf, "get_kg_expander", lambda: expander)
    critic = _critic(monkeypatch)
    monkeypatch.setattr(wf, "get_critic", lambda: critic)
    refiner = ConceptSetRefiner()
    monkeypatch.setattr(wf, "get_concept_set_refiner", lambda: refiner)
    workflow = wf.Agent2Workflow()
    workflow._query_expander = MagicMock(expand=lambda q, domain_hint=None: q)
    with patch("src.agents.agent2.workflow.expand_abbreviation", return_value=("q", False)), \
         patch("src.agents.agent2.workflow.expand_in_context", return_value="q"), \
         patch.object(wf.Agent2Workflow, "_slow_path", return_value=[SEED]), \
         patch("src.agents.agent2.workflow.logician.drop_wrong_entity_class_for_condition",
               side_effect=lambda ids: ids):
        if refiner_counts is None:
            return workflow.process_with_details("q", domain_hint="Condition")
        with patch.object(refiner, "_get_single_descendant_count",
                          side_effect=refiner_counts.__getitem__), \
             patch.object(refiner, "_find_subsumed_ancestors", return_value=set()):
            return workflow.process_with_details("q", domain_hint="Condition")


def _lines(caplog, marker):
    return [r.getMessage() for r in caplog.records if marker in r.getMessage()]


#: Three anchors: clinical_anchor mode skips the critic (<= 10).
FEW_ANCHORS = [(ANCESTOR, "ancestor"), (21, "ancestor"), (22, "ancestor")]
#: Twelve anchors: the critic runs, then the refiner over what it kept.
MANY_ANCHORS = [(ANCESTOR + i, "ancestor") for i in range(12)]


def test_should_return_seeds_only_and_record_the_refusal_when_the_refiner_lookup_fails(
    closed_db, monkeypatch, caplog
):
    caplog.set_level(logging.WARNING, logger="src.agents.agent2.workflow")

    result = _process(monkeypatch, FEW_ANCHORS)

    assert result.concept_ids == [SEED], "the unrefined expansion was kept as the result"
    assert result.overbroad_concept_ids == []
    assert REFINER_MARKER in (result.kg_expansion_failure or "")
    lines = _lines(caplog, FAMILY_MARKER)
    assert len(lines) == 1, lines
    assert REFINER_MARKER in lines[0] and "\n" not in lines[0]


def test_should_record_the_refusal_not_a_critic_failure_when_the_refiner_after_the_critic_fails(
    closed_db, monkeypatch, caplog
):
    caplog.set_level(logging.WARNING)

    result = _process(monkeypatch, MANY_ANCHORS)

    assert result.concept_ids == [SEED]
    assert REFINER_MARKER in (result.kg_expansion_failure or "")
    assert len(_lines(caplog, FAMILY_MARKER)) == 1
    assert result.critic_failure is None, "a refiner failure was recorded as the critic's"
    assert not _lines(caplog, "Critic failed") + _lines(caplog, "Critic] Evaluation failed")


def test_should_keep_the_refined_expansion_when_the_refiner_lookups_succeed(monkeypatch):
    counts = {cid: 91_661 if cid == ANCESTOR else 200 for cid, _ in FEW_ANCHORS}

    result = _process(monkeypatch, FEW_ANCHORS, refiner_counts=counts)

    assert result.concept_ids == [SEED, ANCESTOR, 21, 22]
    assert result.overbroad_concept_ids == [ANCESTOR]
    assert result.kg_expansion_failure is None


def test_should_keep_the_critic_and_refiner_selection_when_both_succeed(monkeypatch):
    counts = {cid: 200 for cid, _ in MANY_ANCHORS}

    result = _process(monkeypatch, MANY_ANCHORS, refiner_counts=counts)

    assert result.concept_ids == [SEED] + [cid for cid, _ in MANY_ANCHORS]
    assert result.kg_expansion_failure is None
