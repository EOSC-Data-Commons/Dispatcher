import urllib

import pytest
from app.config import settings
import os.path
from git import Repo


def test_post_happy_path(binder_vre):
    local_git_url = (
        f"https://{settings.host}{settings.git_url_prefix}/{binder_vre._request_id}"
    )

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


def test_post_with_zenodo_doi(binder_vre_with_doi):
    """Verify DOI-based Binder URL is constructed correctly."""
    result = binder_vre_with_doi.post()

    assert result == "https://mybinder.org/v2/zenodo/10.5281/zenodo.12345678/"


def test_get_zenodo_doi_returns_bare_doi(binder_vre_with_doi):
    """Verify _get_zenodo_doi returns the bare DOI extracted from workflow @id."""
    doi = binder_vre_with_doi._get_zenodo_doi()

    assert doi == "10.5281/zenodo.12345678"


def test_get_zenodo_doi_none_when_no_zenodo_in_id_or_identifier(binder_vre):
    """Verify _get_zenodo_doi returns None when neither id nor identifier contains zenodo."""
    doi = binder_vre._get_zenodo_doi()

    assert doi is None


def test_get_zenodo_doi_from_id_when_identifier_is_none():
    """Verify _get_zenodo_doi falls back to @id when identifier is None."""
    from vre_rocrate import (
        BINDER_PROGRAMMING_LANGUAGE,
        RequestPackage,
        WorkflowDescriptor,
    )
    from app.vres.binder import VREBinder

    workflow = WorkflowDescriptor(
        id="https://doi.org/10.5281/zenodo.99999",
        type="SoftwareSourceCode",
        programming_language_id=BINDER_PROGRAMMING_LANGUAGE,
    )
    package = RequestPackage(
        vre_type=BINDER_PROGRAMMING_LANGUAGE,
        programming_language=BINDER_PROGRAMMING_LANGUAGE,
        workflow=workflow,
        raw_crate={},
    )
    vre = VREBinder(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=package,
    )
    vre.svc_url = "https://mybinder.org"

    doi = vre._get_zenodo_doi()

    assert doi == "10.5281/zenodo.99999"


def test_get_zenodo_doi_none_when_non_zenodo_identifier():
    """Verify _get_zenodo_doi returns None for non-Zenodo identifiers."""
    from vre_rocrate import (
        BINDER_PROGRAMMING_LANGUAGE,
        RequestPackage,
        WorkflowDescriptor,
    )
    from app.vres.binder import VREBinder

    workflow = WorkflowDescriptor(
        id="notebook.ipynb",
        type="SoftwareSourceCode",
        identifier="https://doi.org/10.1234/figshare.5678",
        programming_language_id=BINDER_PROGRAMMING_LANGUAGE,
    )
    package = RequestPackage(
        vre_type=BINDER_PROGRAMMING_LANGUAGE,
        programming_language=BINDER_PROGRAMMING_LANGUAGE,
        workflow=workflow,
        raw_crate={},
    )
    vre = VREBinder(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=package,
    )
    vre.svc_url = "https://mybinder.org"

    doi = vre._get_zenodo_doi()

    assert doi is None


def test_get_binder_zenodo_url_construction(binder_vre_with_doi):
    """Verify _get_binder_zenodo_url constructs the correct URL format."""
    url = binder_vre_with_doi._get_binder_zenodo_url("10.5281/zenodo.12345678")

    assert url == "https://mybinder.org/v2/zenodo/10.5281/zenodo.12345678/"


def test_get_binder_zenodo_url_trailing_slash_handling():
    """Verify _get_binder_zenodo_url handles svc_url with trailing slash."""
    from vre_rocrate import (
        BINDER_PROGRAMMING_LANGUAGE,
        RequestPackage,
        WorkflowDescriptor,
    )
    from app.vres.binder import VREBinder

    workflow = WorkflowDescriptor(
        id="notebook.ipynb",
        type="SoftwareSourceCode",
        identifier="https://doi.org/10.5281/zenodo.99999",
        programming_language_id=BINDER_PROGRAMMING_LANGUAGE,
    )
    package = RequestPackage(
        vre_type=BINDER_PROGRAMMING_LANGUAGE,
        programming_language=BINDER_PROGRAMMING_LANGUAGE,
        workflow=workflow,
        raw_crate={},
    )
    vre = VREBinder(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=package,
    )
    vre.svc_url = "https://mybinder.org/"

    url = vre._get_binder_zenodo_url("10.5281/zenodo.99999")

    assert url == "https://mybinder.org/v2/zenodo/10.5281/zenodo.99999/"
