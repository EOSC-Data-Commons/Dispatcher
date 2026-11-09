"""Shared async HTTP client and unified retry policy.

All dispatcher outbound HTTP goes through :func:`request`, which uses one
lifespan-managed :class:`httpx.AsyncClient` (connection pooling configured
from settings) and retries *transient* failures only — transport errors,
timeouts and 408/429/5xx responses — via tenacity per call, never the whole
flow (a retried IM create would be a VM).

Retry policy: ``http_retry_attempts`` tries with randomized exponential
backoff between ``http_retry_min_backoff`` and ``http_retry_max_backoff``
seconds, a WARNING log line per retry, and the last exception re-raised on
exhaustion (``reraise=True``).  Non-transient 4xx responses fail fast so
callers can map them to domain errors.  ``retry=False`` is the escape hatch
for a single-shot call.
"""

import logging

import httpx
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from app.config import settings
from app.exceptions import TransientHTTPError

logger = logging.getLogger(__name__)

#: Response statuses considered transient (any 5xx also qualifies).
_TRANSIENT_STATUSES = frozenset({408, 429})

_client: httpx.AsyncClient | None = None


def _make_client() -> httpx.AsyncClient:
    """Build the shared client from settings (limits + default timeout)."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_default_timeout),
        limits=httpx.Limits(
            max_connections=settings.http_max_connections,
            max_keepalive_connections=settings.http_max_keepalive_connections,
        ),
    )


def init_http_client() -> httpx.AsyncClient:
    """(Re)create the module-level shared client. Called from the app lifespan
    (and by tests that need a fresh client bound to a mocked transport)."""
    global _client
    _client = _make_client()
    return _client


async def close_http_client() -> None:
    """Close the shared client if one exists. Called on app shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_http_client() -> httpx.AsyncClient:
    """Return the shared client, creating it lazily on first use."""
    global _client
    if _client is None:
        _client = _make_client()
    return _client


def _is_transient(exc: BaseException) -> bool:
    """tenacity predicate: retry transport/timeout errors and TransientHTTPError."""
    return isinstance(exc, (httpx.TransportError, TransientHTTPError))


def _raise_if_transient(resp: httpx.Response) -> None:
    if resp.status_code in _TRANSIENT_STATUSES or resp.status_code >= 500:
        raise TransientHTTPError(
            f"Transient HTTP {resp.status_code} for "
            f"{resp.request.method} {resp.request.url}",
            request=resp.request,
            response=resp,
        )


async def request(
    method: str,
    url: str,
    *,
    retry: bool = True,
    raise_for_status: bool = True,
    client: httpx.AsyncClient | None = None,
    **kwargs,
) -> httpx.Response:
    """Perform an HTTP request with the unified transient-retry policy.

    Args:
        method: HTTP method.
        url: Request URL.
        retry: When False, perform a single attempt (escape hatch).
        raise_for_status: Raise :class:`httpx.HTTPStatusError` on
            non-transient error statuses. Transient statuses (408/429/5xx)
            are always raised as :class:`TransientHTTPError` (after retries,
            if enabled) regardless of this flag.
        client: Override the shared client (e.g. per-flow cookie sessions).
        **kwargs: Forwarded to :meth:`httpx.AsyncClient.request`.

    Returns:
        The successful (or tolerated-error) response.

    Raises:
        httpx.TransportError: Network/timeout failure after retries.
        TransientHTTPError: Retriable status that kept failing.
        httpx.HTTPStatusError: Non-transient error status (fail fast).
    """
    http = client or get_http_client()

    if not retry:
        resp = await http.request(method, url, **kwargs)
        _raise_if_transient(resp)
        if raise_for_status:
            resp.raise_for_status()
        return resp

    retryer = AsyncRetrying(
        stop=stop_after_attempt(max(1, settings.http_retry_attempts)),
        wait=wait_random_exponential(
            multiplier=settings.http_retry_min_backoff,
            max=settings.http_retry_max_backoff,
        ),
        retry=retry_if_exception(_is_transient),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    resp = None
    async for attempt in retryer:
        with attempt:
            resp = await http.request(method, url, **kwargs)
            _raise_if_transient(resp)
            if raise_for_status:
                resp.raise_for_status()
    return resp


async def get(url: str, **kwargs) -> httpx.Response:
    """Convenience wrapper for GET requests via :func:`request`."""
    return await request("GET", url, **kwargs)


async def post(url: str, **kwargs) -> httpx.Response:
    """Convenience wrapper for POST requests via :func:`request`."""
    return await request("POST", url, **kwargs)


async def put(url: str, **kwargs) -> httpx.Response:
    """Convenience wrapper for PUT requests via :func:`request`."""
    return await request("PUT", url, **kwargs)


async def delete(url: str, **kwargs) -> httpx.Response:
    """Convenience wrapper for DELETE requests via :func:`request`."""
    return await request("DELETE", url, **kwargs)
