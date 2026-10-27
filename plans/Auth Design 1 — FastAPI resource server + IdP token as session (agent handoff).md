# Auth Design 1 — resource server + IdP token as session cookie

**Status:** design decided, not yet implemented. Code below is written against `fastapi-oauth2` `master` source (read, not executed) and has NOT been run or tested.

## 1. System shape

*   FastAPI backend serves a frontend **and** must work standalone (headless / service-to-service / CLI callers).
    
*   Frontend is a public OAuth client (PKCE) and passes IdP **access tokens** to the backend as `Authorization: Bearer`.
    
*   Backend forwards access tokens onward to its **own internal services**, all issuing from the **same IdP**.
    
*   Access tokens are **JWTs verifiable via JWKS**.
    
*   Backend also needs **redirect login** (browser-facing `/oauth2/{provider}/authorize`) for standalone/SSR use → `fastapi-oauth2` middleware is **required**.
    

## 2. Decision

Backend acts as an **OAuth2 resource server**: it validates IdP-issued JWTs and **never mints credentials of its own**.
`OAuth2Middleware` is kept (it provides the client registry + redirect flow), but its token minting is neutralized so the **session cookie holds the IdP's access token itself**. One token type, one validator, one code path for browser sessions and bearer callers.
**Rejected:**

*   Letting the library mint its own HS256 JWT (`Auth.jwt_create`) — creates a second credential system.
    
*   Dual-validation design (cookie = own HS256 JWT, header = IdP JWT) — valid if SSR sessions must outlive access-token expiry, but permanently requires algorithm-disambiguation discipline. Revisit only if silent re-login per `expires_in` is unacceptable.
    
*   `fastapi-authlib` — wrong fit: DB-backed cookie-session OIDC wrapper, pins `fastapi>=0.95,<0.96`, last release 0.0.4.
    

## 3. Why the middleware must stay

*   `router.py` resolves clients via `request.auth.clients[provider]` and `request.auth.ssr`.
    
*   `core.py` reads `request.auth.http` (scheme for `authorization_response`) and `request.auth.expires` / `same_site` (cookie attrs) in `token_redirect`.
    

So the middleware is both auth enforcement **and** the client registry the redirect flow depends on. Only two seams matter:

*   `Auth.jwt_create` — used by `OAuth2Core.token_redirect` to produce the cookie value.
    
*   `Auth.jwt_decode` — used by `OAuth2Backend.authenticate` to validate it.
    

## 4. Code

### `app/security.py` — single source of trust

```python
from dataclasses import dataclass
from functools import lru_cache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, decode, PyJWTError   # PyJWT[crypto]

ISSUER   = "https://idp.example.com/realms/main"  # must match `iss` exactly, incl. trailing slash
AUDIENCE = "internal-api"                         # UNVERIFIED placeholder — see §6
PROVIDER = "keycloak"                             # key into OAuth2Config.clients
ALGS     = ("RS256",)

@lru_cache(maxsize=1)
def _jwks() -> PyJWKClient:
    return PyJWKClient(f"{ISSUER}/.well-known/certs", cache_keys=True)  # path varies per IdP

def normalize_scopes(claims: dict) -> frozenset[str]:
    """Covers common Keycloak/Entra layouts by guess — confirm against a live token."""
    out: set[str] = set()
    for key in ("scope", "scp"):
        v = claims.get(key)
        if v:
            out |= set(v.split() if isinstance(v, str) else v)
    out |= set(claims.get("realm_access", {}).get("roles", []))
    out |= set(claims.get("roles", []))
    return frozenset(out)

@dataclass(frozen=True)
class Principal:
    subject: str
    scopes: frozenset[str]
    claims: dict
    raw_token: str                    # forwarded to internal services; never log it
    client_id: str = ""
    is_authenticated: bool = True

def verify(token: str) -> dict:       # THE only place a token becomes trusted
    return decode(
        token, _jwks().get_signing_key_from_jwt(token).key,
        algorithms=list(ALGS), audience=AUDIENCE, issuer=ISSUER, leeway=30,
        options={"require": ["exp", "iat", "iss", "aud", "sub"]},
    )

def principal_from(claims: dict, token: str) -> Principal:
    return Principal(
        str(claims["sub"]), normalize_scopes(claims), claims, token,
        str(claims.get("azp") or claims.get("client_id") or claims.get("cid") or ""),
    )

async def get_principal(creds: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=True))) -> Principal:
    try:
        return principal_from(verify(creds.credentials), creds.credentials)
    except PyJWTError as exc:
        expired = "expired" in str(exc).lower()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, str(exc),
            headers={"WWW-Authenticate": f'Bearer error="{"expired_token" if expired else "invalid_token"}"'},
        )

def require_scope(*needed: str, mode: str = "all"):
    async def dep(p: Principal = Depends(get_principal)) -> Principal:
        ok = set(needed) <= p.scopes if mode == "all" else p.scopes & set(needed)
        if not ok:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Requires {'all' if mode=='all' else 'any'} of {sorted(needed)}")
        return p
    return dep
```

### `app/auth_middleware.py` — neutralize library minting

```python
from fastapi_oauth2 import middleware as fo
from fastapi_oauth2.exceptions import OAuth2AuthenticationError
from .security import PROVIDER, verify, normalize_scopes

def _jwt_create(token_data: dict) -> str:
    tok = token_data.get("_access_token")
    if not tok:
        raise OAuth2AuthenticationError(500, "no provider access token in callback")
    return tok                              # provider token IS the session credential

def _jwt_decode(token: str) -> dict:
    claims = dict(verify(token))
    claims["provider"] = PROVIDER           # required: authenticate() looks up auth.provider by this
    claims["scope"] = sorted(normalize_scopes(claims))   # coerce str->list; Auth(scopes) expects list
    claims["_expires_at"] = claims["exp"]
    return claims

fo.Auth.jwt_create = classmethod(lambda cls, data: _jwt_create(dict(data)))
fo.Auth.jwt_decode = staticmethod(_jwt_decode)
```

### `app/main.py` — wiring

```python
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi_oauth2.config import OAuth2Config
from fastapi_oauth2.client import OAuth2Client
from fastapi_oauth2.claims import Claims
from fastapi_oauth2.csrf_state import CookieStateBackend
from fastapi_oauth2.middleware import OAuth2Middleware
from fastapi_oauth2.router import router as oauth2_router
from . import auth_middleware  # noqa: F401  — must import BEFORE middleware is added
from .security import get_principal

ui = APIRouter()

@ui.get("/oauth2/{provider}/token")
async def callback(request: Request, provider: str):
    core = request.auth.clients[provider]
    data = await core.token_data(request)                       # performs code→token exchange
    data["_access_token"] = dict(core._oauth_client.token).get("access_token")
    if not data["_access_token"]:
        raise RuntimeError("provider returned no access_token")
    return await core.token_redirect(request)                   # sets cookie = provider JWT

def on_auth_error(conn, exc):                                   # default returns 400 — wrong for bearer
    expired = "expired" in str(exc).lower()
    return JSONResponse({"detail": str(exc)}, status_code=401,
                        headers={"WWW-Authenticate": f'Bearer error="{"expired_token" if expired else "invalid_token"}"'})

app = FastAPI()
app.include_router(ui)            # MUST be registered before the library router (first match wins)
app.include_router(oauth2_router)
app.add_middleware(OAuth2Middleware, config=OAuth2Config(
    enable_ssr=True, allow_http=False, same_site="lax",
    jwt_expires=300,              # now governs COOKIE lifetime ≈ provider expires_in
    state_backend=CookieStateBackend(),   # in-memory default is not multi-worker safe
    clients=[OAuth2Client(backend=..., client_id=..., client_secret=...,
                          redirect_uri="https://backend.example.com/callback",
                          scope=["openid", "internal-api"],
                          claims=Claims(identity="sub", display_name="name",
                                        email="email", picture="picture"))],
), on_error=on_auth_error)
```

`/oauth2/{provider}/authorize` and `/oauth2/logout` come from the library router.

## 5. Invariants / gotchas (each one has already cost analysis — do not silently change)

1.  **Audience is the #1 failure mode.** Cookie token is validated with `audience=AUDIENCE`, so the backend's own client must request that audience. A frontend-minted token for a different `aud` 401s _after a successful login_.
    
2.  **Multi-audience is impossible.** One token cannot be accepted by two internal services each with its own `aud`. Chosen stance: **shared internal audience** (`internal-api`) + scope-based authorization; split audiences later only via RFC 8693 token exchange at the `Principal → Downstream` boundary.
    
3.  `Claims` **semantics shift.** `User` is now built from **JWT claims**, not social-core `user_data`. And `authenticate()` resolves `auth.provider` from `user["provider"]` — absent in an IdP token — hence the injection in `_jwt_decode`. Without it `auth.provider is None`, `Claims` mapping is a no-op, `user.display_name` silently returns `""`.
    
4.  `scope` **claim must be coerced to a list** (IdPs emit a space-delimited string) before `Auth(scopes)`.
    
5.  `jwt_expires` **= cookie lifetime**, since `token_redirect` uses `max_age=request.auth.expires`. Set ≈ provider `expires_in`, slightly under.
    
6.  `on_error` **must return 401 +** `WWW-Authenticate`**.** `AuthenticationMiddleware.default_on_error` returns 400. Frontend keys refresh-vs-relogin on `error="expired_token"` vs `invalid_token` — this is API contract.
    
7.  `/oauth2/logout` **only deletes the cookie** (`delete_cookie("Authorization")` + redirect). No OIDC RP-initiated logout, no revocation; IdP session survives. Add end-session redirect if real logout is required.
    
8.  **No refresh token is retained** — deliberate, given internal-only downstreams. `client_credentials` is the standalone/automation grant into the _same_ validator (`Principal.client_id` populated, `sub` = service account). Standalone ≠ separate auth; it means a different grant.
    
9.  **CSRF: do not let cookie fallback reach API routes.** `fastapi_oauth2.security`'s metaclass copies the `Authorization` cookie into the header. SSR/HTML routes may use it; **state-changing API routes must use header-only** `HTTPBearer` (as `get_principal` does) so cookie-borne credentials can't be replayed cross-site. Keep `same_site="lax"`.
    
10.  **Never accept both HS256 and RS256 on one endpoint**; pin `algorithms`. Note `fastapi_oauth2.middleware` still imports `jose.jwt` internally for its own paths — PyJWT is used here deliberately (`python-jose` has a history of HMAC/RSA confusion issues).
     
11.  `token_data()` **discards the provider tokens** and returns only `standardize(user_data(...))`; the token is read off `core._oauth_client.token` synchronously per request in the callback to avoid the shared-`_oauth_client` race (`OAuth2Core` instances are built once per provider in `OAuth2Backend.__init__`).
     
12.  **Wasted round-trip (optional optimization):** `token_data` calls `backend.user_data(access_token)` (a network fetch) whose result is thrown away in this design. Skipping `token_redirect` and setting the cookie manually removes it, at the cost of re-implementing cookie attributes (`max_age`/`expires`/`secure`/`httponly`/`samesite`).
     
13.  **Monkeypatch surface is unadvertised API.** `Auth.jwt_create` / `Auth.jwt_decode` are classmethods in `fastapi_oauth2/middleware.py`; patch at import time before the app serves requests. **Pin the version.** Fallback if upstream breaks: build `AuthenticationMiddleware` with a custom backend and set `Auth.ssr/http/secret/expires/same_site/clients` manually (the router depends on those).
     

## 6. UNVERIFIED — resolve before implementation

*   **IdP vendor, issuer URL, and JWKS/discovery path** — never stated by the user. Placeholder `realms/main` + `.well-known/certs` is Keycloak-shaped.
    
*   **Audience claim name** (`aud` vs `azp`) and **scope claim name** (`scope` vs `scp` vs `roles` vs `realm_access.roles`) — `normalize_scopes` covers common layouts _by guess_. Decode one live access token and confirm.
    
*   **Whether the IdP sets** `aud` **to the resource identifier by default** (Keycloak often needs an audience mapper; Entra uses `api://<guid>`).
    
*   Exact `fastapi-oauth2` version installed (`pip show fastapi-oauth2`) — repo is `src/`-layout on master; older wheels differ.
    
*   Whether the frontend sends `Authorization` header only, or also relies on the cookie.
    
*   Whether SSR sessions must outlive access-token expiry (if yes → the dual-validation design; note its earlier sketch had an infinite-recursion bug in the `_jwt_decode` branch, rewrite rather than reuse).
    

## 7. Verification checklist

- [ ] IdP: register `internal-api` API/resource + scopes; allow frontend public client (PKCE) to request it; confirm audience claim emitted.
- [ ] Decode a live token: confirm `iss`/`aud`/`exp`/`sub`/scope keys; align `AUDIENCE`, `ISSUER`, `normalize_scopes`, `Claims(...)`.
- [ ] Remove any prior `jwt_secret`/minting config; grep for leftover `Auth.jwt_*` assumptions.
- [ ] E2E: `/oauth2/{provider}/authorize` → callback → cookie is the IdP JWT → authenticated request works.
- [ ] E2E: `client_credentials` bearer (no cookie) hits the same route successfully.
- [ ] Tests: wrong `iss`, wrong `aud`, expired → 401 with correct `WWW-Authenticate` error code; missing scope → 403; `alg=none` and HS256-signed-with-public-key → rejected.
- [ ] Tests: cookie-only request to a state-changing API route is rejected (CSRF invariant #9).
- [ ] Frontend treats `expired_token` as refresh-and-retry, `invalid_token` as re-login.
- [ ] Confirm no logging of `raw_token`; confirm no silent fallback to a service token on downstream 401 (that turns a permission failure into privilege escalation).

## 8. Downstream forwarding pattern

```python
class Downstream:
    def __init__(self, base: str, client: httpx.AsyncClient) -> None:
        self._base, self._c = base.rstrip("/"), client

    async def get(self, path: str, p: Principal, **kw):
        r = await self._c.get(f"{self._base}{path}",
                             headers={"Authorization": f"Bearer {p.raw_token}"}, **kw)
        if r.status_code == 401:
            raise httpx.HTTPStatusError("downstream rejected token", request=r.request, response=r)
        r.raise_for_status()
        return r
```

This `Principal → Downstream` seam is the only place RFC 8693 token exchange would be added if a peer later needs its own audience.