# Lab Meeting: Benchmark V3 설계

**날짜**: 2026-02-16
**참여 모델**: Claude, Gemini (gemini-3-pro-preview), Codex (gpt-5.3-codex)

## 안건
Benchmark V3 설계: Agent 2 concept set 평가를 넘어 Agent 3 Circe JSON 전체 파이프라인 평가 체계 구축

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | 3-Layer (ConceptSet/JSON Diff/ATLAS E2E) | 디버깅 가능성 — 어느 레이어에서 실패인지 분리 |
| Gemini | Bug-first 접근 + Semantic Fingerprinting | **실제 버그 발견** (CodesetId=0, Age→ConditionOccurrence), JSON Diff 대신 rule fingerprint 비교 |
| Codex | 4-Level (A~D) + Agent Attribution + Sprint 분리 | 코드 근거 제시 (assembler:135, validator:78), **TROY 자체 데이터 품질 이슈** 발견 (HbA1C name≠value) |

## 교차 검증에서 발견된 문제점

### 3개 모델 모두 지적한 공통 문제
1. **WebAPI/SQL 경로 미존재**: 현재 코드에 ATLAS WebAPI SQL 컴파일 로직이 없음. `cohort_executor.py`는 heuristic/fallback 방식
2. **TROY 단일 구현 편향**: silver ground truth로만 사용 가능. 절대 기준 불가
3. **JSON raw diff 무의미**: ID 재할당, 순서 차이로 strict diff는 false positive 발생

### Gemini 고유 발견
- **Semantic Fingerprinting** 제안: `[Type]_[TableName]_[ConceptSetName]_[Window]` 형태로 rule을 정규화하여 Jaccard 비교
- CriteriaGroup 중첩(Nested) 구조에서 단순 diff의 한계 (`A AND (B OR C)` vs `(A AND B) OR C`)

### Codex 고유 발견
- **TROY JSON 내 데이터 불일치**: `"HbA1C >= 7%"` 이름이지만 값은 10 (line 4760, 4769)
- **Agent Attribution 자동화 불가**: provenance 추적 구조 없이는 오류 원인 분리 불가
- **Validator 테스트 커버리지 부족**: `CodesetId=0` 감지 테스트 부재

## 최종 합의 (✅ 3-모델 합의)

### 결정 1: 평가 범위 — **2단계 + 로드맵**

| 우선순위 | 범위 | 이번 스프린트 | 구현 방식 |
|---------|------|:----------:|----------|
| **필수** | Static Semantic Validation | ✅ | `agent4/validator.py` 확장 |
| **필수** | Semantic Fingerprint 비교 | ✅ | `scripts/benchmark_v3.py` 신규 |
| 선택 | WebAPI SQL 컴파일 | ❌ | WebAPI 연동 완료 후 |
| 선택 | E2E 환자수 비교 | ❌ | CDM+WebAPI 환경 고정 후 |

### 결정 2: 비교 기준 — **Fingerprint + Concept Recall**
- JSON raw diff ❌ → **Semantic Fingerprint Jaccard** ✅
- Rule 단위 fingerprint: `[CriteriaType]_[Table]_[ConceptSet]_[Window]`
- 매칭된 rule 내부의 **Concept Set Recall** (V2 계승)

### 결정 3: 자동화 수준 — **Offline Python 우선**
- WebAPI 없이 실행 가능한 Python 스크립트
- CI/CD Integration Test로 SQL 컴파일은 분리

### 결정 4: TROY Ground Truth — **Silver Ground Truth**
- "전문가 구현 1종"으로 취급
- Primary reference로 사용하되, 절대 기준 아님
- 향후 trial 3개 이상 확장으로 편향 완화

## 반대 의견 기록
- **없음** (3-모델 합의 달성)
- 세부 구현 차이: Gemini가 Fingerprinting 깊이를, Codex가 Attribution을 더 강조했으나, 최종안에 모두 반영됨

## 실행 계획

### Phase 1: Static Semantic Validator 강화 (이번 스프린트)
- [ ] `agent4/validator.py`에 추가: CodesetId=0 감지, 도메인 불일치, 빈 Criteria
- [ ] 기존 validator 테스트에 CodesetId=0 케이스 추가

### Phase 2: Benchmark V3 스크립트 (이번 스프린트)
- [ ] `scripts/benchmark_v3.py` 신규 작성
  1. Validator 실행 (Fail → 0점)
  2. Inclusion Rule → Semantic Fingerprint 추출
  3. TROY vs ARTEMIS Fingerprint Jaccard
  4. 매칭 Rule 내 Concept Set Recall

### Phase 3: WebAPI SQL 컴파일 (다음 스프린트)
- [ ] ATLAS WebAPI 연동 구현
- [ ] Circe JSON → SQL 생성 성공률 측정

### Phase 4: E2E 환자수 비교 (다음 스프린트)
- [ ] TROY SQL vs ARTEMIS SQL 환자수 비교
- [ ] Patient-level overlap 측정

## 부록: 원본 제안 및 리뷰
> 상세 내용은 `tmp/lab_meeting/20260216_benchmark_v3_design/` 참조
