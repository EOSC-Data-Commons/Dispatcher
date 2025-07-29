from .vre import VRE, vre_factory
import zipfile as zf
import io
import logging
import os
import subprocess
import urllib
import app.internal.config as config

logger = logging.getLogger("uvicorn.error")

# TODO: cleanup the created repos

default_service = "https://mybinder.org/v2"

# touch .git/git-daemon-export-ok


class VREBinder(VRE):
    async def post(self, svc, request_id):
        if svc is None:
            url = default_service
        else:
            url = svc["url"]

        url = url.rstrip("/")

        gitrepos = config.config["git"]["repos"]
        repo = f"{gitrepos}/{request_id}"

        os.mkdir(repo)

        logger.debug(f"{__class__.__name__}: unzipping ROCrate")
        with zf.ZipFile(io.BytesIO(self.body)) as zfile:
            for filename in zfile.namelist():
                logger.debug("  " + filename)
                if filename != "ro-crate-metadata.json":
                    with zfile.open(filename) as z, open(
                        f"{repo}/{filename}", "wb"
                    ) as f:
                        f.write(z.read())

        result = subprocess.run(
            f'cd {repo} && git init && git add * && git commit -m "on the fly"',
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

        git = f'http://{config.config["hostname"]}:{config.config["nginx"]["port"]}/git/{request_id}'
        logger.debug(git)
        return f"{url}/git/{urllib.parse.quote_plus(git)}/HEAD"


vre_factory.register("https://jupyter.org/binder/", VREBinder)
