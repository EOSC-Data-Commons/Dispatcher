import os

from celery import Celery


celery = Celery(__name__, include=['app.tasks'])
celery.conf.update(accept_content = ['pickle'])
celery.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379")
celery.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379")

from app.worker import celery
from app.internal.vre import vre_factory
from rocrate.rocrate import ROCrate
from fastapi import UploadFile, Depends
from app.internal.galaxy import VREGalaxy
from app.internal.binder import VREBinder


@celery.task(name="galaxy_from_zipfile")
def galaxy_from_zipfile(parsed_zipfile: (ROCrate, UploadFile)):
    vre_handler = vre_factory(*parsed_zipfile)
    return {"url": vre_handler.post()}

