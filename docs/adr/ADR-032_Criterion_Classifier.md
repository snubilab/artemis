# ADR-032: Criterion Classifier (기준 문장 임계값 분류기)

**상태**: 제안됨 (Proposed) — 설계만, 구현 없음
**날짜**: 2026-07-29
**의사결정자**: @kyh
**관련**: ADR-031(값 조건 의미 보존), ADR-031-A(이환 기간), ADR-030(사이트별 적응 계층), ADR-016(ThreadPoolExecutor 결정적 순서), ADR-017(Agent1 역할 축소), `docs/daily_notes/tte_value_taxonomy.json`, `docs/daily_notes/tte_related_work.json`

## 컨텍스트

파이프라인은 세 단계다.

```
1. decompose (LLM)   적격기준 원문 -> 원자 기준            [기존: src/agents/agent1/]
2. classify  (LLM)   기준 -> 구문별 {class, head, phrase}  [본 ADR]
3. structure (code)  구문 -> Circe                         [기존: src/services/value_constraint.py]
```

3단계는 동작한다. `normalize_unit()`과 `build_measurement_value_filter()`가 `ValueAsNumber`+형제 `Unit`, `RangeHighRatio`, `RangeLowRatio`를 낸다. 본 ADR의 산출물은 그 입력이므로, 계약은 3단계가 **그대로 소비할 수 있는 것**이어야 한다.

2단계가 LLM인 이유는 ADR-031 D2와 `tte_related_work.json`이 이미 정했다. Chia는 숫자를 **단위가 아니라 head(그 숫자가 수식하는 대상)** 로 분류하고, head 식별은 의미 판단이다. 정규식으로 head 규칙을 코퍼스에 적용하려던 시도는 `ALT, AST, or alkaline phosphatase > 3x ULN`을 `or`로 쪼개면서 head를 날려 값 조건의 62%밖에 해소하지 못했다.

### 이 단계의 실패는 조용한 0이 아니다 (설계를 바꾼 사실)

ADR-031과 ADR-031-A의 실패 모드는 전부 **조용한 0**이었다 — 잘못된 필터가 아무 행과도 안 맞아 코호트가 빈다. 2단계의 지배적 실패는 반대다.

| 실패 | 결과 | 발견 가능성 |
|---|---|---|
| 구문을 **누락** | 그 조건이 코호트에서 사라짐 → 환자 **과다** 포함 | 숫자가 0이 아니고 그럴듯하다. 사실상 안 보인다 |
| 구문을 **오분류** | 잘못된 Circe 목적지 → 조용한 0 (ADR-031 계열) | 0이라도 나오면 눈에 띈다 |

실측(아래 「실측 — 다중 구문 회수」)에서 기본 프롬프트는 `LVEF < 40% measured within 6 months`에서 시간창을, `blood donation ... > 500 mL within 3 months`에서 시간창을, HIV 문장에서 4개 중 3개를 **말없이 버렸다**. 오분류보다 누락이 훨씬 흔하고 훨씬 안 보인다. 따라서 본 ADR의 방어선은 분류 정확도가 아니라 **회수(recall) 강제**에 무게가 실린다.

### 측정한 컨텍스트 예산

| 항목 | 값 | 측정 |
|---|---|---|
| 렌더된 택소노미 프롬프트 | **5,474 토큰** (216행) | `build_value_taxonomy.py --prompt` → vLLM `/tokenize` |
| 지시 tail (본 ADR D3) | 152 토큰 | 동일 |
| `max_model_len` | 16,384 | 서버 설정 |
| 캐시된 프로토콜 | 729건 | `data/nct_cache/*.json` |
| 적격기준 원문 | 중앙값 802자, 최대 13,926자 = **3,143 토큰** | 동일 |
| 기준 행 | 10,940행, 중앙값 58자, 최대 1,969자 = **421 토큰** | 동일 |
| 구문당 출력 | **~54 토큰** (5구문 행 = 272 토큰) | 실측 |

과제 설명의 "가장 큰 스터디 9,200 토큰"은 이 워크스페이스에서 재현되지 않았다. `data/cache/agent1_ir/`의 6개 저장 스터디 중 최대는 908 토큰이고, 원본 CT.gov 캐시 729건의 최대는 3,143 토큰이다. 아래 D2는 **9,200을 그대로 인정해도** 성립하도록 산수를 해 둔다.

### 측정한 head 생략 빈도

과제 설명은 "부모 불릿에 검사명, 자식 불릿에 임계값만"이 얼마나 흔한지 모른다고 했다. 원문 채널에서는 측정 가능하다.

| 지표 | 값 |
|---|---|
| 임계값을 가진 행 (비교연산자 + 숫자) | 1,716 |
| 비교연산자·숫자·단위를 제거하면 아무 단어도 남지 않는 행 | **2 (0.1%)** — `<50 years`, `< 18 years,` |
| 비교연산자로 시작하는 행 (10,940행 중) | 20 (0.18%) |

**즉 ClinicalTrials.gov 원문에서 head 생략은 희소하다.** 위험은 CT.gov 서식이 아니라 **1단계가 문장을 쪼개는 순간** 생긴다(`ALT, AST, or ALP > 3x ULN` → `or`로 분해). 이 채널은 여기서 측정할 수 없다. 결론은 바뀌지 않는다 — 방어는 여전히 필요하고, **비용이 0.1%로 측정됐으므로 방어를 켜지 않을 이유가 사라졌다.**

## 결정

### D1. 인터페이스 계약 — 기준당 구문 리스트, 새 IR 타입 하나

```python
# src/models/ir.py — ValueConstraint 바로 옆
SpanClass = Literal[
    "MEASUREMENT_VALUE", "AGE", "TEMPORAL_WINDOW", "STATE_DURATION",
    "DRUG_DOSE", "SCORE_GRADE", "EVENT_QUANTITY", "REVIEW", "NON_CRITERION",
]

class ThresholdSpan(BaseModel):
    threshold_phrase: str            # 기준 원문의 축자 부분문자열
    head: Optional[str]              # 숫자가 수식하는 대상, 축자. 없으면 None
    span_class: SpanClass
    family: Optional[str] = None     # span_class == NON_CRITERION 일 때만
    origin: Literal["model", "recall_net"] = "model"
    review_reason: Optional[str] = None   # REVIEW로 강등한 게이트 이름
```

```python
# src/agents/agent1/threshold_classifier.py  (신설, 본 ADR 범위 밖 = 미구현)
def classify_criterion(text: str, llm: BaseChatModel | None = None) -> list[ThresholdSpan]
def classify_criteria(texts: Sequence[str], llm=None) -> list[list[ThresholdSpan]]
```

`Criteria`에 `source_text: Optional[str]`을 추가한다. 현재 `Criteria`는 `name`/`entity_text`만 갖고 **원문 행을 보존하지 않는다.** 분류기는 원문 행을 입력으로 받으므로 이 필드 없이는 호출할 수 없다.

**3단계 연결 — 새 API를 만들지 않는다.**

```python
for span in spans:
    if span.span_class != "MEASUREMENT_VALUE":
        continue
    for vc in parse_value_constraints(span.threshold_phrase):   # ADR-031 D3, 이미 선언됨
        criteria_attrs.update(build_measurement_value_filter(vc))
```

`parse_value_constraints(text) -> list[ValueConstraint]`는 ADR-031 D3가 이미 시그니처까지 정해 두고 `NotImplementedError`로 막아 둔 자리다. 2단계의 출력은 **그 함수의 입력 형태와 정확히 같다** — 축자 구문 문자열. 즉 경계는 새로 설계할 것이 없다.

MEASUREMENT_VALUE가 아닌 구문의 목적지: `AGE`→`DemographicCriteria.Age`, `TEMPORAL_WINDOW`→`StartWindow`, `STATE_DURATION`→ADR-031-A D1 fragment, `DRUG_DOSE`→`DrugExposure`, `SCORE_GRADE`→`ValueAsNumber`(Unit 없이) 또는 `ValueAsConcept`, `EVENT_QUANTITY`→미구현, `REVIEW`/`NON_CRITERION`→아래 D8.

**선결 조건**: Agent 1의 프롬프트는 현재 "ALL Measurement criteria MUST include `value_constraint`"를 요구한다(`src/agents/agent1/prompts.py`). 2단계를 넣으려면 그 요구를 **제거**해야 한다. 두 곳이 같은 값을 만들면 진실이 둘이 되고, 어느 쪽이 이겼는지 기록되지 않는다.

### D2. 호출 단위는 기준 한 개 — 스터디 단위 금지

| 단위 | 최악 입력 | 출력 여유 | 실패 반경 |
|---|---|---|---|
| 기준 1개 | 5,474 + 152 + 421 = **6,047** | 10,337 | 기준 1개 |
| 스터디 1개 (실측 최대) | 5,474 + 152 + 3,143 = **8,769** | 7,615 | 스터디 전체 |
| 스터디 1개 (과제 설명의 9,200) | 5,474 + 152 + 9,200 = **14,826** | **1,558** | 스터디 전체 |

마지막 행이 결정적이다. 구문당 출력이 실측 ~54 토큰이므로 1,558 토큰은 **약 29구문**이다. 코퍼스에서 한 행이 최대 5구문을 실었고 스터디 중앙값이 13행이므로, 밀도 높은 스터디는 이 한도를 넘는다. 넘으면 JSON이 중간에서 잘린다 — 첫 실행에서 실제로 관측했다(5구문 행, `finish_reason` 절단, 문자열 중간에서 종료). 잘린 JSON은 파싱 실패이고, 스터디 단위에서는 **그 스터디의 모든 구문이 함께 사라진다.**

비용 논거는 성립하지 않는다. 5,474 토큰 prefix를 매번 다시 보내는 값을 측정했다.

```
full-5474tok   ['4.59', '4.65', '4.68']  min=4.59s
tiny-11tok     ['4.59', '4.33', '4.30']  min=4.30s
full-again     ['4.68', '4.67', '4.69']  min=4.67s
```

**택소노미 전체를 매 호출에 붙이는 비용은 0.3초다.** 지연은 prefill이 아니라 decode가 지배한다. 따라서 배치의 유일한 실질 이득이 사라지고, 배치의 손실(한 구문의 파싱 실패가 이웃을 죽인다)만 남는다.

시스템 메시지에 택소노미를, 사용자 메시지에 기준을 둔다. 시스템 메시지는 호출 간 **바이트 동일**이므로 vLLM automatic prefix caching이 적용될 수 있다. 위 측정은 그것이 켜져 있든 아니든 결론이 같음을 보인다.

병렬화는 새로 만들지 않는다. ADR-016의 `ThreadPoolExecutor` + 결정적 순서 패턴을 그대로 쓴다. 중앙값 13기준 스터디는 직렬 ~55초, 8워커 ~10초다.

### D3. 프롬프트 = 렌더러 출력 + 고정 tail, 입력은 반드시 de-escape

프롬프트 본문은 `scripts/build_value_taxonomy.py --prompt`의 출력을 **한 글자도 고치지 않고** 쓴다. 그 렌더러는 택소노미 JSON의 순수 함수이므로 동기화할 사본이 생기지 않는다(`meta.prompt_contract.invariant`). 배포 형태: `--prompt`의 출력을 `docs/daily_notes/tte_value_taxonomy.prompt.txt`로 체크인하고, `--check`가 체크인된 파일과 즉석 렌더 결과의 일치를 검사한다. 분류기 모듈은 `scripts/`를 import하지 않고 그 텍스트 파일만 읽는다.

**입력 de-escape는 선택이 아니다.** ClinicalTrials.gov는 비교연산자를 `\>` `\<` `=\>` `=\<`로 escape한다. "축자로 복사하라"는 지시와 결합하면 모델이 JSON 문자열 안에 `"\<"`를 쓰고, 이는 유효하지 않은 escape sequence여서 `json.loads`가 죽는다. 실측:

| 입력 | 13케이스 중 JSON 파싱 성공 |
|---|---|
| CT.gov escape 그대로 | **5 / 13** |
| `text.replace("\\", "")` 후 | **13 / 13** |

파싱 실패 8건은 전부 분류 자체는 옳았다. 즉 이것은 모델 품질 문제가 아니라 **입력 형식과 출력 형식의 충돌**이며, 호출 앞단 한 줄로 사라진다. escape 복원은 필요 없다 — ADR-031 D5의 `_clean()`이 3단계에서 어차피 backslash를 제거한다.

지시 tail 전문 (본 ADR에서 유일하게 손으로 쓴 프롬프트 조각):

```
HEAD IS REQUIRED
  head must be a verbatim substring of the CRITERION below -- copy it, never paraphrase
  and never supply a word the text does not contain.
  If the criterion does not name what the number measures, set head to null and class to
  "REVIEW". A parent bullet you cannot see is not a licence to guess.
  Do NOT supply "age" as a head for a bare unit. If the text does not say age/aged/years
  old, it is not an AGE span.

EVERY NUMERAL
  Every number in the CRITERION must appear in exactly one span, including numbers you
  think are irrelevant. If a number is not a threshold, still emit a span for it with the
  class that says so (NON_CRITERION with its family, or REVIEW). Do not skip it.

Answer with one JSON object and nothing else:
{"spans": [{"threshold_phrase": "...", "head": "..." or null, "class": "...", "family": null}]}
```

few-shot은 **추가하지 않는다.** 렌더러가 이미 클래스마다 `example_ids`의 코퍼스 예시를 붙인다(23개 항목). 손으로 예시를 더 넣으면 (a) 평가셋 유출이 커지고 (b) 택소노미 JSON 바깥에 두 번째 진실이 생긴다. 어떤 예시를 쓰는지에 대한 답은 "택소노미가 고른 23개, 그 이상 없음"이고, 그 대가는 D9에 정량화돼 있다.

### D4. `confidence` 필드를 버린다

택소노미의 `meta.output_schema`는 `confidence: "high" | "low"`를 선언한다. 채택하지 않는다.

8B 모델에게 자기 확신도를 라벨로 달라고 하면 대체로 잡음이 나오고, 더 나쁜 것은 **그 라벨이 REVIEW를 우회하는 통로가 된다는 점**이다 — 모델이 `{class: "AGE", confidence: "low"}`를 내면 파이프라인은 "일단 AGE로 두되 표시" 같은 타협을 하게 되고, 표시는 곧 무시된다.

대신 **구조 신호**를 쓴다. 확신도는 모델이 말하는 것이 아니라 **답의 형태에서 코드가 읽어내는 것**이다.

| 신호 | 코드가 검사 가능한가 | 무엇을 뜻하는가 |
|---|---|---|
| `head`가 null | 예 | 모델이 대상을 못 찾았다 |
| `head`가 원문에 없음 | 예 (부분문자열) | 모델이 지어냈다 |
| `head`가 피연산자 영역 안 | 예 (D5 게이트2) | 모델이 단위를 head 칸에 넣었다 |
| 숫자가 어느 구문에도 안 잡힘 | 예 (D6) | 모델이 구문을 버렸다 |

넷 다 결정적이고, 넷 다 모델의 자기평가에 의존하지 않는다.

### D5. 검증 게이트 — 전부 REVIEW로 수렴, 클래스로 수렴하는 경로 없음

호출 결과는 아래 순서로 통과해야 한다. 실패의 결과는 **항상 REVIEW이며, 결코 다른 클래스가 아니다.**

| # | 게이트 | 실패 시 |
|---|---|---|
| G0 | JSON 파싱 | 1회 재시도 → 실패면 기준 전체를 `REVIEW` 한 구문으로 |
| G1 | **headless 사전 검사 (모델 답을 읽기 전)** | 기준의 모든 구문을 `REVIEW`. 모델 답 폐기 |
| G2 | `span_class`가 enum 안 / `family`가 NON_CRITERION 계열 안 | 해당 구문 `REVIEW` |
| G3 | `threshold_phrase`가 기준의 부분문자열 (escape·공백·대소문자 정규화 후) | 해당 구문 `REVIEW` |
| G4 | `head`가 부분문자열 **이면서 피연산자 영역 밖** | 해당 구문 `REVIEW` |
| G5 | `span_class == "AGE"`이면 원문에 age 어휘(`age/aged/years old/year-old/older/younger/adult`)가 있어야 함 | 해당 구문 `REVIEW` |
| G6 | 구문끼리 원문 위치가 겹치지 않음 | 긴 쪽만 남기고 짧은 쪽 폐기 |
| G7 | **숫자 회수** (D6) | 안 잡힌 숫자마다 `REVIEW` 구문 합성 |

**G1이 이 설계의 핵심이다.** 정의:

> 기준에서 비교연산자, 숫자, 그리고 `normalize_unit()`이 해소하는 단위 철자를 제거했을 때 알파벳이 하나도 남지 않으면 그 기준은 headless다.

```
"> 1500/mm3"      -> "/"      -> headless  (mm3는 단위 8785)
"< 100,000/mm3"   -> "/"      -> headless
">= 6 months"     -> ""       -> headless  (months는 단위 9580)
"at least 18 years old"          -> "old"   -> headless 아님
"Adequate organ function, ... ANC > 1500/mm3" -> 다수 -> headless 아님
```

위치를 쓰지 않는 것이 중요하다. "비교연산자 앞에 단어가 없으면 headless"라는 더 단순한 규칙은 1,511행 중 38행(2.5%)을 잡는데, 그중 대부분이 `at least 18 years old`, `≤ 40 years of age` 처럼 head가 뒤에 오는 **정상적인 AGE 문장**이다. 단위 인지 규칙으로 바꾸면 1,716행 중 **2행(0.1%)** 만 걸린다. 즉 G1의 오탐 비용이 측정됐고, 무시할 수 있다.

G1은 모델 호출 **전에** 돌 수도 있다(호출을 아예 건너뛰고 REVIEW). 호출 후에 돌리는 편이 관측 가치가 있으므로(모델이 무엇을 지어냈는지 로그에 남는다) 순서는 호출 후로 정하되, 판정은 모델 답과 무관하다.

G4가 필요한 이유는 실측이다. 아래 「실측 — head 요구 제거」 참조: head 요구를 빼면 모델은 AGE로 가지 않고 **단위를 head 칸에 넣는다**(`head: "mm3"`, `head: "months"`). 이는 부분문자열 검사를 통과한다. 피연산자 영역 밖 조건이 이것을 잡는다. 반대로 `White blood cell count <3×10^9/L`처럼 head가 `threshold_phrase` 안에 있으면서 정당한 경우는 통과해야 하므로, "head가 phrase 안에 있으면 안 된다"로는 쓸 수 없다 — 비교연산자 **이후** 영역만 금지한다.

### D6. 숫자 회수 검사 — 누락으로 REVIEW를 우회할 수 없게 한다

게이트 G0~G6은 전부 "모델이 낸 구문"을 검사한다. 모델이 구문을 **안 내면** 전부 통과한다. 이것이 REVIEW의 가장 넓은 우회로이고, 실측상 가장 흔한 실패다.

> 기준 안의 모든 숫자 토큰(단어 경계 기준, 과학적 표기의 밑 `10` 제외)은 정확히 한 구문의 `threshold_phrase`에 포함돼야 한다. 포함되지 않은 숫자마다 `origin="recall_net"`, `span_class="REVIEW"`, `review_reason="unclaimed numeral"` 구문을 합성한다.

숫자 토큰 정규식은 `(?<![A-Za-z\d])\d[\d,]*(?:\.\d+)?`다. 앞의 lookbehind가 없으면 `CD4`의 `4`, `HbA1c`의 `1`이 미회수 숫자로 잡힌다(첫 구현에서 실제로 그랬다).

이 검사가 만드는 성질이 설계의 요지다. **1단계가 나중에 개선되든 말든 답이 달라지지 않는다** — 부모 불릿이 없어 head가 없으면 G1이 REVIEW로 보내고, 모델이 구문을 버리면 G7이 REVIEW를 만든다. 어느 쪽도 클래스로 새지 않는다.

### D7. 재현성은 temperature·seed가 아니라 캐시가 만든다

`temperature=0` + `LLM_SEED=42`를 쓴다(이미 `get_llm`이 그렇게 한다). 3케이스 × 3회 호출에서 바이트 동일 출력을 얻었다. 다만 이것을 재현성 보장으로 기록하지 않는다.

- 측정은 **부하 없는 서버**에서 순차 호출로 이뤄졌다.
- vLLM의 continuous batching은 배치 구성에 따라 reduction 순서가 달라질 수 있고, 그러면 동일 요청이 다른 logit을 낼 수 있다. `temperature=0`은 분산을 줄이지 argmax의 동일성을 보장하지 않는다.

따라서 회귀 검증이 의존하는 것은 **콘텐츠 주소 캐시**다. Agent 1이 이미 쓰는 패턴을 그대로 쓴다 — `data/cache/agent1_ir/{NCT}_{model}_{hash}.json`. 키는 `sha256(prompt_text + criterion_text + model_id)`. 같은 입력은 같은 파일을 읽으므로 파이프라인 전체가 결정적이 되고, 프롬프트나 택소노미가 바뀌면 해시가 바뀌어 캐시가 자동 무효화된다. 새 캐시 계층을 만들지 않는다.

### D8. REVIEW의 소비자 계약 — 3단계는 REVIEW를 볼 수 없다

REVIEW를 만들어 놓고 조용히 버리면 아무것도 안 한 것과 같다.

- `REVIEW`와 `NON_CRITERION` 구문은 **`parse_value_constraints`에 전달되지 않는다.** 3단계 진입 지점에서 `span_class == "MEASUREMENT_VALUE"`만 통과시킨다.
- `REVIEW` 구문은 기존 `GapReport`/`GapItem`(`src/models/ir.py`)에 항목으로 등록된다. 새 리포트 모델을 만들지 않는다. `reason`에 `review_reason`(어느 게이트가 강등했는지)과 `origin`을 넣는다.
- 한 기준의 구문이 **전부** REVIEW면 그 기준은 Circe에 어떤 속성도 기여하지 않는다. 이때 그 기준은 `conditional=True`(ADR-029 feasibility gating이 이미 쓰는 표시)로 두어 규칙 자체가 조용히 완화되지 않게 한다.

### D9. 평가 — 코퍼스가 말할 수 있는 것과 없는 것

코퍼스(`tests/fixtures/value_constraint_corpus.yaml`)는 114항목 / **45개 출처**다(과제 설명의 "90 protocols"는 수집 스크립트가 조회한 프로토콜 수이고, 실제 표현된 출처는 45다).

**유출 분리가 먼저다.** 렌더된 프롬프트는 코퍼스 항목 **23개**를 축자로 싣는다(`CLASSES[].example_ids` + NON_CRITERION 계열 대표). 그 23개에 대한 정확도는 상한이지 성능이 아니다. held-out은 91항목이다.

| 클래스 | 전체 | held-out |
|---|---|---|
| MEASUREMENT_VALUE | 88 | **85** |
| NON_CRITERION | 12 | **4** |
| SCORE_GRADE | 3 | 1 |
| TEMPORAL_WINDOW | 3 | 1 |
| EVENT_QUANTITY | 2 | **0** |
| AGE | 2 | **0** |
| STATE_DURATION | 2 | **0** |
| DRUG_DOSE | 1 | **0** |
| REVIEW | 1 | **0** |

**이것이 코퍼스가 말할 수 있는 것의 전부다.** 과제 설명은 "여섯 클래스가 n≤3이라 n=5 미만 클래스 정확도는 잡음"이라고 했다. 유출을 빼면 더 나쁘다 — **다섯 클래스는 held-out 사례가 0이고, 두 클래스는 1이다.** `example_ids`가 자연히 그 클래스의 **유일한** 사례를 골랐기 때문이다. 즉 얇은 클래스에 대해서는 정확도가 잡음인 것이 아니라 **정의되지 않는다.**

추가로 행 단위 유출이 2건 있다: `abs-mgdl-lower`(프롬프트)와 `neg-unit-conversion`(held-out)이 같은 `source_text`를 공유하고, `abs-gl`과 `no-unit-child-pugh`도 그렇다. held-out 4건 중 2건의 원문이 프롬프트에 인쇄돼 있다.

**정밀도(precision)는 코퍼스로 측정할 수 없다.** 코퍼스는 행마다의 **구문 목록이 아니라 구문 표본**이다. `abs-gdl-nospace`는 `<13g/dL for males and <12g/dL for females`의 앞 절반만 담고, `abs-ml-volume`은 혈액 기증 문장의 수량만 담고 시간창 절반은 **다른 시험**에서 별도 항목으로 들어와 있다(`neg-blood-donation-window`). 따라서 분류기가 코퍼스에 없는 구문을 내면 그것이 오탐인지 코퍼스의 누락인지 판정할 방법이 없다.

측정 가능한 것 / 불가능한 것:

| 지표 | 가능? | 방법 |
|---|---|---|
| 구문 회수율 (recall) | **가능** | 코퍼스 `threshold_phrase`가 어떤 출력 구문에 포함되는가 |
| MEASUREMENT_VALUE 분류 정확도 | **가능** (held-out n=85) | 클래스 일치 |
| NON_CRITERION 분류 정확도 | 약하게 (n=4) | 클래스 일치 |
| 나머지 7개 클래스 정확도 | **불가능** | held-out 0~1 |
| 정밀도 / 오탐률 | **불가능** | 코퍼스가 행별 전수가 아님 |
| head 정확도 | **불가능** | 코퍼스에 head 필드가 없다 |
| G1~G7 오탐 비용 | **가능** | 원문 캐시 729건 전수 (측정 완료: G1 = 0.1%) |

**필요한 추가 라벨링** (우선순위 순):

1. **행별 전수 구문 목록** — 기존 45개 출처의 각 `source_text`에 대해 그 행의 **모든** 임계값을 라벨링. 새 프로토콜 없이 정밀도가 측정 가능해진다. 규모: 12개 다중 구문 행 + 나머지 행의 미기록 구문.
2. **head 필드** — 항목마다 head를 축자로 추가. G4와 head 정확도가 측정 가능해진다. 114항목의 필드 하나.
3. **얇은 클래스 보강** — AGE·EVENT_QUANTITY·STATE_DURATION·DRUG_DOSE 각 최소 10건. `age_surface_coverage` 한계가 지목한 미검증 표기(`18 years of age or older`, `aged 18-75`, `N-year-old`)를 반드시 포함.
4. **부모/자식 불릿 쌍** — 1단계 분해 후의 실제 출력에서 수집. 원문에서는 0.1%이므로 원문 수집으로는 안 모인다.

**코퍼스는 수정하지 않는다.** 위 1~4는 별도 fixture로 만들고 기존 114항목의 회귀 역할은 유지한다.

## 실측

모든 수치는 `scripts/probe_criterion_classifier.py`가 낸다. 모델 `vllm/snuh/hari-q3-8b`, `temperature=0`, `seed=42`, `max_tokens=1024`.

### 실측 — 정상 동작 (13/13 파싱, 지연 3.9~6.4초)

5구문 행. 회수 5/5, 게이트 전부 통과.

```
CRITERION
White blood cell count <3×10^9/L; neutrophil count<1.5×10^9/L; platelet count<90×10^9/L;
hemoglobin below the lower limit of normal; serum creatine kinase (CK) >3×ULN
```

```json
{"spans": [
 {"threshold_phrase": "White blood cell count <3×10^9/L", "head": "White blood cell count", "class": "MEASUREMENT_VALUE", "family": null},
 {"threshold_phrase": "neutrophil count<1.5×10^9/L", "head": "neutrophil count", "class": "MEASUREMENT_VALUE", "family": null},
 {"threshold_phrase": "platelet count<90×10^9/L", "head": "platelet count", "class": "MEASUREMENT_VALUE", "family": null},
 {"threshold_phrase": "hemoglobin below the lower limit of normal", "head": "hemoglobin", "class": "MEASUREMENT_VALUE", "family": null},
 {"threshold_phrase": "serum creatine kinase (CK) >3×ULN", "head": "serum creatine kinase (CK)", "class": "MEASUREMENT_VALUE", "family": null}]}
```

네 번째 구문이 주목할 만하다 — 숫자가 없는 암묵적 배수 1(ADR-031 D6)을 구문으로 잡았다. 3단계가 `value 1.0` + `reference_bound: "lln"`을 합성할 재료가 넘어온다.

### 실측 — head 생략 (설계가 막으려는 바로 그 케이스)

| 입력 | 출력 |
|---|---|
| `> 1500/mm3` | `{"threshold_phrase": "> 1500/mm3", "head": "null", "class": "REVIEW"}` |
| `< 100,000/mm3` | `{"threshold_phrase": "< 100,000/mm3", "head": "null", "class": "REVIEW"}` |
| `>= 6 months` | `{"threshold_phrase": ">= 6 months", "head": null, "class": "REVIEW"}` |
| `Adequate organ function, defined as: absolute neutrophil count > 1500/mm3` (대조) | `{"head": "absolute neutrophil count", "class": "MEASUREMENT_VALUE"}` |

세 개 모두 REVIEW, 대조군은 정상 분류. 다만 모델이 JSON `null` 대신 **문자열 `"null"`** 을 쓴 사례가 2/3이다. 검증기는 `"null"`/`"none"`/`""`를 null로 접어야 한다. 접는 것은 관대함이 아니라 같은 뜻이다.

### 실측 — head 요구 제거 (ablation)

`HEAD IS REQUIRED` 문단만 빼고 동일 호출.

| 입력 | head 요구 있음 | head 요구 없음 |
|---|---|---|
| `> 1500/mm3` | `REVIEW`, head null | `MEASUREMENT_VALUE`, **head `"mm3"`** |
| `< 100,000/mm3` | `REVIEW`, head null | `MEASUREMENT_VALUE`, **head `"mm3"`** |
| `>= 6 months` | `REVIEW`, head null | `TEMPORAL_WINDOW`, **head `"months"`** |

예상과 달랐다. 모델은 AGE로 가지 않고 **단위를 head 칸에 넣어 요구를 형식적으로 충족시켰다.** `"mm3"`도 `"months"`도 기준의 진짜 부분문자열이므로 부분문자열 검사만으로는 통과한다. 이것이 G4(피연산자 영역 밖)와 G1(단위 인지 headless 검사)가 존재하는 이유이고, 둘 다 위 세 케이스를 잡는다.

```
'> 1500/mm3'      -> ['criterion is headless before the comparator -> all spans REVIEW (gate 1)']
'>= 6 months'     -> ['criterion is headless ... (gate 1)']
'< 100,000/mm3'   -> ['criterion is headless ... (gate 1)']
'Adequate organ function, ... absolute neutrophil count > 1500/mm3' -> accepted
'White blood cell count <3×10^9/L'                                  -> accepted
'Age >= 18 years at screening'                                      -> accepted
'LVEF < 40% measured within 6 months prior to randomization'        -> accepted
```

### 실측 — 다중 구문 회수 (모델이 실패하는 지점)

`EVERY NUMERAL` 문단 유무 비교. 미회수 숫자는 D6 검사의 출력이다.

| 기준 | 기본 tail | `EVERY NUMERAL` 포함 |
|---|---|---|
| `LVEF < 40% measured within 6 months prior to randomization` | 1구문, **미회수 `6`** | 2구문, 미회수 없음 |
| HIV 문장 (숫자 4개) | 1구문, **미회수 `1`, `150`** | 3구문, 미회수 없음 |
| `Blood donation or blood loss > 500 mL within 3 months prior to screening` | 1구문, **미회수 `3`** | 4구문(중복 1), 미회수 없음 |
| 커피 문장 | 1구문, **미회수 `1`, `250`** | 2구문, 미회수 없음 |

기본 tail은 **네 문장 모두에서 구문을 버렸다.** 이것이 이 단계의 주된 실패이고, D6의 회수 검사는 네 건 모두를 잡았다.

`EVERY NUMERAL`의 대가는 두 가지다. (a) 지연 4~5초 → 9~17초. (b) 겹치는 구문이 생긴다 — 혈액 기증 문장에서 `blood donation or blood loss > 500 mL`와 `> 500 mL`를 **둘 다** 냈고, 숫자가 없는 `prior to screening`도 구문으로 냈다. G6(겹침 제거)과 "숫자도 비교연산자도 없는 구문은 폐기"가 필요한 이유다.

### 실측 — 워크드 예제: 다중 구문 기준의 전 구간

입력(ADR-031-A의 NCT04826341, de-escape 후):

```
Patients with long-standing (>5 years) HIV on antiretroviral therapy > 1 month
(undetectable HIV viral load and CD4 count > 150 cells/microL) may be eligible
```

모델 출력 (`EVERY NUMERAL` 포함, 축자):

```json
{"spans": [
 {"threshold_phrase": ">5 years",           "head": "HIV",                    "class": "STATE_DURATION",     "family": null},
 {"threshold_phrase": "> 1 month",          "head": "antiretroviral therapy", "class": "STATE_DURATION",     "family": null},
 {"threshold_phrase": "> 150 cells/microL", "head": "CD4 count",              "class": "MEASUREMENT_VALUE",  "family": null}]}
```

게이트 통과 후 3단계로 가는 것:

| 구문 | 게이트 | 목적지 |
|---|---|---|
| `>5 years` / head `HIV` | 통과 | ADR-031-A D1 — `ConditionOccurrence` + `StartWindow{Start:{Coeff:-1}, End:{Days:1826, Coeff:-1}}` |
| `> 1 month` / head `antiretroviral therapy` | 통과 | ADR-031-A D5 — `DrugEra` + 같은 창 + `EndWindow{UseEventEnd:true}` |
| `> 150 cells/microL` / head `CD4 count` | 통과 | `parse_value_constraints` → `ValueAsNumber{Value:150, Op:"gt"}` + 형제 `Unit` |
| — | G7 | `undetectable`은 숫자가 없어 회수 검사가 걸지 않는다. **놓친다** (아래 리스크) |

head 세 개가 전부 다르고 두 개가 같은 시간 단위(`years`, `month`)라는 점이 요지다. **단위로는 갈리지 않고 head로만 갈린다.** ADR-031-A가 문헌의 빈자리라고 기록한 판정이 실제 모델 출력에서 재현됐다.

### 실측 — 오답

| 케이스 | 출력 | 판정 |
|---|---|---|
| `the upper boundary of the two-sided 95.02% confidence interval for the hazard ratio was less than 1.3` | 클래스·계열 정확(`NON_CRITERION`/`statistical_decision_rule`)하나 `threshold_phrase`에서 `for the hazard ratio`를 **빼고 요약**함 | G3 부분문자열 실패 → REVIEW. 클래스가 맞았는데 REVIEW가 되는 손실이지만, NON_CRITERION은 어차피 폐기되므로 실질 손실 0 |
| 커피 문장 | `more than 8 cups per day`를 `EVENT_QUANTITY`로 분류 (택소노미는 `REVIEW`로 지정) | **오분류.** head `cups`가 해소되자 모델이 양성 클래스를 골랐다. "CDM에 표현할 곳이 없다"는 판단은 head 존재 여부와 무관한데, 모델은 그 둘을 묶는다 |
| 커피 문장 (`EVERY NUMERAL`) | `1 cup = 250 mL`을 `NON_CRITERION`/`spelled_out_count`로 분류 (정답은 `definitional_equality`) | 계열 오답, 클래스 정답. 둘 다 폐기이므로 무해 |
| 혈액 기증 (`EVERY NUMERAL`) | `> 500 mL` 구문을 두 번, 숫자 없는 `prior to screening`을 한 번 | G6 + 숫자 없는 구문 폐기로 처리 |

커피 케이스가 진짜 약점이다. **REVIEW는 "head를 못 찾았다"와 "목적지가 없다" 두 가지를 뜻하는데, 구조 신호는 앞의 것만 잡는다.** 뒤의 것은 모델 판단에 의존하고, 모델은 head가 있으면 양성 클래스로 기운다. 코퍼스에 사례가 1건뿐이라 빈도를 알 수 없다.

## 근거

- **3단계 경계를 새로 만들지 않는다.** `parse_value_constraints(text) -> list[ValueConstraint]`는 ADR-031 D3가 이미 시그니처를 확정하고 막아 둔 자리다. 2단계 출력이 축자 구문 문자열인 것은 설계 선택이 아니라 그 함수가 요구하는 형태다.
- **REVIEW를 코드가 만들지 모델이 만들지 않는다.** 모델에게 "확신 없으면 REVIEW"라고 부탁하는 설계는 모델이 확신을 잘못 추정하는 순간 무너진다. G1·G4·G7은 모델 답을 신뢰하지 않고 원문과 답의 **형태**만 본다.
- **오탐 비용을 측정한 뒤에 게이트를 켠다.** G1의 첫 정의(위치 기반)는 정상 AGE 문장 2.5%를 잡았다. 단위 인지 정의로 바꾸니 0.1%다. 측정하지 않았으면 "안전하지만 못 쓰는" 게이트를 넣을 뻔했다.
- **배치를 안 하는 이유는 컨텍스트가 아니라 실패 반경이다.** 산수만 보면 실측 최대 스터디는 스터디 단위로도 들어간다. 들어가는데도 안 하는 이유는 절단된 JSON 하나가 스터디 전체를 지우기 때문이고, prefix 재전송 비용이 0.3초로 측정됐기 때문이다.
- **재현성을 캐시로 산다.** temperature 0 + seed는 관측상 안정적이었지만 서버 부하 조건이 통제되지 않는다. 콘텐츠 주소 캐시는 조건과 무관하게 결정적이고, Agent 1이 이미 그 패턴을 쓴다.

## 스코프 (의도적 단순화)

- **구문 간 관계를 표현하지 않는다.** 조건부 임계값(`ALT ≤ 2.5×ULN unless liver metastases, in which case ≤ 5×ULN`), 성별별 임계값, carve-out 절은 각각 독립 구문이 되고 둘을 묶는 조건은 사라진다. 택소노미 `limits`의 `conditional_thresholds`·`sex_conditioned_thresholds`·`carve_out_attachment`가 그대로 남는다.
- **범위(`6.5 - 8.5%`)를 다루지 않는다.** 택소노미가 `NON_CRITERION`으로 지정한 대로 따른다. 올바른 해법은 3단계에 `bt` 피연산자를 넣는 것이지 2단계의 클래스가 아니다(`limits.ranges_need_bt`).
- **숫자 없는 조건을 다루지 않는다.** `undetectable`, `Child-Pugh B/C`, `NYHA III/IV`는 숫자가 없어 회수 검사가 걸지 않는다. 숫자 임계값 분류기의 범위 밖이다.
- **`op`/`value`/`unit`/`reference_bound`를 계산하지 않는다.** ADR-031 D2대로 3단계가 소유한다. 2단계가 정규화·환산·계산을 하면 코퍼스 회귀 방어선이 무력화된다.
- **1단계를 고치지 않는다.** 부모 불릿 계보(ancestry) 전달은 별도 작업이다. 본 설계는 그것이 오든 안 오든 답이 달라지지 않게 하는 것이 목적이다.
- **few-shot을 손으로 늘리지 않는다.** 택소노미가 고른 23개로 고정한다. 늘리면 held-out이 더 줄고, 지금도 다섯 클래스가 0이다.

## 미해결 리스크

- **얇은 클래스는 평가가 불가능하다, 잡음이 아니라.** held-out 기준으로 AGE·EVENT_QUANTITY·STATE_DURATION·DRUG_DOSE·REVIEW가 각각 **0건**이다. 이 다섯 클래스의 동작에 대해 본 ADR이 제시하는 증거는 이 문서의 실측 케이스 몇 개가 전부이며, 그것은 내가 고른 문장이다. D9의 추가 라벨링 3번 전까지 이 클래스들의 정확도를 인용하면 안 된다.
- **정밀도는 앞으로도 측정 못 한다** — 코퍼스가 행별 전수가 아니기 때문이다. 분류기가 없는 구문을 지어내도 지금 인프라로는 안 보인다. D9 추가 라벨링 1번이 유일한 해결책이다.
- **`EVERY NUMERAL`은 검증되지 않은 프롬프트 변경이다.** 4문장에서 회수를 0 누락으로 올렸지만 4문장이다. 지연을 2~4배로 늘리고 중복 구문을 만든다. 코퍼스 91개 held-out 전수 실행 전에는 기본값으로 켜면 안 된다.
- **커피 케이스 — "목적지가 없다"는 구조 신호가 없다.** head가 해소되면 모델은 양성 클래스로 기운다. `REVIEW`의 두 의미 중 하나만 구조적으로 방어된다. 코퍼스 사례 1건.
- **G3(부분문자열)이 정답을 REVIEW로 보낸다.** 통계 CI 케이스에서 관측했다. NON_CRITERION은 무해하지만 양성 클래스에서 같은 요약이 일어나면 실제 조건이 REVIEW 큐로 간다. 정규화 후 재정렬(fuzzy re-anchor)을 넣으면 게이트가 물러지므로 넣지 않았다. 빈도 미측정.
- **재현성 측정이 무부하 조건이다.** 3케이스 × 3회 바이트 동일은 순차 호출 결과다. D2가 요구하는 병렬 실행(8워커) 하에서 다시 측정해야 하며, 그때 흔들리면 D7의 캐시가 유일한 방어선이 된다.
- **head 생략 빈도 0.1%는 원문 채널의 값이다.** 1단계 분해 후의 값이 아니다. 진짜 노출은 `ALT, AST, or ALP > 3x ULN` 같은 문장을 1단계가 쪼갤 때 생기고, 그 빈도는 1단계 출력에서만 잴 수 있다. 재본다는 전제로 G1을 켠다.
- **`Criteria.source_text` 추가가 저장된 IR과 호환되어야 한다.** 기존 6개 저장 스터디에는 이 필드가 없다. `Optional`이므로 로드는 되지만, 없으면 분류기를 호출할 수 없어 그 스터디들은 재추출 전까지 2단계를 못 탄다.
- **`0.3초 prefix` 측정은 이 서버의 값이다.** prefix caching 설정이 바뀌거나 GPU가 바뀌면 D2의 비용 논거를 다시 재야 한다. `--budget`이 재현 명령이다.

## 관련

- ADR-031 — 값 조건 의미 보존. 본 ADR은 그 D2("발견은 LLM, 구조화는 파서")의 LLM 쪽 절반을 구체화한다. `parse_value_constraints`가 두 단계의 유일한 접점이다.
- ADR-031-A — 이환 기간. 본 ADR의 `STATE_DURATION` 클래스가 그 D1/D5 fragment로 간다. 워크드 예제가 그 문장이다.
- ADR-016 — `ThreadPoolExecutor` 결정적 순서. D2의 병렬화는 이 패턴을 재사용한다.
- ADR-029 — feasibility gating. D8의 `conditional=True` 표시를 공유한다.
- `docs/daily_notes/tte_value_taxonomy.json` — 9개 클래스, 계열, op 표, 표기 절. 프롬프트의 유일한 출처.
- `docs/daily_notes/tte_related_work.json` — `synthesis` 항목의 head 우선 판정과 5단계 라우터 표. 본 ADR의 D5는 그 표의 2번("head 없이 시간 단위만 있으면 나이로 간주")을 **의도적으로 뒤집는다** — 근거는 「실측 — head 요구 제거」다.
- `tests/fixtures/value_constraint_corpus.yaml` — 114항목 / 45출처. 수정하지 않는다.
- 재현 스크립트: `scripts/probe_criterion_classifier.py`. `--budget`(컨텍스트 산수), `--run`(13케이스), `--repeat 3`(재현성), `--no-head-rules`(ablation), `--elided`(head 생략 빈도). 본 문서의 모든 모델 유래 수치를 낸다. 쓰기 없음, 코호트 생성 없음.
