"""A stated exception on the real A2 rows: when its base set is kept, and when the row is refused.

Pinned to the A2 dry rebuild (`output/site_gap/2026-10-14_a2_dry`, code be78c16) through
`tests/fixtures/a2_exception_unit_rows.json.gz`, which records each source file by sha256:

* ``a2Sets`` -- what A2 delivered for the row. On a row whose exception was applied, its
  non-excluded items are the base phrase's mapping and its ``isExcluded`` items the excepted
  phrases'; on a row whose exception was NOT applied it is the whole set the fallback mapped.
* ``candidateSets`` -- what the delivery candidate (code d7dc2bb) delivered for the same row,
  mapped on the row's own entity text. It stands in for the own-seed mapping, which A2 never
  made (its seed was the base span).
* ``vocabulary`` -- the CONCEPT / CONCEPT_ANCESTOR facts those sets' closures need.

Only the per-phrase mapper is stubbed; the decisions run as written. No LLM, embedding or DB.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.services.conceptset_closure import PrefetchedVocabulary
from src.utils.criterion_refusal import CriterionRefused
from src.utils.criterion_seed import criterion_mapper_seed

FIXTURE = Path(__file__).parent / "fixtures" / "a2_exception_unit_rows.json.gz"


@pytest.fixture(scope="module")
def fx():
    return json.loads(gzip.open(FIXTURE).read())


def _row(fx, trial, role, cid):
    return next(
        r for r in fx["rows"] if (r["trial"], r["role"], r["criterionId"]) == (trial, role, cid)
    )


def _lookup(fx) -> PrefetchedVocabulary:
    v = fx["vocabulary"]
    return PrefetchedVocabulary(
        {int(k): x for k, x in v["concept_invalid_reason"].items()},
        {int(k): set(x) for k, x in v["ancestor_edges"].items()},
        {int(k): set(x) for k, x in v["maps_to_edges"].items()},
        {int(k): set(x) for k, x in v["replacement_edges"].items()},
    )


def _mapping(name, items):
    return {
        "name": name,
        "domain": None,
        "expression": {"items": [dict(i) for i in items]},
        "mapping_metadata": None,
    }


def _included(items):
    return [{**i, "isExcluded": False} for i in items if not i.get("isExcluded")]


def _excluded_as_mapped(items):
    return [{**i, "isExcluded": False} for i in items if i.get("isExcluded")]


class _NoWholePhraseWorkflow:
    """Agent 2 for the whole-phrase fallback: it must not be reached on a stated exception."""

    def process_with_details(self, seed, **_kwargs):
        raise AssertionError(f"the whole phrase {seed!r} reached Agent 2")


def _service(fx, table, fallback=None):
    """A TTEService mapping each phrase from ``table``, over the fixture's vocabulary.

    ``fallback`` is what the RAG fallback returns for the whole phrase -- what A2 emitted when
    its exception was not applied.
    """
    from src.services.tte_service import TTEService

    lookup = _lookup(fx)

    class _Stubbed(TTEService):
        def _recommend_seeded_concept_set(self, seed_text, **kwargs):
            if kwargs.get("resolving_entity_exception"):
                self.calls.append(seed_text)
                if seed_text not in table:
                    raise CriterionRefused(
                        f"No concept selected for {seed_text!r}", code="reranker-no-match"
                    )
                return _mapping(seed_text, table[seed_text])
            return super()._recommend_seeded_concept_set(seed_text, **kwargs)

        def _exact_ingredient_match_enabled(self):
            return False

        def _recommend_seeded_concept_set_rag_fallback(self, seed, **_kwargs):
            if fallback is None:
                raise AssertionError(f"RAG fallback reached for {seed!r}")
            self.calls.append(f"fallback:{seed}")
            return _mapping(seed, fallback)

        def _vocabulary_lookup(self, items):
            return lookup

    svc = _Stubbed(store=MagicMock())
    svc.calls = []
    return svc


def _map_row(svc, row):
    from src.services.tte_service import TTEService

    seed = criterion_mapper_seed(row)
    return svc._recommend_seeded_concept_set(
        seed,
        expected_domain=row.get("domain"),
        workflow=_NoWholePhraseWorkflow(),
        entity_exception=TTEService._stated_entity_exception(row, seed),
    )


@pytest.fixture(autouse=True)
def _no_criterion_cache(monkeypatch):
    monkeypatch.setenv("CRITERION_CACHE_ENABLED", "false")


def _ids(items, excluded):
    return sorted(
        i["concept"]["CONCEPT_ID"] for i in items if bool(i.get("isExcluded")) == excluded
    )


# --- item 2: the base span's set is kept only when it shares a concept with the row's own --------


@pytest.mark.parametrize("cid", [3, 4])
def test_should_map_the_row_on_its_own_entity_when_the_base_set_shares_no_concept_with_it(fx, cid):
    """ARISTOTLE exclusion 3 (AST) and 4 (total bilirubin): A2 seeded both on the base span 'an
    alternative causative factor' and delivered LOINC 'Risk adjustment factor' / 'Confounding
    factors' minus Gilbert's syndrome. That closure shares no concept with the lab the row names."""
    case = _row(fx, "aristotle", "exclusion", cid)
    row, a2, own = case["row"], case["a2Sets"][0]["items"], case["candidateSets"][0]["items"]
    svc = _service(
        fx,
        {
            criterion_mapper_seed(row): _included(a2),
            "Gilbert’s syndrome": _excluded_as_mapped(a2),
            row["sourceText"]: own,
        },
    )
    result = _map_row(svc, row)
    assert _ids(result["expression"]["items"], excluded=False) == _ids(own, excluded=False)
    assert _ids(result["expression"]["items"], excluded=True) == []
    dropped = result["mapping_metadata"].exceptionDropped
    assert "an alternative causative factor" in dropped and "no concept" in dropped


@pytest.mark.parametrize(
    "trial,cid",
    [
        ("empa-reg", 19),  # 'Malignant neoplasm' under 'cancer (except for basal cell carcinoma)'
        ("empa-reg", 30),  # 'Endocrine disorder' minus type 2 diabetes
        ("carolina", 14),  # 'open bariatric surgery' under the bariatric base span
        ("carolina", 18),  # 'Systemic corticosteroid' minus inhaled use
        ("leader", 17),  # 'peripheral artery revascularization' minus coronary and carotid
    ],
)
def test_should_keep_the_exception_when_the_base_set_overlaps_the_row_s_own(fx, trial, cid):
    """The correct exceptions A2 applied (overfill classification: EMPA-REG 19/30, CAROLINA 18) and
    the other rows whose base span shares concepts with the row's own set keep A2's set exactly."""
    case = _row(fx, trial, "exclusion", cid)
    row, a2, own = case["row"], case["a2Sets"][0]["items"], case["candidateSets"][0]["items"]
    from src.services.criterion_annotation import stated_exceptions

    excepted = [e["text"] for e in stated_exceptions(row)]
    table = {criterion_mapper_seed(row): _included(a2), row["sourceText"]: _included(own)}
    # Each excepted phrase maps to A2's excluded items; the union is what A2 subtracted.
    for phrase in excepted:
        table[phrase] = _excluded_as_mapped(a2)
    svc = _service(fx, table)
    result = _map_row(svc, row)
    assert _ids(result["expression"]["items"], excluded=False) == _ids(a2, excluded=False)
    assert _ids(result["expression"]["items"], excluded=True) == _ids(a2, excluded=True)
    assert getattr(result["mapping_metadata"], "exceptionDropped", None) is None


def test_should_not_map_the_own_seed_when_it_is_the_base_itself(fx):
    """No extra mapper call when the seed IS the row's own text (no base span replaced it)."""
    from src.services.entity_subtraction import EntityException

    case = _row(fx, "empa-reg", "exclusion", 19)
    a2 = case["a2Sets"][0]["items"]
    svc = _service(fx, {"cancer": _included(a2), "basal cell carcinoma": _excluded_as_mapped(a2)})
    svc._recommend_seeded_concept_set(
        "cancer",
        expected_domain="Condition",
        workflow=_NoWholePhraseWorkflow(),
        entity_exception=EntityException(
            text="cancer", base="cancer", excepted=["basal cell carcinoma"], own="cancer"
        ),
    )
    assert svc.calls == ["cancer", "basal cell carcinoma"]


# --- item 3: an exception that cannot be applied refuses the row ------------------------------


def test_should_refuse_the_row_when_every_member_of_its_base_is_excepted(fx):
    """LEADER exclusion 40: the excepted union (human NPH, long-acting analogue, premixed)
    covers all 29 insulins 'insulin' mapped to, so the guard cannot subtract. A2 shipped the
    whole 29-insulin set
    -- forbidding the insulins the protocol allows."""
    case = _row(fx, "leader", "exclusion", 40)
    row, a2 = case["row"], case["a2Sets"][0]["items"]
    nph = _row(fx, "leader", "inclusion", 15)["candidateSets"][0]["items"]
    long_acting = _excluded_as_mapped(case["candidateSets"][0]["items"])
    premixed = _excluded_as_mapped(_row(fx, "leader", "exclusion", 41)["candidateSets"][0]["items"])
    svc = _service(
        fx,
        {
            "insulin": a2,
            "human NPH insulin": nph,
            "long-acting insulin analogue": long_acting,
            "premixed insulin": premixed,
            # The row's own phrase mapped whole: the tail-dominated NPH set of 2026-09-14.
            row["sourceText"]: nph,
        },
        fallback=a2,
    )
    with pytest.raises(CriterionRefused) as refused:
        _map_row(svc, row)
    assert refused.value.code == "exception-not-applied"
    assert "subtracting would empty the concept set" in str(refused.value)
    assert not any(c.startswith("fallback:") for c in svc.calls)


def test_should_refuse_the_row_when_an_excepted_phrase_does_not_map(fx):
    """CAROLINA exclusion 68: 'non-melanoma skin cancer' was refused by the reranker, and A2 shipped
    the whole 'cancer' set -- an exclusion of every cancer, the excepted ones included."""
    case = _row(fx, "carolina", "exclusion", 68)
    row, a2 = case["row"], case["a2Sets"][0]["items"]
    svc = _service(fx, {"cancer": a2, row["sourceText"]: a2}, fallback=a2)
    with pytest.raises(CriterionRefused) as refused:
        _map_row(svc, row)
    assert refused.value.code == "exception-not-applied"
    assert "non-melanoma skin cancer" in str(refused.value)
