# BUG: WebAPI ConceptSet Stripping → Silent 0-Patient Failure

**Date**: 2026-02-27  
**Severity**: High  
**Affected**: Incremental exclusion analysis script (cohort generation via WebAPI)

---

## 증상

SYNTHEA23M에서 LEADER Entry-Only = **14,397명**, +Age ≥ 50 = **0명**.  
DB 직접 조회 시 Age ≥ 50 해당자 = **2,343명**.

## 원인

Incremental exclusion 스크립트가 각 단계에서 **현재 InclusionRules가 참조하는 ConceptSet만** 남기고 나머지를 제거:

```python
# ❌ 버그 코드
needed_cs_ids = collect_referenced_cs(rules_so_far)
incr["ConceptSets"] = [cs for cs in troy["ConceptSets"] if cs["id"] in needed_cs_ids]
# 49개 → 1~2개로 축소
```

WebAPI(Circe)는 ConceptSet 배열이 불완전할 때 **에러 없이 0명을 반환** (silent failure).

## 수정

```python
# ✅ 수정
incr["ConceptSets"] = modified["ConceptSets"]  # 49개 전부 유지
```

## 영향 범위

| Dataset | 항목 | 버그 | 수정 후 |
|---------|------|:---:|:---:|
| 100K | Entry-Only | 1,238 | 1,238 |
| 100K | +Age ≥ 50 | 272 | 272 |
| **23M** | Entry-Only | 14,397 | 14,397 |
| **23M** | **+Age ≥ 50** | **0** | **2,343** |

100K에서는 ConceptSet 수가 적어 우연히 정상 동작했으나, 23M에서 manifest.

## 교훈

WebAPI cohort definition에서 **ConceptSets는 항상 전체를 포함**해야 한다.  
사용하지 않는 ConceptSet이 있어도 제거하면 안 됨 — Circe SQL 생성 시 internal reference가 깨짐.

## 관련 파일

- `/tmp/incremental_exclusion.py` (이전 버그 버전)
- `/tmp/leader_23m_fix.py` (수정 버전)
