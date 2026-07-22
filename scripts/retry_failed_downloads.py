#!/usr/bin/env python3
"""
실패한 cohort JSON 파일만 재다운로드 (인코딩 폴백 적용)
"""
import urllib.request
import json
import os
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "ohdsi_studies"
RAW_URL = "https://raw.githubusercontent.com/ohdsi-studies"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# failed.txt에서 파싱한 실패 목록
FAILED_FILES = [
    ("ScyllaCharacterization", "143.json"),
    ("HERACharacterization", "4266367003.json"),
    ("PhenotypePhebruary", "118.json"),
    ("Troy", "105.json"), ("Troy", "106.json"), ("Troy", "107.json"),
    ("Troy", "108.json"), ("Troy", "109.json"), ("Troy", "110.json"),
    ("Troy", "117.json"), ("Troy", "118.json"), ("Troy", "127.json"),
    ("Troy", "128.json"), ("Troy", "135.json"), ("Troy", "136.json"),
    ("Troy", "137.json"), ("Troy", "138.json"), ("Troy", "139.json"),
    ("Troy", "140.json"), ("Troy", "141.json"), ("Troy", "142.json"),
    ("Troy", "15.json"), ("Troy", "17.json"), ("Troy", "19.json"),
    ("Troy", "20.json"), ("Troy", "21.json"), ("Troy", "24.json"),
    ("PhenotypePhebruary2023", "221.json"),
    ("PhenotypePhebruary2023", "305.json"),
    ("CovidVaccineRapidCycleAnalyses", "GuillainBarrSyndrome.json"),
]

def download_with_fallback(url, output_path):
    """인코딩 폴백 적용 다운로드"""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "OHDSI-Studies-Fetcher")
    if GITHUB_TOKEN:
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw_bytes = resp.read()
    
    # 인코딩 폴백: utf-8 → latin-1 → cp1252 → replace
    content = None
    for encoding in ["utf-8", "latin-1", "cp1252"]:
        try:
            content = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    
    if content is None:
        content = raw_bytes.decode("utf-8", errors="replace")
    
    data = json.loads(content)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data

def main():
    success = 0
    failed = []
    
    for repo_name, filename in FAILED_FILES:
        # master or main 브랜치 시도
        for branch in ["master", "main"]:
            url = f"{RAW_URL}/{repo_name}/{branch}/inst/cohorts/{filename}"
            output_path = OUTPUT_DIR / repo_name / filename
            
            try:
                data = download_with_fallback(url, output_path)
                cs_count = len(data.get("ConceptSets", [])) if data else 0
                print(f"✓ {repo_name}/{filename} (CS: {cs_count})")
                success += 1
                break
            except urllib.error.HTTPError as e:
                if e.code == 404 and branch == "master":
                    continue  # try main branch
                failed.append(f"{repo_name}/{filename}: HTTP {e.code}")
                print(f"✗ {repo_name}/{filename}: HTTP {e.code}")
                break
            except Exception as e:
                failed.append(f"{repo_name}/{filename}: {e}")
                print(f"✗ {repo_name}/{filename}: {e}")
                break
    
    print(f"\n=== 완료 ===")
    print(f"성공: {success}/{len(FAILED_FILES)}")
    if failed:
        print(f"실패: {len(failed)}")
        for f in failed:
            print(f"  - {f}")

if __name__ == "__main__":
    main()
