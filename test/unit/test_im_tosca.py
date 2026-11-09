"""Unit tests for app.services.im_tosca — pure TOSCA assembly."""

import yaml

from app.services.im_tosca import (
    add_files_to_tosca_template,
    add_inputs_to_tosca_template,
    assemble_tosca_template,
)
from vre_rocrate import IMInputFile, RuntimePlatform


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
    rp = RuntimePlatform(
        name="Test",
        install_url="http://test.url",
        memory="2GB",
        num_cpus=2,
        num_gpus=1,
        storage="20GB",
    )

    result = add_inputs_to_tosca_template(yaml.safe_load(test_tosca), rp)

    assert result["topology_template"]["inputs"]["mem_size"]["default"] == "2GB"
    assert result["topology_template"]["inputs"]["num_cpus"]["default"] == 2
    assert result["topology_template"]["inputs"]["num_gpus"]["default"] == 1
    assert result["topology_template"]["inputs"]["disk_size"]["default"] == "20GB"


def test_add_inputs_skips_missing_inputs():
    rp = RuntimePlatform(
        name="Test",
        install_url="http://test.url",
        memory="2GB",
    )
    tosca = {"topology_template": {"inputs": {}}}

    result = add_inputs_to_tosca_template(tosca, rp)

    assert result["topology_template"]["inputs"] == {}


def test_add_input_files_to_tosca_template():
    test_tosca = {
        "topology_template": {
            "inputs": {},
            "node_templates": {"compute1": {"type": "tosca.nodes.Compute"}},
        }
    }

    rp = RuntimePlatform(
        name="Test",
        install_url="http://test.url",
        input_files=[
            IMInputFile(
                url="http://example.com/data1.txt",
                destination="/data",
                compute_node="compute1",
            ),
            IMInputFile(
                url="http://example.com/data2.txt",
                destination="/data",
                compute_node=None,
            ),
        ],
    )

    updated_tosca = add_files_to_tosca_template(test_tosca, rp)
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
    # No compute_node given: defaults to the first compute node in the template.
    assert get_data_1["requirements"][0]["host"] == "compute1"


def test_add_input_files_skips_unknown_compute_node():
    test_tosca = {
        "topology_template": {
            "inputs": {},
            "node_templates": {"compute1": {"type": "tosca.nodes.Compute"}},
        }
    }
    rp = RuntimePlatform(
        name="Test",
        install_url="http://test.url",
        input_files=[
            IMInputFile(
                url="http://example.com/data.txt",
                destination="/data",
                compute_node="no-such-node",
            ),
        ],
    )

    updated = add_files_to_tosca_template(test_tosca, rp)

    assert "get_data_0" not in updated["topology_template"]["node_templates"]


def test_no_input_files_is_noop():
    test_tosca = {
        "topology_template": {
            "inputs": {},
            "node_templates": {"compute1": {"type": "tosca.nodes.Compute"}},
        }
    }
    rp = RuntimePlatform(name="Test", install_url="http://test.url")

    assert add_files_to_tosca_template(test_tosca, rp) is test_tosca


def test_assemble_tosca_template_combines_inputs_and_files():
    test_tosca = {
        "topology_template": {
            "inputs": {"mem_size": {"default": 1}},
            "node_templates": {"compute1": {"type": "tosca.nodes.Compute"}},
        }
    }
    rp = RuntimePlatform(
        name="Test",
        install_url="http://test.url",
        memory="4GB",
        input_files=[
            IMInputFile(
                url="http://example.com/data.txt",
                destination="/data",
                compute_node="compute1",
            ),
        ],
    )

    result = assemble_tosca_template(test_tosca, rp)

    assert result["topology_template"]["inputs"]["mem_size"]["default"] == "4GB"
    assert "get_data_0" in result["topology_template"]["node_templates"]
