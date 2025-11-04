import pytest
from app.exceptions import VREConfigurationError
from rocrate.rocrate import ROCrate

from app.routers.utils.vre import (
    validate_rocrate,
    check_main_entity,
    check_workflow_object,
    check_workflow_language_object,
    check_workflow_lang,
)


def create_valid_rocrate_json():
    return {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": [
            {
                "@id": "./",
                "@type": "Dataset",
                "datePublished": "2025-09-26T14:09:25+00:00",
                "mainEntity": {"@id": "#workflow"},
                "hasPart": [
                    {"@id": "#workflow"},
                ],
            },
            {
                "@id": "#workflow",
                "@type": "File",
                "programmingLanguage": {"@id": "cwl"},
            },
            {
                "@id": "cwl",
                "@type": "ComputerLanguage",
                "name": "Common Workflow Language",
                "identifier": "https://w3id.org/cwl/v1.0/",
            },
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "about": {"@id": "./"},
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
            },
        ],
    }


def create_rocrate_json_without_main_entity():
    return {
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


def create_rocrate_json_with_main_entity_string():
    data = create_valid_rocrate_json()
    # Add mainEntity as string reference
    for item in data["@graph"]:
        if item["@id"] == "./":
            item["mainEntity"] = "workflow.cwl"
            break
    return data


def create_rocrate_json_with_invalid_programming_language():
    data = create_valid_rocrate_json()
    # Modify programmingLanguage to be string instead of object reference
    for item in data["@graph"]:
        if item["@id"] == "#workflow":
            item["programmingLanguage"] = "cwl"
            break
    return data


def create_rocrate_json_without_language_identifier():
    data = create_valid_rocrate_json()
    # Remove identifier from ComputerLanguage
    for item in data["@graph"]:
        if item.get("@id") == "cwl":
            item.pop("identifier", None)
            break
    return data


def test_validate_rocrate_success():
    json_data = create_valid_rocrate_json()
    crate = ROCrate(source=json_data)

    try:
        validate_rocrate(crate)
    except VREConfigurationError:
        pytest.fail("validate_rocrate raised VREConfigurationError unexpectedly")


def test_check_main_entity_missing():
    json_data = create_rocrate_json_without_main_entity()
    crate = ROCrate(source=json_data)

    with pytest.raises(VREConfigurationError) as exc_info:
        check_main_entity(crate)

    assert "Missing mainEntity" in str(exc_info)


def test_check_workflow_object_missing():
    json_data = create_rocrate_json_with_main_entity_string()
    crate = ROCrate(source=json_data)

    with pytest.raises(VREConfigurationError) as exc_info:
        check_workflow_object(crate)

    assert "Missing main entiy object" in str(exc_info)


def test_check_workflow_language_object_missing():
    json_data = create_rocrate_json_with_invalid_programming_language()
    crate = ROCrate(source=json_data)

    with pytest.raises(VREConfigurationError) as exc_info:
        check_workflow_language_object(crate)

    assert "Missing main entiy programmingLanguage object" in str(exc_info)


def test_check_workflow_lang_missing():
    json_data = create_rocrate_json_without_language_identifier()
    crate = ROCrate(source=json_data)

    with pytest.raises(VREConfigurationError) as exc_info:
        check_workflow_lang(crate)

    assert "Missing programmingLanguage identifier" in str(exc_info)
