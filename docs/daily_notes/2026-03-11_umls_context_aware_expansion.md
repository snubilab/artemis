# 2026-03-11: UMLS Context-Aware Expansion (MRSTY 통합)

## 배경

Procedure/Surgery 도메인 매핑 실패 근본 원인 분석 결과:

- **Embedding Confusion**: "ACS" → Acrocephalosyndactyly, "fibrinolytic" → fibrinogen
- **원인**: ChromaDB vector search에서 의미적으로 유사한 잘못된 concept이 상위에 랭크됨
- **기존 약어 사전(abbreviation_expander.py)**: exact match만 가능, "ACS (excluding STEMI)" 같은 compound query 미처리
- **사전 제거 결정**: 하드코딩 130개 항목 → no-op으로 변경. UMLS가 대체해야 함

## 오늘 수정한 코드

### 1. `drug_class_expander.py` — ATC ingredient count 검증

- ATC 매칭 후 RxNorm Ingredient ≤2개 → reject (개별 약물이 아닌 drug class만 통과)
- "Fibrinolytic agents" → "Fibrinogen" (1개 ingredient) → **reject됨** ✅

### 2. `workflow.py` — Drug class → slow path 강제

- `domain_hint="Drug"` + query에 "agents/inhibitors/drugs" 패턴 → fast path → slow path 전환
- Slow path에서 UMLS diverse rewrite 실행됨

### 3. `workflow.py` — UMLS diverse rewrite (slow path)

- UMLS CUI의 synonym 중 **다른 root word**를 가진 것 최대 2개를 추가 ChromaDB 검색어로 사용
- "Fibrinolytic agents" → UMLS → "Drug, Thrombolytic" → retriever.search() 추가

### 4. `abbreviation_expander.py` — 사전 제거

- 130개 하드코딩 약어 사전 전체 제거, no-op 함수로 변환

## 벤치마크 결과 (변경 후)

| Trial    | R (before→after) | P (before→after) |
| -------- | ---------------- | ---------------- |
| PLATO    | 47.1% → 47.1%    | 29.1% → 29.1%    |
| LEADER   | 76.2% → 75.2%    | 67.1% → 67.8%    |
| EMPA-REG | 65.6% → 64.5%    | 65.1% → 63.8%    |

- Concept 품질은 개선 (ACS: Acrocephalosyndactyly → Acute coronary syndrome)
- 수치 변화 없음: **bottleneck이 seed 개수** (Agent2가 2~4개 vs GOLD 5~11개)

---

## TODO: MRSTY.RRF 통합 (다운로드 완료 후)

### Step 1: MRSTY.RRF → SQLite 테이블 추가

MRSTY.RRF 포맷: `CUI|TUI|STN|STY|ATUI|CVF|`

```bash
# build_umls_sqlite.py 수정하거나 별도 스크립트 작성
python scripts/build_umls_mrsty.py \
    --input /path/to/MRSTY.RRF \
    --db data/umls/mrconso.sqlite
```

생성할 테이블:

```sql
CREATE TABLE mrsty (
    cui  TEXT NOT NULL,
    tui  TEXT NOT NULL,  -- e.g., T047
    sty  TEXT NOT NULL   -- e.g., "Disease or Syndrome"
);
CREATE INDEX idx_mrsty_cui ON mrsty(cui);
CREATE INDEX idx_mrsty_sty ON mrsty(sty);
```

### Step 2: domain_hint → Semantic Type 매핑 정의

```python
DOMAIN_TO_STY = {
    "Condition": {
        "Disease or Syndrome",
        "Neoplastic Process",
        "Finding",
        "Sign or Symptom",
        "Pathologic Function",
        "Mental or Behavioral Dysfunction",
        "Congenital Abnormality",
        "Injury or Poisoning",
    },
    "Drug": {
        "Pharmacologic Substance",
        "Clinical Drug",
        "Antibiotic",
        "Organic Chemical",  # many drugs are here
    },
    "Procedure": {
        "Therapeutic or Preventive Procedure",
        "Diagnostic Procedure",
        "Health Care Activity",
        "Laboratory Procedure",
    },
    "Measurement": {
        "Laboratory or Test Result",
        "Laboratory Procedure",
        "Diagnostic Procedure",
        "Clinical Attribute",
    },
}
```

### Step 3: `umls_synonym_expander.py` 수정 — `get_cuis()`에 domain 필터 추가

```python
def get_cuis(self, query: str, domain_hint: Optional[str] = None) -> List[str]:
    # 1. Exact match → CUI 후보 목록
    cuis = [exact match 결과]

    # 2. domain_hint가 있으면 MRSTY로 필터
    if domain_hint and cuis and self._has_mrsty:
        allowed_stys = DOMAIN_TO_STY.get(domain_hint, set())
        if allowed_stys:
            filtered = []
            for cui in cuis:
                cur.execute("SELECT sty FROM mrsty WHERE cui = ?", (cui,))
                stys = {row[0] for row in cur.fetchall()}
                if stys & allowed_stys:  # 교집합 있으면 통과
                    filtered.append(cui)
            if filtered:
                cuis = filtered  # 필터된 결과가 있을 때만 대체

    return cuis
```

핵심 효과:

- `"ACS" + domain_hint="Condition"` → C0948089 (Acute Coronary Syndrome) ✅
- `"ACS" + domain_hint=None` → C0002455 (American Cancer Society) ← 기존 동작 유지

### Step 4: `workflow.py`에 domain_hint 전달

현재 `_slow_path()`의 UMLS expander에 `domain_hint`를 전달하도록 수정:

```python
# 현재: self.umls_expander.expand(query_text, max_synonyms=3)
# 변경: self.umls_expander.expand(query_text, max_synonyms=3, domain_hint=domain_hint)
```

### Step 5: 벤치마크 실행 및 비교

```bash
# 3개 trial 재실행
PIPELINE_MODE=benchmark conda run --no-capture-output -n artemis \
    python scripts/benchmark_a_direct.py \
    --troy data/gold/PLATO/PLATO_GOLD.json \
    --report-dir data/gold/PLATO/ --no-agent2-cache

# LEADER, EMPA-REG 동일하게 실행
```

기대 효과:

- ACS → Acute coronary syndrome (Condition 도메인 필터) → seed 품질 향상
- fibrinolytic → Thrombolytic drug (Drug 도메인 필터) → Drug 도메인 concept 우선 반환
- STEMI → ST elevation myocardial infarction (Condition 필터) → 정확한 매핑

---

## Ablation: Domain-Balanced Retrieval (#2) ❌ 폐기

`_slow_path()` 내 ChromaDB 후보를 `domain_id` 기준으로 균등 분배 시도.

| Metric   | Baseline | Domain-Balanced | Δ           |
| -------- | -------- | --------------- | ----------- |
| LEADER R | 75.2%    | 64.9%           | **-10.3pp** |
| LEADER P | 67.8%    | 61.7%           | **-6.1pp**  |

**실패 원인**: 대부분 규칙은 단일 도메인. Minority 도메인 강제 삽입 → 좋은 candidate 밀어냄.
즉시 revert. → [ABLATION_STUDY.md §2.11](../experiments/ABLATION_STUDY.md)

## Transplant domain_hint 조사

GOLD Transplant 규칙이 4개 concept set (2 domain)으로 구성된 것을 확인:

| ConceptSet                      | domain_hint | GOLD concepts                             |
| ------------------------------- | ----------- | ----------------------------------------- |
| `kidney transplant (condition)` | Condition   | Transplanted kidney present (1개)         |
| `kidney transplant (procedure)` | Procedure   | Transplant of kidney (1개)                |
| `organ transplant_cond`         | Condition   | present/failure/rejection 등 (10개)       |
| `transplant_proc`               | Procedure   | solid organ/liver/heart transplant (10개) |

벤치마크 코드(`benchmark_v5.py` L226-241)에서 `cs_domains` 딕셔너리로 CS마다 올바른 domain_hint 전달 확인 → **버그 아님**.

**핵심 발견**: 문제는 domain_hint가 아니라 Agent2가 **Procedure 도메인에서 "transplant" 검색 시 합병증(complication) 개념 위주로 반환**하는 것. ChromaDB embedding 품질 문제.

## 발견/결론

1. Domain-balanced retrieval은 전역 적용 시 regression (-10.3pp). 혼합 도메인 쿼리에만 선택 적용해야 하나, 사전 식별이 어려움
2. Transplant 문제의 bottleneck은 **ChromaDB embedding이 "transplant procedure"와 "transplant complication"을 구분 못함**
3. 약어 사전 제거 후 UMLS MRSTY 기반 context-aware expansion이 필요하나 MRSTY.RRF 다운로드 대기 중
4. **seed 개수 부족** (2-4개 vs GOLD 5-11개)이 recall의 가장 큰 bottleneck

### Ablation: Pass 3 Footprint Guard (§2.12) ❌

Hybrid policy에 sibling/maps_to desc>1000 → `includeDescendants=false` 추가. R -10.9pp, P -7.1pp. Default OFF.

### Ablation: Reranker Top-N 3→5 (§2.13) ❌

Cross-branch concept noise 증가. R -11.1pp, P -7.2pp. Revert.

### 오늘의 결론

| #     | Ablation                  | ΔR      | ΔP     | 판정 |
| ----- | ------------------------- | ------- | ------ | ---- |
| §2.10 | ATC+UMLS rewrite          | ~0pp    | ~0pp   | 중립 |
| §2.11 | Domain-balanced retrieval | -10.3pp | -6.1pp | ❌   |
| §2.12 | Pass 3 Footprint Guard    | -10.9pp | -7.1pp | ❌   |
| §2.13 | Reranker Top-N 3→5        | -11.1pp | -7.2pp | ❌   |

~~**현재 파이프라인이 local optimum 도달**~~ → **Supervisor Phase 0로 돌파!**

---

## 🚀 Supervisor Phase 0: domain_hint 버그 수정 (21:40)

`cohort_pipeline.py` `_map_all_entities()`에서 Agent 1 domain → Agent 2 전달 누락 발견.
한 줄 수정: `process_with_details(entity["text"], domain_hint=entity.get("domain"))`

### Multi-Trial E2E 결과 (fix 전 → 후)

| Trial    | Before R | **After R** | ΔR         | Before P | **After P** | ΔP     |
| -------- | -------- | ----------- | ---------- | -------- | ----------- | ------ |
| LEADER   | 72.5%    | **77.4%**   | **+4.9pp** | 61.5%    | 59.7%       | -1.8pp |
| EMPA-REG | 46.9%    | **46.6%**   | -0.3pp     | 49.9%    | 52.3%       | +2.4pp |
| PLATO    | 36.4%    | **36.4%**   | 0.0pp      | 19.1%    | 19.1%       | 0.0pp  |

### A_direct 대비 Gap

| Trial    | A_direct R | E2E R     | Gap                          |
| -------- | ---------- | --------- | ---------------------------- |
| LEADER   | 75.2%      | **77.4%** | **+2.2pp** (E2E > A_direct!) |
| EMPA-REG | 64.5%      | 46.6%     | -17.9pp                      |
| PLATO    | 47.1%      | 36.4%     | -10.7pp                      |

> 4개 ablation 전체(-10pp)보다 **한 줄 버그 수정**(+4.9pp)이 더 큰 효과.
> LEADER E2E가 A_direct를 초과: Agent 1 Hierarchical Expansion이 원본에 없는 concept 발견.

_마지막 업데이트: 2026-03-11T22:17_
