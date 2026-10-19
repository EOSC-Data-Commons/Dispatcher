"""Fail-fast healthcheck of external VRE providers.

Before dispatching a request, the target provider URL is probed with a
short-timeout HTTP GET so that requests against unavailable providers fail
immediately instead of hanging on connection or read timeouts.
"""

import logging

import requests

from app import exceptions
from app.config import settings

logger = logging.getLogger(__name__)


def check_service_alive(url: str) -> None:
    """Probe a VRE provider URL; raise VREUnavailableError if unavailable.

    Any HTTP response with status < 500 (including 401/403/404) counts as
    "the server is up". Connection errors, DNS failures, TLS failures,
    timeouts, malformed URLs, and 5xx responses count as unavailable.
    """
    if not settings.vre_healthcheck_enabled:
        return

    timeout = settings.vre_healthcheck_timeout
    logger.debug("VRE healthcheck GET %s (timeout %.1fs)", url, timeout)
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        logger.error("VRE healthcheck failed for %s: %s", url, e)
        raise exceptions.VREUnavailableError(
            f"VRE service {url} is unreachable: {e}"
        ) from e

    if response.status_code >= 500:
        logger.error(
            "VRE healthcheck failed for %s: HTTP %d", url, response.status_code
        )
        raise exceptions.VREUnavailableError(
            f"VRE service {url} responded with HTTP {response.status_code}"
        )
