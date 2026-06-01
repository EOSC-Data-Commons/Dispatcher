import io
import json
import zipfile
from unittest.mock import Mock
import pytest
from fastapi import UploadFile, HTTPException
from app.routers.utils.vre import parse_zipfile


def create_test_zip_with_rocrate() -> bytes:
    rocrate_data = {"test": "data"}

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        zip_file.writestr("ro-crate-metadata.json", json.dumps(rocrate_data))

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def create_test_zip_with_files() -> bytes:
    rocrate_data = {"test": "data"}

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        zip_file.writestr("ro-crate-metadata.json", json.dumps(rocrate_data))
        zip_file.writestr("notebook.ipynb", '{"cells": []}')
        zip_file.writestr("data.csv", "col1,col2\n1,2")

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def create_test_zip_with_invalid_json() -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        zip_file.writestr("ro-crate-metadata.json", "invalid json")

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def create_test_zip_without_metadata() -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        zip_file.writestr("other_file.txt", "content")

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def create_mock_uploadfile(content: bytes) -> Mock:
    mock_uploadfile = Mock(spec=UploadFile)

    async def mock_read():
        return content

    mock_uploadfile.read = mock_read
    return mock_uploadfile


@pytest.mark.asyncio
async def test_parse_zipfile_success():
    zip_content = create_test_zip_with_rocrate()
    mock_uploadfile = create_mock_uploadfile(zip_content)

    rocrate, file_bytes_map = await parse_zipfile(mock_uploadfile)

    assert rocrate == {"test": "data"}
    assert file_bytes_map == {}


@pytest.mark.asyncio
async def test_parse_zipfile_extracts_file_bytes():
    zip_content = create_test_zip_with_files()
    mock_uploadfile = create_mock_uploadfile(zip_content)

    rocrate, file_bytes_map = await parse_zipfile(mock_uploadfile)

    assert rocrate == {"test": "data"}
    assert "notebook.ipynb" in file_bytes_map
    assert file_bytes_map["notebook.ipynb"] == b'{"cells": []}'
    assert "data.csv" in file_bytes_map
    assert file_bytes_map["data.csv"] == b"col1,col2\n1,2"
    assert "ro-crate-metadata.json" not in file_bytes_map


@pytest.mark.asyncio
async def test_parse_zipfile_missing_metadata():
    zip_content = create_test_zip_without_metadata()
    mock_uploadfile = create_mock_uploadfile(zip_content)

    with pytest.raises(HTTPException) as exc_info:
        await parse_zipfile(mock_uploadfile)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_parse_zipfile_errors_with_invalid_json():
    zip_content = create_test_zip_with_invalid_json()
    mock_uploadfile = create_mock_uploadfile(zip_content)

    with pytest.raises(HTTPException) as exc_info:
        await parse_zipfile(mock_uploadfile)

    assert exc_info.value.detail.startswith(
        "Handling request failed. Invalid JSON format"
    )
