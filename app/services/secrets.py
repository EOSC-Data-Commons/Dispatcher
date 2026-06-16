"""Temporary secret storage backed by Redis.

Provides atomic one-time retrieval of secrets via opaque reference keys,
so that sensitive values never enter the Celery task-serialization pipeline.
"""

import uuid
import os
import logging
from typing import Optional

import redis

logger = logging.getLogger(__name__)

# Lua script for atomic GET + DELETE in a single Redis round-trip.
_GET_AND_DELETE_LUA = """
local value = redis.call('GET', KEYS[1])
if value then
    redis.call('DEL', KEYS[1])
end
return value
"""


class SecretStore:
    """Stores a secret under a random reference key with a TTL.

    The caller passes only the opaque reference through the message broker;
    the worker retrieves (and atomically destroys) the real value.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or self._default_redis_url()
        self._redis: redis.Redis | None = None
        self._lua_script: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def put(self, secret: str, ttl: int = 300) -> str:
        """Store *secret* and return an opaque reference key.

        Args:
            secret: The value to protect.
            ttl: Time-to-live in seconds (default 300 – 5 min).

        Returns:
            A UUID that must be passed to :meth:`get_and_delete`.
        """
        ref_key = str(uuid.uuid4())
        self._client.setex(ref_key, ttl, secret)
        logger.debug("Stored secret ref_key=%s ttl=%d", ref_key, ttl)
        return ref_key

    def get_and_delete(self, ref_key: str) -> str | None:
        """Atomically retrieve and remove the secret referenced by *ref_key*.

        Returns ``None`` when the key does not exist (expired or already
        consumed).
        """
        script = self._lua_script
        if script is None:
            script = self._client.register_script(_GET_AND_DELETE_LUA)
            self._lua_script = script

        raw = script(keys=[ref_key])
        if raw is None:
            logger.warning(
                "Secret not found for ref_key=%s (expired or already consumed)",
                ref_key,
            )
            return None

        value = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        logger.debug("Retrieved and deleted secret for ref_key=%s", ref_key)
        return value

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _client(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.Redis.from_url(self._redis_url)
        return self._redis

    @staticmethod
    def _default_redis_url() -> str:
        celery_broker = os.environ.get("CELERY_BROKER_URL")
        if celery_broker:
            return celery_broker
        # Fallback when running without the full Celery env (e.g. local dev).
        return "redis://localhost:6379/0"
