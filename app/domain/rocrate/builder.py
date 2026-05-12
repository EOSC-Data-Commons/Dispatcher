from __future__ import annotations
from .models import ParsedCrate
from .request_package import RequestPackage
from .validator import ValidationPipeline


class RequestPackageBuilder:
    @classmethod
    def build(cls, crate: ParsedCrate) -> RequestPackage:
        ValidationPipeline.validate_basic(crate)
        return RequestPackage.from_parsed_crate(crate)
