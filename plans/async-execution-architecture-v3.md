# Design Note & Implementation Plan: Async Execution Architecture (v3)

**Status:** approved for implementation. Supersedes
`async-execution-architecture-v2.md` (Redis store) — team review replaced Redis
with SQLite; the deployment now needs **no added infrastructure services** (no
Celery, no Redis, no RabbitMQ). Decisions are grilled and locked; the decisions
log is at the end.

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

## Architecture (v3)

**Uniform contract, single async runtime, no added services.**

### Contract (clients)

- `POST /requests/*` → `202 {task_id}` (immediately); invalid crate → `400`
  synchronously (deliberate change from async FAILURE).
- `GET /requests/{task_id}` → `{task_id, status, stage?, result?, error?}`.
- New: `GET /requests/` (caller-owned listing), `DELETE /requests/{task_id}`.
- `GET`/`DELETE` owner-enforced: 403 on mismatch; anonymous flows
  (`owner=NULL`) stay open — the task_id acts as bearer credential and is
  excluded from listings.
- Unknown `task_id` → **404** (deliberate change from Celery's fabricated
  PENDING).
- Status vocabulary: `PENDING → PROGRESS → SUCCESS | FAILURE`, plus terminal
  **`DESTROYED`** (user tore down delivered infra via DELETE — distinguishable
  from failure). Mid-flight DELETE ⇒ `FAILURE("cancelled by user")`.

### Execution: one async orchestrator per flow, zero Celery

Every flow — T1/T2/T3 alike — executes as an `asyncio` background task inside
the uvicorn process that received the POST (`app.state.tasks` dict holds the
live handles). All HTTP via `httpx` + per-call `tenacity` retry (transient
only: transport errors, timeouts, 408/429/5xx; other 4xx fail fast). Readiness
waits are **bounded** `asyncio.sleep` poll loops (fixes the unbounded Jupyter
loop and its latent `exceptions.ServiceError` bug).

**IM is consumed only behind a protocol.** The dispatcher does **not** rewrite
IM: it defines `AsyncIMProtocol` (`typing.Protocol`) — `init(token)` /
`create(tosca_yaml) -> inf_id` / `get_property(inf_id, prop)` /
`destroy(inf_id)` / `wait_for_ready(heartbeat)` / `run(rp, heartbeat) ->
outputs`, with `IMError` semantics — and the concrete async client is delivered
by the **IM repo** (separate work, out of this plan's scope). Dispatcher keeps
only what is dispatcher-domain:

- TOSCA assembly (mem/gpu/disk input mapping, data-staging `get_data_*` nodes)
  as a small pure-Python module;
- `base_vre` injection: `await self._im_factory(token).run(rp, heartbeat=...)`;
  the default factory lazily imports the external package and raises a clean
  `IMError("async IM client not installed")` when absent, so development is
  never blocked;
- tests inject `FakeAsyncIM` (scripted state transitions) — everything stays
  green without the external package.

**Consumption decisions agreed post-review (recorded so the IM-repo PR and
this repo stay aligned):** the dispatcher creates with `asyncr=True` (never
block the create call on allocation; the wait loop polls with heartbeat);
`im_ssl_verify` config **defaults True** (library default stays `False`
for upstream harmony); the library's `wait()` carried the heartbeat-related
shape upstream instead — `on_poll(state)` callback (sync or async) and
`max_unknown` parameter — while the own wait loop stays dispatcher-side
(liveness depends on it). Deliberate non-actions: `contmsg` fetch on failure
stays caller-owned; `destroy(force=...)` stays an attribute-poke
(`client.options.force = True`) rather than a signature param; no doc
artifacts (glossary/ADRs) added to the im-client repo; the library version
string is NOT bumped in the feature branch (upstream owns releases).

### State: two stores, two durability requirements

- **Live tasks** — dict in the uvicorn process (`task_id → asyncio.Task`).
  Un-serializable handles; in-memory by nature.
- **Records** — one **SQLite** file, WAL mode + `synchronous=FULL`
  (per-commit durability out of the box, zero tuning, no service):

  ```sql
  CREATE TABLE IF NOT EXISTS tasks (
    task_id        TEXT PRIMARY KEY,
    sub            TEXT,            -- owner identity: "{provider}:{oidc-sub}"
    owner_json     TEXT,            -- {"sub","name","email"} | NULL (anonymous)
    kind           TEXT,
    status         TEXT NOT NULL,   -- PENDING|PROGRESS|SUCCESS|FAILURE|DESTROYED
    stage          TEXT,
    result_json    TEXT,
    error          TEXT,
    crate_json     TEXT,            -- crate metadata only; bytes never stored
    im_inf_id      TEXT,
    im_outputs_json TEXT,
    resume_stage   TEXT,            -- NONE | IM_WAIT
    destroyed_at   TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,   -- heartbeat: refreshed on every write
    expires_at     TEXT NOT NULL    -- uniform 24 h TTL from creation
  );
  CREATE INDEX idx_tasks_sub ON tasks(sub);
  CREATE INDEX idx_tasks_state ON tasks(status, updated_at);
  ```

  - Access: **`aiosqlite`** (MIT, zero transitive deps, maintained) — one
    connection, whose dedicated thread + internal request queue give us the
    async bridge and write serialization for free, instead of hand-rolling
    `check_same_thread=False` + an `asyncio.Lock` around stdlib `sqlite3`. Its
    own thread also keeps DB writes off the default `asyncio.to_thread` executor
    shared with Binder's `git clone` / zip handling.
  - Schema evolution: `PRAGMA user_version` + ordered migration list from day
    one (v1 = the create above).
  - Behind a `StatusStore` protocol: `SQLiteStatusStore` (prod),
    `InMemoryStatusStore` (tests). A RESP/Postgres backend is a documented
    future option for multi-instance — deliberately **not built**.
  - Every write refreshes `updated_at` — the janitor's heartbeat signal.

**Why not Redis/RabbitMQ** (team review outcome): durability in Redis is a
*configured* property (volume + AOF + fsync) vs SQLite's *default* property
(WAL + FULL); Redis is cache/broker culture, not a store-of-record habit.
RabbitMQ provides durable *message delivery*, not *queryable state* — status
polling, owner indices and the infra registry cannot be built on a queue, and
it would re-introduce the worker tier. Service-minimalism principle credited:
no new service is added without need.

### Durability model: resume, don't queue

The actual IM work happens **server-side**; our 30–60 min is observation.
Everything needed to reconstruct a flow therefore fits in the record:

- **Persisted at dispatch:** `crate_json` (metadata always — KB-scale, stable
  public format; the *built* payload is deliberately not persisted — it is a
  version-coupled intermediate representation, carries `raw_crate` anyway, and
  rebuilding is a millisecond-pure function via `VREPayloadBuilder.build`).
- **Persisted the instant `create()` returns:** `im_inf_id` +
  `resume_stage=IM_WAIT` — a VM can never exist before its record does.
- **Resume eligibility:** IM-backed flows that arrived *metadata-only*. A
  zip+IM flow (not expected in practice; nothing forbids it) executes normally
  but gets `resume_stage=NONE` — it degrades to FAILED + orphan-reap + user
  resubmit on restart, never a leak. File bytes are never persisted; if a real
  zip+IM use case appears, byte persistence is an additive migration.

**Recovery manager** (janitor, at startup + every `janitor_interval`):

- Record `PROGRESS` + `resume_stage=IM_WAIT` + `im_inf_id` + no live local task
  ⇒ **respawn continuation**: rebuild payload from `crate_json`, re-poll IM
  state (the server kept provisioning), fetch outputs, run VRE steps → SUCCESS.
  Same failure semantics as a live flow (contmsg to logs, destroy, FAILED);
  heartbeats (`updated_at`) resume with the continuation.
- Stale (`updated_at` older than `stale_task_timeout`), non-resumable ⇒
  FAILED("worker lost"); FAILED with `im_inf_id` & undestroyed ⇒ destroy
  (covers post-IM crashes too).
- `infra_max_lifetime` set ⇒ TTL-destroy of delivered VMs — **off** by default.
- T2 (Jupyter/MDDash) resume: **out of scope**; restart ⇒ FAILED + resubmit.
  Documented future exit only.

### Lifecycle consequences

- **Infra registry:** immediate `inf_id` persistence — no VM without a record;
  DELETE and the janitor close the loop.
- **Owner capture at dispatch (zero extra HTTP):** the middleware's identity
  string (`request.user` → `{provider}:{sub}`, per the existing claims format in
  `main.py`) keys ownership; `name`/`email` stored for display; no userinfo
  fallback calls on the authenticated router.
- **Listing:** `GET /requests/` = indexed `WHERE sub = ?`, expired rows
  filtered on read; horizon = 24 h TTL (longer history is a separate product
  decision with data-protection review — out of scope).
- **DELETE:** cancels the local task (if running), destroys infra if
  `im_inf_id`, then `DESTROYED` (delivered) or `FAILURE("cancelled")` (in-flight).

### Component inventory

| Component | Justified by |
|---|---|
| FastAPI async handlers + in-process orchestrator tasks | T1/T2/T3 |
| dict live-task registry | execution handles (in-memory by nature) |
| SQLite `tasks` table (WAL) | status, owner, infra registry, resume substrate |
| `app/http.py` shared httpx client + tenacity | all HTTP, unified retry |
| `AsyncIMProtocol` + `FakeAsyncIM` | T1 without a second runtime; IM impl external |
| Recovery manager / janitor | resume + orphaned-VM cleanup |

**Operated as a single uvicorn worker** (no `--workers N`): flows live in the
receiving worker's memory; polls could read SQLite from any process, but the
"does anyone own this flow?" liveness check must be unambiguous. One core
suffices — everything is I/O-bound; blocking bits (`git clone`, zip, sqlite)
go via `asyncio.to_thread`.

## Decisions log

1. **Uniform 202 contract** (200-inline for T3 rejected): zero client-side
   special cases.
2. **Owner-enforced GET/DELETE** (403; anon open by bearer task_id).
3. v1 Celery variants (combined/split) superseded by async IM consumption.
4. **Async IM via protocol, implementation in the IM repo** ⇒ Celery tier and
   its broker deleted entirely.
5. **Per-call retries (tenacity), never whole-flow retries** (a retried IM
   create = a VM).
6. **SQLite (WAL) store** over Redis (durable by default, no service) and
   RabbitMQ (category mismatch); dict for live tasks. Accessed via
   **`aiosqlite`**, not a hand-rolled `sqlite3` + `to_thread` bridge — the
   library owns the thread/queue serialization we would otherwise re-implement,
   and it has zero transitive deps (consistent with taking `tenacity`/`httpx`
   rather than hand-rolling retries/HTTP).
7. **Conservative janitor defaults:** orphan-reap on; delivered-VM TTL off.
8. **Resume = crate_json + inf_id + IM_WAIT**, metadata-only IM flows; zip+IM
   degrades; T2 resume out of scope; payload persistence rejected.
9. **Owner = middleware identity (`{provider}:{sub}`)** at dispatch.
10. **`DESTROYED` terminal state; unknown task_id = 404; invalid crate = 400.**

## Trade-offs / open questions

- **Single-host coupling:** SQLite ties records to the web host's volume;
  multi-instance later ⇒ swap backend behind `StatusStore` (RESP/Postgres),
  flow code untouched.
- **Expiring user tokens for IM lifecycle operations** — see the open
  discussion note below.
- **External IM dependency:** release of IM-backed flows gates on the IM repo's
  package; rest of the release ships independently (lazy factory + fake).
- **Contract changes requiring consumer notice:** 400 on invalid crate, 403 on
  foreign owner, 404 on unknown id, new `DESTROYED` state.

### Open for team discussion: IM lifecycle operations with expiring user tokens

**Limitation.** IM auth on the EGI provider path (and the OpenStack
`3.x_oidc_access_token` path) reuses the *user's* OIDC access token, captured at
dispatch. Those tokens live ~1 h, but IM lifecycle operations do not: orphan
reaping, the optional delivered-VM TTL janitor, a user's `DELETE` hours later,
and resuming a flow that sat queued all run long after expiry — the destroy call
then fails auth, the VM stays up, and cleanup silently falls back to manual ops
intervention. The same clock can even bite a *live* 60-minute deployment, whose
late `state` polls may outlive the token.

**Proposed direction (for team decision, not resolved here).** Decouple
infrastructure-lifecycle credentials from the per-user session token: give the
dispatcher its own long-lived IM credential in settings (an ops-owned service
account / robot token, or the existing OpenStack static-password path) used for
janitor, recovery-scan and `DELETE` operations, with the user token used only for
the initial dispatch. A lighter alternative is to persist the EGI refresh token
at dispatch and mint fresh access tokens on demand (requires `offline_access`
and secure refresh-token storage). Both are security/operations trade-offs, not
purely technical ones — hence called out for team discussion rather than decided
unilaterally.

## Implementation plan

Branch: `feature/async-execution` (exists). Two PRs + one integration gate.

**PR-1 — foundation & ports (P0–P2):**

- P0: deps (`httpx>=0.27,<1`, `tenacity>=8.2`, `aiosqlite>=0.22,<1`,
  `pytest-httpx>=0.30`; drop `aiohttp`) + config: `db_path`, `status_ttl=86400`, `janitor_interval=60`,
  `stale_task_timeout=3600`, `infra_max_lifetime=None`, `http_default_timeout=30`
  (+ pool limits), `http_retry_attempts=4`, backoff 1–30 s,
  `jupyter_poll_interval=10`/`jupyter_wait_max_time=900`,
  `mddash_poll_interval=5`/`mddash_wait_max_time=600`; add the 4 previously
  undeclared settings (`im_max_time`, `im_sleep`, `im_max_retries`, and drop
  `redis_port` usage with Celery). Mirror all in the ansible config template.
- P1: `TransientHTTPError`; `app/http.py` (lifespan AsyncClient +
  tenacity-wrapped helpers, `retry=False` escape hatch); `app/status_store.py`
  (protocol + `SQLiteStatusStore` with schema/migrations above +
  `InMemoryStatusStore`); unit tests (retry matrix, store CRUD/index/TTL/infra).
- P2: async ports — `token_utils`, `vault`, `base_vre` (async `post`, store
  injection, `AsyncIMProtocol` + `im_factory`, TOSCA module extracted from the
  old sync IM into dispatcher ownership) and all VREs in order
  scipion→sciencemesh→vip→galaxy→oscar→jupyter→binder(`to_thread`)→mddash
  (httpx cookie flow); each with its test file migrated to `httpx_mock`
  (`pytest.ini`: `asyncio_mode = auto`).

**PR-2 — web layer, recovery, ops (P3–P5) + integration gate:**

- P3: async routers (parse/build in handler ⇒ 400; owner capture; record create;
  orchestrator spawn + registry; 202) + `GET` (403/404) + `GET /` listing +
  `DELETE` (cancel/destroy/`DESTROYED`) + lifespan wiring (http client, store,
  registry, recovery manager) + `app/vre_runner.py` shared flow executor.
- P4: recovery manager (startup scan + periodic janitor per the rules above).
- P5: ops — ansible drops `redis:` and `worker:` services, adds the DB volume;
  requirements drop `redis`; README: architecture, single-worker rationale, new
  endpoints, contract changes; one dev-instance smoke run (Galaxy, Jupyter-zip,
  TOSCA crate, DELETE-during-provisioning, kill-restart-during-IM ⇒ resume).
- **Integration gate (before PR-2 merge):** install IM repo's async client,
  wire `im_factory` default, delete `app/services/im.py`, drop
  `im-client`/`radl`, **one live IM smoke run** (`create → wait → outputs →
  destroy`, on a real IM with real credentials).

Rollout: drain-then-deploy (no in-flight migration; single pilot instance),
consumers notified of the contract changes.
