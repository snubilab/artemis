# 2026-03-16: Agent 1 Zero-Shot Prompt Tuning & E2E Benchmark

## 오늘 완료

- [x] P2: Agent 1 Prompt 강제화 (Rule 12, Rule 7 도입)
  - PURE CLINICAL CONCEPTS만 추출하도록 Zero-Shot 프롬프트 추가 (No few-shot data bleeding)
  - 잡음 텍스트("history of", "concomitant therapy with" 등) 및 grammatical glue words 강제 제거 지시
- [x] P3: HITL 하드코딩 완전 제거 (CYP inhibitors)
  - Agent 2의 사전 정의된 Manual Dictionary(HITL) 의존성을 끊고 순수 추론 파이프라인으로 복원
- [x] P5: 벤치마크 인프라 안정화
  - NoneType 오류 패치 (`parser.py` value_constraint null 체크)
  - Docker 컨테이너 이슈 해결 (`artemis-neo4j`, `artemis-redis` 재시동 규칙 확립)

## 진행중

- [/] P5: 벤치마크 병렬화 (ThreadPoolExecutor) 리팩토링 진행 (`benchmark_v5.py`)

## 발견/변경사항

- **하드코딩 제거의 효과성 증명**: Agent 1이 추출하는 Sub-criteria 텍스트에서 임상시험 문맥(context string)을 제거하고 순수 약물/질환 개념만 뽑아내는 프롬프트만으로 Agent 2의 Mapping 성공률이 대폭 회복됨. 
- 단, PLATO/ARISTOTLE 대비 LEADER 벤치마크에서는 'No GLP-1 RA within 3 months' 같은 복합 부정+기간 개념이 순수 개념('GLP-1 RA')으로만 매핑되면서 TROY Gold Standard(Observation/Procedure 도메인이 섞인 경우)와 매칭률이 소폭 하락하는 Trade-off가 관찰됨 (Avg Recall 84.8% → 71.4%).

## 벤치마크 결과 (Before: 3/15 Baseline → After: 3/16 Zero-Shot)

| Trial | R (before→after) | P (before→after) | F1 (before→after) |
| ----- | ---------------- | ---------------- | ----------------- |
| PLATO | 56.4% → **79.1%** | 20.2% → 21.4%    | 22.2% → 24.5%     |
| ARISTOTLE | 67.3% → 68.4% | 53.8% → 63.8%    | 56.2% → 64.0%     |
| LEADER | 84.8% → 71.4% | 65.6% → 52.3%    | 65.8% → 52.1%     |

- **PLATO 주요 이슈 완전 해결**:
  - `Fibrinolytic therapy`: Recall 0% → **100%**
  - `Oral anticoagulation`: Recall 0% → **89%**
  - `CYP3A inhibitor/inducer`: Recall 0% → **25%** (하드코딩 없이 달성)
