# Handoff — 값 제약(ULN) 6개 스터디 circe-be 생성 — 2026-08-03

## Goal / context

임상시험 프로토콜 원문에서 `ALT > 3x ULN` 같은 **정상 상한 배수 조건**을 뽑아 OMOP
Circe 코호트 정의(`RangeHighRatio`)로 옮기는 일. 사용자의 최종 요구는
**"수정한 코드로 6개 스터디 전부 circe-be를 만들어라. 그걸로 비교하겠다"**.

## Current state

- Branch: `fix/tte-a-drug-anchored-entry` · HEAD: `b1fb99c` · PR 없음 (push 안 함)
- 작업 트리 깨끗. 미커밋 변경 없음.
- **실행 중: 6개 스터디 재수집** — `/tmp/reingest_six.log`, PID 파일
  `/tmp/reingest_six.pid`, 내부 로그 `/tmp/reingest_run.log`
  - 스토어 `/app/tmp/tte_six_fixed`, 원본 `/app/tmp/tte_nct/studies.json`
  - 순서: ARISTOTLE(3) → PLATO(2) → CAROLINA(10) → EMPA-REG(8) → CARMELINA(9) → LEADER(1)
  - 스터디당 60~90분. 벤치마크는 `REINGEST_SKIP_BENCH=1` 로 건너뜀
  - **6개를 한 스토어에 넣으므로 병합 단계가 필요 없다** (아티팩트 id 충돌 원천 제거)

### 기대값 (오프라인 측정 완료, GPU 없이 재현 가능)

| 스터디 | id | NCT | 추출 경로 | inc/exc | ULN |
|---|---|---|---|---|---|
| ARISTOTLE | 3 | NCT00412984 | protocol 섹션 | 13 / 23 | 1 |
| PLATO | 2 | NCT00391872 | 전체텍스트 폴백 | 24 / 12 | 1 |
| CAROLINA | 10 | NCT01243424 | supplement 섹션 | 22 / 26 | 1 |
| EMPA-REG | 8 | NCT01131676 | 전체텍스트 폴백 | 0 / 15 | 1 |
| CARMELINA | 9 | NCT01897532 | 전체텍스트 폴백 | 3 / 18 | 1 |
| LEADER | 1 | NCT01179048 | appendix 섹션 | 19 / 14 | 0 (gold도 0) |

ULN 1건은 문장 하나를 뜻하고, LLM이 그것을 분석물(ALT/AST/ALP)마다 하나씩 배치해
`RangeHighRatio` 3건이 되는 것이 기대 동작 (커밋 `fe08096`).

## Done this session (2026-08-03 오후)

- `786e649` — `Criteria for exclusion:` 어순 수용. CAROLINA 제외기준 0 → 42
- `20d20ef` — LEADER를 `_ALL_TARGETS` 에 추가, gold=0 거짓실패 차단,
  `REINGEST_CANONICAL` 오버라이드, 벤치마크가 `REINGEST_STUDIES` 를 따르도록
- `b1fb99c` — PDF 페이지 머리글 필터. ARISTOTLE 12건 / CAROLINA 32건 제거
- `docs/tte_agent/06`·`07` 에 실행 슬라이스와 상태 기록 (루트는 git 아님)

## 확정된 진단 두 건

**1. CAROLINA 제외기준 0건 — 헤더 어순.**
JAMA supplement 는 Boehringer Ingelheim 프로토콜 요약표이고 `Criteria for exclusion:`
로 절을 연다. `exc_patterns` 는 `exclusion criteria` 만 받았다. 포함 쪽은 같은 문서가
`Inclusion criteria:` 를 표준 어순으로 써서 우연히 살아남았다. `criteria_keywords` 는
이미 `"exclusion:"` 를 포함하고 있었으므로 게이트는 "기준 있음"이라 말하고 추출기는
조용히 0을 반환했다 — 로그 한 줄 남지 않는 실패.

**2. ARISTOTLE circe-be 0명 — 페이지 머리글이 기준이 됐다.**
WebAPI 감쇠표(코호트 3395, `synthea_cdm_aristotle_results.cohort_inclusion_stats`):
`base_count=3100 → final_count=0`, 41개 규칙 중 **9개가 0명**.

- 머리글 유래 4건: `Approved v 8.0`(규칙 5), `BMS-562247`(6), `CV185030`(7),
  `apixaban`(13). 전부 **Procedure 도메인**으로 매핑됐다. `CV185030` 은 PDF 전체에
  215회 등장한다 — 페이지 머리글이다. Circe 는 InclusionRule 을 AND 하므로 하나로 충분.
- **Synthea 데이터 부재 5건** (별도 사안, 코드 미수정 — 사용자 결정):
  `ECG at enrollment`(9), `Diabetes mellitus + Hypertension`(32),
  `Symptomatic CHF + LVEF <= 40%`(33), `Holter + Intracardiac electrogram`(34),
  `AF/Flutter documented on two occasions`(35).
  Synthea 벤치마크 CDM 에 LVEF·Holter·심내막 전위도·ECG 시술·"2회 문서화" 시간논리가
  없다. **머리글을 고쳐도 ARISTOTLE 이 0명을 벗어난다는 보장은 없다.**
  gold(TROY, id=1138)가 같은 소스에서 1,113명을 얻는 것은 개별 기준을 더 적은 복합
  규칙으로 묶기 때문 (ADR-013 의 "그룹핑").

## 철회된 진단 — 다시 시도하지 말 것

전 세션의 미커밋 `_extract_eligibility_windows`(슬라이딩 창)는 **거짓 측정에 근거**했다.
docstring 은 `Active liver disease` 가 13,424자 섹션의 오프셋 **13,431**(끝에서 7자 뒤)에서
시작한다고 적었으나, 실제는 **7,366** — 섹션 안이다. 20K 상한은 발동조차 하지 않았다.

20K 를 넘는 섹션은 ARISTOTLE 프로토콜(26,406자) 하나뿐이고, **상한/무상한/창분할 세
방식의 결과가 완전히 동일**하다 (inc=19 exc=29 ULN=1). `_best_section_match` 가 매치 중
가장 긴 것 하나만 고르고, 그 캡처는 20K 훨씬 이전에 끝나기 때문이다.

되돌렸지만 버리지는 않았다:
- `git stash@{1}` — parser.py 구현
- `git stash@{0}` — 짝이 되는 테스트 (**둘을 함께 복원할 것**)

## Key decisions & why

**ADR-031-B: 파서가 숫자를 뽑고 LLM 은 배치만 한다.**
`docs/adr/ADR-031-B_Constraint_Annotation_Feedback.md`. 결과적으로
**"LLM 이 문헌에서 값 제약을 추출한다"고 주장할 수 없다.** 보고서·논문에서 이 구분을 지킬 것.

**gold(TROY)를 정답으로 쓰지 말 것.** ADR-013 이 2026-02 에 "TROY 는 전문가 참조,
design paper 가 ground truth"로 결정. 분모를 16(TROY)으로 볼지 15(논문 기준)로 볼지는
`omx_wiki/adr-031-value-constraint.md` 에 양쪽 다 적어둠.

**PLATO 4번째(고감도 TnI)는 도달 불가.** 2009년 논문에 없는 검사법. TROY 보강분.

## Next steps (ordered)

1. **재수집 완료 대기** — `tail -f /tmp/reingest_run.log`.
   각 스터디 끝에 `[after] criteria=N ratio-emitting=M` 이 찍힌다.
   기대: ARISTOTLE 3 · PLATO 3 · CAROLINA 3 · EMPA-REG 3 · CARMELINA 3 · LEADER 0
2. 결과 집계 (아래 "How to verify" 4번). **description grep 금지**
3. circe-be 생성 → WebAPI 등록 → 코호트 생성 → 환자 수 비교
4. 0명이 나오면 **먼저 감쇠표를 볼 것** (아래 5번). 규칙 이름이 기준처럼 보이지 않으면
   추출 문제, 기준처럼 보이는데 0이면 Synthea 데이터 부재 쪽이다
5. 미해결로 남긴 것: `follow-up` 종료자가 CAROLINA 섹션 오프셋 9,751 에서 문장 중간에
   매치해 비검사 제외기준 2건을 자른다. 그 너머에 ULN 텍스트는 없어서 기록만 해뒀다

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea

# 1) 실행 중인 재수집 상태
ps -o pid,etime= -p "$(cat /tmp/reingest_six.pid)" || echo "끝남"
grep -nE '^=== |ratio-emitting|Cache (HIT|MISS)' /tmp/reingest_run.log

# 2) 게이트 — 실행 4분 내 확인. 둘 중 하나라도 틀리면 중단
#    기대: 첫 스터디 헤더 1줄, 그리고 "Cache MISS"
#    "Cache HIT" 이면 옛 IR 을 재생하므로 결과가 무의미

# 3) 재수집 (한 스터디만 다시 돌릴 때)
REINGEST_STORE_DIR=/app/tmp/tte_<name> \
REINGEST_CANONICAL=/app/tmp/tte_nct/studies.json \
REINGEST_STUDIES=<study_id> REINGEST_SKIP_BENCH=1 \
  nohup artemis/scripts/reingest_protocol_pdfs.sh > /tmp/reingest_<name>.log 2>&1 &

# 4) 결과 집계 (description grep 금지)
docker exec -i artemis-api python - <<'PY'
import sys, json; sys.path.insert(0,'/app')
from src.services.value_constraint import build_measurement_value_filter as build
S=json.load(open('/app/tmp/tte_six_fixed/studies.json'))['studies']
for st in sorted(S, key=lambda s: s['id']):
    if st['id'] not in (1,2,3,8,9,10): continue
    el=st.get('eligibility') or {}
    rows=[*(el.get('inclusionCriteria') or []),*(el.get('exclusionCriteria') or [])]
    hits=[c for c in rows if 'RangeHighRatio' in build(c.get('valueConstraint'))]
    print(f"id={st['id']:<3} criteria={len(rows):<4} ratio={len(hits)}")
    for c in hits: print("   ·", ' '.join((c.get('description') or '').split())[:80])
PY

# 5) 코호트가 0명일 때 — 어느 규칙이 죽였는지 (WebAPI 감쇠표)
docker exec broadsea-atlasdb psql -U postgres -d postgres -c "
SELECT DISTINCT s.rule_sequence, LEFT(i.name,58) AS rule_name, s.person_count
FROM <results_schema>.cohort_inclusion_stats s
LEFT JOIN <results_schema>.cohort_inclusion i
  ON i.cohort_definition_id=s.cohort_definition_id AND i.rule_sequence=s.rule_sequence
WHERE s.cohort_definition_id=<generation_id> AND s.person_count=0
ORDER BY s.rule_sequence;"
#   ARISTOTLE: results_schema=synthea_cdm_aristotle_results, generation_id=3395

# 6) 오프라인 추출 확인 (GPU 불필요, 수 초)
docker exec -i artemis-api python - <<'PY'
import sys, subprocess, re; sys.path.insert(0,'/app')
from src.agents.agent1.parser import LogicDecomposer as LD
from src.agents.agent1.pubmed_fetcher import extract_eligibility_from_text
txt = subprocess.run(['pdftotext','/app/data/papers/<NCT>/<file>.pdf','-'],
                     capture_output=True, text=True).stdout
sec = LD._extract_eligibility_section(txt)
c = extract_eligibility_from_text(sec or txt)
print("inc", len(c['inclusion']), "exc", len(c['exclusion']))
for i in c['inclusion']+c['exclusion']:
    if re.search(r'ULN|upper limit of normal', i, re.I): print("  ULN:", i[:150])
PY

# 7) 테스트 — 반드시 파일별 개별 프로세스로
cd artemis
for f in test_08_pubmed_fetcher test_criterion_constraint_annotation test_agent1_ir_cache_key \
         test_agent1 test_value_constraint test_apply_artifact_preserves_criteria; do
  .venv/bin/python -m pytest tests/$f.py -q --no-header -p no:randomly | tail -1
done
```

## 확정된 사실 — 다시 유도하지 말 것

- **LLM 체인은 재현 가능하도록 설정돼 있다.** `LLM_TEMPERATURE=0.0`,
  `LLM_SEED=42` (`src/settings.py:41-42`, 컨테이너 실측 확인).
  세션 중 "매핑이 비결정적"이라는 주장을 한 적이 있으나 **근거가 틀렸다** —
  EMPA-REG 결과 차이는 2026-06-22 구코드와 08-03 코드의 프롬프트·파서 차이
  (`baa2629`, `fe08096`, `3fd4b8e`)로 설명되며 샘플링 흔들림이 아니다.
  vLLM continuous batching이 greedy 출력을 흔드는지는 **측정한 적 없음**.
- **PLATO의 경구 항응고제 기준에 뺄 것이 없는 것은 정상이다.** 리바록사반·
  다비가트란·아픽사반의 Clinical Drug Form 이 각각 4개·8개 조회되고 전부 경구다.
  조회 실패와 진짜 0건이 똑같이 `+0` 으로 보이므로 확인해두었다.
- **벤치마크 CDM 들에는 약이 거의 없다.** `synthea_cdm_aristotle` 21,000명에
  약물 노출 6,685행·서로 다른 약물 **2종**, `synthea_cdm_plato` 2종,
  `synthea_cdm_leader` **1종**. 대상약·비교약만 심어둔 데이터라 자격기준의
  병용약·제외약은 존재하지 않는다. 경로 뺄셈은 이 데이터에서 환자 수를
  바꾸지 않는다.
- **`SYNTHEA_CDM_BENCHMARK` 는 고정 벤치마크가 아니다.**
  `evaluate_generated_gold_studies.py` 가 gold 로부터 환자를 생성해 매번
  ETL 로 갈아끼우는 작업 스키마다. 현재 내용물로 돌린 숫자는 의미 없다.
- **`evaluate_generated_gold_studies.py` 는 지금 상태로 실행되지 않는다.**
  `STUDY_CONFIGS` 가 가리키는 gold 파일 4개가 모두 없다
  (`data/gold/LEADER/LEADER_GOLD.json` 등). 실제로 있는 것은 TROY arm 별 파일.

## 미해결 — 설명되지 않은 것

- **EMPA-REG 의 간효소 기준이 6번 복제된 이유.** 코드 변경이 "결과가 달라진 것"은
  설명하지만 "왜 하나가 6개로 복제됐는지"는 설명하지 못한다. `fe08096` 의 의도는
  분석물당 규칙 하나(= 3건)이지 동일 문장 6벌이 아니다. gold 는 3.
- **CARMELINA 는 반대로 1건으로 뭉쳤다** (`Liver enzyme elevation` 하나).
  같은 코드·같은 모델인데 CAROLINA 는 3개로 정확히 분해했다.
- 두 건 모두 값 제약 분해 단계의 문제이며 경로 뺄셈과 무관하다.

## 병원 전달 산출물 (2026-08-03)

- `output/circe_be/tte_circe_6studies_20260803.tar.gz` — circe 6종 + README + manifest
- 경로 뺄셈 적용본. `isExcluded` 148건 (CAROLINA 139, EMPA-REG 9, 나머지 0)
- 원본 스토어 `tmp/tte_six_fixed/`, 경로 적용본 `tmp/tte_six_routed/`
- 스냅샷 `snapshots/2026-08-03_six-studies_fixed-code.json` (md5 검증)
- 평가 목적으로 WebAPI 코호트 정의 **3396~3401** 을 만들었다. 전부 0명이며
  당뇨 3종은 소스가 부적절해 무효. 불필요하면 삭제해도 된다.

## Gotchas / constraints

- **컨테이너는 UTC, 호스트는 KST.** `docker exec ls` 의 mtime 을 `git log` 시각과 직접
  비교하면 9시간 어긋난다. 이 때문에 ARISTOTLE 스토어가 구코드 산물로 잘못 보였고
  불필요한 90분 재실행을 할 뻔했다. 환산 후 비교할 것.
- **`ARTEMIS_GIT_REV` 는 컨테이너에 전달되지만 스토어에 저장되지 않는다.** 산출물 출처를
  파일 mtime 으로 추론해야 하는 상태. 기록하도록 고칠 가치가 있다.
- **`pgrep -f NAME` / `pkill -f NAME` 는 자기 자신을 매치한다.** 첫 글자를 대괄호로
  (`'[r]eingest'`), 또는 런치 시 PID 를 잡아 `ps -o pid,etime= -p <PID>` 로 확인할 것.
  실제로 세션을 죽인 적 있음(exit 144).
- **`rg` 는 이 프로젝트 스크립트에서 쓰지 말 것.** `~/.local/bin/rg` 에 있지만 cron 기본
  PATH(`/usr/bin:/bin`)에는 없다. 스크립트에서는 POSIX `grep -oE`.
- **파일 역할 라벨을 믿지 말 것.** 6개 중 3개는 자격기준이 예상 위치에 없다:
  PLATO 의 NEJM 부록은 그림 범례뿐(기준은 `plato_design_ahj2009.pdf`),
  ARISTOTLE 부록은 인명·CONSORT뿐(기준은 `nejmoa1107039_protocol.pdf`),
  LEADER 부록의 ULN 3건은 리파아제 결과 그림이지 자격기준이 아니다.
  EMPA-REG·CARMELINA 는 **섹션 추출 자체가 실패**하고 전체텍스트 폴백(`parser.py:470`)으로
  기준에 도달한다. CARMELINA 의 ULN 문장은 앞이 잘려 `ALT` 토큰 없이 `(SGPT)` 로 시작한다 —
  숫자는 파싱되지만(`gte 3.0`) 분석물 배치가 취약하다.
- **성공 판정을 description 문자열로 하지 말 것.** `process_eligibility` 가 기준 이름을
  바꾼다(예: `Troponin/CK-MB elevation`). 반드시 `build_measurement_value_filter` 출력으로.
- **테스트를 한 번에 돌리지 말 것.** `tests/test_parser_paper_status.py` 가 import 시점에
  `src.models.ir` 을 MagicMock 으로 덮어 이후 테스트를 오염시킨다. 파일별 개별 프로세스로.
- **`tests/test_parser_paper_status.py` 는 4 실패 / 1 통과가 기본값** (`LogicDecomposer`
  에 `model_name` 속성 없음). 베이스라인에서 확인함. 회귀로 오해하지 말 것.
- **`tests/test_tte_api.py` 는 92 실패 / 3 통과가 기본값.** `testclient_compat.py` 의
  starlette/httpx 비호환. 어떤 변경과도 무관.
- **`artemis/tmp/` 는 gitignore.** 중요한 산출물은 `snapshots/` 에 복사해둘 것.
- **`docs/tte_agent/` 는 Broadsea 루트에 있고 그곳은 git 저장소가 아니다.** 커밋되지 않는다.
- 컨테이너 `/app/output` 마운트는 `compose/artemis-api.yml` 에 선언돼 있으나
  **컨테이너 재생성 전이라 아직 미발효**. 현재는 양쪽 심볼릭 링크로 우회 중.
