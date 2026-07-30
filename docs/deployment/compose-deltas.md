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

## Closed 2026-07-31: `/app/output` is now mounted

`- ../artemis/output:/app/output` is declared in `compose/artemis-api.yml`.
Write to `/app/output` freely; it lands on the host.

**Pending apply.** The mount is declared but the running `artemis-api` predates
it, so it is not live yet. It takes effect on the next recreate — which must not
happen while a benchmark is running, because the queue drives the container over
`docker exec` and recreating it kills the in-flight model. Until then a
container-layer symlink bridges the gap:

```
/app/output/classifier_probe -> /app/tmp/classifier_probe   (mounted, so it escapes)
```

The host side is symlinked the same way, so both regimes resolve to one real
directory and neither the queue's `[ -f "$out" ]` skip check nor the container's
`--save` needs to know which is in force. The symlinks become redundant once the
mount is live; leaving them costs nothing and removing them mid-run would split
storage.

Verify after the next recreate:

```bash
docker exec artemis-api sh -c 'echo ok > /app/output/.wc'
cat artemis/output/.wc   # "ok" means mounted
```

### Why this was worth a mount rather than a convention

The old guidance was "harnesses write to `/app/tmp/model_benchmarks` instead."
That is a rule every *future* script has to already know, and twice it did not:

| When | What wrote to `/app/output` | Cost |
| --- | --- | --- |
| 2026-07-29 | six-study benchmark harness | six studies' results nearly lost |
| 2026-07-30 | `run_model_benchmark_queue.sh` probe step | ~50 GPU-minutes of probes stranded in the container layer |

Both exited `0`. Both printed a path. Neither produced a host file. A convention
cannot fail loudly; a missing mount can only be discovered by noticing an absence,
which is the hardest kind of defect to see. Mounting the obvious path removes the
class instead of re-teaching the rule.

**Rule going forward:** a script writing results inside this container may use
`/app/output` or `/app/tmp`. If a *new* container-side output path is ever
introduced, add the mount in the same commit — never the path alone.

## Reapplying

There is no automation. After a fresh checkout or a Compose reset, diff the file
against this list and reapply by hand, then:

```bash
docker compose --profile default up -d artemis-api
docker exec artemis-api ls /app/scripts    # mount present
```

A restart is not enough when the change is to a bind-mounted file's contents:
Edit/Write replaces the host inode and Docker follows the old one.
