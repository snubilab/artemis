# Exp D vs M-GOLD Gap Analysis: GOLD 기준

> 🏷 명명 규칙: [EXPERIMENT_NAMING_CONVENTION.md](./EXPERIMENT_NAMING_CONVENTION.md) | 레거시 이름: `A_direct` → **M-GOLD**

> **날짜**: 2026-03-03  
> **M-GOLD**: R=75.0%, P=56.6%, F1=53.5% (ConceptSet name → Agent2)  
> **Exp D**: R=58.4%, P=28.3%, F1=32.9% (NCT+PDF → Agent1 → Agent2)  
> **Gap**: **ΔR=-16.6pp, ΔF1=-20.6pp**
>
> ⚠️ `No drug use`, `No pregnant`는 **원문(Supp. Appendix)에 없는 TROY 추가 항목**이므로 원문 기준 평가에서 제외.  
> 이들을 제외하면 Evaluated=15 기준으로 재계산 필요.

---

## 1. Per-Rule 비교

| GOLD Rule         | M-GOLD R | Exp D R |    Gap     | 원인 분류                                              |
| ----------------- | :------: | :-----: | :--------: | ------------------------------------------------------ |
| HbA1C ≥ 7%        |   100%   |  100%   |     0      | ✅ 동일                                                |
| prior CV disease  |   60%    |   40%   |   -20pp    | ⚠️ Agent1 분해: 11개 sub-rule로 scatter                |
| No T1DM           |   100%   |   24%   | **-76pp**  | 🔴 Polarity 손실 + 노이즈 매칭                         |
| No calcitonin     |   50%    |   50%   |     0      | ✅ 동일                                                |
| No GLP-1/DPP-4    |   100%   |  100%   |     0      | ✅ 동일                                                |
| No insulin        |   97%    |   97%   |     0      | ✅ 동일                                                |
| No acute decomp.  |   100%   | **0%**  | **-100pp** | 🔴 Agent1이 생성했으나 PRESENCE로 출력 → N:1 매칭 실패 |
| No acute coronary |   92%    |   46%   |   -46pp    | ⚠️ Agent1 분해 + N:1 매칭 분산                         |
| No CHF            |   100%   |   80%   |   -20pp    | ⚠️ Agent1이 NYHA II-III과 IV를 혼합                    |
| No renal replace. |   87%    |   58%   |   -29pp    | ⚠️ N:1 매칭 noise                                      |
| No eGFR <30       |   100%   |   21%   | **-79pp**  | 🔴 Agent1이 eGFR을 inclusion에 배치                    |
| No ESLD           |   31%    |   42%   |   +11pp    | ✅ 오히려 개선 (Agent1 텍스트가 더 넓음)               |
| No transplant     |   20%    |   21%   |    +1pp    | ✅ 동일 수준                                           |
| No malignant      |   100%   |   95%   |    -5pp    | ✅ 거의 동일                                           |
| No MEN2/FMTC      |   100%   |  100%   |     0      | ✅ 동일                                                |
| No drug use       |   100%   | **0%**  |     —      | ⬜ **평가 제외**: 원문 미명시 (TROY 추가 항목)         |
| No pregnant       |   100%   | **3%**  |     —      | ⬜ **평가 제외**: 원문 미명시 (TROY 추가 항목)         |

---

## 2. 원인 분류별 요약

### 🔴 Critical (ΔR ≥ 50pp) — 3건

| 원인               | 해당 Rule        |  Gap   | 설명                                                                                  |
| ------------------ | ---------------- | :----: | ------------------------------------------------------------------------------------- |
| **N:1 매칭 실패**  | No acute decomp. | -100pp | Agent1이 생성했으나 PRESENCE로 출력 → 매칭 알고리즘이 GOLD exclusion rule과 연결 못함 |
| **Polarity 손실**  | No T1DM          | -76pp  | Agent1이 ABSENCE로 출력해야 할 것을 잘못 의미 매칭 → N:1에서 wrong rule에 합산        |
| **eGFR 위치 오류** | No eGFR <30      | -79pp  | Agent1이 eGFR을 inclusion 측에 배치 → exclusion GOLD rule과 매칭 불가                 |

### ⬜ 평가 제외 — 2건

| 원인            | 해당 Rule                | 설명                                                                                   |
| --------------- | ------------------------ | -------------------------------------------------------------------------------------- |
| **원문 미명시** | No drug use, No pregnant | 원문(Supp. Appendix)에 없는 TROY 추가 항목 → 0%/3%는 **정상**. 원문 기준 평가에서 제외 |

### ⚠️ Moderate (10pp ≤ ΔR < 50pp) — 4건

| 원인          | 해당 Rule                            | 설명                                                                                     |
| ------------- | ------------------------------------ | ---------------------------------------------------------------------------------------- |
| **Rule 분산** | prior CV, acute coronary, CHF, renal | Agent1이 한 개 GOLD rule에 해당하는 내용을 여러 sub-rule로 분해 → N:1 매칭 시 noise 유입 |

---

## 3. Agent1 출력 분석

### 3.1 Polarity 문제

Agent1이 생성한 28개 rule 중 **26개가 PRESENCE**, 단 **2개만 ABSENCE**:

```
[ABSENCE] (Condition) Type 1 diabetes mellitus   ← 유일하게 올바른 ABSENCE
[PRESENCE] (Measurement) Calcitonin              ← ❌ ABSENCE여야 함
[PRESENCE] (Drug) GLP-1 receptor agonist...      ← ❌ ABSENCE여야 함
[PRESENCE] (Condition) Acute decompensation...   ← ❌ ABSENCE여야 함
...
```

원문 Exclusion criteria 15개 중 Agent1이 **ABSENCE로 표시한 것은 1개(T1DM)뿐**. 나머지 14개는 모두 PRESENCE로 잘못 출력.

> 💡 **polarity_penalty=1.0 (비활성화)** 이기 때문에 점수에 직접 영향 없지만, N:1 매칭에서 연결 실패의 원인.

### 3.2 문제 Rule 상세

| GOLD Rule                 | Agent1 출력                                               | 이유                                                                           |
| ------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------ |
| No acute decompensation   | `Acute decompensation of glycemic control` (**PRESENCE**) | ✅ 생성했으나 PRESENCE로 출력 → N:1 매칭 알고리즘이 GOLD exclusion과 연결 실패 |
| No drug use or dependence | **없음**                                                  | 원문에 없는 TROY 추가 항목 → 평가 제외 대상                                    |
| No pregnant               | **없음**                                                  | 원문에 없는 TROY 추가 항목 → 평가 제외 대상                                    |

---

## 4. 핵심 병목 순위

| 순위 | 병목                     | 영향                                                | 개선 방향                                         |
| :--: | ------------------------ | --------------------------------------------------- | ------------------------------------------------- |
|  1   | **Agent1 Polarity 손실** | Exclusion 14/15를 PRESENCE로 출력                   | Agent1 프롬프트에 Exclusion = ABSENCE 명시 강화   |
|  2   | **N:1 Matching 실패**    | acute decomp. 등 PRESENCE↔ABSENCE 매칭 불가         | Polarity-aware matching 또는 polarity 무시 매칭   |
|  3   | **Rule 분산**            | prior CV, acute coronary 등 여러 sub-rule로 scatter | Matching 알고리즘 개선 (semantic similarity 기반) |
|  4   | **Agent2 자체**          | ESLD/Transplant 여전히 저조                         | RFC-010 구현 (Reranker cross-branch)              |

> **참고**: `No drug use`, `No pregnant`는 원문에 없는 TROY 추가 항목이므로 0%/3%는 정상. 평가 제외 시 Evaluated=15.

> **결론**: M-GOLD(75%) → Exp D(58%) 하락의 핵심은 **Agent1 Polarity 손실 + N:1 매칭 알고리즘**. Agent2 자체는 동일 로직.
