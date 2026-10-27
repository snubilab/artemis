from copy import deepcopy
from unittest.mock import MagicMock

from src.api.models.tte import CriterionMappingMetadata
from src.services.tte_service import TTEService


def _expression(*ids):
    return {"items": [{"concept": {"CONCEPT_ID": cid}, "includeDescendants": True,
                       "isExcluded": False, "includeMapped": False} for cid in ids]}


def _service():
    from src.services.conceptset_closure import PrefetchedVocabulary
    svc = TTEService(store=MagicMock())
    svc._vocabulary_lookup = MagicMock(return_value=PrefetchedVocabulary(
        {1448778: None, 1448827: None}, {}))
    return svc


def _pairs():
    return [(dict(id=i, groupId="g", protocolLine="shared source", sourceText=label,
                  domain="Condition"),
             dict(conceptSet=dict(id=i, name=label, expression=_expression(1448778)),
                  rule={}, _mapping_metadata=CriterionMappingMetadata()), "exclusion")
            for i, label in [(1, "Alcohol Use Disorder"), (2, "Substance Use Disorder")]]


def test_should_retry_each_sibling_once_when_same_line_sets_are_identical():
    svc = _service()
    pairs = _pairs()
    svc._rerank_sibling_mapping = MagicMock(
        side_effect=[{"name": "alcohol"}, {"name": "substance"}]
    )
    svc._build_seeded_eligibility_rule = MagicMock(side_effect=[
        {**deepcopy(pairs[0][1]), "conceptSet": {"expression": _expression(1448827)}},
        deepcopy(pairs[1][1]),
    ])
    svc._repair_sibling_aliases(pairs, {})
    assert svc._rerank_sibling_mapping.call_count == 2
    assert svc._rerank_sibling_mapping.call_args_list[0].args[1] == ["Substance Use Disorder"]
    assert svc._rerank_sibling_mapping.call_args_list[1].args[1] == ["Alcohol Use Disorder"]
    assert pairs[0][1]["conceptSet"]["expression"] == _expression(1448827)


def test_should_keep_both_sets_when_sibling_retry_refuses():
    svc = _service()
    pairs = _pairs()
    original = deepcopy(pairs)
    svc._rerank_sibling_mapping = MagicMock(side_effect=RuntimeError("refused"))
    svc._repair_sibling_aliases(pairs, {})
    assert pairs == original
    assert svc._rerank_sibling_mapping.call_count == 2


def test_should_skip_retry_when_identical_sets_come_from_different_lines():
    svc = _service()
    pairs = _pairs()
    pairs[1][0]["protocolLine"] = "other source"
    svc._rerank_sibling_mapping = MagicMock()
    svc._repair_sibling_aliases(pairs, {})
    svc._rerank_sibling_mapping.assert_not_called()


def test_should_keep_gate_failure_when_rollup_collision_has_no_sibling_retry():
    from src.services.conceptset_closure import PrefetchedVocabulary
    svc = _service()
    svc._vocabulary_lookup.return_value = PrefetchedVocabulary(
        {1448778: None, 1448827: None}, {1448778: {1448827}}
    )
    pairs = _pairs()
    pairs[0][1]["_mapping_metadata"].rollupExpression = _expression(1448778)
    pairs[0][1]["_mapping_metadata"].preRollupExpression = _expression(1448778, 1448827)
    pairs[1][0]["protocolLine"] = "other source"
    svc._repair_sibling_aliases(pairs, {})
    assert pairs[0][1]["conceptSet"]["expression"] == _expression(1448778)


def test_should_keep_original_failure_when_retry_changes_ids_but_not_closure():
    from src.services.conceptset_closure import PrefetchedVocabulary
    svc = _service()
    pairs = _pairs()
    original = deepcopy(pairs)
    svc._vocabulary_lookup.return_value = PrefetchedVocabulary(
        {1448778: None, 1448827: None}, {1448778: {1448827}})
    svc._rerank_sibling_mapping = MagicMock(return_value={})
    svc._build_seeded_eligibility_rule = MagicMock(side_effect=[
        {**deepcopy(pairs[0][1]), "conceptSet": {"expression": _expression(1448778, 1448827)}},
        deepcopy(pairs[1][1]),
    ])
    svc._repair_sibling_aliases(pairs, {})
    assert pairs == original


def test_should_preserve_final_subtraction_when_pre_rollup_items_are_available():
    svc = _service()
    pairs = _pairs()
    metadata = pairs[0][1]["_mapping_metadata"]
    metadata.rollupExpression = _expression(1448778)
    metadata.preRollupExpression = _expression(1448778, 1448827)
    pairs[0][1]["conceptSet"]["expression"]["items"][0]["includeDescendants"] = False
    pairs[1][0]["protocolLine"] = "other source"
    before = deepcopy(pairs)
    svc._repair_sibling_aliases(pairs, {})
    assert pairs == before


def test_should_forward_sibling_context_when_retry_uses_shared_mapper():
    svc = _service()
    row = _pairs()[0][0]
    svc._recommend_seeded_concept_set = MagicMock(return_value={"expression": _expression(1448827)})
    result = svc._rerank_sibling_mapping(row, ["Substance Use Disorder"], ["candidates"])
    assert result["expression"] == _expression(1448827)
    kwargs = svc._recommend_seeded_concept_set.call_args.kwargs
    assert kwargs["sibling_labels"] == ["Substance Use Disorder"]
    assert kwargs["pre_fetched_candidates"] == ["candidates"]
    assert kwargs["source_line"] == "shared source"
