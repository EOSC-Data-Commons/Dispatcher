"""
Scipion VRE implementation for cryo-EM processing environments.
"""

from fastapi import HTTPException

from app.constants import SCIPION_DEFAULT_SERVICE, SCIPION_PROGRAMMING_LANGUAGE
import logging

from .base_vre import VRE, vre_factory

logger = logging.getLogger(__name__)


class VREScipion(VRE):
    def get_default_service(self):
        return SCIPION_DEFAULT_SERVICE

    def post(self):
        return self.svc_url


vre_factory.register(SCIPION_PROGRAMMING_LANGUAGE, VREScipion)
