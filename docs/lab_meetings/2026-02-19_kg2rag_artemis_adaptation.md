# Lab Meeting: KG²RAG ARTEMIS 적용 방안

**날짜**: 2026-02-19
**참여 모델**: Claude, Gemini (gemini-2.5-pro), Codex (gpt-5.3-codex-spark)

## 안건
KG²RAG(Zhu et al., arXiv:2502.06864, 2025)의 핵심 기법을 ARTEMIS Agent 2의 KG-RAG 파이프라인에 적용할 수 있는지 검토하고, 구현 방향과 우선순위를 결정한다.

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | Context Organization만 채택 (트리 구조) | ARTEMIS chunk은 OMOP Concept → KG²RAG 대부분 기법 불적용 |
| Gemini | 2-Phase: Context Alignment + Smart Expansion Heuristics | descendant_count 기반 확장 제어, 공통 조상 활용 |
| Codex | 3-Tier: Context + Distance Cutoff + Fast Path Critic Skip | 토큰 절감 + 비용 최적화, 구조화된 dict 반환 |

## 교차 검증에서 발견된 문제점

### Claude 제안의 결함 (Gemini & Codex 지적)
- **트리 구조는 부적합**: OMOP 계층은 **DAG(Directed Acyclic Graph)**이지 트리가 아님. 하나의 concept이 여러 부모를 가질 수 있어서 트리로 강제 변환하면 정보 손실 발생
- **`KGConcept`에 parent ID 없음**: 현재 스키마에는 `relationship` 문자열만 있어서 true tree 구성에 추가 쿼리 필요
- **seed 출처 정보 손실**: 여러 seed가 있을 때 어떤 seed에서 확장된 concept인지 Critic에 전달되지 않음

### Gemini 제안의 결함 (Codex 지적)
- **`descendant_count > 10,000` 하드 임계값은 위험**: 임상적으로 중요한 하위 개념을 놓칠 수 있음
- **공통 조상 확장 루틴 미존재**: 현재 코드에 없으므로 추가 구현 필요
- **vocabulary별 휴리스틱 확장 부족**: RxNorm만 고려하고 LOINC, SNOMED 등 미제시

### Codex 제안의 결함 (Gemini 지적)
- **Fast Path Critic Skip은 위험**: `ADR-013`에서 이미 "고신뢰 매핑도 틀릴 수 있다"고 결론. Critic 우회 시 잘못된 concept이 무검증 통과할 위험
- **구조화된 dict 반환 시 기존 인터페이스 깨짐**: `List[KGConcept]`에서 dict로 변경하면 호출부 전체 리팩토링 필요

## 최종 합의

### ✅ 합의 사항 (3개 모델 동의)

1. **Grouped-by-Relationship Context Format 채택**
   - 트리가 아닌 **관계 유형별 그룹핑**으로 Critic에 전달
   - 형식:
   ```
   ### Seed Concepts (from Vector Search)
   - ID: 4099974 | Completed stroke | separation: 0

   ### Ancestors (Broader Terms)
   - ID: 381591 | Cerebrovascular disease | separation: 1 | descendants: 47

   ### Descendants (Specific Terms)
   - ID: 375557 | Cerebral embolism | separation: 1

   ### Siblings (Same Parent)
   - ID: 35609033 | Haemorrhagic stroke | separation: 1
   ```
   - **수정 파일**: `critic.py` (프롬프트 + candidate_text 생성 로직)

2. **Fast Path Critic Skip은 채택하지 않음**
   - 임상 안전성 우선. Critic은 모든 경로에서 유지
   - 비용 최적화는 candidate 수 줄이기로 달성

3. **Smart Expansion Heuristics는 Phase 2로 (soft cap만)**
   - 하드 임계값(10,000) 대신 **soft budget** 방식
   - 모든 seed에 최소 descendant 슬라이스 보장 후 추가분만 cap

### ⚠️ 부분 합의 사항

| 항목 | Claude/Gemini | Codex | 결론 |
|:---|:---|:---|:---|
| Seed 출처 추적 | 불필요 | provenance tag 추가 | **향후 검토** (현재 seed 수 적어 불필요) |

## 반대 의견 기록
- Codex: Fast Path Critic 스킵을 confidence-gated 옵션으로라도 두자 → **Gemini 반박**: ADR-013 근거로 기각

## 실행 계획
- [ ] **Phase 1**: `critic.py`의 candidate_text 생성 로직을 grouped-by-relationship 형식으로 변경
- [ ] **Phase 1**: Critic few-shot 예시를 새 형식에 맞게 갱신
- [ ] **Phase 2** (추후): `kg_expander.py`에 soft budget 기반 adaptive expansion 추가

## 부록: 원본 제안 및 리뷰
> 상세 내용은 `tmp/lab_meeting/20260219_kg2rag_artemis_adaptation/` 참조
