# test/unit/test_galaxy.py
import pytest
import requests_mock
from app import constants
from app.exceptions import (
    GalaxyAPIError,
    WorkflowURLError,
    WorkflowConfigurationError,
    ExternalDataSourceError,
)
from fixtures.dummy_crate import DummyEntity, DummyCrate, WORKFLOW_URL


# TODO FILE1, FILE2 move somewhere else, split to 2 tests
def test_prepare_workflow_data_success(galaxy_vre):
    """_prepare_workflow_data must return the exact dict that Galaxy expects."""
    payload = galaxy_vre._prepare_workflow_data()
    assert payload["public"] is constants.GALAXY_PUBLIC_DEFAULT
    assert payload["workflow_target_type"] == constants.GALAXY_WORKFLOW_TARGET_TYPE
    assert payload["workflow_id"] == WORKFLOW_URL

    # The request_state must contain both files, correctly transformed
    request_state = payload["request_state"]
    assert set(request_state.keys()) == {"sample1.fastq", "sample2.fastq"}
    for spec in request_state.values():
        assert spec["class"] == "File"
        assert spec["filetype"] == "fastq"
        assert spec["location"].endswith(".fastq")


def test_prepare_workflow_onedata_success(galaxy_vre_onedata):
    """_prepare_workflow_data must return the exact dict that Galaxy expects."""
    payload = galaxy_vre_onedata._prepare_workflow_data()

    request_state = payload["request_state"]

    assert request_state["onedata_file"]["filetype"] == "tiff"
    assert (
        request_state["onedata_file"]["location"]
        == "https://demo.onedata.org/api/v3/onezone/shares/data/00000000007EADF3736861726547756964233964613065396530393037303130393062356433623965356632643832353138636830386464233665366232326436663332623633646233346663666163353365353265323333636864386261233437656434633633333638393264396361626239316435636430623161663436636830343438/content"
    )


def test_post_happy_path(galaxy_vre, requests_mock):
    data = {"uuid": "final-uuid-42"}
    requests_mock.post(
        galaxy_vre._get_api_url(),
        headers=galaxy_vre._get_headers(),
        status_code=201,
        json=data,
    )

    final_url = galaxy_vre.post()

    assert (
        final_url
        == f"{constants.GALAXY_DEFAULT_SERVICE}workflow_landings/final-uuid-42?public=False"
    )


def test_missing_workflow_url_causes_exception(galaxy_vre):
    from vre_rocrate import RequestPackage, WorkflowDescriptor

    galaxy_vre.request_package = RequestPackage(
        vre_type="galaxy",
        programming_language="galaxy",
        workflow=WorkflowDescriptor(id="#wf", type="Dataset"),
        raw_crate={},
    )

    with pytest.raises(WorkflowURLError):
        galaxy_vre.post()


def test_missing_uuid_in_response_causes_exception(galaxy_vre, requests_mock):
    """When the API response does not contain a UUID, ``post`` raises GalaxyAPIError."""
    empty_response = {}

    requests_mock.post(
        galaxy_vre._get_api_url(),
        headers=galaxy_vre._get_headers(),
        status_code=201,
        json=empty_response,
    )

    with pytest.raises(GalaxyAPIError):
        galaxy_vre.post()


def test_api_error_causes_custom_exception(galaxy_vre, requests_mock):
    """When the API fails, ``post`` raises GalaxyAPIError."""
    requests_mock.post(galaxy_vre._get_api_url(), status_code=400)

    with pytest.raises(GalaxyAPIError):
        galaxy_vre.post()


# ---------------------------------------------------------------------------
# WorkflowHub TRS fallback (issue #161)
#
# The tool registry hands over a bare workflowhub.eu *page* URL
# (https://workflowhub.eu/workflows/{id}), not a versioned .ga descriptor.
# The handler must resolve it through WorkflowHub's TRS API — exactly like
# the req-packager mock did — and post the versioned TRS URL as workflow_id.
# ---------------------------------------------------------------------------

WORKFLOWHUB_PAGE_URL = "https://workflowhub.eu/workflows/1747"
WORKFLOWHUB_VERSIONS_URL = "https://workflowhub.eu/ga4gh/trs/v2/tools/1747/versions"
WORKFLOWHUB_RESOLVED_URL = WORKFLOWHUB_VERSIONS_URL + "/2"

WORKFLOWHUB_VERSIONS = [
    {"id": "1", "name": "dev"},
    {"id": "2", "name": "1.0"},
    {"id": "3", "name": "2.0-rc"},
]


def _galaxy_vre_for_url(url, tool_version=None):
    """A VREGalaxy whose workflow entity carries the given URL and tool version."""
    from app.vres.galaxy import VREGalaxy
    from vre_rocrate import RequestPackage, WorkflowDescriptor

    vre = VREGalaxy(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=RequestPackage(
            vre_type="galaxy",
            programming_language="galaxy",
            workflow=WorkflowDescriptor(
                id=url, type="ComputationalWorkflow", url=url,
                tool_version=tool_version,
            ),
            raw_crate={},
        ),
    )
    vre.svc_url = "https://usegalaxy.eu/"
    return vre


def test_workflowhub_page_url_resolved_to_trs_version(requests_mock):
    """A bare workflowhub page URL is resolved to a versioned TRS URL."""
    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version="1.0")
    requests_mock.get(WORKFLOWHUB_VERSIONS_URL, json=WORKFLOWHUB_VERSIONS)

    payload = vre._prepare_workflow_data()

    assert payload["workflow_id"] == WORKFLOWHUB_RESOLVED_URL
    assert payload["workflow_target_type"] == constants.GALAXY_WORKFLOW_TARGET_TYPE


def test_workflowhub_resolution_end_to_end(requests_mock):
    """post() resolves the TRS version before calling the Galaxy API."""
    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version="1.0")
    requests_mock.get(WORKFLOWHUB_VERSIONS_URL, json=WORKFLOWHUB_VERSIONS)
    post_mock = requests_mock.post(
        vre._get_api_url(), status_code=201, json={"uuid": "uuid-123"}
    )

    final_url = vre.post()

    assert final_url.endswith("workflow_landings/uuid-123?public=False")
    assert post_mock.last_request.json()["workflow_id"] == WORKFLOWHUB_RESOLVED_URL


def test_non_workflowhub_url_passes_through_untouched(requests_mock):
    """Direct descriptor URLs are posted verbatim — no WorkflowHub call.

    (requests_mock intercepts everything, so any unregistered GET would fail
    the test; nothing is registered here on purpose.)"""
    vre = _galaxy_vre_for_url("https://workflow.example.org/myworkflow.ga",
                              tool_version="1.0")

    payload = vre._prepare_workflow_data()

    assert payload["workflow_id"] == "https://workflow.example.org/myworkflow.ga"


def test_workflowhub_trs_url_passes_through_untouched(requests_mock):
    """Already-versioned TRS URLs must not trigger a second resolution."""
    trs_url = WORKFLOWHUB_VERSIONS_URL + "/9"
    vre = _galaxy_vre_for_url(trs_url, tool_version="1.0")

    payload = vre._prepare_workflow_data()

    assert payload["workflow_id"] == trs_url


def test_workflowhub_raw_descriptor_url_passes_through_untouched(requests_mock):
    """Concrete workflowhub raw-descriptor URLs (…/git/{v}/raw/…) stay as-is."""
    raw_url = "https://workflowhub.eu/workflows/1747/git/1/raw/workflow_simple.json"
    vre = _galaxy_vre_for_url(raw_url, tool_version="1.0")

    payload = vre._prepare_workflow_data()

    assert payload["workflow_id"] == raw_url


def test_latest_version_used_when_tool_version_missing(requests_mock):
    """Without a pinned version, the newest (max numeric id) version is used."""
    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version=None)
    requests_mock.get(WORKFLOWHUB_VERSIONS_URL, json=WORKFLOWHUB_VERSIONS)

    payload = vre._prepare_workflow_data()

    assert payload["workflow_id"] == WORKFLOWHUB_VERSIONS_URL + "/3"


def test_unknown_tool_version_raises(requests_mock):
    """A pinned version name that WorkflowHub doesn't know is a config error."""
    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version="9.9")
    requests_mock.get(WORKFLOWHUB_VERSIONS_URL, json=WORKFLOWHUB_VERSIONS)

    with pytest.raises(WorkflowConfigurationError):
        vre._prepare_workflow_data()


def test_workflowhub_empty_version_list_raises(requests_mock):
    """An empty TRS versions list leaves nothing to resolve to."""
    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version="1.0")
    requests_mock.get(WORKFLOWHUB_VERSIONS_URL, json=[])

    with pytest.raises(WorkflowConfigurationError):
        vre._prepare_workflow_data()


def test_workflowhub_http_error_raises(requests_mock):
    """A failing WorkflowHub lookup surfaces as an external-source error."""
    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version="1.0")
    requests_mock.get(WORKFLOWHUB_VERSIONS_URL, status_code=500)

    with pytest.raises(ExternalDataSourceError):
        vre._prepare_workflow_data()
