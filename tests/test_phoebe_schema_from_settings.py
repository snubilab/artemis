"""PhoebeClient must query the schema the operator configured.

settings.PHOEBE_SCHEMA existed and had exactly one reference in the whole codebase:
its own definition. PhoebeClient carried `SCHEMA = "demo_cdm"` as a class constant,
so with PHOEBE_SCHEMA=omop_vocab set in .env AND in the running container, every
call still queried demo_cdm -- with nothing logged.

That is the worst shape a configuration can take. An absent setting fails on the
first call; a set-and-ignored one returns plausible results from the wrong schema
forever. Reached live: tte_service.py's mapping-candidates path calls
stage2.search(), which calls self.phoebe.expand_seeds().
"""
from __future__ import annotations

import importlib

import pytest


def _reloaded_client_class(monkeypatch: pytest.MonkeyPatch, schema: str):
    """Reload through settings so the class constant is rebuilt from the env."""
    monkeypatch.setenv("PHOEBE_SCHEMA", schema)
    import src.settings

    importlib.reload(src.settings)
    import src.agents.conceptset.phoebe_client as phoebe_client

    importlib.reload(phoebe_client)
    return phoebe_client.PhoebeClient


def test_the_configured_schema_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    client_cls = _reloaded_client_class(monkeypatch, "omop_vocab")

    assert client_cls.SCHEMA == "omop_vocab"
    assert client_cls().schema == "omop_vocab"


def test_a_different_setting_reaches_the_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not just "not demo_cdm" -- the actual value has to arrive."""
    client_cls = _reloaded_client_class(monkeypatch, "synthea23m")

    assert client_cls().schema == "synthea23m"


def test_an_explicit_argument_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """The constructor override predates this change and callers may rely on it."""
    client_cls = _reloaded_client_class(monkeypatch, "omop_vocab")

    assert client_cls(schema="explicit_override").schema == "explicit_override"
