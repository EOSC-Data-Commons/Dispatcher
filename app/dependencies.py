from rocrate.rocrate import ROCrate
import zipfile as zf
import json
import io
from fastapi import UploadFile
from fastapi.exceptions import HTTPException
from fastapi_oauth2.security import OAuth2AuthorizationCodeBearer
from app.internal.vre import vre_factory, ROCrateValidationError
from typing import Dict

oauth2_scheme = OAuth2AuthorizationCodeBearer(authorizationUrl="/oauth2/login", tokenUrl="/oauth2/egi-checkin/token")

def parse_rocrate(rocrate_data: Dict) -> ROCrate:
    try:
        crate = ROCrate(source=rocrate_data)
        validate_rocrate(crate)
        return crate
    except (ValueError, KeyError) as e:
        print(data)
        raise HTTPException(
            status_code=400, detail=f"Invalid ROCrate data. Reason: {e}"
        )

def validate_rocrate(crate: ROCrate):
    check_main_entity(crate)
    check_workflow_object(crate)
    check_workflow_language_object(crate)
    check_workflow_lang(crate)
    check_vre_registered(crate)

def check_main_entity(crate: ROCrate):
    if crate.mainEntity is None:
        raise HTTPException(
            status_code=400, detail=f"Missing mainEntity inside ROCrate")

def check_workflow_object(crate: ROCrate):
    if type(crate.mainEntity) is str:
        raise HTTPException(
            status_code=400, detail=f"Missing main entiy object")

def check_workflow_language_object(crate: ROCrate):
     if type(crate.mainEntity.get("programmingLanguage")) is str:
        raise HTTPException(
            status_code=400, detail=f"Missing main entiy programmingLanguage object")

def check_workflow_lang(crate: ROCrate):
    if crate.mainEntity.get("programmingLanguage", {}).get("identifier") is None:
        raise HTTPException(
            status_code=400, detail=f"Missing programmingLanguage identifier inside ROCrate's mainEntity")

def check_vre_registered(crate: ROCrate):
    lang = crate.mainEntity.get("programmingLanguage").get("identifier")
    if not vre_factory.is_registered(lang):
        raise HTTPException(
            status_code=400, detail=f"Unsupported workflow language {lang}")

def parse_json_metadata(metadata: str):
    try:
        return json.loads(metadata)
    except json.decoder.JSONDecodeError as json_exception:
        raise HTTPException(
            status_code=400,
            detail=f"Handling request failed. Invalid JSON format: \n{json_exception}",
        )


def zipfile_parser(zipfile: UploadFile):
    metadata = None
    with zf.ZipFile(zipfile.file) as zfile:
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
    validate_rocrate(rocrate)
    return (rocrate, metadata)
