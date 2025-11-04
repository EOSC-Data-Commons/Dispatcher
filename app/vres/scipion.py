from .base_vre import VRE, vre_factory
import logging
from fastapi import HTTPException
from app.constants import SCIPION_DEFAULT_SERVICE, SCIPION_PROGRAMMING_LANGUAGE

logging.basicConfig(level=logging.INFO)


class VREScipion(VRE):
    def get_default_service(self):
        return SCIPION_DEFAULT_SERVICE

    def post(self):
        return self.svc_url


vre_factory.register(SCIPION_PROGRAMMING_LANGUAGE, VREScipion)
