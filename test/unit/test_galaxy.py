# test/unit/test_galaxy.py
import pytest
from app import constants
from app.exceptions import (
    GalaxyAPIError,
    WorkflowURLError,
    WorkflowConfigurationError,
    ExternalDataSourceError,
)
from fixtures.dummy_crate import DummyEntity, DummyCrate, WORKFLOW_URL


# TODO FILE1, FILE2 move somewhere else, split to 2 tests
async def test_request_state_keys_are_workflow_input_names():
    """request_state keys must be workflow input names, never file names."""
    from vre_rocrate import (
        VREPayload,
        WorkflowDescriptor,
        FileReference,
        FormalParameter,
    )
    from app.vres.galaxy import VREGalaxy

    package = VREPayload(
        vre_type="galaxy",
        programming_language="galaxy",
        workflow=WorkflowDescriptor(
            id="https://workflow.example.org/wf.ga",
            type="Dataset",
            url="https://workflow.example.org/wf.ga",
        ),
        files=[
            FileReference(
                id="https://data.example.org/reads_1.fastq",
                name="sample_1",
                encoding_format="application/fastq",
                url="https://data.example.org/reads_1.fastq",
            ),
        ],
        workflow_inputs=[
            FormalParameter(
                id="#input-reads",
                name="reads",
                default_value={"@id": "https://data.example.org/reads_1.fastq"},
            ),
        ],
        raw_crate={},
    )
    vre = VREGalaxy(token="t", request_id=0, status_store=None, payload=package)

    request_state = (await vre._prepare_workflow_data())["request_state"]
    assert set(request_state.keys()) == {"reads"}
    assert request_state["reads"]["location"].endswith(".fastq")


async def test_prepare_workflow_data_success(galaxy_vre):
    """_prepare_workflow_data must return the exact dict that Galaxy expects."""
    payload = await galaxy_vre._prepare_workflow_data()
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


async def test_prepare_workflow_onedata_success(galaxy_vre_onedata):
    """_prepare_workflow_data must return the exact dict that Galaxy expects."""
    payload = await galaxy_vre_onedata._prepare_workflow_data()

    request_state = payload["request_state"]

    assert request_state["onedata_file"]["filetype"] == "tiff"
    assert (
        request_state["onedata_file"]["location"]
        == "https://demo.onedata.org/api/v3/onezone/shares/data/00000000007EADF3736861726547756964233964613065396530393037303130393062356433623965356632643832353138636830386464233665366232326436663332623633646233346663666163353365353265323333636864386261233437656434633633333638393264396361626239316435636430623161663436636830343438/content"
    )


async def test_post_happy_path(galaxy_vre, httpx_mock):
    data = {"uuid": "final-uuid-42"}
    httpx_mock.add_response(
        method="POST",
        url=galaxy_vre._get_api_url(),
        status_code=201,
        json=data,
    )

    final_url = await galaxy_vre.post()

    assert (
        final_url
        == f"{constants.GALAXY_DEFAULT_SERVICE}workflow_landings/final-uuid-42?public=False"
    )


async def test_missing_workflow_url_causes_exception(galaxy_vre):
    from vre_rocrate import VREPayload, WorkflowDescriptor

    galaxy_vre.payload = VREPayload(
        vre_type="galaxy",
        programming_language="galaxy",
        workflow=WorkflowDescriptor(id="#wf", type="Dataset"),
        raw_crate={},
    )

    with pytest.raises(WorkflowURLError):
        await galaxy_vre.post()


async def test_missing_uuid_in_response_causes_exception(galaxy_vre, httpx_mock):
    """When the API response does not contain a UUID, ``post`` raises GalaxyAPIError."""
    empty_response = {}

    httpx_mock.add_response(
        method="POST",
        url=galaxy_vre._get_api_url(),
        status_code=201,
        json=empty_response,
    )

    with pytest.raises(GalaxyAPIError):
        await galaxy_vre.post()


async def test_api_error_causes_custom_exception(galaxy_vre, httpx_mock):
    """When the API fails, ``post`` raises GalaxyAPIError."""
    httpx_mock.add_response(
        method="POST", url=galaxy_vre._get_api_url(), status_code=400
    )

    with pytest.raises(GalaxyAPIError):
        await galaxy_vre.post()


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
    from vre_rocrate import VREPayload, WorkflowDescriptor

    vre = VREGalaxy(
        token="test-token",
        request_id=0,
        status_store=None,
        payload=VREPayload(
            vre_type="galaxy",
            programming_language="galaxy",
            workflow=WorkflowDescriptor(
                id=url,
                type="ComputationalWorkflow",
                url=url,
                tool_version=tool_version,
            ),
            raw_crate={},
        ),
    )
    vre.svc_url = "https://usegalaxy.eu/"
    return vre


async def test_workflowhub_page_url_resolved_to_trs_version(httpx_mock):
    """A bare workflowhub page URL is resolved to a versioned TRS URL."""
    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version="1.0")
    httpx_mock.add_response(url=WORKFLOWHUB_VERSIONS_URL, json=WORKFLOWHUB_VERSIONS)

    payload = await vre._prepare_workflow_data()

    assert payload["workflow_id"] == WORKFLOWHUB_RESOLVED_URL
    assert payload["workflow_target_type"] == constants.GALAXY_WORKFLOW_TARGET_TYPE


async def test_workflowhub_resolution_end_to_end(httpx_mock):
    """post() resolves the TRS version before calling the Galaxy API."""
    import json as _json

    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version="1.0")
    httpx_mock.add_response(url=WORKFLOWHUB_VERSIONS_URL, json=WORKFLOWHUB_VERSIONS)
    httpx_mock.add_response(
        method="POST",
        url=vre._get_api_url(),
        status_code=201,
        json={"uuid": "uuid-123"},
    )

    final_url = await vre.post()

    assert final_url.endswith("workflow_landings/uuid-123?public=False")
    post_req = httpx_mock.get_requests()[-1]
    assert _json.loads(post_req.read())["workflow_id"] == WORKFLOWHUB_RESOLVED_URL


async def test_non_workflowhub_url_passes_through_untouched(httpx_mock):
    """Direct descriptor URLs are posted verbatim — no WorkflowHub call.

    (httpx_mock intercepts everything, so any unregistered GET would fail
    the test; nothing is registered here on purpose.)"""
    vre = _galaxy_vre_for_url(
        "https://workflow.example.org/myworkflow.ga", tool_version="1.0"
    )

    payload = await vre._prepare_workflow_data()

    assert payload["workflow_id"] == "https://workflow.example.org/myworkflow.ga"


async def test_workflowhub_trs_url_passes_through_untouched(httpx_mock):
    """Already-versioned TRS URLs must not trigger a second resolution."""
    trs_url = WORKFLOWHUB_VERSIONS_URL + "/9"
    vre = _galaxy_vre_for_url(trs_url, tool_version="1.0")

    payload = await vre._prepare_workflow_data()

    assert payload["workflow_id"] == trs_url


async def test_workflowhub_raw_descriptor_url_passes_through_untouched(httpx_mock):
    """Concrete workflowhub raw-descriptor URLs (…/git/{v}/raw/…) stay as-is."""
    raw_url = "https://workflowhub.eu/workflows/1747/git/1/raw/workflow_simple.json"
    vre = _galaxy_vre_for_url(raw_url, tool_version="1.0")

    payload = await vre._prepare_workflow_data()

    assert payload["workflow_id"] == raw_url


async def test_latest_version_used_when_tool_version_missing(httpx_mock):
    """Without a pinned version, the newest (max numeric id) version is used."""
    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version=None)
    httpx_mock.add_response(url=WORKFLOWHUB_VERSIONS_URL, json=WORKFLOWHUB_VERSIONS)

    payload = await vre._prepare_workflow_data()

    assert payload["workflow_id"] == WORKFLOWHUB_VERSIONS_URL + "/3"


async def test_unknown_tool_version_raises(httpx_mock):
    """A pinned version name that WorkflowHub doesn't know is a config error."""
    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version="9.9")
    httpx_mock.add_response(url=WORKFLOWHUB_VERSIONS_URL, json=WORKFLOWHUB_VERSIONS)

    with pytest.raises(WorkflowConfigurationError):
        await vre._prepare_workflow_data()


async def test_workflowhub_empty_version_list_raises(httpx_mock):
    """An empty TRS versions list leaves nothing to resolve to."""
    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version="1.0")
    httpx_mock.add_response(url=WORKFLOWHUB_VERSIONS_URL, json=[])

    with pytest.raises(WorkflowConfigurationError):
        await vre._prepare_workflow_data()


async def test_workflowhub_http_error_raises(httpx_mock):
    """A failing WorkflowHub lookup surfaces as an external-source error."""
    vre = _galaxy_vre_for_url(WORKFLOWHUB_PAGE_URL, tool_version="1.0")
    for _ in range(4):  # 5xx responses are retried per-call
        httpx_mock.add_response(url=WORKFLOWHUB_VERSIONS_URL, status_code=500)

    with pytest.raises(ExternalDataSourceError):
        await vre._prepare_workflow_data()
