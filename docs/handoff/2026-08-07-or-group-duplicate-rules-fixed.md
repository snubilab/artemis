# Handoff — OR 그룹 중복 규칙 수정 — 2026-08-07

> **[2026-08-09] 최신 문서는 `docs/handoff/2026-08-09-aristotle-zero-cohort-root-causes.md` 다.**
> 이 문서의 내용은 유효하지만 불완전하다 — ARISTOTLE 0명의 원인은 여기 적힌 것 말고도
> 세 개가 더 있고(개념집합 과확장, `procedure_occurrence` 공백, 규칙 17∧27 서로소),
> 최신 문서가 그것까지 담는다. 여기는 코드 변경과 2팔 실험의 **측정치 원본**으로 남긴다.

직전 핸드오프: `docs/handoff/2026-08-06-or-group-and-duplicate-rules.md`.
**그 문서의 "미해결" 절 진단은 틀렸다.** 아래 "정정된 진단"을 먼저 읽을 것.
그 문서의 "Gotchas / constraints" 절은 여전히 유효하다.

## Current state

- Branch: `fix/tte-a-drug-anchored-entry` · HEAD `4300eec` · **커밋 안 함, 워킹트리에 미스테이징**
- stash 2개는 **건드리지 말 것** — 2026-08-03 에 반증된 슬라이딩 창 변경. 이 세션에서
  `git stash` / `git checkout` 을 워킹트리에 쓰지 않았고 스택은 그대로다.
- 병원 전달 산출물(`output/circe_be/*.tar.gz`)은 **이 변경 전에 만들어진 것이고 재생성하지
  않았다.** 아래 "아직 안 한 것" 참조.

## 정정된 진단 — 원인은 파싱이 아니라 규칙 병합이었다

`2026-08-06` 문서는 `_collapse_hierarchical_groups` 가 자식을 소비하지 못한다고 적었다.
**재현되지 않는다.** 그 함수는 정상 작동한다: CT.gov 텍스트를 넣으면 OR 그룹 1개를 만들고
자식 4줄을 전부 소비하며, 뒤이은 `_regex_parse_criteria` 가 받는 잔여 텍스트는 빈 문자열이다.

그 문서가 본 "포함기준 7개"는 다른 경로에서 나왔다:

1. 접기가 **성공해서** 항목 수가 1로 줄었다.
2. 그래서 `_parse_criteria_items:469` 의 게이트 `len(regex_items) < 5 and len(text) > 200`
   이 발동했다 — 1 < 5, 400 > 200.
3. LLM 이 **원문(접기 전)** 을 다시 평평하게 6개로 파싱했다.
4. `_merge_parsed_items` 가 전부 덧붙였다. 합계 7.

접기가 잘 될수록 게이트가 더 잘 발동하는 역설이다. 결정적 단서는 출력의 대소문자였다 —
정규식은 `transient` 를 `Transient` 로 바꾸지 않는다.

**그런데 이것도 ARISTOTLE 0명의 원인이 아니었다.** 실제 원인은 그 다음 단계다.

### 진짜 원인

스토어(`tmp/tte_aristotle_orgroup/studies.json`, study id=3)의 규칙 구조를 보면
OR 그룹은 **정상 생성됐다** — `[14] Risk Factor OR Group` (groupType=ANY, 자식 5개).
문제는 같은 조항이 최상위 규칙으로 **또** 들어온 것이다:

```
[13] LVEF <= 40%              (ALL, 단독)  ← 자식 [17] CHF or LVEF <= 40% 의 중복
[20-22] Has TIA or SE         (ANY)        ← 자식 [16] Prior stroke, TIA or systemic embolus 의 중복
[3-5] Has Diabetes or Hypertension (ANY)   ← 자식 [18]/[19] 의 중복
[8],[9]                                    ← 설명이 글자 그대로 동일 (한 그룹 안 자기중복)
```

Circe 는 최상위 규칙을 AND 하므로 단독 `LVEF <= 40%` 하나만으로 코호트가 빈다.

중복이 들어온 곳은 **enricher** 다. 같은 "이게 중복인가" 판단이 네 곳에 각자 복제돼 있었고,
전부 전체 문자열 `SequenceMatcher` 라 포함 관계를 못 본다 — 66자 자식 vs 330자 그룹 줄은
길이 차만으로 모든 임계값 아래다.

| 위치 | 임계값 |
| --- | --- |
| `pubmed_fetcher._merge_parsed_items` | >= 0.7 이면 중복 |
| `enricher._merge_criteria` | >= 0.7 이면 중복 |
| `enricher._supplement_priority_merge` | < 0.5 이면 없는 것 (**ARISTOTLE 의 실제 경로**) |
| `enricher._pick_richer` | 개수 비교 |

실측(술어 무력화 vs 활성, 실제 ARISTOTLE 데이터):

```
                        items        AND-폭발 누수
supplement_priority   13 -> 9          4 -> 0
merge                 13 -> 9          4 -> 0
replace                8 -> 9          0 -> 0
```

누수 4건이 바로 코호트를 비운 그 네 개다.

## 착지한 변경 (커밋 안 됨)

### 새 파일

- `src/agents/agent1/criteria_dedup.py` — 중복 판단의 단일 권위.
  `restates_or_group_alternative(candidate, items)` + OR-GROUP 와이어 포맷 상수.
  내용어 커버리지 + 퍼지 토큰 + 두문자 규칙(`TIA` ↔ `transient ischemic attack`), 임계 0.70.
  안전성을 지탱하는 두 개의 조기 반환:
  1. **OR 그룹 후보는 절대 중복이 아니다** — 없으면 자식 5개짜리 PDF 그룹이 자식 4개짜리
     CT.gov 그룹에 0.722 로 걸려 **더 풍부한 쪽이 버려진다**.
  2. `items` 에 OR 그룹이 없으면 무조건 False — 평범한 기준 목록은 오늘과 완전히 동일하게
     동작한다. 이 스코핑이 코퍼스 전체 변경 폭을 4개 항목으로 묶는다.

### 수정

- `pubmed_fetcher._header_trigger` — `any of` 갈래에만 리스트 예고어를 요구
  (`the/these/those following|below|listed`, 또는 40자 이내 줄끝 콜론). 나머지 갈래는
  줄바꿈된 헤더도 잡도록 그대로 두되 관계대명사/소유격만 거부.
  실측: 진짜 그룹 15/15 유지, 오검출 1개(CAROLINA `"...to any of the components"`)만 제거.
  덤으로 현재 정규식이 **놓치던** 진짜 헤더 2개(`at least 1 of the following:`)를 잡는다.
- `_merge_parsed_items`, `_merge_criteria`(전방 + 역방향 스윕), `_supplement_priority_merge`,
  `_pick_richer` 네 곳 모두 공용 술어로 라우팅.
  `_merge_criteria` 는 역방향 스윕이 **필수** — 그쪽은 NCT 가 base 라 그룹이 중복보다
  나중에 도착해서 전방 루프가 못 본다.
- `_pick_richer` — 한쪽만 그룹을 가지면 고르지 말고 병합. 오늘 ARISTOTLE 여유는 +3 뿐이라
  (PDF 8 vs NCT 5) 그룹이 자식을 3개만 더 삼켰으면 통째로 버려졌다.

### 테스트 (신규 69개, 전부 통과)

| 파일 | 개수 | 역할 |
| --- | --- | --- |
| `tests/test_or_group_header_trigger.py` | 27 | 발동/비발동 라인 14+12 + CAROLINA 실제 형태 |
| `tests/test_criteria_dedup.py` | 22 | 술어 단위 — 중복 제거 / 필수기준 보존 / 근접 오답 |
| `tests/test_and_explosion_invariant.py` | 8 | **원래 실패를 잡았을 유일한 테스트** |
| `tests/test_dry_or_group_contract.py` | 7 | AST 하드 게이트 — 다섯 번째 복제 차단 |
| `tests/test_corpus_regression.py` | 7 | PDF 6종 inc/exc/ULN 계약 고정 |

- `tests/test_08_pubmed_fetcher.py` — 과금 차단 픽스처 추가. **기본 실행마다 실제 유료 호출
  3건이 새고 있었다** (`billed` 마커 누락). 그 출력은 어떤 단언에도 안 쓰여 순수 낭비였다.
  5.47s → 0.31s.
- `tests/test_parse_criteria_items.py::TestLeaderSupplementStyle::test_llm_items_are_merged_with_the_headers`
  → `test_llm_items_that_restate_group_alternatives_are_suppressed` 로 **의도적으로 반전**.
  기존 단언 `len(result) >= 12` 가 바로 제거 대상인 append-everything 동작이었다.
  양성 대조군을 넣어 "제대로 중복 제거됨"과 "폴백이 통째로 사라짐"을 구별할 수 있게 했다.

## 적대적 검토에서 나온 것 (렌즈 3개 → 발견 14건 → 독립 반증)

확정 1건, 과장 3건, 반증 10건. **뮤테이션으로 확인된 실제 구멍 2개는 이 세션에서 닫았다.**

### 닫은 것

1. **DRY 병합사이트 게이트가 주석으로 만족됐다.** 원래 구현은 `def` 사이 원문에 대한
   부분문자열 검사였고, `_merge_criteria` 에 이미 들어 있는 주석("...is_or_group
   candidates return False...")만으로 초록이 됐다. 실제 술어 호출 두 개를 지워도 통과했다.
   → `ast` 로 **실제 `Call` 노드**를 요구하도록 교체. 자기검증 테스트도 추가.
2. **`_pick_richer` 되돌림이 29개 테스트를 전부 통과했다.** AND-폭발 픽스처가
   PDF 8 > NCT 5 방향만 쓰는데, 그 방향에서는 수정 전 개수 비교도 우연히 맞는 답을 낸다.
   그룹 쪽이 더 **짧은** 케이스가 없어서 버려지는 분기가 아예 테스트되지 않았다.
   → `test_should_keep_the_group_when_the_flat_source_is_the_longer_one` 추가.

   두 게이트 모두 뮤턴트(사전수정 `_pick_richer` + 죽은 주석 언급)로 실패하는 것을 확인했다.
3. **와이어 포맷 게이트가 `[OR-GROUP]` 만 봤다.** `OR_GROUP_JOIN`(`" with any of: "`)은
   자유롭게 재타이핑 가능했는데 단언 메시지는 세 상수 모두 강제하는 것처럼 적혀 있었다.
   → JOIN 추가(오늘 `src/` 에 0회라 오탐 없음), 메시지 정정.
   `OR_GROUP_SEP`(`" | "`)은 `src/` 40개 파일에 정상 용도로 존재해 **어떤 부분문자열
   게이트도 소유할 수 없다.** 코드에 그 이유를 적어뒀다 — 다음 사람이 "고치려" 들지 않도록.

### 안 닫고 기록만 한 것

- **`_supplement_priority_merge` 에는 역방향 스윕이 없다** (`_merge_criteria` 와 비대칭).
  검증자가 500회 셔플로 확인: 실제 경로는 그룹이 base 에 통째로 들어가므로 **순서 무관하게
  안전**하다. 나쁜 방향을 만들려면 저장소에 없는 PDF 조합을 지어내야 했다. 비대칭은
  사고가 아니라 정당하다.
- **PLATO `3. One of the following:` 는 접히지 않는다** — `_header_trigger` 에 맨 `one of`
  갈래가 없다. 수정 **전후 출력이 바이트 동일**이라 이 변경이 만든 것도 보존한 것도 아니다.
  게다가 검증자가 확인: 순진하게 갈래를 추가하면 뒤따르는 임신검사 문단까지 대안으로
  삼켜서 CAROLINA 오검출과 같은 실패로 바뀐다. 그리고 PLATO 는 2단 조판 파편이 더 큰
  문제라 그룹을 접어도 쓸만한 정의가 안 나온다. 별도 과제.
- **`\beither\s+of` 갈래는 리스트 예고어를 요구하지 않는다.** 검토자가 실제 CT.gov 레코드
  (NCT06846541 `"Completed either of the two previous studies"`)로 오검출을 만들었지만,
  **도달 불가**다 — `extract_eligibility_from_text` 의 호출부는 PDF(`parser.py:489,493`)와
  PMC(`pmc_fetcher.py:223`, 이미 한 줄로 평탄화돼 접기가 불가능)뿐이고, CT.gov 텍스트는
  `nct_fetcher._parse_items` 로 간다. 실제 PDF 15개 전수: 그룹 획득 0 / 손실 0.
  (이건 "CT.gov 텍스트를 `pubmed_fetcher` 에 수동으로 넣어 측정"하는 함정의 세 번째
  사례다. 정찰·설계·검토 세 단계에서 모두 나왔다.)

## 검증 결과 (정적, 사용자 결정)

- **PDF 6종 계약 불변**: CAROLINA 20/24/1 · ARISTOTLE 8/21/1 · CARMELINA 3/16/1 ·
  EMPA-REG 0/15/1 · PLATO 18/12/1 · LEADER 17/14/0
- **파일별 기준선 불변**: 기존 9개 파일 465 passed / 0 failed → 동일
- **전체 스위트**: HEAD 210 failed / 1543 passed → 변경 후 210 failed / **1614** passed.
  실패 동일, 통과만 +71(신규 테스트 수).
- 전체 스위트 수집 오류 10건은 호스트 venv 의존성 누락(`pandas`×9, `langgraph`×1)이고
  `import pandas` 에서 죽으므로 이 변경과 무관하다.

## 2팔 실측 결과 (2026-08-07 야간 · GPU)

`scripts/verify_orgroup_dedup_two_arm.sh` 로 대조 실험을 돌렸다. 두 팔은 기준 목록 외
**모든 것이 같다** — 같은 모델(`vllm/google/gemma-4-E4B-it`), 같은 프롬프트, 같은 스토어
계보, 같은 소스(`ARISTOTLE_BENCHMARK`), 같은 스터디(3).
팔 전환은 `ARTEMIS_DISABLE_ORGROUP_DEDUP=1` — `criteria_dedup.py` 의 **명명된 ablation**
이고 기본값이 켜짐인 것을 `tests/test_criteria_dedup.py::TestAblationSwitch` 가 고정한다.

| | 팔 A (수정 전) | 팔 B (수정 후) |
| --- | --- | --- |
| 분해기 입력 기준 | 13 | **9** |
| 스토어 inclusion 규칙 | 23 | **11** |
| ANY 그룹 | 5 (중복 4개 포함) | **1** (`Risk Factor Composite`, 자식 5) |
| Circe InclusionRules | 31 | 31 |
| 0명 규칙 | **3** — ECG, LVEF, TIA+SE | **1** — ECG |
| 환자 수 | base 3,100 → final **0** | base 3,100 → final **0** |

팔 A 의 중복이 그대로 재현됐다 — `Has TIA or SE`, `Has Diabetes or Hypertension`,
단독 `LVEF <= 40%`, 단독 `Age >= 75 with previous stroke` 가 전부 최상위 AND 규칙으로 섰다.
팔 B 에는 넷 다 없다.

**두 생성 모두 캐시가 아니다.** `ohdsi-webapi` 로그에 각각
`Cache is absent for cohort id = 3402. Calculating with design hash = 2020650619` (팔 B) /
`= -1347131814` (팔 A). CLAUDE.md 가 경고하는 함정은 걸리지 않았다.

팔 A 는 IR 이 이미 캐시에 있어(`37238bec0812ee42`, 같은 모델) GPU 없이 재현됐다.
드라이버의 `Cache HIT → 중단` 게이트가 팔 A 에서도 발동했는데 **그건 게이트가 틀린 것**이다.
시험 대상 팔에서 HIT 은 "수정이 입력을 안 바꿨다"는 뜻이라 중단이 맞지만, 대조군에서 HIT 은
역사적 산출물을 공짜로 얻는 것이라 정상이다. 다음에 쓸 때 팔별로 분기할 것.

### 결론: 수정은 설계대로 동작하지만, 그것이 0명의 유일한 원인은 아니었다

원가설 "중복 규칙 제거가 코호트를 0에서 벗어나게 한다"는 **확인되지 않았다.**
ECG 규칙만 제거하고 재생성해 CDM 제약을 상수로 두면 원인이 분리된다:

| ECG 규칙 제거 후 | 팔 A | 팔 B |
| --- | --- | --- |
| 0명 규칙 | 2 (LVEF, TIA+SE) | **0** |
| 환자 수 | 0 | **0** |

팔 B 는 0명 규칙이 하나도 없는데도 코호트가 비었다. 개별 규칙은 각자 매칭되지만
**30개의 논리곱**을 만족하는 환자가 없다.

남은 두 블로커 (둘 다 이 수정 범위 밖):

1. **`procedure_occurrence` 가 전체 0행이다.** `synthea_cdm_aristotle` 에 환자는 21,000명인데
   시술 행이 하나도 없다. `ECG at enrollment` 는 Procedure 도메인(4144544 / 4145308 /
   4187078)이라 **어떤 정의로도 매칭될 수 없다.** `infra.md` 에 적힌 "사이트 CDM 은 CDM 5.4
   테이블이 비어 있다" 와 같은 부류다.
2. **규칙 28 이 3,100명 중 39명만 통과시킨다.** `Atrial Fibrillation or Flutter due to
   Thyroid Dysfunction + ...` — 가역적 원인 AF 가 0회일 것을 요구하는 부정 조건이고
   의미상으로는 맞다(`Occurrence Type 0, Count 0`). 그런데 통과가 39명뿐이다.
   창이 index 이전 9999일 + `IgnoreObservationPeriod: false` 라 관찰기간 부족을 의심했으나
   9999일 이상인 환자가 1,885명이라 그것만으로는 설명되지 않는다. **미해결.**
   다음으로 제한적인 것은 규칙 27(789명), 규칙 17 `Platelet count`(812명).

즉 ARISTOTLE 0명은 **중복 규칙 하나가 아니라 최소 세 가지가 겹친 결과**였고, 이 세션은
그중 하나를 제거하고 나머지 둘을 특정했다.

산출물: `/tmp/twoarm/` (드라이버 로그, `progress.jsonl`, 팔별 reingest/circe/cohort 로그),
스토어 `/app/tmp/tte_arm_{a,b}_*`, circe `/app/tmp/circe_{a,b}{,_noecg}`.

## 아직 안 한 것 / 다음 세션

1. **규칙 28 이 왜 39명인지** 밝힐 것. ECG 를 빼고 나면 이것이 최상위 블로커다.
   관찰기간 가설은 반증됐다(1,885명이 9999일 이상).
2. **`procedure_occurrence` 가 빈 것**을 벤치마크 CDM 생성 쪽에서 고칠지, 아니면 ECG 류
   기준을 이 CDM 에서 평가 불가로 표시할지 결정할 것.
3. **병원 산출물은 재생성 안 했다.** `output/circe_be/*` 는 이 수정 이전 코드의 결과다.
   넘길 거라면 재생성 여부를 결정해야 한다.
4. WebAPI 정의 3402 는 **팔 B(ECG 제거본)로 마지막에 덮였다.** 두 팔이 같은 정의 ID 를
   재사용하므로 공존하지 않는다. 비교를 다시 보려면 해당 circe 디렉터리로 재등록할 것.
3. **임계값 0.70 은 진짜 OR 그룹 딱 하나(ARISTOTLE)로 보정됐다.** 코퍼스 16개 그룹 중
   병합에 도달하는 건 그것뿐이다. 새 스터디에 진짜 포함 OR 그룹이 생기면 재보정이 필요하고,
   `test_corpus_regression.py` 에 스터디별 그룹/자식 개수를 핀으로 박아 두면 조용히 지나가는
   대신 실패한다.
4. **시간 창이 지워진다** — `prior`/`months`/`weeks`/`years` 가 불용어라
   `"Stroke or TIA <= 3 months prior"` 가 ARISTOTLE 그룹에 0.833 으로 걸린다.
   이 코퍼스에서는 도달 불가(둘 다 OR 그룹 없는 스터디의 배제기준이고 포함/배제는 따로
   병합된다). 불용어에서 빼는 건 측정해봤고 **더 나쁘다** — 진짜 양성이 0.750 → 0.600 으로
   떨어진다.
5. **`[OR-GROUP]` 마커를 해석하는 downstream 코드가 없다.** `src/` 어디에도 그 리터럴을
   읽는 곳이 없고, 마커는 분해 LLM 프롬프트로 그대로 흘러간다. `prompts.py:478`(Pattern E)은
   자연어 OR 표현으로 `group_type: "ANY"` 를 내라고 가르치지만 이 마커는 언급하지 않는다.
   즉 올바른 그룹핑이 모델이 `"with any of:"` 를 OR 로 읽어주는 우연에 달려 있다.
   프롬프트에 넘기기 전에 결정적으로 `groupType=ANY` 로 변환하는 게 더 견고하다. 미착수.
6. **CAROLINA 헤더 오검출은 오늘 프로덕션에 도달하지 않는다.** `_collapse_hierarchical_groups`
   호출부는 `_parse_criteria_items` 하나뿐이고, 실제 CT.gov 경로는 `nct_fetcher._parse_items`
   라 접기 자체가 없다. 잠재 결함 수정이고 순서상 먼저 간 건 맞다.
7. `2026-08-06` 문서의 나머지 미해결 항목은 그대로다 — 절 안내문이 기준으로 잡히는 것,
   원문 2)의 `OR` 가 AND 로 갈라지는 것, PLATO 2단 조판 파편화.

## 이 세션에서 새로 확인한 함정

- **전체 스위트 숫자는 회귀 신호가 아니다.** 이 저장소는 파일 간 간섭이 있어
  `test_09_enricher` 처럼 단독으로는 통과하는 파일이 전체 실행에서는 실패 목록에 오른다.
  HEAD 에서도 210 failed 다. **반드시 파일별 개별 프로세스로** 비교할 것.
- **`artemis/tmp/` 는 root 소유다.** 에이전트가 컨테이너로 만든 스크래치는 호스트 셸로
  못 지운다. `docker exec artemis-api python -c "import shutil; shutil.rmtree(...)"` 를 쓸 것.
- **`/app/tests` 는 마운트되지 않는다.** 이미지에 구워진 stale 디렉터리(`fixtures` 만)가
  있어서 `docker exec ... /app/tests/...` 가 조용히 엉뚱한 걸 실행할 수 있다.
  `pdftotext` 는 호스트에도 있으니 코퍼스 회귀는 호스트 pytest 로 돌린다.
- **`artemis-eval-baseline/` 과 `artemis-codex-fixes/`** 는 Broadsea 루트의 별도 체크아웃이고
  거의 동일한 파일을 담고 있다. codegraph/grep 이 자꾸 그쪽을 가리키니 주의.

## How to verify

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 신규 + 손댄 파일 (반드시 파일별 개별 프로세스)
for f in test_or_group_header_trigger test_criteria_dedup test_and_explosion_invariant \
         test_dry_or_group_contract test_corpus_regression test_parse_criteria_items \
         test_08_pubmed_fetcher test_09_enricher; do
  printf "%-32s %s\n" "$f" "$(.venv/bin/python -m pytest tests/$f.py -q --no-header -p no:randomly | tail -1)"
done

# 기존 기준선 9개 (465 passed / 0 failed 여야 정상)
for f in test_parse_criteria_items test_pdf_role_strategy test_08_pubmed_fetcher \
         test_09_enricher test_agent1 test_value_constraint \
         test_dose_form_route test_route_qualifier test_route_subtraction; do
  .venv/bin/python -m pytest tests/$f.py -q --no-header -p no:randomly | tail -1
done

# ARISTOTLE 중복 제거 효과 (술어 무력화 vs 활성)
.venv/bin/python -m pytest tests/test_and_explosion_invariant.py -q --no-header -p no:randomly
```
