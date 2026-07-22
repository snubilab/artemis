# Lab Meeting: Benchmark V3 결과 기반 다음 우선순위

**날짜**: 2026-02-16
**참여 모델**: Claude, Gemini (gemini-3-pro-preview), Codex (gpt-5.3-codex-spark)

## 안건
V2 Agent 2 Recall 68.3%, V3 Full Pipeline Recall 58.5% 결과 기반으로 다음 스프린트 우선순위 결정.

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | **B → C → A** (Agent 3 먼저) | V2→V3 10%p 손실이 Agent 3 품질 문제 |
| Gemini | **C first** (벤치마크 로직 먼저) | "부러진 자로 측정하면 수정 효과를 모른다" + 1-to-N matching 코드 제안 |
| Codex | **C → B → A** (벤치마크 먼저) | 58.5%는 lower bound, 매칭 로직이 과소평가 유발 |

## 교차 검증에서 발견된 문제점

### Claude (B→C→A) 반박
- ❌ **"부러진 자" 위험**: 벤치마크 로직이 부정확하면 Agent 3 수정 효과를 측정 불가 (Gemini)
- ❌ **인과관계 비약**: V2 68.3% → V3 58.5% 하락 = Agent 3 문제라는 근거 불충분 (Gemini, Codex)
- ❌ **매칭 미고정 상태에서 B 변경**: 원인 분리 불가 (Codex)

### Gemini (C first, 300줄 재작성) 반박
- ❌ **과도한 최적화**: 300줄 재작성은 회귀 리스크 크다 (Gemini 자체 인정)
- ❌ **FP inflation**: 1-to-N이 recall을 올리지만 precision 없이 "점수 부풀리기" 위험 (Gemini, Codex)
- ⚠ **단계적 접근 필요**: 전체 재작성 대신 fuzzy matching + temporal normalization만 추가 (Codex)

### Codex (이중 GT 체계) 반박
- ❌ **관리 비용 과소평가**: dual GT는 유지보수 악몽, 스타트업 단계에서 비현실적 (Gemini)
- ⚠ **"58.5% = lower bound"는 정성 추정**: 수치적 근거 부재, 최소-최대 구간 제시 필요 (Codex 자체 인정)

## 최종 합의

### ✅ 합의: **C(Hotfix) → B → C(Deep) → A**

| 순서 | 작업 | 예상 소요 | 근거 |
|------|------|----------|------|
| **1** | **C-Hotfix**: `benchmark_v3.py` temporal normalization + fuzzy name matching | 2-3시간 | 측정 도구 수정 선행 (3모델 합의) |
| **2** | **B**: Agent 3 temporal window IR 연동 + empty CS skip | 1일 | 캐시 덕분에 빠른 iteration |
| **3** | **C-Deep**: 1-to-N matching (제약 기반, precision 페널티 포함) | 1일 | B 결과 반영 후 필요 시 |
| **4** | **A**: Agent 2 Critic 프롬프트 broad parent 유도 | 1일 | 캐시 무효화 필요, 마지막 |

### C-Hotfix 구체적 범위
1. temporal window 정규화: `-180:0` ≈ `-365:0` → 같은 "prior event"로 매칭
2. concept set name fuzzy: `[TROY]` prefix 제거, substring matching 강화
3. 미매칭 규칙의 recall 분모 처리 명확화

## 반대 의견 기록

- **Claude의 원 제안 (B first)**: Agent 3 품질이 실제로 문제인 것은 맞지만, 매칭 로직이 불완전한 상태에서 효과를 측정할 수 없다는 Gemini/Codex 반박에 동의하여 C-Hotfix 선행으로 수정.
- **Gemini의 300줄 재작성**: 과도하다는 합의. 대신 C-Deep으로 격하하여 B 이후 필요 시 진행.
- **Codex의 이중 GT**: 장기적으로 타당하나 현 단계에서는 비현실적. "Golden Set Annotation" (허용 가능 대체 정답 필드) 방식이 가벼운 대안.

## 실행 계획
- [ ] C-Hotfix: `benchmark_v3.py` temporal normalization + name fuzzy (2-3h)
- [ ] B: Agent 3 temporal window IR 연동 (1d)
- [ ] C-Deep: 1-to-N matching with precision penalty (필요 시, 1d)
- [ ] A: Critic prompt broad parent (1d)

## 부록: 원본 제안 및 리뷰
> 상세 내용은 `tmp/lab_meeting/20260216_benchmark_next_steps/` 참조
