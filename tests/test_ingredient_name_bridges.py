"""A drug name that OMOP spells differently must still reach its ingredient.

``_exact_ingredient_mapping`` matched a seed against standard RxNorm Ingredient names
and nothing else, so two shapes that OMOP does carry were refused:

* MeSH indexes salt and ester headings -- 'Quetiapine Fumarate', 'Sildenafil Citrate' --
  where RxNorm's ingredient is the base. OMOP already holds that edge as
  ``Precise Ingredient --Maps to--> Ingredient``.
* Some standard Ingredients live in ``RxNorm Extension`` rather than ``RxNorm``
  (artenimol, izencitinib, prothrombin complex concentrate). They are standard
  ingredient concepts; only the vocabulary filter excluded them.

Measured over the 730-trial NCT cache these two bridges reach 8 of the 84 trials the
MeSH alias tier could not serve (``scripts/analyze_alias_tier_refusals.py``).

The probes are ORDERED and each one is final: RxNorm decides first, and an ambiguous
RxNorm name still refuses rather than falling through to a bridge. That ordering is
what makes the change additive -- only names that resolved to nothing before can
resolve now -- and these tests pin it.

No live database: ``psycopg2.connect`` is patched throughout.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.services.tte_service import TTEService

RX_CONCEPT = 40239216
EXT_CONCEPT = 1254255
BASE_CONCEPT = 766814


def _build_service() -> TTEService:
    return TTEService(store=MagicMock())


def _pg_connection(*result_sets: list[tuple]) -> tuple[MagicMock, MagicMock]:
    """Connection mock whose successive fetchall() calls return the given result sets.

    :param result_sets: One row list per expected query, in execution order.
    :returns: The connection mock and its cursor, so callers can count queries.
    """
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    cursor.fetchall.side_effect = list(result_sets)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def test_should_resolve_through_rxnorm_without_consulting_any_bridge():
    svc = _build_service()
    conn, cursor = _pg_connection([(RX_CONCEPT,)])
    with patch("psycopg2.connect", return_value=conn):
        assert svc._resolve_ingredient_concept_id("linagliptin") == RX_CONCEPT
    assert cursor.execute.call_count == 1


def test_should_resolve_an_ingredient_that_lives_in_rxnorm_extension():
    svc = _build_service()
    conn, cursor = _pg_connection([], [(EXT_CONCEPT,)])
    with patch("psycopg2.connect", return_value=conn):
        assert svc._resolve_ingredient_concept_id("prothrombin complex concentrate") == EXT_CONCEPT
    assert cursor.execute.call_count == 2


def test_should_resolve_a_salt_heading_through_the_precise_ingredient_bridge():
    svc = _build_service()
    conn, cursor = _pg_connection([], [], [(BASE_CONCEPT,)])
    with patch("psycopg2.connect", return_value=conn):
        assert svc._resolve_ingredient_concept_id("Quetiapine Fumarate") == BASE_CONCEPT
    assert cursor.execute.call_count == 3


def test_should_refuse_an_ambiguous_rxnorm_name_without_trying_the_bridges():
    # An ambiguous name refused before this change and must keep refusing. Falling
    # through to a bridge here would silently change an existing resolution.
    svc = _build_service()
    conn, cursor = _pg_connection([(1,), (2,)])
    with patch("psycopg2.connect", return_value=conn):
        assert svc._resolve_ingredient_concept_id("some ambiguous class name") is None
    assert cursor.execute.call_count == 1


def test_should_refuse_when_the_extension_name_is_ambiguous():
    svc = _build_service()
    conn, cursor = _pg_connection([], [(1,), (2,)])
    with patch("psycopg2.connect", return_value=conn):
        assert svc._resolve_ingredient_concept_id("ambiguous extension name") is None
    assert cursor.execute.call_count == 2


def test_should_refuse_when_a_salt_heading_maps_to_more_than_one_ingredient():
    svc = _build_service()
    conn, _ = _pg_connection([], [], [(1,), (2,)])
    with patch("psycopg2.connect", return_value=conn):
        assert svc._resolve_ingredient_concept_id("ambiguous salt heading") is None


def test_should_refuse_a_name_no_probe_can_reach():
    svc = _build_service()
    conn, cursor = _pg_connection([], [], [])
    with patch("psycopg2.connect", return_value=conn):
        assert svc._resolve_ingredient_concept_id("BI 10773") is None
    assert cursor.execute.call_count == 3


def test_should_refuse_when_the_database_is_unreachable():
    svc = _build_service()
    with patch("psycopg2.connect", side_effect=OSError("no route to host")):
        assert svc._resolve_ingredient_concept_id("linagliptin") is None


def test_should_still_refuse_a_trial_whose_two_salt_headings_both_resolve():
    """A bridge that widens resolution must not widen what the alias tier will guess.

    NCT07531173 is indexed under 'Venlafaxine Hydrochloride' and 'Duloxetine
    Hydrochloride'. Before the salt bridge neither resolved, so the tier refused for want
    of a candidate; now both resolve and it has to refuse for ambiguity instead. Nothing
    in the registry says which of the two is the study drug.
    """
    svc = _build_service()
    mapping = {
        "name": "x", "expression": {"items": [{}]}, "domain": "Drug", "mapping_metadata": None,
    }
    with patch.object(svc, "_exact_ingredient_mapping", return_value=mapping):
        assert svc._alias_ingredient_mapping(
            "sponsor-code-1", ["Venlafaxine Hydrochloride", "Duloxetine Hydrochloride"]
        ) is None
