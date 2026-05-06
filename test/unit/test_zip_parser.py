"""Unit tests for parse_zipfile utility function."""

import io
import json
import zipfile
from unittest.mock import Mock
import pytest
from fastapi import UploadFile, HTTPException
from app.routers.utils.vre import parse_zipfile


def create_test_zip_with_rocrate() -> bytes:
    """Create a test ZIP containing valid RO-Crate metadata."""
    rocrate_data = {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "about": {"@id": "./"},
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
            },
            {
                "@id": "./",
                "@type": "Dataset",
                "name": "Test Crate",
            },
        ],
    }

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        zip_file.writestr("ro-crate-metadata.json", json.dumps(rocrate_data))

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def create_test_zip_with_invalid_json() -> bytes:
    """Create a test ZIP with invalid JSON in the metadata file."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        zip_file.writestr("ro-crate-metadata.json", "invalid json")

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def create_test_zip_without_metadata() -> bytes:
    """Create a test ZIP without ro-crate-metadata.json."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        zip_file.writestr("other_file.txt", "content")

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def create_mock_uploadfile(content: bytes) -> Mock:
    """Create a mock UploadFile with the given content."""
    mock_uploadfile = Mock(spec=UploadFile)

    async def mock_read():
        return content

    mock_uploadfile.read = mock_read
    return mock_uploadfile


@pytest.mark.asyncio
async def test_parse_zipfile_success():
    """parse_zipfile should return the parsed JSON dict and raw bytes."""
    zip_content = create_test_zip_with_rocrate()
    mock_uploadfile = create_mock_uploadfile(zip_content)

    rocrate, file_content = await parse_zipfile(mock_uploadfile)

    assert isinstance(rocrate, dict)
    assert rocrate["@context"] == "https://w3id.org/ro/crate/1.1/context"
    assert file_content == zip_content


@pytest.mark.asyncio
async def test_parse_zipfile_missing_metadata():
    """parse_zipfile should raise HTTPException when metadata file is missing."""
    zip_content = create_test_zip_without_metadata()
    mock_uploadfile = create_mock_uploadfile(zip_content)

    with pytest.raises(HTTPException) as exc_info:
        await parse_zipfile(mock_uploadfile)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_parse_zipfile_errors_with_invalid_json():
    """parse_zipfile should raise HTTPException when JSON is invalid."""
    zip_content = create_test_zip_with_invalid_json()
    mock_uploadfile = create_mock_uploadfile(zip_content)

    with pytest.raises(HTTPException) as exc_info:
        await parse_zipfile(mock_uploadfile)

    assert exc_info.value.detail.startswith(
        "Handling request failed. Invalid JSON format"
    )
