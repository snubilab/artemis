# ADR-020: Supplement 존재 시 Main Paper PDF Enrichment 제외

**상태**: 승인됨  
**날짜**: 2026-03-04  
**의사결정자**: @kyh

## 컨텍스트

Agent1의 `parse_nct()`는 NCT JSON + 논문 PDF(main paper + appendix/supplement)에서 eligibility criteria를 추출하여 LLM에 전달한다.

LEADER trial (NCT01179048) 벤치마크에서 다음 문제가 발견되었다:

- **Main paper** (NEJMoa1603827.pdf): eligibility section 추출 실패 → 52,142 chars 전체 텍스트를 파싱 → 141개 noise exclusion 유입 (통계, 그래프, 저작권 문구 등)
- **Appendix** (nejmoa1603827_appendix.pdf): eligibility section 추출 성공 (2,295 chars) → 10개 깨끗한 exclusion criteria

결과적으로 LLM에 173개 criteria(90%+ noise)가 투입되어 19개로 압축하는 과정에서 "Acute decompensation of glycemic control" 등 실제 criteria가 누락되었다.

## 결정

**Supplement/appendix PDF가 존재하면 main paper PDF enrichment를 건너뛴다.**

- Appendix의 "Key Inclusion/Exclusion Criteria"가 complete하므로 main paper는 불필요
- main paper가 유일한 소스인 경우(supplement 미존재)에는 기존대로 main paper를 사용

## 근거

- Codex CLI 심층 분석에서 **대안 B + 조건부 A** 추천 확인
- 고려된 대안:
  - (A) Main 완전 제거: supplement 없는 trial에서 criteria 손실 위험 → 조건부로 채택
  - (B) Full-text fallback 제거: 근본 해결이지만 단독으로는 부족
  - (C) Pre-filter: 의료 텍스트 필터링 복잡성 높음 → 기각
  - (D) 수 제한/경고: noise 자체는 유입됨 → 기각
- **핵심 판단: Appendix가 complete criteria를 포함하므로, main paper는 noise만 추가할 뿐** (사용자 확인)

## 영향

- 수정 파일: `src/agents/agent1/parser.py` (L118-129)
- Agent1 LLM 캐시 hash 변경 → 새 IR 생성
- **결과 변화**: Agent1 출력 19 rules → 31 rules (173 input → 23 input으로 noise 제거 효과)
  - "Acute decompensation of glycemic control" 이제 생성됨
  - 단, 메트릭은 LLM 재호출로 구조 변동 발생 (별도 분석 필요)
