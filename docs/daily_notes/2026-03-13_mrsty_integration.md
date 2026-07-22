# 2026-03-13: MRSTY 통합 — Domain-Aware CUI Filtering

## 배경

`TODO_mapping_quality.md`에서 **BLOCKED** 상태였던 MRSTY 기반 개선:

- UMLS Full Metathesaurus zip (5.2GB) 다운로드 완료
- MRSTY.RRF (210MB) = CUI → Semantic Type 매핑 (예: C0742343 → "Disease or Syndrome")

## 작업 내용

### 1. MRSTY.RRF 추출 및 SQLite 적재

```bash
# zip에서 MRSTY.RRF만 추출
unzip -o data/umls/umls-2025AB-metathesaurus-full.zip "2025AB/META/MRSTY.RRF" -d data/umls/

# 기존 mrconso.sqlite에 mrsty 테이블 추가
python scripts/build_umls_mrsty.py \
    --input data/umls/2025AB/META/MRSTY.RRF \
    --db data/umls/mrconso.sqlite
```

결과:

- 3,834,110 rows, 3,488,973 unique CUIs, 127 Semantic Types
- 빌드 시간: 8.4초
- SQLite 크기: 1,277MB → 1,597MB (+320MB)
- mrconso와 mrsty 교집합 CUI: 1,664,447개

### 2. `scripts/build_umls_mrsty.py` 신규 작성

MRSTY.RRF (`CUI|TUI|STN|STY|ATUI|CVF|` 포맷)에서 `(cui, tui, sty)` 3컬럼만 추출.
기존 `mrconso` 테이블은 건드리지 않고, `mrsty` 테이블만 `DROP IF EXISTS` → 재생성.

### 3. `umls_synonym_expander.py` 수정

**변경 1: `DOMAIN_TO_STY` 매핑 추가**

OMOP domain_hint → UMLS Semantic Type 매핑 (4개 도메인):

| Domain      | Semantic Types                                                                  |
| ----------- | ------------------------------------------------------------------------------- |
| Condition   | Disease or Syndrome, Neoplastic Process, Finding, Sign or Symptom, ... (10종)   |
| Drug        | Pharmacologic Substance, Clinical Drug, Antibiotic, Organic Chemical, ... (8종) |
| Procedure   | Therapeutic or Preventive Procedure, Diagnostic Procedure, ... (5종)            |
| Measurement | Laboratory or Test Result, Laboratory Procedure, Clinical Attribute, ... (4종)  |

**변경 2: `_init_db()`에 MRSTY 테이블 감지**

```python
self._has_mrsty = False  # 신규 플래그
# sqlite_master에서 'mrsty' 테이블 존재 확인
```

**변경 3: `get_cuis(query, domain_hint=None)` — domain filtering**

```python
def _filter_cuis_by_domain(self, cuis, domain_hint):
    if not domain_hint or not self._has_mrsty:
        return cuis  # 기존 동작 유지
    allowed_stys = DOMAIN_TO_STY.get(domain_hint, set())
    filtered = [cui for cui in cuis if self._cui_matches_sty(cui, allowed_stys)]
    return filtered if filtered else cuis  # graceful degradation
```

**변경 4: `expand(query, ..., domain_hint=None)` — domain_hint 추가**

`expand()` → `get_cuis()` 호출 시 domain_hint 전달.

### 4. `workflow.py` 수정 — domain_hint 전달 (2곳)

```diff
# _slow_path() 내 UMLS diverse rewrite
-            cuis = self.umls_expander.get_cuis(query_text)
+            cuis = self.umls_expander.get_cuis(query_text, domain_hint=domain_hint)

# _slow_path() 내 UMLS multi-query expansion
-            synonyms = self.umls_expander.expand(query_text, max_synonyms=3)
+            synonyms = self.umls_expander.expand(query_text, max_synonyms=3, domain_hint=domain_hint)
```

## 검증 결과

```
[T1] ACS (no domain):  8 CUIs → ['C0002455'(American Cancer Society), ...]
     ACS (Condition):   1 CUI  → ['C0742343'(Acute Chest Syndrome)]
     Filter: 8 → 1

[T2] expand('ACS'):
     no-domain → ['Society, American Cancer', ...]     ← 의료 무관
     Condition → ['Syndrome, Acute Chest', ...]         ← 정확한 의료 동의어

[T3] diabetes mellitus (Condition): 1 CUI ✅
[T4] Unknown domain passthrough ✅ (graceful degradation)
```

## 변경 파일 요약

| 파일                                         | 변경                                         |
| -------------------------------------------- | -------------------------------------------- |
| `scripts/build_umls_mrsty.py`                | [NEW] MRSTY.RRF → SQLite 빌드 스크립트       |
| `src/agents/agent2/umls_synonym_expander.py` | DOMAIN_TO_STY, \_has_mrsty, domain filtering |
| `src/agents/agent2/workflow.py`              | \_slow_path() 내 2곳 domain_hint 전달        |
| `docs/TODO_mapping_quality.md`               | BLOCKED → ✅ 완료                            |

## 다음 단계

- [ ] PLATO 벤치마크 재실행: ACS rule recall 0% → 개선 확인
- [ ] LEADER 벤치마크 재실행: R/P 변화 측정
- [ ] Procedure/Surgery 매핑: MRSTY 기반 slow path 필터 효과 분석
