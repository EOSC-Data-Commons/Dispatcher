from .base_vre import VRE, vre_factory
import logging
from vre_rocrate import SCIPION_PROGRAMMING_LANGUAGE
from app.constants import SCIPION_DEFAULT_SERVICE

logger = logging.getLogger(__name__)


class VREScipion(VRE):
    def get_default_service(self):
        return SCIPION_DEFAULT_SERVICE

    async def post(self):
        return self.require_service_url()


vre_factory.register(SCIPION_PROGRAMMING_LANGUAGE, VREScipion)
