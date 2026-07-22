# Lab Meeting: TROY 데이터 품질 문제 기반 벤치마크 전략 재설계

**날짜**: 2026-02-20
**참여 모델**: Claude, Codex (gpt-5.3-codex-spark) *(Gemini: CLI 2회 실패로 제외)*

## 안건
TROY LEADER v3.4에서 88개 데이터 품질 이슈 발견 — TROY를 gold standard로 사용하면 ARTEMIS의 올바른 행동을 벌하는 구조적 문제. 대안 벤치마크 전략 결정.

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | **3-Layer Framework** (Criteria Completeness + Standard-only Recall + Structural Fidelity) | 역할 분리로 TROY를 폐기하지 않고 정제하여 활용 |
| Codex | **Design Paper GT 전환** + TROY를 diagnostic layer로만 사용 | GT 분모에 TROY를 절대 포함하지 않아 공정성 확보 |

## 교차 검증에서 발견된 문제점

### Claude 제안 반박 (Codex 검증)
- ❌ **Layer 1 "100%" = 무의미한 지표**: 수동 IR이라 측정 자체가 trivial. Agent 1이 NL→IR을 수행하기 전까지 의미 없음
- ❌ **Standard-only filtering 과잉**: 단순 `standard_concept = 'S'` 필터는 TROY의 임상적 의도를 왜곡. `440069 (Drug dependence, invalid=U)` → `37165431 (Substance dependence, S)` 치환 후 비교해야 함
- ❌ **5-day timeline 비현실적**: JSON schema 설계 미포함. 실제 7일 소요
- ⚠ **Vocabulary version pinning 누락**: OMOP vocab 업데이트 시 NOT_FOUND 목록 변동 → 재현성 떨어짐

### Codex 제안 반박 (Claude 검증)
- ❌ **"Discard TROY entirely" 과잉**: TROY의 valid+standard concept은 concept mapping 참조로 활용 가능. 전면 폐기는 전문가 지식 낭비
- ❌ **Design Paper GT 형식 미정의**: ground truth JSON schema가 없으면 trial간 일관성 불가
- ⚠ **Design paper 모호성**: "symptomatic coronary heart disease" 같은 표현은 concept mapping이 아닌 해석의 영역

### 공통 문제점 (양측 모두 누락)
- Empty pool (모든 concept이 non-standard인 rule)의 recall 처리 미정의
- Vocabulary version drift에 대한 재현성 보장 전략 없음
- Multi-trial 확장 경로 불명확

## 최종 합의

### ✅ 합의: **Dual-Track Benchmark (Design Paper Primary + TROY Diagnostic)**

Codex의 거버넌스 모델(Proposal 2) 위에 Claude의 Layer 2 concept diagnostics를 overlay.

| Track | 역할 | Metric | GT Source |
|-------|------|--------|-----------|
| **Primary** | 정량 평가 | `recall_design_paper` | Design Paper criteria (versioned JSON) |
| **Secondary** | 진단/참조 | `troy_alignment_score` | TROY **standard 치환 후** concept set |

#### Primary Track: `recall_design_paper`
- Design paper criteria를 **version-locked JSON** (`data/ground_truth/LEADER_criteria.json`)으로 관리
- IR → Concept 매핑의 completeness를 criteria 단위로 측정
- **이것만 공식 벤치마크 수치로 보고**

#### Secondary Track: `troy_alignment_score`
- TROY concept set에서 Non-standard → **Standard equivalent 자동 치환** (`Maps to` relationship)
- NOT_FOUND → 경고 로그만, **분모에서 제외**
- 결과를 rule별 quality tag로 분류: `PASS` / `WARN` / `BLOCKED`
- **절대 recall 분모로 사용하지 않음** — 진단 목적으로만 보고

#### Version Anchors (재현성)
모든 벤치마크 리포트에 아래 3개를 반드시 포함:
- `design_paper_snapshot_id`: GT 버전 (예: `LEADER_v1.0`)
- `vocab_version`: OMOP vocabulary 날짜/버전
- `benchmark_script_version`: 스크립트 git hash

## 반대 의견 기록
- **Claude의 3-Layer 구조**: Layer 1이 현재 trivial하고 Layer 3는 Agent 4가 이미 수행중이므로, 별도 Layer로 분리하는 것보다 기존 도구 활용이 효율적. → Layer 2만 채택하여 Secondary Track으로 전환.
- **Codex의 "TROY 전면 폐기"**: valid+standard concept까지 버리면 concept mapping 참조 데이터 손실. → standard 치환 후 diagnostic으로 유지.

## 실행 계획

| 순서 | 작업 | 예상 소요 | 산출물 |
|------|------|----------|--------|
| 1 | Design Paper GT JSON schema 정의 + LEADER 데이터 작성 | 1일 | `data/ground_truth/LEADER_criteria.json` |
| 2 | TROY Standard 치환 스크립트 | 0.5일 | `scripts/troy_standard_map.py` |
| 3 | `benchmark_v5.py` (Dual-Track: primary + diagnostic) | 1.5일 | `scripts/benchmark_v5.py` |
| 4 | Version anchor 메커니즘 추가 | 0.5일 | JSON report에 vocab/GT/script version 포함 |
| 5 | 통합 실행 및 리포트 비교 (v4 vs v5) | 0.5일 | `output/benchmark_v5_*.json` |
| 6 | 문서화 + ADR 업데이트 | 0.5일 | ADR-014 |

**총 예상: 5일**

## 부록: 원본 제안 및 리뷰
> 상세 내용은 `tmp/lab_meeting/20260220_troy_benchmark_alternative/` 참조
