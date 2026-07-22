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
        == f'{binder_vre.svc_url.rstrip("/")}/v2/git/{urllib.parse.quote_plus(local_git_url)}/HEAD'
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


# =============================================================================
# Tests for repository-only mode and URL parsing
# =============================================================================


def test_is_repository_only_true_when_url_and_no_local_files():
    """Verify is_repository_only returns True when workflow has URL but no local files."""
    from vre_rocrate import (
        BINDER_PROGRAMMING_LANGUAGE,
        RequestPackage,
        WorkflowDescriptor,
    )

    workflow = WorkflowDescriptor(
        id="notebook.ipynb",
        type="SoftwareSourceCode",
        url="https://github.com/example/repo",
        programming_language_id=BINDER_PROGRAMMING_LANGUAGE,
    )
    package = RequestPackage(
        vre_type=BINDER_PROGRAMMING_LANGUAGE,
        programming_language=BINDER_PROGRAMMING_LANGUAGE,
        workflow=workflow,
        files=[],  # No files at all
        raw_crate={},
    )

    assert package.is_repository_only is True


def test_is_repository_only_false_when_has_local_files():
    """Verify is_repository_only returns False when local files are present."""
    from vre_rocrate import (
        BINDER_PROGRAMMING_LANGUAGE,
        RequestPackage,
        WorkflowDescriptor,
        FileReference,
    )

    workflow = WorkflowDescriptor(
        id="notebook.ipynb",
        type="SoftwareSourceCode",
        url="https://github.com/example/repo",
        programming_language_id=BINDER_PROGRAMMING_LANGUAGE,
    )
    package = RequestPackage(
        vre_type=BINDER_PROGRAMMING_LANGUAGE,
        programming_language=BINDER_PROGRAMMING_LANGUAGE,
        workflow=workflow,
        files=[
            FileReference(id="notebook.ipynb", name="notebook.ipynb", properties={})
        ],
        raw_crate={},
    )

    assert package.is_repository_only is False


def test_is_repository_only_false_when_no_url():
    """Verify is_repository_only returns False when workflow has no URL."""
    from vre_rocrate import (
        BINDER_PROGRAMMING_LANGUAGE,
        RequestPackage,
        WorkflowDescriptor,
    )

    workflow = WorkflowDescriptor(
        id="notebook.ipynb",
        type="SoftwareSourceCode",
        url=None,  # No URL
        programming_language_id=BINDER_PROGRAMMING_LANGUAGE,
    )
    package = RequestPackage(
        vre_type=BINDER_PROGRAMMING_LANGUAGE,
        programming_language=BINDER_PROGRAMMING_LANGUAGE,
        workflow=workflow,
        files=[],
        raw_crate={},
    )

    assert package.is_repository_only is False


def test_build_binder_url_github_simple(binder_vre_github_only):
    """Test GitHub URL without branch specification defaults to HEAD."""
    result = binder_vre_github_only._build_binder_url(
        "https://github.com/example/notebook-repo"
    )
    assert result == "https://mybinder.org/v2/gh/example/notebook-repo/HEAD"


def test_build_binder_url_github_with_branch(binder_vre_github_with_branch):
    """Test GitHub URL with branch specification uses that branch."""
    result = binder_vre_github_with_branch._build_binder_url(
        "https://github.com/example/notebook-repo/tree/main"
    )
    assert result == "https://mybinder.org/v2/gh/example/notebook-repo/main"


def test_build_binder_url_zenodo(binder_vre_zenodo_url):
    """Test Zenodo DOI URL conversion."""
    result = binder_vre_zenodo_url._build_binder_url(
        "https://doi.org/10.5281/zenodo.12345678"
    )
    assert result == "https://mybinder.org/v2/zenodo/10.5281/zenodo.12345678/"


def test_build_binder_url_zenodo_http(binder_vre_zenodo_url):
    """Test Zenodo DOI URL with http protocol."""
    result = binder_vre_zenodo_url._build_binder_url(
        "http://doi.org/10.5281/zenodo.99999"
    )
    assert result == "https://mybinder.org/v2/zenodo/10.5281/zenodo.99999/"


def test_build_binder_url_unsupported_raises_exception(binder_vre_github_only):
    """Test that unsupported repository sources raise UnsupportedBinderSource."""
    from app.exceptions import UnsupportedBinderSource

    with pytest.raises(UnsupportedBinderSource):
        binder_vre_github_only._build_binder_url("https://gitlab.com/example/repo")


def test_post_repository_only_github(binder_vre_github_only):
    """Test post() in repository-only mode with GitHub URL."""
    result = binder_vre_github_only.post()
    assert result == "https://mybinder.org/v2/gh/example/notebook-repo/HEAD"


def test_post_repository_only_zenodo(binder_vre_zenodo_url):
    """Test post() in repository-only mode with Zenodo URL."""
    result = binder_vre_zenodo_url.post()
    assert result == "https://mybinder.org/v2/zenodo/10.5281/zenodo.12345678/"


def test_clone_remote_files_none_url_does_nothing(tmpdir):
    """Test that _clone_remote_files does nothing when URL is None."""
    from vre_rocrate import (
        BINDER_PROGRAMMING_LANGUAGE,
        RequestPackage,
        WorkflowDescriptor,
    )
    from app.vres.binder import VREBinder

    workflow = WorkflowDescriptor(
        id="notebook.ipynb",
        type="SoftwareSourceCode",
        url=None,
        programming_language_id=BINDER_PROGRAMMING_LANGUAGE,
    )
    package = RequestPackage(
        vre_type=BINDER_PROGRAMMING_LANGUAGE,
        programming_language=BINDER_PROGRAMMING_LANGUAGE,
        workflow=workflow,
        files=[],
        raw_crate={},
    )
    vre = VREBinder(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=package,
    )

    repo_path = str(tmpdir / "test_repo")
    os.makedirs(repo_path)

    # Should not raise any exception
    vre._clone_remote_files(None, repo_path)

    # Directory should be unchanged (empty except for what we created)
    assert os.path.isdir(repo_path)


def test_clone_remote_files_non_github_logs_warning(caplog, tmpdir):
    """Test that non-GitHub URLs log a warning and do nothing."""
    from vre_rocrate import (
        BINDER_PROGRAMMING_LANGUAGE,
        RequestPackage,
        WorkflowDescriptor,
    )
    from app.vres.binder import VREBinder

    workflow = WorkflowDescriptor(
        id="notebook.ipynb",
        type="SoftwareSourceCode",
        url="https://gitlab.com/example/repo",
        programming_language_id=BINDER_PROGRAMMING_LANGUAGE,
    )
    package = RequestPackage(
        vre_type=BINDER_PROGRAMMING_LANGUAGE,
        programming_language=BINDER_PROGRAMMING_LANGUAGE,
        workflow=workflow,
        files=[],
        raw_crate={},
    )
    vre = VREBinder(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=package,
    )

    repo_path = str(tmpdir / "test_repo")
    os.makedirs(repo_path)

    vre._clone_remote_files("https://gitlab.com/example/repo", repo_path)

    # Check that warning was logged
    assert any("non-GitHub" in record.message for record in caplog.records)
