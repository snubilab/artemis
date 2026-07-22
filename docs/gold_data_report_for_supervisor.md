# Gold Standard 데이터 구축 현황

**Date**: 2026-03-11

---

## 임상시험 요약 (Study Summary)

| 항목 | **LEADER** | **PLATO** | **ARISTOTLE** |
|------|:----------:|:---------:|:-------------:|
| **질환그룹 (Disease Group)** | T2DM + CV risk | ACS | Non-valvular AF |
| **Trial (Reference)** | NCT01179048 (Zinman 2016) | NCT00391872 (Wallentin 2009) | NCT00412984 (Granger 2011) |
| **타겟 약물 / 대조군** | Liraglutide vs Placebo | Ticagrelor vs Clopidogrel | Apixaban vs Warfarin |
| **Rules** | 18 | 5 | 15 |
| **ConceptSets** | 56 | 24 | 33 |
| **Concepts** | 241 | 115 | 136 |

---

## LEADER

**특이사항**:

- **구축**: TROY v1.1의 age-stratified inclusion 구조(≥50+CV disease, ≥60+risk factor)를 v3.4에 이식하고, v3.4의 condition 커버리지(ESLD, transplant 등)를 결합
- **버그 수정**: v3.4 HbA1c rule에서 원본 버그 발견 (Value=10, Op=gte → Value=7, Op=lt로 수정)
- **미구현**: E-7 (Planned revascularization) — TROY v1.1, v3.4 양쪽 모두 미구현
- **프로토콜 외 추가**: Substance abuse, Pregnancy — 원문 프로토콜에 없으나 TROY가 추가한 기준
- **구조적**: 고아 ConceptSet 14개 (rule 미연결), 중복 CS 3쌍 (LVH, LVD, Revascularization)
- **Insulin 배제 범위 (Codex 점검 완료)**:
  - CS 95 "Insulin"에 19 concepts, 모두 `includeDescendants=true`
  - 프로토콜상 **허용**: human NPH, long-acting (glargine, detemir, degludec), premixed
  - 프로토콜상 **배제 대상**: rapid-acting (aspart, lispro, glulisine), short-acting (regular)
  - **현황**: broad class concept `21600713 (INSULINS AND ANALOGUES)` 포함 → 사실상 전체 인슐린 배제
  - **결정**: 현행 유지. TROY v3.4 원본 보수적 배제 정책으로 문서화. 프로토콜과의 차이를 인지하되 Gold 수정하지 않음

---

## ARISTOTLE

**특이사항**:

- **구축**: TROY v3.4 기반 + v1.1 cherry-pick (DM, Bilirubin 개념 추가)
- **도메인 특성**: AF 도메인으로, 약물(Drug class)보다 질환(Condition hierarchy, e.g., stroke, ICH, CKD 등)의 비중이 높음
- **비교군 설계**: Target(Apixaban entry → Warfarin exclusion), Comparator(Warfarin entry → Apixaban exclusion) 설계 적절함
- **CS 정리**: v3.4 원본에 존재하던 Orphan CS 13개(미사용 심부전, 수술 등)를 Gold 구축 시 제거 완료
- **벤치마크 미측정**: Gold는 구축되었으나 Agent 2 E2E 평가 전 (다른 질환군과 성능 패턴 차이 예상)

---

## PLATO

**특이사항**:

- **구축**: v3.4 기반 + v1.1의 DM concepts(+6개) 및 CrCl concepts(+2개) cherry-pick
- **단순 구조**: ACS treatment trial 특성상 5개 rule만 존재 (Inc 1 + Exc 4)
- **Drug class 의존도**: 5 rules 중 4개가 약물 관련 (fibrinolytics, anticoagulants, CYP 3A4 inhibitors, clopidogrel)
- **CYP inhibitor 목록**: 12개 약물(Amiodarone, Carbamazepine 등)은 TROY 큐레이터 임상 판단 기반, 포함/제외 근거 문서화 없음
- **미구현 criteria 3개**:
  - E-1: Clopidogrel contraindication (너무 일반적, 코딩 불가)
  - E-5: Increased risk of bradycardia (임상적 판단 필요)
  - E-6: Moderate/severe liver disease (NCT에만 명시, 본문 미기재)
- **Orphan CS**: LBBB, MI, Prasugrel — 프로토콜 관련이나 rule에 미연결

---

## Codex CLI 자동 점검 결과

> gpt-5.3-codex-spark, reasoning=high | 142K tokens | 2026-03-11

| 항목                 |         **LEADER**         |         **PLATO**            |        **ARISTOTLE**         |
| -------------------- | :------------------------: | :--------------------------: | :--------------------------: |
| Circe JSON 파싱      |             ✅             |              ✅              |              ✅              |
| 참조된 CS / 전체 CS  |          42 / 56           |           20 / 24            |           33 / 33            |
| Orphan CS            |             14             |              4               |              0               |
| 중복 CS 그룹         |             3              |        1 (ticagrelor)        |              0               |
| Non-standard concept |             23             |              9               |             TBD              |
| Invalid reason 위반  |             4              |              2               |             TBD              |
| Protocol 미구현      |    E-7 planned revasc.     |  3개 (contraindication 등)   |             미상             |
| Protocol 외 추가     | substance abuse, pregnancy | ICH, peptic ulcer, prasugrel |             최소             |

**주요 지적사항**:

- 🔴 LEADER / PLATO 모두 `STANDARD_CONCEPT='S'` 미충족 concept 포함 → non-standard concept 교체 또는 정당성 문서화 필요
- 🟡 LEADER orphan CS 14개 + 중복 3그룹 → 정리 필요
- 🟡 PLATO CYP3A4 목록은 큐레이터 판단이며 evidence-based versioning 필요
- 🟢 ARISTOTLE orphan CS 전면 제거되어 구조적으로 깔끔함 (가장 최근 구축)

> 상세 리뷰: [2026-03-11_gold_data_codex_review.md](../../docs/lab_meetings/2026-03-11_gold_data_codex_review.md)
