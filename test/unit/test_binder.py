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


def test_clone_remote_files_none_url_does_nothing(binder_vre_no_url, tmpdir):
    """Test that _clone_remote_files does nothing when URL is None."""
    repo_path = str(tmpdir / "test_repo")
    os.makedirs(repo_path)

    # Should not raise any exception
    binder_vre_no_url._clone_remote_files(None, repo_path)

    # Directory should be unchanged (empty except for what we created)
    assert os.path.isdir(repo_path)


def test_clone_remote_files_non_github_logs_warning(
    binder_vre_gitlab_only, caplog, tmpdir
):
    """Test that non-GitHub URLs log a warning and do nothing."""
    repo_path = str(tmpdir / "test_repo")
    os.makedirs(repo_path)

    binder_vre_gitlab_only._clone_remote_files(
        "https://gitlab.com/example/repo", repo_path
    )

    # Check that warning was logged
    assert any("non-GitHub" in record.message for record in caplog.records)


# =============================================================================
# Tests for _write_start_script with cloned start script preservation
# =============================================================================


EXISTING_START_CONTENT = "#!/bin/bash\necho 'original start'\n"


def test_write_start_script_preserves_existing(binder_vre_not_repo_only, tmpdir):
    """Existing 'start' from cloned repo is renamed and sourced by the new one."""
    repo_path = str(tmpdir / "test_repo")
    os.makedirs(repo_path)

    # Simulate a cloned repo that already has a start script
    existing_start = os.path.join(repo_path, "start")
    with open(existing_start, "w") as f:
        f.write(EXISTING_START_CONTENT)
    os.chmod(existing_start, 0o755)

    binder_vre_not_repo_only._write_start_script(repo_path)

    # New start should exist, be executable, and source the preserved one
    new_start = os.path.join(repo_path, "start")
    assert os.path.isfile(new_start)
    assert os.access(new_start, os.X_OK)

    with open(new_start) as f:
        content = f.read()
    assert "source ./start." in content
    # Original start already execs "$@", so our wrapper must not
    assert 'exec "$@"' not in content

    # The preserved script should still be on disk, executable, with original content
    preserved_files = [f for f in os.listdir(repo_path) if f.startswith("start.")]
    assert len(preserved_files) == 1
    preserved_path = os.path.join(repo_path, preserved_files[0])
    assert os.access(preserved_path, os.X_OK)
    with open(preserved_path) as f:
        assert f.read() == EXISTING_START_CONTENT


def test_write_start_script_no_existing_no_remote(binder_vre_not_repo_only, tmpdir):
    """No existing start and no remote files: no start script is created."""
    repo_path = str(tmpdir / "test_repo")
    os.makedirs(repo_path)

    binder_vre_not_repo_only._write_start_script(repo_path)

    # No start script should have been created
    assert not os.path.isfile(os.path.join(repo_path, "start"))


def test_write_start_script_existing_plus_remote_files(
    binder_vre_not_repo_only_with_remote, tmpdir
):
    """Existing start + remote files: datahugger lines come first, then source."""
    repo_path = str(tmpdir / "test_repo")
    os.makedirs(repo_path)

    # Simulate a cloned repo that already has a start script
    existing_start = os.path.join(repo_path, "start")
    with open(existing_start, "w") as f:
        f.write(EXISTING_START_CONTENT)
    os.chmod(existing_start, 0o755)

    binder_vre_not_repo_only_with_remote._write_start_script(repo_path)

    # New start should exist and contain both datahugger and source lines
    new_start = os.path.join(repo_path, "start")
    assert os.path.isfile(new_start)
    with open(new_start) as f:
        content = f.read()

    # datahugger download should appear before the source line
    assert "datahugger download" in content
    assert "source ./start." in content
    # Original start already execs "$@", so our wrapper must not
    assert 'exec "$@"' not in content

    idx_dh = content.index("datahugger")
    idx_source = content.index("source ./start.")
    assert idx_dh < idx_source

    # Preserved script should exist with original content
    preserved_files = [f for f in os.listdir(repo_path) if f.startswith("start.")]
    assert len(preserved_files) == 1
    preserved_path = os.path.join(repo_path, preserved_files[0])
    with open(preserved_path) as f:
        assert f.read() == EXISTING_START_CONTENT


# =============================================================================
# Tests for _ensure_start_in_dockerfile
# =============================================================================


def test_ensure_dockerfile_absent_does_nothing(binder_vre_not_repo_only, tmpdir):
    """Dockerfile is not created when it doesn't already exist."""
    repo_path = str(tmpdir / "test_repo")
    os.makedirs(repo_path)

    # Create a start script so the guard passes
    start_path = os.path.join(repo_path, "start")
    with open(start_path, "w") as f:
        f.write("#!/bin/bash\necho ok\n")
    os.chmod(start_path, 0o755)

    binder_vre_not_repo_only._ensure_start_in_dockerfile(repo_path)

    assert not os.path.isfile(os.path.join(repo_path, "Dockerfile"))


def test_ensure_dockerfile_present_no_start_does_nothing(
    binder_vre_not_repo_only, tmpdir
):
    """Dockerfile is left unchanged when no start script exists."""
    repo_path = str(tmpdir / "test_repo")
    os.makedirs(repo_path)

    dockerfile_path = os.path.join(repo_path, "Dockerfile")
    original = "FROM ubuntu:latest\n"
    with open(dockerfile_path, "w") as f:
        f.write(original)

    binder_vre_not_repo_only._ensure_start_in_dockerfile(repo_path)

    with open(dockerfile_path) as f:
        assert f.read() == original


def test_ensure_dockerfile_present_with_start_patches(binder_vre_not_repo_only, tmpdir):
    """Dockerfile is patched to invoke start when both exist."""
    repo_path = str(tmpdir / "test_repo")
    os.makedirs(repo_path)

    # Create both Dockerfile and start
    dockerfile_path = os.path.join(repo_path, "Dockerfile")
    with open(dockerfile_path, "w") as f:
        f.write("FROM ubuntu:latest\n")

    start_path = os.path.join(repo_path, "start")
    with open(start_path, "w") as f:
        f.write("#!/bin/bash\necho ok\n")
    os.chmod(start_path, 0o755)

    binder_vre_not_repo_only._ensure_start_in_dockerfile(repo_path)

    with open(dockerfile_path) as f:
        content = f.read()

    assert 'ENTRYPOINT ["/usr/local/bin/start"]' in content
    assert "COPY start /usr/local/bin/start" in content
