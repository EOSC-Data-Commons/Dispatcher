from rocrate.rocrate import ROCrate
import zipfile as zf
import json
from fastapi import UploadFile
from fastapi.exceptions import HTTPException
from typing import Dict
import io
from app.exceptions import VREConfigurationError


def parse_rocrate(rocrate_data: Dict) -> Dict:
    try:
        crate = ROCrate(source=rocrate_data)
        validate_rocrate(crate)
        return crate.metadata.generate()
    except (ValueError, KeyError, VREConfigurationError) as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid ROCrate data. Reason: {e}"
        )


def validate_rocrate(crate: ROCrate):
    check_main_entity(crate)
    check_workflow_object(crate)
    check_workflow_language_object(crate)
    check_workflow_lang(crate)


def check_main_entity(crate: ROCrate):
    if crate.mainEntity is None:
        raise VREConfigurationError("Missing mainEntity inside ROCrate")


def check_workflow_object(crate: ROCrate):
    if type(crate.mainEntity) is str:
        raise VREConfigurationError("Missing main entiy object")


def check_workflow_language_object(crate: ROCrate):
    if type(crate.mainEntity.get("programmingLanguage")) is str:
        raise VREConfigurationError(f"Missing main entiy programmingLanguage object")


def check_workflow_lang(crate: ROCrate):
    if crate.mainEntity.get("programmingLanguage", {}).get("identifier") is None:
        raise VREConfigurationError(
            "Missing programmingLanguage identifier inside ROCrate's mainEntity"
        )


def parse_json_metadata(metadata: str):
    try:
        return json.loads(metadata)
    except json.decoder.JSONDecodeError as json_exception:
        raise HTTPException(
            status_code=400,
            detail=f"Handling request failed. Invalid JSON format: \n{json_exception}",
        )


async def parse_zipfile(zipfile: UploadFile):
    file_content = await zipfile.read()

    metadata = None
    with io.BytesIO(file_content) as file_like:
        with zf.ZipFile(file_like) as zfile:
            for filename in zfile.namelist():
                if filename == "ro-crate-metadata.json":
                    with zfile.open(filename) as file:
                        metadata = file.read()
        if metadata is None:
            raise HTTPException(
                status_code=400, detail="ro-crate-metadata.json not found in zip"
            )
    rocrate_json = parse_json_metadata(metadata)
    rocrate = parse_rocrate(rocrate_json)
    return (rocrate, file_content)
