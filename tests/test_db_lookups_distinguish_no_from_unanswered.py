""""The database said no" and "the database did not answer" are not the same fact.

Four psycopg2 lookups in `tte_service.py` collapsed them. Each wrapped `connect` and its
queries in one `try`, logged at DEBUG, and returned its NO-MATCH value on any exception:

    _resolve_ingredient_concept_id  -> None
    _fetch_concept_candidates       -> []
    _unique_ingredient_ids_by_name  -> {}
    _subsumed_concept_pairs         -> None

`None` from the first is what `_recommend_seeded_concept_set` reads as "this seed is not
an ingredient name", so a pool exhaustion or a connect failure sends a drug seed down the
embedding path -- the path that answers "linagliptin" with sitagliptin and "warfarin"
with a LOINC lab, and the only reason the exact tier exists (AGENTS.md, NAME RESOLUTION
OWNERSHIP). At INFO the failure left no trace anywhere, which is why the measured batch
shows ZERO rows of this loss class: nothing records it.

`src/agents/agent2/logic.py` got the same split in 3b1a287; this is its other half. No
TTL and no latch here, deliberately: logic.py's filters are optional by design, whereas
these four are load-bearing name resolution, so the per-call answer is either real or an
error -- never a quiet fallback to embedding search.

No live database: `psycopg2.connect` is patched throughout, exactly as
`tests/test_ingredient_name_bridges.py` does.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from src.services.tte_service import TTEService
from src.utils.exceptions import DBConnectionError, DBQueryError


def _build_service() -> TTEService:
    return TTEService(store=MagicMock())


def _connection(rows: list[tuple] | None = None, execute_error: Exception | None = None):
    """A connection mock that either returns ``rows`` or raises from ``execute``."""
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    if execute_error is not None:
        cursor.execute.side_effect = execute_error
    else:
        cursor.fetchall.return_value = list(rows or [])
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


#: (label, callable taking the service, the value a genuine no-match returns)
LOOKUPS = [
    (
        "_resolve_ingredient_concept_id",
        lambda s: s._resolve_ingredient_concept_id("linagliptin"),
        None,
    ),
    ("_fetch_concept_candidates", lambda s: s._fetch_concept_candidates([1594973]), []),
    (
        "_unique_ingredient_ids_by_name",
        lambda s: s._unique_ingredient_ids_by_name({"linagliptin"}),
        {},
    ),
    ("_subsumed_concept_pairs", lambda s: s._subsumed_concept_pairs({(1, 2)}), set()),
]


@pytest.mark.parametrize("label,call,no_match", LOOKUPS, ids=[row[0] for row in LOOKUPS])
def test_should_raise_when_the_connection_could_not_be_made(label, call, no_match):
    svc = _build_service()
    with patch("psycopg2.connect", side_effect=OSError("no route to host")):
        with pytest.raises(DBConnectionError):
            call(svc)


@pytest.mark.parametrize("label,call,no_match", LOOKUPS, ids=[row[0] for row in LOOKUPS])
def test_should_raise_when_a_query_failed(label, call, no_match):
    svc = _build_service()
    conn = _connection(execute_error=psycopg2.OperationalError("pool exhausted"))
    with patch("psycopg2.connect", return_value=conn):
        with pytest.raises(DBQueryError):
            call(svc)


@pytest.mark.parametrize("label,call,no_match", LOOKUPS, ids=[row[0] for row in LOOKUPS])
def test_should_still_return_the_no_match_value_when_the_database_answered_nothing(
    label, call, no_match
):
    """A real no-match is unchanged. Only the error path moves."""
    svc = _build_service()
    conn = _connection(rows=[])
    with patch("psycopg2.connect", return_value=conn):
        assert call(svc) == no_match


def test_should_not_reroute_a_drug_seed_to_embedding_search_when_the_database_is_down():
    """The whole point: an unreachable database must not read as 'not an ingredient'."""
    svc = _build_service()
    with patch("psycopg2.connect", side_effect=OSError("no route to host")):
        with pytest.raises(DBConnectionError):
            svc._exact_ingredient_mapping("linagliptin")


def test_should_leave_the_repair_declining_only_for_a_real_empty_subsumption():
    """`_subsumed_concept_pairs` no longer has a None channel to decline on."""
    svc = _build_service()
    conn = _connection(rows=[])
    with patch("psycopg2.connect", return_value=conn):
        assert svc._subsumed_concept_pairs({(1, 2)}) == set()
