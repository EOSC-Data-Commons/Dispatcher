from .vre import VRE, vre_factory

import logging
logger = logging.getLogger('uvicorn.error')

default_service = "https://mybinder.org/"

# touch .git/git-daemon-export-ok


class VREBinder(VRE):
    def post(self):
        logger.debug('VREBinder')

        svc = self.root.get("runsOn")
        if svc is None:
            url = default_service
        else:
            url = svc["url"]

        url = url.rstrip("/")

        return None


vre_factory.register("https://jupyter.org/binder/", VREBinder)
