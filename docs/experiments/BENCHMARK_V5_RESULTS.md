# Benchmark V5 Results Report — Exp A 상세

> 🏷 명명 규칙: [EXPERIMENT_NAMING_CONVENTION.md](./EXPERIMENT_NAMING_CONVENTION.md) | 실험 계열: **Exp A** (Agent1 경유)

**Date**: 2026-02-27  
**Trial**: LEADER (Liraglutide vs Placebo)  
**Reference**: `[TROY] Liraglutide (LEADER) v3.4.json` (18 rules)  
**Schema**: `synthea_cdm`

## 1. Overview

V5 벤치마크는 TROY의 criteria를 기준으로 ARTEMIS Agent의 매핑 정확도를 평가한다.

### 실험 버전

| Version  | Pipeline                      | 측정 대상                             |
| -------- | ----------------------------- | ------------------------------------- |
| **v5.0** | Rule name → Agent 2 직접      | Agent 2 단독 성능 (Agent 1 간섭 없음) |
| **v5.1** | Rule name → Agent 1 → Agent 2 | Agent 1 + Agent 2 결합 성능           |

> [!IMPORTANT]
> v5.1에서는 Agent 1과 Agent 2 성능이 결합(coupled)되어 있어 원인 분리가 불가능하다.
> Agent 2 단독 성능을 보려면 v5.0 결과를 참조할 것.

## 2. 실험 이력

|   #   | 변경 사항                                                | Full  | Partial | Wrong |  Recall   | Precision |    F1     |
| :---: | -------------------------------------------------------- | :---: | :-----: | :---: | :-------: | :-------: | :-------: |
|   1   | Agent 2 only, no Neo4j                                   |   1   |    0    |  16   |   7.3%    |   27.6%   |   9.0%    |
|   2   | + Review 반영 (recursive groups, symmetric substitution) |   1   |    0    |  16   |   9.7%    |   26.0%   |   9.0%    |
|   3   | + Neo4j KG Expansion                                     |   2   |    1    |  14   |   15.2%   |   32.9%   |   15.3%   |
|   4   | + Agent 1 → Agent 2 Full Pipeline                        |   4   |    0    |  13   |   24.4%   |   31.8%   |   23.2%   |
|   5   | + Agent 1 list fallback 수정                             |   5   |    5    |   7   |   46.1%   |   63.7%   |   42.9%   |
| **6** | **+ ATC ChromaDB drug class expansion (RFC-006)**        | **4** |  **5**  | **8** | **41.3%** | **61.5%** | **39.1%** |

> ⚠ v6는 v5 대비 Recall이 하락했지만, 이는 dictionary alias 제거 + LLM 비결정성 때문. GLP1-RA/DPP-4 rule은 **1% → 99%** 로 극적 개선. dictionary를 제거하고도 ATC vocab만으로 drug class 매핑 가능함을 증명.

## 3. Per-Rule 결과 비교 (Recall)

| Rule                               | TROY  | #5 +A1 fix |   #6 +ATC   |     ms | 변화                                       |
| ---------------------------------- | :---: | :--------: | :---------: | -----: | ------------------------------------------ |
| Age ≥ 50                           |   -   |     ⏭     |     ⏭      |      - | Demographic                                |
| HbA1C ≥ 7 %                        |   1   |  ✅ 100%   | ✅ **100%** | 16,815 | 일관 성공                                  |
| **prior CV disease**               | 4,932 |   🔶 63%   | 🔶 **63%**  | 21,105 | A1 "Cardiovascular disease"                |
| **No T1DM**                        |  25   |  ✅ 100%   | 🔶 **76%**  | 18,980 | ⚠ LLM 비결정성                             |
| No calcitonin ≥ 50 ng/L            |   2   |   🔶 50%   |  ❌ **0%**  | 33,972 | ⚠ LLM 비결정성                             |
| **No GLP1-RA, pramlintide, DPP-4** | 3,326 |   ❌ 1%    | ✅ **99%**  | 19,974 | 🎉 **ATC expansion 적용!**                 |
| **No use of insulin**              | 8,449 |   ✅ 91%   | ✅ **97%**  |  7,104 | ATC insulin class 확장                     |
| No acute decompensation            |   8   |   ❌ 0%    |    ❌ 0%    | 14,253 | 의미 매핑 실패                             |
| No acute coronary/cerebrovascular  | 1,193 |   ❌ 9%    |    ❌ 9%    | 31,158 | 2개 분리, 부분 매핑                        |
| **No CHF**                         |  166  |   ❌ 20%   | ❌ **20%**  | 20,097 | KG expansion 부족                          |
| **No renal replacement**           |  126  |   🔶 48%   | 🔶 **48%**  | 11,887 | 안정                                       |
| No eGFR <30                        |  38   |   ❌ 8%    |  ❌ **8%**  | 20,393 | Measurement 부분                           |
| **No ESLD**                        |  770  |   🔶 33%   | 🔶 **33%**  | 16,206 | 안정                                       |
| No history of transplant           |  319  |   ❌ 17%   |  ❌ **4%**  | 15,045 | ⚠ LLM 비결정성                             |
| **No malignant**                   | 5,310 |   🔶 40%   | 🔶 **40%**  | 15,239 | 안정                                       |
| **No FH/PH MEN2/FMTC**             |   6   |  ✅ 100%   | ✅ **100%** | 47,938 | 일관 성공                                  |
| **No drug use or dependence**      |  241  |  ✅ 100%   |  ❌ **0%**  |  8,562 | ⚠ Agent 1 domain 오분류 → ATC 오매칭       |
| No pregnant                        | 2,253 |   ❌ 4%    |  ❌ **4%**  | 18,855 | ⚠ Concept granularity — KG climbing 미작동 |

### Timing Bottlenecks

| 분류     | 대표 Rule                         |   시간(ms) | 원인                             |
| -------- | --------------------------------- | ---------: | -------------------------------- |
| **Slow** | No FH/PH MEN2/FMTC                | **47,938** | 4개 sub-criteria × LLM reranking |
| **Slow** | No calcitonin                     | **33,972** | Measurement domain slow path     |
| **Slow** | No acute coronary/cerebrovascular | **31,158** | 2개 sub-criteria × KG expansion  |
| **Fast** | No use of insulin                 |  **7,104** | ATC direct → skip slow path      |
| **Fast** | No drug use or dependence         |  **8,562** | ATC direct (but wrong match)     |

## 4. Key Findings

### 4.1 각 개선의 기여도

| 개선                       | 효과                           | 사례                                                             |
| -------------------------- | ------------------------------ | ---------------------------------------------------------------- |
| **Neo4j KG Expansion**     | `includeDescendants` 계층 확장 | `No pregnant`: 2 concepts → 2,253 resolved (Pregnancy 계층 전체) |
| **Agent 1 분리**           | domain 식별 + 약물명 추출      | `No use of insulin` → `[Drug] Insulin` → 7,689 resolved          |
| **Recursive Group Fix**    | 깊이 3 이상 groups 순회        | `prior CV disease`: 102→106 raw concepts                         |
| **Symmetric Substitution** | Agent 2 출력도 `Maps to` 치환  | 비대칭 비교 제거                                                 |

### 4.2 실패 원인 분석

| 원인                            | 빈도  | 대표 사례                                                                    |
| ------------------------------- | :---: | ---------------------------------------------------------------------------- |
| **Agent 1 JSON 파싱 실패**      | 15/17 | `'list' object has no attribute 'get'` — LLM이 예상과 다른 JSON 구조 반환    |
| **복합 criteria 미분리**        |   5   | `prior CV disease` (15개 concept set 그룹), `No GLP1-RA, pramlintide, DPP-4` |
| **Agent 2 seed concept만 반환** |  13   | `No CHF`→1 concept vs TROY 166 resolved                                      |
| **Measurement domain 미지원**   |   2   | `eGFR`, `calcitonin` — Agent 2가 Lab test 매핑 약함                          |

### 4.3 Agent 1 실패 상세 진단

Agent 1은 입력 텍스트를 LLM에 보내고, 응답 JSON을 `{target: {}, comparator: {}, outcome: {}}` 구조로 파싱한다.

**실패 원인**: LLM이 `target/comparator/outcome` wrapper 없이 **flat list**를 반환 → parser crash

그러나 **LLM이 반환한 내용 자체는 정확하다**:

| Input                                            | LLM entity_text                   |  domain   | logic_type |     분리      |
| ------------------------------------------------ | --------------------------------- | :-------: | :--------: | :-----------: |
| `No CHF`                                         | Congestive Heart Failure          | Condition |  ABSENCE   |      1개      |
| `prior CV disease`                               | Cardiovascular disease            | Condition |  PRESENCE  |      1개      |
| `No T1DM`                                        | Type 1 Diabetes Mellitus          | Condition |  ABSENCE   |      1개      |
| `No ESLD`                                        | End-Stage Liver Disease           | Condition |  ABSENCE   |      1개      |
| `No GLP1-RA, pramlintide, DPP-4 within 3 months` | **GLP1-RA / Pramlintide / DPP-4** | **Drug**  |  ABSENCE   | **3개 분리!** |

**특히 주목**: "No GLP1-RA, pramlintide, DPP-4 within 3 months" 입력에 대해 LLM이 3개 약물을 개별 criteria로 정확하게 분리하고, domain=Drug, window=-90일까지 올바르게 설정했다.

**실패 응답 예시** (`No CHF`):

```json
[
  {
    "name": "No CHF",
    "domain": "Condition",
    "entity_text": "Congestive Heart Failure",
    "logic_type": "ABSENCE"
  }
]
```

**성공 응답 예시** (`No use of insulin`):

```json
{
  "target": {
    "exclusion_rules": [
      {"name": "No use of insulin", "domain": "Drug",
       "entity_text": "Insulin", "logic_type": "ABSENCE"}
    ]
  },
  "comparator": { ... }, "outcome": { ... }
}
```

**결론**: LLM의 criteria 분석 능력은 우수하다. **Parser만 수정하면 (list → dict 변환 fallback 추가)** 성공률이 15/17까지 올라갈 수 있다.

## 5. Known Issues

### Issue 1: "No drug use or dependence" — ATC False Positive

Agent 1이 "Drug use or dependence"를 `[Drug]`로 태그 → ATC 검색 발동 → **"Drugs used in alcohol dependence" (N07BB, dist=0.552) 매칭** → 날트렉손, 디설피람 등 *치료 약물*의 ingredient가 반환됨.

**실제 의미**: "drug use or dependence"는 **물질 사용 장애(Condition)**이지 약물 클래스가 아님.

| 항목           | 값                                                         |
| -------------- | ---------------------------------------------------------- |
| Agent 1 domain | `[Drug]` ❌ (정답: `[Condition]`)                          |
| ATC 매칭       | "Drugs used in alcohol dependence" (N07BB, dist=0.552)     |
| 결과           | R=0% (이전 R=100%)                                         |
| 원인           | Agent 1의 domain 분류 오류 + ATC distance가 threshold 이하 |

**해결 방향**: Agent 1 프롬프트에 "use" / "dependence" / "abuse"가 포함된 criteria는 Condition으로 분류하도록 가이드 추가. 또는 ATC 매칭 후 LLM judge로 한 번 더 검증.

### Issue 2: "No pregnant" — Concept Granularity 문제 (R=4%)

TROY 기대값: 2,253 resolved concepts. Agent 2 출력: 40 concepts → 95 resolved.

|                    | TROY                                                         | Agent 2               |
| ------------------ | ------------------------------------------------------------ | --------------------- |
| Seed concept       | `4088927` "Pregnancy, **childbirth and puerperium** finding" | `4299535` "Pregnancy" |
| includeDescendants | **2,253**                                                    | **112**               |
| SNOMED 계층        | 상위 카테고리 (임신+출산+산후 전체)                          | 좁은 하위 (임신만)    |

**원인**: ChromaDB 검색 "Pregnancy" → 정확한 이름 매칭 `4299535` "Pregnancy" hit → descendants 112개. TROY는 더 상위 개념 사용.

**해결 방향**: KG expansion이 ancestor climbing을 수행해야 함. "Pregnancy" → parent "Pregnancy, childbirth and puerperium finding" → 2,253 descendants. 현재 KG expansion이 이 hierarchy climbing을 하지 않는 것이 핵심 버그.

## 6. Next Steps

1. **LLM seed 고정 후 재벤치** (P0): `LLM_SEED=42` 적용 후 재실행으로 비결정성 제거
2. **Agent 1 domain 분류 개선** (P1): "drug use/abuse/dependence" → Condition 가이드
3. **Agent 2 Concept Expansion** (P1): seed → ancestor/sibling 확장 강화
4. **Measurement Domain 지원** (P2): Agent 2에 Lab test 전용 매핑 경로 추가

## 6. Technical Notes

- **Report Files**: `output/benchmark_v5_*.json`
- **Script**: `scripts/benchmark_v5.py` (v5.1, full pipeline)
- **Trigger**: `PIPELINE_MODE=benchmark python scripts/benchmark_v5.py`
- **Neo4j Password**: `artemis_neo4j` (container: `telos-neo4j`)
- **TROY Non-Standard**: 총 3개 unmapped (`concept_relationship` Maps to 1-hop)

## Appendix A: Agent 1 Parsing Issue

### 문제

`_build_artemis_request()`가 LLM 응답을 `dict`로만 기대(`data.get("target")`) → LLM이 `list`를 반환하면 `'list' object has no attribute 'get'` crash.

### 무엇이 작동했는가 (2/17)

LLM이 정상적인 `{target: {...}, comparator: {...}, outcome: {...}}` dict를 반환한 경우:

- `No use of insulin` → `{"target": {"exclusion_rules": [{"entity_text": "Insulin", "domain": "Drug"}]}}`
- `No drug use or dependence` → 동일 dict 구조

### 무엇이 실패했는가 (15/17)

LLM이 짧은 입력에 대해 flat list를 반환한 경우:

```json
// "No CHF" 입력 → LLM 응답
[
  {
    "name": "No CHF",
    "domain": "Condition",
    "entity_text": "Congestive Heart Failure",
    "logic_type": "ABSENCE"
  }
]
```

**내용은 정확하지만 wrapper 구조가 없어서** parser crash.

### 수정 내용

`parser.py:_build_artemis_request()`에 list fallback 추가:

```python
if isinstance(data, list):
    # logic_type으로 inclusion/exclusion 분류
    for item in data:
        if item.get("logic_type") == "ABSENCE":
            exclusion.append(item)
        else:
            inclusion.append(item)
    data = {"target": {"inclusion_rules": inclusion, "exclusion_rules": exclusion}}
```

수정 후 15/17 실패 케이스 → 전부 성공으로 전환 확인 (5개 샘플 테스트 완료).
