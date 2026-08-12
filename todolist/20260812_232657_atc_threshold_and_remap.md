# ATC 클래스 임계값 상향과 재측정 — 2026-08-12

## 배경

`drug_class_expander.py:177`의 `AGENT2_ATC_DISTANCE_THRESHOLD` 기본값 `0.4`가 의미상
정확한 ATC 매칭 14건을 기각하고 있다. 재매핑 로그의 전체 판정 31건을 거리순으로 보면:

- 통과 4건, 최대 거리 0.134
- 기각 27건, 최소 거리 0.453
- 기각된 0.45~0.735 구간은 **전부 정답** (DPP-4, SGLT2 ×3, GLP-1 ×3, insulin ×3,
  corticoid, anti-obesity, OADs/Insulin)
- 그 구간의 유일한 오답은 `Concomitant strong CYP3A inhibitors → Pi3K inhibitors` (0.760)

즉 0.75가 안전 상한이며, 그 값에서 정답 14건이 들어오고 오답은 0건이다.

ATC 확장이 gold를 실제로 재현하는지 DB로 확인했다:

| ATC 클래스 | 성분 확장 | gold 커버 | 여분 |
| --- | --- | --- | --- |
| DPP-4 inhibitors (A10BH) | 8 | 8/10 | 0 |
| SGLT2 inhibitors (A10BK) | 7 | 5/5 | 2 |
| GLP-1 analogues (A10BJ) | 6 | — | — |

대상 기준의 현재 recall: DPP4 0.04(closure 2093), SGLT2 0.25(987), GLP-1 0.41(1409).

부수 발견: UMLS MRREL SQLite가 없어(로그 37회) 약물 클래스 확장의 1번 전략은 죽어 있고
ATC가 유일한 경로다. 이번 작업 범위 밖.

## 체크리스트

### A. 임계값 변경 (순차 — 서로 의존)

- [x] A1. 실패 테스트 작성: 실제 기각 사례(DPP-4 0.456, GLP-1 0.618)가 통과해야 하고,
      실제 오답(CYP3A 0.760)은 계속 기각돼야 한다. 합성값이 아니라 로그에서 관측된 거리를 쓸 것
- [x] A2. 테스트가 현재 코드에서 실패하는 것 확인 (RED)
- [x] A3. `drug_class_expander.py:177` 기본값 0.4 → 0.75
- [x] A4. 신규 테스트 통과 확인 (GREEN)
- [x] A5. 기존 drug-class 관련 테스트 통과 확인 (회귀 없음)
- [x] A6. 전체 스위트 실행, 기준선 `100 failed / 2076 passed`와 대조
- [x] A7. 커밋

### B. 재매핑과 채점 (A 완료에 의존)

- [x] B1. 새 store 디렉터리 생성 (콜드 캐시) `tmp/atc_fix/`
- [x] B2. arm 검증: 컨테이너 새 프로세스에서 임계값 0.75가 실제로 읽히는지 + DPP-4가
      통과하는지 확인, 불일치 시 중단
- [x] B3. 6개 시험 재매핑 실행 (약 2시간 20분)
- [x] B4. CIRCE export
- [x] B5. 채점 및 `scoped_scale_fix.json`과 짝지어 비교 (공통 gold 집합 기준)
      → 매크로 recall 0.611 → 0.627 (+0.017, 1.52 SE, 5/6 개선), precision 보합 (−0.0000)
- [x] B6. DPP4/SGLT2/GLP-1 기준의 실제 recall 변화 확인 → 아래 표

## B5/B6 결과

| 기준 | recall | precision |
| --- | --- | --- |
| SGLT2 inhibitors (CARMELINA) | 0.25 → **1.00** | 0.48 → 0.97 |
| GLP-1 RA (CARMELINA, CAROLINA) | 0.41 → **1.00** | 1.00 → 1.00 |
| DPP-4 inhibitor (CARMELINA, 올바른 짝) | 0.131 → **0.621** | 0.577 → **1.000** |
| [CKim] any insulin (CAROLINA) | 0.00 → 0.20 | 1.00 → 0.63 |

## 새로 발견 — 채점 하네스의 짝짓기 결함 (이번 범위 밖)

`scoped_atc_fix.json`은 gold `[TROY intervention] DPP4 inhibitors`를 생성 집합
**`SGLT-2 inhibitors`**에 붙이고(`matched_by_name`, recall 0.07), 정작 맞는 상대인
생성 집합 `id=9 'DPP-4 inhibitor'`(gliptin 7성분)는 `unmatched_generated`로 버렸다.

올바른 짝으로 직접 채점하면 recall 0.621 / precision 1.000이다. 즉 **보고된 0.07은
파이프라인이 아니라 매처의 산물**이고, ATC 수정의 실제 효과는 매크로 수치가 보여주는
것보다 크다.

원인 추정: `DPP4 inhibitors` vs `DPP-4 inhibitor`에서 하이픈·단수형 차이가 벌점을 받는
사이, 복수형이 일치하는 `SGLT-2 inhibitors`가 더 높은 이름 유사도를 얻는다. 변별력 있는
토큰(DPP vs SGLT)보다 어미가 더 세게 작용한다.

- [ ] D1. 매처의 이름 유사도가 변별 토큰보다 단복수/하이픈에 좌우되는 문제 조사
- [ ] D2. 6개 시험 전체에서 같은 부류의 오짝짓기가 몇 건인지 집계 (매크로 수치 신뢰도에 직결)
- [ ] D3. 수정 시 과거 arm 전부 재채점 필요 — 별도 세션에서 진행할 것

## 4-arm 씨앗 실험 결과 (C1, 완료 — B와 무관하게 독립)

리랭커가 `top_n=3`으로 씨앗을 고르는 병목을 두 가지로 건드려 봤다. 74개 기준(검색이
gold를 top-15에 올린 전부), 네 arm이 **동일한 후보 15개**를 채점하도록 검색은 한 번만
돌렸다. 지표는 검색이 올린 gold 118개 중 씨앗에 든 개수.

| arm | top_n | 커버리지 지침 | gold 씨앗 유지 |
| --- | --- | --- | --- |
| A | 3 | 없음 (현재) | 74/118 = 62.7% |
| B | 5 | 없음 | 86/118 = **72.9%** |
| C | 3 | 있음 | 75/118 = 63.6% |
| D | 5 | 있음 | 88/118 = **74.6%** |

- **top_n 효과**: A→B `+10.2pp`, C→D `+11.0pp`. 두 조건에서 일관.
- **프롬프트 한 줄 효과**: A→C `+0.9pp`, B→D `+1.7pp`. 1pp ≈ gold 1.2개이므로 각각
  1~2개 차이다. 온도 0이어도 후보 순서에 민감한 부품이라 **0과 구별되지 않는다.**

결론: 커버리지를 프롬프트로 지시하려던 가설은 기각. **씨앗 예산을 늘리는 기계적 변경이
유일하게 작동하는 지렛대다.**

`top_n` 변경은 **이번 재매핑에 넣지 않았다.** ATC 임계값과 같은 arm에 섞으면 무엇이
숫자를 움직였는지 귀속할 수 없다. 다음 arm의 후보로 남긴다. 넣을 때 확인할 것: 씨앗이
늘면 KG 확장·critic 부하가 늘고 precision이 떨어질 수 있다 — 이 실험은 **recall 쪽만**
쟀다.

### C. 기록 (B 완료에 의존)

- [x] C1. 4-arm 씨앗 실험 결과 정리 — 위 표
- [x] C2. 핸드오프 갱신
- [x] C3. omx_wiki 갱신 + 대시보드 재빌드
- [ ] C4. 커밋

## 검증 명령

```bash
cd /home/bilab/work/projects/Broadsea/artemis
.venv/bin/python -m pytest tests/test_environment_matches_requirements.py -q
.venv/bin/python -m pytest tests/ -q -p no:randomly     # 기준선 100 failed / 2076 passed
```
