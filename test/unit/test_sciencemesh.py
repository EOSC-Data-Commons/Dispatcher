import pytest
import requests_mock
from rocrate import rocrate
from app.exceptions import MissingOCMParameters


def test_missing_uuid_in_response_causes_exception(sciencemesh_vre, requests_mock):
    """"""
    sciencemesh_vre.crate = rocrate.ROCrate()

    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=201,
    )
    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


# return requests_mock.mock().call_count
