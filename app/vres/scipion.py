from .base_vre import VRE, vre_factory
import logging
from fastapi import HTTPException

logging.basicConfig(level=logging.INFO)


class VREScipion(VRE):
    def post(self):
        return self.svc_url
    

vre_factory.register("http://scipion.i2pc.es/", VREScipion)
