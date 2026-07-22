# 2026-03-25: PMC Enrichment Pipeline & Supplement Upload UI

## Summary

Added PMC full-text and supplementary PDF enrichment to the NCT import
pipeline, plus a user-facing PDF upload UI in the trial preview panel.
Improved all TTE error messages to be user-friendly.

## Changes

### PMC Enrichment Pipeline (backend)

- **pmc_fetcher.py**: PMID -> PMCID conversion (NCBI ID Converter API),
  PMC full-text XML fetch (efetch), eligibility section extraction with
  3-strategy heuristic (heading match -> keyword context -> methods fallback)
- **pmc_supplement.py**: PMC OA API file listing, tgz package download and
  extraction, PDF filename classification (supplement/appendix/main)
- **parser.py `_enrich_from_pubmed`**: Updated priority chain:
  1. PMC supplement PDFs (most complete eligibility criteria)
  2. PMC full-text eligibility section
  3. PubMed abstract (existing fallback)
- Each step wrapped in try/except to gracefully fall through

### Real-World Testing

- LEADER (NCT01179048): PMC full-text extraction successful — 9 inclusion,
  10 exclusion criteria from PMID 27295427 (PMC4985288)
- PMC OA supplement download blocked for major journals (NEJM, Lancet) —
  articles are in PMC but not Open Access. Supplement PDF auto-download
  only works for OA journal papers.
- Solution: manual PDF upload by user (see below)

### Supplement PDF Upload (backend + frontend)

- **Backend**: `POST /tte/papers/{nct_id}/upload` (save PDF to
  `data/papers/{NCT_ID}/`), `GET /tte/papers/{nct_id}` (list with roles)
- **Frontend**: Upload area in trial preview panel after Preview Trial click.
  Dashed border, "Choose PDF" button, uploaded file badges, error display.
- On Import Trial, `parse_nct._discover_pdfs` auto-discovers uploaded PDFs.

### ATLAS Cohort Editor Fix

- `atlas.cohort-editor`: Added `currentCohortDefinitionMode` view switching.
  Definition/Concept Sets buttons now toggle content via `conceptset-list`.

### UX Improvements

- Disabled "Next Required Action" banner
- Removed verbose preview/import description texts
- NCT 404 error: "Trial NCTxxxxxxxx was not found on ClinicalTrials.gov"
- All 26 TTEService error messages rewritten: "Could not [action]. [guidance]."

## Test Coverage

| File | Tests |
|------|-------|
| test_pmc_fetcher.py | 16 |
| test_pmc_supplement.py | 27 |
| test_pmc_integration.py | 13 (4 preset trials) |
| test_tte_upload.py | 5 |
| **Total new** | **61** |

## Known Limitations

- PMC OA supplement auto-download only works for Open Access articles
- `extract_eligibility_section` regex may miss some article structures
  (EMPA-REG partial extraction observed)
- `python-multipart` pip dependency needed for upload endpoint
