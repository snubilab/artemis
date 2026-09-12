# Handoff — 여덟 개를 고치고 병목이 옮겨갔다 — 2026-09-12

## Goal / context

자연어 적격기준이 CIRCE JSON으로 **제대로** 변환되는지, 논리 결함이 없는지가 이 프로젝트의 질문이다.
이번 세션은 결함의 뿌리 다섯 개를 찾아 여덟 개를 고치고, 냉간 재추출 한 번으로 그것들을 **처음으로
실제 납품 파일에 반영**했다. 결과: 구조는 명확히 좋아졌고 납품 게이트는 0/12 그대로다. 병목이
해소된 게 아니라 **옮겨갔다.**

## Current state

- Branch: `fix/tte-a-drug-anchored-entry` · HEAD: `d50bf8c` · Open PR: 없음 (`gh` 미사용/원격 PR 없음)
- Uncommitted: 없음 (artemis clean)
- 위키 저장소 `/home/bilab/work/projects/Broadsea`: branch `docs/note-014` · HEAD `e6c7412` · clean
- 서버/빌드: 상시 프로세스 없음. vLLM은 `http://100.66.233.6:8000` 에서 응답 (이 세션에서 띄운 게 아니라 이미 떠 있던 것)
- 이번 실행 산출물: `output/site_gap/2026-09-15/` — `PROVENANCE.md`, `reingest.log`, `store/studies.json`,
  `DELIVERY/`(12개 팔별 CIRCE), `circe_per_study/`, `export_arms.log`, `gate.log`

## Done this session

여덟 개 수정 (커밋 순서 역순):

- PDF 위첨자 재결합 + 블록을 문서 순서로 병합 (`e8daa37`)
- 중첩 그룹과 `AT_LEAST` 개수 조건이 표현식까지 관통 (`c0df6db`)
- 플래너가 "형제가 곧 예외 항목"일 때 기준을 통째로 유지 (`d0ee924`)
- `"X other than Y"` 를 `isExcluded` 멤버로 방출 (`c75085c`)
- 추출 전 알파벳 정렬 제거 — 실제 코드 한 줄 (`a2fb858`)
- UCUM 단위 보강 + 1000배 쌍 import-time 가드 (`141ecb7`)
- 시간창을 원문 줄에 접지 (`a2ecba6`)
- 퓨샷 예시가 평가 코퍼스를 인용하지 않도록 전면 교체 + 재발 게이트 (`623e663`)

게이트 2개 추가: 단위 없는 값 경계를 Measurement에서 (`5d4dc1d`), Observation까지 (`606c686`).
정리 1건: 발동 0회짜리 표현-선호 장치 제거 + 실제 모듈을 mock으로 덮던 테스트 수정 (`646dbf8`).
실험 하네스 커밋 (`d50bf8c`).

## Key decisions & why — 후임이 다시 논쟁하지 말 것

- **정렬 제거가 핵심이었다.** `_normalize_trial_data_for_stable_hash` 안의 `sorted()` 한 줄이
  "다음 중 하나:" 제목과 그 항목들을 갈라놓고 있었다. 중복 제거는 `seen` 집합이 하므로 정렬은
  그 목적에도 불필요했다. 정규화를 **옮기지 말 것** — 프롬프트 생성 이후로 옮기면 캐시 키에
  닿지 못해 공백/NBSP 안정성을 잃는다. 삭제가 정답이다.
- **`_prefer_wording` 은 측정으로 제거했다.** 코퍼스 전체 발동 0회, 재배열이 순수 치환이라
  (`set(before) == set(after)`) 살릴 표현이 없고, 자기가 해를 안 끼치도록 자기 가드가 필요했다.
  되살리지 말 것 — 제거 전후 순서 이탈 수가 동일함이 확인됐다.
- **LEADER `isExcluded` 는 일부러 거부한다.** 26개 멤버 전부가 예외 집합에 들어 있어 빼면 집합이
  빈다. 빈 집합은 조건을 조용히 무력화하므로, 너무 넓은 채로 두고 린트에 계속 걸리게 하는 쪽이 낫다.
- **퓨샷 예시는 치환이 아니라 합성으로 바꿔야 한다.** `4aa1f08` 이 빌리루빈을 GGT로 바꿨는데 GGT도
  같은 코퍼스에 있었다. 지어낸 문장만이 구성상 코퍼스에 있을 수 없다.
- **퓨샷 제거는 성능 비용이 없었다.** DECLARE-TIMI 58 4팔 실험(반복 3회)에서 위약(공백 한 칸)이
  진짜 편집만큼 흔들었고, 예시를 전부 뺀 팔이 그 범위 안이었다. 오히려 뺀 쪽이 대안 4개를 그룹으로
  묶어 프롬프트 지시문을 따랐다. 기록: `docs/wiki/content/records/note-022.md` (Broadsea 저장소).

## 측정으로 확인된 결과

- **사전 선언한 반증 조건 통과.** 09-14 납품본에 있던 CARMELINA `Elevated Total Bilirubin`
  (`gte 1.5`, `referenceBound: uln`)이 사라졌다 — 빌리루빈 이름의 개념집합 0개, `1.5` 값 없음.
  `bilirubin`은 CARMELINA PDF 두 개 모두에서 0회 나온다. 단, 개념 하나(3024128)가
  `ALT [U/L] in Serum or Plasma` 집합 **안에** 잘못 남아 있다 — 날조가 아니라 매핑 결함.
- **LEADER 두 등록 코호트가 각각 ANY 그룹 하나가 됐다.** 위험인자 11개가 최상위 AND 조건에서
  그룹 멤버로. 그룹 이름이 정렬이 갈라놨던 바로 그 고아 제목이다.
- `contradictory presence/absence` 2 → 0, `conjoined disjunction` 2 → 0
- `isExcluded` 가 납품 파일에 처음 등장 (CAROLINA 5개, 이전엔 514집합 중 0개)
- 게이트 판정은 **0/12 그대로**

## Next steps (ordered, concrete)

1. **개념집합 매핑 품질 — 최우선.** 이름과 내용이 갈라지는 지점이 RAG 검색인지 재순위인지
   씨앗 선택인지 특정할 것. `src/agents/conceptset/` 경로를 실제로 타고 확인하고, 추측하지 말 것.
   두 실제 사례:
   - CAROLINA codeset 80 `cancer other than non-melanoma skin cancer` — 포함 13개가 병기 소견
     (`Tumor stage finding`, `Histological grade finding`, `Cancer confirmed` 등), 제외 4개가
     흑색종. 흑색종은 "NMSC 말고 다른 암"이므로 **제외하면 안 되는데** 제외돼 있다.
   - LEADER codesets **4 / 10 / 14** — liraglutide(40170911), lixisenatide(44506754) 포함.
     둘 다 GLP-1 수용체 작용제이지 인슐린이 아니다. codeset **13** `Use of GLP-1 receptor agonist
     or DPP-4 inhibitor` 에 있는 건 정상이므로 **대조군으로 쓸 것**.
2. **그룹 경계 전파.** LEADER treatment arm에서 `stranded-group-threshold` 로 거부된 기준 **9개**
   (`Myocardial Infarction`, `Stroke or TIA`, `Revascularization`, `Coronary Heart Disease`,
   `Cardiac Ischemia`, `Chronic heart failure`, `Microalbuminuria or proteinuria`,
   `Hypertension and left ventricular hypertrophy`, `Left ventricular systolic or diastolic dysfunction`).
   그룹 라벨이 코호트의 연령 경계(`>=50`, `>=60`)를 들고 있고 전파 가드가 멤버에게 물려주지 못해서다.
   **가드를 제거하지 말 것** — 경계를 잘못 물려주면 조용히 틀린 코호트가 나온다. 과제는
   "물려줄 수 있는 경계"와 "그룹만의 조건"을 구분하는 것이다. 연령은 후자다.
3. 남은 미해결 (우선순위 낮음): `src/utils/circe_lint.py` 의 그룹 라벨이 타입 결정 시점에 보이지
   않아 `AT_LEAST` 가 16개 중 9개만 잡힌다 (`c0df6db` 커밋 메시지에 상세).

## output/ 정리와 그때 드러난 구조 문제

2.4 GB → 1.8 GB, 상위 폴더 23개 → 9개. `output/_archive/{runs,logs}/` 로 모았고
참조 0인 `_cold*.json` 159 MB 는 `trash-put` 으로 버렸다 (복구 가능).

**분류할 때 주의할 것**: `rg` 로 경로 문자열을 세면 *읽고 쓰는 코드* 와 *이름만 언급하는
주석* 이 구별되지 않는다. 첫 분류에서 `placeholder_refusal`(315 MB)을 "코드 참조"로 보고
남겼는데, 실제로는 `src/services/tte_service.py:815` 의 주석 한 줄이었다. 같은 착각으로
`circe_arm_a/b`, `anchor_after`, `gold_vs_generated`, `circe_atc_fix` 도 남아 있었다.
실제로 쓰이는 것은 `classifier_probe`(`scripts/run_model_benchmark_queue.sh` 가 여기에 쓴다)
와 `e2e_leader_test`(`tests/test_e2e_pipeline.py:103`) 둘뿐이다.

**남은 1.3 GB 는 구조 문제이고 다음 세션의 리팩터 후보다.** `output/site_gap/<날짜>/` 가
*실행 기록* 이면서 동시에 *테스트 픽스처* 다. 테스트가 날짜 경로를 하드코딩한다 —
`2026-09-10` 18 곳, `2026-09-14` 17 곳, 주로
`tests/test_unit_bound_gates.py`, `tests/test_entity_subtraction.py`,
`tests/test_emission_drop_is_accounted_for.py`. 그래서 기록을 지울 수 없고 픽스처는 날짜에
묶인다. 실행이 쌓일수록 지울 수 없는 것이 쌓인다.

해법은 테스트가 실제로 읽는 조각만 `tests/fixtures/` 로 떼어내고 날짜 폴더를 자유롭게
만드는 것이다. 정리가 아니라 리팩터이므로 이번 세션에서는 하지 않았다.

**옮기지 못한 것**: `output/site_gap/` 안의 09-06 일회성 폴더 6 개
(`anchor_20260906_*`, `deliver_20260906b`)가 root 소유다. 컨테이너가 쓴 것이고 `sudo` 는
비밀번호가 걸려 있다. 직접 돌릴 때:
`sudo mv output/site_gap/anchor_20260906_* output/site_gap/deliver_20260906b output/site_gap/_archive_20260906/`

**발송 산출물**: `output/broadsea-circe-20260912.zip` (149 KB, CIRCE JSON 12 개).
`output/delivery/` 를 그대로 압축한 것이고, 그 폴더 규칙은 `AGENTS.md` § WHERE A DELIVERY
LIVES 에 고정했다 (`29d498d`).

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 인슐린 집합 세 개 (codeset 12는 Calcitonin이니 주의 — 번호는 실행마다 바뀐다)
.venv/bin/python -c "
import json;d=json.load(open('output/site_gap/2026-09-15/DELIVERY/leader_treatment.circe.json'))
print([(s['id'],s['name'][:44]) for s in d['ConceptSets'] if s['id'] in (4,10,13,14)])"

# 암 집합의 오제외
.venv/bin/python -c "
import json;d=json.load(open('output/site_gap/2026-09-15/DELIVERY/carolina_treatment.circe.json'))
s=[x for x in d['ConceptSets'] if x['id']==80][0]
[print(('EXCL ' if i.get('isExcluded') else '     ')+i['concept']['CONCEPT_NAME']) for i in s['expression']['items']]"

# 그룹 경계 거부 9건
rg -o "refused as 'stranded-group-threshold'" output/site_gap/2026-09-15/gate.log | wc -l

# 납품 게이트 재실행 (읽기 전용)
.venv/bin/python scripts/verify_circe_delivery.py \
  --dir output/site_gap/2026-09-15/DELIVERY \
  --store output/site_gap/2026-09-15/store/studies.json
```

재추출이 필요해지면 (프롬프트나 추출 경로를 다시 건드렸을 때만):

```bash
cd /home/bilab/work/projects/Broadsea/artemis
RUN="$PWD/output/site_gap/<새-날짜>"
mkdir -p "$RUN/store"
cp output/site_gap/2026-09-15/store/studies.json "$RUN/store/studies.json"
chmod u+w "$RUN/store/studies.json"
PYTHONPATH="$PWD" TTE_STORE_PATH="$RUN/store/studies.json" \
  nohup .venv/bin/python scripts/reingest_protocol_pdfs.py > "$RUN/reingest.log" 2>&1 &
echo $! > "$RUN/reingest.pid"
```

내보내기는 **`export_seeded_cohorts.py`** 를 쓴다 (`export_circe_from_store.py` 는 게이트가 읽지 않는
`*_circe.json` 형식을 낸다):

```bash
PYTHONPATH="$PWD" .venv/bin/python scripts/export_seeded_cohorts.py \
  --store "$RUN/store/studies.json" --out "$RUN/DELIVERY" \
  --study-id 3 --study-id 2 --study-id 10 --study-id 8 --study-id 9 --study-id 1 \
  --slug-map "3=aristotle,2=plato,10=carolina,8=empa-reg,9=carmelina,1=leader"
```

## Gotchas / constraints

- **`TTE_STORE_PATH` 는 셸에 unset이고 artemis-api 컨테이너는 라이브 스토어를 가리킨다.**
  라이브 `tmp/tte/studies.json` 은 08-13에 마지막으로 쓰였고 25.7 MB, 측정 기준
  `output/site_gap/2026-09-14/store/studies.json` 은 09-11에 85.3 MB. 라이브로 돌리면
  2026-08-31 납품 사고가 재현된다. 항상 측정 기준을 복사해서 씨앗으로 쓰고 출처를 기록할 것.
- **codeset 번호는 실행마다 바뀐다.** 09-14의 12번은 인슐린, 09-15의 12번은 Calcitonin이다.
  인용할 때 실행 디렉터리를 같이 적을 것.
- **`git stash` 를 이 체크아웃에서 쓰지 말 것.** 경로 없는 stash는 다른 에이전트의 미커밋 파일까지
  쓸어간다. 실제로 발생했고 복구했다. HEAD 비교는 `git show HEAD:<path>` 로 할 것.
  기존 stash 2개는 "둘 다 같이 복원" 쌍이다.
- **PDF는 `-layout` 없이 변환된다** (`src/agents/agent1/parser.py`). `-layout` 으로 재현한 진단은
  프로덕션에서 무효일 수 있다.
- **위임 브리핑은 `docs/agent-briefing-facts.md`** 를 가리킬 것. 이 세션에서 네 개 절이 추가됐다.
- **이 호스트의 모든 CDM은 합성이다.** 환자 수는 픽스처에 대한 사실이지 파이프라인에 대한 증거가 아니다.
- 이번 세션에서 **제 측정이 네 번 틀렸다** (깊이 histogram, CAROLINA 순서 이탈 수, codeset 번호,
  LEADER 누락 건수). 전부 에이전트가 "보고한 대로 안 맞추고 측정한 걸 보고"해서 잡혔다.
  브리핑에 숫자를 넣을 때 "이게 틀리면 측정한 걸 보고하라"를 같이 넣을 것.

## 관련 기록 (Broadsea 저장소, branch `docs/note-014`)

- `docs/wiki/content/records/note-022.md` — 퓨샷 오염: 발견·부분수정의 실패·게이트·4팔 실험
- `docs/wiki/content/records/note-023.md` — 이번 재추출과 납품 시도, 두 병목
- `docs/wiki/content/prompt-corpus-contamination.md` — 지속되는 함정 요약
- 메모리: `~/.claude/projects/-home-bilab-work-projects-Broadsea/memory/project_extraction_fidelity_2026-09-12.md`
