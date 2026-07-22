"""Regression tests for Drug-domain ingredient rollup in Agent 2."""

from unittest.mock import MagicMock, patch

from src.agents.agent2.logic import ConceptLogician
from src.agents.agent2.workflow import Agent2Workflow


def _mock_db_session(rows):
    """Build a SQLAlchemy-session-like mock for get_db()."""
    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_session
    mock_session.__exit__.return_value = False
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows
    mock_session.execute.return_value = mock_result
    return mock_session


def test_roll_up_to_rxnorm_ingredients_replaces_product_codes():
    """RxNorm Extension product codes should collapse to the RxNorm ingredient."""
    logician = ConceptLogician()
    mock_session = _mock_db_session(
        rows=[
            (855208, 40241186),
            (855221, 40241186),
        ]
    )

    with (
        patch("src.agents.agent2.logic._check_db", return_value=True),
        patch("src.utils.db.get_db", return_value=iter([mock_session])),
    ):
        rolled_up = logician.roll_up_to_rxnorm_ingredients(
            [855208, 855221, 40241186, 999999]
        )

    assert rolled_up == [40241186, 999999]
    query_text = str(mock_session.execute.call_args.args[0])
    assert "c.vocabulary_id = 'RxNorm'" in query_text
    assert "c.concept_class_id = 'Ingredient'" in query_text


def test_process_with_details_rolls_up_final_drug_ids():
    """Final Drug-domain IDs should be ingredient-normalized after KG/Critic."""
    workflow = Agent2Workflow()
    fake_pool = MagicMock()
    fake_conn = MagicMock()
    fake_pool.getconn.return_value = fake_conn

    class _FakeQueryExpander:
        def __init__(self, umls_expander=None):
            self.umls_expander = umls_expander

        def expand(self, query_text, domain_hint=None):
            return query_text

    with (
        patch("src.agents.agent2.workflow.expand_abbreviation", return_value=("ticagrelor", False)),
        patch("src.agents.agent2.workflow.expand_in_context", return_value="ticagrelor"),
        patch("src.agents.agent2.workflow._get_db_pool", return_value=fake_pool),
        patch("src.agents.agent2.workflow.expand_drug_class_via_vocab", return_value=(None, [])),
        patch("src.agents.agent2.query_expander.QueryExpander", _FakeQueryExpander),
        patch.object(Agent2Workflow, "_slow_path", return_value=[855208]),
        patch.object(Agent2Workflow, "_kg_expand_and_critique", return_value=([855208, 855221], [], False)),
        patch("src.agents.agent2.workflow.logician.roll_up_to_rxnorm_ingredients", return_value=[40241186]) as mock_rollup,
    ):
        result = workflow.process_with_details("ticagrelor", domain_hint="Drug")

    assert result.concept_ids == [40241186]
    mock_rollup.assert_called_once_with([855208, 855221])
