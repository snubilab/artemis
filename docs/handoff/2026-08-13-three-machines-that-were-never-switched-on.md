# Handoff — 켜진 적 없는 기계 셋 — 2026-08-13 (3)

## Goal / context

같은 날 세 번째. 앞선 두 문서(`2026-08-13-the-matcher-was-wrong-and-it-did-not-matter.md`,
`2026-08-13-the-alias-path-was-never-switched-on.md`)가 채점기를 고치고 EMPA-REG의
시험약 결함을 잡은 뒤, **"짝없는 gold 90건"** 을 파고들어 나온 후속 4건을 각각
workflow로 조사하고 패치했다.

이번 세션의 관통 주제는 하나다. **이 저장소에는 구현·테스트가 끝났는데 아무도 호출하지
않는 기계가 반복적으로 나타나고, 전부 조용히 실패한다.** 이번에만 셋을 더 찾았다.

## Current state

- 브랜치 `fix/tte-a-drug-anchored-entry` · HEAD `2f57935` · **PR 없음** (`git remote` 없음)
- 작업 트리 **깨끗** (uncommitted 0)
- 테스트: **100 failed / 2118 passed / 10 skipped** — 실패 100건은 세션 시작 시점과 동일,
  회귀 0. 늘어난 통과분은 전부 이번 세션 신규 테스트.
- 실행 중:
  - vLLM PID `134304` — `google/gemma-4-E4B-it`, `:8000`, max-model-len 32768,
    `--gpu-memory-utilization 0.55`
  - 컨테이너 `artemis-api` / `ohdsi-webapi` / `broadsea-atlasdb` / `artemis-neo4j-v2` Up
- 새 arm: store `tmp/mesh_fix/` · CIRCE `output/circe_mesh_fix/` ·
  채점 `output/conceptset_overlap/scoped_mesh_fix_rematch.json` ·
  로그 `output/mesh_fix_regen.log`
- **프로덕션 스토어 `tmp/tte/studies.json`에 MeSH 백필 적용됨**
  (백업 `tmp/tte/studies.pre-mesh-20260813T101318Z.json`)

## Done this session

| 커밋 | 내용 |
| --- | --- |
| `23c0ef4` | 채점기 이름 매칭 — 하이픈/숫자 접기, 복수형, 범주명사 단독 매칭 금지 |
| `b2d7040` | 그 결과 핸드오프 |
| `0caf8bd` | todolist D1~D3 마감 |
| `54516db` | **MeSH 별칭 경로 배선** + 백필 스크립트 + 테스트 |
| `59c3f58` | mesh_fix arm 핸드오프 |
| `ccb8ca8` | **약어 확장 4행** (`_CURATED_EXPANSIONS`) |
| `5bf6fb8` | **후보 score/source 위조 수정** |
| `8692a55` | **alias가 비교약을 시험약에 넣던 결함** |
| `2f57935` | 이름해결 권위 문서화 (`AGENTS.md` NAME RESOLUTION OWNERSHIP) |

## Key decisions & why

### 켜진 적 없는 기계 셋 — 이번 세션에서 발견

1. **MeSH 별칭 경로** (`TTEService._alias_ingredient_mapping`). 작동은 완벽했다.
   급식선 둘이 **동시에** 끊겨 있었고 둘 다 조용했다 — 하네스가 주입 지점을 건너뛰었고,
   어떤 스터디도 `trialMetadata.interventionMeshTerms`를 안 들고 있었다. 데이터는
   `data/nct_cache/`에 처음부터 있었다.
2. **`QueryExpander`** — `tte_service.py`의 라이브 경로가 `umls_expander` 없이 생성해서
   항상 원문을 반환했다. 그 UMLS 백엔드는 `MRCONSO.RRF`가 라이선스 게이트라 이 호스트에
   없다. **"빌드 안 한 것"이 아니라 "받을 수 없는 것"** — MeSH 건과 성격이 다르다.
3. **`abbreviation_expander.py`** — 하드코딩 사전을 지우고 위 UMLS로 대체하려다
   no-op만 남았다. `AGENTS.md`에 대체됨으로 기록.

### 약어 확장을 4행으로 묶은 이유

eGFR 하나만 보고 일반화하려던 것을 **14개 전수 측정이 막았다**:

| 판정 | 개수 | |
| --- | ---: | --- |
| 확장이 명백히 나음 | **4** | eGFR, NSTEMI, TIA, Stroke |
| 차이 없음 | 7 | ALT, AST, CK-MB, COPD, HbA1c, STEMI, insulin |
| **약어가 더 나음** | **2** | Glucose, Sarcoma |
| 둘 다 오답 | 1 | ECG |

`Sarcoma`의 정답 개념 4311439가 1→5위로 밀리고 `Glucose`의 표준 LOINC 3000483은
top-10 밖으로 사라진다. **둘 다 7자라 기존 6자 길이 게이트가 이미 막고 있다 — 그 게이트를
"고치지" 말 것.** 테스트가 고정해 두었다.

`Stroke`는 정직하게 말해 극적이지 않다. 맨 약어도 `Ischemic stroke`를 주고 확장형이
포괄 개념 `Cerebrovascular accident`를 준다. **틀린 게 아니라 좁은 것.**

### score/source는 비어 있던 게 아니라 거짓이었다

`_fetch_concept_candidates`가 CDM에서 id로 재수화하며 7개 필드 중 5개만 넘겨,
`score`/`source`가 Pydantic 기본값 `0.0` / `"rag"`로 내려앉았다. 빠뜨린 인자 하나가
관측된 두 상수를 동시에 설명한다. **`"rag"`는 KG/ATC 확장 유래 개념에게 적극적으로 거짓**
이었다 — 검색을 거친 적 없는 것들이다.

`None`을 쓴 이유: **0.0은 결함이 만들어내던 바로 그 값**이라, "점수 없음"과 "점수 나쁨"을
읽는 사람이 구분할 수 있어야 한다.

### 에이전트가 제안한 4파일 패치를 1파일로 줄였다

제안은 `MappingResult`에 필드를 추가해 `workflow.py`에서 채우는 것이었으나, 실제로
`_slow_path`는 `List[int]`만 반환하고 `result`가 스코프에 없다. 서명을 바꾸거나 인스턴스
상태를 쓰면 배치 경로의 `ThreadPoolExecutor`와 얽힌다. 반면 `pre_fetched_candidates`가
**바로 그 함수의 인자로 이미 들어와 있어서**, 검색기가 만든 실제 객체를 그대로 읽으면
된다. 한계는 커밋 메시지에 적었다 — pre-fetch 없는 경로는 점수를 기록하지 못한다.
(6개 시험 실측상 적격기준은 100% pre-fetch를 받는다.)

### PubChem은 두되 배선하지 않는다 (사용자 결정)

730개 시험 캐시 전체에서 **고유하고 정확한 기여가 1건**(TMC435 → Simeprevir).
`"MeSH 용어 없음"`과 `"RxNorm 성분 없음"`은 **같은 조건**(승인 전 화합물)이라, 코드를
정확히 풀고 OMOP에 개념이 없는 곳에 도착한다. 게다가 22GB 안에 `is_ambiguous=False`로
**확신에 찬 오답**을 내는 오염된 간선이 있다 — 모듈 docstring이 막겠다던 바로 그 실패.
브랜드명 구간은 OMOP `concept_relationship` 3-테이블 조인이 저장공간 0으로 더 잘한다.
디스크는 1.3T 여유가 있어 급하지 않으므로 **두고 문서화만** 한다.

### 재검토를 막기 위해 기록한 정정 3건

이번 세션 중간 보고에서 내가 틀렸던 것들이며, `AGENTS.md`에 settled로 박았다:

- **검색기 두 개는 프로덕션에서 어긋나지 않는다.** `RAGSearch`가 eGFR을 잘 찾은 건
  `domain_filter`를 손으로 넘겨서 생긴 착시고, 라이브 호출자는 아무도 안 넘긴다.
- **`_VOCAB_PREFERENCE`의 LOINC −0.30은 결함이 아니다.** 밀려난 SNOMED 쌍은 gold에
  없고, 이 선호가 **진짜 gold(3049187, 46236952)를 1~2위로 올린다.**
  `tests/test_map_retriever_scoring.py::test_hba1c_loinc_beats_snomed`가 지킨다.
- 채점기 기준 개수는 **592**개이지 323개가 아니다. 앞 보고에서 중복제거한 분모와
  안 한 분모를 섞었다. 후보 수준 수치(6,961/6,950/11)는 정확했다.

## 측정 (atc_fix → mesh_fix, 동일 채점기 `_rematch` 기준)

| trial | pairs | recall | precision |
| --- | --- | --- | --- |
| ARISTOTLE | 23 → 23 | 0.670 → 0.670 | 0.399 → 0.399 |
| CARMELINA | 21 → 21 | 0.621 → 0.621 | 0.638 → 0.638 |
| CAROLINA | 38 → 38 | 0.588 → 0.587 | 0.589 → 0.589 |
| **EMPA-REG** | **23 → 26** | **0.480 → 0.540** | **0.450 → 0.513** |
| LEADER | 26 → 26 | 0.625 → 0.625 | 0.602 → 0.602 |
| PLATO | 11 → 11 | 0.807 → 0.807 | 0.729 → 0.729 |
| **MACRO** | | **0.632 → 0.642** | **0.568 → 0.578** |

`[TROY intervention] Empagliflozin` → recall **1.000** / precision **1.000**,
`Empagliflozin (ATC)` → 0.997 / 1.000. 나빠진 짝 0건.

**매크로 +0.010은 ±0.02 아래다. 인과가 특정된 수리이므로 매크로가 아니라 EMPA-REG
수치와 메커니즘으로 인용할 것.**

CAROLINA −0.001과 PLATO의 집합명 대소문자 변화는 이번 변경과 무관하다 —
`glimepiride` 집합(Condition 도메인 기준)이 임베딩 경로로 떨어져 실행 간 후보 순위가
흔들린 것. **따뜻한 캐시로도 임베딩 경로에는 비결정성이 남는다.**

## Next steps (ordered, concrete)

1. **`_alias_ingredient_mapping`의 55% 거부율.** 별칭 경로가 실제로 발화하는 149개 시험 중
   **82개에서 거부**한다 — "정확히 하나만 통과" 조건 때문. MeSH 경로의 진짜 한계이고
   PubChem도 못 고친다(123개 좌초 seed 중 8개 구제, 그중 정확·고유는 1개).
   `src/services/tte_service.py`의 `_alias_ingredient_mapping` 내 `len(resolved) != 1`
   분기부터 볼 것.
2. **`_VOCAB_PREFERENCE` 모집단 수준 측정.** eGFR 1건으로만 확인했다. 상수를 건드리기
   전에 567개 기준 전체로 선호 on/off 매크로 recall·precision을 재야 한다.
   `src/agents/agent2/retriever.py:22`. 측정 없이 만지지 말 것.
3. **미생성 39건 중 30건이 무기록.** `_unmappedCriteria`가 9건만 잡는다. 못 세는 것은
   못 고친다. 앞 핸드오프 `2026-08-13-the-alias-path-was-never-switched-on.md` 참조.
4. **`substance abuse` 등 반복 누락 4종** — 4개 시험 공통. 체계적이라 규칙 하나로 여러 건
   회수 가능.
5. **`tte_service.py`가 프로토콜 원문을 버린다** (`source_text = entity_text`).
   실측: 원문 형태 `eGFR < 60 (Cockcroft-Gault)`는 gold **5/5**, 맨 `eGFR`은 0/5.
   전략적으로 더 큰 수정이지만 모든 기준의 질의를 바꾸므로 blast radius 미측정. 별건.
6. **대시보드 재생성 여부 결정.** `scripts/build_conceptset_dashboard.py`가 어느 JSON을
   읽는지 확인하고 `_rematch`를 반영할지 정할 것. 이번 세션은 안 건드렸다.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 실행환경 게이트 — 다른 무엇보다 먼저
.venv/bin/python -m pytest tests/test_environment_matches_requirements.py -q

# 이번 세션 신규 테스트
.venv/bin/python -m pytest \
  tests/test_query_expander.py \
  tests/test_mapping_candidate_provenance.py \
  tests/test_intervention_mesh_alias_wiring.py \
  tests/test_conceptset_overlap_eval.py -q -p no:randomly

# 전체 (기준선: 100 failed / 2118 passed / 10 skipped)
.venv/bin/python -m pytest tests/ -q -p no:randomly
```

**약어 확장이 실제 검색기에서 먹는지** (캐시 off 필수, MedCPT 워밍업 ~30초):

```bash
CRITERION_CACHE_ENABLED=false EMBEDDING_MODEL=medcpt .venv/bin/python -c "
from src.agents.agent2.query_expander import QueryExpander
from src.agents.agent2.retriever import ConceptRetriever
GOLD = {40771922, 46236952, 3029859, 3053283, 3049187}
qe, r = QueryExpander(), ConceptRetriever()
q = qe.expand('eGFR', domain_hint='Measurement')
ids = [c.concept_id for c in r.batch_search([q], n_results=60, domain_hints=['Measurement'])[q]]
print(repr(q), 'gold', len(GOLD & set(ids)), '/5')
"
# 기대: 'estimated glomerular filtration rate' gold 5 /5
```

**MeSH 별칭 경로가 프로덕션에서 살아 있는지:**

```bash
docker exec -i artemis-api python -u - <<'PY'
import sys; sys.path.insert(0,'/app')
from src.services.tte_service import TTEService
from src.services.tte_store import TTEStore
svc = TTEService(TTEStore('/app/tmp/tte/studies.json'))
for sid in (8, 2):
    s = svc.store.get_study(sid)
    terms = (s.get('trialMetadata') or {}).get('interventionMeshTerms') or []
    seed = (s.get('eligibility') or {}).get('targetCohortName')
    print(sid, repr(seed), terms, '->', svc._alias_ingredient_mapping(seed, terms) is not None)
PY
# 기대: 8 'BI 10773' ['empagliflozin'] -> True   /   2 'ticagrelor' [...] -> False (거부가 정답)
```

**arm 전체 재현** (캐시 warm 기준 수 분, cold면 3시간):

```bash
docker exec artemis-api python -u /app/scripts/backfill_intervention_mesh_terms.py \
  /app/tmp/<arm>/studies.json --cache-dir /app/data/nct_cache --apply
docker exec -d -e TTE_STORE_PATH=/app/tmp/<arm>/studies.json artemis-api sh -c \
  'python -u /app/scripts/regenerate_structured_expression.py --apply > /app/output/<arm>.log 2>&1'
.venv/bin/python scripts/export_circe_from_store.py --store tmp/<arm>/studies.json --out output/circe_<arm>
.venv/bin/python scripts/conceptset_overlap_eval.py --mode closure \
  --generated-dir output/circe_<arm> --out output/conceptset_overlap/scoped_<arm>_rematch.json
```

## Gotchas / constraints

- 🔴 **warm criterion 캐시가 매핑 수정을 통째로 가린다.** 캐시 키가 **확장 전** seed로
  만들어지고 매핑 메타데이터를 통째 저장·재생하므로, 고친 뒤 재실행해도 옛 개념 집합이
  나와 **"효과 없음"으로 읽힌다.** 두 workflow가 독립적으로 경고했고 이번 세션 내내 warm
  캐시를 썼으니 밟기 직전이었다. 측정할 땐 `CRITERION_CACHE_ENABLED=false` 또는 새
  `CRITERION_CACHE_DB_PATH`.
- **`scoped_*.json`(구 채점기)과 `scoped_*_rematch.json`(신 채점기)을 같은 표에 올리지
  말 것.** arm 비교는 `_rematch`끼리.
- **`MappingCandidateItem.score`를 확률로 읽거나 기준 간 비교하지 말 것.** 질의별
  정규화된 `adjusted_score`에서 유도한 **한 기준 내 상대 순위**다. `None`은 KG/ATC
  확장 유래로 점수가 없다는 뜻이며 "낮다"와 다르다.
- **`artemis/tmp/`는 root 소유** (컨테이너가 bind mount에 root로 씀). 호스트에서 store를
  못 고치니 백필은 `docker exec`로.
- **하네스가 별칭 없는 스터디를 크게 경고한다.** 그 경고가 뜬 실행의 진입약물 결과는
  믿지 말 것.
- **임베딩 경로는 실행 간 비결정적이다** (CAROLINA `glimepiride` 3개 ↔ 4개).
  1뽑기로 ±0.02 미만 델타를 주장하지 말 것.
- **`_CURATED_EXPANSIONS`에 행을 추가하려면 먼저 측정할 것.** 14개 중 2개는 확장이
  악화시킨다. 6자 길이 게이트가 그 둘을 막고 있으니 게이트를 넓히지 말 것.
- **`omx_wiki/index.md`는 병렬 세션의 미커밋 상태**였다. 루트 저장소에서 다른 세션이
  작업 중이니 커밋 전 `git log` 확인. (이번 세션 중 그 세션이 `b437d20`~`e392ce1` 4건을
  커밋했다.)
- 이 저장소는 **remote가 없다** — `gh pr` 계열은 쓸 수 없다.
