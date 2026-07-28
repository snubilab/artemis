"""Fetch ClinicalTrials.gov protocols rich in numeric eligibility thresholds.

Populates ``data/nct_cache/`` with full study records (same shape the six
pre-existing files use) so the value-constraint corpus can be rebuilt offline.

Selection is query-driven rather than hand-picked: each query targets a
therapeutic area whose eligibility criteria are known to carry lab thresholds,
and requires a threshold phrase to appear in the eligibility text itself via
the ``AREA[EligibilityCriteria]`` field selector.

Usage:
    .venv/bin/python scripts/fetch_threshold_protocols.py
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://clinicaltrials.gov/api/v2/studies"
CACHE = Path(__file__).resolve().parent.parent / "data" / "nct_cache"

# (label, query.term, query.cond) - one row per therapeutic area x phrasing probe.
QUERIES: list[tuple[str, str, str]] = [
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

PER_QUERY = 6


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "artemis-corpus/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search(term: str, cond: str, page_size: int) -> list[str]:
    """Return NCT ids for one area probe, newest-first with results preferred."""
    params = {
        "query.term": term,
        "query.cond": cond,
        "filter.overallStatus": "COMPLETED",
        "pageSize": str(page_size),
        "fields": "NCTId",
        "sort": "StudyFirstPostDate:desc",
    }
    data = _get(f"{API}?{urllib.parse.urlencode(params)}")
    return [s["protocolSection"]["identificationModule"]["nctId"] for s in data.get("studies", [])]


def fetch_full(nct_id: str) -> dict:
    return _get(f"{API}/{nct_id}")


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in CACHE.glob("NCT*.json")}
    wanted: dict[str, str] = {}

    for label, term, cond in QUERIES:
        try:
            for nct_id in search(term, cond, PER_QUERY):
                wanted.setdefault(nct_id, label)
        except OSError as exc:  # network/HTTP failure on one probe must not abort the run
            print(f"[warn] search {label} failed: {exc}")
        time.sleep(0.3)

    todo = [n for n in wanted if n not in existing]
    print(f"{len(wanted)} candidates, {len(todo)} new")

    for i, nct_id in enumerate(todo, 1):
        try:
            record = fetch_full(nct_id)
        except OSError as exc:
            print(f"[warn] fetch {nct_id} failed: {exc}")
            continue
        eligibility = (
            record.get("protocolSection", {}).get("eligibilityModule", {}).get("eligibilityCriteria", "")
        )
        if not eligibility:
            print(f"[skip] {nct_id} has no eligibilityCriteria")
            continue
        (CACHE / f"{nct_id}.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        print(f"[{i}/{len(todo)}] {nct_id} ({wanted[nct_id]}) {len(eligibility)} chars")
        time.sleep(0.3)


if __name__ == "__main__":
    main()
