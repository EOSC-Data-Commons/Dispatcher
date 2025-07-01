from app.worker import celery
from app.internal import 

@celery.task(name="galaxy_from_zipfile")
def galaxy_from_zipfile(parsed_zipfile: (ROCrate, UploadFile)):
    vre_handler = vre_factory(*parsed_zipfile)
    return {"url": await vre_handler.post()}
