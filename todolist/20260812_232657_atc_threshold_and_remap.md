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
- [ ] A7. 커밋

### B. 재매핑과 채점 (A 완료에 의존)

- [ ] B1. 새 store 디렉터리 생성 (콜드 캐시) `tmp/atc_fix/`
- [ ] B2. arm 검증: 컨테이너 새 프로세스에서 임계값 0.75가 실제로 읽히는지 + DPP-4가
      통과하는지 확인, 불일치 시 중단
- [ ] B3. 6개 시험 재매핑 실행 (약 2시간 20분)
- [ ] B4. CIRCE export
- [ ] B5. 채점 및 `scoped_scale_fix.json`과 짝지어 비교 (공통 gold 집합 기준)
- [ ] B6. DPP4/SGLT2/GLP-1 기준의 실제 recall 변화 확인

### C. 기록 (B 완료에 의존)

- [ ] C1. 4-arm 씨앗 실험 결과 정리 (A/B는 완료: 62.7% → 72.9%)
- [ ] C2. 핸드오프 갱신
- [ ] C3. omx_wiki 갱신 + 대시보드 재빌드
- [ ] C4. 커밋

## 검증 명령

```bash
cd /home/bilab/work/projects/Broadsea/artemis
.venv/bin/python -m pytest tests/test_environment_matches_requirements.py -q
.venv/bin/python -m pytest tests/ -q -p no:randomly     # 기준선 100 failed / 2076 passed
```
