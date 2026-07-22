#!/usr/bin/env python3
"""
OHDSI Studies GitHub org에서 모든 연구의 코호트 JSON을 다운로드하는 스크립트

- github.com/ohdsi-studies/ 에서 모든 repo 조회
- 각 repo의 inst/cohorts/ 폴더에서 JSON 파일 다운로드

사용법:
    python3 scripts/fetch_ohdsi_studies.py

Note: GitHub API rate limit (60 req/hr unauthenticated) 있음
     더 빨리 받으려면 환경변수 GITHUB_TOKEN 설정
"""
import urllib.request
import json
import time
import os
from pathlib import Path

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("💡 tqdm 설치하면 이쁜 프로그레스 바가 나옵니다: pip install tqdm")

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "ohdsi_studies"
GITHUB_API = "https://api.github.com"
RAW_URL = "https://raw.githubusercontent.com"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

def make_request(url, retries=3):
    """GitHub API 요청 (rate limit 고려, 자동 재시도)"""
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "OHDSI-Studies-Fetcher")
    if GITHUB_TOKEN:
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            elif e.code == 403:  # Rate limit
                reset_time = e.headers.get("X-RateLimit-Reset")
                if reset_time and attempt < retries - 1:
                    wait_secs = max(int(reset_time) - int(time.time()), 60)
                    print(f"\n⚠️ Rate limit! Waiting {wait_secs}s... (Ctrl+C to stop)")
                    time.sleep(wait_secs)
                    continue
                else:
                    raise
            raise
    return None

def get_all_repos():
    """ohdsi-studies org의 모든 public repo 조회 (pagination 처리)"""
    repos = []
    page = 1
    while True:
        url = f"{GITHUB_API}/orgs/ohdsi-studies/repos?per_page=100&page={page}"
        data = make_request(url)
        if not data:
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
        time.sleep(0.5)
    return repos

def get_cohort_files(repo_name, branch="master"):
    """repo의 inst/cohorts/ 폴더에서 JSON 파일 목록 조회"""
    # 먼저 main 브랜치 시도, 없으면 master
    for br in [branch, "main"]:
        url = f"{GITHUB_API}/repos/ohdsi-studies/{repo_name}/contents/inst/cohorts?ref={br}"
        data = make_request(url)
        if data:
            return [(f["name"], f["download_url"], br) for f in data if f["name"].endswith(".json")]
    return []

def download_file(url, output_path):
    """Raw 파일 다운로드 및 포맷팅 (인코딩 폴백 지원)"""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "OHDSI-Studies-Fetcher")
    
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw_bytes = resp.read()
    
    # 인코딩 폴백: utf-8 → latin-1 → utf-8 with replace
    content = None
    for encoding in ["utf-8", "latin-1", "cp1252"]:
        try:
            content = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    
    if content is None:
        content = raw_bytes.decode("utf-8", errors="replace")
    
    try:
        data = json.loads(content)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return data
    except json.JSONDecodeError:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        return None

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. 모든 repo 조회
    print("📋 Fetching ohdsi-studies repository list...")
    repos = get_all_repos()
    print(f"Found {len(repos)} repositories")
    
    # repo 메타데이터 저장
    repo_metadata = [{"name": r["name"], "description": r.get("description", ""), 
                      "url": r["html_url"], "topics": r.get("topics", [])} for r in repos]
    with open(OUTPUT_DIR / "repositories.json", "w", encoding="utf-8") as f:
        json.dump(repo_metadata, f, indent=2, ensure_ascii=False)
    
    # 2. 각 repo에서 cohort 파일 찾아서 다운로드
    all_cohorts = {}
    total_files = 0
    failed = []
    
    if HAS_TQDM:
        pbar = tqdm(repos, desc="🔍 Scanning repos", unit="repo",
                    bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]")
    else:
        pbar = repos
    
    for i, repo in enumerate(pbar):
        repo_name = repo["name"]
        
        # Skip already downloaded repos
        repo_dir = OUTPUT_DIR / repo_name
        if repo_dir.exists() and any(repo_dir.glob("*.json")):
            if HAS_TQDM:
                pbar.set_postfix_str(f"SKIP {repo_name[:20]}")
            else:
                print(f"[{i+1}/{len(repos)}] {repo_name}... SKIP (already exists)")
            continue
        
        if HAS_TQDM:
            pbar.set_postfix_str(f"{repo_name[:25]}...")
        else:
            print(f"[{i+1}/{len(repos)}] {repo_name}...", end=" ", flush=True)
        
        # inst/cohorts/ 폴더 확인
        cohort_files = get_cohort_files(repo_name)
        
        if cohort_files:
            # 폴더 생성
            repo_dir = OUTPUT_DIR / repo_name
            repo_dir.mkdir(exist_ok=True)
            
            cohort_info = []
            for filename, download_url, branch in cohort_files:
                output_path = repo_dir / filename
                try:
                    data = download_file(download_url, output_path)
                    cs_count = len(data.get("ConceptSets", [])) if data else 0
                    cohort_info.append({
                        "file": filename,
                        "conceptSets": cs_count
                    })
                    total_files += 1
                    time.sleep(0.1)
                except Exception as e:
                    failed.append(f"{repo_name}/{filename}: {e}")
            
            all_cohorts[repo_name] = {
                "description": repo.get("description", ""),
                "url": repo["html_url"],
                "cohort_count": len(cohort_info),
                "cohorts": cohort_info
            }
            
            if not HAS_TQDM:
                print(f"✓ ({len(cohort_info)} cohorts)")
        else:
            if not HAS_TQDM:
                print("- (no cohorts)")
        
        time.sleep(0.2)  # Rate limit
    
    # 3. 요약 저장
    summary = {
        "total_repos": len(repos),
        "repos_with_cohorts": len(all_cohorts),
        "total_cohort_files": total_files,
        "failed": len(failed)
    }
    
    with open(OUTPUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    with open(OUTPUT_DIR / "all_studies_cohorts.json", "w", encoding="utf-8") as f:
        json.dump(all_cohorts, f, indent=2, ensure_ascii=False)
    
    if failed:
        with open(OUTPUT_DIR / "failed.txt", "w") as f:
            f.write("\n".join(failed))
    
    print(f"\n=== 완료 ===")
    print(f"저장 위치: {OUTPUT_DIR}")
    print(f"총 repos: {len(repos)}")
    print(f"코호트 있는 repos: {len(all_cohorts)}")
    print(f"다운로드한 cohort 파일: {total_files}")
    if failed:
        print(f"실패: {len(failed)} (failed.txt 참조)")

if __name__ == "__main__":
    main()
