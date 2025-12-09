import pytest
from unittest.mock import Mock, patch
import yaml
from app.services.im import IM


@pytest.fixture
def mock_settings():
    with patch("app.services.im.settings") as mock_settings:
        mock_settings.im_endpoint = "http://test.endpoint"
        mock_settings.im_cloud_provider = {
            "type": "openstack",
            "host": "test.host",
            "username": "test_user",
            "auth_version": "3.x_oidc_access_token",
            "tenant": "test_tenant",
        }
        mock_settings.im_max_time = 600
        mock_settings.im_max_retries = 5
        mock_settings.im_sleep = 1
        yield mock_settings


def test_build_auth_config_openstack(mock_settings):
    im = IM("test_token")
    auth = im._build_auth_config("test_token")
    assert len(auth) == 2
    assert auth[0]["type"] == "InfrastructureManager"
    assert auth[1]["type"] == "OpenStack"
    assert auth[1]["host"] == "test.host"


def test_build_auth_config_egi(mock_settings):
    mock_settings.im_cloud_provider = {
        "type": "egi",
        "VO": "test_vo",
        "site": "test_site",
    }
    im = IM("test_token")
    auth = im._build_auth_config("test_token")
    assert len(auth) == 2
    assert auth[1]["type"] == "EGI"
    assert auth[1]["vo"] == "test_vo"


def test_add_inputs_to_tosca_template():
    test_tosca = """
topology_template:
  inputs:
    mem_size:
      default: 1
    num_cpus:
      default: 1
    num_gpus:
      default: 0
    disk_size:
      default: 10
"""
    service = {
        "memoryRequirements": "2GB",
        "processorRequirements": ["2vCPU", "1GPU"],
        "storageRequirements": "20GB",
    }

    result = IM._add_inputs_to_tosca_template(test_tosca, service)
    result_dict = yaml.safe_load(result)

    assert result_dict["topology_template"]["inputs"]["mem_size"]["default"] == "2GB"
    assert result_dict["topology_template"]["inputs"]["num_cpus"]["default"] == 2
    assert result_dict["topology_template"]["inputs"]["num_gpus"]["default"] == 1
    assert result_dict["topology_template"]["inputs"]["disk_size"]["default"] == "20GB"


@patch("app.services.im.IM._get_tosca_template", return_value="test_template")
@patch(
    "app.services.im.IM._add_inputs_to_tosca_template", return_value="modified_template"
)
def test_deploy_service(mock_get_tosca, mock_add_inputs, mock_settings):
    mock_im_client = Mock()
    mock_im_client.create.return_value = (True, "test_inf_id")
    im = IM("test_token")
    im.client = mock_im_client

    service = {"hasPart": [{"encodingFormat": "text/yaml", "url": "http://test.url"}]}

    inf_id = im.deploy_service(service)

    assert inf_id == "test_inf_id"
    mock_im_client.create.assert_called_once_with("modified_template", desc_type="yaml")


def test_wait_for_service_success(mock_settings):
    mock_client = Mock()
    mock_client.get_infra_property.return_value = (True, {"state": "configured"})
    im = IM("test_token")
    im.client = mock_client

    im.inf_id = "test_inf_id"
    im.wait_for_service()

    mock_client.get_infra_property.assert_called_with("test_inf_id", "state")


def test_destroy_service(mock_settings):
    mock_client = Mock()
    mock_client.destroy.return_value = (True, "Success")
    im = IM("test_token")
    im.client = mock_client

    im.inf_id = "test_inf_id"
    im.destroy_service()

    assert im.inf_id is None
    mock_client.destroy.assert_called_once_with("test_inf_id")


@patch("requests.get")
def test_get_tosca_template(mock_get, mock_settings):
    im = IM("test_token")
    test_url = "http://test.url"

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "tosca_content"
    mock_get.return_value = mock_response

    result = im._get_tosca_template(test_url)

    assert result == "tosca_content"
    mock_get.assert_called_once_with(test_url, timeout=10)


@patch("app.services.im.IM._get_tosca_template", return_value="test_template")
@patch(
    "app.services.im.IM._add_inputs_to_tosca_template", return_value="modified_template"
)
def test_run_service(mock_add_inputs, mock_get_tosca, mock_settings):
    im = IM("test_token")
    service = {"hasPart": [{"encodingFormat": "text/yaml", "url": "http://test.url"}]}

    mock_im_client = Mock()
    mock_im_client.create.return_value = (True, "test_inf_id")
    mock_im_client.get_infra_property.side_effect = [
        (True, {"state": "configured"}),
        (True, {"outputs": {"url": "http://some.url"}}),
    ]
    im.client = mock_im_client
    log = im.run_service(service)
    assert log == {"outputs": {"url": "http://some.url"}}
    mock_im_client.create.assert_called_once_with("modified_template", desc_type="yaml")


def test_add_input_files_to_tosca_template(mock_settings):
    test_tosca = {
        "topology_template": {
            "inputs": {},
            "node_templates": {"compute1": {"type": "tosca.nodes.Compute"}},
        }
    }

    service = {
        "input": [
            {
                "@type": "File",
                "url": "http://example.com/data1.txt",
                "contentLocation": "compute1:/data",
            },
            {
                "@type": "File",
                "url": "http://example.com/data2.txt",
                "contentLocation": "/data",
            },
        ]
    }

    im = IM("test_token")
    updated_tosca_str = im._add_files_to_tosca_template(
        yaml.safe_dump(test_tosca), service
    )
    updated_tosca = yaml.safe_load(updated_tosca_str)
    node_templates = updated_tosca["topology_template"]["node_templates"]
    assert len(node_templates) == 3
    assert "get_data_0" in node_templates
    assert "get_data_1" in node_templates

    get_data_0 = node_templates["get_data_0"]
    assert get_data_0["type"] == "tosca.nodes.SoftwareComponent"
    assert (
        get_data_0["interfaces"]["Standard"]["configure"]["inputs"]["data_url"]
        == "http://example.com/data1.txt"
    )
    assert (
        get_data_0["interfaces"]["Standard"]["configure"]["inputs"]["local_path"]
        == "/data"
    )
    assert get_data_0["requirements"][0]["host"] == "compute1"

    get_data_1 = node_templates["get_data_1"]
    assert get_data_1["type"] == "tosca.nodes.SoftwareComponent"
    assert (
        get_data_1["interfaces"]["Standard"]["configure"]["inputs"]["data_url"]
        == "http://example.com/data2.txt"
    )
    assert (
        get_data_1["interfaces"]["Standard"]["configure"]["inputs"]["local_path"]
        == "/data"
    )
    assert get_data_1["requirements"][0]["host"] == "compute1"
