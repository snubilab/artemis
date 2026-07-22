# SPEC-UI-011 Paper Sources Panel - Implementation Log

## Date: 2026-03-30

## Overview

Paper Download Status & URL Guide 기능. Preview Trial 시점에 paper enrichment 상태를 확인하고,
자동 다운로드 시도 → 실패 시 저널 URL 안내 + 업로드 버튼을 제공.

---

## Implemented (Committed: `14851fb`)

### Backend (artemis)

| File | Description |
|------|-------------|
| `src/api/models/tte.py` | `PaperStatus`, `DownloadUrl`, `PaperDownloadInfo`, `DownloadResult` Pydantic 모델 |
| `src/agents/agent1/paper_url_mapper.py` (NEW) | DOI→저널 URL 매핑, `try_download_paper()`, `build_paper_urls()` |
| `src/agents/agent1/parser.py` | `self.last_paper_status` attribute, enrichment 경로별 PaperStatus 수집 |
| `src/services/tte_service.py` | `artifact_meta`에 `paperStatus` 포함, 캐시 호환 |
| `src/api/tte.py` | `GET /tte/papers/{nct_id}/status` 엔드포인트 (Preview 시점 경량 체크) |

### Frontend (atlas-dev)

| File | Description |
|------|-------------|
| `tte-manager.js` | `paperStatus` observable, `paperSourceLabel`/`paperStatusClass`/`showPaperDownloadUrls` computed, `skipPaperDownload()`, Preview 후 `/status` API 호출 |
| `tte-manager.html` | Paper Sources 패널 (상태별 아이콘, 다운로드 카드, Upload/Skip 버튼) |
| `tte-manager.less` | `.paper-sources-panel` 스타일 (success/warning 상태, download card) |

### Tests

| File | Count | Status |
|------|-------|--------|
| `tests/test_paper_status_models.py` | 43 | PASS |
| `tests/test_paper_url_mapper.py` | 49 | PASS |
| `tests/test_parser_paper_status.py` | 5 | PASS |
| `tests/test_service_paper_status.py` | 4 | PASS |

---

## Post-Commit Fixes (Uncommitted, 12 files, +399/-144)

### Fix 1: `tte-progress-indicator.html` 404

- **File**: `components/tte-progress-indicator.js`
- **Problem**: `text!./tte-progress-indicator.html` 상대경로가 require.js baseUrl 기준으로 resolve되어 404
- **Fix**: `text!pages/target-trial-emulation/components/tte-progress-indicator.html` 절대경로로 변경

### Fix 2: `this.studyId is not a function`

- **File**: `tte-manager.js:1036`
- **Problem**: `tabCompletionStates` computed에서 `this.studyId()` 호출 — 존재하지 않는 observable
- **Fix**: `this.studyId()` → `this.analysisId()`

### Fix 3: Preview Trial에서 validation 에러 시 spinner 멈추지 않음

- **File**: `tte-manager.js` `fetchTrialPreview()`
- **Problem**: `NCTPreviewService.normalizeNctId()`가 동기적으로 throw → Promise chain의 `.catch()`에 안 잡힘
- **Fix**: `try-catch`로 동기 에러 포착, `isFetchingPreview(false)` + `previewError()` 즉시 설정

### Fix 4: Paper Sources 패널이 Preview 시점에 안 나타남

- **File**: `tte-manager.js`, `src/api/tte.py`
- **Problem**: `paperStatus`가 Import Trial 완료 후에만 세팅됨
- **Fix**:
  - Backend: `GET /tte/papers/{nct_id}/status` 엔드포인트 추가 (로컬 PDF 체크 + DOI URL 빌드)
  - Frontend: Preview 성공 후 `/artemis-api/tte/papers/{nctId}/status` non-blocking 호출
  - FastAPI 라우터 순서 수정: `/papers/{nct_id}/status`를 `/papers/{nct_id}` 앞으로 이동

### Fix 5-6: 기존 Supplement PDF 섹션 완전 삭제 + 바인딩 수정

- **File**: `tte-manager.html`
- **Fix**: old "Supplement PDF / Choose PDF" 섹션 전체 삭제. `article_url` 바인딩. 저널명/역할 표시 카드 UI.

### Fix 7: PubMed 검색이 design paper 우선하지 않음

- **File**: `src/api/tte.py` (`get_paper_status`)
- **Problem**: `search_pubmed_for_nct()`가 NCT에 연결된 아무 논문을 반환
- **Fix**: ClinicalTrials.gov API에서 NCT 데이터 → `get_design_paper_pmids()` (BACKGROUND 타입 우선). `asyncio.to_thread`로 비동기 처리. referencesModule 없으면 기존 esearch fallback.

### Fix 8: Supplement URL이 Main과 동일

- **File**: `src/agents/agent1/paper_url_mapper.py` (`build_paper_urls`)
- **Fix**: `supp_url`이 None이면 supplement 항목 생성 안 함. NEJM만 실제 supp 카드 표시.

### Fix 9: Supplement hint 텍스트 2줄 줄바꿈

- **File**: `tte-manager.less`
- **Fix**: `max-width: 220px` → `white-space: nowrap`

### Fix 10: `PAPERS_DIR` 경로 오류

- **File**: `src/api/tte.py`
- **Problem**: `parents[3]` = Broadsea/ (repo root) → `data/papers` 없음
- **Fix**: `parents[2]` = artemis/ → `data/papers` 존재

### Fix 11: `classify_supplement` 역할 분류 오류

- **File**: `src/agents/agent1/pmc_supplement.py`
- **Problem**: `NEJMoa1603827.pdf`가 `other` → `supplement`로 잘못 분류
- **Fix**: 기본 반환값 `other` → `main`. `_MAIN_KEYWORDS`에 저널명 추가. `get_paper_status`/`list_papers`에서 `{role}_` prefix 기반 파싱 우선.

### Fix 12: Traefik Host 불일치 404

- **File**: `traefik/routers.yml`
- **Problem**: `BROADSEA_HOST=127.0.0.1` vs `curl Host: localhost` 불일치
- **Fix**: `|| Host('localhost')` 추가

### Fix 13: Role 선택 업로드 UX (신규 기능)

- **Backend** (`src/api/tte.py`, `src/api/models/tte.py`):
  - `POST /papers/{nct_id}/upload?role=main|supplement` — role 파라미터 추가
  - 파일명 `{role}_{original}.pdf` prefix, 동일 role 덮어쓰기
  - `PaperStatus.roles_filled` 필드 추가
- **Frontend** (`tte-manager.js`, `tte-manager.html`, `tte-manager.less`, `TTEService.js`):
  - Role 드롭다운 (Main Paper / Supplement), 기본값 Main Paper
  - `suggestedUploadRole` computed: main이 이미 있으면 자동으로 Supplement 선택
  - 업로드 후 `paperStatus` 자동 갱신
- **Tests** (`tests/test_paper_upload_role.py` NEW): 8개 테스트

### Code Review 피드백 반영

- C1: sync `requests.get` → `asyncio.to_thread` (event loop 블로킹 해소)
- C2: bare `except: pass` → `logger.warning` + `exc_info=True`
- I4: `showPaperUpload` computed 제거 (미사용)
- I5: `uploadPaper()` CSS selector `.tte-paper-upload` → `.paper-sources-panel`
- I2: Dead code `role == "other"` → prefix 기반 파싱으로 대체
- Dead CSS `.tte-paper-upload*` 규칙 삭제

---

## Current State (미커밋)

### 변경 파일 (15개)

| File | Changes |
|------|---------|
| `artemis/src/agents/agent1/paper_url_mapper.py` | supplement URL 중복 제거 |
| `artemis/src/agents/agent1/pmc_supplement.py` | classify_supplement 기본값 main, 저널 키워드 |
| `artemis/src/api/models/tte.py` | `roles_filled` 필드 |
| `artemis/src/api/tte.py` | role upload, PAPERS_DIR 수정, async/logging, prefix 파싱 |
| `artemis/src/utils/llm.py` | `LLMCostTracker`, `_MODEL_COSTS`, `get_cost_tracker()`, token recording |
| `artemis/src/services/tte_service.py` | `llmCost` meta on all return paths, tracker reset |
| `artemis/tests/test_paper_url_mapper.py` | supplement 제거 반영 |
| `artemis/tests/test_pmc_supplement.py` | 기본값 main 반영 |
| `artemis/tests/test_paper_upload_role.py` (NEW) | 8개 upload role 테스트 |
| `atlas-dev/.../tte-progress-indicator.js` | require.js 경로 수정 |
| `atlas-dev/.../services/TTEService.js` | uploadPaper에 role 파라미터 |
| `atlas-dev/.../tte-manager.html` | Step 1/Step 2 분리, Paper Sources 패널, role 드롭다운, skip fallback 문구 |
| `atlas-dev/.../tte-manager.js` | role observable, `paperStatusLoaded`, `lastEligibilityLlmCost`, auto-select, upload 갱신 |
| `atlas-dev/.../tte-manager.less` | `.tte-step2-panel`, `.tte-step2-import-action`, 패널 스타일, dead CSS 삭제 |
| `traefik/routers.yml` | localhost Host 규칙 |

### 테스트 결과

| Suite | Count | Status |
|-------|-------|--------|
| test_paper_upload_role.py | 8 | PASS |
| test_paper_url_mapper.py | 49 | PASS |
| test_paper_status_models.py | 43 | PASS |
| test_pmc_supplement.py | 27 | PASS |
| test_parser_paper_status.py | 5 | PASS |
| test_service_paper_status.py | 4 | PASS |
| **Total** | **136** | **ALL PASS** |

### API 검증 결과

| Trial | `source` | `manual_download_needed` | `roles_filled` |
|-------|----------|--------------------------|----------------|
| LEADER (NCT01179048) | `local` | `false` | `["main", "appendix"]` |
| EMPA-REG (NCT01131676) | `local` | `false` | `["main", "appendix"]` |
| ARISTOTLE (NCT00412984) | `nct_only` | `true` | `[]` |

## Post-Role-Upload UX Fixes (Uncommitted)

### Change 1: Step 1 / Step 2 UI Separation

- **Problem**: Specification tab showed too many buttons at once (Preview Trial, Import Trial, Upload PDF, Skip all at same level)
- **Solution**: Split Specification tab into two explicit sub-steps:

| Step | Heading | Contents |
|------|---------|----------|
| Step 1 | Preview Trial | NCT input, Preset dropdown, Preview button, preview card |
| Step 2 | Import Trial | Paper Sources panel + Import Trial button |

Step 2 only appears after preview succeeds and paper status is loaded.

**Files changed**:

| File | Change |
|------|--------|
| `atlas-dev/.../tte-manager.html` | Restructured into two `panel panel-info` blocks; Step 1 heading renamed from "Trial Import" to "Preview Trial" |
| `atlas-dev/.../tte-manager.less` | Added `.tte-step2-panel` and `.tte-step2-import-action` styles |

---

### Change 2: Paper Sources + Import Trial Simultaneous Appearance

- **Problem**: Paper Sources panel appeared later than Import Trial button because `/papers/{nct_id}/status` API is async; Step 2 gate was `previewStudy()` only
- **Solution**: Added `paperStatusLoaded` observable. Step 2 is now gated on `previewStudy() && paperStatusLoaded()`. The flag is set to `true` on both success and failure of the paper status fetch so a network error does not permanently hide Step 2.

**Files changed**:

| File | Change |
|------|--------|
| `atlas-dev/.../tte-manager.js` | Added `paperStatusLoaded` observable; reset to `false` on new preview; set to `true` after fetch resolves (success or error) |
| `atlas-dev/.../tte-manager.html` | Step 2 `ko if` condition changed from `previewStudy()` to `previewStudy() && paperStatusLoaded()` |

---

### Change 3: Skip Fallback Message

- **Problem**: After clicking "Skip & Continue without paper", Step 2 panel showed empty space with only the Import Trial button
- **Solution**: Added info text when `paperStatus()` is null: "Proceeding with ClinicalTrials.gov data only. No paper PDF will be used for enrichment."

**Files changed**:

| File | Change |
|------|--------|
| `atlas-dev/.../tte-manager.html` | Added `<!-- ko if: !paperStatus() -->` block with info text before Import Trial button |

---

### Change 4: LLM Cost Tracking (Real-Time)

- **Problem**: No visibility into per-run LLM costs during process_eligibility
- **Solution**: Thread-safe `LLMCostTracker` captures Azure OpenAI token usage in real time. Cost summary is returned in the `process_eligibility` response meta and displayed as a pill badge in the eligibility banner.

**Pricing source**: litellm model_prices (Azure)

| Model | Input ($/1M tokens) | Output ($/1M tokens) |
|-------|---------------------|----------------------|
| gpt-4o | $2.50 | $10.00 |
| gpt-4o-mini | $0.165 | $0.66 |

**Files changed**:

| File | Change |
|------|--------|
| `artemis/src/utils/llm.py` | `LLMCostTracker` class, `_MODEL_COSTS` dict, `get_cost_tracker()` singleton, token recording in `AzureAIFoundryChatModel._generate()` |
| `artemis/src/services/tte_service.py` | `get_cost_tracker().reset()` at pipeline start; `llmCost` dict added to meta on all return paths |
| `atlas-dev/.../tte-manager.js` | `lastEligibilityLlmCost` observable; cost pill rendered in eligibility banner as "LLM: N calls, N tokens, $X.XXXX" |

**Banner pill example**: `LLM: 41 calls, 59,500 tokens, $0.2341`

---

## Remaining

- [ ] 전체 변경사항 커밋
- [ ] Docker 통합 테스트: Import Trial 후 paper enrichment → paperStatus 업데이트 확인
- [ ] Upload role 기능 UI 검증 (브라우저)
- [x] LEADER/ARISTOTLE 벤치마크에서 local PDF 감지 확인 (API로 확인 완료)
- [ ] Step 1/Step 2 분리 UI 브라우저 검증
- [ ] LLM cost pill E2E 검증 (process_eligibility 실행 후 배너 확인)

---

## LLM Cost per process_eligibility Run

Pricing source: [litellm model_prices](https://github.com/BerriAI/litellm) (Azure gpt-4o / gpt-4o-mini)

### Per-Token Pricing (Azure)

| Model | Input ($/1K tokens) | Output ($/1K tokens) |
|-------|---------------------|----------------------|
| gpt-4o | $0.0025 | $0.010 |
| gpt-4o-mini | $0.000165 | $0.00066 |

### LLM Call Breakdown (per trial, ~15 criteria)

| Stage | Agent | Model | Calls | Est. Input Tokens | Est. Output Tokens |
|-------|-------|-------|-------|-------------------|-------------------|
| Agent1 parse_nct | LogicDecomposer | gpt-4o | 2 | ~4,000 | ~2,000 |
| Agent1.5 plan | CriteriaPlanner | gpt-4o | 1 | ~3,000 | ~1,500 |
| Agent2 rerank | ConceptReranker | gpt-4o | ~15 | ~15,000 | ~3,000 |
| Agent2 critic | Critic (auto) | gpt-4o / mini | ~15 | ~15,000 | ~5,000 |
| Agent2 self-reflect | Critic (2nd pass) | gpt-4o / mini | ~8 | ~8,000 | ~3,000 |
| **Total** | | | **~41** | **~45,000** | **~14,500** |

### Cost Estimate (single trial, ~15 criteria)

| Scenario | Input Cost | Output Cost | **Total** |
|----------|-----------|-------------|-----------|
| All gpt-4o | $0.1125 | $0.145 | **~$0.26** |
| Auto tier (Condition/Drug→mini) | $0.075 | $0.10 | **~$0.18** |
| All gpt-4o-mini | $0.0074 | $0.0096 | **~$0.02** |

### Notes

- Costs are for the **process_eligibility** pipeline only (Agent1 → Agent1.5 → Agent2)
- Import Trial (generate-from-nct) adds ~2 more Agent1 LLM calls (~$0.02)
- ChromaDB/embedding lookups are free (local MiniLM/MedCPT)
- UMLS API, PubMed, ClinicalTrials.gov API calls are free
- Critic cache (`CRITIC_CACHE_TTL_HOURS=24`) avoids duplicate LLM calls for repeated criteria
- Actual token counts vary by trial complexity (LEADER: 23 criteria, ARISTOTLE: 18 criteria)

---

## DOI Mapping Table

| Journal | DOI Prefix | article_url Pattern | supp_url |
|---------|-----------|---------------------|----------|
| NEJM | 10.1056 | `https://www.nejm.org/doi/pdf/{doi}` | `https://www.nejm.org/doi/suppl/{doi}/suppl_file/{stem}_appendix.pdf` |
| Lancet/Elsevier | 10.1016 | `https://doi.org/{doi}` | None (main only) |
| JAMA | 10.1001 | `https://doi.org/{doi}` | None (main only) |
| BMJ | 10.1136 | `https://doi.org/{doi}` | None (main only) |
| Annals | 10.7326 | `https://doi.org/{doi}` | None (main only) |
| Unknown | * | `https://doi.org/{doi}` | None (main only) |

## Architecture

```
Preview Trial click
  → ClinicalTrials.gov API (NCT metadata)
  → /artemis-api/tte/papers/{nct_id}/status (non-blocking)
    → Check local data/papers/{NCT_ID}/*.pdf
    → If local: classify by {role}_ prefix or classify_supplement()
    → Return PaperStatus { source, papers_found, roles_filled, manual_download_needed }
    → If none: ClinicalTrials.gov referencesModule → get_design_paper_pmids (BACKGROUND first)
    → Fallback: PubMed esearch → DOI extract → build_paper_urls()
    → Return PaperStatus with download_urls
  → Frontend paperStatus observable → Paper Sources panel render

Upload PDF
  → POST /artemis-api/tte/papers/{nct_id}/upload?role=main|supplement
    → Validate role, prefix filename as {role}_{original}.pdf
    → Overwrite existing same-role file
  → Frontend refreshes paperStatus → panel updates

Import Trial click
  → /artemis-api/tte/studies/{id}/generate-from-nct
    → Agent1 parse_nct() → full enrichment pipeline
    → PMC OA → journal direct download → PubMed abstract fallback
    → self.last_paper_status set
  → Response meta.paperStatus → paperStatus observable update
```
