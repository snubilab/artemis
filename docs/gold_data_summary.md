# Gold Standard 데이터 구축 보고

**날짜**: 2026-03-11  
**목적**: 3개 임상시험 Gold 데이터 구축 현황 및 교수님 점검

---

## 1. 총괄

| 항목            |       **LEADER**       |         **EMPA-REG**         |          **PLATO**           |        **ARISTOTLE**         |
| --------------- | :--------------------: | :--------------------------: | :--------------------------: | :--------------------------: |
| Trial ID        |      NCT01179048       |         NCT01131676          |         NCT00391872          |         NCT00412984          |
| 치료 약물       |      Liraglutide       |        Empagliflozin         |          Ticagrelor          |           Apixaban           |
| 대조군          |  Placebo (DPP-4 arm)   |     Placebo (DPP-4 arm)      |         Clopidogrel          |           Warfarin           |
| 질환            |     T2DM + CV risk     |        T2DM + CV risk        |             ACS              |       Non-valvular AF        |
| ConceptSets     |           56           |              53              |              24              |              33              |
| Unique Concepts |          241           |             254              |             115              |             136              |
| Inclusion Rules |           18           |              14              |              5               |              15              |
| 구축 기반       | TROY v1.1 + v3.4 merge | TROY v3.4 + v1.1 cherry-pick | TROY v3.4 + v1.1 cherry-pick | TROY v3.4 + v1.1 cherry-pick |

---

## 2. 연구별 상세

### 2.1 LEADER

> Zinman et al., NEJMoa1603827

| 항목                   | 내용                                                                   |
| ---------------------- | ---------------------------------------------------------------------- |
| 약물                   | Liraglutide (GLP-1 RA) vs Placebo                                      |
| Rules                  | 18 (Inc 4 + Exc 14)                                                    |
| ConceptSets / Concepts | 56 / 241                                                               |
| 구축 방법              | v1.1의 age-stratified inclusion 구조 + v3.4의 condition 커버리지 merge |

**특이사항**:

- v3.4 HbA1c 임계값 원본 버그 발견 → GOLD에서 수정 (Value=10→7, Op=gte→lt)
- E-7 (Planned revascularization) v1.1/v3.4 양쪽 모두 미구현
- Substance abuse, Pregnancy는 원문 프로토콜에 없으나 TROY 추가
- 고아 CS 14개, 중복 CS 3쌍 (LVH, LVD, Revascularization)

---

### 2.2 EMPA-REG

> Zinman et al., NEJMoa1504720

| 항목                   | 내용                                           |
| ---------------------- | ---------------------------------------------- |
| 약물                   | Empagliflozin (SGLT2i) vs Placebo              |
| Rules                  | 14 (Inc 4 + Exc 10)                            |
| ConceptSets / Concepts | 53 / 254                                       |
| 구축 방법              | v3.4 기반 + v1.1의 HbA1c CPT4 코드 cherry-pick |

**특이사항**:

- Comparator arm(DPP-4)을 별도 JSON으로 분리 관리
- Orphan CS 4개 제거, cardiac surgery(CS 93)는 유지
- Drug class 규칙 비중 높음 (anti-obesity, systemic steroids 등)

---

### 2.3 PLATO

> Wallentin et al., NEJMoa0904327

| 항목                   | 내용                                            |
| ---------------------- | ----------------------------------------------- |
| 약물                   | Ticagrelor (P2Y12 inhibitor) vs Clopidogrel     |
| Rules                  | 5 (Inc 1 + Exc 4)                               |
| ConceptSets / Concepts | 24 / 115                                        |
| 구축 방법              | v3.4 기반 + v1.1의 DM/CrCl concepts cherry-pick |

**특이사항**:

- 가장 단순한 구조 (ACS treatment trial, 5 rules)
- Drug class 비중 극히 높음 (5 rules 중 4개가 약물 관련)
- CYP 3A4 inhibitor/inducer 목록(12종)은 TROY 큐레이터 임상 판단 기반
- 미구현 criteria 3개: Clopidogrel contraindication, Bradycardia risk, Liver disease

---

## 3. 공통 이슈

| #   | 이슈                     | 심각도 | 설명                                         |
| --- | ------------------------ | :----: | -------------------------------------------- |
| 1   | 독립 검증 부재           |   🔴   | TROY 기반 cherry-pick, 외부 전문가 리뷰 없음 |
| 2   | Protocol 미구현 criteria |   🟡   | LEADER 1개, PLATO 3개 누락                   |
| 3   | Protocol 외 추가 기준    |   🟡   | LEADER의 substance abuse, pregnancy          |
| 4   | Orphan/중복 CS           |   🟢   | LEADER 고아 14개, 중복 3쌍                   |

> 상세 이슈 분석: [gold_data_issues_report.md](./gold_data_issues_report.md)
