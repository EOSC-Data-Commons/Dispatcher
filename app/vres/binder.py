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

logger = logging.getLogger("uvicorn.error")

# TODO: cleanup the created repos

# touch .git/git-daemon-export-ok


class VREBinder(VRE):
    def get_default_service(self):
        return BINDER_DEFAULT_SERVICE

    def post(self, request_id):
        repo = self._generate_repository_name(request_id)
        self._create(repo)
        self._write_source_files(repo)
        self._initialize_temporary_git_repo(repo)
        self._write_example_file(repo)
        return self._get_binder_url(request_id)

    def _create(self, repo):
        os.mkdir(repo)

    def _get_binder_url(self, request_id):
        url = self.svc_url.rstrip("/")
        # TODO: hardcoded value of /git path
        local_git_url = f"https://{settings.host}/git/{request_id}"
        logger.debug(local_git_url)
        return f"{url}/git/{urllib.parse.quote_plus(local_git_url)}/HEAD"

    def _write_example_file(self, repo):
        with open(f"{repo}/.git/git-daemon-export-ok", "w") as f:
            f.write("I am here\n")

    def _initialize_temporary_git_repo(self, repo):
        result = subprocess.run(
            f'cd {repo} && git init && git config user.email "dispatcher@dispatcher.com" && git config user.name "dispatcher" && git add * && git commit -m "on the fly"',
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(result)
            raise RuntimeError("create temporary git repo")

        logger.info(result.stdout)
        logger.info(result.stderr)

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
