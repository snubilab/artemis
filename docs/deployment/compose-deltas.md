# Compose deltas that live outside version control

`compose/*.yml` sits at the Broadsea root, which is deliberately not a git repo
(CLAUDE.md: "not a Git root; `atlas-dev/` is a nested Git checkout"). This repo
cannot track files above its own worktree, so every change made to a Compose
fragment exists only on this machine's disk and is lost on a fresh checkout.

This file records the deltas so they can be reapplied. It is a workaround for the
versioning gap, not a substitute for it — nothing here is enforced, and a drifted
Compose file will not announce itself.

## compose/artemis-api.yml

### 1. Mount `scripts/` (added 2026-07-29)

```yaml
    volumes:
      - ../artemis/src:/app/src
      - ../artemis/scripts:/app/scripts     # <- this line
```

Benchmark and evaluation harnesses are iterated on while the stack is up. Without
the mount they exist only in the image, so every harness edit needs a rebuild or a
`docker cp` that disappears on the next restart.

### 2. Mount the baseline worktree read-only (added 2026-07-29)

```yaml
      - ../artemis-eval-baseline:/baseline:ro
```

Now unused. The arm A/B was rebuilt as a function swap rather than a checkout, so
this can be dropped once `artemis-eval-baseline/` is removed.

### 3. `AGENT2_CRITIC_MODEL_TIER` commented out (2026-07-29)

It pinned `gpt-4o`, which meant a local-model run still sent the critic to OpenAI
on Condition, Drug and Measurement — roughly 90% of criteria — with nothing in the
output showing it. `select_critic_model` now defaults to "follow LLM_MODEL". Set
this only to override deliberately; `auto` restores the old domain-based tiering.

## Known gap: `/app/output` is not mounted

Anything a script writes to `/app/output` lives only inside the container and is
lost when it is recreated. Six studies' benchmark results were nearly lost this
way. Harnesses write to `/app/tmp/model_benchmarks` instead, which is mounted at
`artemis/tmp/`.

Adding an `output` mount would be the cleaner fix and needs a container recreate.

## Reapplying

There is no automation. After a fresh checkout or a Compose reset, diff the file
against this list and reapply by hand, then:

```bash
docker compose --profile default up -d artemis-api
docker exec artemis-api ls /app/scripts    # mount present
```

A restart is not enough when the change is to a bind-mounted file's contents:
Edit/Write replaces the host inode and Docker follows the old one.
