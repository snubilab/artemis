"""The MeSH alias path must be wired, not merely present.

``TTEService._alias_ingredient_mapping`` resolves a sponsor development code
through the trial's MeSH intervention terms, and it works. It was nonetheless
inactive for every benchmark arm, because the two things that feed it were both
missing: the store carried no ``trialMetadata.interventionMeshTerms``, and the
regeneration harness never injected ``_interventionAliases``. EMPA-REG's target
arm -- 'BI 10773', empagliflozin's development code -- came back as a mix of
HIV and cystic-fibrosis drugs.

These tests pin both feeds. They are DB-free: the resolution itself is already
covered by tests/test_defect_b_exact_ingredient_gate.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.backfill_intervention_mesh_terms import main as backfill_main
from scripts.backfill_intervention_mesh_terms import mesh_terms_for
from scripts.regenerate_structured_expression import alias_terms_for

REPO_ROOT = Path(__file__).resolve().parents[1]
NCT_CACHE = REPO_ROOT / "data" / "nct_cache"

# The trial that motivated all of this, and its registry id.
EMPA_REG_NCT = "NCT01131676"


def _store(tmp_path: Path, studies: list[dict]) -> Path:
    path = tmp_path / "studies.json"
    path.write_text(json.dumps({"studies": studies}))
    return path


# --------------------------------------------------------------------------
# harness injection
# --------------------------------------------------------------------------

def test_should_return_mesh_terms_when_the_study_carries_them():
    study = {"trialMetadata": {"interventionMeshTerms": ["empagliflozin"]}}
    assert alias_terms_for(study) == ["empagliflozin"]


def test_should_return_empty_list_when_the_store_has_no_mesh_terms():
    """The silent case: alias_candidates=None disables the MeSH path entirely."""
    assert alias_terms_for({"trialMetadata": {}}) == []
    assert alias_terms_for({}) == []
    assert alias_terms_for({"trialMetadata": {"interventionMeshTerms": None}}) == []


def test_should_not_share_the_stored_list_with_the_caller():
    """The harness hands this straight to a dict that gets popped and mutated."""
    study = {"trialMetadata": {"interventionMeshTerms": ["empagliflozin"]}}
    terms = alias_terms_for(study)
    terms.append("nonsense")
    assert study["trialMetadata"]["interventionMeshTerms"] == ["empagliflozin"]


def test_should_hand_the_mesh_terms_to_the_circe_builder(tmp_path, monkeypatch):
    """The defect this file exists for: the harness called the builder without them.

    Asserting on ``alias_terms_for`` alone would not catch it -- deleting the
    injection line leaves that function perfectly correct. This drives main() and
    inspects the eligibility dict the builder actually receives.
    """
    import src.services.tte_service as tte_service
    import src.services.tte_store as tte_store
    import scripts.regenerate_structured_expression as harness

    seen: list[dict] = []

    class FakeStore:
        def __init__(self, path):
            self.path = path

        def get_study(self, study_id):
            return {
                "id": study_id,
                "nctId": "NCT01131676",
                "trialMetadata": {"interventionMeshTerms": ["empagliflozin"]},
                "eligibility": {"targetCohortName": "BI 10773"},
            }

        def update_study(self, study_id, patch):  # pragma: no cover - not reached
            raise AssertionError("dry run must not write")

    class FakeService:
        def __init__(self, store):
            self.store = store

        def _build_seeded_target_circe(self, eligibility):
            seen.append(eligibility)
            return {}

    monkeypatch.setattr(tte_service, "TTEService", FakeService)
    monkeypatch.setattr(tte_store, "TTEStore", FakeStore)
    monkeypatch.setattr(harness, "STUDIES", {8: "EMPA-REG OUTCOME"})
    store = _store(tmp_path, [])
    monkeypatch.setenv("TTE_STORE_PATH", str(store))
    monkeypatch.setattr("sys.argv", ["regenerate_structured_expression.py"])

    harness.main()

    assert seen, "the builder was never called"
    assert seen[0].get("_interventionAliases") == ["empagliflozin"], (
        "the entry-drug mapper runs with alias_candidates=None without this, "
        "which silently disables the MeSH path for development-code targets"
    )


# --------------------------------------------------------------------------
# backfill from the NCT cache
# --------------------------------------------------------------------------

@pytest.mark.skipif(not (NCT_CACHE / f"{EMPA_REG_NCT}.json").exists(),
                    reason="NCT cache not present")
def test_should_read_empagliflozin_from_the_real_empa_reg_cache_entry():
    """Run against the actual payload, not a fixture: the field is NLM-authored
    (derivedSection), and no sponsor field in this trial carries the ingredient."""
    assert mesh_terms_for(EMPA_REG_NCT, NCT_CACHE) == ["empagliflozin"]


def test_should_report_none_when_the_trial_is_not_cached(tmp_path):
    assert mesh_terms_for("NCT99999999", tmp_path) is None


# --------------------------------------------------------------------------
# the alias tier must not answer for a seed that is already a drug name
# --------------------------------------------------------------------------

def test_should_refuse_the_alias_path_when_a_mesh_term_is_the_seed_itself():
    """PLATO's shape: seed 'ticagrelor', MeSH terms ['Ticagrelor', 'Clopidogrel'].

    Skipping the alias equal to the seed left exactly one resolving term, which
    satisfied the "exactly one or refuse" guard and returned CLOPIDOGREL's
    concept under the name 'ticagrelor' -- the comparator's drug in the study
    drug's slot. Measured live before the fix: 1322184 clopidogrel.

    The tier exists for seeds the vocabulary cannot answer, i.e. development
    codes. A seed that IS one of the trial's MeSH terms is a recognised drug
    name by definition, so this tier must decline and let the ordinary lookup
    handle it. Masked today only because the exact-ingredient tier runs first.
    """
    from src.services.tte_service import TTEService

    service = TTEService.__new__(TTEService)
    calls: list[str] = []

    def _never_resolves(name):
        calls.append(name)
        return None

    service._exact_ingredient_mapping = _never_resolves
    assert service._alias_ingredient_mapping("ticagrelor", ["Ticagrelor", "Clopidogrel"]) is None
    assert "Clopidogrel" not in calls, "the comparator must not even be tried"


def test_should_still_resolve_a_development_code_that_matches_no_mesh_term():
    """The case the tier exists for must keep working: 'BI 10773' is not a MeSH term."""
    from src.services.tte_service import TTEService

    service = TTEService.__new__(TTEService)
    service._exact_ingredient_mapping = lambda name: (
        {"name": name, "expression": {"items": []}, "domain": "Drug"}
        if name == "empagliflozin" else None
    )
    result = service._alias_ingredient_mapping("BI 10773", ["empagliflozin"])
    assert result is not None
    assert result["name"] == "BI 10773"


def test_should_fill_the_store_from_the_cache_when_apply_is_given(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "NCT01131676.json").write_text(json.dumps(
        {"derivedSection": {"interventionBrowseModule": {"meshes": [{"term": "empagliflozin"}]}}}
    ))
    store = _store(tmp_path, [{"id": 8, "name": "BI 10773 vs Placebo", "nctId": "NCT01131676"}])

    backfill_main([str(store), "--cache-dir", str(cache), "--apply"])

    written = json.loads(store.read_text())["studies"][0]
    assert written["trialMetadata"]["interventionMeshTerms"] == ["empagliflozin"]


def test_should_leave_the_store_untouched_without_apply(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "NCT01131676.json").write_text(json.dumps(
        {"derivedSection": {"interventionBrowseModule": {"meshes": [{"term": "empagliflozin"}]}}}
    ))
    store = _store(tmp_path, [{"id": 8, "name": "x", "nctId": "NCT01131676"}])
    before = store.read_text()

    backfill_main([str(store), "--cache-dir", str(cache)])

    assert store.read_text() == before


def test_should_not_overwrite_mesh_terms_that_are_already_set(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "NCT01131676.json").write_text(json.dumps(
        {"derivedSection": {"interventionBrowseModule": {"meshes": [{"term": "empagliflozin"}]}}}
    ))
    store = _store(tmp_path, [{
        "id": 8, "name": "x", "nctId": "NCT01131676",
        "trialMetadata": {"interventionMeshTerms": ["hand-curated"]},
    }])

    backfill_main([str(store), "--cache-dir", str(cache), "--apply"])

    written = json.loads(store.read_text())["studies"][0]
    assert written["trialMetadata"]["interventionMeshTerms"] == ["hand-curated"]
