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
        return crate.metadata.generate()
    except (ValueError, KeyError, VREConfigurationError) as e:
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


async def parse_zipfile(zipfile: UploadFile):
    file_content = await zipfile.read()

    metadata = None
    file_bytes_map: dict[str, bytes] = {}
    with io.BytesIO(file_content) as file_like:
        with zf.ZipFile(file_like) as zfile:
            for filename in zfile.namelist():
                if filename == "ro-crate-metadata.json":
                    with zfile.open(filename) as file:
                        metadata = file.read()
                else:
                    with zfile.open(filename) as file:
                        file_bytes_map[filename] = file.read()
        if metadata is None:
            raise HTTPException(
                status_code=400, detail="ro-crate-metadata.json not found in zip"
            )
    rocrate_json = parse_json_metadata(metadata)
    rocrate = parse_rocrate(rocrate_json)
    return (rocrate, file_bytes_map)
