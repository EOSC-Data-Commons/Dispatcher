# Design Note: Async Execution Architecture

**Status:** proposal for discussion — nothing implemented yet.

## Problem

All request handling is uniform today: every POST enqueues a Celery task that runs
the whole VRE flow synchronously (`requests` + `time.sleep` polling loops), with
status tracked via Celery's result backend. Concretely this means:

- A whole celery worker process is burned per concurrent flow, even though flows
  spend ~95 % of their time *waiting* on external HTTP (spawn polls, readiness waits).
- No HTTP timeouts in several call sites; one unbounded poll loop (Jupyter).
- No record of *who* requested what, and no way to clean up IM-created infrastructure
  (`inf_id` exists only in worker memory; successful VMs are never destroyed).

## Key insight: three heterogeneous task classes

| | Latency | Wait cost | Side effects if interrupted | Durability needed |
|---|---|---|---|---|
| **T1 — infra deployment (IM)** | 10–60 min | low volume | **money** — orphaned cloud VMs | **high** |
| **T2 — orchestrated API flows** (Jupyter, MDDash) | 10 s–5 min | pure I/O waiting | cheap — hub culls half-spawned servers; user resubmits | low |
| **T3 — instant API calls** (Galaxy, ScienceMesh, VIP, OSCAR) | < 5 s | negligible | none | none |

One execution model cannot serve all three well. The current design treats
everything as T2-shaped background jobs; that is the root of most of the pain.

## Proposed architecture

**Uniform contract, differentiated execution.** Clients always see one shape:

- `POST /requests/*` → `202 {task_id}` (immediately)
- `GET /requests/{task_id}` → `{task_id, status, stage?, result?}` (polled)

…while internally each class gets the execution model its properties demand:

1. **An async orchestrator** sequences every flow — i.e. each flow's step chain
   (`VRE.post()`: dependent API calls + waits) runs as an `asyncio` background
   task *inside the FastAPI/uvicorn process that received the request*
   (spawned via `asyncio.create_task` after the handler returns 202), not in a
   separate worker process. All HTTP via `httpx` + `tenacity`
   (exponential backoff with jitter, transient errors only: transport errors,
   timeouts, 408/429/5xx — permanent 4xx fail fast). Readiness waits are bounded
   `asyncio.sleep` poll loops (this also fixes the unbounded Jupyter loop).
   T2 and T3 flows never leave this layer.
2. **Exactly one Celery task** remains: `im_create_infra` (plus
   `im_destroy_infra`). IM is sync-only (`im-client`), long, and expensive-sided —
   the textbook durable-queue workload; it stays untouched. The orchestrator
   enqueues it and polls `AsyncResult` non-blockingly before continuing its
   async steps (e.g. TOSCA-Galaxy: IM, then `workflow_landings` POST).
3. **Status lives in Redis records** (`task:{id}` — status/stage/result/error/
   owner/updated_at, TTL ~24 h), written by both the orchestrator and the IM task.
   Polling endpoint reads it — decoupled from Celery's result backend.
   Contract unchanged, so **no client changes**.

### Lifecycle consequences (not optional extras — they follow from T1)

- **Infra registry:** `inf_id` is persisted *the moment IM's `create()` returns*,
  before any waiting — no VM may ever exist without a durable record.
- **User tracking:** owner OIDC identity captured at dispatch into the record →
  audit, future quotas, and ownership-based authz become possible.
- **User task listing:** because owner is recorded *at dispatch, before the
  execution-model fork*, `GET /requests/` ("all my flows") works uniformly across
  T1/T2/T3 via a per-user Redis index (`user:{sub}:tasks`, written at dispatch,
  lazily filtered on read against TTL'd records). Listing horizon = status-record
  TTL (~24 h); longer history would need an explicit, separate summary store —
  deliberate product decision (data protection), not a default.
- **Cleanup:** `DELETE /requests/{task_id}` (user-triggered destroy) + a periodic
  janitor that reaps orphaned VMs and marks stale records FAILED.

### Component inventory (deliberately small)

| Component | Justified by |
|---|---|
| FastAPI async handlers + in-process orchestrator tasks | T2/T3 |
| Redis status records | uniform contract + lifecycle tracking |
| 2 Celery tasks (`im_create_infra`, `im_destroy_infra`) | T1 only |
| Infra registry + janitor | T1's money-burning side effects |

That's it — Celery shrinks from "runs everything" to "runs the one thing that
needs it".

## Deliberate decisions (discussion points welcome)

1. **Uniform 202 contract** rather than honest 200-inline for T3: clients always
   poll. Cost: fast flows pay 2 Redis writes + clients make ≥2 requests for 2 s
   work. Benefit: zero client-side special cases.
2. **Per-call retries, never whole-flow retries.** Today `vre_from_rocrate`
   retries the *entire* flow on `GalaxyAPIError`; per-call tenacity retries are
   strictly finer-grained.
3. **In-process orchestrator, not an async job runner (taskiq/ARQ).** Simplest
   option that fits pilot scale. Accepted ceiling: worker restart kills in-flight
   T2 flows (janitor marks them failed; user resubmits). If flows ever need
   "must resume" semantics, swap the invocation layer only — VRE code unchanged.
4. **No fake-async IM.** The sync library is left alone inside its Celery task.

## Considered alternative: single celery task for IM-backed flows

Instead of "async orchestrator enqueues IM task and continues afterwards", the
*entire* IM-backed flow runs as one celery task: sync IM creation/wait, then the
async VRE steps via `asyncio.run(vre.post())` inside the same task. Non-IM flows
stay in-process in uvicorn.

- **Main gain:** no continuation to orphan — if uvicorn dies during the 30–60 min
  IM wait, the flow completes regardless (web tier fully disposable on this path).
  Also removes the bounded-`AsyncResult`-polling edge case; janitor's liveness rule
  becomes uniform (stale record ⇒ fail + reap).
- **Footgun:** whole-task celery retries are forbidden here (today's
  `autoretry_for=GalaxyAPIError` pattern would re-run `IM.create()` per retry →
  duplicate VMs). Transient resilience stays at the per-call tenacity level; IM
  retry must be idempotent via the registry if ever added.
- **Neutral:** celery worker slot occupied IM+ε vs IM only; two invocation sites
  either way; async VRE code identical, only the invocation adapter differs.
- **Take:** arguably better on crash semantics than the split; final call after
  team discussion.

## Trade-offs / open questions for discussion

- **Durability ceiling of in-process execution** — is "lost flow ⇒ user resubmits"
  acceptable? (Celery's current config gives no real durability either:
  default acks-early, crashed flows sit as `STARTED` forever.)
- **EGI token expiry for deferred destroy** — the janitor destroying a VM days
  later may hold an expired user token (EGI auth path); needs graceful handling
  or provider credentials from settings.
- **Auto-destroy TTL for delivered VMs** — Scipion/Galaxy-TOSCA VMs *are* the
  deliverable; a too-short TTL kills in-use infra. Default policy?
- **Single uvicorn worker for execution.** With in-process orchestration, a flow
  lives only in the memory of the worker that received its POST; other workers
  can't see it. `GET` polling is unaffected (status is in Redis), but "is this
  flow still alive?" — the decision the janitor needs to mark tasks FAILED and
  reap dead IM infra — is ambiguous across N workers without per-task heartbeats
  or leases in Redis. One worker makes that check trivial (local task registry).
  One core is plenty: everything on the loop is I/O-bound, and CPU-bound work is
  already offloaded (IM → Celery workers, blocking calls → `asyncio.to_thread`).
  If capacity/HA ever demands more, add heartbeats — or move orchestration to an
  async worker (taskiq/ARQ) and the constraint disappears entirely.

## Future exits (not built, but unblocked)

- Async worker (taskiq/ARQ) for durability — swap invocation layer only.
- SSE/webhooks instead of polling — the Redis record already holds the state machine.
- Per-user quotas/audit from the owner field.
