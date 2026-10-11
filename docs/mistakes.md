# 실수 노트

이 문서는 자체 검사를 통과했지만 실제로는 틀렸던 사례를 적는다. 다음에 같은 상황을
만나기 전에 참고한다. 각 항목은 적용한 규칙으로 끝난다.

## 2026-10-07 — EMPA-REG treatment의 T2DM 제외 결함이 자체 검사를 통과한 채 남아 있었다

- **날짜**: 2026-10-06(병원 회신 수신) ~ 2026-10-07(원인 확인).
- **상황**: 2026-09-23 발송 전, EMPA-REG `#15 'Endocrine disorder (excluding T2DM)'`가
  T2DM을 제외하지 않아 진입한 사람을 전부 배제하는(코호트 0명) 결함을 고치는 작업이었다. 그 수정(이하 수정 B)은 "배제
  규칙의 concept set이 entry 사건의 concept을 덮는 경우"를 찾는 검출기였다.
- **통과한 것**: `output/site_gap/2026-09-22_verify5/fix_reflection.txt`가 다음을
  보고했다.

  ```
  PASS            B entry-absence
                    control: baseline detector exit 1, repair would change ['empa-reg_comparator.circe.json']
                    applicable: repair fired 1 time(s) during export
  ```

  note-031은 이 0명 원인이 해결됐다고 적었다.
- **실제로 틀렸던 것**: EMPA-REG treatment는 2026-09-23 발송 뒤에도 아주대·동아대 두
  사이트 모두 0명이었다. 수정 B의 검출기는 comparator가 T2DM 진단으로 진입하는
  경우만 봤다. treatment는 empagliflozin으로 진입하므로 검출 대상이 아니었고, 진입
  이전 T2DM 기록으로 같은 사람을 배제하는 경로는 검출기의 범위 밖이었다.
  `empa-reg_treatment.circe.json`의 `cs29`에는 `isExcluded` 멤버가 없었다.
- **어떻게 발견했나**: 아주대·동아대가 2026-10-06에 보낸 Atlas inclusion report에서
  EMPA-REG treatment의 `#15` `% Satisfied`가 아주대 874명(14.84%), 동아대 786명(20.58%)으로
  09-12 발송분과 같은 값이었다. note-031의 발송 확인("isExcluded 멤버 12개")은 파일 전체의
  멤버 수를 센 것이라 파일 하나가 빠진 것을 구별하지 못했다.
- **사용자 요청 원문**: "word 파일 열어서 분석해놔."
- **고친 방법**: 커밋 `c588aa7`에서 `entity_exception.description_stated_exception`이
  설명문에 적힌 예외를 매퍼까지 전달하게 했고, `circe_lint` 검사 (t)를 추가해 같은
  테이블에서 ALL 경로로만 도달한 presence 집합의 closure가 absence 집합의 closure
  안에 있으면 FAIL하게 했다. 검사 (t)는 `deliveries/2026-09-23`에서
  `empa-reg_treatment`(#2 대 #15)만 FAIL한다.
- **규칙**: 수정을 그 수정 자신의 검출기로만 검증했다면, 원래 결함 설명이 가리키는
  파일마다 따로 확인한다. 파일을 가로지르는 합계는 파일 하나가 빠진 것을 가릴 수
  있다.

## 2026-10-09 — UMLS 재빌드 B를 단일 스레드 점검만 보고 띄웠다가 매핑 33건이 실패했다

- **날짜**: 2026-10-09.
- **상황**: UMLS 데이터를 넣은 재빌드 B를 실행하기 전, 몇 달 동안 실행된 적이 없는
  UMLS 경로를 점검했다.
- **통과한 것**: `expand_drug_class_via_umls`를 단일 스레드로 7개 계열에 순서대로 호출했고,
  MRREL 경로가 결과를 냈다("DPP-4 inhibitors → 5 ingredients" 등).
- **실제로 틀렸던 것**: 재빌드는 Agent 2 작업자 여러 개가 `UMLSSynonymExpander` 싱글턴을
  함께 쓴다. 이 클래스는 sqlite 연결 하나를 `check_same_thread=False`로 열고 잠금 없이
  공유했다. 재빌드 B에서 매핑 33건이 `InterfaceError: bad parameter or other API misuse`와
  `IndexError: tuple index out of range`로 실패했고, 52분짜리 실행 하나를 버렸다
  (`output/site_gap/2026-10-09_final_umls_race/INVALID.md`).
- **어떻게 발견했나**: 실행 뒤 로그의 Traceback 3건과 `agent2_seeded_mapping_failed` 33건.
- **사용자 요청 원문**: "짜식이 하기전에 그거부터 확인했어야지" (재빌드 B 실패 보고 뒤의 지적).
  재빌드 B는 사용자가 고른 "두 번에 나눠 비교 (권장)"의 두 번째 실행이었다.
- **왜 점검을 통과했나**: 점검을 실제 실행과 다른 동시성(단일 스레드)으로 돌렸다. 단일
  스레드 호출은 경로가 작동하는지는 보여 주지만, 공유 연결의 경합은 원리상 드러내지 못한다.
- **고친 방법**: 커밋 `abf04f4`에서 스레드마다 연결을 따로 열게 했고, 16개 스레드로 같은
  조회를 반복하는 테스트(`tests/test_umls_expander_threads.py`)가 고치기 전 코드에서 같은
  `InterfaceError`로 실패하는 것을 확인했다.
- **규칙**: 오래 실행되지 않던 경로를 켜는 긴 실행 전에는, 실제 실행과 같은 작업자 수로
  짧게 돌려 매핑 실패와 Traceback이 0건인지 먼저 본다.

## 2026-10-09 — 재빌드 A가 수정 대상 게이트를 모두 통과했는데 `Type 1 diabetes mellitus` 집합이 오염돼 있었다

- **날짜**: 2026-10-09 ~ 10-11.
- **상황**: 09-23 회신 수정을 모두 반영한 재빌드 A를 배송 게이트와 gold로 판정했다.
- **통과한 것**: 수정 대상 검사 (t)(u)(v)(w)가 6개 파일 모두 0건이었고, 예측 P1~P8이
  모두 맞았다.
- **실제로 틀렸던 것**: CARMELINA·CAROLINA의 `Type 1 diabetes mellitus` 배제 집합에 임신성·
  이차성 당뇨와 44793113이 들어갔다(gold precision 1.000→0.250). 44793113은 같은 파일의
  `Type 2 Diabetes Mellitus` 포함 집합에도 있어, 이 코드로 기록된 T2DM 환자가 포함되었다가
  배제된다.
- **어떻게 발견했나**: gold 기준별 대조에서 T1D 행의 precision 하락을 행 단위로 확인했다.
- **사용자 요청 원문**: 최종 재빌드 방식으로 사용자가 고른 "전부 재매핑 + 게이트로 걸러내기".
- **왜 점검을 통과했나**: 게이트의 어떤 검사도 이 모양을 보지 않았다. (t)는 포함 집합
  closure 전체가 배제 집합 안에 있을 때만, (x)는 배제가 대상 전체를 금지할 때만 FAIL하고,
  entry-exclusion 검사는 진입 약물만 본다. 예측 목록에도 T1D 행이 없었다. "재매핑하고
  게이트로 거른다"는 방침은 게이트가 잡지 못하는 모양을 그대로 내보낸다.
- **고친 방법**: 검사 (y)(커밋 `b8250cc`, 필수 포함 집합의 명시 항목이 배제 집합 closure
  안에 있으면 FAIL)를 재빌드 A의 실제 CARMELINA 파일로 실패를 먼저 보이고 추가했다. 원인
  쪽은 KG 후보 범위 필터(`bf40e5b`, `01ba254`)와 critic 시드 이름 표시(`7167bda`)로 고쳤다.
  통합 재빌드 2(`993d638`)에서 T1D precision 1.000, T2DM 0.88을 확인했다.
- **규칙**: 재매핑한 결과는 게이트 결과만이 아니라 gold 기준별 행을 하나씩 읽어 판정하고,
  행이 떨어지면 그 모양을 잡는 게이트가 있는지부터 확인한다.
