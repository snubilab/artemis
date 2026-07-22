# ADR-015: MedCPT Embedding Model 도입 (Ablation 지원)

**상태**: 승인됨  
**날짜**: 2026-02-20  
**의사결정자**: @kyh

## 컨텍스트
Agent 2의 벡터 검색(ChromaDB)에서 기본 임베딩 모델 `all-MiniLM-L6-v2`(22M params, 384-dim)를 사용 중이었다.
- 범용 모델로 의료 용어 동의어/약어 매핑 정확도에 한계
- "MI" → "Myocardial Infarction", "DPP-4 inhibitor" → 구성 약물 등의 의미적 매칭 부족
- 의료 도메인 특화 임베딩으로 Recall@20 개선 가능성 확인 필요

## 결정
MedCPT(`ncbi/MedCPT-Query-Encoder` / `ncbi/MedCPT-Article-Encoder`, 330M params, 768-dim)를 **기존 모델과 공존하는 형태**로 도입한다.

- 별도 컬렉션(`omop_concepts_medcpt`)에 인덱싱
- `EMBEDDING_MODEL` 환경변수로 런타임 전환 (`default` / `medcpt`)
- 기존 `omop_concepts` 컬렉션 및 코드 무변경

## 근거
- **성능**: MedCPT는 TREC-COVID, BioASQ, BEIR 의료 subset에서 SOTA (GTR-XXL 4.8B보다 우수)
- **Asymmetric Bi-Encoder**: Query Encoder ≠ Article Encoder 구조로 검색 특화
- **학습 데이터**: 2.55억 PubMed 쿼리-논문 쌍으로 사전학습 → 의료 용어 의미 공간 최적화
- **Ablation 필요성**: 도입 전 정량적 비교(Recall@20) 없이 전면 교체는 리스크 → 공존 구조로 A/B 비교 후 결정

고려한 대안:
1. **BioLinkBERT**: 이미 reranker로 사용 중. retrieval용도로는 contrastive 학습된 MedCPT가 적합
2. **PubMedBERT**: MedCPT의 베이스 모델. contrastive fine-tuning 없이 retrieval 성능 열위
3. **전면 교체**: 기존 인덱스 삭제 후 MedCPT만 사용 → rollback 불가, ablation 불가

## 영향
- **신규 파일**: `src/utils/medcpt_embedding.py`, `scripts/populate_chromadb_medcpt.py`
- **수정 파일**: `src/utils/vector.py`, `src/settings.py`, `pyproject.toml`
- **추가 의존성**: `transformers`, `torch` (optional)
- **컴퓨테이션**: 인덱싱 시 CPU 기준 3-5시간 (GPU 시 ~15분), 쿼리 시 ~50-100ms (CPU)
- **디스크**: 모델 ~1.3GB, 인덱스 ~1.5GB 추가
- **기존 동작 무영향**: `EMBEDDING_MODEL=default`(기본값) 시 기존과 완전 동일
