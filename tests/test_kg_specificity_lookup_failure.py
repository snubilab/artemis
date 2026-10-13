"""A failed KG lookup refuses that query's expansion; it is never cached or stored as a result.

The IC specificity filter in ``ancestor_climb`` reads descendant counts from PostgreSQL.
When that read failed, the counts came back empty, every ancestor scored the leaf IC
(20.0), every ancestor passed the filter, and the over-wide expansion was written to the
persistent KG cache. These tests point the count database at a closed port (no DB is
contacted) and stub Neo4j.
"""

import hashlib
import json
import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2 import kg_expander
from src.agents.agent2.kg_expander import KGConcept, KGExpander

LOOKUP_MARKER = "KG specificity lookup failed"
FAMILY_MARKER = "KG expansion failed"

SEED, SPECIFIC, BROAD = 10, 1, 2
# Real counts: seed IC 9.8 (static threshold 8.0 holds), SPECIFIC IC 13.7 passes,
# BROAD IC 4.9 fails.
REAL_COUNTS = {SPECIFIC: 200, BROAD: 91_661, SEED: 3_000}


@pytest.fixture
def closed_db(monkeypatch):
    monkeypatch.setenv("OMOP_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("OMOP_DB_PORT", "1")
    monkeypatch.setenv("CDM_SCHEMA", "synthea_cdm")


@pytest.fixture
def cache_file(monkeypatch, tmp_path):
    path = tmp_path / "kg_cache.json"
    monkeypatch.setattr(kg_expander, "KG_CACHE_FILE", path)
    return path


@pytest.fixture
def expander(cache_file):
    exp = KGExpander.__new__(KGExpander)
    exp._driver = MagicMock()
    exp._use_cache = True
    exp._cache = {}
    exp._cache_lock = threading.Lock()
    return exp


def _records(*rows):
    result = MagicMock()
    result.__iter__.return_value = list(rows)
    return result


def _ancestor(cid, sep):
    return {"cid": str(cid), "name": f"c{cid}", "domain": "Condition", "vocab": "SNOMED",
            "cclass": "Disorder", "sep": sep}


def _concept(cid):
    return {"cid": str(cid), "name": f"c{cid}", "domain": "Condition", "vocab": "SNOMED",
            "cclass": "Disorder"}


def _neo4j(expander, *results):
    session = MagicMock()
    session.run.side_effect = list(results)
    expander._driver.session.return_value.__enter__.return_value = session


def _clinical_anchor_graph(expander):
    """get_ancestors, then the climb's up query, then one down query per admitted ancestor."""
    _neo4j(
        expander,
        _records(_ancestor(SPECIFIC, 1), _ancestor(BROAD, 2)),
        _records(_ancestor(SPECIFIC, 1), _ancestor(BROAD, 2)),
        _records(_concept(11)),
        _records(_concept(21)),
    )


def _expand_clinical_anchor(expander):
    with patch.object(expander, "get_siblings", return_value=[]), \
         patch.object(expander, "get_maps_to", return_value=[]):
        try:
            return expander.expand(SEED, "clinical_anchor", 3, 50, "Condition")
        except Exception as exc:  # the outcome under test, inspected by the caller
            return exc


# ── kg_expander ──────────────────────────────────────────────


def test_should_raise_with_the_lookup_marker_when_the_count_database_is_unreachable(
    closed_db, expander
):
    with pytest.raises(Exception, match=LOOKUP_MARKER):
        expander._get_pg_descendant_counts([SPECIFIC, BROAD])


def test_should_refuse_the_climb_when_the_specificity_lookup_fails(closed_db, expander):
    _neo4j(expander, _records(_ancestor(SPECIFIC, 1), _ancestor(BROAD, 2)),
           _records(_concept(11)), _records(_concept(21)))

    with pytest.raises(Exception, match=LOOKUP_MARKER):
        expander.ancestor_climb(SEED, domain_filter="Condition", limit=40)


def test_should_not_write_the_expansion_to_the_cache_when_the_specificity_lookup_fails(
    closed_db, expander, cache_file
):
    _clinical_anchor_graph(expander)

    outcome = _expand_clinical_anchor(expander)
    expander.save_cache()

    saved = json.loads(cache_file.read_text())
    assert saved == {}, f"a failed lookup was cached: {saved}"
    assert isinstance(outcome, Exception) and LOOKUP_MARKER in str(outcome), outcome


def test_should_cache_the_expansion_when_the_specificity_lookup_succeeds(
    closed_db, expander, cache_file
):
    _neo4j(
        expander,
        _records(_ancestor(SPECIFIC, 1), _ancestor(BROAD, 2)),
        _records(_ancestor(SPECIFIC, 1), _ancestor(BROAD, 2)),
        _records(_concept(11)),
    )

    with patch.object(expander, "_get_pg_descendant_counts", return_value=dict(REAL_COUNTS)):
        out = _expand_clinical_anchor(expander)
    expander.save_cache()

    assert not isinstance(out, Exception), out
    climbed = [c for c in out if c.relationship.startswith("ancestor_climb")]
    assert [(c.concept_id, c.via_concept_id) for c in climbed] == [(11, SPECIFIC)]
    saved = json.loads(cache_file.read_text())
    assert len(saved) == 1
    assert {e["concept_id"] for e in next(iter(saved.values()))} == {SPECIFIC, BROAD, 11}


def test_should_key_the_cache_on_the_cdm_schema_the_counts_come_from(monkeypatch):
    monkeypatch.setenv("CDM_SCHEMA", "synthea_cdm")
    a = KGExpander._cache_key(SEED, "clinical_anchor", 3, 50, "Condition")
    monkeypatch.setenv("CDM_SCHEMA", "synthea23m")
    b = KGExpander._cache_key(SEED, "clinical_anchor", 3, 50, "Condition")

    assert a != b


def test_should_miss_an_entry_cached_before_the_key_carried_the_schema(
    monkeypatch, expander
):
    monkeypatch.setenv("CDM_SCHEMA", "synthea_cdm")
    raw = f"{SEED}|clinical_anchor|3|50|Condition|{kg_expander.KG_CACHE_SCHEMA}"
    old_key = hashlib.sha256(raw.encode()).hexdigest()[:16]
    expander._cache = {old_key: [{"concept_id": 99, "concept_name": "stale",
                                  "domain_id": "Condition", "vocabulary_id": "SNOMED"}]}

    with patch.object(expander, "get_ancestors", return_value=[]), \
         patch.object(expander, "get_siblings", return_value=[]), \
         patch.object(expander, "get_maps_to", return_value=[]), \
         patch.object(expander, "ancestor_climb", return_value=[]):
        out = expander.expand(SEED, "clinical_anchor", 3, 50, "Condition")

    assert out == []


def test_should_refuse_to_start_when_the_graph_has_no_concepts():
    driver = MagicMock()
    session = driver.session.return_value.__enter__.return_value
    session.run.return_value.single.return_value = None

    with patch("src.agents.agent2.kg_expander.GraphDatabase.driver", return_value=driver):
        with pytest.raises(RuntimeError, match="no Concept nodes"):
            KGExpander(use_cache=False)


# ── workflow: the query's expansion is refused, recorded, and counted ──


class _FailingExpander:
    """Seed 10 fails its lookup (a two-line message, as psycopg2 gives); seed 11 expands."""

    def expand(self, sid, *_a, **_k):
        if sid == SEED:
            raise RuntimeError(f"{LOOKUP_MARKER} for [1, 2, 10]: refused\n\tline two")
        return [KGConcept(concept_id=31, concept_name="c31", domain_id="Condition",
                          vocabulary_id="SNOMED", relationship="maps_to")]

    def save_cache(self):
        pass


def _process(monkeypatch, get_kg_expander):
    from src.agents.agent2 import workflow as wf

    monkeypatch.setenv("KG_EXPAND_MODE", "clinical_anchor")
    monkeypatch.setenv("ENABLE_REFINER", "0")
    monkeypatch.setattr(wf, "get_kg_expander", get_kg_expander)
    workflow = wf.Agent2Workflow()
    with patch("src.agents.agent2.workflow.expand_abbreviation", return_value=("q", False)), \
         patch("src.agents.agent2.workflow.expand_in_context", return_value="q"), \
         patch.object(wf.Agent2Workflow, "_slow_path", return_value=[SEED, 11]), \
         patch("src.agents.agent2.workflow.logician.drop_wrong_entity_class_for_condition",
               side_effect=lambda ids: ids):
        return workflow.process_with_details("q", domain_hint="Condition")


def _family_lines(caplog):
    return [r.getMessage() for r in caplog.records if FAMILY_MARKER in r.getMessage()]


def test_should_return_seeds_only_and_record_the_failure_when_one_seed_lookup_fails(
    monkeypatch, caplog
):
    caplog.set_level(logging.WARNING, logger="src.agents.agent2.workflow")

    result = _process(monkeypatch, lambda: _FailingExpander())

    assert result.concept_ids == [SEED, 11], "a partial expansion was kept as the result"
    assert LOOKUP_MARKER in (result.kg_expansion_failure or "")
    lines = _family_lines(caplog)
    assert len(lines) == 1, lines
    assert LOOKUP_MARKER in lines[0] and "\n" not in lines[0]


def test_should_record_the_failure_when_neo4j_is_unreachable(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="src.agents.agent2.workflow")

    def _unreachable():
        raise RuntimeError("[KG Expander] Neo4j is not reachable at bolt://127.0.0.1:1")

    result = _process(monkeypatch, _unreachable)

    assert result.concept_ids == [SEED, 11]
    assert "Neo4j is not reachable" in (result.kg_expansion_failure or "")
    assert len(_family_lines(caplog)) == 1


def test_should_leave_the_failure_unset_when_expansion_succeeds(monkeypatch):
    class _Ok(_FailingExpander):
        def expand(self, sid, *_a, **_k):
            return []

    result = _process(monkeypatch, lambda: _Ok())

    assert result.kg_expansion_failure is None


# ── criterion cache: a refused expansion is not stored as a mapping ──


def _recommend(mapping_result):
    import os

    from src.agents.agent2.criterion_cache import CriterionResultCache
    from src.services import tte_service

    cache = CriterionResultCache(max_entries=10, ttl_hours=1)
    rec = MagicMock()
    rec.name = "set"
    rec.expression.to_atlas_json.return_value = {"items": [{
        "concept": {"CONCEPT_ID": SEED, "CONCEPT_NAME": "c10", "DOMAIN_ID": "Condition"},
        "isExcluded": False, "includeDescendants": True, "includeMapped": False,
    }]}
    candidate = MagicMock(concept_id=SEED, concept_name="c10", domain_id="Condition",
                          vocabulary_id="SNOMED", concept_class_id="Disorder")
    # tte_service binds get_criterion_cache at import, so the patch goes on its name.
    with patch.object(tte_service, "get_criterion_cache", return_value=cache), \
         patch("src.agents.agent2.workflow.Agent2Workflow.process_with_details",
               return_value=mapping_result), \
         patch("src.services.tte_service.TTEService._fetch_concept_candidates",
               return_value=[candidate]), \
         patch("src.agents.conceptset.expression_builder.get_expression_builder") as builder, \
         patch("src.services.tte_service.TTEService._resolve_seeded_domain",
               return_value="Condition"), \
         patch.dict(os.environ, {"CRITERION_CACHE_ENABLED": "true"}):
        builder.return_value.build_expression.return_value = rec
        out = tte_service.TTEService(store=MagicMock())._recommend_seeded_concept_set(
            "History of Stroke", expected_domain="Condition"
        )
    return out, cache


def test_should_not_store_a_mapping_in_the_criterion_cache_when_its_kg_expansion_failed():
    from src.models.ir import MappingResult

    out, cache = _recommend(MappingResult(
        concept_ids=[SEED], route_path="slow",
        kg_expansion_failure=f"{LOOKUP_MARKER} for [1]: refused",
    ))

    assert out["name"] == "set"
    assert cache.stats()["current_size"] == 0


def test_should_store_a_mapping_in_the_criterion_cache_when_its_kg_expansion_succeeded():
    from src.models.ir import MappingResult

    _, cache = _recommend(MappingResult(concept_ids=[SEED], route_path="slow"))

    assert cache.stats()["current_size"] == 1
