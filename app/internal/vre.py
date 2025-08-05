from rocrate.rocrate import ROCrate
import sys
import json
import zipfile
from .im import IM
from fastapi import HTTPException

from abc import ABC, abstractmethod

import logging

logger = logging.getLogger("uvicorn.error")


class VRE(ABC):
    def __init__(self, crate=None, body=None, token=None):
        self.crate = crate
        self.body = body
        self.token = token
        self.entities = {e.id: e for e in crate.get_entities()}
        self.root = self.entities["./"]
        self.workflow = self.root["mainEntity"]
        self.svc_url = self.setup_service()
        # TODO: sanity check, type contains File,SoftwareSourceCode,ComputationalWorkflow

    @abstractmethod
    def get_default_service(self):
        pass

    def setup_service(self):
        svc = self.root.get("runsOn")
   
        if svc is None:
            return self.get_default_service()
        if svc.get("@type") == "Service":
            return svc.get("url", self.get_default_service())
        elif svc.get("@type") == "SoftwareApplication":
            # Send this destination to the IM to deploy the service
            # and get the URL of the deployed service
            # For now only IM, should be extended to other service providers
            im = IM(self.token)
            outputs = im.run_service(svc)
            if outputs is None:
                raise HTTPException(
                    status_code=400, detail="Failed to deploy service"
                )
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

    def register(self, vre_type, cls):
        if vre_type in self.table:
            raise ValueError(f"{vre_type} already registered")

        self.table[vre_type] = cls

    def __call__(self, crate, body=None, **kwargs):
        elang = self.get_elang(crate)
        logger.debug(f"crate {crate}")
        logger.debug(f"elang {elang}")
        if elang not in self.table:
            raise HTTPException(status_code=400, detail="Unsupported workflow language")
        logger.debug(self.table[elang])
        return self.table[elang](crate=crate, body=body, **kwargs)
    
    def get_elang(self,crate):
        try:
            emap = {e.id: e for e in crate.get_entities()}
            elang = emap["./"]["mainEntity"]["programmingLanguage"]["identifier"]
            return elang
        except (KeyError, ValueError) as e:
            logger.debug(f"Error parsing ROCrate reason: {e}")
            raise HTTPException(status_code=400, detail="Failed to parse ROCrate")


vre_factory = VREFactory()

if __name__ == "__main__":
    with open(sys.argv[1]) as j:
        vre_factory(j.read())
