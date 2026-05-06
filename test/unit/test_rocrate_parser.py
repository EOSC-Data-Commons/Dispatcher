"""Unit tests for parse_rocrate utility function."""

import copy
import pytest
from fastapi import HTTPException

from app.routers.utils.vre import parse_rocrate


def test_parse_rocrate_success():
    """parse_rocrate should return the original dict when given valid RO-Crate data."""
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
                "mainEntity": {"@id": "#workflow"},
            },
            {
                "@id": "#workflow",
                "@type": "Dataset",
                "name": "test.ga",
                "programmingLanguage": {"@id": "#galaxy-lang"},
            },
            {
                "@id": "#galaxy-lang",
                "@type": "ComputerLanguage",
                "identifier": {
                    "@id": "https://w3id.org/workflowhub/workflow-ro-crate#galaxy"
                },
            },
        ],
    }
    result = parse_rocrate(copy.deepcopy(rocrate_data))
    assert isinstance(result, dict)
    assert result == rocrate_data


def test_parse_rocrate_validation_failure():
    """parse_rocrate should raise HTTPException when given invalid RO-Crate data."""
    # Missing required @context and @graph structure
    invalid_data = {"@context": "test", "@graph": [{"@id": "./", "@type": "Dataset"}]}

    with pytest.raises(HTTPException) as exc_info:
        parse_rocrate(invalid_data)

    assert exc_info.value.status_code == 400
    assert "Invalid ROCrate data" in str(exc_info.value.detail)
