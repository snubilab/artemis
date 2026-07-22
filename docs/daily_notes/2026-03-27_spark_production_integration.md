# 2026-03-27: Spark Cohort Executor — Production Integration

## 작업 요약

어제(2026-03-26) 개발 완료 + 3개 study 검증된 Spark 코호트 실행 엔진을
프로덕션 환경에서 zero-manual-setup으로 동작하도록 인프라 정비.

---

## 검증 결과 (전 세션 완료)

| Study | Patients | WebAPI | Spark | Speedup | Match |
|-------|----------|--------|-------|---------|-------|
| LEADER | 1,222 | 479s | 48s | 10x | ✅ |
| PLATO | 436 | 14s | 15s | ~1x | ✅ |
| ARISTOTLE | 1,219 | ~2100s* | 19s | 111x | ✅ |

*ARISTOTLE WebAPI: 이전 세션 stuck query(PID 62681, 35분) + 새 실행 중복. 실제 정상 실행은 훨씬 짧을 것.

---

## 이번 세션 작업 내용

### Problem

- 컨테이너 재시작할 때마다 pyspark, pyarrow, JDK 수동 설치 필요
- Parquet vocab export 수동 실행 필요
- COHORT_ENGINE 설정 문서 없음
- 전제조건 미충족 시 첫 cohort 요청에서야 에러 발생 (fast-fail 없음)

### Solution: 7개 커밋

| 커밋 | 파일 | 내용 |
|------|------|------|
| `3532300` | `pyproject.toml`, `requirements.txt` | pyspark 필수화, pyarrow 추가 |
| `0871476` | `Dockerfile.tte-api` | openjdk-17-jdk-headless + JDBC jar 빌드타임 다운로드 + `COPY scripts/` |
| `517de1a` | `scripts/export_vocab_parquet.py`, `tests/test_export_vocab_parquet.py` | Parquet 자동 export (chunked PyArrow writer, skip-if-exists) |
| `9671bed` | `src/pipeline/spark_startup.py`, `tests/test_spark_startup.py`, `src/api/main.py` | 시작 시 fast-fail 검증 훅 |
| `10617d9` | `compose/artemis-api.yml` | `COHORT_ENGINE`, `SPARK_PARQUET_DIR` env var 추가 |
| `a31ae85` | `docs/spark_setup.md` | 설정 가이드 |
| `4aae606` | `tests/integration/test_spark_parity.py` | Spark vs WebAPI parity 통합 테스트 |

---

## 첫 실행 절차 (새 환경 또는 이미지 변경 후)

```bash
# 1. Colima 메모리 증설 (concept_ancestor 75M rows 처리 필요)
colima start --memory 18 --cpu 4

# 2. Docker 이미지 재빌드 (JDK + pyspark 포함)
docker-compose build artemis-api

# 3. 스택 시작
docker-compose up -d

# 4. Vocab Parquet export (최초 1회, 약 10분 소요)
#    /app/tmp/parquet/ 에 저장 (볼륨 마운트, 재시작 후에도 유지)
docker exec artemis-api python -m scripts.export_vocab_parquet

# 5. Spark 활성화
echo "COHORT_ENGINE=spark" >> artemis/.env

# 6. 재시작 (startup hook이 전제조건 자동 검증)
docker-compose restart artemis-api

# 7. 검증
docker exec artemis-api python -c "
from src.pipeline.spark_startup import validate_spark_prerequisites
validate_spark_prerequisites()
print('All Spark prerequisites met.')
"
```

---

## 재시작 이후 (Parquet 이미 있을 때)

```bash
colima start --memory 18 --cpu 4
docker-compose up -d
# Parquet files: /app/tmp/parquet/ (볼륨 마운트로 유지됨)
# export_vocab_parquet.py는 파일이 있으면 자동 skip
# COHORT_ENGINE=spark가 .env에 있으면 자동 활성화
```

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| 컨테이너 OOM (exit 137) | Colima 메모리 < 18GB | `colima stop && colima start --memory 18` |
| `pyspark not installed` | 구 이미지 | `docker-compose build artemis-api` |
| `JDBC jar not found` | 구 이미지 | `docker-compose build artemis-api` |
| `Parquet vocab files missing` | 최초 실행 또는 볼륨 유실 | Step 4 재실행 |
| API startup 시 RuntimeError | COHORT_ENGINE=spark + 전제조건 미충족 | 에러 메시지 그대로 따라 조치 |
| WebAPI 수천 초 timeout | PostgreSQL stuck query | `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state='active' AND now()-query_start > interval '5 minutes';` in `postgres` DB |

---

## 파일 구조 (추가된 파일)

```
artemis/
├── Dockerfile.tte-api          # openjdk-17, JDBC jar, COPY scripts/
├── docs/
│   └── spark_setup.md          # 상세 설정 가이드
├── scripts/
│   └── export_vocab_parquet.py # vocab Parquet export (chunked PyArrow)
├── src/pipeline/
│   └── spark_startup.py        # startup fast-fail 검증
├── src/api/main.py             # @app.on_event("startup") 훅
└── tests/
    ├── test_export_vocab_parquet.py   # 3 unit tests
    ├── test_spark_startup.py          # 4 unit tests
    └── integration/
        └── test_spark_parity.py       # LEADER 1,222 parity test
```

---

## 핵심 설계 결정

1. **`requirements.txt` 직접 편집 금지** — auto-generated from pyproject.toml. 항상 `generate_requirements.sh` 사용.
2. **`SPARK_PARQUET_DIR`** — `PARQUET_DIR`가 아님. `spark_executor.py` line 223과 동일.
3. **아키텍처 독립적 JAVA_HOME** — `ln -sf /usr/lib/jvm/java-17-openjdk-* /usr/lib/jvm/java-17` symlink (arm64/amd64 모두 동작).
4. **chunked PyArrow writer** — `pd.concat` 대신 사용. concept_ancestor 75M rows를 메모리에 2배로 올리지 않음.
5. **startup hook** — `@app.on_event("startup")` in `create_app()` factory. COHORT_ENGINE=spark 아닐 때는 no-op.
