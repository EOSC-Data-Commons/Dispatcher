"""Binder VRE implementation.

This module implements the Binder repository creation VRE, which creates
temporary Git repositories from ROCrate ZIP files for Binder deployment.
"""

import io
import logging
import os
import urllib
import zipfile
from typing import Any

import git
from app.config import settings
from app.constants import BINDER_DEFAULT_SERVICE, BINDER_PROGRAMMING_LANGUAGE

from .base_vre import VRE, vre_factory

logger = logging.getLogger("uvicorn.error")


class VREBinder(VRE):
    """Binder repository creation VRE."""

    def get_default_service(self) -> str:
        """Return the default Binder service URL."""
        return BINDER_DEFAULT_SERVICE

    def post(self) -> str:
        """Create a Git repository from the ZIP body and return Binder URL.

        Returns:
            URL to access the Binder instance.
        """
        repo = self._generate_repository_name(self._request_id)
        self._create(repo)
        self._write_source_files(repo)
        self._initialize_temporary_git_repo(repo)
        self._write_example_file(repo)
        return self._get_binder_url(self._request_id)

    def _create(self, repo: str) -> None:
        """Create the repository directory.

        Args:
            repo: Path to the repository directory.
        """
        os.mkdir(repo)

    def _get_binder_url(self, request_id: int) -> str:
        """Build the Binder URL for the repository.

        Args:
            request_id: The unique request identifier.

        Returns:
            Complete Binder URL.
        """
        url = self.svc_url.rstrip("/")
        local_git_url = f"https://{settings.host}/git/{request_id}"
        logger.debug(local_git_url)
        return f"{url}/git/{urllib.parse.quote_plus(local_git_url)}/HEAD"

    def _write_example_file(self, repo: str) -> None:
        """Write the git-daemon-export-ok file to enable git daemon access.

        Args:
            repo: Path to the repository directory.
        """
        with open(f"{repo}/.git/git-daemon-export-ok", "w") as f:
            f.write("I am here\n")

    def _initialize_temporary_git_repo(self, repo_path: str) -> None:
        """Initialize a Git repository with default configuration.

        Args:
            repo_path: Path to the repository directory.
        """
        os.chdir(repo_path)

        repo = git.Repo.init(repo_path)
        with repo.config_writer() as git_config:
            git_config.set_value("user", "email", "dispatcher@dispatcher.com")
            git_config.set_value("user", "name", "dispatcher")

        repo.index.add("*")
        repo.index.commit("on the fly")

    def _generate_repository_name(self, request_id: int) -> str:
        """Generate a unique repository path.

        Args:
            request_id: The unique request identifier.

        Returns:
            Full path for the repository directory.
        """
        gitrepos = settings.git_repos
        return f"{gitrepos}/{request_id}"

    def _write_source_files(self, repo: str) -> None:
        """Extract files from the ZIP body to the repository.

        Excludes ro-crate-metadata.json as it's not needed for Binder.

        Args:
            repo: Path to the repository directory.
        """
        if not self.body:
            raise ValueError("No body provided for file extraction")

        logger.debug(f"{self.__class__.__name__}: unzipping ROCrate")
        with io.BytesIO(self.body) as bytes_io:
            with zipfile.ZipFile(bytes_io) as zfile:
                for filename in zfile.namelist():
                    logger.debug("  " + filename)
                    if filename != "ro-crate-metadata.json":
                        with zfile.open(filename) as z, open(
                            f"{repo}/{filename}", "wb"
                        ) as f:
                            f.write(z.read())


vre_factory.register(BINDER_PROGRAMMING_LANGUAGE, VREBinder)
