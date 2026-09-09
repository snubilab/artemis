"""A failed DB probe is "the database did not answer", not "the database said no".

`agent2.logic._check_db()` cached BOTH outcomes in one module global with no
invalidation. One transient failure — Postgres still coming up while artemis-api
boots is the ordinary case — latched `False` for the whole process lifetime, and
four quality filters failed open together behind it for the rest of the run:

  * `roll_up_to_rxnorm_ingredients` returns its input unchanged, leaving RxNorm
    Extension product ids in a DrugEra criterion. `drug_era` is recorded at
    Ingredient level, so that criterion joins nothing and the arm is 0 patients.
  * `drop_qualitative_findings` (`logic.py:93`) and the two other gated filters
    stop filtering.

All of it after a single WARNING. A success is still cached for the process
lifetime — that direction is a real answer; only the failure is a non-answer, and
a non-answer must expire.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2 import logic


@pytest.fixture(autouse=True)
def restore_probe_cache():
    """The probe cache is a module global shared by the whole test session."""
    saved = (logic._db_available, logic._db_probe_failed_at)
    logic._db_available = None
    logic._db_probe_failed_at = None
    yield
    logic._db_available, logic._db_probe_failed_at = saved


def _engine(*, fails: bool):
    engine = MagicMock()
    if fails:
        engine.connect.side_effect = OSError("connection refused")
    else:
        engine.connect.return_value.__enter__.return_value = MagicMock()
    return engine


class TestCheckDbProbeCache:
    def test_should_reprobe_after_the_retry_window_when_the_first_probe_failed(
        self, monkeypatch
    ):
        monkeypatch.setenv("LOGICIAN_DB_PROBE_RETRY_SECONDS", "0")
        down = _engine(fails=True)
        with patch("src.utils.db.engine", down):
            assert logic._check_db() is False
        up = _engine(fails=False)
        with patch("src.utils.db.engine", up):
            assert logic._check_db() is True, \
                "Postgres came up; the process must not stay downgraded for its lifetime"
        assert up.connect.called

    def test_should_not_reprobe_within_the_retry_window(self, monkeypatch):
        monkeypatch.setenv("LOGICIAN_DB_PROBE_RETRY_SECONDS", "3600")
        down = _engine(fails=True)
        with patch("src.utils.db.engine", down):
            assert logic._check_db() is False
            assert logic._check_db() is False
        assert down.connect.call_count == 1, \
            "a down database must not be probed once per call"

    def test_should_cache_a_successful_probe_for_the_process_lifetime(self, monkeypatch):
        monkeypatch.setenv("LOGICIAN_DB_PROBE_RETRY_SECONDS", "0")
        up = _engine(fails=False)
        with patch("src.utils.db.engine", up):
            assert logic._check_db() is True
            assert logic._check_db() is True
        assert up.connect.call_count == 1, \
            "a success is a real answer and stays cached"

    def test_should_stay_down_when_the_reprobe_also_fails(self, monkeypatch):
        monkeypatch.setenv("LOGICIAN_DB_PROBE_RETRY_SECONDS", "0")
        down = _engine(fails=True)
        with patch("src.utils.db.engine", down):
            assert logic._check_db() is False
            assert logic._check_db() is False
        assert down.connect.call_count == 2

    def test_should_fall_back_to_the_default_window_on_an_unparseable_env_value(
        self, monkeypatch
    ):
        monkeypatch.setenv("LOGICIAN_DB_PROBE_RETRY_SECONDS", "not-a-number")
        down = _engine(fails=True)
        with patch("src.utils.db.engine", down):
            assert logic._check_db() is False
            assert logic._check_db() is False
        assert down.connect.call_count == 1, \
            "a bad env value must not turn every call into a connect attempt"


class TestGatedFiltersRecover:
    def test_should_filter_again_once_the_database_answers(self, monkeypatch):
        """The behaviour the latch cost: `drop_qualitative_findings` returned its
        input unchanged while `False` was latched, and used to keep doing so even
        after Postgres was reachable."""
        monkeypatch.setenv("LOGICIAN_DB_PROBE_RETRY_SECONDS", "0")
        logician = logic.ConceptLogician.__new__(logic.ConceptLogician)
        logician.schema = "cdm"
        concept_ids = [40213251, 4024958]

        with patch("src.utils.db.engine", _engine(fails=True)):
            assert logician.drop_qualitative_findings(concept_ids) == concept_ids

        db = MagicMock()
        db.__enter__.return_value = db  # `with next(get_db()) as db:` in the filter
        db.execute.return_value.fetchall.return_value = [(4024958,)]
        with patch("src.utils.db.engine", _engine(fails=False)), \
             patch("src.utils.db.get_db", return_value=iter([db])):
            assert logician.drop_qualitative_findings(concept_ids) == [40213251], \
                "the Clinical Finding must be dropped once the database is reachable again"
