# Agent1 Non-Determinism Fixes (P1/P2/P3) — 2026-03-31

Branch: `fix/agent1-pattern-e-or-logic`
Commit: `8b642d3`

## Summary

LEADER (NCT01179048) 재실행 시 결과가 매번 달라지는 비결정성 문제를 세 레이어에서 수정했다.
각 수정은 독립적인 방어 레이어로 작동하며, 하나가 실패해도 다음 레이어가 보완한다.

| Layer | Fix | 위치 | 테스트 |
|-------|-----|------|--------|
| P3 | Enrichment hash stabilization | `parser.py` | 10/10 pass |
| P2 | PDF hierarchy preservation | `pubmed_fetcher.py` | 9/9 pass |
| P1 | Pattern E post-parse repair | `parser.py` | 8/8 pass |
| **합계** | | | **27/27 pass** |

---

## Root Cause 분석

비결정성의 근본 원인은 하나가 아니라 4가지가 복합적으로 작용했다.

1. **프롬프트 해시 불안정** — enrichment source(PubMed API vs PDF vs cache)에 따라 whitespace가 달라져 6가지 다른 해시가 생성됨. 그 중 4개는 잘못된 IR을 생성.
2. **LLM Rule 충돌** — Rule 3("criterion당 별도 rule")과 Rule 12("Pattern E는 OR group") 사이의 충돌. LLM이 어떤 rule을 우선시하느냐에 따라 결과가 달라짐.
3. **PDF 계층 구조 소실** — bullet hierarchy가 flatten되어 LLM이 19개의 flat criteria를 봄. 원본 문서에 있던 OR 구조가 사라짐.
4. **`temperature=0.0`은 원인이 아님** — 처음 의심했으나 실제 원인은 위 세 가지.

---

## P3 — Enrichment Hash Stabilization (`parser.py`)

### 문제

같은 논리적 기준이지만 enrichment source에 따라 `\xa0`, trailing whitespace, 중복 공백 등이 달라 해시가 달라졌다. 캐시 히트가 안 되면 LLM 재호출 → 다른 IR 생성.

### 구현

- `_normalize_trial_data_for_stable_hash()` 함수 추가:
  - strip whitespace, collapse consecutive spaces
  - remove non-breaking chars (`\xa0`, `\u200b` 등)
  - deduplicate consecutive identical lines
- enrichment 직후, 프롬프트 빌딩 전에 호출
- `.meta.json` sidecar 파일 기록: `enrichment_source`, `timestamp`, counts

### 효과

같은 NCT에서 enrichment source가 달라도 동일한 해시 → 캐시 히트 → 동일한 IR 반환.

---

## P2 — PDF Hierarchy Preservation (`pubmed_fetcher.py`)

### 문제

PDF 파싱 시 다음과 같은 구조가 flatten되었다:

```
Major adverse cardiovascular event:
  • myocardial infarction
  • stroke
  • unstable angina
```

→ LLM이 받는 텍스트: `myocardial infarction`, `stroke`, `unstable angina` (3개 별도 criteria)

### 구현

- `_collapse_hierarchical_groups()` 함수 추가:
  - explicit OR-quantifier header 감지: `"≥1 of"`, `"at least one of"`, `"one or more of"` 등
  - 해당 header 아래 indented bullet children을 탐지
  - `[OR-GROUP] header with any of: A | B | C` 형식으로 single line emit
- **의도적 제외**: colon-only header (`"Criteria:"` 등)는 AND criteria이므로 처리 안 함
  - Codex review에서 잡은 버그: 원래는 colon도 trigger였으나 false positive 발생
- `[OR-GROUP]` 라인은 이후 regex pass에서 re-splitting 방지를 위해 별도 처리

### 효과

LLM이 OR 구조를 명시적으로 받아서 Rule 12(Pattern E)를 더 안정적으로 적용.

---

## P1 — Pattern E Post-Parse Repair (`parser.py`)

### 문제

P2/P3가 작동해도 LLM이 Rule 3를 우선해 flat rules를 생성하는 경우가 있다.
이때 LEADER의 ACS 기준 같은 OR 그룹이 개별 inclusion_rules로 분산되어 CIRCE OR group이 만들어지지 않는다.

### 구현

- `_PATTERN_E_CLUSTERS` dict: 임상적으로 알려진 OR 그룹 4개 정의

  | Cluster | Keywords |
  |---------|----------|
  | `acs` | myocardial infarction, mi, stemi, nstemi, unstable angina, acs, acute coronary syndrome |
  | `cv_prior` | stroke, tia, coronary artery disease, peripheral artery disease, pad, coronary revascularization |
  | `cv_risk` | hypertension, hyperlipidemia, dyslipidemia, diabetes mellitus, smoking |
  | `metabolic` | obesity, bmi, chronic kidney disease, ckd, renal insufficiency |

- `_repair_pattern_e()` 함수:
  - inclusion_rules를 순회하며 3개 이상 연속된 flat rule이 같은 cluster에 속하면 감지
  - 감지된 규칙들을 `group_type="ANY"` composite으로 병합
  - `_build_cohort_definition()` 후처리 단계에서 호출

- **Cluster 순서**: `acs`를 `cv_prior`보다 먼저 정의 — "acute coronary syndrome"이 cv_prior의 "coronary" 패턴에 먼저 매칭되는 shadowing 버그 방지 (Codex review에서 발견)

- **Word-boundary regex**: 단어 경계(`\b`)를 적용하여 `mi` → `family`, `admission` 등에서 false positive 방지

### 효과

LLM이 flat rules를 생성해도 post-parse에서 자동 복구. P1은 P2/P3 실패 시 최종 safety net.

---

## Codex Review — 사전 발견된 버그 3건

코드 병합 전 Codex ensemble review에서 3개 버그가 발견되어 수정 후 병합됨.

| # | Layer | 버그 내용 | 수정 |
|---|-------|---------|------|
| 1 | P2 | `"Criteria:"` 같은 plain colon header가 AND children을 OR로 collapse | colon-only trigger 제거 |
| 2 | P1 | `"acute coronary syndrome"`이 cv_prior의 `"coronary"` 키워드에 먼저 매칭 (cluster shadowing) | acs cluster를 cv_prior 앞으로 reorder |
| 3 | P2 | OR-GROUP items이 section 맨 앞에 위치하게 됨 | acceptable — section start에 나타나므로 허용 |

---

## Defense Layer 구조

```
입력: enrichment (PubMed / PDF / cache)
         ↓
[P3] hash normalization → 같은 논리 = 같은 해시 → 캐시 히트
         ↓
[P2] PDF hierarchy → LLM이 OR 구조를 명시적으로 수신
         ↓
   LLM IR 생성
         ↓
[P1] post-parse repair → flat rules → OR group 복구
         ↓
출력: 안정적인 CIRCE cohort definition
```

P3이 새 해시 생성을 막고, P2가 프롬프트 품질을 높이며, P1이 잘못된 IR을 사후 보정한다.

---

## 테스트 결과

```bash
pytest tests/test_agent1_pattern_e_repair.py      -q   # 8 passed
pytest tests/test_pdf_hierarchy_preservation.py   -q   # 9 passed
pytest tests/test_enrichment_stability.py         -q   # 10 passed
```

총 **27/27 테스트 통과**.

---

## Files Changed

- `artemis/src/agents/agent1/parser.py` — P1 `_repair_pattern_e()`, P3 `_normalize_trial_data_for_stable_hash()`
- `artemis/src/agents/agent1/pubmed_fetcher.py` — P2 `_collapse_hierarchical_groups()`
- `artemis/tests/test_agent1_pattern_e_repair.py` — P1 tests (8)
- `artemis/tests/test_pdf_hierarchy_preservation.py` — P2 tests (9)
- `artemis/tests/test_enrichment_stability.py` — P3 tests (10)
