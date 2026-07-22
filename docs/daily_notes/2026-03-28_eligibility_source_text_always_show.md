# Eligibility Criteria sourceText 항상 표시 — 2026-03-28

## 변경 내용

기존에는 eligibility criteria 행의 원문(`sourceText`)이 display name과 다를 때만 표시되었음.
사용자 경험상 있기도 없기도 해서 혼란스러워 항상 표시하도록 변경.

## 변경 파일

- `artemis/src/services/tte_service.py` (~line 5123)

## 변경 전

```python
source_text = entity_text if name and entity_text and name != entity_text else ""
```

## 변경 후

```python
source_text = entity_text
```

## 동작

- `entity_text`가 있는 항목은 name과 동일하더라도 원문을 항상 표시
- `entity_text` 자체가 없는 항목(Demographics 등)은 그대로 표시 안 됨
