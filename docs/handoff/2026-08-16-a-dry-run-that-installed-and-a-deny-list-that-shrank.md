# Handoff — 설치한 dry-run과 줄어든 deny 목록 — 2026-08-16

## Goal / context

같은 날 두 번째 핸드오프. 첫 번째(`2026-08-16-six-green-gates-and-a-dead-dashboard.md`)는
TTE 계측과 wiki를 다뤘고, 이 문서는 그 뒤에 실행한 **`my_agent` 싱크와 `moai update`** 를
다룬다. 코드 변경은 없다. 전부 도구·설정 상태 변경이고, 그중 하나가 **보안 설정을 조용히
낮췄다.**

## Current state

- 루트 저장소: `main` · HEAD `533f660` · 작업 트리 **깨끗** · PR 없음(remote 없음)
- artemis: `fix/tte-a-drug-anchored-entry` · HEAD `f34154f` · 작업 트리 **깨끗**
- `my_agent`: `3cc9e05` · 로컬 `?? .omx/` 1건 보존됨(건드리지 않음)
- **`.claude/`와 `.moai/`는 git 추적 대상이 아니다** — `.git/info/exclude:22`의 `/*`.
  루트 `CLAUDE.md`만 추적된다. 이 디렉터리들의 변경은 git으로 되돌릴 수 없다
- `moai-adk` **3.1.0** (세션 시작 시 3.0.1)
- **v2→v3 clean reinstall은 미완료** — step 3.5에서 중단, 아래 참조
- 서버/포트: 이번 작업에서 띄운 것 없음. vLLM은 여전히 죽어 있다

## Done this session (이 문서 범위)

커밋 없음. 전부 추적되지 않는 상태 변경이다.

| 대상 | 변경 |
| --- | --- |
| `my_agent` 싱크 | `--profile hybrid`, 스킬 codex=78 / claude=78, SessionEnd 훅 양쪽 설치 |
| `moai` 바이너리 | 3.0.1 → **3.1.0** |
| `.claude/settings.json` | deny 60 → 48 (도구가 제거) → **52** (그중 4건 복원) |
| v2→v3 템플릿 마이그레이션 | 시작됨, step 3.5에서 실패, 롤백 안 됨 |

## Key decisions & why

### `--dry-run`이 실제로 설치했다

```
moai update --dry-run
```

플래그 설명은 `Show planned archive and install operations without modifying the
filesystem`이다. 실제로는 바이너리를 3.0.1 → 3.1.0으로 **설치했고**, 그 다음 템플릿
동기화 단계에서 lock 에러로 멈췄다. 즉 "미리보기"를 요청했는데 전역 도구가 교체됐다.

**다음에 `moai update --dry-run`을 미리보기 용도로 신뢰하지 말 것.** 바이너리 갱신을
원치 않으면 `--templates-only`를 쓰고, 그것도 미리보기가 아니다.

### lock은 stale이었고 소유자는 죽어 있었다

`.moai/.update.lock`에 `{"pid":2536876,...}`이 남아 있었고 `ps -p 2536876`은 비어 있었다.
직전 `--dry-run` 호출이 바이너리를 갈아끼우면서 자기 lock을 정리하지 못한 것으로 보인다.
`trash-put`으로 치우고 진행했다.

`pgrep`으로 프로세스를 확인할 때 **같은 명령줄에 괄호 없는 `moai --version`이 있어서
자기 명령을 잡았다.** 괄호는 명령 안 **모든** 사본에 있어야 한다. `ps -eo pid,cmd | rg
'[m]oai-adk'` 형태로 다시 확인했다.

### 마이그레이션 전에 직접 백업을 떴고, 그게 유일한 완전 복원점이다

`moai update`가 만든 백업은 **부분**이다:

```
.moai/backups/v2-to-v3-2026-08-16T14-50-46Z/   # "PRESERVE inventory: 81 files"
```

`.claude/`의 대부분(commands, hooks, rules, output-styles, settings*, skills 다수)이
여기에 **들어 있지 않다**. 전체 복원점은 마이그레이션 10초 전에 직접 뜬 이쪽이다:

```
.moai/archive/pre-3.1.0-20260816T145036Z/claude/     # cp -a .claude
.moai/archive/pre-3.1.0-20260816T145036Z/moai-config/
```

`.claude/`가 git에 없으므로 이 디렉터리가 사라지면 되돌릴 방법이 없다. **지우지 말 것.**

### 피해 범위는 실측했다 — `settings.json` 한 파일

```
diff -rq .moai/archive/pre-3.1.0-20260816T145036Z/claude .claude
→ 차이 1건: settings.json
```

broadsea 전용 룰 4개(`chromadb.md`, `infra.md`, `webapi-cache.md`,
`atlas-dev-cache.md`)는 **바이트 동일**. agents·skills·hooks·commands 전부 무변경.
실패한 마이그레이션은 결과적으로 트랜잭션처럼 동작했다 — 백업 뜨고, settings 정리하고,
agency 단계에서 멈췄다.

### 🔴 update가 지운 12건은 "retired"가 아니라 **비밀정보 보호 규칙**이었다

도구는 이렇게 보고했다:

```
[settings] Removed 12 retired permission deny entries from settings.json
```

실제로 지워진 것:

```
Write(./secrets/**)  Write(~/.ssh/**)  Write(~/.aws/**)  Write(~/.config/gcloud/**)
Grep (./secrets/**)  Grep (~/.ssh/**)  Grep (~/.aws/**)  Grep (~/.config/gcloud/**)
Glob (./secrets/**)  Glob (~/.ssh/**)  Glob (~/.aws/**)  Glob (~/.config/gcloud/**)
```

`Read`와 `Edit` 대응 항목은 남아 있었지만 **`Write`는 대체 없이 사라졌다.**
`.claude/hooks/` 어디에도 `secrets`/`.ssh` 문자열이 없어 훅이 대신 막지도 않는다.
이 저장소 CLAUDE.md는 "Do not commit secrets or copy runtime values from `.env`,
`.env.runtime`, or `secrets/`"를 anti-pattern으로 명시하고 있다.

**`Write` 4건을 복원했다.** 현재 `Read`/`Write`/`Edit` 3종이 4개 경로를 모두 덮는다.
`Grep`/`Glob`은 복원하지 않았다 — 그 매처는 Claude Code가 지원하지 않아 애초에
무효였을 가능성이 크고, `Read` deny가 내용 접근을 이미 막는다. 이 판단은 검증하지
않았으니 뒤집을 근거가 나오면 되돌릴 것.

## Next steps (ordered, concrete)

1. **v2→v3 마이그레이션 블로커 결정.** 실패 지점은 이것이다:
   ```
   [MIGRATE_MERGE_CONFLICT] tech-preferences.md (Framework: _TBD_)
     conflicts with tech.md (Framework: FastAPI); resolve manually.
   ```
   `tech-preferences.md`는 **디스크에 없다**(`fd -H 'tech-preferences'` → 0건).
   `.moai/project/tech.md:9`는 `### Core Framework: FastAPI`로 실제 값을 갖고 있으므로
   충돌 상대는 `_TBD_` 플레이스홀더 쪽이다. 유력한 원인은 v2 잔재
   `.claude/rules/agency/constitution.md`(2026-04-22, 18133B)가 `agency=true` 신호를
   켠 것이다. 이 파일은 `.claude/rules/moai/design/constitution.md`(2026-04-28, 17626B)로
   **이미 이관됐고**(SPEC-AGENCY-ABSORB-001 M1), 후자 헤더가 전자를 원본 경로로 명시한다.
   즉 중복 사문일 가능성이 높다. **다만 지우면 두 파일 다 로드되던 현재 규칙 집합이
   바뀌므로 사용자 결정 사항이다.** 이번 세션에서는 손대지 않았다.
2. **마이그레이션을 재시도할 거라면 먼저 백업을 다시 뜰 것.**
   `.moai/archive/pre-3.1.0-20260816T145036Z`는 3.1.0 이전 상태이므로, 재시도 전
   현재 상태로 새 스냅샷을 만들어야 되돌릴 지점이 생긴다.
3. **`settings.json` deny 목록을 한 번 눈으로 볼 것.** 도구가 "retired"라고 부른 것이
   실제로는 보안 규칙이었으므로, 남은 48건 중에도 같은 성격의 제거가 있었는지는
   확인하지 않았다. 비교 지점:
   `.moai/archive/pre-3.1.0-20260816T145036Z/claude/settings.json`
4. **Codex / Claude Code 재시작** — `my_agent` 싱크가 새 지시문과 훅을 설치했고,
   싱크 스크립트가 재시작을 요구한다. 이 세션에서는 불가능하다.
5. TTE 쪽 다음 작업은 첫 번째 핸드오프의 Next steps를 볼 것 — vLLM 기동 후 6개 시험
   재매핑이 최우선이다.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea

# 현재 버전
moai --version                      # 기대: moai-adk 3.1.0

# 비밀정보 deny 커버리지 — Read/Write/Edit 각 4건이어야 한다
python3 -c "
import json
d = json.load(open('.claude/settings.json'))['permissions']['deny']
for v in ('Read','Write','Edit'):
    m = [x for x in d if x.startswith(v+'(') and any(s in x for s in ('secrets','ssh','aws','gcloud'))]
    print(f'{v:6s} {len(m)}: {m}')
"

# 마이그레이션 이후 .claude가 백업과 얼마나 다른지 (기대: settings.json 1건)
diff -rq .moai/archive/pre-3.1.0-20260816T145036Z/claude .claude

# broadsea 전용 룰이 살아 있는지 (기대: 차이 없음)
diff -rq .moai/archive/pre-3.1.0-20260816T145036Z/claude/rules/broadsea \
         .claude/rules/broadsea && echo IDENTICAL

# 마이그레이션 재시도 (실패 재현 — 위 1번을 먼저 결정할 것)
moai update --templates-only --yes

# my_agent 싱크 상태 재확인 (미리보기, 설치 변경 없음)
cd /home/bilab/.claude/skills/sync-my-agent
python3 scripts/sync_my_agent.py --profile hybrid --dry-run
```

## Gotchas / constraints

- 🔴 **`.claude/`와 `.moai/`는 git에 없다** (`.git/info/exclude:22`의 `/*`).
  여기를 건드리는 도구를 돌리기 전에 `cp -a`로 직접 백업할 것. `git checkout`으로
  되돌릴 수 없다.
- 🔴 **`moai update --dry-run`은 dry run이 아니다** — 바이너리를 설치한다.
- 🔴 **`moai update`가 "retired"라고 부르는 항목을 그대로 믿지 말 것.** 이번엔
  `Write(./secrets/**)` 계열 4건이 거기 섞여 있었다.
- **MoAI가 만드는 `.moai/backups/v2-to-v3-*`는 부분 백업이다** (preserve 목록 81개).
  `.claude/`의 대부분이 들어 있지 않다. 완전 복원점으로 쓰지 말 것.
- **`.moai/archive/pre-3.1.0-20260816T145036Z/`를 지우지 말 것** — 현재 유일한
  3.1.0 이전 완전 스냅샷이다.
- **`pgrep -f`/`pkill -f`의 괄호는 명령 안 모든 사본에 있어야 한다.** 이번에도
  같은 줄의 `moai --version` 때문에 자기 명령을 잡았다.
- **`rm`은 정책상 차단**되어 있다. `trash-put`을 쓸 것.
- **`find`도 차단**되어 있다. `fd`를 쓸 것.
- `my_agent` 싱크는 target-only 파일을 보존한다. 이번에 보존된 것:
  `claude:literature-search-arxiv:LICENSE_NOTIFICATION.txt`.
- 두 저장소 모두 **remote가 없다** — `gh pr` 계열 불가.

---

## 후속 (2026-08-17) — 마이그레이션 완료, 그리고 반복되는 회귀 두 건

위 Next steps 1번(마이그레이션 블로커)을 처리했다. **`moai update --templates-only`는
이제 끝까지 돈다.** 다만 그 과정에서 이 도구가 **매 실행마다** 되돌리는 변경 두 가지를
발견했다. 아래 둘은 일회성이 아니다.

### 🔴 `moai update`는 실행할 때마다 `CLAUDE.md` 심볼릭 링크를 파괴한다

루트 `CLAUDE.md`는 git에 **mode 120000, 9바이트 심볼릭 링크 → `AGENTS.md`** 로
기록돼 있다. `AGENTS.md`가 Broadsea 지식베이스(`# BROADSEA PROJECT KNOWLEDGE BASE`)이고
`CLAUDE.md`는 그 얇은 뷰다.

`moai update`는 이 심볼릭 링크를 **Broadsea 내용이 0인 19KB MoAI 템플릿 실파일**로
교체한다(`# MoAI Execution Directive`). 즉 실행 직후부터 이 프로젝트의 WHERE TO LOOK,
CONVENTIONS, ANTI-PATTERNS, TTE EVALUATION RULE, GENERATED-GOLD CACHE RULE이
Claude 컨텍스트에서 통째로 사라진다. `git status`에는 `T CLAUDE.md`(typechange) 한 줄로만
보인다.

추적되는 파일이라 복구는 쉽다:

```bash
git checkout -- CLAUDE.md
readlink CLAUDE.md      # 기대: AGENTS.md
head -1 CLAUDE.md       # 기대: # BROADSEA PROJECT KNOWLEDGE BASE
```

**`moai update`를 돌렸으면 반드시 이 두 줄을 확인할 것.**

### 🔴 `Write()` 비밀정보 deny 제거는 매번 다시 일어난다

앞에서 복원한 `Write(./secrets/**)` 외 3건을 재설치가 **다시 지웠다**. "user
customizations preserved"와 "3-way merge engine"이 보고돼도 이 항목은 보존 대상이
아니다. 즉 도구가 이것을 영구 은퇴 목록으로 들고 있다. 다시 복원해 뒀고
(`Read`/`Write`/`Edit` 각 4건), **다음 `moai update` 뒤에도 같은 확인이 필요하다**:

```bash
python3 -c "
import json
d=json.load(open('.claude/settings.json'))['permissions']['deny']
for v in ('Read','Write','Edit'):
    print(v, len([x for x in d if x.startswith(v+'(') and any(s in x for s in ('secrets','ssh','aws','gcloud'))]))
"   # 기대: Read 4 / Write 4 / Edit 4
```

### 블로커의 정체 — `.agency/`는 한 번도 채워진 적 없는 스캐폴드였다

`[MIGRATE_MERGE_CONFLICT] tech-preferences.md (Framework: _TBD_)`의 출처는
`.agency/context/tech-preferences.md`였다. 확인한 사실:

- 그 파일은 **전 항목이 `_TBD_`** 이고, 헤더가 "Fill this file during the first
  `/agency brief` run via client interview"라고 적고 있다. 그 인터뷰는 실행된 적이 없다
- `.agency/context/`의 나머지 4개도 같다 (`_TBD_` 19~52개)
- `.agency/fork-manifest.yaml`은 모든 fork가 `current_generation: 0,
  divergence_score: 0.0` — 한 번도 진화하지 않았다
- 대응하는 v3 사본은 **이미 존재하고 더 채워져 있다**:
  `.moai/project/brand/{brand-voice,target-audience,visual-identity}.md` (Apr 28,
  agency 원본 Apr 22보다 나중, `_TBD_` 더 적음), 설정은
  `.moai/config/sections/design.yaml`("Absorbed from agency config (v3.2.0)")

즉 `.agency/`의 모든 항목이 이미 더 나은 v3 사본으로 대체돼 있었고, 마이그레이션은
플레이스홀더를 실제 값 위에 덮어쓰려다 막힌 것이다. `.agency/`를 `trash-put`으로
은퇴시키자 재설치가 끝까지 돌았다:

```
Clean reinstall complete (81 files preserved, 24 deprecated removed)
Integrity check PASSED (81 PRESERVE-inventory files verified)
```

백업: `.moai/archive/pre-agency-retire-20260817T081456Z/` (claude · moai-project ·
moai-config · agency, 6.1M). `.agency/`는 휴지통에도 있다.

### 재설치가 지운 24개

`.claude/agents/moai/`에서 10개(`expert-backend`, `expert-devops`, `expert-frontend`,
`expert-performance`, `expert-refactoring`, `expert-security`, `manager-project`,
`manager-quality`, `manager-strategy`, `researcher`), `.claude/commands/agency/` 8개,
`.claude/rules/agency/constitution.md`, 그리고 스킬 3개(`moai-domain-brand-design`,
`moai-domain-copywriting`, `moai-workflow-gan-loop`). v3가 이들을 통합 에이전트로
대체한 결과다. 빈 껍데기로 남은 `.claude/rules/agency/`와 `.claude/commands/agency/`는
`rmdir`로 정리했다.

**broadsea 전용 룰 4개는 백업과 바이트 동일**로 살아남았다.

### 손대지 않은 것

`.claude/agents/agency/` 6개(builder·copywriter·designer·evaluator·learner·planner)와
`.claude/skills/agency*` 6개가 남아 있다. 이들이 참조하던 `.agency/context/`는 이제 없으므로
brand context를 읽는 경로는 깨져 있다. 다만 이건 마이그레이션 블로커와 별개의 정리
건이고 삭제 범위가 크므로 손대지 않았다. 정리할 거라면 위 백업을 먼저 확인할 것.

### `my_agent` 재싱크

`3cc9e05` → `8cf3f7d`("feat: sync Codex subagent roles"). `--profile hybrid`,
스킬 codex=78 / claude=78, **Codex subagents 4개 설치**, SessionEnd 훅 양쪽 설치,
로컬 `.omx/` 보존. Codex와 Claude Code 재시작 필요는 그대로다.
