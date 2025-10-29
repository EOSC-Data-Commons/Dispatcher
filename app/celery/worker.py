import os
from celery import Celery
from app.config import settings

celery = Celery(__name__, include=["app.celery.tasks"])
celery.conf.update(accept_content=["pickle", "json"])
celery.conf.broker_url = os.environ.get("CELERY_BROKER_URL", f"redis://localhost:{settings.redis_port}")
celery.conf.result_backend = os.environ.get(
    "CELERY_RESULT_BACKEND", f"redis://localhost:{settings.redis_port}"
)
