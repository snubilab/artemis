# Conversation Notes

대화창 ID 기준으로 핵심 내용을 기록하는 노트. 한 대화창에서 여러 주제를 다룰 수 있으므로, **대화창 ID** 단위로 관리한다.

## 파일명 규칙

`{대화ID 앞 8자리}_{제목}.md`

예: `7e02e8f3_TROY_GOLD_Comparison.md`

## 대화 ID 확인법

Antigravity artifact 경로에서 추출:  
`~/.gemini/antigravity/brain/{conversation-id}/`

## 필수 구조

```markdown
# {대화ID 앞 8자리}: 대화 제목

**대화 ID**: `full-conversation-id`
**날짜**: YYYY-MM-DD
**관련 파일**: 수정/생성된 파일 목록

## 대화 흐름

1. 무엇을 물어봤는지 (질문)
2. 무엇을 발견했는지 (발견)
3. 무엇을 했는지 (조치)

## 핵심 결론

## 다음 단계

## 산출물
```
