"""VRE utility functions for parsing and validating ROCrates.

This module provides utility functions for parsing ZIP files containing
ROCrate metadata and validating the ROCrate structure.
"""

import io
import json
import zipfile
from typing import Any, Dict, Optional, Tuple

from fastapi import UploadFile
from fastapi.exceptions import HTTPException

from app.domain.rocrate import ROCrateFactory
from app.domain.rocrate.checkers import get_checker_by_vre_type
from app.exceptions import VREConfigurationError


def parse_rocrate(rocrate_data: Dict, vre_type: Optional[str] = None) -> Dict[str, Any]:
    """Validate ROCrate data and return the original data.

    This function validates the ROCrate structure without modifying it.
    The original data is returned to avoid unnecessary re-serialization.

    Args:
        rocrate_data: The ROCrate metadata dictionary.
        vre_type: Optional VRE type name for validation (e.g., 'galaxy').

    Returns:
        The original ROCrate metadata dictionary (unchanged).

    Raises:
        HTTPException: If ROCrate is invalid or cannot be parsed.
    """
    try:
        # Validate by creating a package - this will fail if structure is invalid
        package = ROCrateFactory.create_from_dict(rocrate_data)

        if vre_type:
            checker = get_checker_by_vre_type(vre_type)
            is_valid, errors = checker.validate(package)
            if not is_valid:
                raise VREConfigurationError(
                    f"ROCrate validation failed: {'; '.join(errors)}"
                )

        # Return original data - no need to regenerate metadata
        return rocrate_data
    except (ValueError, KeyError, VREConfigurationError) as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid ROCrate data. Reason: {e}"
        )


def parse_json_metadata(metadata: str) -> Dict[str, Any]:
    """Parse a JSON string into a dictionary.

    Args:
        metadata: JSON string to parse.

    Returns:
        Parsed dictionary.

    Raises:
        HTTPException: If JSON is invalid.
    """
    try:
        return json.loads(metadata)
    except json.decoder.JSONDecodeError as json_exception:
        raise HTTPException(
            status_code=400,
            detail=f"Handling request failed. Invalid JSON format: {json_exception}",
        )


async def parse_zipfile(zipfile: UploadFile) -> Tuple[Dict[str, Any], bytes]:
    """Parse a ZIP file containing a ROCrate.

    Extracts the ro-crate-metadata.json file from the ZIP and parses it.

    Args:
        zipfile: FastAPI UploadFile containing the ZIP archive.

    Returns:
        Tuple of (metadata_dict, zip_file_bytes).

    Raises:
        HTTPException: If ZIP doesn't contain valid ROCrate metadata.
    """
    file_content = await zipfile.read()

    metadata = None
    with io.BytesIO(file_content) as file_like:
        with zipfile.ZipFile(file_like) as zfile:
            for filename in zfile.namelist():
                if filename == "ro-crate-metadata.json":
                    with zfile.open(filename) as file:
                        metadata = file.read()
                    break

        if metadata is None:
            raise HTTPException(
                status_code=400, detail="ro-crate-metadata.json not found in zip"
            )

    rocrate_json = parse_json_metadata(metadata.decode("utf-8"))
    return (rocrate_json, file_content)
