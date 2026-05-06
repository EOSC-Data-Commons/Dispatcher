# test/unit/test_jupyter.py
import pytest
import requests
from unittest.mock import Mock

from app.constants import JUPYTER_DEFAULT_SERVICE
from app.exceptions import (
    ExternalServiceError,
    InvalidResponseError,
    VREAuthenticationError,
)
from app.vres.jupyter import VREJupyter
from conftest import register_jupyter_mocks


def test_get_default_service(jupyter_vre):
    assert jupyter_vre.get_default_service() == JUPYTER_DEFAULT_SERVICE


def test_post_returns_correct_url(jupyter_vre, requests_mock):
    register_jupyter_mocks(
        requests_mock,
        userinfo={
            "json": {
                "name": "testuser",
                "server": "some-server",
                "servers": {"": {"ready": True}},
            }
        },
        server_start={"status_code": 200},
        token_creation={"json": {"token": "api-token-123"}},
        upload={"json": {"name": "notebook.ipynb"}},
    )

    result = jupyter_vre.post()

    assert result == f"{JUPYTER_DEFAULT_SERVICE}/user/testuser"


def test_post_raises_when_username_missing(jupyter_vre, requests_mock):
    register_jupyter_mocks(
        requests_mock,
        userinfo={"json": {"server": "some-server"}},
    )

    with pytest.raises(VREAuthenticationError):
        jupyter_vre.post()


def test_post_raises_when_userinfo_fails(jupyter_vre, requests_mock):
    register_jupyter_mocks(
        requests_mock,
        userinfo={"status_code": 401},
    )

    with pytest.raises(requests.HTTPError):
        jupyter_vre.post()


def test_post_raises_when_server_start_fails(jupyter_vre, requests_mock):
    register_jupyter_mocks(
        requests_mock,
        userinfo={"json": {"name": "testuser"}},
        server_start={"status_code": 500},
    )

    with pytest.raises(requests.HTTPError):
        jupyter_vre.post()


def test_post_raises_when_token_missing(jupyter_vre, requests_mock):
    register_jupyter_mocks(
        requests_mock,
        userinfo={"json": {"name": "testuser"}},
        server_start={"status_code": 200},
        token_creation={"json": {}},
    )

    with pytest.raises(InvalidResponseError):
        jupyter_vre.post()


def test_post_raises_when_token_creation_fails(jupyter_vre, requests_mock):
    register_jupyter_mocks(
        requests_mock,
        userinfo={"json": {"name": "testuser"}},
        server_start={"status_code": 200},
        token_creation={"status_code": 403},
    )

    with pytest.raises(ExternalServiceError):
        jupyter_vre.post()


def test_post_raises_when_upload_fails(jupyter_vre, requests_mock):
    register_jupyter_mocks(
        requests_mock,
        userinfo={
            "json": {
                "name": "testuser",
                "server": "some-server",
                "servers": {"": {"ready": True}},
            }
        },
        server_start={"status_code": 200},
        token_creation={"json": {"token": "api-token-123"}},
        upload={"status_code": 500},
    )

    with pytest.raises(ExternalServiceError):
        jupyter_vre.post()


def test_post_with_no_ipynb_in_zip(
    dummy_jupyter_crate, jupyter_zip_body_no_notebook, requests_mock
):
    vre = VREJupyter(
        crate=dummy_jupyter_crate,
        token="test-token",
        request_id=0,
        update_state=Mock(),
        body=jupyter_zip_body_no_notebook,
    )
    vre.svc_url = JUPYTER_DEFAULT_SERVICE

    register_jupyter_mocks(
        requests_mock,
        userinfo={"json": {"name": "testuser"}},
        server_start={"status_code": 200},
        token_creation={"json": {"token": "api-token-123"}},
    )

    with pytest.raises(UnboundLocalError):
        vre.post()
