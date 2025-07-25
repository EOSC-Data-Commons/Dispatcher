import os

from celery import Celery


celery = Celery(__name__, include=["app.tasks"])
celery.conf.update(accept_content=["pickle"])
celery.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379")
celery.conf.result_backend = os.environ.get(
    "CELERY_RESULT_BACKEND", "redis://localhost:6379"
)
