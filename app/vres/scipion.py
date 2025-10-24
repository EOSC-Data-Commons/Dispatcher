from .base_vre import VRE, vre_factory
import logging
from fastapi import HTTPException

logging.basicConfig(level=logging.INFO)


class VREScipion(VRE):
    def get_default_service(self):
        return "https://scipion.i2pc.es/"

    def post(self):
        return self.svc_url
    

vre_factory.register("http://scipion.i2pc.es/", VREScipion)
