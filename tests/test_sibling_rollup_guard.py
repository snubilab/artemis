from src.agents.conceptset.expression_builder import ExpressionBuilder
from src.agents.conceptset.rag_search import ConceptCandidate


def _candidate(concept_id):
    return ConceptCandidate(concept_id=concept_id, concept_name=str(concept_id))


def _builder(monkeypatch):
    builder = ExpressionBuilder()
    monkeypatch.setattr(builder, '_validate_standard_concepts', lambda candidates: candidates)
    def roll_up(candidates, seed_concept_ids=None, unrolled_candidates=None):
        unrolled_candidates.extend(candidates)
        return candidates[:1]

    monkeypatch.setattr(builder, '_roll_up', roll_up)
    return builder


def test_should_keep_pre_rollup_items_when_rolled_set_matches_sibling(monkeypatch):
    builder = _builder(monkeypatch)
    sibling = builder.build_expression([_candidate(1)]).expression
    result = builder.build_expression([_candidate(1), _candidate(2)], sibling_expressions=[sibling])
    assert [item.concept_id for item in result.expression.items] == [1, 2]
    assert [item.concept_id for item in result.pre_rollup_expression.items] == [1, 2]
    assert all(item.includeDescendants for item in result.expression.items)


def test_should_roll_up_when_result_differs_from_sibling(monkeypatch):
    builder = _builder(monkeypatch)
    sibling = builder.build_expression([_candidate(3)]).expression
    result = builder.build_expression([_candidate(1), _candidate(2)], sibling_expressions=[sibling])
    assert [item.concept_id for item in result.expression.items] == [1]
    assert [item.concept_id for item in result.pre_rollup_expression.items] == [1, 2]


def test_should_not_restore_filtered_ancestor_when_rollup_matches_sibling(monkeypatch):
    builder = ExpressionBuilder()
    candidates = [_candidate(9), _candidate(1), _candidate(2)]
    monkeypatch.setattr(builder, '_validate_standard_concepts', lambda values: values)
    monkeypatch.setattr(builder, '_drop_non_seed_ancestors', lambda values, seeds: values[1:])
    monkeypatch.setattr(builder, '_drop_non_seed_coparents', lambda values, seeds: values)
    monkeypatch.setattr(builder, '_filter_overbroad', lambda values: values)
    from unittest.mock import MagicMock

    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [
        MagicMock(descendant_concept_id=2, ancestor_concept_id=1)
    ]
    monkeypatch.setattr('src.agents.conceptset.expression_builder.SessionLocal', lambda: session)
    sibling = builder.build_expression([_candidate(1)], roll_up=False).expression
    result = builder.build_expression(candidates, sibling_expressions=[sibling])
    assert [item.concept_id for item in result.expression.items] == [1, 2]
    assert [item.concept_id for item in result.pre_rollup_expression.items] == [1, 2]
