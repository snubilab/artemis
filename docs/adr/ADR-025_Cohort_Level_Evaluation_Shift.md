# ADR-025: Cohort-Level Evaluation Shift (Precision 튜닝 폐기)

**상태**: 승인됨  
**날짜**: 2026-03-16  
**의사결정자**: @kyh

## 컨텍스트

- 벤치마크 평가 과정에서 Agent 2의 **Precision**이 상대적으로 낮게 측정되는 현상(Avg ~52%)이 지속적으로 관찰됨.
- 이를 해결하기 위해 `includeDescendants` 정책 변경, Ancestor 1-hop 제한 등(P0 Precision 개선 전략) 세부적인 Concept ID 개수 맞추기에 노력과 시간을 집중함.
- 그러나 단일 Broad Ancestor(예: History of malignant neoplasm) 하나가 수천 개의 descendant를 끌고 오는 OMOP CDM 계층 구조(Hierarchy)의 특성상, "Flat Union 방식의 수학적 Precision/Recall 계산"은 큰 왜곡을 발생시킴.
- 결국 개별 Concept을 얼마나 많이(혹은 적게) 반환했느냐는 벤치마크상의 숫자에 불과하며, 실제 OHDSI 시스템(WebAPI)에 쿼리가 던져졌을 때 추출되는 **최종 환자 코호트(Cohort)의 결과물 조립(Assembler)**이 가장 중요하다는 근본적 한계를 재확인함.

## 결정

- 개별 Concept ID 개수를 카운팅하여 계산하는 **Precision 개선(P0) 튜닝 작업을 즉각 폐기(Drop)**한다.
- 시스템의 성공 여부를 측정하는 **진정한 Ground Truth 기준을 "최종 추출된 환자의 Jaccard Similarity(Cohort Overlap)"로 변경**한다.
- 평가지표 가중치를 Agent 2의 단일 매핑 성능에서, Agent 3가 생성한 Circe-be JSON 기반의 데이터베이스 실행 성능(E2E)으로 전환한다.

## 근거

1. **임상적 유용성 확보**: 실제 연구자가 원하는 것은 "정확한 Concept 목록"이 아니라 "정확한 환자 집단"임. 특정 계층의 상위 개념 하나만 잘 잡으면 하위 개념이 누락/과포함되더라도 코호트 추출 결과는 거의 동일할 수 있음.
2. **리소스 낭비 방지**: 무의미한 숫자를 맞추기 위한 로직 하드코딩이나 규칙별 예외 처리(Rule-specific policy)는 시스템의 일반화(Generalizability)를 훼손하고 유지보수 비용만 증가시킴.
3. **구조적 한계 극복**: TROY 기반의 Gold Standard 데이터 또한 완벽한 정답이 아닌 Best-effort 산출물이기 때문에, 거기에 오버피팅하는 것은 학술적으로나 실무적으로 올바른 방향이 아님.

## 영향

- **향후 개발 방향 스위칭**: 남은 정량 평가(Agent 2 Precision 개선) 노력을 즉시 중단하고, **Agent 3 (Assembler) 구현 및 실제 환자 데이터베이스(Synthea) 연동 파이프라인 구축**으로 최우선 순위가 변경됨.
- **평가 스크립트 재작성**: 향후 벤치마크는 두 개의 Circe JSON (Gold vs Agent)으로 각각 추출된 코호트의 환자 ID Set(교집합/합집합)을 비교하는 쿼리 실행 스크립트로 대체/보완되어야 함.
- 기존에 작성된 `implementation_plan.md`의 "P0 Precision Improvement Strategy" 내용은 본 결정으로 인해 실행 취소됨.
