import io
import json
import zipfile
from unittest.mock import Mock, patch
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
@patch("app.routers.utils.vre.parse_rocrate")
async def test_parse_zipfile_success(mock_parse_rocrate):
    zip_content = create_test_zip_with_rocrate()
    mock_uploadfile = create_mock_uploadfile(zip_content)
    mock_parse_rocrate.return_value = "parsed_rocrate"

    rocrate, file_content = await parse_zipfile(mock_uploadfile)

    assert rocrate == "parsed_rocrate"
    assert file_content == zip_content
    mock_parse_rocrate.assert_called_once()


@pytest.mark.asyncio
async def test_parse_zipfile_missing_metadata():
    zip_content = create_test_zip_without_metadata()
    mock_uploadfile = create_mock_uploadfile(zip_content)

    with pytest.raises(HTTPException) as exc_info:
        await parse_zipfile(mock_uploadfile)

    assert exc_info.value.status_code == 400
