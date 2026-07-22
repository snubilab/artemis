# Gold Standard 구축 체크리스트

**목적**: 이미지 Pivotal Trial 15종 Gold 데이터 구축 관리  
**기반**: LEADER/EMPA-REG/PLATO 구축 프로세스 (TROY v1.1 + v3.4 merge)

---

## 구축 완료

### ✅ LEADER (NCT01179048) — Liraglutide vs Placebo

- [x] TROY v1.1 / v3.4 수집
- [x] v1.1 + v3.4 merge (age-stratified inclusion 구조 + condition 커버리지)
- [x] HbA1c 임계값 원본 버그 수정 (Value=10→7, Op=gte→lt)
- [x] 고아 CS 14개 / 중복 CS 3쌍 정리
- [x] Target JSON (`LEADER_GOLD.json`) 최종 확정
- [x] 벤치마크 통합 (56 CS, 241 concepts, 18 rules)

### ✅ EMPA-REG OUTCOME (NCT01131676) — Empagliflozin vs Placebo

- [x] TROY v3.4 기반 + v1.1 HbA1c CPT4 코드 cherry-pick
- [x] Comparator arm (DPP-4) 분리 JSON
- [x] Orphan CS 4개 제거
- [x] Target/Comparator JSON 최종 확정
- [x] 벤치마크 통합 (53 CS, 254 concepts, 14 rules)

### ✅ PLATO (NCT00391872) — Ticagrelor vs Clopidogrel

- [x] TROY v3.4 기반 + v1.1 DM/CrCl concepts cherry-pick
- [x] CYP 3A4 inhibitor/inducer 목록 (12종) 확인
- [x] Target/Comparator JSON 최종 확정
- [x] 벤치마크 통합 (24 CS, 115 concepts, 5 rules)

---

## 미구축 — DPP-4 계열 (T2DM + CV risk)

### ⬜ DECLARE-TIMI 58 (NCT01730534) — Dapagliflozin vs Placebo

- [ ] 프로토콜 원문 수집 (Supplementary Appendix)
- [ ] TROY 소스 확인: `data/sample/DECLARE-TIMI/` (v1.1 + v3.4 존재 ✅)
- [ ] TROY v1.1 + v3.4 비교 분석
- [ ] Merge 전략 결정 (EMPA-REG과 유사한 T2DM+CV 구조 예상)
- [ ] Target JSON 구축 (`DECLARE-TIMI58_GOLD.json`)
- [ ] Comparator JSON 구축 (`DECLARE-TIMI58_GOLD_COMPARATOR.json`)
- [ ] ConceptSet 검증 (orphan/중복 정리)
- [ ] 벤치마크 등록

### ⬜ CANVAS (NCT01032629) — Canagliflozin vs Placebo

- [ ] 프로토콜 원문 수집
- [ ] TROY 소스 확인: `atlas_cohorts/` (v1.1 + v3.4 + v3.33 다수 ✅)
- [ ] TROY v1.1 + v3.4 비교 분석
- [ ] Merge 전략 결정
- [ ] Target JSON 구축 (`CANVAS_GOLD.json`)
- [ ] Comparator JSON 구축 (`CANVAS_GOLD_COMPARATOR.json`)
- [ ] ConceptSet 검증
- [ ] 벤치마크 등록

### ⬜ CARMELINA (NCT01897532) — Linagliptin vs Placebo

- [ ] 프로토콜 원문 수집
- [ ] TROY 소스 확인: `atlas_cohorts/1779097` (v3.4 ✅)
- [ ] Merge 전략 결정
- [ ] Target/Comparator JSON 구축
- [ ] ConceptSet 검증
- [ ] 벤치마크 등록

### ⬜ TECOS (NCT01174381) — Sitagliptin vs Placebo

- [ ] 프로토콜 원문 수집
- [ ] TROY 소스 확인: `atlas_cohorts/1779096` (✅)
- [ ] Merge 전략 결정
- [ ] Target/Comparator JSON 구축
- [ ] ConceptSet 검증
- [ ] 벤치마크 등록

### ⬜ SAVOR-TIMI 53 (NCT01107886) — Saxagliptin vs Placebo

- [ ] 프로토콜 원문 수집
- [ ] TROY 소스 확인: `atlas_cohorts/1779095` (✅)
- [ ] Merge 전략 결정
- [ ] Target/Comparator JSON 구축
- [ ] ConceptSet 검증
- [ ] 벤치마크 등록

### ⬜ CAROLINA (NCT01243424) — Linagliptin vs Glimepiride

- [ ] 프로토콜 원문 수집
- [ ] TROY 소스 확인: `atlas_cohorts/1779097` (CARMELINA 공유) + `1779098` (Glimepiride ✅)
- [ ] ⚠️ **유일한 active comparator trial** (Placebo 아님) — Comparator JSON 구조 주의
- [ ] Target/Comparator JSON 구축
- [ ] ConceptSet 검증
- [ ] 벤치마크 등록

---

## 미구축 — Antiplatelet 계열 (ACS)

### ⬜ TRITON-TIMI 38 (NCT00097591) — Prasugrel vs Clopidogrel

- [ ] 프로토콜 원문 수집
- [ ] TROY 소스 확인: `atlas_cohorts/1779074` (Prasugrel ✅), `1779071` (Clopidogrel ✅)
- [ ] ⚠️ PLATO와 유사한 구조 (ACS, active comparator) — 참고 가능
- [ ] Target/Comparator JSON 구축
- [ ] ConceptSet 검증
- [ ] 벤치마크 등록

---

## 미구축 — DOAC 계열 (Non-valvular AF)

### ⬜ ROCKET AF (NCT00403767) — Rivaroxaban vs Warfarin

- [ ] 프로토콜 원문 수집
- [ ] TROY 소스 확인: v3.33 + v3.4 다수 존재 ✅ (`1780793`, `1779154` 등)
- [ ] Merge 전략 결정
- [ ] Target/Comparator JSON 구축
- [ ] ConceptSet 검증
- [ ] 벤치마크 등록

### ✅ ARISTOTLE (NCT00412984) — Apixaban vs Warfarin

- [x] 프로토콜 원문 수집 (NEJMoa1107039 + protocol PDF)
- [x] TROY 소스 확인: v1.1 + v3.4 Target/Comparator 4개
- [x] Merge 전략: v3.4 base + v1.1 cherry-pick (DM +6, Bilirubin +1)
- [x] Target JSON: `ARISTOTLE_GOLD.json` (33 CS, 136 concepts)
- [x] Comparator JSON: `ARISTOTLE_GOLD_WARFARIN.json` (33 CS, 138 concepts)
- [x] ConceptSet 검증: orphan 0, 중복 0
- [ ] 벤치마크 등록

### ⬜ ENGAGE AF-TIMI 48 (NCT00781391) — Edoxaban vs Warfarin

- [ ] 프로토콜 원문 수집
- [ ] TROY 소스 확인: v3.33 + v3.4 존재 ✅ (`1779156`, `1779544`)
- [ ] Merge 전략 결정
- [ ] Target/Comparator JSON 구축
- [ ] ConceptSet 검증
- [ ] 벤치마크 등록

---

## 미구축 — JAK inhibitor 계열 (RA)

### ⬜ ORAL Surveillance (NCT02092467) — Tofacitinib vs TNFi

- [ ] 프로토콜 원문 수집
- [ ] TROY 소스 확인: `atlas_cohorts/1779099` (Tofacitinib ✅)
- [ ] ⚠️ **RA 적응증** — 기존 T2DM/ACS/AF와 다른 도메인
- [ ] Target/Comparator JSON 구축
- [ ] ConceptSet 검증
- [ ] 벤치마크 등록

### ⬜ STAR-RA (NCT04498286) — Tofacitinib vs TNFi

- [ ] 프로토콜 원문 수집
- [ ] TROY 소스 확인: ORAL과 공유 가능 여부 판단
- [ ] ⚠️ 최신 trial (2020~) — TROY 데이터 충분 여부 확인 필요
- [ ] Target/Comparator JSON 구축
- [ ] ConceptSet 검증
- [ ] 벤치마크 등록

---

## 구축 프로세스 (per trial)

```
1. 프로토콜 원문 수집 (ClinicalTrials.gov + Supplementary Appendix)
2. TROY v1.1 / v3.4 / v3.33 소스 비교
3. Merge 전략 결정 (어느 버전의 어떤 요소를 cherry-pick할지)
4. Target JSON 구축 + Comparator JSON 구축
5. 품질 검증:
   - Orphan CS 제거
   - 중복 CS 병합
   - INVALID_REASON / STANDARD_CONCEPT 검증
   - Protocol 미구현 criteria 문서화
6. 벤치마크 등록 (benchmark_v5.py에 추가)
```

## 진행 현황

| 질환 그룹          | 완료  | 미구축 |   총   |
| ------------------ | :---: | :----: | :----: |
| T2DM + CV (DPP-4)  |   2   |   4    |   6    |
| ACS (Antiplatelet) |   1   |   1    |   2    |
| AF (DOAC)          |   1   |   2    |   3    |
| RA (JAK inhibitor) |   0   |   2    |   2    |
| **합계**           | **4** | **9**  | **15** |

> ⚠️ CANVAS, CAROLINA은 `data/sample/` 폴더 미존재 — atlas_cohorts에서 직접 가져와야 함
