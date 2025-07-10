from rocrate.rocrate import ROCrate
import zipfile as zf
import json
import io
from fastapi import UploadFile
from fastapi.exceptions import HTTPException


def parse_rocrate(data: dict):
    try:
        return ROCrate(source=data)
    except (ValueError, KeyError) as e:
        print(data)
        raise HTTPException(
            status_code=400, detail=f"Invalid ROCrate data. Reason: {e}"
        )


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
    return (parse_rocrate(rocrate_json), response)
