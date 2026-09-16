# Handoff — 단위를 요구하자 돌던 코호트가 0이 됐다 — 2026-09-14

## Goal / context

자연어 적격기준이 CIRCE JSON으로 제대로 변환되는지가 이 프로젝트의 질문이다. 이번 세션은
**측정을 하지 않았고, 이미 나간 것들을 뒤로 읽었다.** 아주대에서 09-12 발송분 3개 시험 6개
코호트가 전부 0명으로 돌아왔고, 그 원인을 찾는 과정에서 **직전 발송(08-31)에서는 CAROLINA가
31/46명이었다**는 기록이 나왔다. 즉 이번 건은 "여전히 0"이 아니라 **회귀**다.

세션의 결과물은 두 가지다. (1) 회귀의 원인을 정의 파일에서 직접 읽어 특정했고, (2) 발송분이
git에서 복구 불가능했던 상태를 규칙·게이트·태그로 닫았다.

## Current state

- Branch: `fix/tte-a-drug-anchored-entry` · HEAD: `310dc30` · Open PR: 없음
- Uncommitted: 없음 (artemis clean)
- 위키 저장소 `/home/bilab/work/projects/Broadsea`: branch `docs/note-014` · HEAD `cfc2c8e` · clean
- 서버/빌드: 이 세션에서 띄운 것 없음. `broadsea-atlasdb` 컨테이너는 떠 있고 `omop_vocab` 스키마에
  `concept_ancestor` 75,689,500행 (vocabulary v5.0 27-AUG-25) — overlap 채점에 필요
- 복구 태그 3개 생성: `delivery/2026-06-24`, `delivery/2026-08-31`, `delivery/2026-09-12`
- `.venv/bin/python -m pytest tests/test_delivery_provenance.py` → 6 passed

## Done this session

커밋 (오래된 것 → 최신):

- `6771666` 발송 3건을 발송일 기준으로 기록, CAROLINA 회귀 명시
- `4bc2ed0` 06-24 발송분 편입, 발송별 차단 요인 규명
- `b047f31` `deliveries/` 아카이브 + `deliveries/INDEX.json` 원장 + 게이트 스크립트
- `f57dbd8` 게이트를 pytest에 배선
- `7d0e518` 규칙을 `AGENTS.md § WHERE A DELIVERY LIVES`에 확정

새 파일:

- `docs/delivery_index.md` — 발송 3건의 표 6개 (코드버전 / 추출숫자 / 병원실측 / 차단요인 / 성능 / 게이트)
- `docs/site_zero_diagnosis_queries.sql` — 아주대에 보낼 판별 쿼리 7개 (집계값만)
- `deliveries/<날짜>/` + `deliveries/INDEX.json` — 추적되는 발송 아카이브와 원장
- `scripts/verify_delivery_provenance.py`, `tests/test_delivery_provenance.py`
- `output/conceptset_overlap/deliveries_20260914/` — overlap JSON 3건, 게이트 로그 3건, README (gitignored)

6월 발송분 정리: 사용자가 루트에 둔 `test_study_circe_json.zip` →
`output/circe_be/test_study_circe_json_20260624.zip`, 내용은 `output/circe_be/2026-06-24/`에
**원본 레이아웃 그대로** (`test_study_circe_json/<study>/`, `empa_reg_*` 표기 유지).

## Key decisions & why — 후임이 다시 논쟁하지 말 것

- **"송부"는 사용자의 말만이 근거다.** `output/circe_be/`에 파일이 있는 것, zip이 옆에 있는 것,
  게이트가 통과한 것, 이전 세션이 추론으로 적은 원장 행 — 전부 근거가 아니다. 08-31 행은 이
  착오로 세 번 뒤집혔다(추론으로 sent → 사용자 말로 NOT SENT → 사용자가 발송 3건을 나열하며
  다시 sent). 마지막 것만 사용자에게서 나왔다.
- **코드 버전은 발송일 기준으로 적고, 비어 있어도 채우지 않는다.** 06-24는 리포지터리 이전
  (최초 커밋 `6ffd07c`, 07-22), 08-31은 08-13 store에서 export돼 HEAD가 내용을 설명하지 못한다.
  그럴듯한 커밋으로 채우면 나중에 읽는 사람이 공백과 추측을 구별할 수 없다. `version_note` 없는
  null은 `tests/test_delivery_provenance.py`가 거부한다.
- **런 디렉터리 라벨로 코드 버전을 맞추지 말 것.** 여기선 최대 사흘 틀린다. 09-12에 나간 것은
  `output/site_gap/2026-09-15/` 런이다. 09-11~09-14 네 런의 store는 전부 09-11 하루에 생산됐다.
- **규칙 정본은 `AGENTS.md`에 있고 `.claude/rules/broadsea/delivery-provenance.md`는 포인터다.**
  루트 저장소의 pre-commit이 `AGENTS.md`, `CLAUDE.md`, `docs/wiki/`, `docs/dashboard.html`만
  추적하도록 잠겨 있어 `.claude/` 아래는 커밋이 거부된다. allowlist를 넓히는 것은 사용자 판단이라
  건드리지 않았고, 규칙 본문을 `.claude/`에 복사하면 추적 안 되는 사본이 정본과 갈라지므로
  포인터만 뒀다.
- **아카이브는 `output/`이 아니라 발송 zip에서 뽑는다.** `output/`은 gitignored 스크래치이고, zip이
  실제로 나간 것이다. 세 발송 모두 zip 내부 바이트와 md5가 일치함을 확인한 뒤 넣었다.
- **게이트를 믿기 전에 실패시켰다.** 아카이브 생성 전 27건(태그 3개 없음 + 파일 24개 미추적),
  공백 한 글자 추가 시 `ledger md5 fecf2ce9, on disk c23c113a`, pytest에서 `1 failed, 5 passed`.
  전부 복원 확인.

## 측정으로 확인된 결과

### 회귀의 원인 — 단위 요구

아주대 실측 (treatment / comparator):

| 발송 | CARMELINA | CAROLINA | EMPA-REG |
| --- | --- | --- | --- |
| 2026-06-24 | — | — | — (정성 서술 "대부분 환자 0명"만) |
| 2026-08-31 | 0 / 0 | **31 / 46** | 0 / 0 |
| 2026-09-12 | 0 / 0 | **0 / 0** | 0 / 0 |

두 발송의 CAROLINA 정의에서 presence를 요구하는 `ALL` 규칙을 직접 비교하면 변수가 하나다:

| 규칙 | 08-31 (31/46명) | 09-12 (0/0명) |
| --- | --- | --- |
| entry event | `DrugEra` linagliptin / glimepiride | **동일** |
| Body Mass Index | `<= 45`, 단위 조건 없음 | `<= 45`, **`Unit = 9531 (kg/m2)` 요구** |
| HbA1c | `>= 6.5`, `> 7.5`, 단위 조건 없음 | `6.5~8.5`, `> 7.5`, **`Unit = 8554 (%)` 요구** |

둘 다 `ALL`이라 AND로 묶이고 하나만 0이면 코호트 전체가 0이다. entry event가 동일하고 08-31에
31/46명을 냈으므로 **아주대 `drug_era`가 비어 있다는 가설은 실측으로 배제된다.** 단위 요구를
넣은 커밋은 `141ecb7`, `956d8e8`이고 같은 방향 lint가 `5d4dc1d`, `606c686`이다.

배제 규칙(`Occurrence: Exactly 0`)은 사이트에 데이터가 없으면 자동 통과하므로 0의 원인이 될 수
없다. 이 비대칭이 용의자를 20여 개에서 3~6개로 줄였다.

### 발송별 차단 요인이 전부 다르다

| 항목 | 06-24 | 08-31 | 09-12 |
| --- | --- | --- | --- |
| entry event | 3개 전부 `ConditionOccurrence` T2DM | CAROLINA `DrugEra`, 나머지 T2DM | `DrugEra` 4 + T2DM 2 |
| CARMELINA 치료제 concept | **`1580747` sitagliptin (오매핑)** | `40239216` linagliptin | `40239216` |
| CAROLINA 치료제 concept | **`1580747` sitagliptin (오매핑)** | `40239216` | `40239216` |
| EMPA-REG 치료제 concept | **`1254065` CHF-6366 (오매핑)** | **무관 약물 5개** `859730` `1254065` `1201518` `1201447` `702171` | `45774751` empagliflozin |
| BMI/HbA1c 단위 조건 | 없음 | 없음 | **요구** |

06-24는 `'linagliptin'`이라는 이름의 concept set 안에 sitagliptin이 들어 있었고, 그게 `ALL`
규칙이었다. 하나를 고치면 다음이 드러나는 구조였으므로 "계속 0"으로 보였을 뿐 같은 원인의
반복이 아니다.

### gold 대비 성능 (`--mode closure`, treatment arm만)

| 시험 | 06-24 | 08-31 | 09-12 |
| --- | --- | --- | --- |
| CARMELINA | 26 · 0.474 · 0.492 · 0 | 27 · 0.503 · 0.483 · 2 | 20 · 0.614 · 0.626 · 4 |
| CAROLINA | 27 · 0.484 · 0.680 · 2 | 27 · 0.595 · 0.792 · 4 | 39 · 0.597 · 0.571 · 5 |
| EMPA-REG | 19 · 0.503 · 0.550 · 0 | 19 · 0.418 · 0.519 · 1 | 22 · 0.562 · 0.502 · 2 |
| **합(pair 가중)** | **72 · 0.485 · 0.578 · 2** | **73 · 0.515 · 0.607 · 7** | **81 · 0.592 · 0.566 · 11** |

(`pairs · recall · precision · exact`) 델타는 스크립트 자신의 `delta_verdict()`(floor 0.02,
n_draws=1)로 매겼다:

- 06-24 → 08-31: recall +0.030 improved, precision +0.029 improved
- 08-31 → 09-12: recall +0.077 improved, **precision −0.041 regressed**
- 그 구간 시험별: CARMELINA rec +0.111 / prec +0.143 둘 다 improved · CAROLINA rec +0.003
  **unresolved** / prec **−0.221 regressed** · EMPA-REG rec +0.144 improved / prec −0.017 unresolved

**CAROLINA precision −0.221.** 아주대에서 31/46 → 0이 된 그 시험이다. gold 채점과 병원 실측이
서로를 보지 않고 같은 시험을 지목했다.

### 게이트 (오늘 스크립트로 3건 동일 검사)

| 사유 | 06-24 | 08-31 | 09-12 |
| --- | --- | --- | --- |
| **unitless value bound** | **4** | **6** | **0** |
| aliased concept sets | 4 | 6 | 4 |
| asserted bound missing | 2 | 2 | 2 |
| unmapped criteria | 0 | 0 | 6 |
| skips recorded under an allowed reason that does not hold | 0 | 0 | 6 |
| criteria skipped for a reason not on the allowlist | 0 | 0 | 4 |
| unfiltered measurement absence | 0 | 0 | 2 |
| domain mismatch | 0 | 2 | 0 |
| **FAIL / 전체** | 6/6 | 12/12 | 6/6 |

`unitless value bound`가 **6 → 0.** 변경이 겨냥한 항목이 완전히 사라진 그 구간에 병원 코호트가
0이 됐다. 게이트는 단위 **없는** bound를 세고, **사이트가 쓰지 않는 단위를 요구하는** bound는
세지 않는다.

## Next steps (ordered, concrete)

1. **아주대에 규칙별 attrition을 요청한다.** 지금 가장 값싸고 결정적이다. 동아대가 한 번 줬을 때
   EMPA-REG comparator 원인이 한 줄로 확정됐다(`rule 11 "Dietary regimen + Exercise regimen"이
   entry event 94,164건 중 0건 충족`, note-010). 요청 내용: Atlas 코호트 정의 → Generation →
   해당 CDM source 탭의 **Inclusion Rule Statistics** (규칙별 `id`, `name`, `personCount`,
   `gainCount`, `personTotal`) + **규칙 적용 전 entry event 인원수**, 6개 파일 각각. 집계값만
   필요하고 환자 단위 행은 불필요. 문구는 `docs/delivery_index.md` § "규칙별 attrition을 받으면
   무엇이 끝나는가"에 있다.
2. **대안/병행: `docs/site_zero_diagnosis_queries.sql`의 Q3·Q5를 보낸다.** Q3는 HbA1c의
   `unit_concept_id` 분포, Q5는 BMI의 분포. 이 둘만으로 단위 가설은 판정된다. 단 CARMELINA의
   별개 차단 요인은 규칙별 표가 없으면 못 잡는다.
3. **`8554`·`9531`의 deprecated-form 커버리지가 없다** — 실측 확인했다.
   `src/services/value_constraint.py:129` `_UNIT_DEPRECATED_FORMS`에 등록된 standard unit은
   `[8848, 8961, 9448, 720870]`뿐이고 `8554`/`9531`은 `None`이다. note-021이 eGFR(`720870`)에
   대해 은퇴 concept `9117`을 받아주도록 고친 그 처리가 percent와 kg/m2에는 들어가지 않았다.
   **단, 이 수정은 사이트가 "은퇴한 UCUM concept"을 쓸 때만 듣는다.** 사이트가
   `unit_concept_id`를 NULL로 둔다면 deprecated-form 표는 아무 도움이 안 되고, 규칙 쪽에서
   NULL을 허용하거나 단위 조건을 떼는 별도 결정이 필요하다. **2번 결과를 보고 어느 분기인지
   확정한 뒤에 손대라.** 먼저 고치면 엉뚱한 것을 고친다.
4. **게이트에 반대 방향 검사를 추가한다.** 현재 `unitless value bound`는 단위 없는 bound만 잡는다.
   "사이트 CDM이 그 unit concept을 쓰지 않는 bound"를 검사하려면 사이트 ACHILLES 스냅숏
   (`data/site_snapshots/*.zip`)의 단위 분포를 대조하는 lint가 필요하다.
   `scripts/verify_circe_delivery.py`에 추가하고, **반드시 09-12 CAROLINA 파일로 실패를 보여라** —
   그게 이 게이트를 만들게 한 실제 사건이다.
5. **note-018 Row 1을 바로잡는다.** 원장은 08-31을 `NOT SENT (user, 2026-09-12)`로 적고 있는데
   사용자가 2026-09-14에 발송 3건(6/24, 8/31, 9/12)을 나열했다. note-010 본문도 아주대 결과를
   "the delivered 08-31 artifact"에서 나온 것으로 서술하므로 발송 쪽이 맞다. Row 3의 verdict
   `pending`도 이번 실측(0/0/0)으로 채워야 한다. 위키 저장소 `docs/wiki/content/records/note-018.md`,
   수정 후 빌드와 게이트 필수:
   ```bash
   cd /home/bilab/work/projects/Broadsea
   python docs/wiki/build.py --content docs/wiki/content \
     --template docs/wiki/template.html --out docs/wiki/site
   ./docs/wiki/scripts/verify_surfaces.sh
   ```
6. **CAROLINA의 과확장을 확인한다(원인 미측정).** 09-12 CAROLINA는 gold 55세트 대비 85세트를
   만들었고(08-31은 72) ratio 3.0 이상 과확장 쌍이 9건이다: `Smoking` 1→18 (rec 0.00),
   `PCI` 37→280 (prec 0.07), `proliferative retinopathy_proc` 4→34 (rec 0.00),
   `Fasting glucose` 1→4 (rec 0.00). precision −0.221의 원인이라고 **측정되지 않았다** —
   연관만 기록돼 있다.
7. **CARMELINA는 단위 가설로 설명되지 않는다.** 08-31 CARMELINA는 entry가 T2DM, 치료제 concept
   정상(`40239216`), 단위 조건 없음, comparator 팔엔 치료제 `ALL` 규칙조차 없었는데 양쪽 0이었다.
   별개 차단 요인이고 아직 특정되지 않았다. 1번의 attrition 표가 필요한 지점이 정확히 여기다.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 발송 3건이 태그에서 복구 가능한지 (게이트)
python3 scripts/verify_delivery_provenance.py
.venv/bin/python -m pytest tests/test_delivery_provenance.py -q

# 무엇을·언제·어느 코드로 보냈나
git tag -l 'delivery/*' -n30

# 발송분 복구 (대상 디렉터리를 먼저 만들어야 tar가 실패하지 않는다)
mkdir -p /tmp/recover && git archive delivery/2026-08-31 deliveries/2026-08-31 | tar -x -C /tmp/recover

# gold 대비 성능 재측정 (7~8초; omop_vocab 필요)
#   스코어러는 <TRIAL>_NCT..._studyN_circe.json 이름을 기대하므로
#   deliveries/<날짜>/<trial>_treatment.circe.json 을 그 이름으로 복사해 넘겨야 한다.
#   매핑: ARISTOTLE_NCT00412984_study3 / CARMELINA_NCT01897532_study9 /
#         CAROLINA_NCT01243424_study10 / EMPA-REG_NCT01131676_study8 /
#         LEADER_NCT01179048_study1 / PLATO_NCT00391872_study2
.venv/bin/python scripts/conceptset_overlap_eval.py --mode closure \
  --generated-dir <위 이름으로 복사한 디렉터리> \
  --trials CARMELINA CAROLINA "EMPA-REG OUTCOME" --out /tmp/overlap.json

# 배포 게이트 (3건 동일 검사)
.venv/bin/python scripts/verify_circe_delivery.py --dir deliveries/2026-09-12 \
  --store output/site_gap/2026-09-15/store/studies.json
.venv/bin/python scripts/verify_circe_delivery.py --dir deliveries/2026-08-31 \
  --store tmp/tte/studies.json

# 단위 커버리지 실측
.venv/bin/python -c "from src.services.value_constraint import _UNIT_DEPRECATED_FORMS as D; print(sorted(D))"
```

이번 세션의 측정 증거: `output/conceptset_overlap/deliveries_20260914/` (overlap JSON 3건,
게이트 로그 3건, 재현 명령과 주의사항이 담긴 `README.md`). gitignored이므로 git에는 없다.

## Gotchas / constraints

- **06-24 게이트 열은 store 참조 검사에 대해 무의미하다.** 그 발송의 store가 보존돼 있지 않아
  `tmp/tte/studies.json`(08-13 store)로 돌렸다. 파일 자체만 보는 lint
  (`unitless value bound`, `aliased concept sets`, `asserted bound missing`)만 읽어라.
  `rule name`, `domain mismatch`, `entry concept`는 읽으면 안 된다.
- **게이트 스크립트 버전이 다르면 PASS/FAIL은 비교 불가다.** 09-12·09-13 런이 2/12였다가 0/12가
  된 것은 산출물이 나빠진 게 아니라 검사 항목이 늘어난 것이다(note-023이 09-14 내용을 당시
  스크립트로 재측정해 확인). 세 발송을 비교할 때는 반드시 같은 체크아웃으로 돌려라.
- **총 기준수 증가는 품질 지표가 아니다.** 09-15 런에서 ARISTOTLE 44→78, CAROLINA 84→115로 늘고
  LEADER는 83→70으로 줄었다. 방향이 시험마다 갈린다.
- **`_generationCensus`는 09-12 산출물에만 있다.** 06-24·08-31 발송분에는 없어서
  `InclusionRules / ConceptSets`만 셀 수 있다. 세 발송의 총 기준수를 직접 비교하면 안 된다.
- **micro(concept mass) 숫자를 품질로 인용하지 말 것.** JSON에 있지만 이 데이터에서도
  per-criterion과 반대 방향이다 (예: 09-12 CAROLINA micro rec 0.150 / prec 0.270 대
  per-criterion 0.597 / 0.571).
- **floor 0.02 미달 델타는 방향을 주장할 수 없다.** `n_draws=1`이므로 `delta_verdict()`가
  `unresolved`를 반환한다. CAROLINA recall +0.003, EMPA-REG precision −0.017이 그 경우다.
- **comparator arm은 채점하지 않았다.** gold는 시험당 정의 하나이고 treatment arm이 counterpart다.
- **`output/`에 새 배포 위치를 만들지 말 것.** 이미 `circe_be/`(준비 선반)와 `deliveries/`(복구
  지점)로 역할이 갈려 있다. 과거에 21개 디렉터리 5개 표기로 드리프트한 이력이 있다.
- **루트 저장소는 `git add -A` 금지.** pre-commit이 allowlist 밖 경로를 거부하고, 다른 세션의
  작업을 쓸어담을 위험이 있다. 경로를 명시해 스테이징하라.
- **아주대 CDM 단위를 관측한 적이 없다.** 회귀 결론은 "단위 요구가 추가됐다"(정의 측 사실) +
  "31/46 → 0"(실측)의 결합이다. 어느 단위 값 때문인지는 미확인이며, 그 확인 없이 3번을
  진행하면 엉뚱한 것을 고친다.

## 관련 기록 (Broadsea 저장소, branch `docs/note-014`)

- `docs/wiki/content/records/note-010.md` — 아주대·동아대 실측 (08-31 발송 결과, CAROLINA 31/46)
- `docs/wiki/content/records/note-018.md` — 병원 납품 판정 원장 (Row 1이 바로잡혀야 함, 위 5번)
- `docs/wiki/content/records/note-021.md` — eGFR 13,845행 전부 은퇴 concept `9117` 사용,
  `_UNIT_DEPRECATED_FORMS`로 eGFR만 복구 (아주대 0 → 112행)
- `docs/wiki/content/records/note-023.md` — 09-12 발송을 만든 재추출, 게이트 0/12, 두 blocker
- `.claude/rules/broadsea/delivery-provenance.md` — 규칙 포인터 (정본은 artemis `AGENTS.md`)
