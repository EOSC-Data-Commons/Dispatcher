"""Scipion VRE implementation.

This module implements the Scipion workflow execution VRE, which creates
service deployments for Scipion workflows using Infrastructure Manager.
"""

import logging

from app.constants import SCIPION_DEFAULT_SERVICE, SCIPION_PROGRAMMING_LANGUAGE

from .base_vre import VRE, vre_factory

logging.basicConfig(level=logging.INFO)


class VREScipion(VRE):
    """Scipion workflow execution VRE."""

    def get_default_service(self) -> str:
        """Return the default Scipion service URL."""
        return SCIPION_DEFAULT_SERVICE

    def post(self) -> str:
        """Create Scipion service deployment.

        The service setup is handled by the base class via Infrastructure Manager.
        Returns the service URL after successful deployment.

        Returns:
            URL of the deployed Scipion service.
        """
        return self.svc_url


vre_factory.register(SCIPION_PROGRAMMING_LANGUAGE, VREScipion)
