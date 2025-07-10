from rocrate.rocrate import ROCrate
import sys
import json
import zipfile

from abc import ABC, abstractmethod

import logging
logger = logging.getLogger("uvicorn.error")

class VRE(ABC):
    def __init__(self, crate=None, body=None):
        self.crate = crate
        self.body = body
        self.entities = {e.id: e for e in crate.get_entities()}
        self.root = self.entities["./"]
        self.workflow = self.root["mainEntity"]

        # TODO: sanity check, type contains File,SoftwareSourceCode,ComputationalWorkflow

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
        try:
            logger.debug(f"crate {crate}")
            emap = {e.id: e for e in crate.get_entities()}

            ewf = emap["./"]["mainEntity"]
            elang = ewf["programmingLanguage"]["identifier"]
            logger.debug(f"ewf {ewf}")
            logger.debug(f"elang {elang}")
            logger.debug(self.table[elang])
            return self.table[elang](crate=crate, body=body, **kwargs)

        except Exception as e:
            print(f"exception {e}")
            raise ValueError(f"VREFactory: parse ROCrate") from e


vre_factory = VREFactory()

if __name__ == "__main__":
    with open(sys.argv[1]) as j:
        vre_factory(j.read())
