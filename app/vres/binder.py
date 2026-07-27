from __future__ import annotations

from .base_vre import VRE, vre_factory
import os
import urllib.parse
import uuid
from app.config import settings
from vre_rocrate import BINDER_PROGRAMMING_LANGUAGE
from app.constants import BINDER_DEFAULT_SERVICE
from app.exceptions import UnsupportedBinderSource
import git
import logging
import tempfile
import shutil
from typing import Optional

logger = logging.getLogger(__name__)


class VREBinder(VRE):
    def get_default_service(self):
        return BINDER_DEFAULT_SERVICE

    def post(self) -> str:
        if self.request_package.is_repository_only:
            workflow_url = self.request_package.workflow.url
            return self._build_binder_url(workflow_url)
        return self._build_local_git_repo()

    def _build_binder_url(self, url: str) -> str:
        """Construct BinderHub URL from GitHub or Zenodo URL.

        Args:
            url: Either a GitHub repo URL (https://github.com/org/repo[/tree/branch])
                 or a Zenodo DOI URL (https://doi.org/10.xxxx/zenodo.NNNN)

        Returns:
            BinderHub URL for the repository

        Raises:
            UnsupportedBinderSource: If URL is neither GitHub nor Zenodo
        """
        if "github.com" in url:
            return self._build_github_binder_url(url)
        if "zenodo" in url:
            return self._build_zenodo_binder_url(url)
        raise UnsupportedBinderSource(f"Unsupported repository source: {url}")

    def _build_github_binder_url(self, url: str) -> str:
        """Build BinderHub URL for GitHub repository.

        Parses URLs like:
        - https://github.com/org/repo → /v2/gh/org/repo/HEAD
        - https://github.com/org/repo/tree/branch → /v2/gh/org/repo/branch
        """
        parsed = urllib.parse.urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]  # Remove empty strings

        if len(path_parts) < 2:
            raise UnsupportedBinderSource(f"Invalid GitHub URL: {url}")

        org = path_parts[0]
        repo = path_parts[1]

        # Check for branch specification (/tree/branch)
        ref = "HEAD"
        if len(path_parts) >= 4 and path_parts[2] == "tree":
            ref = path_parts[3]

        return f"{self.svc_url}/v2/gh/{org}/{repo}/{ref}"

    def _build_zenodo_binder_url(self, url: str) -> str:
        """Build BinderHub URL for Zenodo DOI.

        Parses URLs like:
        - https://doi.org/10.5281/zenodo.12345 → /v2/zenodo/10.5281/zenodo.12345/
        """
        # Extract DOI from URL
        doi = url
        for prefix in ("https://doi.org/", "http://doi.org/"):
            if doi.startswith(prefix):
                doi = doi[len(prefix) :]
                break

        return f"{self.svc_url}/v2/zenodo/{doi}/"

    def _build_local_git_repo(self) -> str:
        """Prepare a local git repo from source files and optional remote clone, return Binder git URL."""
        repo = self._generate_repository_name(self._request_id)
        self._create(repo)
        self._write_source_files(repo)
        self._clone_remote_files(self.request_package.workflow.url, repo)
        self._write_start_script(repo)
        self._ensure_start_in_dockerfile(repo)
        self._initialize_temporary_git_repo(repo)
        self._write_example_file(repo)
        url = self.svc_url.rstrip("/")
        local_git_url = (
            f"https://{settings.host}{settings.git_url_prefix}/{self._request_id}"
        )
        logger.debug(local_git_url)
        return f"{url}/v2/git/{urllib.parse.quote_plus(local_git_url)}/HEAD"

    def _create(self, repo):
        os.mkdir(repo)

    def _write_example_file(self, repo):
        with open(f"{repo}/.git/git-daemon-export-ok", "w") as f:
            f.write("I am here\n")

    def _initialize_temporary_git_repo(self, repo_path):
        os.chdir(repo_path)

        repo = git.Repo.init(repo_path)
        with repo.config_writer() as git_config:
            git_config.set_value("user", "email", "dispatcher@dispatcher.com")
            git_config.set_value("user", "name", "dispatcher")

        repo.index.add("*")

        repo.index.commit("on the fly")

    def _generate_repository_name(self, request_id):
        gitrepos = settings.git_repos
        return f"{gitrepos}/{request_id}"

    def _write_source_files(self, repo: str) -> None:
        """Write local files from request package to repo directory.

        Validates that filenames do not contain path traversal sequences (..).
        """
        logger.debug(f"{__class__.__name__}: writing source files from request package")
        for fref in self.request_package.local_files:
            filename = fref.id
            # Reject filenames with path traversal attempts
            if ".." in filename:
                logger.warning(
                    f"Skipping file with invalid name (path traversal attempt): {filename}"
                )
                continue
            content = fref.properties.get("content")
            if content is not None:
                with open(os.path.join(repo, filename), "wb") as f:
                    f.write(content if isinstance(content, bytes) else content.encode())

    def _write_start_script(self, repo: str) -> None:
        """Write Binder start script that stages data and sources an existing start.

        If a ``start`` script already exists in the repository (e.g. cloned from
        a remote repo), it is renamed to a unique name and sourced by the newly
        generated script so the original startup logic is preserved.

        For each remote file in the request package, generates a datahugger
        download command.  The script hands control back to Binder via ``exec "$@"``
        so Jupyter starts normally after the files are staged.
        """
        existing_start = os.path.join(repo, "start")
        renamed_start: str | None = None

        # Preserve a pre-existing start script from a cloned repository
        if os.path.isfile(existing_start):
            unique_name = f"start.{uuid.uuid4().hex[:8]}"
            renamed_start = os.path.join(repo, unique_name)
            os.rename(existing_start, renamed_start)
            os.chmod(renamed_start, 0o755)
            logger.debug(
                f"{__class__.__name__}: preserved existing start as {unique_name}"
            )

        remote_files = self.request_package.remote_files
        download_lines: list[str] = []
        if remote_files:
            for fref in remote_files:
                if not fref.url:
                    continue
                download_lines.append(
                    f'./datahugger download "{fref.url}" --to "data/"'
                )

        if not download_lines and renamed_start is None:
            return

        script_path = os.path.join(repo, "start")
        logger.debug(
            f"{__class__.__name__}: writing start script "
            f"(downloads={len(download_lines)}, sourced={renamed_start is not None})"
        )
        with open(script_path, "w") as f:
            f.write("#!/bin/bash\n")
            f.write("set -e\n")
            f.write("\n")

            if download_lines:
                f.write("# Data staging via datahugger\n")
                for line in download_lines:
                    f.write(f"{line}\n")
                f.write("\n")

            if renamed_start is not None:
                f.write("# Source original start script from repository\n")
                f.write("# (renamed from 'start' to avoid overwrite)\n")
                f.write(f"source ./{os.path.basename(renamed_start)}\n")
                f.write("\n")

            f.write("# Hand control back to Binder so Jupyter actually starts\n")
            f.write('exec "$@"\n')

        # Make the script executable
        os.chmod(script_path, 0o755)

    def _ensure_start_in_dockerfile(self, repo: str) -> None:
        """Patch Dockerfile to invoke the generated start script if both exist.

        When a cloned repository contains a Dockerfile, Binder/repo2docker uses
        it verbatim and ignores the repo-root ``start`` script.  Appending
        ``COPY``, ``RUN chmod`` and ``ENTRYPOINT`` ensures the generated
        ``start`` is executed inside the container.
        """
        dockerfile_path = os.path.join(repo, "Dockerfile")
        start_path = os.path.join(repo, "start")

        if not os.path.isfile(dockerfile_path):
            return
        if not os.path.isfile(start_path):
            return

        container_path = "/usr/local/bin/dispatcher-start"
        with open(dockerfile_path, "a") as f:
            f.write("\n# Added by dispatcher - start script integration\n")
            f.write(f"COPY start {container_path}\n")
            f.write(f"RUN chmod +x {container_path}\n")
            f.write(f'ENTRYPOINT ["{container_path}"]\n')

        logger.debug(f"{__class__.__name__}: patched Dockerfile to invoke start script")

    def _clone_remote_files(self, url: Optional[str], repo_path: str) -> None:
        """Clone remote repository working tree into repo_path.

        Only clones the working tree (not .git metadata) using shallow clone.
        Does nothing if url is None.

        Args:
            url: Remote repository URL (GitHub only for now)
            repo_path: Local directory to copy files into
        """
        if url is None:
            return

        # Only support GitHub URLs for cloning
        if "github.com" not in url:
            logger.warning(f"Skipping remote clone for non-GitHub URL: {url}")
            return

        try:
            # Parse URL to get org/repo
            parsed = urllib.parse.urlparse(url)
            path_parts = [p for p in parsed.path.split("/") if p]

            if len(path_parts) < 2:
                logger.warning(f"Invalid GitHub URL for cloning: {url}")
                return

            org = path_parts[0]
            repo = path_parts[1]
            clone_url = f"https://github.com/{org}/{repo}.git"

            # Create temp directory for clone
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Shallow clone to save time/space
                git.Repo.clone_from(clone_url, tmp_dir, depth=1)

                # Copy working tree files (excluding .git)
                for item in os.listdir(tmp_dir):
                    if item == ".git":
                        continue
                    src = os.path.join(tmp_dir, item)
                    dst = os.path.join(repo_path, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)

        except Exception as e:
            logger.warning(f"Failed to clone remote repository {url}: {e}")


vre_factory.register(BINDER_PROGRAMMING_LANGUAGE, VREBinder)
