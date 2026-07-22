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
    
    inclusion, exclusion = _parse_criteria_text(criteria_text)
    
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


def _parse_criteria_text(text: str) -> tuple[List[str], List[str]]:
    """
    Parse raw eligibility criteria text into inclusion/exclusion lists.
    
    Handles common ClinicalTrials.gov formatting:
    - "Inclusion Criteria:" / "Exclusion Criteria:" headers
    - Numbered items (1., 2., ...) or bullet points (-, *, •)
    """
    if not text:
        return [], []
    
    # Split by exclusion/non-inclusion header
    parts = re.split(
        r'(?:exclusion|non-inclusion)\s*criteria\s*:?',
        text,
        flags=re.IGNORECASE
    )
    
    inc_text = parts[0]
    exc_text = parts[1] if len(parts) > 1 else ""
    
    # Remove "Inclusion Criteria:" header
    inc_text = re.sub(r'^inclusion\s*criteria\s*:?\s*', '', inc_text, flags=re.IGNORECASE)
    
    inclusion = _parse_items(inc_text)
    exclusion = _parse_items(exc_text)
    
    return inclusion, exclusion


def _parse_items(text: str) -> List[str]:
    """Parse numbered/bulleted items from criteria text.
    
    Handles both:
    - Newline-separated items (standard format)
    - Inline dash-separated items: "- item1 - item2 - item3" (common in API v2)
    
    Codex-reviewed: regex uses negative lookaround for digits to avoid
    splitting numeric ranges like "18 - 60 years".
    """
    items = []
    
    # Check if text has newlines with bullets/numbers
    has_newline_items = bool(re.search(r'\n\s*[\d•\-\*]', text))
    
    if has_newline_items:
        # Standard: split by newline + number/bullet
        lines = re.split(r'\n\s*\d+\.?\s*|\n\s*[•\-\*]\s*', text)
    else:
        # Inline: split on spaced dashes that are list markers, not numeric ranges.
        # (?<!\d) = not preceded by digit, (?!\d) = not followed by digit
        # This correctly splits "Type 2 diabetes - Age min. 50 years"
        # but preserves "18 - 60 years" and "long-acting" (no spaces around hyphen).
        lines = re.split(r'(?<!\d)\s+-\s+(?!\d)', text)
    
    for line in lines:
        line = line.strip()
        # Clean up escaped characters
        line = line.replace('\\>', '>').replace('\\<', '<')
        # Remove sub-bullets content (keep only main item)
        line = re.sub(r'\n\s*\*\s*.*', '', line, flags=re.DOTALL)
        # Keep items with meaningful content (lowered from 10 to avoid dropping
        # short but valid criteria like "Male only" or "Age 18+")
        if line and len(line) > 5:
            items.append(line)
    
    return items


