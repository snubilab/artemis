#!/usr/bin/env python3
"""
ATLAS Demo에서 모든 코호트 정의를 다운로드하고 포맷팅하는 스크립트

사용법:
    python3 scripts/fetch_all_atlas_cohorts.py
"""
import urllib.request
import json
import time
from pathlib import Path

BASE_URL = "https://atlas-demo.ohdsi.org/WebAPI"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "atlas_cohorts"

def get_cohort_list():
    print("Fetching cohort list...")
    req = urllib.request.Request(f"{BASE_URL}/cohortdefinition")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    print(f"Total cohorts: {len(data)}")
    return data

def fetch_cohort(cohort_id):
    url = f"{BASE_URL}/cohortdefinition/{cohort_id}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if isinstance(data.get("expression"), str):
        data["expression"] = json.loads(data["expression"])
    return data

def safe_filename(name, cohort_id):
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    return f"{cohort_id}_{safe[:80]}.json"

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cohorts = get_cohort_list()
    
    with open(OUTPUT_DIR / "cohort_list.json", "w") as f:
        json.dump(cohorts, f, indent=2)
    
    success, failed, results = 0, 0, []
    
    for i, cohort in enumerate(cohorts):
        cid = cohort.get("id")
        name = cohort.get("name", f"cohort_{cid}")
        
        try:
            print(f"[{i+1}/{len(cohorts)}] {cid}: {name[:50]}...", end=" ", flush=True)
            data = fetch_cohort(cid)
            filename = safe_filename(name, cid)
            
            with open(OUTPUT_DIR / filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            expr = data.get("expression", {})
            print(f"OK (CS:{len(expr.get('ConceptSets', []))}, IR:{len(expr.get('InclusionRules', []))})")
            results.append({"id": cid, "name": name, "file": filename})
            success += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"FAILED: {e}")
            results.append({"id": cid, "error": str(e)})
            failed += 1
    
    with open(OUTPUT_DIR / "summary.json", "w") as f:
        json.dump({"success": success, "failed": failed, "results": results}, f, indent=2)
    
    print(f"\n완료! 저장: {OUTPUT_DIR}\n성공: {success}, 실패: {failed}")

if __name__ == "__main__":
    main()
