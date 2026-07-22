#!/usr/bin/env python3
"""
OHDSI PhenotypeLibrary에서 모든 코호트 정의와 Concept Sets를 다운로드하는 스크립트
- Cohorts.csv 메타데이터를 먼저 가져와서 코호트 이름을 파일명에 포함
- 파일명 형식: {cohortId}_{cohortName}.json

Source: https://github.com/OHDSI/PhenotypeLibrary

사용법:
    python3 scripts/fetch_phenotype_library.py
"""
import urllib.request
import json
import csv
import time
from pathlib import Path
from io import StringIO

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("💡 tqdm 설치하면 더 멋진 프로그레스 바를 볼 수 있어요: pip install tqdm")

RAW_URL = "https://raw.githubusercontent.com/OHDSI/PhenotypeLibrary/main"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "phenotype_library"

def fetch_csv_metadata():
    """Cohorts.csv 메타데이터 다운로드 및 파싱"""
    print("Fetching Cohorts.csv metadata...")
    url = f"{RAW_URL}/inst/Cohorts.csv"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "OHDSI-Fetcher")
    
    with urllib.request.urlopen(req, timeout=60) as resp:
        content = resp.read().decode("utf-8-sig")  # BOM 처리
    
    reader = csv.DictReader(StringIO(content))
    metadata = {}
    for row in reader:
        cohort_id = row.get("cohortId", "").strip()
        if cohort_id:
            metadata[cohort_id] = {
                "name": row.get("cohortName", "").strip(),
                "description": row.get("logicDescription", "").strip(),
                "status": row.get("status", "").strip(),
                "hashtags": row.get("hashTag", "").strip(),
                "librarian": row.get("librarian", "").strip(),
            }
    print(f"Found {len(metadata)} cohorts in metadata")
    return metadata

def safe_filename(name):
    """안전한 파일명 생성"""
    if not name:
        return "unknown"
    # 특수문자 제거 및 길이 제한
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    return safe.strip()[:60]

def download_cohort(cohort_id, output_path):
    """코호트 JSON 다운로드"""
    url = f"{RAW_URL}/inst/cohorts/{cohort_id}.json"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "OHDSI-Fetcher")
    
    with urllib.request.urlopen(req, timeout=60) as resp:
        content = resp.read().decode("utf-8")
    
    data = json.loads(content)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cohorts_dir = OUTPUT_DIR / "cohorts"
    cohorts_dir.mkdir(exist_ok=True)
    
    # 1. 메타데이터 가져오기
    metadata = fetch_csv_metadata()
    
    # 메타데이터 저장
    with open(OUTPUT_DIR / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    # 2. 각 코호트 다운로드
    all_concept_sets = {}
    success, failed = 0, 0
    download_log = []
    
    items = list(metadata.items())
    if HAS_TQDM:
        pbar = tqdm(items, desc="📥 Downloading", unit="cohort", 
                    bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]")
    else:
        pbar = items
    
    for i, (cohort_id, info) in enumerate(pbar):
        name = info["name"]
        safe_name = safe_filename(name)
        filename = f"{cohort_id}_{safe_name}.json"
        output_path = cohorts_dir / filename
        
        if HAS_TQDM:
            pbar.set_postfix_str(f"{name[:30]}...")
        else:
            print(f"[{i+1}/{len(metadata)}] {cohort_id}: {name[:40]}...", end=" ", flush=True)
        
        try:
            data = download_cohort(cohort_id, output_path)
            
            # ConceptSets 추출
            cs = data.get("ConceptSets", [])
            if cs:
                all_concept_sets[cohort_id] = {
                    "name": name,
                    "file": filename,
                    "concept_sets": [{"id": c.get("id"), "name": c.get("name")} for c in cs]
                }
            
            download_log.append({
                "cohortId": cohort_id,
                "name": name,
                "file": filename,
                "conceptSets": len(cs),
                "status": "OK"
            })
            
            if not HAS_TQDM:
                print(f"OK (CS: {len(cs)})")
            success += 1
            time.sleep(0.1)
            
        except Exception as e:
            if not HAS_TQDM:
                print(f"FAILED: {e}")
            download_log.append({
                "cohortId": cohort_id,
                "name": name,
                "status": "FAILED",
                "error": str(e)
            })
            failed += 1
    
    # 3. 요약 저장
    summary = {
        "total_cohorts": len(metadata),
        "success": success,
        "failed": failed,
        "cohorts_with_concept_sets": len(all_concept_sets),
        "total_concept_sets": sum(len(v["concept_sets"]) for v in all_concept_sets.values())
    }
    
    with open(OUTPUT_DIR / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    with open(OUTPUT_DIR / "download_log.json", "w", encoding="utf-8") as f:
        json.dump(download_log, f, indent=2, ensure_ascii=False)
    
    with open(OUTPUT_DIR / "all_concept_sets.json", "w", encoding="utf-8") as f:
        json.dump(all_concept_sets, f, indent=2, ensure_ascii=False)
    
    print(f"\n=== 완료 ===")
    print(f"저장 위치: {OUTPUT_DIR}")
    print(f"성공: {success}, 실패: {failed}")
    print(f"Concept Sets 포함 코호트: {len(all_concept_sets)}")
    print(f"총 Concept Sets: {summary['total_concept_sets']}")
    print(f"\n파일 형식: {{cohortId}}_{{cohortName}}.json")
    print(f"예: 3_Cough or Sputum.json")

if __name__ == "__main__":
    main()
