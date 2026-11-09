"""Unit tests for app.http — the shared client + transient-retry matrix."""

import httpx
import pytest

from app import http as app_http
from app.exceptions import TransientHTTPError

URL = "https://svc.example.org/endpoint"


def _request_count(httpx_mock) -> int:
    return len(httpx_mock.get_requests())


class TestRetryMatrix:
    async def test_success_no_retry(self, httpx_mock):
        httpx_mock.add_response(url=URL, json={"ok": True})

        resp = await app_http.request("GET", URL)

        assert resp.json() == {"ok": True}
        assert _request_count(httpx_mock) == 1

    async def test_transport_error_retried_then_success(self, httpx_mock):
        httpx_mock.add_exception(httpx.ConnectError("boom"), url=URL)
        httpx_mock.add_response(url=URL, json={"ok": True})

        resp = await app_http.request("GET", URL)

        assert resp.json() == {"ok": True}
        assert _request_count(httpx_mock) == 2

    async def test_timeout_retried_then_success(self, httpx_mock):
        httpx_mock.add_exception(httpx.ReadTimeout("slow"), url=URL)
        httpx_mock.add_response(url=URL, json={"ok": True})

        resp = await app_http.request("GET", URL)

        assert resp.json() == {"ok": True}
        assert _request_count(httpx_mock) == 2

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    async def test_5xx_retried_then_success(self, httpx_mock, status):
        httpx_mock.add_response(url=URL, status_code=status)
        httpx_mock.add_response(url=URL, json={"ok": True})

        resp = await app_http.request("GET", URL)

        assert resp.status_code == 200
        assert _request_count(httpx_mock) == 2

    @pytest.mark.parametrize("status", [408, 429])
    async def test_transient_4xx_retried_then_success(self, httpx_mock, status):
        httpx_mock.add_response(url=URL, status_code=status)
        httpx_mock.add_response(url=URL, json={"ok": True})

        resp = await app_http.request("GET", URL)

        assert resp.status_code == 200
        assert _request_count(httpx_mock) == 2

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    async def test_other_4xx_fail_fast(self, httpx_mock, status):
        httpx_mock.add_response(url=URL, status_code=status, text="nope")

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await app_http.request("GET", URL)

        assert not isinstance(exc_info.value, TransientHTTPError)
        assert exc_info.value.response.status_code == status
        assert _request_count(httpx_mock) == 1

    async def test_retry_exhaustion_raises_transient_http_error(self, httpx_mock):
        for _ in range(4):
            httpx_mock.add_response(url=URL, status_code=503)

        with pytest.raises(TransientHTTPError):
            await app_http.request("GET", URL)

        assert _request_count(httpx_mock) == 4

    async def test_transport_error_exhaustion_reraises(self, httpx_mock):
        for _ in range(4):
            httpx_mock.add_exception(httpx.ConnectError("boom"), url=URL)

        with pytest.raises(httpx.ConnectError):
            await app_http.request("GET", URL)

        assert _request_count(httpx_mock) == 4

    async def test_retry_false_escape_hatch(self, httpx_mock):
        httpx_mock.add_response(url=URL, status_code=500)

        with pytest.raises(TransientHTTPError):
            await app_http.request("GET", URL, retry=False)

        assert _request_count(httpx_mock) == 1

    async def test_retry_warning_logged_per_attempt(self, httpx_mock, caplog):
        httpx_mock.add_response(url=URL, status_code=500)
        httpx_mock.add_response(url=URL, status_code=500)
        httpx_mock.add_response(url=URL, json={"ok": True})

        with caplog.at_level("WARNING", logger="app.http"):
            resp = await app_http.request("GET", URL)

        assert resp.status_code == 200
        warning_logs = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_logs) == 2


class TestRaiseForStatus:
    async def test_false_returns_error_response(self, httpx_mock):
        httpx_mock.add_response(url=URL, status_code=400, text="bad request")

        resp = await app_http.request("GET", URL, raise_for_status=False)

        assert resp.status_code == 400
        assert resp.text == "bad request"

    async def test_transient_still_raised_when_raise_for_status_false(self, httpx_mock):
        for _ in range(4):
            httpx_mock.add_response(url=URL, status_code=503)

        with pytest.raises(TransientHTTPError):
            await app_http.request("GET", URL, raise_for_status=False)

        assert _request_count(httpx_mock) == 4


class TestSharedClient:
    async def test_get_http_client_returns_singleton(self):
        first = app_http.get_http_client()
        second = app_http.get_http_client()

        assert first is second
        assert isinstance(first, httpx.AsyncClient)

    async def test_init_replaces_client(self):
        first = app_http.init_http_client()
        second = app_http.init_http_client()

        assert first is not second
        assert app_http.get_http_client() is second

    async def test_close_clears_client(self):
        app_http.init_http_client()

        await app_http.close_http_client()

        fresh = app_http.get_http_client()
        assert fresh is not None  # lazily recreated

    async def test_request_uses_passed_client(self, httpx_mock):
        httpx_mock.add_response(url=URL, json={"ok": True})
        async with httpx.AsyncClient() as custom:
            resp = await app_http.request("GET", URL, client=custom)

        assert resp.json() == {"ok": True}
        assert _request_count(httpx_mock) == 1

    async def test_post_forwards_json_and_headers(self, httpx_mock):
        httpx_mock.add_response(url=URL, status_code=201, json={"id": "1"})

        resp = await app_http.post(
            URL, json={"a": 1}, headers={"X-Test": "yes"}, retry=False
        )

        assert resp.status_code == 201
        sent = httpx_mock.get_requests()[0]
        assert sent.headers["X-Test"] == "yes"
        assert sent.read() == b'{"a":1}'
