"""The export chain does not rewrite a concept set to the concept its NAME resolves to.

RFC-016 §4 (C7): ``overbroad_absence_repair`` replaced the single member of an absence
concept set with the standard concept whose ``concept_name`` equalled the set's name. A
concept-set name is model-written free text; matching it against vocabulary names is a
text rule, and the repair is deleted (an over-broad absence set is the critic's question).

The real case, copied verbatim into ``tests/fixtures/p3_structural_rows.json``
(``c7_carmelina_t1dm``): ``2026-09-18_verify`` CARMELINA codeset 14 'Type 1 diabetes
mellitus' holds 4130526 'Disorder of glucose metabolism' with descendants, read by the
absence rule #3. The vocabulary rows (synthea23m) are the three concepts involved. The
vocabularies are stubbed so that the deleted repair, were it still wired, would fire.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "p3_structural_rows.json").read_text()
)["c7_carmelina_t1dm"]
GLUCOSE_METABOLISM = 4130526
T1DM = 201254
T2DM = 201826


class _Vocabulary:
    def __init__(self, *_args: Any) -> None:
        pass

    def __enter__(self) -> "_Vocabulary":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def prefetch(self, _items: Any) -> Any:
        from src.services.conceptset_closure import PrefetchedVocabulary

        ids = [GLUCOSE_METABOLISM, T1DM, T2DM]
        return PrefetchedVocabulary(
            concept_invalid_reason={cid: None for cid in ids},
            ancestor_edges={GLUCOSE_METABOLISM: set(ids), T1DM: {T1DM}, T2DM: {T2DM}},
        )


class _Catalog(_Vocabulary):
    """Concept rows by id and by exact name -- what the deleted repair asked for."""

    def _records(self) -> list[Any]:
        from src.services.overbroad_absence_repair import ConceptRecord

        return [ConceptRecord(*row) for row in FIXTURE["vocabulary_concepts"]["rows"]]

    def concepts_by_id(self, concept_ids: Any) -> dict[int, Any]:
        wanted = set(concept_ids)
        return {r.concept_id: r for r in self._records() if r.concept_id in wanted}

    def standard_concepts_by_name(self, names: Any) -> dict[str, list[Any]]:
        wanted = {" ".join(str(n).split()).lower() for n in names}
        out: dict[str, list[Any]] = {}
        for record in self._records():
            key = " ".join(record.concept_name.split()).lower()
            if key in wanted:
                out.setdefault(key, []).append(record)
        return out


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch):
    from src.services import conceptset_closure, overbroad_absence_repair
    from src.services.tte_service import TTEService

    monkeypatch.setattr(conceptset_closure, "PostgresVocabulary", _Vocabulary)
    monkeypatch.setattr(overbroad_absence_repair, "PostgresConceptCatalog", _Catalog)
    svc = TTEService.__new__(TTEService)
    for name in (
        "_repair_entry_excluded_by_own_rule",
        "_repair_range_disjunctions",
        "_repair_restated_absences",
        "_repair_confusable_concept_set_members",
        "_repair_presence_unit_filters",
    ):
        monkeypatch.setattr(svc, name, lambda *_a, **_k: None)
    return svc


def test_should_keep_the_absence_set_member_when_the_set_name_names_a_descendant(service):
    base = {
        "ConceptSets": [deepcopy(FIXTURE["concept_set_14"])],
        "PrimaryCriteria": {"CriteriaList": []},
        "InclusionRules": [deepcopy(FIXTURE["rule_3"])],
    }

    service._export_repair_chain(base)

    members = [i["concept"]["CONCEPT_ID"] for i in base["ConceptSets"][0]["expression"]["items"]]
    assert members == [GLUCOSE_METABOLISM]
