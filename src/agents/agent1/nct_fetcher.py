"""
Agent 1 - NCT Fetcher.
Fetches clinical trial eligibility criteria from ClinicalTrials.gov API v2.
Supports local JSON caching for offline/reproducible usage.
"""
import json
import re
import requests
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

from src.agents.agent1.segmentation import SectionKind, segment_eligibility


# Default cache directory (relative to project root)
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "nct_cache"


class TrialData(BaseModel):
    """Structured data fetched from a ClinicalTrials.gov NCT entry."""
    nct_id: str
    title: str = ""
    conditions: List[str] = Field(default_factory=list)
    interventions: List[str] = Field(default_factory=list)
    inclusion_criteria: List[str] = Field(default_factory=list)
    exclusion_criteria: List[str] = Field(default_factory=list)
    primary_outcomes: List[str] = Field(default_factory=list)
    study_type: str = ""
    phase: str = ""


def _parse_protocol_to_trial_data(data: dict, nct_id: str) -> TrialData:
    """
    Parse raw ClinicalTrials.gov API v2 JSON into a TrialData object.
    
    Args:
        data: Raw JSON dict from the API (top-level, containing 'protocolSection')
        nct_id: NCT identifier string
        
    Returns:
        TrialData with parsed eligibility criteria and metadata
    """
    protocol = data.get("protocolSection", {})
    
    # --- Extract metadata ---
    identification = protocol.get("identificationModule", {})
    title = identification.get("officialTitle") or identification.get("briefTitle", "")
    
    # Conditions
    conditions_module = protocol.get("conditionsModule", {})
    conditions = conditions_module.get("conditions", [])
    
    # Interventions
    arms_module = protocol.get("armsInterventionsModule", {})
    interventions = [
        iv.get("name", "")
        for iv in arms_module.get("interventions", [])
        if iv.get("name")
    ]
    
    # Primary outcomes
    outcomes_module = protocol.get("outcomesModule", {})
    primary_outcomes = [
        om.get("measure", "")
        for om in outcomes_module.get("primaryOutcomes", [])
        if om.get("measure")
    ]
    
    # Study design
    design_module = protocol.get("designModule", {})
    study_type = design_module.get("studyType", "")
    phases = design_module.get("phases", [])
    phase = ", ".join(phases) if phases else ""
    
    # --- Parse eligibility criteria ---
    eligibility = protocol.get("eligibilityModule", {})
    criteria_text = eligibility.get("eligibilityCriteria", "")

    # Which text is an inclusion or an exclusion criterion is decided by the
    # segmentation step (RFC-016 §5), not by splitting on headers and bullets.
    segmented = segment_eligibility(eligibility_source_text(criteria_text))
    if segmented.failures:
        print(f"[Agent 1] ⚠ {nct_id}: registry eligibility segmentation: "
              f"{segmented.describe_rejections(segmented.failures)}")
    criteria = segmented.criteria()
    inclusion = criteria[SectionKind.INCLUSION.value]
    exclusion = criteria[SectionKind.EXCLUSION.value]

    return TrialData(
        nct_id=nct_id,
        title=title,
        conditions=conditions,
        interventions=interventions,
        inclusion_criteria=inclusion,
        exclusion_criteria=exclusion,
        primary_outcomes=primary_outcomes,
        study_type=study_type,
        phase=phase,
    )


def load_trial_data_from_file(json_path: str) -> TrialData:
    """
    Load trial data from a local JSON file (ClinicalTrials.gov API v2 format).
    
    Args:
        json_path: Path to the JSON file
        
    Returns:
        TrialData with parsed eligibility criteria and metadata
        
    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If JSON cannot be parsed
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"NCT JSON file not found: {json_path}")
    
    print(f"[Agent 1] 📂 Loading trial data from {path.name}...")
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Extract NCT ID from the data or filename
    protocol = data.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    nct_id = identification.get("nctId", path.stem)
    
    trial_data = _parse_protocol_to_trial_data(data, nct_id)
    
    print(f"[Agent 1] ✅ {nct_id}: {len(trial_data.inclusion_criteria)} inclusion, "
          f"{len(trial_data.exclusion_criteria)} exclusion criteria (from local file)")
    return trial_data


def fetch_trial_data(nct_id: str, timeout: int = 30, cache_dir: Optional[str] = None) -> TrialData:
    """
    Fetch trial protocol data from ClinicalTrials.gov API v2.
    Optionally caches the raw JSON for offline reuse.
    
    Args:
        nct_id: ClinicalTrials.gov identifier (e.g., "NCT01932190")
        timeout: Request timeout in seconds
        cache_dir: Directory to cache raw JSON. None disables caching.
        
    Returns:
        TrialData with parsed eligibility criteria and metadata
        
    Raises:
        ValueError: If NCT ID format is invalid
        ConnectionError: If API request fails
    """
    # Validate NCT ID format
    nct_id = nct_id.strip().upper()
    if not re.match(r'^NCT\d{8}$', nct_id):
        raise ValueError(f"Invalid NCT ID format: '{nct_id}'. Expected format: NCT########")
    
    print(f"[Agent 1] 📡 Fetching {nct_id} from ClinicalTrials.gov...")
    
    url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"
    params = {"format": "json"}
    
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Failed to fetch {nct_id}: {e}")
    
    # Cache raw JSON if cache_dir is specified
    if cache_dir:
        cache_path = Path(cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)
        json_file = cache_path / f"{nct_id}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[Agent 1] 💾 Cached raw JSON to {json_file}")
    
    trial_data = _parse_protocol_to_trial_data(data, nct_id)
    
    print(f"[Agent 1] ✅ {nct_id}: {len(trial_data.inclusion_criteria)} inclusion, "
          f"{len(trial_data.exclusion_criteria)} exclusion criteria")
    return trial_data


def fetch_or_load_trial_data(
    nct_id: str, 
    cache_dir: Optional[str] = None,
    timeout: int = 30
) -> TrialData:
    """
    Load trial data from cache if available, otherwise fetch from API and cache.
    
    Args:
        nct_id: ClinicalTrials.gov identifier (e.g., "NCT01730534")
        cache_dir: Directory for cached JSON files. Defaults to data/nct_cache/
        timeout: Request timeout in seconds
        
    Returns:
        TrialData with parsed eligibility criteria and metadata
    """
    nct_id = nct_id.strip().upper()
    cache = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    cached_file = cache / f"{nct_id}.json"
    
    if cached_file.exists():
        print(f"[Agent 1] 📦 Found cached data for {nct_id}")
        return load_trial_data_from_file(str(cached_file))
    
    print(f"[Agent 1] 📡 No cache found, fetching {nct_id} from API...")
    return fetch_trial_data(nct_id, timeout=timeout, cache_dir=str(cache))


def eligibility_source_text(raw: str) -> str:
    """The registry's eligibility text as the segmentation step reads it.

    ClinicalTrials.gov API v2 returns the field as Markdown, which escapes the comparison
    signs (``=\\>`` for ``=>``). Unescaping them is reading a machine format, and it is done
    before the model sees the text so that the fragments it quotes are substrings of what
    is sliced.

    :param raw: ``eligibilityModule.eligibilityCriteria``.
    :returns: the same text with the Markdown escapes of ``>`` and ``<`` removed.
    """
    return (raw or "").replace("\\>", ">").replace("\\<", "<")
