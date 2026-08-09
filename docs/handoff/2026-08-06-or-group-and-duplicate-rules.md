# Handoff — OR 그룹 복원과 중복 규칙 — 2026-08-06

> **[2026-08-07 정정] 아래 "미해결" 절의 진단은 틀렸다.**
> `_collapse_hierarchical_groups` 는 자식을 정상적으로 소비한다 — 재현되지 않는다.
> "포함기준 7개"는 접기가 **성공해서** 항목 수가 1로 줄었고, 그 때문에
> `_parse_criteria_items` 의 LLM 폴백 게이트(`< 5 items and > 200 chars`)가 발동해
> LLM 이 원문을 다시 평평하게 파싱한 결과다.
> 그리고 그것조차 ARISTOTLE 0명의 원인이 아니었다 — 실제 원인은 `enricher` 의
> 중복 판정(네 곳에 복제된 전체 문자열 유사도)이 포함 관계를 못 보는 것이다.
> **`docs/handoff/2026-08-09-aristotle-zero-cohort-root-causes.md` 를 읽고 계획할 것** (최신).
> 코드 변경과 2팔 실험의 측정치 원본은 `2026-08-07-or-group-duplicate-rules-fixed.md` 에 있다.
> 이 문서의 "Gotchas / constraints" 절은 여전히 유효하다.

## Goal / context

임상시험 프로토콜에서 뽑은 자격기준을 OMOP Circe 코호트 정의로 옮기는 일. 산출물은
**병원에 넘길 circe-be JSON 6종** 이고 이미 전달 가능한 상태다. 이 세션의 나머지는
"왜 코호트가 0명인가" 를 파고든 결과다.

직전 핸드오프: `docs/handoff/2026-08-03-value-constraint-six-studies.md` (값 제약 6개
스터디). 그 문서의 "확정된 사실" 절은 여전히 유효하니 먼저 읽을 것.

## Current state

- Branch: `fix/tte-a-drug-anchored-entry` · HEAD: `4300eec` · PR 없음 (push 안 함)
- 작업 트리 깨끗. 실행 중 프로세스 없음. GPU 비어 있음.
- stash 2개는 **건드리지 말 것** — 2026-08-03 에 반증된 슬라이딩 창 변경이다.
  `stash@{0}` 테스트 / `stash@{1}` 구현, 복원하려면 둘 다.
- 컨테이너: `artemis-api`, `broadsea-atlasdb`, `broadsea-hades`, `ohdsi-webapi` 등 가동 중.
  `broadsea-hades` 는 이 세션에서 `docker compose --profile hades up -d broadsea-hades` 로 띄웠다.

### 병원 전달 산출물 (완성, 검증됨)

- `output/circe_be/tte_circe_6studies_20260804.tar.gz` — README·manifest 포함
- `output/circe_be/tte_circe_6studies_json_only_20260804.tar.gz` — circe JSON 6개만 (77 KB)
- 개별 파일은 `output/circe_be/2026-08-03/` 에 있다. `output/` 은 gitignore 라 `-f` 로 추적 중.
- 재생성 가능 여부를 명령으로 검사할 수 있다 (아래 "How to verify" 1번).
- **이 산출물은 아래 미해결 결함을 안고 있다.** 개념 매핑은 정상이고 코호트를 좁게
  잡는 문제이므로 넘겨도 되지만, 병원이 0명을 볼 가능성이 있다.

## Done this session

- `08d2522` — 줄바꿈이 기호로 이어질 때 재결합 + 머리글을 분할 **전에** 제거.
  CARMELINA 간효소 기준이 `Liver enzyme elevation` 1건 → ALT/AST/ALP 3건이 됐다.
- `57d228b` — "매핑이 비결정적" 주장 철회. `LLM_TEMPERATURE=0.0`, `LLM_SEED=42`.
- `142ac36` / `e6f9285` — circe 산출물과 스토어 스냅샷을 git 에 넣음 (`output/` 은 gitignore).
- `e9c39ad` — `scripts/export_circe_from_store.py` (`--check` 로 재생성 가능성 검사).
- `7609014` — `a)`~`e)` 열거형 자식을 OR 그룹으로 묶음. ARISTOTLE 포함기준 13 → 8.
- `4300eec` — `protocol` 역할 PDF 도 `supplement_priority` 를 쓰도록. **효과 없었다, 아래 참조.**
- 아킬레스를 3개 사이트 CDM 에 돌림 (아주 529,359 / 동아 438,199 / 계명 401,329 행, 각 243분석).

## Key decisions & why

**병원 산출물은 `tte_six_deliver` 에서 뽑는다.** 계보:
`tte_six_fixed`(6개 재수집) → `tte_six_routed`(경로 뺄셈) → `tte_six_deliver`(CARMELINA 교체).
**CARMELINA 만 2026-08-04 코드**, 나머지 5개는 08-03 코드다. 파싱 수정이 다섯 곳의 기준
목록도 바꾸지만 ULN 개수는 불변이라 재수집하지 않았다. README 에 그 사실이 적혀 있다.

**매핑을 다시 돌리지 않고 경로 뺄셈만 적용했다** (`scripts/apply_route_subtraction_to_store.py`).
비결정성 때문이 **아니라** 변경 범위를 하나로 유지하려는 것이다 — 재매핑은 모든 기준의
개념 선택을 다시 뽑는다.

**`SYNTHEA_CDM_BENCHMARK` 로 평가하지 말 것.** 고정 벤치마크가 아니라
`evaluate_generated_gold_studies.py` 가 매번 갈아끼우는 작업 스키마다.

**벤치마크 CDM 들에는 약이 1~2종뿐이다** (`synthea_cdm_aristotle` 21,000명에 서로 다른
약물 2종). 경로 뺄셈은 이 데이터에서 환자 수를 못 바꾼다.

## 이 세션의 진단 — ARISTOTLE 0명의 진짜 원인

WebAPI 정의 **3402** (`ARTEMIS ARISTOTLE eligibility 2026-08-03`, 소스 `ARISTOTLE_BENCHMARK`)
로 생성한 결과: `base 3,100 → final 0`, 0명 규칙 3개.

```
[ 4] ECG at enrollment                   ← Synthea 데이터 없음
[ 5] Left ventricular ejection fraction   ← Synthea 데이터 없음
[26] TIA + Systemic Embolism              ← 중복 규칙
```

원문(`data/papers/NCT00412984/nejmoa1107039_protocol.pdf`)은 구조를 명시한다:

```
3) One or more of the following risk factor(s) for stroke:
   a) Age 75 years or older
   b) Prior stroke, TIA or systemic embolus
   c) Either symptomatic congestive heart failure ... or LVEF <= 40%
   d) Diabetes mellitus
   e) Hypertension requiring pharmacological treatment
```

gold(TROY)는 이걸 규칙 **1개**(`One or more of the following risk factor(s) for stroke:`)로
표현하고 1,113명을 얻는다. 우리는 다섯으로 흩어 AND 걸어 0명이 됐다.

`7609014` 로 OR 그룹은 복원됐다 — `Risk Factor OR Group`(Type=ANY, 자식 5개)이 생긴다.
**그런데 같은 조항이 다른 경로로 또 들어와 중복 규칙을 만든다.**

## 미해결 — 여기서 시작할 것

### CT.gov 자격기준이 한 조항을 7개로 부풀린다 (핵심)

`data/nct_cache/NCT00412984.json` 의
`protocolSection.eligibilityModule.eligibilityCriteria` 원문:

```
* Males and females >= 18 yrs with atrial fibrillation (AF) and one or more of the following risk factors for stroke:
* Age >= 75, previous stroke
* transient ischemic attack (TIA) or Systemic Embolism (SE)
* Symptomatic congestive heart failure or left ventricular dysfunction with LVEF <= 40%
* Diabetes mellitus or hypertension requiring pharmacological treatment
```

`extract_eligibility_from_text` 에 넣으면 **포함기준 7개**가 나온다:

```
[0] [OR-GROUP] Males and females ... one or more of the following   ← 묶인 것
[1] Males and females ... one or more of the following risk facto   ← 부모 줄이 또
[2] Age >= 75
[3] Previous stroke
[4] Transient ischemic attack (TIA) or Systemic Embolism (SE)       ← 자식이 또
[5] Symptomatic CHF or LVEF <= 40%                                  ← 〃
[6] Diabetes mellitus or hypertension requiring pharmacological ... ← 〃
```

**`_collapse_hierarchical_groups` 가 자식을 소비하지 못한다.** PDF 쪽(`a)` 열거)은
`7609014` 로 고쳤지만 CT.gov 쪽은 **부모와 자식이 둘 다 `*` 불릿**이라 다른 경로로 샌다.
부모 줄은 `_bullet_start` 정규화 후 `_header_trigger` 에 걸려 OR-GROUP 을 만들지만,
원본 줄이 그대로 남고 뒤이어 `_regex_parse_criteria` 가 `*` 불릿을 다시 쪼갠다.

`[4]`·`[5]`·`[6]` 이 Circe 의 `Has TIA or SE`, `LVEF <= 40%`, `Has Diabetes or Hypertension`
독립 규칙이 되고, Circe 는 규칙끼리 AND 이므로 OR 그룹의 효과를 상쇄한다.

### `4300eec` 는 이 문제를 못 고친다 — 이유

`protocol` 을 `supplement_priority` 로 바꿨지만 결과가 동일했다 (`5 -> 13 inclusion`,
그리고 **Cache HIT** — 입력이 바이트 단위로 같다는 뜻).

`_supplement_priority_merge` (`src/agents/agent1/enricher.py:105`) 는 `SequenceMatcher`
유사도 0.5 미만인 CT.gov 항목만 추가한다. 그런데 중복이 **텍스트 유사가 아니라 포함
관계**다 — `Diabetes mellitus` 한 줄과 200자짜리 OR-GROUP 줄은 길이 차 때문에 유사도가
낮게 나온다. 그래서 5개가 전부 "없는 것"으로 판정돼 추가된다.

즉 커밋 자체는 방향이 맞지만 (프로토콜이 등록부 요약보다 권위 있다), **중복 제거 수단이
약해서 효과가 없다.** 되돌릴 필요는 없다.

### 그 밖에 남은 것

- `For entry into the study, the following criteria MUST be met` 가 기준으로 잡힌다 (절 안내문).
- 원문 2)의 `OR` (심방세동 ECG 확인 **또는** 2회 문서화) 이 아직 AND 로 갈라져 있다.
  `a)~e)` 형식이 아니라 `OR` 한 단어가 줄로 서 있는 형태라 별도 패턴이 필요하다.
- PLATO 기준 파편화 — `plato_design_ahj2009.pdf` 의 2단 조판 `Table I` 을 pdftotext 가
  뒤섞는다. 파싱 수정 전 24개 / 후 18개, 둘 다 파편. ULN 기준은 온전.
- **`tte_aristotle_pdfonly` 스토어는 신뢰하지 말 것.** `4300eec` 검증 중 중단시킨 실행의
  산물이다. `tte_aristotle_orgroup` 이 `7609014` 의 온전한 산출물이다.

## Next steps (ordered, concrete)

1. **`_collapse_hierarchical_groups` 가 불릿 계층에서 자식을 소비하도록 고친다.**
   `src/agents/agent1/pubmed_fetcher.py:312`. 부모와 자식이 같은 불릿(`*`)일 때,
   부모 줄이 OR-GROUP 이 되면 원본 부모 줄과 자식 줄이 결과에 남지 않아야 한다.
   뒤이어 `_regex_parse_criteria`(같은 파일 `:489`)가 `*` 를 다시 쪼개는 것도 함께 볼 것.
   재현은 아래 "How to verify" 2번 — GPU 불필요, 수 초.
2. 고친 뒤 같은 명령으로 CT.gov 포함기준이 7개 → 1~2개가 되는지 확인.
   6개 PDF 전수 회귀도 함께 (3번).
3. ARISTOTLE 재수집 → circe 등록 → 환자 수. 0명 규칙이 `ECG`/`LVEF` 둘만 남으면
   중복은 해결된 것이다. 그 둘은 Synthea 데이터 부재라 이 CDM 에서는 못 넘는다.
4. 남은 다섯 스터디도 같은 CT.gov 부풀림을 겪는지 확인. LEADER 27규칙 / PLATO 33규칙에
   같은 패턴이 있을 가능성이 크다.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 1) 산출물이 스냅샷에서 그대로 재생성되는가 (exit 0 이어야 정상)
python3 scripts/export_circe_from_store.py \
  --store snapshots/2026-08-04_six-studies_deliverable.json \
  --out output/circe_be/2026-08-03 --check

# 2) CT.gov 부풀림 재현 (GPU 불필요, 수 초)
docker exec -i artemis-api python - <<'PY'
import sys, json; sys.path.insert(0,'/app')
from src.agents.agent1.pubmed_fetcher import extract_eligibility_from_text
d=json.load(open('/app/data/nct_cache/NCT00412984.json'))
raw=d['protocolSection']['eligibilityModule']['eligibilityCriteria']
c=extract_eligibility_from_text(raw)
print("포함", len(c['inclusion']))          # 현재 7, 목표 1~2
for x in c['inclusion']: print("  ·", x[:96])
PY

# 3) 6개 PDF 전수 회귀 (추출 로직을 건드린 뒤 반드시)
docker exec -i artemis-api python - <<'PY'
import sys, subprocess, re; sys.path.insert(0,'/app')
from src.agents.agent1.parser import LogicDecomposer as LD
from src.agents.agent1.pubmed_fetcher import extract_eligibility_from_text
DOC={'CAROLINA':('NCT01243424','jama_2019_carolina_supplement.pdf'),
     'ARISTOTLE':('NCT00412984','nejmoa1107039_protocol.pdf'),
     'CARMELINA':('NCT01897532','jama_2019_carmelina_supplement.pdf'),
     'EMPA-REG':('NCT01131676','nejmoa1504720_appendix.pdf'),
     'PLATO':('NCT00391872','plato_design_ahj2009.pdf'),
     'LEADER':('NCT01179048','nejmoa1603827_appendix.pdf')}
# 기준선 (2026-08-06): inc/exc/ULN
BASE={'CAROLINA':(20,24,1),'ARISTOTLE':(8,21,1),'CARMELINA':(3,16,1),
      'EMPA-REG':(0,15,1),'PLATO':(18,12,1),'LEADER':(17,14,0)}
for n,(nct,pdf) in DOC.items():
    txt=subprocess.run(['pdftotext',f'/app/data/papers/{nct}/{pdf}','-'],capture_output=True,text=True).stdout
    sec=LD._extract_eligibility_section(txt); c=extract_eligibility_from_text(sec or txt)
    items=(c['inclusion'] or [])+(c['exclusion'] or [])
    uln=sum(1 for i in items if re.search(r'ULN|upper limit of normal',i,re.I))
    print(f"{n:<11} inc={len(c['inclusion']):>3} exc={len(c['exclusion']):>3} ULN={uln}  기준선 {BASE[n]}")
PY

# 4) 재수집 (스터디 하나. 40~60분. 반드시 격리 스토어)
REINGEST_STORE_DIR=/app/tmp/tte_<name> \
REINGEST_CANONICAL=/app/tmp/tte_six_deliver/studies.json \
REINGEST_STUDIES=<id> REINGEST_SKIP_BENCH=1 \
  nohup artemis/scripts/reingest_protocol_pdfs.sh > /tmp/reingest_<name>.log 2>&1 &
echo $! > /tmp/reingest_<name>.pid

# 5) 게이트 — 실행 5분 내 확인. "Cache HIT" 이면 입력이 안 바뀐 것이니 중단
grep -E '^=== |Cache (HIT|MISS)|PDF enriched' /tmp/reingest_run.log

# 6) circe 뽑아서 WebAPI 등록 + 감쇠표
docker exec artemis-api sh -c 'mkdir -p /app/tmp/circe_check'
docker exec -i artemis-api sh -c 'cd /app && python scripts/export_circe_from_store.py \
  --store /app/tmp/tte_<name>/studies.json --out /app/tmp/circe_check'
docker exec -i artemis-api sh -c 'cd /app && python scripts/register_and_generate_circe.py \
  --studies 3 --circe-dir /app/tmp/circe_check'

# 7) 테스트 — 반드시 파일별 개별 프로세스로
for f in test_parse_criteria_items test_pdf_role_strategy test_08_pubmed_fetcher \
         test_09_enricher test_agent1 test_value_constraint \
         test_dose_form_route test_route_qualifier test_route_subtraction; do
  .venv/bin/python -m pytest tests/$f.py -q --no-header -p no:randomly | tail -1
done
```

## Gotchas / constraints

- **`pkill -f` / `pgrep -f` 에 맨 패턴을 쓰지 말 것.** 이 세션에서 또 당했다 —
  `pkill -f 'vllm.entrypoints.openai.api_server'` 가 제 셸을 죽여 **exit 144**.
  첫 글자를 대괄호로 (`'[v]llm.entrypoints'`), 또는 런치 시 PID 를 파일에 남겨
  `ps -o pid,etime= -p <PID>` 로 확인할 것.
- **`_parse_criteria_items` 는 200자 넘는 입력에 실제 LLM 을 호출한다.** 테스트는
  `_regex_parse_criteria` / `_collapse_hierarchical_groups` 를 직접 부를 것.
  이 세션에서 모르고 과금 호출을 하는 테스트를 썼다가 고쳤다.
- **컨테이너는 UTC, 호스트는 KST.** `docker exec ls` mtime 을 `git log` 와 직접 비교하면
  9시간 어긋난다.
- **`/app/output` 은 선언만 되고 마운트 안 됨.** 컨테이너 안에서 거기 쓰면 exit 0 에
  경로까지 출력하는데 호스트엔 없다. `/app/tmp` 아래로 쓰거나 호스트에서 쓸 것.
- **`tmp/` 는 호스트에서 root 소유.** 사용자 셸의 `mkdir` 은 실패한다. 컨테이너 안에서
  만들고 `docker cp` 할 것.
- **`tests/test_parser_paper_status.py` 는 4 실패 / 1 통과가 기본값** (`LogicDecomposer` 에
  `model_name` 없음). `tests/test_tte_api.py` 는 92 실패 / 3 통과가 기본값. 회귀 아님.
- **아킬레스를 다시 돌리려면** `broadsea-hades` 컨테이너가 필요하다.
  `docker compose --profile hades up -d broadsea-hades` 후
  `docker exec -d -e ACHILLES_DB_PASSWORD=mypass broadsea-hades sh -c 'Rscript /tmp/run_achilles_sites.R <site> > /tmp/achilles_<site>.log 2>&1'`.
  스크립트 원본은 `achilles/run_achilles_sites.R` 이고 컨테이너로 `docker cp` 해야 한다.
  사이트 CDM 은 CDM 5.4 테이블 19개가 없어서 스크립트가 빈 채로 만든다 —
  그중 `drug_era`·`condition_era` 가 비어 있으므로 **`DrugEra` 를 쓰는 코호트는
  이 사이트들에서 아무도 못 찾는다.**
- **위키는 `omx_wiki/`** 에 있고 Broadsea 루트라 git 저장소가 아니다. 관련 페이지:
  `route-of-administration-overreach.md`, `tte-artifact-locations.md`.
  갱신 후 `python3 scripts/build_llm_wiki_dashboard.py`.
