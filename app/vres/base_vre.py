import sys
from app.services.im import IM
from fastapi import HTTPException
from abc import ABC, abstractmethod

import logging

logger = logging.getLogger("uvicorn.error")


class ROCrateValidationError(Exception):
    pass


class VRE(ABC):
    def __init__(self, crate=None, body=None, token=None):
        self.crate = crate
        self.body = body
        self.token = token
        self.svc_url = self.setup_service().rstrip("/")
        # TODO: sanity check, type contains File,SoftwareSourceCode,ComputationalWorkflow

    @abstractmethod
    def get_default_service(self):
        pass

    def setup_service(self):
        dest = self.crate.root_dataset.get("runsOn")

        if dest is None:
            return self.get_default_service()
        if dest.get("serviceType") == "PublicService":
            return dest.get("url", self.get_default_service())
        elif dest.get("serviceType") == "InfrastructureManager":
            im = IM(self.token)
            outputs = im.run_service(dest)
            if outputs is None:
                raise HTTPException(status_code=400, detail="Failed to deploy service")
            return outputs.get("url")
        else:
            raise HTTPException(
                status_code=400, detail="Invalid service type in runsOn"
            )

    @abstractmethod
    def post():
        pass


class VREFactory:
    instance = None
    table = {}

    def __new__(cls, *args, **kwargs):
        if not cls.instance:
            cls.instance = super(VREFactory, cls).__new__(cls, *args, **kwargs)
        return cls.instance

    def is_registered(self, vre_type):
        return vre_type in self.table

    def register(self, vre_type, cls):
        if self.is_registered(vre_type):
            raise ValueError(f"{vre_type} already registered")
        self.table[vre_type] = cls

    def __call__(self, crate, body=None, **kwargs):
        elang = crate.mainEntity.get("programmingLanguage").get("identifier")
        if not self.is_registered(elang):
            raise ValueError(f"Unsupported workflow language {elang}")
        logger.debug(f"crate {crate}")
        logger.debug(f"elang {elang}")
        logger.debug(self.table[elang])
        return self.table[elang](crate=crate, body=body, **kwargs)


vre_factory = VREFactory()

if __name__ == "__main__":
    with open(sys.argv[1]) as j:
        vre_factory(j.read())
