"""Fetch ClinicalTrials.gov protocols into ``data/nct_cache/``.

Populates the cache with full study records (same shape the six pre-existing
files use) so the value-constraint corpus and the elided-head measurement can
be rebuilt offline.

Three sampling frames, kept separate because they answer different questions:

``threshold``
    The original 14 probes. Each requires a threshold phrase to appear in the
    eligibility text via ``AREA[EligibilityCriteria]``, scoped by condition and
    restricted to COMPLETED trials. Good for harvesting threshold *surface
    forms*; useless for estimating how *often* anything happens, because the
    sample is selected on the presence of a threshold.

``cond``
    Condition-only probes across therapeutic areas well outside the original
    cardiometabolic/oncology/renal skew. No eligibility-text term and no status
    filter, so nothing about the number being measured enters the selection.

``year``
    No query at all, sliced by ``StudyFirstPostDate`` year. This is the closest
    thing the API offers to a registry-wide sample and it supplies the recency
    strata used to test whether the elided-head rate drifts over time.

Sponsor class, therapeutic area and posting year are all present in the fetched
record, so those strata are derived post hoc rather than probed for.

Usage:
    .venv/bin/python scripts/fetch_threshold_protocols.py
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://clinicaltrials.gov/api/v2/studies"
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "nct_cache"
MANIFEST = CACHE / "_manifest.json"

SLEEP_SECONDS = 0.35

# (label, query.term, query.cond) - one row per therapeutic area x phrasing probe.
THRESHOLD_QUERIES: list[tuple[str, str, str]] = [
    ("cardiometabolic-uln", 'AREA[EligibilityCriteria]"upper limit of normal"', "type 2 diabetes"),
    ("cardiometabolic-bmi", 'AREA[EligibilityCriteria]"body mass index"', "type 2 diabetes"),
    ("cardiometabolic-hba1c", 'AREA[EligibilityCriteria]"HbA1c"', "cardiovascular disease"),
    ("renal-egfr", 'AREA[EligibilityCriteria]"eGFR"', "chronic kidney disease"),
    ("renal-creatinine", 'AREA[EligibilityCriteria]"creatinine clearance"', "renal insufficiency"),
    ("anticoag-inr", 'AREA[EligibilityCriteria]"upper limit of normal"', "atrial fibrillation"),
    ("anticoag-platelet", 'AREA[EligibilityCriteria]"platelet count"', "venous thromboembolism"),
    ("acs-troponin", 'AREA[EligibilityCriteria]"troponin"', "acute coronary syndrome"),
    ("oncology-anc", 'AREA[EligibilityCriteria]"absolute neutrophil count"', "breast cancer"),
    ("oncology-bilirubin", 'AREA[EligibilityCriteria]"institutional upper limit of normal"', "lung cancer"),
    ("oncology-transaminase", 'AREA[EligibilityCriteria]"x ULN"', "lymphoma"),
    ("heartfailure-lvef", 'AREA[EligibilityCriteria]"ejection fraction"', "heart failure"),
    ("hepatic-lln", 'AREA[EligibilityCriteria]"lower limit of normal"', "hepatitis"),
    ("lipid-ldl", 'AREA[EligibilityCriteria]"LDL cholesterol"', "hyperlipidemia"),
]
THRESHOLD_PER_QUERY = 6

# Condition-only probes. Deliberately spans specialties the original frame never
# touched (psychiatry, neurology, ID, derm, ophthalmology, OB, peds, dental,
# rehab, addiction, pain, sleep, allergy, vaccines, surgery, rare disease).
COND_QUERIES: list[str] = [
    "schizophrenia",
    "major depressive disorder",
    "bipolar disorder",
    "generalized anxiety disorder",
    "attention deficit hyperactivity disorder",
    "autism spectrum disorder",
    "alzheimer disease",
    "parkinson disease",
    "multiple sclerosis",
    "epilepsy",
    "migraine",
    "stroke rehabilitation",
    "chronic low back pain",
    "osteoarthritis",
    "rheumatoid arthritis",
    "psoriasis",
    "atopic dermatitis",
    "acne vulgaris",
    "glaucoma",
    "age related macular degeneration",
    "dry eye disease",
    "asthma",
    "chronic obstructive pulmonary disease",
    "cystic fibrosis",
    "obstructive sleep apnea",
    "tuberculosis",
    "malaria",
    "influenza vaccine",
    "hiv infection",
    "covid-19",
    "sepsis",
    "inflammatory bowel disease",
    "irritable bowel syndrome",
    "gastroesophageal reflux disease",
    "obesity",
    "osteoporosis",
    "thyroid disorders",
    "preterm birth",
    "preeclampsia",
    "contraception",
    "neonatal jaundice",
    "smoking cessation",
    "alcohol use disorder",
    "opioid use disorder",
    "periodontitis",
    "wound healing",
    "postoperative pain",
    "anesthesia",
    "sickle cell disease",
    "hemophilia",
    "spinal muscular atrophy",
    "duchenne muscular dystrophy",
    "urinary incontinence",
    "benign prostatic hyperplasia",
    "infertility",
    "anemia",
    "frailty elderly",
    "palliative care",
]
COND_PER_QUERY = 8

# Registry-wide slices with no query term at all, one per posting year.
YEARS: list[int] = list(range(2005, 2027))
YEAR_PER_QUERY = 8


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "artemis-corpus/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _search(params: dict[str, str]) -> list[str]:
    merged = {"fields": "NCTId", **params}
    data = _get(f"{API}?{urllib.parse.urlencode(merged)}")
    return [s["protocolSection"]["identificationModule"]["nctId"] for s in data.get("studies", [])]


def search_threshold(term: str, cond: str, page_size: int) -> list[str]:
    """Original frame: eligibility text must contain the probe phrase."""
    return _search(
        {
            "query.term": term,
            "query.cond": cond,
            "filter.overallStatus": "COMPLETED",
            "pageSize": str(page_size),
            "sort": "StudyFirstPostDate:desc",
        }
    )


def search_condition(cond: str, page_size: int) -> list[str]:
    """Condition-only frame: no eligibility term, no status filter."""
    return _search({"query.cond": cond, "pageSize": str(page_size), "sort": "@relevance"})


def search_year(year: int, page_size: int) -> list[str]:
    """Registry-wide frame: one slice per first-post year, no query term."""
    return _search(
        {
            "filter.advanced": f"AREA[StudyFirstPostDate]RANGE[{year}-01-01,{year}-12-31]",
            "pageSize": str(page_size),
            "sort": "StudyFirstPostDate:asc",
        }
    )


def fetch_full(nct_id: str) -> dict:
    return _get(f"{API}/{nct_id}")


def collect_candidates() -> dict[str, tuple[str, str]]:
    """Return ``{nct_id: (frame, probe_label)}``, first frame to claim an id wins."""
    wanted: dict[str, tuple[str, str]] = {}

    def add(frame: str, label: str, ids: list[str]) -> None:
        for nct_id in ids:
            wanted.setdefault(nct_id, (frame, label))

    for label, term, cond in THRESHOLD_QUERIES:
        try:
            add("threshold", label, search_threshold(term, cond, THRESHOLD_PER_QUERY))
        except OSError as exc:  # one dead probe must not abort the run
            print(f"[warn] threshold probe {label} failed: {exc}")
        time.sleep(SLEEP_SECONDS)

    for cond in COND_QUERIES:
        try:
            add("cond", cond, search_condition(cond, COND_PER_QUERY))
        except OSError as exc:
            print(f"[warn] cond probe {cond} failed: {exc}")
        time.sleep(SLEEP_SECONDS)

    for year in YEARS:
        try:
            add("year", str(year), search_year(year, YEAR_PER_QUERY))
        except OSError as exc:
            print(f"[warn] year probe {year} failed: {exc}")
        time.sleep(SLEEP_SECONDS)

    return wanted


def load_manifest() -> dict[str, dict[str, str]]:
    if not MANIFEST.exists():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in CACHE.glob("NCT*.json")}
    manifest = load_manifest()

    # Cache files predating the manifest all came from the threshold frame.
    for nct_id in existing:
        manifest.setdefault(nct_id, {"frame": "threshold", "probe": "legacy"})

    wanted = collect_candidates()
    todo = [n for n in wanted if n not in existing]
    print(f"{len(wanted)} candidates, {len(existing)} cached, {len(todo)} new")

    kept = 0
    for i, nct_id in enumerate(todo, 1):
        frame, label = wanted[nct_id]
        try:
            record = fetch_full(nct_id)
        except (OSError, urllib.error.HTTPError) as exc:
            print(f"[warn] fetch {nct_id} failed: {exc}")
            continue
        eligibility = (
            record.get("protocolSection", {}).get("eligibilityModule", {}).get("eligibilityCriteria", "")
        )
        if not eligibility:
            print(f"[skip] {nct_id} has no eligibilityCriteria")
            time.sleep(SLEEP_SECONDS)
            continue
        (CACHE / f"{nct_id}.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        manifest[nct_id] = {"frame": frame, "probe": label}
        kept += 1
        print(f"[{i}/{len(todo)}] {nct_id} ({frame}/{label}) {len(eligibility)} chars")
        time.sleep(SLEEP_SECONDS)

    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"kept {kept} new records; manifest now covers {len(manifest)} ids")


if __name__ == "__main__":
    main()
