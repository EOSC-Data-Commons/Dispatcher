import json
import os
import pytest
from app.domain.rocrate.parser import ROCrateParser
from app.domain.rocrate.builder import RequestPackageBuilder
from app.domain.rocrate.request_package import RequestPackage
from app.domain.rocrate.validator import ValidationPipeline
from app.exceptions import VREConfigurationError


def load_json(file_name):
    abs_file_path = os.path.join(os.path.dirname(__file__), file_name)
    with open(abs_file_path, encoding="utf-8") as f:
        return json.load(f)


class TestROCrateParser:
    def test_parse_galaxy_crate(self):
        source = load_json("../galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        assert parsed.root_id == "./"
        assert parsed.main_entity is not None
        assert parsed.main_entity.id == "#workflow"
        lang_ref = parsed.main_entity.get("programmingLanguage")
        assert isinstance(lang_ref, dict)
        assert lang_ref.get("@id") == "#galaxy-lang"
        lang = parsed.get("#galaxy-lang")
        assert lang is not None
        assert lang.get("identifier") == "https://galaxyproject.org/"

    def test_parse_oscar_crate(self):
        source = load_json("../oscar/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        assert parsed.main_entity is not None
        assert parsed.main_entity.get("url") is not None

    def test_parse_resolves_references(self):
        source = load_json("../galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        lang_ref = parsed.main_entity.get("programmingLanguage")
        assert isinstance(lang_ref, dict)
        assert lang_ref.get("@id") == "#galaxy-lang"
        lang = parsed.get("#galaxy-lang")
        assert lang.get("identifier") == "https://galaxyproject.org/"


class TestValidationPipeline:
    def test_valid_crate_passes(self):
        source = load_json("../galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        ValidationPipeline.validate_basic(parsed)

    def test_missing_main_entity_raises(self):
        source = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": [
                {"@id": "./", "@type": "Dataset"},
                {
                    "@id": "ro-crate-metadata.json",
                    "@type": "CreativeWork",
                    "about": {"@id": "./"},
                    "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                },
            ],
        }
        parsed = ROCrateParser.parse(source)
        with pytest.raises(VREConfigurationError, match="Missing mainEntity"):
            ValidationPipeline.validate_basic(parsed)

    def test_missing_programming_language_raises(self):
        source = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": [
                {"@id": "./", "@type": "Dataset", "mainEntity": {"@id": "#wf"}},
                {"@id": "#wf", "@type": "File"},
                {
                    "@id": "ro-crate-metadata.json",
                    "@type": "CreativeWork",
                    "about": {"@id": "./"},
                    "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                },
            ],
        }
        parsed = ROCrateParser.parse(source)
        with pytest.raises(VREConfigurationError, match="programmingLanguage"):
            ValidationPipeline.validate_basic(parsed)

    def test_missing_language_identifier_raises(self):
        source = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": [
                {"@id": "./", "@type": "Dataset", "mainEntity": {"@id": "#wf"}},
                {
                    "@id": "#wf",
                    "@type": "File",
                    "programmingLanguage": {"@id": "#lang"},
                },
                {"@id": "#lang", "@type": "ComputerLanguage", "name": "Test"},
                {
                    "@id": "ro-crate-metadata.json",
                    "@type": "CreativeWork",
                    "about": {"@id": "./"},
                    "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                },
            ],
        }
        parsed = ROCrateParser.parse(source)
        with pytest.raises(VREConfigurationError, match="identifier"):
            ValidationPipeline.validate_basic(parsed)


class TestRequestPackageBuilder:
    def test_build_galaxy_package(self):
        source = load_json("../galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.vre_type == "https://galaxyproject.org/"
        assert package.workflow_url is not None
        assert len(package.files) == 1
        assert package.files[0].encoding_format == "text/txt"

    def test_build_oscar_package(self):
        source = load_json("../oscar/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.vre_type == "https://oscar.grycap.net/"
        assert package.fdl_url is not None
        assert len(package.script_files) == 1
        assert len(package.oscar_input_files) == 2

    def test_build_galaxy_tosca_package(self):
        source = load_json("../galaxy_tosca/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.tosca_file is not None
        assert package.tosca_file.encoding_format == "text/yaml"

    def test_build_scipion_tosca_package(self):
        source = load_json("../scipion_tosca/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.tosca_file is not None
        assert package.tosca_file.encoding_format == "text/yaml"

    def test_build_binder_package(self):
        source = load_json("../simple-binder/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.vre_type == "https://jupyter.org/binder/"
        assert len(package.local_files) == 0
        assert len(package.remote_files) == 0

    def test_build_jupyter_package(self):
        source = load_json("../jupyter/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.vre_type == "https://jupyter.org"
        assert len(package.files) == 0

    def test_build_sciencemesh_package(self):
        source = load_json("../sciencemesh/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert package.vre_type == "https://qa.cernbox.cern.ch"
        receiver = package.get_entity("#receiver")
        assert receiver is not None
        assert "userid" in receiver


class TestRequestPackageSerialization:
    def test_to_dict_and_from_dict_roundtrip(self):
        source = load_json("../galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        d = package.to_dict()
        restored = RequestPackage.from_dict(d)
        assert restored.vre_type == package.vre_type
        assert restored.workflow_url == package.workflow_url
        assert len(restored.files) == len(package.files)
        assert restored.files[0].name == package.files[0].name


class TestRequestPackageHelpers:
    def test_local_vs_remote_files(self):
        source = load_json("../galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert len(package.local_files) == 0
        assert len(package.remote_files) == 1

    def test_files_by_encoding(self):
        source = load_json("../oscar/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        scripts = package.files_by_encoding("text/x-shellscript")
        assert len(scripts) == 1
        assert scripts[0].name == "script.sh"

    def test_file_by_id(self):
        source = load_json("../galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        f = package.file_by_id(
            "https://example-files.online-convert.com/document/txt/example.txt"
        )
        assert f is not None
        assert f.name == "simpletext_input"

    def test_workflow_inputs_outputs(self):
        source = load_json("../galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert len(package.workflow_inputs) == 1
        assert package.workflow_inputs[0].name == "simpletext_input"
        assert len(package.workflow_outputs) == 1
        assert package.workflow_outputs[0].name == "reversed_text"

    def test_runtime_platform_plain_url(self):
        source = load_json("../galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        rp = package.workflow.runtime_platform
        assert rp is not None
        assert isinstance(rp, str)
        assert rp == "https://usegalaxy.eu/"

    def test_runtime_platform_im_dict(self):
        source = load_json("../galaxy_tosca/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        rp = package.workflow.runtime_platform
        assert rp is not None
        assert rp.get("installUrl") == (
            "https://raw.githubusercontent.com/grycap/tosca/"
            "refs/heads/eosc_dc/templates/galaxy.yaml"
        )
