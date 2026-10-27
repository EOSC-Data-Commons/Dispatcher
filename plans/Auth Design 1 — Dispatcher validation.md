# Auth Design 1 — validation against the Dispatcher

**Status:** design validated 2026-10-27 against the installed stack
(EGI Check-in, this repo's code). **Implemented on `feature/auth-design-1`
with `fastapi-sso`** — the §8 migration was taken one commit later, so
the fastapi-oauth2 monkeypatching no longer exists (except the janitor —
deliberately deferred, see §4.1). Companion to *Auth Design 1 — FastAPI
resource server + IdP token as session*; this file records what holds,
what breaks, and what applying it here actually means. Verdict first:

> The design is sound and its library research is real — every seam it
> patches exists in the installed version with the signatures it assumes.
> But it is written against fastapi-oauth2 **master**, the dispatcher runs
> **1.3.0** (one wiring piece does not exist), and it is
> **Keycloak-generic** while the dispatcher is **EGI Check-in** — whose
> token shape this repo's own code disagrees with the plan about. Apply
> it only after the gate in §2 passes, and after making the three
> decisions in §4.

## 1. What validates cleanly (checked in this repo, not from memory)

- **The monkeypatch seams are real and correctly shaped.**
  `Auth.jwt_decode(cls, token)` and `Auth.jwt_create(cls, token_data)` are
  classmethods on the installed 1.3.0 (`middleware.py:53,57`); the plan's
  `classmethod(lambda cls, data…)` / `staticmethod(_jwt_decode)` patches
  bind correctly against both call sites (`core.py:139` create,
  `middleware.py:115` decode).
- **Current minting is exactly what the plan rejects**: HS256 with a
  shared `Auth.secret` (`middleware.py:49-59`) — a second credential
  system with a symmetric secret. The rejection rationale holds here.
- **The custom callback seam is real.** `token_data()` parses the full
  IdP response into `core._oauth_client.token` (`core.py:131`) — the plan
  reads `access_token` (and a `refresh_token`, if issued) off exactly
  that object. Verified reading the source.
- **`on_error=` exists in 1.3.0** (`middleware.py:145`) — the plan's 401
  + `WWW-Authenticate` error-contract wiring works as written.
- **CSRF mechanics exist**: `security.py:18-20` copies the
  `Authorization` cookie into the header via metaclass — invariant #9's
  premise holds on this version.
- **PyJWT 2.10.1 is already in the venv** (transitive); add it to
  requirements explicitly (`PyJWT[crypto]`) when applying.

## 2. The gate: RESOLVED — a live EGI Check-in token was decoded (2026-10-27, aai-dev)

A real access token from the `aai-dev.egi.eu/auth/realms/egi` realm was
decoded and its JWKS endpoint probed. `token_utils.py`'s "opaque" docstring
is **wrong** — Check-in issues standard Keycloak JWTs. Findings that change
the plan:

- **JWT, RS256, kid-based JWKS.** The JWKS endpoint
  (`{issuer}/protocol/openid-connect/certs`) is live and publishes the
  matching key; `PyJWKClient` resolves it. The plan's verification
  mechanism works as designed. (The signature check on the pasted token
  itself failed — a chat-transport artifact: header and payload decode to
  perfectly coherent claims, one mangled character in the ~430-char
  signature segment suffices. Export a token via file to prove the
  signature end-to-end if desired.)
- **No `aud` claim — the plan's audience validation must be dropped.**
  The token carries `iss`, `sub`, `azp`, `scope`, `exp`, no `aud`. The
  design's `AUDIENCE`/`require: aud` would reject every real Check-in
  token. Adaptation: validate `iss` (pinned per env) + `exp` + signature,
  no `audience=`; optionally soft-check `azp`. (You cannot register
  audience mappers on a federation realm you don't operate.)
- **No `email` / human name in the token.** Present claims: `sub`,
  `voperson_id`, `preferred_username` (all the opaque
  `<hash>@egi.eu` id), `eduperson_assurance`, `scope` (space-delimited
  string), `jti`, `sid`, `acr`, `azp`. Consequences: owner enforcement
  keys on `sub` (sufficient); `Claims(email=…, display_name=…)` yields
  nothing from the JWT — capture display fields once at login from the
  userinfo round-trip the callback already performs, or drop them from
  owner records.
- **`offline_access` appears in `scope`** — refresh tokens ARE obtainable
  from Check-in when requested. **But the dispatcher's `OAuth2Client`
  scope list does not request it** (`openid email profile entitlements
  voperson_id …` — no `offline_access`): the v4 janitor's refresh capture
  requires adding it to the requested scope.
- **Token lifetime is 3600 s** — quantifies the §4.2 session decision:
  IdP-token-as-cookie means re-login at most hourly.
- **`azp` was `eoscdcmatchmaker`** (the token was minted for another
  client) — `azp` varies with the requesting client; do not hard-require
  it to equal the dispatcher's client id unless tokens only ever arrive
  via the dispatcher's own flow.

## 3. Version gap (1.3.0 vs the plan's assumed master)

- `state_backend=CookieStateBackend()` — **does not exist in 1.3.0**
  (no `csrf_state` module; `OAuth2Config` takes no such param). Drop it;
  1.3.0's in-memory state default is acceptable *because* the
  dispatcher is single-worker (the plan's own multi-worker concern
  doesn't apply — but note it if workers ever scale).
- Everything else in the plan's wiring exists in 1.3.0 (`enable_ssr`,
  `same_site`, `on_error`, the router, the claims mechanism).

## 4. Conflicts with this repo's plans — DECIDED (2026-10-27)

1. **Invariant #8 ("no refresh token retained") vs the v4 janitor.**
   *Decision: janitor deferred to its own session; capture kept possible.*
   The login callback hands every issued token to
   `auth_middleware.on_login_tokens(sub, access_token, refresh_token)` —
   today a debug-log stub, the exact seam the v4 D2 store write replaces.
   `offline_access` was added to the client scope so refresh tokens ARE
   issued; no config change needed later.
2. **Session lifetime.** *Decision: accepted.* `jwt_expires=3600`
   (cookie ≈ token lifetime); sessions end at `expires_in` and the user
   re-logs in. No dual-validation.
3. **Invariant #9 (header-only on state-changing routes) vs the
   dispatcher's browser UX.** *Decision: the browser UX stays.* API routes
   remain reachable with the session cookie; compensating controls:
   `same_site` flipped `"none"` → `"lax"`, JSON-only request bodies, the
   CORS origin map. Residual CSRF risk accepted and stated here.

## 5. What the design fixes here for free

- **The singleton token race** (documented in the v4 plan's latent-bug
  note): today `caller_access_token` reads
  `request.auth.provider.access_token` — shared per-process state that
  holds *the last login's* token. Under this design the credential
  travels with the request (header or cookie); two concurrent users can
  no longer receive each other's token.
- **v4's capture mechanism simplifies**: the "subclass the middleware
  pair" plan item is replaced by the custom callback route (one seam,
  already verified). `caller_access_token` becomes "read the credential
  off the request" instead of a store lookup.

## 6. Application map (file level), if the §2 gate passes

- `app/security.py` (new) — as the plan, adapted per §2: ISSUER from
  `settings.egi_checkin_env` → the three Check-in realm URLs; JWKS via
  `{issuer}/protocol/openid-connect/certs`; **no `aud` validation**
  (claim absent in Check-in tokens; pin iss/exp/alg instead);
  `normalize_scopes` handles the space-delimited `scope` string
  (Keycloak `realm_access` branches can go).
- `app/auth_middleware.py` (new) — the two patches, as written.
- `app/main.py` — custom `/oauth2/{provider}/token` **before** the
  library router (capture access token for the cookie + refresh token
  for the credentials store); `same_site` → `"lax"`; no
  `state_backend`; `on_error` works as planned.
- `app/routers/utils/auth.py` + `dispatch.caller_access_token` — replace
  the singleton read with the request credential; owner key becomes
  `sub` (provider is constant here — keep `{provider}:{sub}` only for
  record continuity).
- `app/vres/utils/token_utils.py` — deleted, or kept as the
  opaque-fallback if §2 goes the other way.
- Tests — the plan's §7 checklist, plus the regression test for the
  singleton bug: two concurrent "users" never cross tokens.

## 7. Order of operations

1. ~~Decode one live Check-in token~~ — **done** (§2): JWT confirmed,
   no `aud`, no email claim, refresh obtainable but must be requested
   (`offline_access`), 1 h lifetime.
2. Decide §4.1 (refresh-for-janitor — now confirmed feasible; add
   `offline_access` to the client scope), §4.2 (session UX — re-login
   hourly), §4.3 (cookie on API routes).
3. Then implement per §6 — after which the v4 plan's D2 shrinks to
   "store the refresh token captured at the callback seam".

## 8. Is this the right shape? (ecosystem check, 2026-10-27)

The requirement is two standard problems glued together: (a) an OIDC
browser login flow and (b) JWT resource-server validation. No mainstream
FastAPI package does both; `fastapi-oauth2` solves (a) by minting its own
HS256 sessions — its core product, which this design disables — and has
no resource-server mode (v1.5.0, actively maintained, zero
issues/PRs asking for one). Hence the two patched seams in
`auth_middleware.py`: the honest cost of forcing a session-minting
library into validator mode.

- `security.py` is the standard solution, not a workaround — PyJWT +
  PyJWKClient + issuer pinning is what FastAPI itself documents, and the
  EGI specifics (env-keyed issuers, **no `aud` claim**) require a custom
  validator regardless of library choice.
- **Cleaner alternative (recorded, not taken):** `fastapi-sso` (488★,
  active) — its generic OpenID provider + PKCE/state handling covers the
  login flow and returns the tokens, letting us set the cookie directly.
  That composition deletes `auth_middleware.py` entirely and shrinks the
  custom callback to a plain route. Migration effort ≈ what the callback
  already cost; every piece then does its documented job.
- **Parallel track worth doing:** upstream issue/PR to `fastapi-oauth2`
  formalizing `jwt_create`/`jwt_decode` as documented extension points
  ("external validator" mode) — the patch becomes a supported API.

**Decision (taken):** migrated to `fastapi-sso` + `security.py` —
`auth_middleware.py` (the monkeypatch) is deleted; the login flow is
fastapi-sso's generic OpenID provider (state cookie included), the
session cookie is set directly by the callback, and every route
authenticates through the `oauth2_scheme` dependency which verifies via
`security.verify`. fastapi-oauth2, social-auth-core, authlib and
itsdangerous are removed from requirements.
