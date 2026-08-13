# Handoff — 별칭 경로는 켜진 적이 없었다 — 2026-08-13 (2)

## Goal / context

같은 날 `2026-08-13-the-matcher-was-wrong-and-it-did-not-matter.md`의 후속. 그 문서가
채점기를 고친 뒤 "생성이 의도대로 되는가"로 초점을 옮겼고, 짝없는 gold 90건을 열어보다
**EMPA-REG OUTCOME이 자기 시험약을 만들지 않는다**는 것을 발견했다.

원인은 새 결함이 아니었다. `TTEService._alias_ingredient_mapping` — 시험 기록의 MeSH
intervention 용어로 개발코드를 푸는 경로 — 가 **이미 구현돼 있고 테스트도 있었지만
한 번도 실행된 적이 없었다.**

## Current state

- 브랜치 `fix/tte-a-drug-anchored-entry` · HEAD `54516db` · 작업 트리 깨끗
- 이번 세션 커밋 4건 (아래 Done)
- 새 arm: store `tmp/mesh_fix/` · CIRCE `output/circe_mesh_fix/` ·
  채점 `output/conceptset_overlap/scoped_mesh_fix_rematch.json` ·
  로그 `output/mesh_fix_regen.log`
- 테스트: **100 failed / 2102 passed** (기준선 100 + 신규 20). 회귀 0.
- 보존: `tmp/atc_fix/`, `output/circe_atc_fix/`, `scoped_*_fix.json`(구 채점기) 무수정

## 무엇이 꺼져 있었나

별칭 경로는 작동한다. 직접 호출하면:

```
_alias_ingredient_mapping('BI 10773', ['empagliflozin'])
  -> 45774751  RxNorm Ingredient  empagliflozin  (includeDescendants)
```

급식선 두 개가 **둘 다** 끊겨 있었고 **둘 다 조용히** 실패했다:

1. **하네스가 주입 지점을 건너뜀.** `regenerate_structured_expression.py`가
   `_build_seeded_target_circe`를 직접 호출한다. 프로덕션은 그 직전에
   `_interventionAliases`를 넣는데 그 줄을 지나지 않으므로 매퍼는 항상
   `alias_candidates=None`을 받았다.
2. **스토어에 데이터가 없음.** 10개 스터디 전부 `trialMetadata.interventionMeshTerms`가
   비어 있었다. 이 필드는 원본 레지스트리 페이로드가 있을 때만 기록된다.

데이터는 처음부터 `data/nct_cache/`에 있었다. `NCT01131676` → `['empagliflozin']`.

그래서 EMPA-REG의 `_target`은 문자열 `BI 10773`으로 임베딩 검색을 돌았고 다음을 얻었다
(전부 `score: 1.0`으로 기록):

```
bictegravir / emtricitabine / tenofovir alafenamide   (HIV)
elexacaftor / ivacaftor / tezacaftor                  (낭포성 섬유증)
vilobelimab [Gohibic]                                 (항 C5a)
CHF-6366 .beta.-2 metabolite
```

**지금까지의 모든 arm이 이 상태로 측정됐다.**

## Done this session

| 커밋 | 내용 |
| --- | --- |
| `23c0ef4` | `fix(eval)` 채점기 이름 매칭 수정 (하이픈·복수형·범주명사) |
| `b2d7040` | `docs(handoff)` 채점기 수정 결과 |
| `0caf8bd` | `chore(todolist)` D1~D3 마감 |
| `54516db` | `fix(tte)` **MeSH 별칭 경로 배선** + 백필 스크립트 + 테스트 9건 |

## 측정 (atc_fix → mesh_fix, 동일 채점기 `_rematch` 기준)

| trial | pairs | recall | precision |
| --- | --- | --- | --- |
| ARISTOTLE | 23 → 23 | 0.670 → 0.670 | 0.399 → 0.399 |
| CARMELINA | 21 → 21 | 0.621 → 0.621 | 0.638 → 0.638 |
| CAROLINA | 38 → 38 | 0.588 → 0.587 | 0.589 → 0.589 |
| **EMPA-REG** | **23 → 26** | **0.480 → 0.540 (+0.060)** | **0.450 → 0.513 (+0.063)** |
| LEADER | 26 → 26 | 0.625 → 0.625 | 0.602 → 0.602 |
| PLATO | 11 → 11 | 0.807 → 0.807 | 0.729 → 0.729 |
| **MACRO** | | **0.632 → 0.642 (+0.010)** | **0.568 → 0.578 (+0.011)** |

새로 짝이 생긴 것 (이전에는 `no_counterpart`):

```
[TROY intervention] Empagliflozin        -> 'BI 10773'  recall 1.000  precision 1.000
[TROY intervention] Empagliflozin (ATC)  -> 'BI 10773'  recall 0.997  precision 1.000
```

나빠진 짝은 없다.

**매크로 +0.010은 ±0.02 해상도 아래다. 그러나 이번 건은 튜닝이 아니라 인과가 특정된
수리다** — gold 2개가 recall 0에서 1.000/0.997로 갔고, 개념 하나(45774751)까지 확인된다.
매크로가 작게 보이는 이유는 6개 시험 중 1개에서만 일어났기 때문이다. 매크로로 인용하지
말고 EMPA-REG 수치와 메커니즘으로 인용할 것.

## 격리는 대체로 지켜졌으나 완전하진 않았다

criterion 캐시를 atc_fix에서 복사해 진입약물만 바꾸도록 격리했다(별칭 경로는 캐시보다
먼저 실행되므로 유효). 6개 중 4개가 소수점까지 동일했다. 나머지 둘은 **이번 변경과
무관한 이유**로 움직였다:

- **PLATO**: 생성 집합 이름이 `Chronic kidney disease` → `Chronic Kidney Disease`로
  대소문자만 바뀌었다. 점수 동일.
- **CAROLINA**: `glimepiride` 집합(id=47)이 3개 → 4개 개념으로 바뀌며 recall
  0.0555 → 0.0023. 이 집합은 *Condition* 도메인 기준("investigational product 또는
  glimepiride 과민반응")에서 나오므로 정확-성분 경로를 타지 않고 임베딩 검색으로
  떨어진다. 두 실행 모두 RxNorm Ingredient를 못 집었고, 제품 수준 후보의 순위만
  흔들렸다(`glimepiride 6 MG` ↔ `... by Niche Generics`).

**즉 따뜻한 캐시로도 임베딩 경로에는 실행 간 비결정성이 남는다.** ±0.02 해상도 규칙에
드디어 구체적 메커니즘이 붙었다: 근소차 후보 하나가 뒤집히면 한 시험이 흔들린다.

## Key decisions & why

- **새 store 디렉터리(`tmp/mesh_fix/`)로 갔다.** 저장소 관례이자 `tmp/atc_fix`가 실험
  기록이기 때문. 단 criterion 캐시는 복사해 warm으로 두었다 — 콜드로 돌리면 3시간이고,
  더 중요하게는 진입약물 외 모든 것이 재계산되어 변경을 격리할 수 없다.
- **`drug_name_normalizer`(PubChem 22GB)를 쓰지 않았다.** 그 모듈도 `BI 10773`을
  풀지만(`AZD6140 → Ticagrelor`까지), 이 저장소가 채택한 설계는 MeSH 메타정보 경로다.
  두 개를 동시에 켜면 권위가 둘이 된다. PubChem 경로는 **여전히 어디서도 호출되지
  않으므로** 별도 판단이 필요하다 — 아래 Next steps.
- **불용어로 `disease`를 빼는 안을 기각했다** (앞 핸드오프). 여기 다시 적는 이유는
  같은 유혹이 `drug`/`inhibitor`에도 오기 때문이다.
- **게이트가 결함에 반응하는지 증명했다.** 주입 라인을 지우고 테스트를 돌려 실패를
  확인한 뒤 복구했다. 그때 스크립트 stdout은 `dry run: 0 studies`로 **정상 완료를
  보고했다** — 결함이 숨어 있던 방식 그대로다.

## Next steps (ordered)

1. **`_target` 외 나머지 짧은 질의어.** MeSH 경로는 진입약물만 고친다. 고유 질의어
   271개 중 짧은 약어형 14개(`ALT` `AST` `CK-MB` `COPD` `ECG` `Glucose` `HbA1c`
   `NSTEMI` `STEMI` `Sarcoma` `Stroke` `TIA` `eGFR` `insulin`)는 그대로다.
   실측: `retriever.search("eGFR")` → 정답 0/5 (EGFR 수용체가 상위 점령),
   `"estimated glomerular filtration rate"` → **정답 3/5, 1·2·4위.** 질의어 확장의
   근거는 이미 측정돼 있다.
2. **점수 기록이 죽어 있다.** 후보 6,961개 중 6,950개가 정확히 `0.0`, 11개가 `1.0`,
   중간값 0개. `rerankConfidence`는 323개 기준 중 321개가 `0.0`. 그 1.0 열한 개가
   전부 `BI 10773`의 오답들과 `glimepiride`다. **왜 그 개념이 뽑혔는지 추적할 수단이
   지금 없다.** 다른 모든 개선의 측정 기반이므로 우선순위 높음.
3. **검색기가 둘이고 다르게 동작한다.** `rag_search.py`로 `"eGFR"`을 치면 정답 후보가
   3위에 오지만, 파이프라인이 쓰는 `retriever.py`로는 0/5다. 어느 쪽이 정본인지
   정해져 있지 않다.
4. **PubChem 정규화기 처리 결정.** `src/agents/agent2/drug_name_normalizer.py`와
   `data/pubchem/pubchem_synonyms.sqlite`(22GB)는 완성돼 있으나 호출자가 없다.
   MeSH 경로로 충분하면 삭제하거나, MeSH가 없는 시험을 위한 2차 경로로 배선할 것.
   방치하면 다음 사람이 또 "이미 있는데 왜 안 쓰지"를 반복한다.
5. **`substance abuse` 등 반복 누락 4종.** 4개 시험에서 공통으로 빠진다. 체계적이므로
   규칙 하나로 여러 건 회수 가능.
6. **미생성 39건 중 30건이 무기록.** `_unmappedCriteria`는 9건만 잡는다. 못 세는 것은
   못 고친다.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 실행환경 게이트 — 다른 무엇보다 먼저
.venv/bin/python -m pytest tests/test_environment_matches_requirements.py -q

# 이번 세션 테스트
.venv/bin/python -m pytest tests/test_intervention_mesh_alias_wiring.py \
                          tests/test_conceptset_overlap_eval.py -q -p no:randomly

# 전체 (기준선: 100 failed / 2102 passed)
.venv/bin/python -m pytest tests/ -q -p no:randomly

# 수정 확인 — EMPA-REG 타깃이 empagliflozin인가
.venv/bin/python -c "
import json
d=json.load(open('output/circe_mesh_fix/EMPA-REG_NCT01131676_study8_circe.json'))
cs=[c for c in d['ConceptSets'] if c['name']=='BI 10773'][0]
print([(i['concept']['CONCEPT_ID'], i['concept']['CONCEPT_NAME']) for i in cs['expression']['items']])
"
# 기대: [(45774751, 'empagliflozin')]
```

**arm 전체 재현 (캐시 warm 기준 수 분):**

```bash
# 1) 새 store에 MeSH 백필
docker exec artemis-api python -u /app/scripts/backfill_intervention_mesh_terms.py \
  /app/tmp/<arm>/studies.json --cache-dir /app/data/nct_cache --apply

# 2) 재생성 (캐시를 복사해 두면 warm)
docker exec -d -e TTE_STORE_PATH=/app/tmp/<arm>/studies.json artemis-api sh -c \
  'python -u /app/scripts/regenerate_structured_expression.py --apply > /app/output/<arm>.log 2>&1'

# 3) CIRCE 내보내기 → 4) 채점
.venv/bin/python scripts/export_circe_from_store.py --store tmp/<arm>/studies.json --out output/circe_<arm>
.venv/bin/python scripts/conceptset_overlap_eval.py --mode closure \
  --generated-dir output/circe_<arm> --out output/conceptset_overlap/scoped_<arm>_rematch.json
```

## Gotchas / constraints

- **`scoped_*.json`(구 채점기)과 `scoped_*_rematch.json`(신 채점기)을 같은 표에 올리지
  말 것.** 이번 arm 비교는 `atc_fix_rematch` ↔ `mesh_fix_rematch`로 했다.
- **criterion 캐시를 복사하면 warm이고 변경이 격리되지만, 복사하지 않으면 3시간이다.**
  별칭 경로는 캐시 조회보다 먼저 실행되므로 캐시가 있어도 진입약물은 새로 풀린다.
- **`artemis/tmp/`는 root 소유다.** 컨테이너가 bind mount에 root로 쓴다. 호스트에서
  store를 수정할 수 없으니 백필은 `docker exec`로 돌릴 것.
- **하네스가 이제 별칭 없는 스터디를 크게 경고한다.** 그 경고가 뜨면 그 실행의
  진입약물 결과를 믿지 말 것.
- **임베딩 경로는 실행 간 비결정적이다** (CAROLINA `glimepiride` 3개 ↔ 4개). 1뽑기로
  ±0.02 미만 델타를 주장하지 말 것 — 이제 그 규칙에 메커니즘이 붙었다.
- **`omx_wiki/index.md`는 병렬 세션의 미커밋 상태다.** 루트 저장소에서 다른 세션이
  작업 중이니 커밋 전 `git log`를 확인할 것.
