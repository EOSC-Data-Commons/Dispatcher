"""TOSCA template assembly for IM deployments (dispatcher domain, pure Python).

Extracted from the retired synchronous IM service into dispatcher ownership
per the async-execution design note: mem/gpu/disk input mapping plus
data-staging ``get_data_*`` nodes.  No I/O happens here — fetching the
template referenced by ``RuntimePlatform.install_url`` is the caller's job
(see :mod:`app.services.im_async`).
"""

import copy
import logging
from typing import Any

from vre_rocrate import RuntimePlatform

logger = logging.getLogger(__name__)

#: Data-staging node added per input file (grycap download_data artifact).
GET_DATA_NODE_TEMPLATE: dict[str, Any] = {
    "type": "tosca.nodes.SoftwareComponent",
    "interfaces": {
        "Standard": {
            "configure": {
                "implementation": (
                    "https://raw.githubusercontent.com/grycap/"
                    "tosca/main/artifacts/download_data.yml"
                ),
                "inputs": {
                    "data_url": "",
                    "local_path": "/opt",
                    "wait_to_download": True,
                    "max_download_time": 1800,
                    "unarchive_file": False,
                },
            }
        }
    },
    "requirements": [{"host": "simple_node"}],
}


def _update_input_default(inputs: dict, key: str, value: Any) -> None:
    if value:
        if inputs.get(key, {}).get("default") is not None:
            inputs[key]["default"] = value
        else:
            logger.warning("The TOSCA template does not define '%s' input.", key)


def add_inputs_to_tosca_template(tosca_template: dict, rp: RuntimePlatform) -> dict:
    """Map RuntimePlatform mem/gpu/cpu/disk onto the TOSCA template inputs."""
    inputs = tosca_template["topology_template"]["inputs"]
    _update_input_default(inputs, "mem_size", rp.memory)
    _update_input_default(inputs, "num_gpus", rp.num_gpus)
    _update_input_default(inputs, "num_cpus", rp.num_cpus)
    _update_input_default(inputs, "disk_size", rp.storage)
    return tosca_template


def _get_compute_nodes(tosca_dict: dict) -> dict:
    """Extract compute nodes from the TOSCA template."""
    compute_nodes = {}
    node_templates = tosca_dict.get("topology_template", {}).get("node_templates", {})
    for node_name, node in node_templates.items():
        if node.get("type").endswith("Compute"):
            compute_nodes[node_name] = node
    return compute_nodes


def _gen_get_data_node(file_url: str, file_dest: str | None, compute_name: str) -> dict:
    get_data = copy.deepcopy(GET_DATA_NODE_TEMPLATE)
    get_data_inputs = get_data["interfaces"]["Standard"]["configure"]["inputs"]
    if file_dest:
        get_data_inputs["local_path"] = file_dest
    get_data_inputs["data_url"] = file_url
    get_data["requirements"][0]["host"] = compute_name
    return get_data


def add_files_to_tosca_template(tosca_template: dict, rp: RuntimePlatform) -> dict:
    """Add input files to the TOSCA template for staging in."""
    if not rp.input_files:
        return tosca_template

    compute_nodes = _get_compute_nodes(tosca_template)
    node_templates = tosca_template.get("topology_template", {}).get(
        "node_templates", {}
    )

    for i, input_file in enumerate(rp.input_files):
        compute_name = input_file.compute_node
        if not compute_name and compute_nodes:
            compute_name = list(compute_nodes.keys())[0]
        if not compute_name:
            logger.error("No compute node available for input file, skipping.")
            continue
        if compute_name not in compute_nodes:
            logger.error(
                "Compute node %s not found in TOSCA template, skipping file.",
                compute_name,
            )
            continue

        node_templates[f"get_data_{i}"] = _gen_get_data_node(
            input_file.url, input_file.destination, compute_name
        )

    return tosca_template


def assemble_tosca_template(tosca_template: dict, rp: RuntimePlatform) -> dict:
    """Full dispatcher-side assembly: inputs + data-staging nodes."""
    tosca_template = add_inputs_to_tosca_template(tosca_template, rp)
    tosca_template = add_files_to_tosca_template(tosca_template, rp)
    return tosca_template
