"""
Celery worker configuration for the dispatcher application.

This module configures Celery with application logging integration.
"""

import os
import logging

from celery import Celery
from app.config import settings
from app.logging_config import setup_logging

# Initialize logging for Celery worker
setup_logging(
    log_level=settings.log_level,
    log_format=settings.log_format,
    disable_uvicorn_access=True,
)

logger = logging.getLogger(__name__)

celery = Celery(__name__, include=["app.celery.tasks"])
celery.conf.update(accept_content=["pickle", "json"])
celery.conf.broker_url = os.environ.get(
    "CELERY_BROKER_URL", f"redis://localhost:{settings.redis_port}"
)
celery.conf.result_backend = os.environ.get(
    "CELERY_RESULT_BACKEND", f"redis://localhost:{settings.redis_port}"
)

# Configure Celery logging
celery.conf.worker_hijack_root_logger = False
celery.conf.worker_redirect_stdouts = False


@celery.on_after_finalize.connect
def on_worker_ready(sender, **kwargs):
    """Log when Celery worker is initialized."""
    logger.info("Celery worker initialized")
