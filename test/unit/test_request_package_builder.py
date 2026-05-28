"""Tests for RequestPackageBuilder — building RequestPackage from ParsedCrate."""

import json
from pathlib import Path

import pytest

from vre_rocrate import ROCrateParser, RequestPackageBuilder, RuntimePlatform


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the directory containing ROCrate fixture files."""
    return Path(__file__).parent.parent


def _load_json(fixtures_dir: Path, file_name: str) -> dict:
    """Load a JSON fixture file from the fixtures directory."""
    with open(fixtures_dir / file_name, encoding="utf-8") as f:
        return json.load(f)


BUILDER_CASES = [
    ("galaxy/ro-crate-metadata.json", "https://galaxyproject.org/"),
    ("oscar/ro-crate-metadata.json", "https://oscar.grycap.net/"),
    ("galaxy_tosca/ro-crate-metadata.json", "https://galaxyproject.org/"),
    ("scipion_tosca/ro-crate-metadata.json", "http://scipion.i2pc.es/"),
    ("simple-binder/ro-crate-metadata.json", "https://jupyter.org/binder/"),
    ("jupyter/ro-crate-metadata.json", "https://jupyter.org"),
    ("sciencemesh/ro-crate-metadata.json", "https://qa.cernbox.cern.ch"),
]


class TestRequestPackageBuilder:
    """Unit tests for RequestPackageBuilder.build()."""

    @pytest.mark.parametrize("fixture_path,expected_vre", BUILDER_CASES)
    def test_build_package(self, fixtures_dir, fixture_path, expected_vre):
        source = _load_json(fixtures_dir, fixture_path)
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.vre_type == expected_vre

    def test_build_galaxy_package_details(self, fixtures_dir):
        source = _load_json(fixtures_dir, "galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.workflow_url is not None
        txt_files = [f for f in package.files if f.encoding_format == "text/txt"]
        assert len(txt_files) == 1
        assert txt_files[0].name == "simpletext_input"

    def test_build_oscar_package_details(self, fixtures_dir):
        source = _load_json(fixtures_dir, "oscar/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.fdl_url is not None
        assert len(package.script_files) == 1
        assert len(package.oscar_input_files) == 1

    def test_build_galaxy_tosca_package(self, fixtures_dir):
        source = _load_json(fixtures_dir, "galaxy_tosca/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        rp = package.workflow.runtime_platform
        assert rp is not None
        assert rp.install_url == (
            "https://raw.githubusercontent.com/grycap/tosca/"
            "refs/heads/eosc_dc/templates/galaxy.yaml"
        )

    def test_build_scipion_tosca_package(self, fixtures_dir):
        source = _load_json(fixtures_dir, "scipion_tosca/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        rp = package.workflow.runtime_platform
        assert rp is not None
        assert rp.install_url == (
            "https://raw.githubusercontent.com/grycap/tosca/"
            "refs/heads/eosc_beyond/templates/scipion.yaml"
        )

    def test_build_binder_package(self, fixtures_dir):
        source = _load_json(fixtures_dir, "simple-binder/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.vre_type == "https://jupyter.org/binder/"
        assert len(package.local_files) == 1
        assert len(package.remote_files) == 0

    def test_build_jupyter_package(self, fixtures_dir):
        source = _load_json(fixtures_dir, "jupyter/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.vre_type == "https://jupyter.org"
        assert len(package.files) == 1

    def test_build_sciencemesh_package(self, fixtures_dir):
        source = _load_json(fixtures_dir, "sciencemesh/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.vre_type == "https://qa.cernbox.cern.ch"
        receiver = package.get_entity("#receiver")
        assert receiver is not None
        assert "userid" in receiver

    def test_runtime_platform_plain_url(self, fixtures_dir):
        source = _load_json(fixtures_dir, "galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        rp = package.workflow.runtime_platform
        assert rp is not None
        assert isinstance(rp, str)
        assert rp == "https://usegalaxy.eu/"

    def test_runtime_platform_im_dict(self, fixtures_dir):
        source = _load_json(fixtures_dir, "galaxy_tosca/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        rp = package.workflow.runtime_platform
        assert isinstance(rp, RuntimePlatform)
        assert rp.install_url == (
            "https://raw.githubusercontent.com/grycap/tosca/"
            "refs/heads/eosc_dc/templates/galaxy.yaml"
        )
