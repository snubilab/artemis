# 001_SHARED_CONTEXT: Agent 1 Enhancement

## Existing Types (from src/)

### TrialData (src/agents/agent1/nct_fetcher.py)
```python
class TrialData(BaseModel):
    nct_id: str
    title: str = ""
    conditions: List[str] = Field(default_factory=list)
    interventions: List[str] = Field(default_factory=list)
    inclusion_criteria: List[str] = Field(default_factory=list)
    exclusion_criteria: List[str] = Field(default_factory=list)
    primary_outcomes: List[str] = Field(default_factory=list)
    study_type: str = ""
    phase: str = ""
```

### LogicDecomposer.parse_nct (src/agents/agent1/parser.py)
```python
def parse_nct(self, nct_id: str, json_path: Optional[str] = None) -> ARTEMISRequest:
    # 1. Fetch trial data (NCT API or local JSON)
    # 2. Build prompt with trial_data fields
    # 3. LLM call
    # 4. Parse JSON → ARTEMISRequest
```

## New Types

### PubMedPaper
```python
class PubMedPaper(BaseModel):
    pmid: str
    title: str = ""
    abstract: str = ""
    full_text: Optional[str] = None  # PMC full text if available
    eligibility_section: Optional[str] = None  # Extracted criteria section
```

## APIs Used
- **ClinicalTrials.gov API v2**: `https://clinicaltrials.gov/api/v2/studies/{nct_id}`
  - `referencesModule.references[]` → PMID 링크 포함
- **PubMed E-utilities**: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
  - `esearch.fcgi` → NCT → PMID 검색
  - `efetch.fcgi` → PMID → abstract/full text
- **PubMed Central (PMC)**: Full text access (Open Access subset)

## Key Constants
```python
NCT_API_BASE = "https://clinicaltrials.gov/api/v2/studies"
PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PMC_OA_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
```
