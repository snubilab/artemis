# ADR-014: C2Q 3.0 기반 Agent 1 프롬프트 전략

**상태**: 승인됨
**날짜**: 2026-02-17
**의사결정자**: @kyh

## 컨텍스트
LEADER 임상시험 Attrition Analysis에서 TROY L2=512 vs ARTEMIS L2=0 분기가 발생.
근본 원인 분석 결과, Agent 1이 "HbA1c 7-10%" 범위 조건을 잘못 해석하여
PRESENCE(아무 HbA1c)로 출력. TROY 정의는 ABSENCE(HbA1c ≥10%)로 상한 체크.

- P0 코드 수정(시간 창 정규화)만으로 불충분 (v5b 진단 확인)
- Agent 1 프롬프트에 OMOP 도메인 지식과 범위 패턴 예시가 부재

## 결정
Criteria2Query 3.0 (Park et al, JAMIA 2024)의 프롬프트 설계 전략을 참고하여
Agent 1의 4개 프롬프트(SYSTEM/DECOMPOSITION × free-text/NCT)를 개선한다:

1. **OMOP 도메인 레퍼런스** — Measurement → value_as_number 매핑 정보
2. **Clinical Pattern 분류법** — 범위/임계/부정/이력 패턴 A-D
3. **One-shot 예시** — HbA1c 7-10% → PRESENCE(≥7%) + ABSENCE(≥10%)
4. **후처리 검증기** — Measurement 규칙에 value_constraint 누락 시 경고

## 근거
- C2Q 3.0은 OMOP 테이블 정의를 프롬프트에 포함하여 F1=0.891 달성
- OHDSI의 "범위 → PRESENCE+ABSENCE" 패턴은 Circe-be JSON의 관례이나, LLM이 자연어에서 이를 추론하기 어려움
- One-shot 예시가 가장 직접적인 in-context learning 수단

### 고려한 대안
1. **Fine-tuning**: OHDSI 코호트 정의 데이터셋으로 미세조정 — 데이터 부족 및 유지보수 비용으로 보류
2. **Multi-agent 검증**: 별도 검증 에이전트 추가 — 지연 시간 증가, 현 단계에서 과도
3. **규칙 기반 후처리**: Measurement → 자동 value_constraint 추가 — 범용성 부족

## 영향
- 수정 파일: `src/agents/agent1/prompts.py` (4개 프롬프트 전체), `src/agents/agent1/parser.py` (검증기)
- 프롬프트 토큰 증가: ~200 토큰 (비용 미미)

## 검증 결과 (2회 독립 LLM 호출)

입력: LEADER 임상시험 기반 자유 텍스트 (HbA1c 7-10%, eGFR ≥30, Age ≥50, T1D 제외, GLP-1 제외)

| 패턴 | Run 1 | Run 2 | 판정 |
|------|-------|-------|------|
| HbA1c ≥7% (PRESENCE, W: -180→0) | ✅ | ✅ | **2/2** |
| HbA1c ≥10% (ABSENCE, W: -180→0) | ✅ | ✅ | **2/2** |
| eGFR ≥30 (PRESENCE) | ✅ | ✅ | **2/2** |
| Age ≥50 (Demographics) | ✅ | ✅ | **2/2** |
| GLP-1 제외 (ABSENCE, W: -90→0) | ✅ | ✅ | **2/2** |
| T1D 제외 | ABSENCE | PRESENCE | ⚠️ |

### 도메인별 시간 창 기본값 (2/2 일관 적용)
- Measurement: `-180→0` (6개월 이내)
- Condition: `-9999→0` (전체 이력)
- Demographics: `-9999→0` (전체 이력)
- Drug: `-90→0` (명시적 기간 반영)

### 잔존 비결정성
- T1D 제외 규칙의 `logic_type`이 ABSENCE/PRESENCE 사이에서 비결정적
- 그러나 `exclusion_rules` 배열에 배치되므로 의미적으로 동일 ("이 조건이 있는 환자 제외")
- 후속 Agent 3 (Assembler)에서 `Occurrence.Type=0` (Exactly 0) 으로 변환되어 결과 동일

