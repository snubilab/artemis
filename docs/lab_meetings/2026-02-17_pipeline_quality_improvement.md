# Lab Meeting: ARTEMIS 파이프라인 품질 개선 전략

**날짜**: 2026-02-17
**참여 모델**: Claude, Codex (gpt-5.3-codex-spark) *(Gemini: 429 rate limit으로 제외)*

## 안건
ARTEMIS LEADER 벤치마크 Full=13, Recall=38.0% → 실제 파이프라인 출력 품질 개선 방향 결정.

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | **Agent 2 먼저** (Critic broad parent + Retriever fallback) | Wrong/Missed의 근본 원인은 Agent 2 매핑 품질 |
| Codex | **Agent 3 먼저** (temporal + emptyCS + composite) → 효과 확인 후 Agent 2 | 캐시 유지 = 빠른 iteration, 비용 최소화 |

## 교차 검증에서 발견된 문제점

### Claude 제안 반박 (Codex 검증)
- ❌ **broad parent → Wrong 감소 과대 추정**: broad parent는 recall↑이지만 precision↓ 위험. "malignant neoplasm" 상위 선택 시 피부암/뇌종양 등 불필요 하위 포함
- ❌ **원인 분해 불충분**: Wrong 11건 전부를 Agent 2 탓으로 단정 → 빈 CS, 규칙 해석 손실 등 다른 경로 누락
- ⚠ **fallback dict 안전장치 부재**: CKD→ESRD 과확장/충돌 관리 없이 운영하면 품질 급락

### Codex 제안 반박 (Claude + Codex 자체 검증)
- ❌ **temporal window 변경의 실효성 낮음**: 벤치마크에서 이미 window_group으로 정규화 → window 값 자체가 concept set 내용에 영향 없음
- ❌ **composite rule ROI 낮음**: ARTEMIS는 atomic decomposition, TROY는 composite → 구조적 차이이므로 Agent 3에서 composite 지원해도 효과 제한적
- ⚠ **4~5건 회복 임계치 판별 기준 모호**: 휴리스틱 의사결정

## 최종 합의

### ✅ 합의: **Agent 3 방어적 안정화 (cheap) → Agent 2 매핑 개선 (가드 기반)**

| 순서 | 작업 | 예상 소요 | 근거 |
|------|------|----------|------|
| **1** | **Agent 3: empty CS skip + warning log** | 15분 | 캐시 유지, CodesetId=0 제거, validation error 감소 |
| **2** | **Agent 2: Retriever abbreviation expander 강화** | 30분 | ESLD/ESRD/CKD/MEN2/MTC → OMOP 매핑 dict. 규칙형이라 리스크 낮음 |
| **3** | **Agent 2: Critic 프롬프트 조건부 broad parent** | 30분 | "general category일 때만 ancestor 선호". **가드 조건** 포함 필수 |
| **4** | **E2E 재실행 + benchmark** | 25분 | 1-3 모두 반영 후 한 번만 캐시 무효화 |

### 핵심 가드레일
1. **Critic broad parent는 조건부**: `"If the query term is a general category (e.g., 'malignancy', 'transplant'), prefer broad ancestor. If the query term is specific (e.g., 'liver transplant'), prefer exact match."`
2. **Abbreviation fallback은 타입 안전**: 상위-하위 충돌 시 블랙리스트/우선순위 적용
3. **Agent 3 empty CS는 skip+log**: fallback 후보 생성 없이 단순 제거 (안전 우선)

## 반대 의견 기록
- **Codex의 temporal/composite 우선**: 실효성이 교차검증에서 부정됨. 향후 다른 trial에서 필요하면 재논의.
- **Claude의 무조건 broad parent**: precision 리스크로 조건부로 완화됨.

## 실행 계획
- [ ] 1. Agent 3 `assembler.py`: CodesetId=0 rule skip + warning log (15min)
- [ ] 2. Agent 2 `abbreviation_expander.py`: ESLD/ESRD/CKD/MEN2/MTC fallback dict (30min)
- [ ] 3. Agent 2 `critic.py`: 조건부 broad parent 프롬프트 추가 (30min)
- [ ] 4. E2E 재실행: `verify_leader_design_e2e.py` (25min)
- [ ] 5. Benchmark V3 실행 및 결과 비교 (5min)

## 부록: 원본 제안 및 리뷰
> 상세 내용은 `tmp/lab_meeting/20260217_pipeline_quality_improvement/` 참조
