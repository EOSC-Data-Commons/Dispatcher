import urllib

import pytest
from app.config import settings
import os.path
from git import Repo


def test_post_happy_path(binder_vre):
    local_git_url = f"https://{settings.host}/git/{binder_vre._request_id}"

    final_url = binder_vre.post()

    assert (
        final_url
        == f'{binder_vre.svc_url.rstrip("/")}/git/{urllib.parse.quote_plus(local_git_url)}/HEAD'
    )


def test_post_dir_created(binder_vre, tmpdir):
    binder_vre.post()

    assert os.path.isdir(f"{tmpdir}/{binder_vre._request_id}")


def test_post_git_repo_initialized(binder_vre, tmpdir):
    binder_vre.post()

    assert os.path.isdir(f"{tmpdir}/{binder_vre._request_id}/.git")


def test_post_git_deamon_export_created(binder_vre, tmpdir):
    binder_vre.post()

    assert os.path.isfile(
        f"{tmpdir}/{binder_vre._request_id}/.git/git-daemon-export-ok"
    )


def test_post_git_commit(binder_vre, tmpdir):
    binder_vre.post()
    repo = Repo(f"{tmpdir}/{binder_vre._request_id}")

    assert repo.head.commit.message == "on the fly"


def test_post_permission_denied(binder_vre):
    settings.git_repos = "/"

    with pytest.raises(PermissionError):
        binder_vre.post()


def test_post_not_found(binder_vre, tmpdir):
    settings.git_repos = f"{tmpdir}/../abc"

    with pytest.raises(FileNotFoundError):
        binder_vre.post()
