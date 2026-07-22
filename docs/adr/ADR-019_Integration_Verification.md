# ADR-019: Integration Verification 필수화

**상태**: 승인됨  
**날짜**: 2026-03-03  
**의사결정자**: @kyh

## 컨텍스트

Agent 2 파이프라인에서 KG Expansion 관련 코드(`kg_expander.py`의 `expand()`, `ancestor_climb()`)가 **개발 완료 상태로 존재**했으나, `workflow.py`의 실제 실행 경로에서 **효과적으로 호출되지 않는** 상황이 장기간 지속됨.

- 함수 코드: ✅ 작성 완료
- 단위 기능: ✅ 개별 동작 확인
- Neo4j 데이터: ✅ 로딩 완료
- **파이프라인 통합**: ❌ 미연결 or 비효과적 동작

이 상태에서 벤치마크(Exp A/A'/B/C/D)가 수행되었으나, KG Expansion 없이 vector search + reranker만으로 동작 → **Avg Recall 41~52%에 정체**.

A_direct v2에서 파이프라인 재검토 후 실제 연결을 확인/수정한 결과, 동일 코드로 **+26.5pp recall 개선** 발생.

## 결정

**모든 기능 개발 완료 시 Integration Verification Checklist를 필수 실행**한다.

### 체크리스트
1. **호출 경로 확인**: 해당 함수가 메인 파이프라인에서 실제로 호출되는가?
2. **E2E 검증**: 입력→최종 출력에서 해당 기능이 반영된 결과를 확인했는가?
3. **Before/After 비교**: 기능 on/off 시 출력이 실제로 달라지는가?
4. **로그 확인**: 해당 기능의 로그가 실행 시 출력되는가?

## 근거

- "Dead Code Path" = 코드가 존재하지만 실행되지 않는 상태.
- 단위 테스트만으로는 파이프라인 통합을 보장할 수 없다.
- 26.5pp recall 손실은 **코드 부재가 아닌 통합 부재**에서 발생.
- 벤치마크 체계화가 문제를 발견한 유일한 수단이었음.

## 영향

- `.agent/rules/integration-verification.md` 생성
- 기능 개발 완료 시 daily note에 before/after 수치 기록 의무화
- "개발 완료"의 정의 변경: 코드 작성 + E2E 검증 완료 = 완료
