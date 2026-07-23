# ADR-029: Criterion Feasibility Gating (Defect D — infeasible eligibility rules)

**상태**: 제안됨 (Proposed) — 미구현
**날짜**: 2026-07-23
**의사결정자**: @kyh
**관련**: ADR-027/020 (comparator), Defect D 진단 (대시보드 gold_vs_generated)

## 컨텍스트

생성기는 트라이얼 자격기준의 **모든 문장을 필수 코드 규칙(inclusion rule)으로** 만든다. 일부 기준은 실세계 CDM에 사실상 없는 데이터를 요구해 **전원 탈락(0명)** 시킨다. 확인된 사례:

- EMPA-REG #11 «Dietary regimen / Exercise regimen» — 생활습관 Observation, 실 CDM에 거의 없음
- CARMELINA #9 «Albuminuria / UACR» — 요알부민/크레아티닌비 검사, 희소

원문 확인 결과 이 기준들은 **프로토콜에 실제로 존재**한다 (AI가 지어낸 게 아님). gold(사람)는 이런 것을 코호트 규칙에서 뺐다. 즉 **추출은 정확하나, "실세계 식별 가능성" 판단 계층이 빠진 것**이 D다.

경험 측정(Synthea, 11,771명): Dietary/Exercise regimen=0, UACR=0, Type 2 Diabetes≈819(7%). Albuminuria는 parent concept 단독 0이나 descendant 포함 시 1,661(14%).

## 결정

**타깃 CDM에서 각 기준의 데이터 유병률을 측정**해, 필수 inclusion인데 데이터가 0/희소인 규칙을 **사람에게 제외/완화 제안(HITL)**. 자동으로 IR을 바꾸지 않는다.

### 핵심 불변식
**"precomputed 유병률은 0을 후보로 증명할 수는 있어도, 충분함(적합)을 증명하지 못한다."** 따라서 precomputed(ACHILLES)는 **빠른 0-후보 선별**에만 쓰고, 최종 0 판정은 **직접 측정 카운트**로만 내린다.

### Polarity (부호) — 가장 중요한 교정
0% 유병률의 의미는 규칙 부호에 따라 **정반대**다:
- **필수 inclusion(PRESENCE)** 이 0% → 전원 탈락 → **DROP/RELAX 후보** (D가 잡으려는 실패)
- **배제(exclusion, "No X")** 가 0% → 아무도 배제 안 함 → **정상(BENIGN_KEEP)**, 절대 플래그 금지 (플래그하면 프로토콜이 배제하려던 환자를 몰래 재편입)
- **진입 이벤트(entry)** 가 0% → **하드 블로커** ("이 CDM엔 index 개념 없음 → 개념 remap 필요"), DROP 아님

### 측정 계층
1. **Tier-1 (ACHILLES, 빠른 선별)**: precomputed person-count(도메인별 person 분석 X00: 조건 400 / 약물 700 / 관찰 800 / 측정 1800 / 시술 600) 조회. **단독 presence 규칙의 feasible 확인** 또는 **hard-zero 후보 지명**에만 사용.
   - **small-cell 억제**: ACHILLES는 0 행을 안 쓰고 임계 미만을 억제 → **행 부재 = 0이 아니라 "미상 ≤ smallCell"**. 반드시 Tier-2로 확정.
   - **descendant 합은 상한값만**: includeDescendants set은 descendant 합으로 ">0 여부"만 (합 2,911 vs 실제 1,661 = ~75% 과대). 합=0은 진짜 0 증명, 합>0은 Tier-2 재측정. parent 단독은 0이어도 descendant는 있을 수 있으니 확장 필수.
2. **Tier-2 (직접 측정, 권위 있음)**: `COUNT(DISTINCT person_id)` + concept_ancestor 확장(+ value/unit, 시간창 predicate). **하드 0을 주장할 수 있는 유일한 계층.** 단일 set은 정확, 비싼 조인은 샘플링+오차한계.
3. **Joint oracle (진짜 0명 탐지)**: 개별 기준이 각각 >0이어도 **AND 결합에서 0**일 수 있다. 조립된 PRESENCE-inclusion 논리곱을 **한 번의 joint COUNT(DISTINCT person_id)** 로 측정. joint=0인데 marginal 모두 >0이면 **leave-one-out**으로 붕괴 규칙 지목. marginal만으로 "feasible" 단정 금지.

### 규칙 논리
ANY/ALL(group_type) 트리로 평가: ALL은 한 분기라도 hard-0이면 DROP 후보(0 분기 지목); ANY는 모든 분기가 ~0일 때만 infeasible. value/시간창 분기는 Tier-2로만.

### HITL
게이트는 **제안만** 한다. 각 제안: {규칙명, role(inclusion/exclusion/entry), polarity, evidence_tier, persons(정확/CI), evidence_state(정확한 0 / 억제·미상 / 희소 / feasible), action(DROP / RELAX / REMAP-entry / BENIGN-KEEP / BLOCKER)}. 사람이 항목/배치 승인. **부재 행·억제 가능 셀·descendant 합·미검증 테이블만을 근거로 한 DROP 제안 금지.** 승인 시 IR **복사본**에 적용·로깅.

## 스코프 (의도적 단순화)
- **ACHILLES 최신성 유지 = 각 병원(사이트)의 운영 책임.** 우리 시스템은 타깃 CDM에 있는 precomputed를 **그대로 조회**하고, 없거나 비어 있으면 Tier-2로 직접 측정. staleness 자동감지·재실행 machinery는 **범위 밖**.
- 단, 최소 안전장치: results 스키마/`achilles_results`가 비어 있으면 (전부 0으로 오판하지 않도록) Tier-2로 폴백.
- **CDM별 측정**: Synthea ≠ 아주대 ≠ 계명대. 캐시는 (CDM + 데이터버전 지문 + 개념셋/값/창 시그니처)로 키; 재적재 시 무효화.

## 근거
- gold이 손으로 뺀 판단을 **데이터가 대신 판정** → 에이전트 의견 의존 최소화
- precomputed lookup으로 **O(환자수) 스캔 → O(개념수) 조회** (Synthea 6개 199ms). 대형 CDM에서도 초 단위
- polarity·joint·small-cell 교정으로 **오탐(정상 배제규칙 삭제, 억제를 0으로 오인, 결합 붕괴 누락)** 방지

## 미해결 리스크 (구현 시 유의)
- 진입 이벤트 0 = 하드 블로커(remap), DROP 절대 불가 — 별도 경로
- small-cell 임계는 사이트별(Synthea 미억제 vs 병원 5~10) → 사이트마다 억제 프로브 필요
- 복합 검사(UACR=albumin+creatinine 성분)·단위 이질성(mg/g vs mg/mmol) → 성분/단위 정규화 없으면 오탐
- demographic·observation_period 기준은 concept 없음 → prevalence 게이팅 대상 아님(별도 predicate), 0으로 강제 금지
- leave-one-out은 규칙수 비례 비용 → 다규칙 코호트는 샘플 oracle로 상한

## 관련
- 대시보드 `artemis/output/gold_vs_generated/` — Defect D 진단·유병률 근거
- 프로젝트 규칙: 재적재 후 WebAPI generation-cache staleness 안티패턴 (동일 원리)
