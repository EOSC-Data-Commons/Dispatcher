"""Tests for the minimal VRE start endpoint and helper."""

import pytest
from pydantic import ValidationError

from app.routers.utils.minimal_vre import MinimalVRERequest, MinimalFileInput
from app.domain.rocrate.request_package import RequestPackage
from app.constants import (
    GALAXY_PROGRAMMING_LANGUAGE,
    OSCAR_PROGRAMMING_LANGUAGE,
    SCIPION_PROGRAMMING_LANGUAGE,
    BINDER_PROGRAMMING_LANGUAGE,
    JUPYTER_PROGRAMMING_LANGUAGE,
)


class TestMinimalVRERequest:
    def test_valid_galaxy_request(self):
        req = MinimalVRERequest(
            vre_type="galaxy",
            workflow_url="https://dockstore.org/api/ga4gh/trs/v2/tools/test",
        )
        assert req.vre_type == "galaxy"
        assert (
            str(req.workflow_url) == "https://dockstore.org/api/ga4gh/trs/v2/tools/test"
        )

    def test_valid_oscar_request(self):
        req = MinimalVRERequest(
            vre_type="oscar",
            workflow_url="https://raw.githubusercontent.com/example/fdl.json",
        )
        assert req.vre_type == "oscar"

    def test_valid_scipion_request_no_workflow_url(self):
        req = MinimalVRERequest(vre_type="scipion")
        assert req.vre_type == "scipion"
        assert req.workflow_url is None

    def test_valid_binder_request_no_workflow_url(self):
        req = MinimalVRERequest(vre_type="binder")
        assert req.vre_type == "binder"
        assert req.workflow_url is None

    def test_valid_jupyter_request_no_workflow_url(self):
        req = MinimalVRERequest(vre_type="jupyter")
        assert req.vre_type == "jupyter"
        assert req.workflow_url is None

    def test_galaxy_missing_workflow_url_raises(self):
        with pytest.raises(ValidationError) as exc:
            MinimalVRERequest(vre_type="galaxy")
        assert "workflow_url is required for vre_type 'galaxy'" in str(exc.value)

    def test_oscar_missing_workflow_url_raises(self):
        with pytest.raises(ValidationError) as exc:
            MinimalVRERequest(vre_type="oscar")
        assert "workflow_url is required for vre_type 'oscar'" in str(exc.value)

    def test_unknown_vre_type_raises(self):
        with pytest.raises(ValidationError):
            MinimalVRERequest(vre_type="unknown")

    def test_with_files(self):
        req = MinimalVRERequest(
            vre_type="galaxy",
            workflow_url="https://example.com/workflow.ga",
            files=[
                MinimalFileInput(
                    name="sample.fastq",
                    url="https://data.example.org/sample.fastq",
                    encoding_format="application/fastq",
                )
            ],
        )
        assert len(req.files) == 1
        assert req.files[0].name == "sample.fastq"

    def test_with_runtime_platform_override(self):
        req = MinimalVRERequest(
            vre_type="galaxy",
            workflow_url="https://example.com/workflow.ga",
            runtime_platform="https://custom-galaxy.example.org/",
        )
        assert str(req.runtime_platform) == "https://custom-galaxy.example.org/"


class TestRequestPackageFromMinimal:
    def test_galaxy_package(self):
        package = RequestPackage.from_minimal(
            vre_type="galaxy",
            programming_language=GALAXY_PROGRAMMING_LANGUAGE,
            workflow_url="https://dockstore.org/api/ga4gh/trs/v2/tools/test",
            files_data=[
                {
                    "name": "sample.fastq",
                    "url": "https://data.example.org/sample.fastq",
                    "encoding_format": "application/fastq",
                }
            ],
            file_bytes_map={},
        )

        assert package.programming_language == GALAXY_PROGRAMMING_LANGUAGE
        assert (
            package.workflow.url == "https://dockstore.org/api/ga4gh/trs/v2/tools/test"
        )
        assert len(package.files) == 1
        assert package.files[0].name == "sample.fastq"
        assert package.files[0].url == "https://data.example.org/sample.fastq"

    def test_oscar_package(self):
        package = RequestPackage.from_minimal(
            vre_type="oscar",
            programming_language=OSCAR_PROGRAMMING_LANGUAGE,
            workflow_url="https://raw.githubusercontent.com/example/fdl.json",
            files_data=[],
            file_bytes_map={},
        )

        assert package.programming_language == OSCAR_PROGRAMMING_LANGUAGE
        assert (
            package.workflow.url == "https://raw.githubusercontent.com/example/fdl.json"
        )
        assert len(package.files) == 0

    def test_scipion_package(self):
        package = RequestPackage.from_minimal(
            vre_type="scipion",
            programming_language=SCIPION_PROGRAMMING_LANGUAGE,
            workflow_url=None,
            files_data=[],
            file_bytes_map={},
        )

        assert package.programming_language == SCIPION_PROGRAMMING_LANGUAGE
        assert package.workflow.url is None

    def test_binder_package_with_uploaded_files(self):
        package = RequestPackage.from_minimal(
            vre_type="binder",
            programming_language=BINDER_PROGRAMMING_LANGUAGE,
            workflow_url=None,
            files_data=[
                {"name": "notebook.ipynb", "url": None, "encoding_format": None},
                {"name": "requirements.txt", "url": None, "encoding_format": None},
            ],
            file_bytes_map={
                "notebook.ipynb": b'{"cells": []}',
                "requirements.txt": b"numpy==1.21.0",
            },
        )

        assert package.programming_language == BINDER_PROGRAMMING_LANGUAGE
        assert len(package.files) == 2
        assert package.files[0].properties["content"] == b'{"cells": []}'
        assert package.files[1].properties["content"] == b"numpy==1.21.0"

    def test_jupyter_package_with_uploaded_notebook(self):
        package = RequestPackage.from_minimal(
            vre_type="jupyter",
            programming_language=JUPYTER_PROGRAMMING_LANGUAGE,
            workflow_url=None,
            files_data=[
                {"name": "notebook.ipynb", "url": None, "encoding_format": None},
            ],
            file_bytes_map={
                "notebook.ipynb": b'{"cells": []}',
            },
        )

        assert package.programming_language == JUPYTER_PROGRAMMING_LANGUAGE
        assert len(package.files) == 1
        assert package.files[0].properties["content"] == b'{"cells": []}'

    def test_runtime_platform_override(self):
        package = RequestPackage.from_minimal(
            vre_type="galaxy",
            programming_language=GALAXY_PROGRAMMING_LANGUAGE,
            workflow_url="https://example.com/workflow.ga",
            files_data=[],
            file_bytes_map={},
            runtime_platform="https://custom-galaxy.example.org/",
        )

        assert package.workflow.runtime_platform == "https://custom-galaxy.example.org/"

    def test_onedata_file(self):
        package = RequestPackage.from_minimal(
            vre_type="galaxy",
            programming_language=GALAXY_PROGRAMMING_LANGUAGE,
            workflow_url="https://example.com/workflow.ga",
            files_data=[
                {
                    "name": "onedata_file",
                    "url": None,
                    "encoding_format": "image/tiff",
                    "onedata_domain": "demo.onedata.org",
                    "onedata_file_id": "00000000007EADF37368",
                }
            ],
            file_bytes_map={},
        )

        assert package.files[0].onedata_domain == "demo.onedata.org"
        assert package.files[0].onedata_file_id == "00000000007EADF37368"
