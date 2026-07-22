# RFC-001: TROY-ARTEMIS Gap Closing 전략

**상태**: 검토 중  
**날짜**: 2026-02-10  
**제안자**: @kyh + Gemini-3-Pro (토론)  

## 1. 가설 및 목표

ARTEMIS 파이프라인이 자동 생성하는 Circe-be JSON은 전문가 수작업(TROY) 대비 **ConceptSet 수 73% 부족, InclusionRule 수 61% 부족**하다.

| 메트릭 | TROY (Expert) | ARTEMIS (Auto) | Gap |
|--------|:---:|:---:|:---:|
| ConceptSets | 49 | 13 | -73% |
| InclusionRules | 18 | 7 | -61% |
| Items/CS (avg) | ~8 | ~1 | -87% |
| EndStrategy | CustomEra | None | ❌ |
| PrimaryCriteria | DrugEra | DrugExposure | ⚠️ |

**목표**: TROY Concept ID 기준 Recall 50% 이상 달성 (현재 추정 <10%) + 구조적 완전성 확보

**성공 기준**: LEADER Trial에서 Precision ≥ 70%, Recall ≥ 50%, 구조적으로 DrugEra + CustomEra EndStrategy 포함

## 2. 제안 설계 (Proposed Design)

> [!IMPORTANT]
> 이 전략은 Gemini-3-Pro와 2라운드 토론을 통해 도출되었습니다.

### Phase 1: 즉시 실행 가능한 개선 (Week 1)

#### 1-1. ConceptSet Descendant 자동 확장

**현재 문제**: Agent 2가 ConceptSet당 1개 Concept만 매핑. TROY는 `includeDescendants: true`를 활용하여 하위 개념까지 자동 포함.

**해결**: Agent 2 출력의 ConceptSet Expression에 `includeDescendants: true` 기본 적용

```diff
# Agent 2 output format 변경
{
  "concept": { "CONCEPT_ID": 1503297, ... },
  "isExcluded": false,
- "includeDescendants": false,
+ "includeDescendants": true,
  "includeMapped": true
}
```

**영향**: 코드 변경 최소 (Agent 2/3의 output formatter만 수정), Recall 대폭 향상 예상

#### 1-2. DrugEra PrimaryCriteria + CustomEra EndStrategy

**현재 문제**: ARTEMIS는 `DrugExposure` 사용, EndStrategy 없음. TROY는 `DrugEra` + `CustomEra(GapDays=30)` 사용.

**해결**: Agent 3 Assembler에서 Drug 기반 코호트일 때 DrugEra + CustomEra를 기본 Skeleton으로 사용

```python
# Agent 3: Drug cohort의 기본 구조
if primary_domain == "Drug":
    primary_criteria = {"DrugEra": {"CodesetId": cs_id}}
    end_strategy = {"CustomEra": {
        "DrugCodesetId": cs_id, "GapDays": 30, "Offset": 0
    }}
```

---

### Phase 2: Agent 구조 개선 (Week 2-3)

#### 2-1. Phoebe Enrichment (Agent 2 후처리)

**위치**: Agent 2의 매핑 완료 후, Agent 3에 전달하기 전 **Enrichment 단계** 추가

```
Agent 2 Flow:
Text → UMLS Search → Athena Mapping → [NEW] Phoebe Enrichment → Enriched ConceptSet
```

- `phoebe/concept_recommended.csv`에서 매핑된 Standard Concept의 추천 개념 조회
- Record Count(RC) 기준 필터링으로 노이즈 제거
- Agent 3에는 단일 ID가 아닌 **Enriched ConceptSet 리스트** 전달

#### 2-2. Agent 3 Skeleton + Slot Filling 리팩토링

**현재**: Agent 3은 IR로부터 하드코딩 방식으로 JSON을 조립
**변경**: Composable Skeleton 패턴으로 전환

| Skeleton | 용도 |
|----------|------|
| `drug_era_entry` | Drug 기반 코호트 진입 |
| `condition_entry` | Condition 기반 코호트 진입 |
| `washout_rule` | Prior 기간 내 약물/조건 배제 |
| `measurement_rule` | HbA1c, eGFR 등 측정값 기반 조건 |
| `temporal_rule` | "within N days" 시간 기반 조건 |
| `custom_era_exit` | Drug persistence 종료 전략 |

---

### Phase 3: TROY-as-Teacher RAG (Week 3-4)

#### 3-1. Ground Truth 확장

| Tier | Source | 개수 | 용도 |
|------|--------|:---:|------|
| Gold | TROY 코호트 (보유) | 6개 | 최상위 참조 |
| Silver | OHDSI Phenotype Library | 100+개 | RAG 검색 대상 |

#### 3-2. RAG 워크플로우

```
NCT 텍스트 → Agent 1 (IR) → Retriever → 유사 TROY/Phenotype JSON 3개 검색
→ Agent 3: "이 참조 JSON 구조를 기반으로 수정" (Delta-Modification)
```

- ChromaDB에 TROY + Phenotype Library JSON 인덱싱
- Agent 1 출력(IR)과 유사한 기존 코호트 정의를 검색
- Agent 3는 in-context example로 검색 결과를 활용

## 3. 예상되는 리스크 (Potential Risks)

| 리스크 | 영향 | 완화 방안 |
|--------|------|-----------|
| `includeDescendants` 과확장 | 불필요한 하위 개념 포함으로 Precision 하락 | OHDSI vocabulary hierarchy 기반 도메인별 규칙 적용 |
| Phoebe CSV가 대규모 (수GB) | 메모리/속도 이슈 | SQLite로 변환 후 인덱스 쿼리 |
| OHDSI Phenotype Library 접근성 | Public API 불안정 | 로컬 미러링 |
| Skeleton이 새로운 시험 유형 미대응 | 커버리지 부족 | Fallback으로 기존 from-scratch 방식 유지 |

## 4. 해결되지 않은 질문

1. OHDSI Phenotype Library에서 JSON을 대량 다운로드하는 공식 API가 있는가?
2. Phoebe CSV의 최신 버전은 어디서 확보하는가? (현재 `phoebe/` 디렉토리에 존재 확인 필요)
3. `includeDescendants` 적용 시 도메인별로 다르게 처리해야 하는가? (Drug은 true, Condition은 선택적?)

## 5. 실행 우선순위 (Impact × Feasibility)

| 순위 | 전략 | Impact | Feasibility | 예상 기간 |
|:---:|------|:---:|:---:|:---:|
| **1** | ConceptSet Descendant 자동 확장 | ★★★★ | ★★★★★ | 1일 |
| **2** | DrugEra + CustomEra EndStrategy | ★★★★ | ★★★★ | 1-2일 |
| **3** | Skeleton + Slot Filling (Agent 3) | ★★★★ | ★★★ | 3-5일 |
| **4** | TROY + Phenotype Library RAG | ★★★★★ | ★★★ | 5-7일 |
| **5** | Phoebe Enrichment (Agent 2) | ★★★ | ★★★ | 3-5일 |

## 6. 타임라인

- **Week 1**: Phase 1 (순위 1-2) — 즉시 실행, LEADER Trial 재실행 + 비교
- **Week 2-3**: Phase 2 (순위 3, 5) — Agent 구조 리팩토링
- **Week 3-4**: Phase 3 (순위 4) — RAG 구축 + Delta-Modification 프로토타입
