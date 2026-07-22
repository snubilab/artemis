# Lab Meeting: Mapping Benchmark V5 (Dual-Track) 구현 전략

**날짜**: 2026-02-27  
**참여 모델**: Claude, Codex (gpt-5.3-codex-spark), Perplexity (Gemini 대체: CLI 4회 실패)

## 안건
V4 벤치마크(61.9% recall)가 동작 중이나 TROY를 GT로 쓰는 구조적 문제 존재. ADR-013(TROY ≠ GT) 합의 후 2/20 Lab Meeting에서 V5 Dual-Track 합의했으나 1주간 미실행. 구현 전략 결정.

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | Pragmatic 3-day: 최소 GT schema + V4 확장 | `sub_criteria`로 1:N criteria matching |
| Codex | Extensible 3-day: 풍부한 schema + loader 분리 | `aliases, candidate_concepts, tolerance` 포함 |
| Perplexity | **4-day: TROY 이슈 분류 + Design Paper 검증 우선** | 양 제안 모두 불충분, 기초 작업 없이 metrics 무의미 |

## 교차 검증에서 발견된 문제점

### Claude 제안 반박
- ❌ **최소 schema 1-2주 내 실패** (Perplexity): provenance tracking, uncertainty flag, match confidence 부재
- ❌ `expected_domains` 수동 추론 불확실 (Codex/Claude 자체 인정)
- ❌ `sub_criteria`의 AND/OR 로직 미정의 → partial match 판정 불가 (Codex)

### Codex 제안 반박
- ❌ `candidate_concepts`가 GT에 포함되면 순환 논리 (Claude)
- ❌ `tolerance` 정의 불명 — 무엇의 tolerance인지 미정의 (Perplexity)
- ❌ `--trial` flag 조기 추상화 — LEADER 하나도 없을 때 (Claude)

### 양쪽 공통 반박 (Perplexity)
- ❌ **Design Paper 자체 검증 없음**: TROY 88건은 지적하면서 DP의 정확성은 가정
- ❌ **criteria-level vs concept-level 혼재**: recall 하나로는 불충분, precision도 필요
- ❌ **Maps-to 1-hop 너무 좁음**: TROY 88건 이슈 유형별 치환 전략 필요
- ❌ **V4 코드 결합도 미확인**: TROY 가정이 녹아있으면 확장이 아닌 리팩터링 필요
- ⚠ Partial match, negation criteria, temporal criteria 처리 미정의

## 최종 합의

### ✅ 합의: 수정된 4-Day 계획 (Perplexity 반박 수용)

| Day | 작업 | 산출물 |
|-----|------|--------|
| 1 | ClinicalTrials.gov NCT01179048 structured criteria → GT JSON **기계적 추출** | `data/ground_truth/LEADER_criteria.json` |
| 2 | V5 GT schema 정의 (semantics 포함) + **교수님 검수** | schema doc + reviewed GT |
| 3 | V4 코드 audit + TROY 결합 추출 + `benchmark_v5.py` 구현 | `scripts/benchmark_v5.py` |
| 4 | Dual-track 실행 (criterion + concept level) + V4 vs V5 비교 | `output/benchmark_v5_*.json` |

### ⚠️ GT 생성 편향 문제 (회의 후 추가 논의)

**문제**: LLM이 Design Paper에서 criteria를 해석하여 GT JSON을 작성하면, ARTEMIS(역시 LLM)와 **동일한 편향 공유** → LLM끼리 동의하는지만 측정.

**합의된 해결책 (2단계)**:
1. **기계적 추출**: ClinicalTrials.gov NCT01179048의 structured eligibility criteria를 **원문 그대로** JSON으로 변환 (LLM 해석 최소화)
2. **인간 검수**: 교수님/도메인 전문가가 GT JSON을 review하여 최종 확정

### 🔴 근본 한계: Concept-Level 정답이 존재하지 않음 (회의 후 추가 논의 2)

**문제**: Agent 2의 concept mapping이 "맞는지" 비교할 대상이 없음.

| 비교 대상 | 왜 GT로 부적합한가 |
|----------|-------------------|
| TROY concepts | 88건 품질 이슈 (ADR-013) |
| Design Paper | 텍스트만 있고 OMOP concept ID 없음 |
| LLM이 생성한 정답 | ARTEMIS와 동일 편향 (순환 논리) |

**V5가 자동으로 측정 가능한 것과 불가능한 것**:

| 수준 | 측정 가능? | 방법 |
|------|:---:|------|
| Criteria completeness (빠뜨리지 않았는가) | ✅ 자동 | DP criteria vs ARTEMIS rules |
| Concept correctness (concept이 맞는가) | ⚠️ 참조만 | TROY 대비 overlap (불완전) |
| Concept ground truth (진짜 맞는가) | ❌ 인간만 | 도메인 전문가 직접 검수 |

**결론**: V5 벤치마크는 **completeness는 자동화**, **correctness는 TROY 참조 + 인간 검수 병행**으로 설계해야 함. 완전 자동화된 concept-level GT는 현재 불가능.

### 💡 대안 2: TROY criteria → Agent 2 → TROY concepts 비교 (회의 후 추가 논의 3)

GT 문제를 우회하는 실용적 접근:

```
TROY criteria text (입력) → [Agent 2] → Agent 2 concepts (출력)
                                              ↕ 비교
                            TROY concept IDs (정답)
```

| 항목 | 설명 |
|------|------|
| **입력** | TROY 18 rules의 criteria 텍스트 |
| **평가 대상** | Agent 2 단독 (Agent 1 제거) |
| **정답** | TROY의 concept set (동일 전문가 출처) |
| **비교 방법** | TROY non-standard → standard 치환 후 concept overlap |

**왜 이게 더 나은가**:
- ✅ GT 편향 문제 없음 (입력과 정답이 같은 전문가에서 나옴)
- ✅ Agent 1 변수 제거 → Agent 2 순수 평가
- ✅ TROY 88건 품질 이슈와 무관 (TROY가 GT "역할"을 하는 것이지 GT "자체"는 아님)
- ✅ 즉시 실행 가능 (추가 GT 작성 불필요)

### GT Schema (3-Model 합의 버전)

```json
{
  "meta": {
    "schema_version": "1.0",
    "trial_id": "NCT01179048",
    "trial_name": "LEADER",
    "source": "NEJM 2016; 375:311-322",
    "created_at": "2026-02-27",
    "vocab_version": "OMOP v5.3 2024-01"
  },
  "criteria": [
    {
      "id": "C01",
      "type": "inclusion",
      "source_text": "50 years of age or older with at least one cardiovascular condition",
      "sub_criteria": [
        {"id": "C01a", "text": "prior myocardial infarction"},
        {"id": "C01b", "text": "prior stroke or transient ischemic attack"}
      ],
      "match_logic": "any",
      "annotator_note": ""
    }
  ]
}
```

Claude → Codex → Perplexity 교차 검증 결과로 확정:
- `match_logic: any|all` 추가 (Codex/Perplexity 반박 수용)
- `annotator_note` 추가 (DP 모호성 표시, Perplexity 제안)
- `candidate_concepts`, `tolerance` 제거 (순환 논리/미정의)
- `vocab_version` → `meta`에 포함 (재현성)

### 메트릭 정의 (Perplexity 반박 수용: 4종)

| Track | Metric | 설명 |
|-------|--------|------|
| Primary | `criterion_recall` | DP criteria 중 ARTEMIS가 식별한 비율 |
| Primary | `concept_recall_per_criterion` | 매칭된 criteria별 OMOP concept 커버리지 |
| Secondary | `troy_alignment_score` | TROY standard-치환 후 concept overlap |
| Secondary | `false_positive_rate` | DP에 없는 ARTEMIS 생성 concept 비율 |

## 반대 의견 기록
- **Perplexity: "양쪽 다 거부"** → 4일 계획으로 수용하되, 완전 재작성은 과도. V4 audit 후 확장 결정.
- **Claude: `expected_domains` 제거 수용** → annotation protocol에서 별도 관리
- **Codex: `aliases` 제거** → 향후 확장 옵션으로 보류

## 부록: 원본 제안 및 리뷰
> 상세 내용은 `tmp/lab_meeting/20260227_mapping_v4_benchmark/` 참조
> - `proposal_claude.md`, `proposal_codex.md`
> - `review_claude.md`, `review_codex.md`, `review_perplexity.md`
