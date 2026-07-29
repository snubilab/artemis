"""The ingredient rollup must not touch its session after the `with` block exits.

It used to. `Session.__exit__` returns the connection to the pool, and the
safety-net query that ran afterwards checked out a fresh one that nothing ever
returned. Measured against the live pool, `checkedout` climbed 1, 2, 3... per
call until it hit "QueuePool limit of size 20 overflow 40 reached, connection
timed out, timeout 60.00".

From that point every rollup raised, and the handler swallows it and returns the
original ids. So a drug concept set silently kept product-level concepts --
`liraglutide 6 MG/ML [Biolide]` rather than `liraglutide` -- which match no
drug_exposure rows, because Synthea CDMs record at the ingredient level. The run
completes, the log holds one warning line, and the cohort is empty.

This test needs no database: it fails on the ordering alone.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2.logic import ConceptLogician


class _RecordingSession:
    """A session that remembers whether it was used after close."""

    def __init__(self) -> None:
        self.exited = False
        self.used_after_exit = False

    def __enter__(self) -> "_RecordingSession":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.exited = True

    def execute(self, *_args: object, **_kwargs: object) -> MagicMock:
        if self.exited:
            self.used_after_exit = True
        result = MagicMock()
        result.fetchall.return_value = []
        return result


@pytest.fixture
def session() -> _RecordingSession:
    return _RecordingSession()


def _run_rollup(session: _RecordingSession, concept_ids: list[int]) -> list[int]:
    with patch("src.agents.agent2.logic._check_db", return_value=True), \
         patch("src.utils.db.get_db", return_value=iter([session])):
        return ConceptLogician().roll_up_to_rxnorm_ingredients(concept_ids)


def test_session_is_not_used_after_the_with_block_exits(session) -> None:
    _run_rollup(session, [855816, 1718703])

    assert session.exited, "the with block should have run at all"
    assert not session.used_after_exit, (
        "a query ran on a closed session; it checks out a connection nothing returns"
    )


def test_rollup_returns_the_original_ids_when_the_database_is_unavailable(session) -> None:
    """The fallback is correct behaviour -- it is the silence around it that hurt."""
    with patch("src.agents.agent2.logic._check_db", return_value=False):
        result = ConceptLogician().roll_up_to_rxnorm_ingredients([855816, 1718703])

    assert result == [855816, 1718703]


def test_empty_input_does_not_open_a_session(session) -> None:
    assert _run_rollup(session, []) == []
    assert not session.exited
