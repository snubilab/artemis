# Handoff — 매처는 틀렸고, 결론은 바뀌지 않았다 — 2026-08-13

## Goal / context

`2026-08-13-atc-class-gate-and-a-scorer-that-mispairs.md`의 D1~D3을 닫는다.
그 문서는 채점기가 gold `[TROY intervention] DPP4 inhibitors`를 생성 집합
`SGLT-2 inhibitors`에 붙이는 것을 발견하고 **"지금까지의 모든 판단이 그 채점기 숫자
위에 서 있다"**고 경고했다. 이번 세션은 그 결함을 세고, 고치고, 과거 arm을 다시 채점했다.

**결론부터: 결함은 실재했지만 매크로 수치를 의미 있게 왜곡하지 않았다.** ATC 수정의
효과는 +0.017에서 +0.018로, 5/6 시험 동일 방향이라는 성질까지 그대로다. 앞 세션이
"과소평가"를 의심한 것은 합리적이었으나 **사실이 아니었다**.

## Current state

- 브랜치 `fix/tte-a-drug-anchored-entry` · HEAD `93f3c62` · **이번 세션 커밋 없음**
  (이전 세션들의 미커밋 변경이 그대로 남아 있다 — 섞지 말 것)
- 이번 세션이 건드린 파일:
  ```
   M scripts/conceptset_overlap_eval.py     매처 수정 (아래 3가지)
   M tests/test_conceptset_overlap_eval.py  신규 테스트 11건 (15 → 26)
   M todolist/20260812_232657_atc_threshold_and_remap.md   D1~D3 마감
  ?? docs/handoff/2026-08-13-the-matcher-was-wrong-and-it-did-not-matter.md
  ?? output/conceptset_overlap/scoped_{gate,scale,atc}_fix_rematch.json
  ```
- 테스트: **100 failed / 2093 passed** (기준선 100/2082 + 신규 11). 회귀 0.
  실패 100건은 기존과 동일하며 `test_conceptset_overlap_eval.py`는 0건.
- 베이스라인 보존: `scoped_{gate,scale,atc}_fix.json`은 손대지 않았다.
  재채점 결과는 `_rematch` 접미사로 따로 썼다.

## Done this session

### D2 — 오짝짓기 건수: 232개 gold 중 결정적 3건

기존 채점 JSON만으로(DB·재해석 없이) 짝짓기 결정을 다시 밟았다. 판정을 세 갈래로 나눴다:

| 분류 | 뜻 | atc_fix | scale_fix | gate_fix |
| --- | --- | --- | --- | --- |
| 결정적 | 이름만으로 이김 (`>= name_strong`, jaccard 불필요) | **3** | **3** | **2** |
| 신규 적격 | 정규화가 새로 약한 증거로 승격시킴 (jaccard 의존) | 3 | 3 | 2 |
| 미결 | 0.25~0.50 구간, JSON만으로는 판정 불가 | 9 | 9 | 10 |

결정적 3건 (atc_fix / scale_fix 동일):

1. CARMELINA `[TROY intervention] DPP4 inhibitors` → `SGLT-2 inhibitors`(0.250)가
   아니라 `DPP-4 inhibitor`(1.000)
2. CARMELINA `[TROY intervention] Sulfonylureas` → 짝 없음이 아니라 `Sulfonylurea`(1.000)
3. CAROLINA `[TROY drugs] DPP4 inhibitors (excluding linagliptin)` → `DPP-IV
   inhibitors`(overlap)가 아니라 `DPP-4 inhibitors`(0.500)

**이것이 D2의 답이다: 같은 결함이 비교 대상 두 arm에 똑같이 3건씩 들어 있다.**
뺄셈의 양쪽에 동일하게 존재하는 편향은 상쇄된다. 왜곡된 것은 델타가 아니라 절대 수준이다.

### D1 — 매처 수정 3가지

`scripts/conceptset_overlap_eval.py`:

1. **문자-숫자 사이 구두점 접기.** `_LETTER_DIGIT_PUNCT`. `DPP-4` → `dpp4`.
   문자 뒤·숫자 앞의 구두점만 접는다. `4-ESRD`(숫자 뒤 문자)와 `DPP-IV`(숫자 없음)는
   그대로 둔다.
2. **단순 복수형 접기.** `_depluralize`. `inhibitors` → `inhibitor`.
   `ss`/`us`/`is` 어미는 건드리지 않는다(`loss`, `mellitus`, `stenosis`).
   비교 양쪽에 똑같이 적용되므로 `diabetes` → `diabete` 같은 과잉 접기는 무해하다.
3. **범주 명사 단독 매칭 금지.** `_GENERIC_TOKENS = {disease, disorder, drug, inhibitor}`.
   공유 토큰이 범주 명사뿐이면 `name_similarity`가 0.0을 돌려준다.

3번은 예정에 없던 것이고, **2번이 만든 회귀를 잡느라 생겼다** — 아래 참조.

### D3 — 과거 arm 3개 재채점

| arm | recall | precision |
| --- | --- | --- |
| gate_fix | 0.600 → **0.607** | 0.520 → **0.532** |
| scale_fix | 0.611 → **0.614** | 0.557 → **0.565** |
| atc_fix | 0.625 → **0.632** | 0.558 → **0.568** |

arm 간 델타 (수정된 채점기 기준):

| 비교 | 기존 보고 | 재채점 후 |
| --- | --- | --- |
| gate → scale | +0.011 | +0.007 |
| scale → atc | **+0.017** | **+0.018** (5/6 동일 방향, 0 역방향) |

scale → atc 시험별: ARISTOTLE +0.008 · CARMELINA +0.077 · CAROLINA +0.017 ·
EMPA-REG +0.002 · LEADER +0.003 · PLATO 0.000.

**±0.02 해상도 규칙은 여전히 유효하다.** +0.018은 그 아래이므로 크기가 아니라
방향 일치(5/6, 역방향 0)가 근거다. 이 성질이 재채점 후에도 보존되었다는 것이 요점이다.

## Key decisions & why

- **`0.9` 같은 숫자를 앞 단어에 붙이는 접기를 기각했다.** 초안은 모든 숫자 토큰을 앞
  토큰에 붙였고, 그러면 LEADER `Ankle brachial index less than 0.9`의 `than 0` 이
  `than0`으로 합쳐지며 합집합이 7→6으로 줄어 `Ankle-brachial index`와의 유사도가
  0.429 → 0.500으로 **임계값을 넘는다**. 짝은 맞지만 이유가 틀렸다 — 개념이 일치해서가
  아니라 쓰레기 토큰 두 개가 하나로 합쳐져서 오른 값이다. 문자-숫자 경계만 접는
  방식으로 바꿨고, 이 사례가 **고쳐지지 않는다는 것**을 테스트로 박아 두었다
  (`test_should_leave_a_numeric_threshold_qualifier_unmatched`). 숫자 한정어 제거는
  별도 근거를 갖춘 별도 변경이다.
- **`disease`를 불용어로 넣었다가 되돌렸다.** 복수형 접기가 `diseases` → `disease`를
  만들면서 gold `diseases of the blood`가 `Chronic disease`(0.333)에 붙어
  recall 0.066 → 0.005로 떨어졌다. 불용어로 통째 제거하면 이 두 건은 고쳐지지만,
  EMPA-REG `coronary atherosis and other chronic ischemic heart disease` ↔
  `Coronary Artery Disease`(recall 1.00)라는 **맞는 짝이 깨진다** — 거기서는
  `disease`가 `coronary`와 함께 정당한 증거이기 때문이다. 그래서 토큰은 남기되
  **단독으로는 증거가 되지 못하게** 하는 좁은 규칙으로 바꿨다. 세 사례가 모두 맞다.
- **CAROLINA `DPP4 inhibitors (excluding linagliptin)`가 scale_fix에서 나빠지는 것을
  받아들였다.** `DPP-IV inhibitors`(rec 0.451)에서 이름이 정확히 같은
  `DPP-4 inhibitors`(rec 0.162)로 옮겨간다. 파이프라인이 겹치는 DPP-4 집합을 둘
  만들었고, **점수가 높은 쪽이 아니라 이름이 같은 쪽에 붙이는 것이 정직한 측정**이다.
  점수가 좋은 상대를 고르는 매처는 성적 부풀리기다. atc_fix에서는 같은 규칙이
  0.451 → 0.549로 좋아진다.
- **테스트는 관측값으로 썼다.** 앞 세션의 ATC 임계값 테스트와 같은 이유다. 결함이
  "경계를 어디 두었나"에 있으므로 합성값으로는 재현되지 않는다. 실패 재현 테스트
  (`test_should_pair_the_observed_dpp4_gold_with_the_gliptin_set_not_the_sglt2_set`)는
  유사도 숫자가 아니라 **짝짓기 메커니즘**을 재현한다 — SGLT-2가 공유 개념 하나만
  있으면 0.25가 이름 증거로 승격되어 gliptin 집합의 overlap 매칭을 이긴다.
- **기존 테스트를 통과시키려고 느슨하게 만들지 않았다.**
  `test_should_keep_a_shared_class_noun_below_strong_name_evidence`는 "약한 증거로
  남아 jaccard가 막는다"를 전제했는데, 새 규칙은 아예 증거가 되지 않게 만든다.
  전제가 강화된 것이므로 이름을 바꾸고 **더 강한 보장**을 검증하도록 옮겼다
  (`test_should_give_no_name_evidence_when_only_a_drug_class_noun_is_shared`).

## Next steps (ordered, concrete)

1. **대시보드 재생성.** `scripts/build_conceptset_dashboard.py`가 어느 JSON을 읽는지
   확인하고 `_rematch`를 반영할지 결정할 것. 이번 세션은 대시보드를 건드리지 않았다.
2. **`_rematch`를 정식 파일로 승격할지 결정.** 지금은 베이스라인 보존을 위해 병렬로
   두었다. 앞으로의 arm은 수정된 채점기로 채점되므로, 과거 파일과 섞이면 비교가
   깨진다. **`scoped_*.json`(구 채점기)과 `scoped_*_rematch.json`(신 채점기)을
   같은 표에 올리지 말 것.**
3. **`top_n=3 → 5`가 다음 파이프라인 arm.** 앞 핸드오프의 씨앗 실험 근거 그대로
   (A 62.7% → B 72.9%). precision 영향이 미측정이므로 재매핑으로 확인할 것.
4. **`standard_concept` 재색인.** 미착수. ChromaDB `omop_concepts_medcpt` 메타데이터에
   키가 없어 `retriever.py`의 표준 개념 선호(−0.10/+0.15)가 한 번도 실행된 적이 없다.
   벡터는 두고 메타데이터만 갱신할 수 있는지부터 확인할 것.
5. **UMLS MRREL SQLite 부재.** 약물 클래스 확장의 1번 전략이 죽어 있고 ATC가 유일한
   경로다. 빌드하면 두 번째 경로가 생긴다.
6. **미결 9건은 열어 둔 채로 남는다.** 0.25~0.50 구간은 JSON만으로 판정할 수 없다
   (jaccard가 필요한데 요약 JSON에는 개념 ID가 없다). 필요하면 해석된 집합으로
   다시 볼 것. 다만 D3 재채점이 실제 짝 변화를 전부 보여줬고 그중 나빠진 것은
   위에 적은 정당한 탈락뿐이었으므로, 우선순위는 낮다.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 실행환경 게이트 — 다른 무엇보다 먼저
.venv/bin/python -m pytest tests/test_environment_matches_requirements.py -q

# 이번 세션 테스트 (26 passed)
.venv/bin/python -m pytest tests/test_conceptset_overlap_eval.py -q -p no:randomly

# 전체 (기준선: 100 failed / 2093 passed)
.venv/bin/python -m pytest tests/ -q -p no:randomly

# 수정 확인 — DPP4가 올바른 상대에 1.000으로 붙는지
.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from scripts.conceptset_overlap_eval import normalize_set_name, name_similarity
g='[TROY intervention] DPP4 inhibitors'
for c in ('DPP-4 inhibitor','SGLT-2 inhibitors'):
    print(f'{c:20} {sorted(normalize_set_name(c))}  name_sim={name_similarity(g,c):.3f}')
"
# 기대: DPP-4 inhibitor ['dpp4','inhibitor'] 1.000 / SGLT-2 inhibitors 0.333
```

**재채점 (재매핑 불필요, CIRCE는 이미 있음, arm당 약 5초):**

```bash
.venv/bin/python scripts/conceptset_overlap_eval.py --mode closure \
  --generated-dir output/circe_atc_fix \
  --out output/conceptset_overlap/scoped_atc_fix_rematch.json
```

## Gotchas / constraints

- **`scoped_*.json`과 `scoped_*_rematch.json`을 섞어 비교하지 말 것.** 채점기가 다르다.
  구 파일은 베이스라인 보존용으로만 남겨 두었다.
- **`recall_mean`의 분모는 짝이 지어진 쌍의 수다.** 매처를 고치면 분자와 분모가 같이
  움직인다(`Sulfonylureas`가 짝을 얻어 평균에 합류하고, `Chronic disease` 쓰레기 짝은
  빠진다). arm 비교 시 `matched_pairs` 수를 같이 볼 것 — D3 표에 넣어 두었다.
- **`name_similarity`는 이제 범주 명사만 공유하면 0.0을 돌려준다.** JSON의 `name_sim`
  0.0이 "이름이 전혀 안 겹침"과 "범주 명사만 겹침" 두 가지를 뜻하게 되었다.
  이 함수를 쓰는 곳은 채점기 내부뿐이다(대시보드 스크립트들은 쓰지 않는다).
- **`artemis/tmp/`는 root 소유다.** 컨테이너가 bind mount에 root로 쓴다. 호스트에서
  쓰려면 다른 경로를 쓸 것. 이번 세션은 `output/`(gitignore됨)에 임시 스크립트를 두고
  끝나고 지웠다.
- **`omx_wiki/index.md`는 병렬 세션의 미커밋 상태다.** 루트 저장소에서 다른 세션이
  작업 중이니 커밋 전 `git log`를 확인할 것.
- **±0.02 해상도 규칙은 여전히 유효하다.** 1뽑기로 작은 델타를 주장하지 말 것.
