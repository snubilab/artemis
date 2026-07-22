# 2026-04-01 Full Benchmark Handoff

## 한 줄 요약

7,945개 전체 데이터 기준 멀티모델 벤치마크 병렬 실행 중. LLM Direct 6개 모델 + RAG 호스트 실행, Agent2 컨테이너 실행 시작.

---

## 현재 실행 중인 프로세스 (호스트)

| PID | Mapper | 모델 | 로그 | 결과 파일 |
|-----|--------|------|------|----------|
| 90977 | RAG | MedCPT | - | bench_rag_full_20260401_100006.json |
| 34478 | LLM Direct | gpt-4o | /tmp/bench_llm_gpt_4o_full.log | bench_llm_gpt_4o_full_20260401_103722.json |
| 34481 | LLM Direct | gpt-4.1 | /tmp/bench_llm_gpt_4_1_full.log | bench_llm_gpt_4_1_full_20260401_103722.json |
| 34487 | LLM Direct | gpt-5-chat | /tmp/bench_llm_gpt_5_chat_full.log | bench_llm_gpt_5_chat_full_20260401_103722.json |
| 34492 | LLM Direct | gpt-5.1 | /tmp/bench_llm_gpt_5_1_full.log | bench_llm_gpt_5_1_full_20260401_103722.json |
| 34499 | LLM Direct | gpt-5.2 | /tmp/bench_llm_gpt_5_2_full.log | bench_llm_gpt_5_2_full_20260401_103722.json |
| 34500 | LLM Direct | gpt-5.4 | /tmp/bench_llm_gpt_5_4_full.log | bench_llm_gpt_5_4_full_20260401_103722.json |

## 컨테이너 (artemis-api)

| Mapper | 로그 | 결과 파일 |
|--------|------|----------|
| Agent2 full (7,945) | /tmp/bench_agent2_full.log | bench_agent2_full_*.json |

Agent2 시작 확인: `docker exec artemis-api tail -5 /tmp/bench_agent2_full.log`

---

## 예상 소요 시간

| Mapper | 예상 완료 |
|--------|---------|
| RAG | ~12:00 (시작 10:00, 2시간) |
| LLM Direct 6종 | ~16:00~17:00 (7,945 × 2.5s) |
| Agent2 | ~20:00~다음날 (7,945 × 45s ÷ workers) |

---

## 완료 시 할 일

1. 각 JSON에서 `aggregate` 필드 파싱
2. `artemis/docs/daily_notes/2026-04-01_benchmark_full_results.md` 작성
3. 도메인별 분석 (Condition, Drug, Procedure, Measurement)
4. Agent2 vs RAG vs LLM 비교 최종 결론

---

## 인프라 상태

| 컨테이너 | 상태 |
|---------|------|
| artemis-api | Up (HF cache + omop_vocab 마운트 확인됨) |
| ohdsi-webapi | Up |
| broadsea-atlasdb | Up (statement_timeout=30min) |
| artemis-neo4j-v2 | Up (healthy) |

## Gold Cohort 생성 (진행 중)

- LEADER (1136): RUNNING (statement_timeout 30min 적용)
- ARISTOTLE (1138): RUNNING
- PLATO (1137): 436명 이미 완료

완료 후 AI vs Gold HR 비교 가능.

---

## 오늘 완료된 Fix 목록

| 항목 | 내용 |
|------|------|
| WebAPI timeout | 10min → 30min (ALTER SYSTEM) |
| CONCEPT.csv | omop_vocab 마운트 누락 → compose recreate 해결 |
| HuggingFace cache | MedCPT 컨테이너 접근 불가 → ~/.cache/huggingface 마운트 추가 |
| Gold N=0 오진 | timeout 에러를 "데이터 없음"으로 잘못 해석 → 재생성 중 |

## 100개 샘플 결과 (최신 corrected table 요약)

| Model | Precision | Recall | F1 | Hit@1 | Hit@5 | Hit@10 | Latency |
|-------|-----------|--------|-----|-------|-------|--------|---------|
| Agent2 | 0.322 | 0.341 | 0.287 | 0.270 | 0.570 | 0.570 | 24,822ms |
| RAG (MedCPT, validated rerun) | 0.055 | 0.279 | 0.076 | 0.140 | 0.370 | 0.490 | 1,154ms |
| gpt-5.4 | 0.126 | 0.167 | 0.106 | 0.270 | 0.340 | 0.360 | 2,456ms |
| gpt-5.2 | 0.118 | 0.162 | 0.095 | 0.260 | 0.320 | 0.320 | 2,257ms |
| gpt-5-chat | 0.048 | 0.136 | 0.059 | 0.260 | 0.320 | 0.320 | 1,527ms |
| gpt-5.1 | 0.033 | 0.134 | 0.037 | 0.260 | 0.310 | 0.320 | 2,239ms |
| gpt-4.1 | 0.025 | 0.149 | 0.035 | 0.240 | 0.320 | 0.330 | 3,265ms |
| gpt-4.1-mini | 0.010 | 0.067 | 0.015 | 0.120 | 0.140 | 0.140 | 2,739ms |
| o4-mini | 0.058 | 0.037 | 0.031 | 0.090 | 0.100 | 0.100 | 24,448ms |

Note:
- 최신 manuscript-facing source:
  - `artemis/output/benchmark_results/2026-04-01_paper_method_comparison_sample100.md`
- RAG의 초기 `0.0` 결과는 잘못된 아티팩트였고, 위 값은 동일 `sample_ids` 기준 validated rerun이다.
- 평가 단위는 single-label이 아니라 `criterion -> concept set`이다.
- 즉 각 criterion에 대해 gold concept 집합과 predicted concept 집합의 overlap으로 precision/recall/F1을 계산한다.

## 2026-04-02 Addendum: Hybrid Ablation Summary

추가 hybrid row:

| Model | Precision | Recall | F1 | Hit@1 | Hit@5 | Hit@10 | Latency |
|-------|-----------|--------|-----|-------|-------|--------|---------|
| GPT54 RAG (EASTUS2) | 0.238 | 0.194 | 0.165 | 0.400 | 0.450 | 0.450 | 3,573ms |
| LLM RAG (gpt-4o + MedCPT) | 0.203 | 0.197 | 0.156 | 0.340 | 0.440 | 0.440 | 2,686ms |

요약 해석:
- `GPT54 RAG > LLM RAG > LLM Direct (gpt-5.4) > RAG` 순으로 `F1`이 개선되었다.
- hybrid는 plain `RAG`보다 recall은 다소 낮아지지만 precision이 크게 올라가서 전체 `F1`이 훨씬 좋아진다.
- 그래도 `Ours (F1=0.287)`가 여전히 가장 높다.
- 따라서 retrieval + LLM selection만으로 baseline 대비 큰 개선은 만들 수 있지만, `UMLS/KG/critic/refiner`까지 포함한 full pipeline의 이득이 여전히 남아 있다.
- `GPT54 RAG` 유효 row는 기본 Azure endpoint가 아니라 EASTUS2 Azure endpoint override로 얻었다.

관련 아티팩트:
- `artemis/data/benchmark_results/bench_gpt54_rag_sample100_eastus2.json`
- `artemis/data/benchmark_results/bench_llm_rag_sample100.json`

## 해석 메모

- Condition 성능은 broad bucket / proxy / confounder label 때문에 별도 해석이 필요하다.
- 특히 `conditions indicating established cardiovascular disease`, `Malignant neoplasms of lymphoma`, `Parkinsonism confounder conditions` 같은 항목은 단일 질환명보다 훨씬 불리한 benchmark 구조를 가진다.
- 현재 partial Agent2 분석에서는 noisy tag, broad/ambiguous label, compositional phrase를 제외하면 macro Recall과 F1이 소폭 개선되었다.
- 따라서 메인 결과는 전체 benchmark 기준으로 보고, 부가 해석에서는:
  - clean term 성능
  - noisy / broad label 영향
  - Condition vs Drug/Measurement의 구조 차이
  를 분리해서 설명하는 것이 적절하다.
