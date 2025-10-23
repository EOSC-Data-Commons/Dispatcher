from .base_vre import VRE, vre_factory
import zipfile as zf
import io
import logging
import os
import subprocess
import urllib
import uuid
from app.config import settings
from . import constants

logger = logging.getLogger("uvicorn.error")

# TODO: cleanup the created repos

# touch .git/git-daemon-export-ok


class VREBinder(VRE):
    def get_default_service(self):
        return constants.BINDER_DEFAULT_SERVICE

    def post(self):
        request_id = str(uuid.uuid4())
        url = self.svc_url

        url = url.rstrip("/")

        gitrepos = settings.git_repos
        repo = f"{gitrepos}/{request_id}"

        os.mkdir(repo)
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
        with open(f"{repo}/.git/git-daemon-export-ok", "w") as f:
            f.write("I am here\n")

        git = f"https://{settings.host}/git/{request_id}"
        logger.debug(git)
        return f"{url}/git/{urllib.parse.quote_plus(git)}/HEAD"


vre_factory.register(constants.BINDER_PROGRAMMING_LANGUAGE, VREBinder)
