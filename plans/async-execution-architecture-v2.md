# Design Note: Async Execution Architecture (v2 — single runtime)

**Status:** v2 — approved for implementation. Supersedes
`async-execution-architecture.md` (v1: hybrid — async web tier + Celery for IM)
via the decision to port IM to async, which retires Celery entirely.
Decisions log at the end.

## Problem

All request handling was uniform: every POST enqueued a Celery task running the
whole VRE flow synchronously (`requests` + `time.sleep` polling), status via
Celery's result backend. Concretely:

- A whole Celery worker process burned per concurrent flow, although flows spend
  ~95 % of their time *waiting* on external HTTP (spawn polls, readiness waits).
- Missing/uneven HTTP timeouts; one unbounded poll loop (Jupyter).
- No record of *who* requested what; IM-created infrastructure untracked and
  never destroyed (`inf_id` existed only in worker memory).

## Key insight: three heterogeneous task classes

| | Latency | Wait cost | Side effects if interrupted | Durability needed |
|---|---|---|---|---|
| **T1 — infra deployment (IM)** | 10–60 min | low volume | **money** — orphaned cloud VMs | **high** |
| **T2 — orchestrated API flows** (Jupyter, MDDash) | 10 s–5 min | pure I/O waiting | cheap — hub culls half-spawned servers; user resubmits | low |
| **T3 — instant API calls** (Galaxy, ScienceMesh, VIP, OSCAR) | < 5 s | negligible | none | none |

## Architecture (v2)

**Uniform contract, single async runtime.**

### Contract (unchanged for clients)

- `POST /requests/*` → `202 {task_id}` (immediately); invalid crate → `400` synchronously.
- `GET /requests/{task_id}` → `{task_id, status, stage?, result?, error?}` (polled).
- New: `GET /requests/` (caller-owned listing), `DELETE /requests/{task_id}`.
- `GET`/`DELETE` are owner-enforced (403 on mismatch); anonymous flows
  (`owner=null`) stay open — the task_id acts as bearer credential.

### Execution: one async orchestrator, zero Celery

Every flow — T1/T2/T3 alike — executes as an `asyncio` background task inside the
uvicorn process that received the POST (spawned via `asyncio.create_task` after
202 is returned). All HTTP via `httpx` + per-call `tenacity` retry (transient
only: transport errors, timeouts, 408/429/5xx; other 4xx fail fast). Readiness
waits are **bounded** `asyncio.sleep` poll loops (fixes the unbounded Jupyter loop).

**IM is now async too.** The four im-client operations we use (auth-header
serialization, `POST /infrastructures`, `GET …/{id}/{state|contmsg|outputs}`,
`DELETE …/{id}`) are ~130 lines of a 1,894-line library with no session state —
ported as an ~100-line `httpx` client (`app/services/im_async.py`, **produced in
a separate session**; also fixes that library's missing timeouts and
verify-SSL-off defaults). The classic reason IM lived in Celery was the
sync-only client; with the port, Celery's remaining value (durability of the
long wait) is covered by the resume model below — **the Celery tier is deleted.**

### Durability model: resume, don't queue

- The Redis record (`task:{id}`; status/stage/result/error/owner/kind/**crate**/
  im_inf_id/im_outputs/resume_stage/destroyed_at/timestamps) persists enough to
  resume: the crate payload is stored at dispatch, `inf_id` the instant
  `create()` returns.
- A **recovery manager** (janitor loop) runs at startup and periodically:
  - `PROGRESS` + `resume_stage=IM_WAIT` + `inf_id` + no live local task ⇒
    **respawn the continuation** (the IM *server* kept deploying; we re-attach
    by polling state, then finish the VRE steps).
  - stale non-resumable flows (`updated_at` older than timeout) ⇒ FAILED;
    FAILED with attached `inf_id` ⇒ destroy the orphaned VM.
  - TTL auto-destroy of delivered VMs: implemented but **off** by default
    (`infra_max_lifetime=None`) — Scipion/Galaxy-TOSCA VMs are the deliverable.
- Crash matrix short version: uvicorn dies during IM wait ⇒ flow **resumes** on
  restart. uvicorn dies mid-T2 ⇒ FAILED, user resubmits (same as Celery
  acks-early status quo). IM provisioning fails ⇒ IM-side destroy (existing
  behavior) + FAILED.

### Lifecycle consequences (follow from T1, not optional)

- **Infra registry:** `inf_id` persisted immediately — no VM without a record.
- **User tracking + listing:** owner captured at dispatch (before the flow
  starts) ⇒ `GET /requests/` works uniformly across task types; horizon = record
  TTL (~24 h; longer history would be a separate, deliberate store).
- **`DELETE` semantics:** `task.cancel()` + `await destroy` — trivially local,
  no revoke-terminate.

### Component inventory

| Component | Justified by |
|---|---|
| FastAPI async handlers + in-process orchestrator tasks | T1/T2/T3 |
| Redis status records + user index | uniform contract, resume, lifecycle |
| `app/services/im_async.py` async IM client | T1 without a second runtime |
| Recovery manager / janitor | durability + orphaned-VM cleanup |

**Operated as a single uvicorn worker** (no `--workers N`): a flow lives in the
memory of the receiving worker; `GET` polling works from any process (Redis),
but the recovery liveness check must be unambiguous. One core suffices — all
in-process work is I/O-bound; blocking bits (`git clone`, zip) go via
`asyncio.to_thread`.

## Decisions log

1. **Uniform 202 contract** over honest 200-inline for T3 — zero client-side
   special cases; fast flows pay two Redis writes.
2. **Owner-enforced GET/DELETE** (403) — behavior change vs. today's open polling.
3. v1 considered a "combined celery task for IM-backed flows" and a
   "split/orchestrator-polls-AsyncResult" variant — **superseded** by (4).
4. **Async IM port (separate session) ⇒ Celery retired entirely.** Durability via
   resume-from-`inf_id`, not broker at-least-once (today's acks-early Celery
   loses mid-flight tasks anyway — not a durability downgrade).
5. **Per-call retries, never whole-flow retries** (a retried IM create = a VM).
6. **Conservative janitor defaults:** orphan-reap on; delivered-VM TTL off.

## Trade-offs / open questions

- **Durability ceiling:** restart ⇒ resume only for IM-in-flight; T2 flows are
  lost (acceptable: user resubmits, hub-side culling; resume may be extended to
  Jupyter later — hub keeps the server, re-attach is feasible).
- **EGI token expiry** on late destroy/resume (tokens outlive ~1 h, not days):
  janitor handles auth failure gracefully; deployments needing long-lived cleanup
  should configure provider credentials server-side.
- **We own a ~100-line IM wire-format client** — small, but it's a compatibility
  surface vs. IM server evolution; guarded by unit tests + one integration run.
- **Delivered-VM TTL policy** left to operators (`infra_max_lifetime`).
- Invalid crate ⇒ `400` (was async FAILURE) — consumer teams should confirm.

## Future exits (not built, but unblocked)

- SSE/webhooks instead of polling (the record holds the whole state machine).
- Per-user quotas/audit from the owner field + index.
- If T2 flows ever must survive restarts, extend resume the same way (the record
  already persists what they'd need).
