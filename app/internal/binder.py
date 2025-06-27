from .vre import VRE, vre_factory

import logging

logger = logging.getLogger("django")

default_service = "https://mybinder.org/"

# touch .git/git-daemon-export-ok


class VREBinder(VRE):
    def post(self):
        return None


vre_factory.register("https://jupyter.org/binder/", VREBinder)
