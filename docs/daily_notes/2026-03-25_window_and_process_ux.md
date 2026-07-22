# 2026-03-25: Window 필드 강화 & Process Eligibility UX 개선

## 완료 항목

### 1. Agent1 프롬프트 window 필드 mandatory 강화 (`f040c5b`)
- **문제**: LLM이 window를 안 뱉어서 모든 criteria가 fallback 365일
- **원인**: 프롬프트에서 window가 optional ("if inferrable") 취급
- **수정**: SYSTEM_PROMPT, DECOMPOSITION_PROMPT, NCT_SYSTEM_PROMPT, NCT_DECOMPOSITION_PROMPT 4곳에서 window mandatory + domain default 명시
  - Condition/Procedure: `{start: -9999, end: 0}`
  - Drug: `{start: -365, end: 0}`
  - Measurement: `{start: -180, end: 0}`
- **검증**: NCT01179048 (LEADER) 재import → GLP-1/DPP-4가 -90일, acute event가 -14일로 정확 추출

### 2. NCT import 후 자동 process 제거 (`5ac1c66`)
- **문제**: import 완료 → `convertEligibilityToStructured()` 자동 호출 → 유저 의도 없이 mapping 시작
- **수정**: import 후 eligibility 탭으로 이동만, process는 유저가 직접 버튼 클릭

### 3. Processing overlay UI (`9dd5cd6`)
- **문제**: 버튼 아래 "Starting..." 텍스트가 어색 + 배너 안에 progress가 묻힘
- **수정**: `isCapabilityRunning()` 시 탭 전체에 반투명 오버레이 + 중앙 progress 카드
  - 스피너 + 실시간 진행 텍스트 (target mapping → concept set mapping N/M)
  - 아래 criteria rows 보이지만 조작 불가

### 4. Mapping quality pre-check 중복 제거 (`a7e3f7e`)
- **문제**: process 시작 전 `_build_real_mapping_quality_signal`이 모든 criterion에 Agent2 순차 호출 → "Preparing..." 상태 장시간 정체
- **원인**: process_eligibility와 완전히 같은 Agent2 매핑을 사전 quality check에서 한번 더 수행
- **수정**: 가벼운 `_build_mapping_quality_signal` fallback으로 대체

## 커밋 목록
- `f040c5b` fix: enforce mandatory window field in agent1 prompts
- `5ac1c66` fix: remove auto-process after NCT import, require manual trigger
- `9dd5cd6` feat: processing overlay replaces inline progress text
- `a7e3f7e` fix: skip duplicate Agent2 mapping-quality pre-check in process eligibility

## 관련 파일
- `artemis/src/agents/agent1/prompts.py` — window mandatory 강화
- `artemis/src/services/tte_service.py` — mapping quality pre-check 제거
- `atlas-dev/js/pages/target-trial-emulation/tte-manager.js` — auto-process 제거, polling 로그
- `atlas-dev/js/pages/target-trial-emulation/tte-manager.html` — processing overlay
- `atlas-dev/js/pages/target-trial-emulation/tte-manager.less` — overlay CSS
