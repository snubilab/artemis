# ADR-030: Per-Site CDM Adaptation Layer (사이트별 CDM 적응 계층)

**상태**: 제안됨 (Proposed) — 아키텍처 정의
**날짜**: 2026-07-24 (개정: ACHILLES export 인터페이스 채택)
**의사결정자**: @kyh
**관련**: ADR-027(active comparator), ADR-028(comparator 문헌 우선 + CDM grounding), ADR-029(feasibility gating = 본 계층의 3단계), Defect A/B/C/D 진단

## 컨텍스트

TROY v1.1 코호트를 아주대·계명대 실 CDM에 적용하자 대부분 0-patient/왜곡이 나왔다. 결함 A/B/C/D를 개별 수정했지만, 근본 원인은 하나의 구조적 사실로 수렴한다:

> **하나의 코호트 정의를 "한 번 만들어 모든 병원에 그대로 배포"할 수 없다.** 각 사이트의 CDM은 서로 다르기 때문이다.

같은 질병·같은 의도라도 사이트마다 달라지는 축:

1. **Source vocabulary 매핑** — ICD-10 / KCD(한국) / 로컬코드 → OMOP standard concept 매핑이 ETL마다 다름.
2. **Granularity** — 한 사이트는 "Type 2 diabetes" 일반 개념으로, 다른 사이트는 세부 하위형으로 코딩.
3. **Domain routing** — 같은 임상 사실이 사이트 A는 Condition, B는 Observation(예: 흡연·비만).
4. **데이터 밀도(feasibility)** — 랩·생활습관·파생값(UACR, 식이/운동)이 사이트마다 있거나 없음(Defect D).

### 결정적 제약 (본 ADR을 개정하게 만든 사실)

**우리(프로토타입)는 아주대·계명대 CDM에 접근할 수 없다.**
- 우리 Synthea에서 feasibility를 세는 것은 **틀린 CDM을 세는 것**이다 (사이트마다 답이 다름).
- 실 병원 CDM에서 criterion마다 raw 스캔은 **느리다**(수백만 명 × 개념 수).
- 우리 코드를 병원 인프라에 배포·실행시키는 것은 **거버넌스 마찰이 크다**.

이미 우리는 이 문제의 **한 조각을 comparator에서 프로토타입**했다(ADR-028): "CV-neutral 대조군"이라는 **의도**를 문헌에서 뽑고 → **그 사이트 CDM에 실재하는 약으로 grounding**했다. 이 "의도 → 사이트 grounding" 패턴을 코호트 전체로 일반화하는 것이 본 ADR이다.

## 결정

### D1. WHAT/HOW 분리
**이식 가능한 임상 의도(WHAT)와 사이트별 개념 해석(HOW)을 분리한다.** 코호트를 concept ID로 박아 배포하지 않고, **의도를 담은 포터블 스펙**을 각 타깃 CDM에 **컴파일(adapt)**한다.

### D2. 사이트 인터페이스 = ACHILLES 집계 export (개정 핵심)

사이트에 우리 엔진을 설치·실행시키지 않는다. 대신 **표준 집계 파일 한 장을 받는다.**

```
사이트 → 우리:  <cdm>_results.achilles_results  (개념별 distinct person count)
우리 → 사이트:  사이트-튜닝된 Circe + 적응 리포트 (담당자 검토·승인)
```

| 항목 | 내용 |
|------|------|
| 파일 | `achilles_results` (analysis_id, stratum_1=concept_id, count_value=distinct persons) |
| 필요 analysis | 400(Condition) / 700(Drug) / 800(Observation) / 1800(Measurement) / 600(Procedure) / 200(Visit) |
| 성격 | 집계·비식별 (PHI 아님), 소규모 셀은 억제됨 |
| 크기 | Synthea 실측 1,212행 ≈ **19KB** → 대형 병원도 **~1MB** (환자 수가 아니라 **개념 종류 수**에 비례) |
| 가용성 | ATLAS/Broadsea 운영 사이트는 데이터소스 특성화 목적으로 **이미 보유**한 경우가 많음. 없으면 `Achilles::achilles()` 1회 실행 |

**근거**: 사이트 마찰 최소(파일 1장), CDM 접근 불필요, 우리 쪽에서 반복 실험 가능, OHDSI 표준 산출물이라 신뢰·재현 용이.

### D3. 2계층 측정 (ACHILLES의 한계를 명시적으로 보완)

ACHILLES 단독으로 **불가능한 것**이 있으므로 2계층으로 나눈다.

| 계층 | 수단 | 커버 | 한계 |
|------|------|------|------|
| **1차** | 사이트 ACHILLES export (우리 쪽 실행) | 단일 개념 유병률, 개념 해석/granularity 적응, 0-후보 지명 | small-cell 억제(행 부재=0 아님), marginal만, descendant 합=상한, value/시간창 없음 |
| **2차** | 사이트가 돌리는 **타깃 쿼리 소수** (선택) | joint 0-patient(A∧B∧C), value/시간창 조건, 하드 0 확정 | 사이트 실행 필요 → 1차에서 걸러진 소수 항목만 |

**불변식(ADR-029 계승)**: precomputed는 "0 후보"를 지명할 수 있어도 **충분함을 증명하지 못한다**. 하드 0 주장은 2차에서만.

### D4. 적응 컴파일러 5단계

```
포터블 스펙 (의도)                     사이트 적응 (ACHILLES export + vocab 기반)
────────────────                       ─────────────────────────────────────────
진입: "study drug X"            →  ① 개념 해석: 의도 → standard concept → 그 사이트에
포함/배제: 임상 의도들          →     실제 populated 된 개념으로 확장/축소     (Defect B)
결과: outcome 의도              →  ② 도메인·granularity 맞춤: 일반개념이 비고 하위형만
                                      있으면 하위형으로, 도메인 오배치 교정      (Defect B)
                                   ③ feasibility 게이팅: polarity-aware
                                      (필수포함 0%→DROP제안 / 배제 0%→KEEP /
                                       진입 0%→REMAP 블로커), joint는 2차       (Defect D=ADR-029)
                                   ④ grounding: 실재·feasible 개념만 유지. 대조군은
                                      문헌 의도 → 사이트 실재 약으로 grounding  (Defect C=ADR-028)
                                   ⑤ 리포트 + HITL: 적응 내역·근거·되돌리기 제시,
                                      담당자 승인 후에만 반영 (자동 적용 금지)
                                   → 사이트 튜닝된 Circe + 적응 로그
```

### D5. 기존 결함의 재정렬
- **Defect B**(개념 오매핑) = 단계 ①②
- **Defect C**(대조군) = 단계 ④의 특수 케이스(ADR-028)
- **Defect D**(feasibility) = 단계 ③(ADR-029)
- **Defect A**(진입 이벤트) = 적응 대상이 아니라 **포터블 스펙의 불변식**(drug-anchored new-user)

즉 B·C·D는 별개 기능이 아니라 **하나의 적응 레이어의 단계들**이다.

### D6. 검증 전략 — 가짜 병원 A/B/C

우리는 실 병원 CDM이 없으므로, **서로 다른 사이트 프로파일을 시뮬레이션**해 적응 로직을 검증한다.
Synthea 실측 `achilles_results`를 베이스로 **perturb**하여 동일 스키마의 export 3개를 만든다(진짜 concept ID·현실적 카운트 유지).

| | 병원 A (대학병원) | 병원 B (다른 vocab/granularity) | 병원 C (지역·희소) |
|---|---|---|---|
| T2DM 코딩 | 일반 개념 존재 | **하위형만 존재**, 일반개념 0 | 일반 개념 존재 |
| UACR/albuminuria | 존재 | 없음(0) | 없음(0) |
| 식이/운동 | 없음(0) | 없음(0) | 없음(0) |
| 당뇨약 커버리지 | 전 계열 | 일부 성분 없음 | metformin+SU 중심 |
| **검증 목표** | feasibility flag(EMPA #11) | **granularity 적응**(일반→하위형) | **grounding 축소**(대조군 후보 제한) |

기대 결과: 동일 스펙(예: EMPA-REG)을 3개 사이트에 컴파일하면 **서로 다른 튜닝 결과**가 나와야 한다(A는 flag 1건 + DPP-4i 대조군, B는 진입 개념 재해석 + UACR flag, C는 대조군이 SU 등으로 축소).
fixture는 진짜 병원 CSV와 **동일 스키마**이므로, 실제 데이터가 오면 그대로 대체 가능하다.

## 근거

- **OHDSI 네트워크 스터디 관행과 일치** — 코호트는 사이트마다 검증·적응되어야 이식된다.
- **사람이 하던 적응을 자동화** — gold 제작자가 손으로 하던 "사이트 코드에 맞게 개념 조정 + 코딩 불가 기준 제외"를 파이프라인화.
- **접근 불가·속도·거버넌스 문제 동시 해소** — 집계 파일 1장(≈1MB) 인터페이스.
- **의도 레벨 이식성** — concept ID를 박지 않으므로 새 사이트는 재컴파일만.

## 스코프 (의도적 단순화)

- 입력은 **사이트 ACHILLES export + OMOP vocabulary**. 환자 레코드·PHI는 다루지 않는다.
- ACHILLES staleness(최신성) 유지는 **사이트 운영 책임**. 우리는 받은 스냅샷의 기준일을 기록·표시만 한다.
- **CDM별 산출물**: Synthea ≠ 아주대 ≠ 계명대. 적응 결과·로그는 (사이트 + ACHILLES 기준일 + 개념/값/창 시그니처)로 키.
- HITL: 엔진은 **제안만** 한다. 자동 적용 금지.

## 미해결 리스크 (구현 시 유의)

- **의도 스펙(intent spec) 저작 부담** — 코호트를 concept ID가 아니라 의도로 쓰는 스키마가 필요 → 후속 ADR에서 정의.
- **small-cell 억제 오판** — 행 부재를 0으로 읽으면 정상 규칙을 DROP 제안할 수 있음. 사이트별 임계값을 회신받아 "미상(≤N)" 상태를 별도 표기해야 함.
- **descendant 롤업 과대** — `count_value`는 개념 정확 매칭(롤업 없음). includeDescendants 개념셋은 합산이 중복 카운트되어 상한값(예: albuminuria 합 2,911 vs 실제 1,661) → ">0 판정"에만 사용.
- **joint 붕괴 미탐지** — marginal이 모두 >0이어도 결합 시 0일 수 있음 → 2차 계층 필수.
- **개념 해석 LLM 신뢰도** — 단계 ①에 LLM이 개입하면 오판 가능(대조군 CV-neutral 판정이 흔들렸던 교훈, ADR-028) → vocab 검증 + HITL로 방어.
- **검증의 한계** — 가짜 병원 fixture는 우리가 만든 가정이므로, 실 사이트에서 새 실패모드가 나올 수 있음(HITL·적응 로그가 안전장치).

## 관련

- ADR-028 — 본 패턴의 최초 프로토타입(문헌 의도 → CDM grounding). 스냅샷 `data/comparator_literature/`.
- ADR-029 — 단계 ③(feasibility). polarity 판정 primitive는 `TTEService._concept_prevalence` / `_feasibility_verdict`(Synthea 검증 완료).
- `artemis/docs/site_data_request/ACHILLES_데이터_요청서.md` — 사이트에 보내는 데이터 요청 문서(D2 인터페이스의 실물).
- 대시보드 `artemis/output/gold_vs_generated/` — Defect A/B/C/D 진단, 실험노트 탭.
- 후속 ADR 후보: intent-level 코호트 스키마(적응 레이어의 입력 계약).
