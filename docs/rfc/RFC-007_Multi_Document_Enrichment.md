# RFC-007: Multi-Document Enrichment for Agent 1

**상태**: 검토 중  
**날짜**: 2026-03-01  
**제안자**: @kyh + Codex (gpt-5.3-codex-spark)

## 1. 가설 및 목표

NCT registry에는 전체 criteria의 ~30-50%만 포함. Design paper 본문에는 ~60-70%. **Supplementary Appendix에 100%가 있다.**

현재 Agent 1은 단일 PDF만 처리 가능(`design_paper_pdf`). 다중 문서(main paper + appendix + protocol)를 자동으로 수집하고 병합하는 **범용적 메커니즘**이 필요하다.

## 2. 제안 설계

### 2.1 인터페이스

```python
def parse_nct(
    self,
    nct_id: str,
    json_path: Optional[str] = None,
    enrich_from_pubmed: bool = True,
    design_paper_pdf: Optional[str] = None,  # 하위 호환
    papers: Optional[list[str]] = None,       # 명시적 다중 경로
    papers_dir: Optional[str] = None,         # 자동 탐색 루트
) -> ARTEMISRequest:
```

**우선순위**: `papers` > `papers_dir` auto-discovery > `design_paper_pdf` > `enrich_from_pubmed`

### 2.2 디렉토리 구조

```
data/papers/
└── NCT01179048/
    ├── NEJMoa1603827.pdf           # main paper
    ├── NEJMoa1603827_appendix.pdf  # supplementary
    └── protocol.pdf                # optional
```

파일명 힌트로 역할 유추: `supplement`, `appendix`, `protocol`, `main`, `design`

### 2.3 다중 문서 병합

- 전략: **union + dedupe + source priority**
- 우선순위: supplement > main paper > pubmed abstract > NCT
- 중복 제거: `difflib.SequenceMatcher` (유사도 ≥ 0.8이면 동일 항목)
- 기본 정책: `merge` (replace 아님)

### 2.4 추출 품질 개선

- 1단계: 키워드 확장 (`Eligibility`, `Patient Selection`, `Inclusion and Exclusion`)
- 2단계: 휴리스틱 실패 시 **LLM 폴백** 추출
- 3단계: `.docx` 지원 (python-docx)

### 2.5 Retrieval 전략

| 순위 | 방법 | 비고 |
|:---:|---|---|
| 1 | `papers_dir` 로컬 파일 | 즉시 구현 가능, 안정적 |
| 2 | PMC API + Unpaywall | OA 논문 자동 획득 |
| 3 | Selenium 자동화 | 비용/안정성 문제로 보류 |

## 3. 예상되는 리스크

- Cloudflare/paywall로 자동 다운로드 실패 (NEJM, Lancet, JAMA)
- 스캔 PDF에서 텍스트 추출 실패 (pdftotext 한계)
- `.docx` appendix 미지원 (현재)
- 잘못된 paper를 본문으로 사용하는 위험 (NCT reference 오매칭)
- 문장 변형이 많아 dedupe 오탐/누락 가능

## 4. 해결되지 않은 질문

- LLM 폴백 추출의 token 비용 (52K chars PDF → ~13K tokens)
- 다중 PDF 처리 시 Agent 1 전체 latency 증가 예측?
- Supplementary Appendix가 없는 trial은 어떻게 처리?

## 5. 구현 순서 (최소 변경)

| Step | 내용 | 파일 |
|:---:|---|---|
| 1 | `parse_nct`에 `papers`/`papers_dir` 추가 + 다중 PDF 순회 | `parser.py` |
| 2 | `enricher.py`에 소스별 병합 함수 (우선순위 dedupe) | `enricher.py` |
| 3 | 문서 추출기 분리 (pdf/docx/txt) + heading 보강 | `pubmed_fetcher.py` |
| 4 | 벤치마크 배치 스크립트 | `scripts/` |
