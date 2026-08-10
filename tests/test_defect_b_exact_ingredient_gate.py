"""Regression tests for Defect B (exact-ingredient mapping) gating.

Confirmed root cause: the exact standard-RxNorm-Ingredient name match in
``TTEService._exact_ingredient_mapping`` was gated behind
``TTE_DRUG_ANCHORED_ENTRY`` (Defect A / ADR-019, an unfinished, unset-by-default
entry-mode feature), so it never ran in production and a concept set named
"linagliptin" resolved to sitagliptin.

These tests pin the fix: the exact-ingredient match applies unconditionally for
Drug-domain seeds, independent of drug-anchored entry mode, with its own named
ablation (``ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH``, default OFF / match ON)
for a per-criterion A/B control arm.

No live database or containers are used; ``psycopg2.connect`` and the
downstream Agent2/cache pipeline are patched throughout.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2.criterion_cache import CriterionCacheEntry, CriterionResultCache
from src.services.tte_service import TTEService


def _build_service() -> TTEService:
    """Instantiate TTEService with a mock store (matches test_perf002_integration.py)."""
    return TTEService(store=MagicMock())


def _make_exact_mapping_result(concept_id: int = 40239216, name: str = "linagliptin") -> dict:
    """Build a return value shaped like ``_exact_ingredient_mapping``'s success path."""
    return {
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": name,
                        "DOMAIN_ID": "Drug",
                        "CONCEPT_CLASS_ID": "Ingredient",
                        "STANDARD_CONCEPT": "S",
                        "VOCABULARY_ID": "RxNorm",
                    },
                    "isExcluded": False,
                    "includeDescendants": True,
                    "includeMapped": False,
                }
            ]
        },
        "domain": "Drug",
        "mapping_metadata": None,
    }


def _make_cache_entry(seed: str) -> CriterionCacheEntry:
    """Build a CriterionCacheEntry to short-circuit the pipeline past the gate."""
    return CriterionCacheEntry(
        concept_ids=[999],
        expression={"items": []},
        name="Cached Concept Set",
        domain="Drug",
        route_path="cache",
        mapping_metadata=None,
        created_at="2026-03-29T00:00:00+00:00",
    )


def _pg_connection(rows: list[tuple]) -> MagicMock:
    """Build a psycopg2-connection-like mock whose cursor().fetchall() returns rows."""
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    cursor.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure the two gate env vars start unset for every test unless overridden."""
    monkeypatch.delenv("TTE_DRUG_ANCHORED_ENTRY", raising=False)
    monkeypatch.delenv("ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH", raising=False)


class TestExactIngredientGateAppliesUnconditionally:
    """RED: exact mapping must apply for Drug seeds regardless of drug-anchored entry mode."""

    def test_should_apply_exact_mapping_for_drug_seed_when_anchored_entry_unset(self):
        """This is the regression that started this fix: with TTE_DRUG_ANCHORED_ENTRY
        unset (the live production state), a Drug-domain seed must still be resolved
        via the exact-ingredient lookup, not fall through to the embedding pipeline.
        """
        svc = _build_service()
        sentinel = _make_exact_mapping_result()

        with patch.object(svc, "_exact_ingredient_mapping", return_value=sentinel) as mock_exact:
            result = svc._recommend_seeded_concept_set("linagliptin", expected_domain="Drug")

        mock_exact.assert_called_once_with("linagliptin")
        assert result == sentinel

    def test_should_apply_exact_mapping_for_drug_seed_when_anchored_entry_explicitly_false(self):
        """Explicitly-false TTE_DRUG_ANCHORED_ENTRY must not disable the exact match either --
        the two are decoupled, not just defaulting the same way.
        """
        svc = _build_service()
        sentinel = _make_exact_mapping_result(concept_id=1, name="glimepiride")

        with (
            patch.dict(os.environ, {"TTE_DRUG_ANCHORED_ENTRY": "false"}),
            patch.object(svc, "_exact_ingredient_mapping", return_value=sentinel) as mock_exact,
        ):
            result = svc._recommend_seeded_concept_set("glimepiride", expected_domain="Drug")

        mock_exact.assert_called_once_with("glimepiride")
        assert result == sentinel

    def test_should_normalize_seed_whitespace_before_exact_mapping_lookup(self):
        """The gate must pass the normalized (collapsed-whitespace) seed, matching the
        cache and Agent2 paths' normalization.
        """
        svc = _build_service()
        sentinel = _make_exact_mapping_result()

        with patch.object(svc, "_exact_ingredient_mapping", return_value=sentinel) as mock_exact:
            svc._recommend_seeded_concept_set("  linagliptin   ", expected_domain="Drug")

        mock_exact.assert_called_once_with("linagliptin")

    def test_should_not_query_cache_when_exact_mapping_succeeds(self):
        """A successful exact match returns before the cache lookup runs at all --
        this is what lets it override previously-cached wrong mappings.
        """
        svc = _build_service()
        sentinel = _make_exact_mapping_result()

        with (
            patch.object(svc, "_exact_ingredient_mapping", return_value=sentinel),
            patch("src.agents.agent2.criterion_cache.get_criterion_cache") as mock_get_cache,
        ):
            svc._recommend_seeded_concept_set("linagliptin", expected_domain="Drug")

        mock_get_cache.assert_not_called()


class TestExactIngredientGateScopedToDrugDomain:
    """Non-Drug domains must never trigger the exact-ingredient lookup."""

    def test_should_skip_exact_mapping_for_non_drug_domain(self):
        svc = _build_service()
        cache = CriterionResultCache(max_entries=100, ttl_hours=1)
        cache.put("History of Stroke", "Condition", _make_cache_entry("history of stroke"))

        with (
            patch.object(svc, "_exact_ingredient_mapping") as mock_exact,
            patch("src.agents.agent2.criterion_cache.get_criterion_cache", return_value=cache),
            patch.dict(os.environ, {"CRITERION_CACHE_ENABLED": "true"}),
        ):
            result = svc._recommend_seeded_concept_set(
                "History of Stroke", expected_domain="Condition"
            )

        mock_exact.assert_not_called()
        assert result["name"] == "Cached Concept Set"

    @pytest.mark.parametrize("domain", ["Condition", "Measurement", "Procedure", "Observation"])
    def test_should_skip_exact_mapping_when_domain_is_set_and_not_drug(self, domain):
        """Five seeds in the six-trial store carry a non-Drug domain and still match an
        ingredient name exactly: Calcitonin, Creatinine, Glucose and glucose are
        Measurement lab tests named after the analyte, and glimepiride is the Condition
        "Hypersensitivity to investigational product or glimepiride" whose sourceText
        normalized to the bare drug name. Dropping the domain check recasts all five as
        drug exposures, so the gate must stay closed for any domain that is set and is
        not Drug.
        """
        svc = _build_service()
        cache = CriterionResultCache(max_entries=100, ttl_hours=1)
        cache.put("Creatinine", domain, _make_cache_entry("creatinine"))

        with (
            patch.object(svc, "_exact_ingredient_mapping") as mock_exact,
            patch("src.agents.agent2.criterion_cache.get_criterion_cache", return_value=cache),
            patch.dict(os.environ, {"CRITERION_CACHE_ENABLED": "true"}),
        ):
            svc._recommend_seeded_concept_set("Creatinine", expected_domain=domain)

        mock_exact.assert_not_called()

    def test_should_apply_exact_mapping_when_expected_domain_is_none(self):
        """_build_seeded_target_circe maps the entry drug with no expected_domain, so the
        PrimaryCriteria DrugEra concept set arrives here with None. Requiring == "Drug"
        left it on the embedding path, which is the whole linagliptin->sitagliptin defect.
        """
        svc = _build_service()
        cache = CriterionResultCache(max_entries=100, ttl_hours=1)
        cache.put("linagliptin", None, _make_cache_entry("linagliptin"))
        expected = _make_exact_mapping_result()

        with (
            patch.object(svc, "_exact_ingredient_mapping", return_value=expected) as mock_exact,
            patch("src.agents.agent2.criterion_cache.get_criterion_cache", return_value=cache),
            patch.dict(os.environ, {"CRITERION_CACHE_ENABLED": "true"}),
        ):
            result = svc._recommend_seeded_concept_set("linagliptin", expected_domain=None)

        mock_exact.assert_called_once_with("linagliptin")
        assert result is expected
        assert result["expression"]["items"][0]["concept"]["CONCEPT_ID"] == 40239216


class TestExactIngredientGateFallsThrough:
    """A None result from the exact lookup must fall through to the existing pipeline."""

    def test_should_fall_through_to_pipeline_when_exact_mapping_returns_none(self):
        svc = _build_service()
        cache = CriterionResultCache(max_entries=100, ttl_hours=1)
        cache.put("linagliptin", "Drug", _make_cache_entry("linagliptin"))

        with (
            patch.object(svc, "_exact_ingredient_mapping", return_value=None) as mock_exact,
            patch("src.agents.agent2.criterion_cache.get_criterion_cache", return_value=cache),
            patch.dict(os.environ, {"CRITERION_CACHE_ENABLED": "true"}),
        ):
            result = svc._recommend_seeded_concept_set("linagliptin", expected_domain="Drug")

        mock_exact.assert_called_once_with("linagliptin")
        assert result["name"] == "Cached Concept Set"


class TestExactIngredientMappingRowCounts:
    """Direct coverage of _exact_ingredient_mapping's row-count handling (no gate)."""

    def test_should_return_none_when_exact_ingredient_lookup_finds_zero_rows(self):
        svc = _build_service()
        conn = _pg_connection(rows=[])

        with patch("psycopg2.connect", return_value=conn):
            result = svc._exact_ingredient_mapping("investigational-code-1234")

        assert result is None

    def test_should_return_none_when_exact_ingredient_lookup_finds_multiple_rows(self):
        """Ambiguous (>1) exact matches must fall through, not pick either row."""
        svc = _build_service()
        conn = _pg_connection(rows=[(1,), (2,)])

        with patch("psycopg2.connect", return_value=conn):
            result = svc._exact_ingredient_mapping("some ambiguous ingredient class name")

        assert result is None


class TestExactIngredientMatchAblation:
    """Named ablation env var (control arm), following the ARTEMIS_DISABLE_ORGROUP_DEDUP idiom."""

    def test_should_skip_exact_mapping_when_ablation_env_var_set(self):
        svc = _build_service()
        cache = CriterionResultCache(max_entries=100, ttl_hours=1)
        cache.put("linagliptin", "Drug", _make_cache_entry("linagliptin"))

        with (
            patch.object(svc, "_exact_ingredient_mapping") as mock_exact,
            patch("src.agents.agent2.criterion_cache.get_criterion_cache", return_value=cache),
            patch.dict(
                os.environ,
                {
                    "ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH": "1",
                    "CRITERION_CACHE_ENABLED": "true",
                },
            ),
        ):
            result = svc._recommend_seeded_concept_set("linagliptin", expected_domain="Drug")

        mock_exact.assert_not_called()
        assert result["name"] == "Cached Concept Set"

    def test_should_apply_exact_mapping_when_ablation_env_var_unset(self):
        """Default (unset) must be ON -- the ablation is opt-out, not opt-in."""
        svc = _build_service()
        sentinel = _make_exact_mapping_result()

        with patch.object(svc, "_exact_ingredient_mapping", return_value=sentinel) as mock_exact:
            result = svc._recommend_seeded_concept_set("linagliptin", expected_domain="Drug")

        mock_exact.assert_called_once_with("linagliptin")
        assert result == sentinel


class TestMeshAliasResolution:
    """A development code is never an ingredient name, so the trial's MeSH terms are tried
    next. The vocabulary genuinely cannot answer this: 'BI 10773' appears in none of the
    6.3M concepts and empagliflozin's ingredient carries no synonym rows. The resolution
    lives in the trial record, which NLM indexes to MeSH preferred terms.
    """

    def test_should_resolve_through_mesh_alias_when_seed_is_a_development_code(self):
        svc = _build_service()
        expected = _make_exact_mapping_result(45774751, "empagliflozin")

        def lookup(name):
            return expected if name == "empagliflozin" else None

        with patch.object(svc, "_exact_ingredient_mapping", side_effect=lookup):
            result = svc._alias_ingredient_mapping("BI 10773", ["empagliflozin"])

        assert result is not None
        assert result["expression"]["items"][0]["concept"]["CONCEPT_ID"] == 45774751

    def test_should_keep_the_study_label_when_resolving_through_an_alias(self):
        """The concept set still reads as the arm the protocol named, not as the alias."""
        svc = _build_service()
        with patch.object(
            svc, "_exact_ingredient_mapping",
            side_effect=lambda n: _make_exact_mapping_result(45774751, "empagliflozin")
            if n == "empagliflozin" else None,
        ):
            result = svc._alias_ingredient_mapping("BI 10773", ["empagliflozin"])

        assert result["name"] == "BI 10773"

    def test_should_refuse_when_more_than_one_alias_resolves(self):
        """Two resolving aliases means an ambiguous trial; refuse rather than guess."""
        svc = _build_service()
        with patch.object(
            svc, "_exact_ingredient_mapping",
            side_effect=lambda n: _make_exact_mapping_result(1, n.lower()),
        ):
            result = svc._alias_ingredient_mapping("BI 10773", ["Warfarin", "apixaban"])

        assert result is None

    def test_should_return_none_when_no_alias_resolves(self):
        svc = _build_service()
        with patch.object(svc, "_exact_ingredient_mapping", return_value=None):
            assert svc._alias_ingredient_mapping("BI 10773", ["not a drug at all"]) is None

    @pytest.mark.parametrize("aliases", [None, [], ["", "   "]])
    def test_should_return_none_when_there_are_no_usable_aliases(self, aliases):
        svc = _build_service()
        with patch.object(svc, "_exact_ingredient_mapping", return_value=None) as mock_lookup:
            assert svc._alias_ingredient_mapping("BI 10773", aliases) is None
        if not aliases:
            mock_lookup.assert_not_called()

    def test_should_ignore_an_alias_identical_to_the_seed(self):
        """Retrying the seed under a different case cannot succeed; it already failed."""
        svc = _build_service()
        with patch.object(svc, "_exact_ingredient_mapping", return_value=None) as mock_lookup:
            svc._alias_ingredient_mapping("apixaban", ["Apixaban"])
        mock_lookup.assert_not_called()

    def test_should_not_consult_aliases_when_the_seed_itself_resolves(self):
        """Seed wins. Five of the six benchmark trials never reach the alias route."""
        svc = _build_service()
        seed_hit = _make_exact_mapping_result(43013024, "apixaban")
        cache = CriterionResultCache(max_entries=100, ttl_hours=1)
        cache.put("apixaban", None, _make_cache_entry("apixaban"))

        with (
            patch.object(svc, "_exact_ingredient_mapping", return_value=seed_hit),
            patch.object(svc, "_alias_ingredient_mapping") as mock_alias,
            patch("src.agents.agent2.criterion_cache.get_criterion_cache", return_value=cache),
        ):
            result = svc._recommend_seeded_concept_set(
                "apixaban", expected_domain=None, alias_candidates=["Warfarin", "apixaban"]
            )

        assert result is seed_hit
        mock_alias.assert_not_called()

    def test_should_try_aliases_from_the_gate_when_the_seed_fails(self):
        svc = _build_service()
        alias_hit = _make_exact_mapping_result(45774751, "empagliflozin")
        cache = CriterionResultCache(max_entries=100, ttl_hours=1)
        cache.put("BI 10773", None, _make_cache_entry("BI 10773"))

        with (
            patch.object(svc, "_exact_ingredient_mapping", return_value=None),
            patch.object(svc, "_alias_ingredient_mapping", return_value=alias_hit) as mock_alias,
            patch("src.agents.agent2.criterion_cache.get_criterion_cache", return_value=cache),
        ):
            result = svc._recommend_seeded_concept_set(
                "BI 10773", expected_domain=None, alias_candidates=["empagliflozin"]
            )

        assert result is alias_hit
        mock_alias.assert_called_once_with("BI 10773", ["empagliflozin"])

    def test_should_skip_aliases_when_the_ablation_env_var_is_set(self, monkeypatch):
        monkeypatch.setenv("ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH", "1")
        svc = _build_service()
        cache = CriterionResultCache(max_entries=100, ttl_hours=1)
        cache.put("BI 10773", None, _make_cache_entry("BI 10773"))

        with (
            patch.object(svc, "_alias_ingredient_mapping") as mock_alias,
            patch("src.agents.agent2.criterion_cache.get_criterion_cache", return_value=cache),
        ):
            svc._recommend_seeded_concept_set(
                "BI 10773", expected_domain=None, alias_candidates=["empagliflozin"]
            )

        mock_alias.assert_not_called()
