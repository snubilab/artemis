# 2026-03-24: ChromaDB 인프라 구축 + Eligibility Criteria Metadata UI

## 오늘 완료

### ChromaDB 인프라 (mapping agent 활성화)

- [x] 문제 진단: `artemis-api` 컨테이너에 `chromadb` 패키지 미설치, chromadb 서비스
  미실행 → mapping agent가 항상 placeholder fallback
- [x] `artemis/chroma_db/` (900MB, 440K OMOP concepts) 볼륨 마운트로 해결
  - `compose/artemis-api.yml`에 `../artemis/chroma_db:/app/chroma_db` 추가
  - 기존 로컬 chroma_db (2월~3월 생성, all-MiniLM-L6-v2 임베딩) 재활용
- [x] `vector.py`에 `CHROMA_URL` 환경변수 지원 추가 (HttpClient/PersistentClient 분기)
- [x] fallback 정책 수정
  - `_should_use_placeholder_seeded_mapping`: `"chromadb" in str(exc)` 문자열 매칭 제거
  - `ModuleNotFoundError`만 placeholder 허용 (테스트/부트 환경)
  - 런타임 chromadb 오류는 이제 예외로 전파
- [x] `rag_search.py`: concept_name이 metadata에 없고 documents에 저장되어 있던 문제 수정
  - `meta.get("concept_name") or doc or "Unknown"` fallback 체인

### Eligibility Criteria Metadata (IR → FE 정보 보존)

- [x] 문제 진단: `_criteria_from_ir`가 IR의 `entity_text`만 추출, `name`/`domain`/
  `value_constraint`/`sourceText` 전부 소실
  - LEADER trial "Age >= 50 with cardiovascular disease" → "Age"로 퇴화
  - mapping agent가 "Age" 매핑 시도 → 실패
- [x] `Criterion` model 확장 (`artemis/src/api/models/tte.py`)
  - `domain: str`, `valueConstraint: CriterionValueConstraint | None`,
    `sourceText: str`, `mappable: bool` (computed_field)
  - `DEMOGRAPHIC_DOMAINS` frozenset 추가
- [x] `_criteria_from_ir` 재작성 (`tte_service.py`)
  - `name` 우선 사용 (e.g. "Age >= 50" vs "age")
  - `domain`, `valueConstraint`, `sourceText` 보존
  - `sourceText` = `entity_text` (name과 다를 때만, 원본 trial 텍스트)
- [x] `_build_seeded_target_circe`: Demographics domain 자동 스킵
- [x] FE `createEligibilityCriterionModel` 확장
  - `domain` (observable, dropdown으로 편집 가능)
  - `valueConstraint` (observable), `sourceText` (static)
  - `mappable` (pureComputed, domain 변경 시 자동 갱신)
- [x] FE criteria row HTML 업데이트
  - domain dropdown (120px), value badge, source text (read-only), mappable indicator
  - inclusion/exclusion 모두 적용
- [x] `buildStudyData` 직렬화에 새 필드 포함

### E2E 검증 (LEADER trial, NCT01179048)

- [x] Trial import → criteria에 domain badge 표시 확인
  - Condition: Type 2 diabetes
  - Demographics: Age >= 50 with cardiovascular disease (not mapped)
  - Measurement: HbA1c >= 7% (value badge: gte 7 %)
  - Drug: Anti-diabetic drug use, oral anti-diabetic drugs, insulin 종류들
- [x] Process Eligibility → 200 OK
  - 20 concept sets, 19 inclusion rules
  - Demographics 3개 criteria 자동 스킵
  - 실제 OMOP concept 매핑 확인:
    - Type 2 diabetes mellitus (SNOMED 201826)
    - liraglutide (RxNorm)
    - HbA1c (SNOMED)
    - exenatide, pramlintide, DPP-4 inhibitors
- [x] ATLAS Cohort Editor 정상 열림

## 커밋

| Hash | Description |
|------|-------------|
| `1ffb4a5` | Criterion model: domain, valueConstraint, sourceText, mappable |
| `f63e4ad` | _criteria_from_ir: preserve IR metadata |
| `59bbca4` | Skip Demographics criteria in mapping agent |
| `ec988a9` | FE: domain dropdown, value badge, source text, mappable indicator |
| `c0c9466` | ChromaDB infra + fallback policy |
| `e396e57` | RAG search: concept_name fallback |
| `a4ff58e` | Documentation |
| `da9956e` | DB 연결 (broadsea-atlasdb) + auto-trigger Process Eligibility |

### DB 연결 + Auto-trigger + Apply 검증

- [x] `OMOP_DB_HOST=broadsea-atlasdb` 설정 (`compose/artemis-api.yml`)
  - Ontology search, Expression Builder concept validation 작동
  - concept set items 정제 (5→2 items, 실제 유효 concept만)
  - PHOEBE 테이블은 현재 DB에 없음 → graceful fallback
- [x] `Dockerfile.tte-api`에 `psycopg2-binary`, `sqlalchemy` 추가
- [x] trial import 후 `convertEligibilityToStructured()` 자동 호출 (`tte-manager.js`)
- [x] Apply Structured Edit → Save → 재진입 검증
  - criteria metadata (domain, valueConstraint, sourceText) 전부 persist 확인
  - domain dropdown 값, value badge, source text, not mapped indicator 모두 유지

## 알려진 제한사항

- PHOEBE 테이블이 `synthea_cdm` 스키마에 없음 → ingredient-level roll-up 미작동
  - concept set name이 구체적 제형명 (e.g. "liraglutide 3.6 MG/ML")으로 나올 수 있음
- Redis 미연결 → 매 호출마다 fresh LLM 요청 (~5-15분 소요, DB 연결 후 더 길어짐)
- agent1 LLM 캐시가 있으면 이전 포맷으로 criteria가 생성될 수 있음
  → 캐시 클리어 후 재생성 필요
- Stage1 pipeline timeout (5s)이 첫 DB 연결 시 부족할 수 있음
  → connection pool warm-up 후 정상 동작

## 남은 것

- [ ] PHOEBE 테이블 생성/로딩 → ingredient-level concept name 개선
- [ ] Redis 연결 → LLM 호출 캐싱으로 처리 시간 단축
- [ ] Stage1 timeout 조정 또는 connection pool warm-up
- [x] Eligibility criteria UI 정렬 (valueConstraint badge, X button, domain dropdown) → 2026-03-25 완료
- [x] Expression adapter exclusion 분리 수정 → 2026-03-25 완료
