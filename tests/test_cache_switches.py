"""Both LLM result caches are switched the same way, by environment variable.

The two caches sit on the same axis — they exist for deterministic replay, and both
have to be off to measure whether the pipeline reproduces on its own. Before this,
only one had a switch; the other was disabled by moving its files aside, a manual step
with nothing to undo it and no record that it happened.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.agents.agent1.parser import _ir_cache_enabled  # noqa: E402
from src.agents.agent2.criterion_cache import _cache_enabled  # noqa: E402

SWITCHES = [
    pytest.param(_ir_cache_enabled, "AGENT1_IR_CACHE_ENABLED", id="agent1-ir"),
    pytest.param(_cache_enabled, "CRITERION_CACHE_ENABLED", id="criterion"),
]


@pytest.mark.parametrize(("switch", "variable"), SWITCHES)
class TestBothCachesAnswerToAnEnvironmentVariable:
    def test_should_be_on_when_the_variable_is_unset(
        self, switch, variable, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Caching stays the default; a cold run is the deliberate act."""
        monkeypatch.delenv(variable, raising=False)

        assert switch() is True

    def test_should_be_off_when_the_variable_is_false(
        self, switch, variable, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(variable, "false")

        assert switch() is False

    def test_should_be_off_when_the_variable_is_false_in_any_case(
        self, switch, variable, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whoever types FALSE in a shell means it."""
        monkeypatch.setenv(variable, "FALSE")

        assert switch() is False

    def test_should_be_off_for_any_value_that_is_not_true(
        self, switch, variable, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The comparison is against "true", not against "false", so "0" or a typo
        disables rather than enables. That is the safe direction: a slower run beats one
        that replayed cached results while reporting itself as cold. Measured against
        both switches so the two cannot drift onto different conventions."""
        monkeypatch.setenv(variable, "0")

        assert switch() is False
