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
