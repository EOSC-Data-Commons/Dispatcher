# Async Execution Architecture (v4)

**Status:** implemented on `feature/async-execution` (phases R, D0–D6 as
separate commits; the v3 prototype is preserved on
`celery2async-prototype`). Outstanding before merge: the two live gates
from D5 — one live EGI Check-in login verifying the credential row
carries a refresh token, and one live IM smoke run (create → wait →
outputs → destroy) — plus the D6 operator items that live outside the
repo: scheduling off-host registry backups, executing (and documenting)
the restore drill, and verifying the non-root container in a real
deployment. Replaces the v3 design note.

This note is self-contained. It describes what we will build, the decisions
behind it, and the implementation order. Language note: the project glossary
(`GLOSSARY.md`) calls the URL returned to the user the **callback URL**.

## 1. The problem

Every POST currently starts a Celery task that runs the whole flow
synchronously (blocking HTTP, `time.sleep` polls). That wastes a worker
process per flow, since flows spend most of their time waiting. Other
issues found during review:

- No HTTP timeouts in several places; one poll loop has no upper bound.
- No record of which user started which task.
- Infrastructure Manager (IM) deployments are never cleaned up. The
  infrastructure id (`inf_id`) only exists in worker memory; a crash leaves
  a paid VM running with no record.

## 2. The three kinds of work

Everything the dispatcher does falls into one of these, and each needs a
different runtime:

| Type | Duration | Cost of waiting | Damage if interrupted |
|---|---|---|---|
| T1 — IM deployment | 10–60 min | low volume | orphaned cloud VMs (money) |
| T2 — multi-step API sequences (Jupyter, MDDash) | 10 s–5 min | pure I/O waiting | minor: hub cleans up; user retries |
| T3 — one-shot API calls (Galaxy, ScienceMesh, VIP, OSCAR) | < 5 s | none | none |

A sync worker pool is wrong for waiting work. Async I/O is cheap: one
event loop can supervise hundreds of waiting flows.

## 3. What v4 changes compared to v3

The v3 design tried to make flows **resume** after a restart (persist the
request crate, the IM id, and continue where the crash happened). That
turned out to be the most complex part of the design for a benefit that is
small at our restart frequency. v4 drops it.

- **No resume.** A restart kills the flow. The janitor marks it FAILED and
  destroys any half-deployed IM infrastructure. The user resubmits.
- **Slimmer task record.** The SQLite table no longer stores the request
  crate, the IM outputs, the IM token, or the resume stage. Those four
  fields existed only for resume.
- **Slimmer janitor.** The janitor now has one job per record, in two
  flavors:
  - **At startup**, anything marked PENDING/PROGRESS is by definition dead
    (the process that ran it just restarted) ⇒ mark it
    `FAILURE("worker lost")` immediately and destroy its IM infra. No
    grace period, because no second worker can own the flow.
  - **In the periodic scan**, three checks: flows whose task disappeared
    without writing an outcome ⇒ same FAILED("worker lost"); failed flows
    whose IM infra was never destroyed ⇒ destroy it, retrying on later
    scans if the call fails; delivered VMs older than
    `infra_max_lifetime` ⇒ destroy — implemented but **disabled** unless
    an operator sets the value.
- **Better IM auth for cleanup.** Instead of persisting the user's access
  token per flow, we keep one **refresh token per user**, captured at login,
  and exchange it for a fresh access token whenever asynchronous cleanup
  needs IM credentials. See section 8.
- Caller token reads no longer go through a shared middleware singleton
  (which held the *last login's* token — a real multi-user bug). This is
  already fixed on master by Auth Design 1: every protected route verifies
  the request's own token via `app.security.oauth2_scheme`, so dispatch
  and DELETE always carry the caller's token.

Everything else from v3 stays. Section 9 lists those decisions so reviewers
do not have to re-derive them.

## 4. The API (what clients see)

Unchanged from v3:

- `POST /requests/…` → `202 {task_id}` immediately. Invalid crate → `400`
  right away (no async failure round trip).
- `GET /requests/{task_id}` → `{task_id, status, stage?, result?, error?}`;
  unknown id → `404`.
- `GET /requests/` → the caller's records only.
- `DELETE /requests/{task_id}` → cancels and tears down; `403` if not the
  owner (anonymous records stay open to anyone holding the task_id).
- Statuses: `PENDING → PROGRESS → SUCCESS | FAILURE`, plus terminal
  `DESTROYED` (user tore down the delivered thing).

## 5. How a flow executes

- The POST handler validates the crate, creates the record, and starts one
  asyncio task per flow in the single uvicorn worker.
- All HTTP goes through one shared `httpx.AsyncClient` with per-call
  `tenacity` retry: only transient failures retry (transport errors,
  timeouts, 408/429/5xx). Everything else fails fast. Poll loops
  (Jupyter spawn, MDDash, IM wait) are bounded `asyncio.sleep` loops.
- IM runs behind a small protocol (`AsyncIMProtocol`). The dispatcher keeps
  TOSCA assembly and the bounded wait loop (with a per-poll heartbeat).
  The wire client is `imclient.AsyncIMClient` from the IM repo (our local
  clone `../im-client`, branch `feature/async-client`).

## 6. What gets stored

Three stores, three lifetimes:

1. **Live task handles** (in-memory dict). Gone on restart — by design.
2. **Task records** (SQLite via **aiosqlite**, WAL). Purpose: the GET
   contract, owner checks, and the *infrastructure registry*.
   Columns: `task_id, sub, owner, kind, status, stage, result, error,
   im_inf_id, destroyed_at, created_at, updated_at, expires_at`.
   That is all. No crate, no tokens, no resume fields.
3. **Credentials** (SQLite, same file). Purpose: the only long-lived
   per-user data. Columns: `sub (PK), access_token, refresh_token,
   updated_at, expires_at`. See section 8.

The task-record class and store protocol stay as in v3 (`StatusStore`
protocol; SQLite and in-memory backends).

## 7. How failures play out

| Event | What happens |
|---|---|
| Any exception in a flow | `FAILURE` with the error text; last stage kept as context ("died while …") |
| Success | `SUCCESS` + callback URL; stage cleared |
| Restart (any flow) | Record left in PENDING/PROGRESS is orphaned by definition ⇒ janitor marks `FAILURE("worker lost")`; IM infra reaped |
| Deployed IM infrastructure outlives a failed flow | Janitor destroys it on the next scan (retries on later scans if the call fails; "already gone" (404) counts as success) |
| Delivered VM exceeds `infra_max_lifetime` | Janitor destroys it — **off by default**, stays off unless an operator sets it |

The point of the table: with resume gone, the rules are small and the
invariant is simple — **every VM has a record, every record with live infra
keeps its `im_inf_id`, and dead records lose their VMs**.

## 8. IM auth for cleanup: per-user refresh tokens

Cleanup does IM calls after the dispatch has ended. A plain access token
(~1 h) could never cover that. Instead:

1. **Capture at login.** Auth Design 1 (merged to master before this
   plan's implementation) removed the `fastapi_oauth2` middleware
   entirely; the login callback in `app/routers/auth.py` already calls
   `security.on_login_tokens(sub, access_token, refresh_token)` — a seam
   left empty for exactly this plan. D2 gives it a body: write the user's
   EGI `refresh_token` plus the access token into the credentials table,
   keyed by OIDC `sub`. (`offline_access` is already in
   `app.checkin.LOGIN_SCOPE`, so Check-in issues refresh tokens; EGI sends
   it in the standard response.)
2. **Use for lifecycle calls.** When the janitor or an orphan-reap needs IM
   auth, it reads the user's row, exchanges the refresh token for a fresh
   access token (EGI Check-in token endpoint, `grant_type=refresh_token`,
   client id+secret from settings), and destroys the infrastructure.
3. **Rotation.** EGI rotates refresh tokens. Each exchange writes the new
   refresh token back keyed by the same `sub`.
4. **Degrade gracefully.** No/rotated-out refresh token ⇒ log and retry next
   scan. User-facing calls (dispatch, DELETE) always use the fresh session
   token, so users never see cleanup failures.

Bonus fix from this design — already landed: master's Auth Design 1
removed the shared `request.auth.provider.access_token` singleton; tokens
are now verified per request (`oauth2_scheme`), so two concurrent users
can no longer receive each other's token. The credentials store is read
only by asynchronous cleanup (janitor, orphan reaps); user-facing calls
always use the request's own token.

Recorded fallback, if EGI does not hand refresh tokens to our client on the
dev instance: an operator-owned IM service credential in settings. Rejected
as the primary because it adds a second identity to operate.

## 9. v3 decisions that still apply

Listed so nobody re-argues them in review:

- Uniform `202 + poll` contract (web tier and orchestration stay
  differentiated behind it).
- Owner-enforced GET/DELETE (403), anonymous flows open by bearer task_id.
- Status vocabulary plus terminal `DESTROYED`.
- Stage is a progress breadcrumb: written in-flight, kept on FAILURE as
  death context, cleared on SUCCESS/DESTROYED.
- At destroy, the callback URL in `result` is set to null — never advertise
  a link to something we just destroyed.
- Retries are per-call only, never whole-flow (a retried IM create = a VM).
- Monitored waits are bounded by settings
  (`im_max_time`, `im_sleep`, `im_max_retries`, jupyter/mddash polls).
- pyyaml/httpx/TOSCA assembly dispatcher-owned; TOSCA+auth mirrored from
  the retired sync IM.
- aiosqlite for the store (avoid hand-rolled `sqlite3` threading).
- Operate one uvicorn worker (liveness unambiguous; everything is I/O-bound).
- VRE interface has `delete()` (no-op default; real teardown where the VRE
  creates remote state — OSCAR deletes its cluster service).
- IM create is called with `asyncr=True` (never block on allocation).
- IM endpoint TLS verify defaults true (`im_ssl_verify`).
- IM-repo PR rules: exceptions not tuples; no self-assigned version bump;
  `wait()` carries `max_unknown` + `on_poll` (sync-or-async callback);
  `force` via attribute poke only; no doc artifacts in the IM repo.

## 10. Decisions log (what changed in v4)

1. Resume is dropped; crash ⇒ FAIL + reap + user resubmit.
2. Task record loses crate/outputs/token/resume columns.
3. Janitor simplifies to startup fail-fast + periodic stale/reap/TTL-off.
4. IM cleanup auth = per-user refresh token captured at login.
5. Caller access token is per-request (Auth Design 1 already verifies the
   request's own token); the credential store is read only by asynchronous
   cleanup, never by user-facing calls.
6. Non-IM teardown keeps working via the record's delivered URL only
   (`delivered_url` hint) — crate is gone at DELETE time. (OSCAR today.)
7. Startup orphans fail immediately, not after the stale timeout.

## 11. Implementation order

Work on top of the current codebase, as separate commits per phase below;
keep the test suite green throughout.

- **R — re-land the prototype.** The v3 prototype lives off-branch (branch
  `celery2async-prototype`, preserved from the `celery2async` stash; it was
  written against pre-Auth-Design-1 master). First commit series: apply it,
  resolve conflicts, and adapt its identity plumbing to Auth Design 1 —
  drop `request.scope["user"]`/`scope["auth"]` reads; routers pass the
  token from `Depends(oauth2_scheme)` and dispatch derives the owner via
  `security.verify`. The bundled extras in the stash (AGENTS.md,
  docs/agents/, the two plans comparisons, `test-config-render.sh`) do not
  land. Suite green before D0 starts.
- **D0 — slim the record.** Drop `crate_json, im_token, im_outputs,
  resume_stage` from `TaskRecord`, both backends, `_UPDATABLE_FIELDS`,
  tests. Suite green.
- **D1 — delete the resume path.** `base_vre`: remove resume params and
  `_persist_infra_finish`; `_on_inf_created` keeps only the `im_inf_id`
  write. `AsyncIMProtocol.resume` and `im_async.resume` out.
  `vre_runner`/`dispatch` lose resume params and the `im_token` record
  field. DELETE-time VRE teardown switched to the `delivered_url` hint
  (drop crate rebuilding on DELETE).
- **D2 — credential store.** Protocol + SQLite + in-memory impls; capture
  through the existing `security.on_login_tokens` seam (Auth Design 1
  already requests `offline_access`); user-facing calls keep the
  per-request token — only cleanup reads the store.
- **D3 — refresh helper.** `exchange_refresh_token()` using the shared
  http/tenacity layer; rotation write-back.
- **D4 — janitor.** Delete `_respawn` and the crate-rebuild import; startup =
  immediate FAILED("worker lost") + reap; periodic = stale check + reap
  retries + TTL (off). Reap auth via D2/D3.
- **D5 — verification.** Dedicated tests for D2–D4 (rotation, revoked token
  → log + retry, startup-orphan rule), one live EGI check that the
  credential row carries a refresh token after login, one live IM smoke
  (create → wait → outputs → destroy) before merge.
- **D6 — production hardening (from the audit round).**
  - *Readiness check:* alongside the trivial `/healthz` liveness probe
    (whose compose wiring — healthcheck, restart policy, autoheal — is
    tracked as a GitHub issue and applies to the current code too), add
    a readiness endpoint that opens and closes the status DB. Rationale:
    in this architecture an unusable status store fails every dispatch at
    record creation; readiness should say "not ready" before traffic
    discovers that the hard way.
  - *Janitor destroy failures:* treat IM destroy 404/410 as success (infra
    already gone ⇒ mark `destroyed_at`, stop retrying); retry genuine
    failures with a per-record attempt counter that escalates to a visible
    worklist instead of warning-forever; expose a reap-failure counter for
    alerting; auth fallback chain = refresh token → operator credential
    (runbook).
  - *Registry backup:* scheduled online backups of the SQLite file (the
    `.backup` API is safe during writes), shipped off-host; a documented,
    actually-executed restore drill (losing the registry orphans every
    tracked VM; IM's per-credential infrastructure list is the partial
    recovery path).
  - *Token-file hygiene:* web container runs as a non-root user with
    700/600 on the DB directory/file; backups inherit the same protection
    class as the tokens (an unprotected backup undoes the permissions).
    Row TTL and refresh rotation (already in D2/D3) keep the number of
    live tokens small.

Delete the resume-lifecycle test suites when their code goes; keep the rest
of the suite, and its v3 invariants (stage/result semantics, delete hooks),
green.

## 12. Trade-offs we accept on purpose

- If the dispatcher restarts mid-IM-deployment, the in-flight VM is
  destroyed instead of delivered (v3 resumed it). The user sees
  `FAILURE("worker lost")` and resubmits — the cost of a restart is one
  wasted provisioning run. If that ever becomes expensive at our scale,
  v3's resume design is archived on `feature/async-execution` and can be
  reintroduced behind this schema.
- A stored refresh token is sensitive; it sits in the same SQLite file as
  the records, expiry TTL'd, and in the ops runbook for manual cleanup if
  it is lost or revoked. The file gets production-grade hygiene (non-root
  container, 700/600 permissions, protected backups — see D6): one read
  of that file impersonates every user to the VREs.
- v4 does not solve multi-instance deployments yet (single uvicorn worker);
  the store protocol leaves the door open.

## 13. Repo state for the executor

- Design notes: v1/v2/v3/v4 live in `plans/` on `feature/async-execution`.
- Base: master includes Auth Design 1 (`app/security.py`,
  `app/checkin.py`, `app/routers/auth.py`) — per-request JWT verification,
  the `on_login_tokens` login seam, and `offline_access` in the login
  scope. Python 3.13, uv-managed `.venv`, pytest suite under `test/unit`.
- The v3 prototype implementation is preserved off-branch on
  `celery2async-prototype` (full stash, including the extras that stay
  out of this branch). Phase R re-lands it here, adapted to Auth Design 1.
- The async IM wire client is `imclient.AsyncIMClient` from the local
  clone `../im-client`, branch `feature/async-client` (editable install;
  the PyPI `im-client==1.8.4` release ships no async client).
- Out of scope here: multi-instance operation (single uvicorn worker),
  whole-flow retries, resume (archived in v3's design and the
  `celery2async-prototype` branch).
