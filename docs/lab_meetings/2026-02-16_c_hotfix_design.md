# Lab Meeting: C-Hotfix 구체 설계

**날짜**: 2026-02-16
**참여 모델**: Claude, Gemini (gemini-3-pro-preview), Codex (gpt-5.3-codex-spark)

## 안건
`benchmark_v3.py` C-Hotfix 4가지 코드 변경안 설계

## 제안 요약

| 모델 | Window 정규화 | Name Fuzzy | 1:N 매칭 | Unmatched 처리 |
|------|-------------|------------|---------|---------------|
| Claude | PRIOR/POST/OVERLAP 3범주 | stopword + `[TROY]` 제거 | C-Deep 미룸 | recall=0 포함 |
| Gemini | HISTORY/RECENT/FUTURE 3범주 | stopword + tag 제거 | **Global Greedy** (scored 1:1) | recall=0 + resolve |
| Codex | PRIOR/POST/ANY/INDEX 4범주 | stopword + 약어사전 | C-Deep 미룸 | recall=0 + Missed 라벨 |

## ✅ 합의 (3모델 일치)

### 결정 1: Window → 의미적 범주 (`window_group`)
```python
def _window_group(window: str) -> str:
    if window == "ALL": return "ANY_TIME"
    start, end = map(int, window.split(":"))
    if start < 0 and end <= 0: return "PRIOR"    # -365:0, -180:0
    if start >= 0 and end > 0:  return "POST"     # 0:365
    return "OVERLAP"                               # -30:30
```
- `key`에 `window_group` 추가: `{type}_{name}_{occ}_{window_group}`

### 결정 2: `_normalize()` 강화
```python
STOPWORDS = {"history", "of", "the", "a", "and", "or", "with", "without",
             "disorder", "disease", "condition", "finding", "measurement"}

def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'\[.*?\]', '', text)   # [TROY], [ARTEMIS] 제거
    text = re.sub(r'\(.*?\)', '', text)   # (LEADER) 제거
    text = re.sub(r'[^\w\s]', '', text)
    words = [w for w in text.split() if w not in STOPWORDS]
    return '_'.join(words) if words else text
```

### 결정 3: 1:N → C-Deep 미룸, Hotfix는 **Global Greedy 1:1**
- Gemini 제안 채택: 현재 first-match → **score 기반 global greedy**
- 모든 (TROY, ARTEMIS) 쌍의 score 계산 → 내림차순 정렬 → best-match 순차 선택
- 1:1은 유지하되 매칭 **품질**을 올림

```python
def match_fingerprints(troy_fps, artemis_fps):
    edges = []
    for i, troy in enumerate(troy_fps):
        for j, artemis in enumerate(artemis_fps):
            if troy.key == artemis.key:
                edges.append((1.0, i, j))
            elif (troy.criteria_type == artemis.criteria_type and
                  troy.occurrence_type == artemis.occurrence_type):
                t_words = set(_normalize(troy.concept_set_name).split('_'))
                l_words = set(_normalize(artemis.concept_set_name).split('_'))
                if t_words and l_words:
                    jaccard = len(t_words & l_words) / len(t_words | l_words)
                    if jaccard > 0.3:
                        edges.append((jaccard, i, j))
    edges.sort(key=lambda x: x[0], reverse=True)
    matched, troy_used, artemis_used = [], set(), set()
    for score, i, j in edges:
        if i not in troy_used and j not in artemis_used:
            matched.append((troy_fps[i], artemis_fps[j]))
            troy_used.add(i); artemis_used.add(j)
    return matched, [unmatched...], [unmatched...]
```

### 결정 4: Unmatched TROY → recall=0 강제 포함
- `compare_concept_sets()`에 `unmatched_troy` 인자 추가
- 미매칭 → `match="Missed", recall=0.0` 레코드
- `avg_concept_recall` 분모에 포함 → **과대평가 제거**

## 실행 계획
- [ ] 1. `SemanticFingerprint` 클래스에 `window_group` property + key 수정 (15min)
- [ ] 2. `_normalize()` stopword + tag 제거 추가 (15min)
- [ ] 3. `match_fingerprints()` → global greedy 방식으로 교체 (30min)
- [ ] 4. `compare_concept_sets()` + `main()` unmatched 처리 (15min)
- [ ] 5. `print_report()` Missed 라벨 + Summary 항목 (15min)
- [ ] 6. 실행 검증: `conda run -n artemis python scripts/benchmark_v3.py` (30min)

**총 예상**: ~2시간

## 부록
> 원본 제안: `tmp/lab_meeting/20260216_c_hotfix_plan/`
