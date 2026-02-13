from .base_vre import VRE, vre_factory
import zipfile as zf
import io
import logging
import os
import subprocess
import urllib
import uuid
from app.config import settings
from app.constants import BINDER_DEFAULT_SERVICE, BINDER_PROGRAMMING_LANGUAGE
import git
import os

logger = logging.getLogger("uvicorn.error")


class VREBinder(VRE):
    def get_default_service(self):
        return BINDER_DEFAULT_SERVICE

    def post(self):
        repo = self._generate_repository_name(self._request_id)
        self._create(repo)
        self._write_source_files(repo)
        self._initialize_temporary_git_repo(repo)
        self._write_example_file(repo)
        return self._get_binder_url(self._request_id)

    def _create(self, repo):
        os.mkdir(repo)

    def _get_binder_url(self, request_id):
        url = self.svc_url.rstrip("/")
        local_git_url = f"https://{settings.host}/git/{request_id}"
        logger.debug(local_git_url)
        return f"{url}/git/{urllib.parse.quote_plus(local_git_url)}/HEAD"

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

    def _write_source_files(self, repo):
        logger.debug(f"{__class__.__name__}: unzipping ROCrate")
        with io.BytesIO(self.body) as bytes_io:
            with zf.ZipFile(bytes_io) as zfile:
                for filename in zfile.namelist():
                    logger.debug("  " + filename)
                    if filename != "ro-crate-metadata.json":
                        with zfile.open(filename) as z, open(
                            f"{repo}/{filename}", "wb"
                        ) as f:
                            f.write(z.read())


vre_factory.register(BINDER_PROGRAMMING_LANGUAGE, VREBinder)
