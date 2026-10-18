"""An exception whose subtraction would empty the base: refused, or a row's own entity mapped.

Pinned to real store rows through `tests/fixtures/exception_not_anchored_rows.json`, which
records each source store by sha256 (P6 SEG-OFF, 2026-10-17; P6 MAIN, 2026-10-13).

The subtraction guard (`entity_subtraction.apply_entity_subtraction`) refuses when the excepted
set covers every included member of the base. Two different things produce that:

* a real exception whose phrases mapped too broadly -- LEADER exclusion 40, 'insulin other than
  human NPH insulin or long-acting insulin analogue or premixed insulin': the annotation is right,
  'human NPH insulin' mapped to all 29 insulins. Refusing is the honest outcome.
* an "exception" that names the row's own entity -- CARMELINA exclusion 32 excepts
  'Percutaneous Coronary Intervention' from a PCI row, PLATO exclusion 55 excepts 'Acute Coronary
  Syndrome' from an ACS row. The protocol line names no set apart from what it excepts: the
  excepted span sits inside the base span (CARMELINA) or no base span verified at all (PLATO).

The second is read off the positions of the verified spans in the line, never off their words.
Only the per-phrase mapper is stubbed; concept ids are placeholders.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.services.conceptset_closure import PrefetchedVocabulary
from src.utils.criterion_refusal import CriterionRefused
from src.utils.criterion_seed import criterion_mapper_seed

FIXTURE = Path(__file__).parent / "fixtures" / "exception_not_anchored_rows.json"


@pytest.fixture(scope="module")
def fx():
    return json.loads(FIXTURE.read_text())


def _row(fx, arm, trial, cid):
    return next(
        r["row"]
        for r in fx["rows"]
        if (r["arm"], r["trial"], r["criterionId"]) == (arm, trial, cid)
    )


def _items(*ids):
    return [
        {"concept": {"CONCEPT_ID": i, "CONCEPT_NAME": f"c{i}"}, "isExcluded": False,
         "includeDescendants": True}
        for i in ids
    ]


def _service(table):
    from src.services.tte_service import TTEService

    ids = {i["concept"]["CONCEPT_ID"] for items in table.values() for i in items}
    lookup = PrefetchedVocabulary({i: None for i in ids}, {}, {}, {})

    class _Stubbed(TTEService):
        def _recommend_seeded_concept_set(self, seed_text, **kwargs):
            if kwargs.get("resolving_entity_exception"):
                self.calls.append(seed_text)
                if seed_text not in table:
                    raise CriterionRefused(f"No concept for {seed_text!r}", code="reranker-no-match")
                return {"name": seed_text, "domain": None, "mapping_metadata": None,
                        "expression": {"items": [dict(i) for i in table[seed_text]]}}
            return super()._recommend_seeded_concept_set(seed_text, **kwargs)

        def _exact_ingredient_match_enabled(self):
            return False

        def _recommend_seeded_concept_set_rag_fallback(self, seed, **_kwargs):
            raise AssertionError(f"the whole phrase {seed!r} reached the fallback")

        def _vocabulary_lookup(self, items):
            return lookup

    svc = _Stubbed(store=MagicMock())
    svc.calls = []
    return svc


def _map(svc, row):
    from src.services.tte_service import TTEService

    seed = criterion_mapper_seed(row)
    return svc._recommend_seeded_concept_set(
        seed,
        expected_domain=row.get("domain"),
        entity_exception=TTEService._stated_entity_exception(row, seed),
    )


def _included(result):
    return sorted(
        i["concept"]["CONCEPT_ID"] for i in result["expression"]["items"] if not i.get("isExcluded")
    )


@pytest.fixture(autouse=True)
def _no_criterion_cache(monkeypatch):
    monkeypatch.setenv("CRITERION_CACHE_ENABLED", "false")


def test_should_map_the_own_entity_when_the_excepted_span_lies_inside_the_base_span(fx):
    """CARMELINA exclusion 32: excepted 'PCI' sits inside the base span, so the line names no set
    apart from what it excepts. P6 SEG-OFF refused the row (exception-not-applied) and lost it."""
    row = _row(fx, "segoff", "carmelina", 32)
    base = criterion_mapper_seed(row)
    svc = _service({base: _items(1), row["sourceText"]: _items(1),
                    "Percutaneous Coronary Intervention": _items(1)})
    result = _map(svc, row)
    assert _included(result) == [1]
    assert "Percutaneous Coronary Intervention" in result["mapping_metadata"].exceptionDropped


def test_should_map_the_own_entity_when_no_base_span_verified(fx):
    """PLATO exclusion 55: the base span came back null, so the exception is anchored to no set in
    the line; its excepted entity is the row's own. P6 SEG-OFF refused the row."""
    row = _row(fx, "segoff", "plato", 55)
    svc = _service({"Acute Coronary Syndrome": _items(2)})
    result = _map(svc, row)
    assert _included(result) == [2]
    assert result["mapping_metadata"].exceptionDropped


def test_should_still_refuse_when_the_exception_is_anchored_and_covers_the_base(fx):
    """LEADER exclusion 40 (must not regress to shipping all insulins): its base span 'insulin' is
    verified and holds no excepted span, so the covering mapping is the excepted phrases' fault."""
    row = _row(fx, "segoff", "leader", 40)
    svc = _service({"insulin": _items(10, 11, 12), "human NPH insulin": _items(10, 11, 12),
                    "long-acting insulin analogue": _items(11), "premixed insulin": _items(12)})
    with pytest.raises(CriterionRefused) as refused:
        _map(svc, row)
    assert refused.value.code == "exception-not-applied"


def test_should_still_refuse_when_the_row_has_no_entity_text_of_its_own(fx):
    """P6 MAIN LEADER exclusion 4: unanchored (excepted spans inside the base span), but the row's
    entity text is empty -- the only text left to map is the whole exception clause."""
    row = _row(fx, "main", "leader", 4)
    base = criterion_mapper_seed(row)
    svc = _service({base: _items(10, 11, 12), "human NPH insulin": _items(10, 11, 12),
                    "long-acting insulin analogue": _items(11), "premixed insulin": _items(12),
                    row["description"]: _items(10)})
    with pytest.raises(CriterionRefused) as refused:
        _map(svc, row)
    assert refused.value.code == "exception-not-applied"


def test_should_apply_an_unanchored_exception_whose_subtraction_succeeds(fx):
    """ARISTOTLE exclusion 6 'Conditions other than atrial fibrillation that require chronic
    anticoagulation': excepted span inside the base span, but the subtraction applies -- unchanged."""
    row = _row(fx, "segoff", "aristotle", 6)
    base = criterion_mapper_seed(row)
    svc = _service({base: _items(3, 4), "atrial fibrillation": _items(5),
                    row["description"]: _items(3)})
    result = _map(svc, row)
    assert _included(result) == [3, 4]
    assert [i["concept"]["CONCEPT_ID"] for i in result["expression"]["items"] if i["isExcluded"]] == [5]
