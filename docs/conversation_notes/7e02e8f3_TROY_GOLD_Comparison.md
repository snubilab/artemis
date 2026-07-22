# 2026-03-03: TROY GOLD 비교 분석 & Agent2 파이프라인 디버깅

**날짜**: 2026-03-03  
**주제**: TROY cohort v1.1/v3.4/GOLD 비교, T1DM cross-branch 문제 발견  
**관련 파일**: `LEADER_GOLD_STANDARD.md`, `RFC-010_Reranker_Cross_Branch_Recall.md`

---

## 대화 흐름

### 1. TROY 비교 테이블 통합

- **질문**: v1.1, v3.4, GOLD의 Inclusion/Exclusion criteria를 하나의 테이블로 통합해줘
- **결과**: 섹션 2/3을 단일 통합 테이블로 병합
- **추가 요청**: 원문 (Supp. Appendix p.39)도 나란히 보고 싶다 → 별도 테이블로 분리
- **최종**: 2.1 마스터 테이블 = 원문 + v1.1 + v3.4 + GOLD + R/P/F1 + 비고 (10 컬럼)

### 2. "동일 (2)" 표기 명확화

- **질문**: "동일 (2)"가 뭔 뜻이냐
- **해결**: `2 concepts (MEN2+MTC), v1.1=v3.4 동일` 으로 구체화. 숫자가 concept 수임을 명시

### 3. 성능 `—` 표시 이유

- **질문**: T2DM, Age 등은 왜 성능이 없는가
- **설명**: PrimaryCriteria(entry event), DemographicCriteria(나이)는 ConceptSet 매핑 대상이 아님
- **조치**: 2.1 테이블 하단에 `[!NOTE]` callout으로 설명 추가

### 4. E-1 (No T1DM) 비고 설명

- **질문**: `v1.1: +uncontrolled, +disorder due to`가 뭔가
- **확인**: v1.1은 3 concepts (201254 + 40484648 + 435216), v3.4는 1 concept (201254)만
- **발견**: 435216은 `Complication due to DM` 계통 → 201254의 descendant가 아닌 **cross-branch**

### 5. OMOP 계층 확인 (synthea_cdm)

- **질문**: 우리 agent는 sibling을 어떻게 보는가
- **DB 확인**: `435216`은 201254의 descendant가 아님 확인 (synthea_cdm.concept_ancestor)
- **KG expander 코드 확인**: sibling은 `min_levels_of_separation=1` (같은 부모)만 → cross-branch 불가

### 6. 임베딩으로 해결 가능?

- **질문**: 임베딩 모델이 있으면 한번에 찾지 않나
- **확인**: `retriever.py`에 이미 ChromaDB + OMOP concept 벡터 검색 구현돼 있음
- **테스트**: "Type 1 diabetes mellitus" 검색 → **435216이 rank 6에 존재!**

### 7. Agent2 파이프라인 step-by-step 추적

- **질문**: 그러면 왜 최종 결과에서 빠지나
- **추적 결과**:
  ```
  Step 1 (Vector Search): 435216 → rank 6 ✅
  Step 2 (UMLS Expansion): 동의어 3개 추가, 435216 position 변화 없음
  Step 3 (Reranker LLM top-3): 435216 → ❌ 탈락
  ```
- **원인**: Reranker 프롬프트가 "best match the user's clinical intent" → LLM이 T1DM subtype(1A, 1B)만 선택하고 합병증 계통은 제외

### 8. Reranker 프롬프트 확인 & RFC 작성

- **질문**: Reranker 프롬프트가 어떻게 돼
- **확인**: `reranker.py`의 `rerank_topn` — "Select up to N OMOP concepts that best match"
- **RFC-010 작성**: top_n 증가, exclusion context 전달, 프롬프트 수정 3가지 방안 제시

---

## 핵심 결론

1. **OMOP 계층은 불완전**: `includeDescendants=true`만으로 cross-branch (sibling 계통) 커버 불가
2. **Vector Search는 이미 찾고 있음**: 문제는 retriever가 아닌 **Reranker LLM**
3. **Reranker 병목**: top-3 제한 + "best match" 프롬프트 → 관련 합병증 concept 필터링
4. **UMLS 확장은 무관**: 동의어 추가만 하고, cross-branch concept 발견에는 기여 없음

## 다음 단계

- [ ] RFC-010 검토 후 구현 우선순위 결정
- [ ] top_n=5로 변경 시 전체 benchmark 영향 측정
- [ ] 다른 rule (E-11 ESLD, E-12 transplant)에도 동일 패턴 있는지 확인

---

## 2026-03-03 (오후 세션) — Ablation Study & GOLD 최종 업데이트

### 9. Ablation Study: Force All Slow Path

- `FORCE_SLOW_PATH=1` 환경변수 추가 → `workflow.py`에 complexity router 우회 로직 삽입
- **결과**: Avg R=77.9%, P=44.8%, F1=48.2% — 기본(mixed path) 대비 오히려 하락
- T1DM은 84%로 급등했으나, 전체적으로 Reranker top-3이 fast path보다 불리한 경우 존재
- `ABLATION_STUDY.md` §2.7 추가, 누적 테이블 #6행 추가 (Precision 컬럼 포함)

### 10. GOLD JSON 파일 정리

- GOLD JSON → `data/gold/LEADER/` 폴더로 이동 (기존 `data/sample/LEADER/`에서 분리)
- `TROY_VERSION_COMPARISON.md` 헤더에 GOLD 경로 추가

### 11. 문서 리네이밍

- `TROY_VERSION_COMPARISON.md` → `LEADER_GOLD_STANDARD.md` (제목+파일명 모두)
- 제목: "LEADER GOLD Standard 구축: 원문 프로토콜 → TROY 버전 비교 → GOLD ConceptSet 확정"
- `MOC.md`, 대화노트 참조 링크 업데이트

### 12. GOLD 벤치마크 최종 결과 업데이트

- A_direct v3 (C) 세팅으로 GOLD reference 재실행 (benchmark_a_direct_20260303_2157.json)
- **최종**: Avg R=80.4%, P=50.4%, F1=50.2%, Full=12, Wrong=2
- 주요 변동: No T1DM 19%→100%, No malignant 68%→100%, prior CV 42%→60%
- §6.1/§6.2 모두 최신 수치로 동기화, 실험 설정 블록 추가

---

## 산출물

| 파일                                      | 변경 내용                                            |
| ----------------------------------------- | ---------------------------------------------------- |
| `LEADER_GOLD_STANDARD.md`                 | 2.1 마스터 테이블 완성 + §6.1/6.2 최신 결과 업데이트 |
| `RFC-010_Reranker_Cross_Branch_Recall.md` | 신규 생성 — Reranker cross-branch recall 개선 제안   |
| `ABLATION_STUDY.md`                       | §2.7 Force All Slow Path 추가, Precision 컬럼 추가   |
| `workflow.py`                             | FORCE_SLOW_PATH 환경변수 로직 추가                   |
| `MOC.md`                                  | 파일명 참조 업데이트                                 |
