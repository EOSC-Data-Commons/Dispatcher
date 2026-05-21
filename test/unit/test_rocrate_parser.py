from rocrate.rocrate import ROCrate
import zipfile as zf
import json
from fastapi import UploadFile
from fastapi.exceptions import HTTPException
from typing import Dict
import io
import copy

from unittest.mock import patch
import pytest
from fastapi import HTTPException

from app.routers.utils.vre import parse_rocrate


def test_parse_rocrate_success():
    rocrate_data = ROCrate().metadata.generate()
    result = parse_rocrate(copy.deepcopy(rocrate_data))

    assert isinstance(result, dict)
    assert rocrate_data == result


def test_parse_rocrate_validation_failure():
    rocrate_data = {"@context": "test", "@graph": [{"@id": "./", "@type": "Dataset"}]}

    with pytest.raises(HTTPException) as exc_info:
        parse_rocrate(rocrate_data)

    assert exc_info.value.status_code == 400
    assert "Invalid ROCrate data" in str(exc_info.value.detail)
