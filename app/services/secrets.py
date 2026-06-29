"""Temporary secret storage backed by Redis.

Provides retrieval of secrets via opaque reference keys so that sensitive
values never enter the Celery task-serialization pipeline.
"""

import uuid
import os
import logging

import redis

logger = logging.getLogger(__name__)


class SecretStore:
    """Stores a secret under a random reference key with a TTL.

    The caller passes only the opaque reference through the message broker;
    the worker reads the secret, uses it, and then explicitly deletes it on
    success so that Celery auto‑retries can re‑read it.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or self._default_redis_url()
        self._redis: redis.Redis | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def put(self, secret: str, ttl: int = 300) -> str:
        """Store *secret* and return an opaque reference key.

        Args:
            secret: The value to protect.
            ttl: Time-to-live in seconds (default 300 – 5 min).

        Returns:
            A UUID that must be passed to :meth:`get`.
        """
        ref_key = str(uuid.uuid4())
        self._client.setex(ref_key, ttl, secret)
        logger.debug("Stored secret ref_key=%s ttl=%d", ref_key, ttl)
        return ref_key

    def get(self, ref_key: str) -> str | None:
        """Retrieve the secret referenced by *ref_key* without removing it.

        Returns ``None`` when the key does not exist (expired).
        """
        raw = self._client.get(ref_key)
        if raw is None:
            logger.warning("Secret not found for ref_key=%s (expired)", ref_key)
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else raw

    def delete(self, ref_key: str) -> None:
        """Delete the secret referenced by *ref_key* (no-op if missing)."""
        self._client.delete(ref_key)

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
