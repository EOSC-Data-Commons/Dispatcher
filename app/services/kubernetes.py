import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Dict

import requests
import urllib3
import yaml
from kubernetes import client as k8s_client, config
from kubernetes.client.rest import ApiException
from vre_rocrate import RuntimePlatform

from app.config import settings

# Suppress warnings from the development Rancher instance's self-signed certificate.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KubernetesDeploymentError(Exception):
    """Exception raised for Kubernetes deployment errors."""

    pass


class KubernetesClient:
    """Deploy services to Kubernetes using Helm and kubectl.

    The client preserves the two modes supported by the upstream Kubernetes
    branch:

    * ``local``: use a static kubeconfig.
    * ``dev``: exchange the user's EGI token for a Rancher token and download
      a temporary kubeconfig.

    It also supports the InterLink/RO-Crate flow:

    * install an InterLink Virtual Kubelet chart;
    * wait for the virtual node to become Ready;
    * apply a manifest to that virtual node;
    * uninstall a Helm release.

    ``run_service`` accepts both the upstream ``RuntimePlatform`` call and the
    dictionary-based RO-Crate call, keeping compatibility with both flows.
    """

    EGI_CHECKIN_TOKEN_URL = (
        "https://aai-dev.egi.eu/auth/realms/egi/protocol/openid-connect/token"
    )
    INTERLINK_CHART_VERSION = "0.6.2-pre3"

    INTERLINK_TOLERATIONS = [
        {
            "key": "virtual-node.interlink/no-schedule",
            "operator": "Exists",
            "effect": "NoSchedule",
        },
        {
            "key": "node.kubernetes.io/unreachable",
            "operator": "Exists",
            "effect": "NoExecute",
        },
    ]

    def __init__(
        self,
        user_token: str | None = None,
        kubeconfig: str | None = None,
        context: str | None = None,
    ):
        self._temp_kubeconfig: str | None = None

        if getattr(settings, "rancher_mode", "local") == "dev" and user_token:
            self._temp_kubeconfig = self._generate_rancher_kubeconfig(user_token)
            self.kubeconfig = self._temp_kubeconfig
            self.context = self._read_kubeconfig_context(self.kubeconfig)
        else:
            self.kubeconfig = kubeconfig or "/usr/src/app/k8s-config.yaml"
            self.context = context or "kuba-cluster"

        self.namespace = "eosc-data-commons-ns"
        self.release_name = None
        self._setup_kubernetes_client()
        self._setup_helm_client()

    # ------------------------------------------------------------------
    # Rancher helpers retained from upstream/kubernetes
    # ------------------------------------------------------------------

    @staticmethod
    def _read_kubeconfig_context(kubeconfig_path: str) -> str:
        """Read the first context name from a kubeconfig file."""
        with open(kubeconfig_path, encoding="utf-8") as kubeconfig_file:
            kubeconfig_data = yaml.safe_load(kubeconfig_file)

        contexts = kubeconfig_data.get("contexts", [])
        if contexts:
            return contexts[0]["name"]

        raise KubernetesDeploymentError(
            "No context found in Rancher-generated kubeconfig"
        )

    def _generate_rancher_kubeconfig(self, user_token: str) -> str:
        """Exchange the EGI token and download a temporary Rancher kubeconfig."""
        logger.info("Rancher dev mode: exchanging EGI token for Rancher token")
        exchanged = self._exchange_token(user_token)
        rancher_token = exchanged["access_token"]
        logger.info("Rancher dev mode: token exchange successful")

        logger.info("Rancher dev mode: fetching kubeconfig from Rancher API")
        kubeconfig_yaml = self._fetch_rancher_kubeconfig(rancher_token)
        logger.info("Rancher dev mode: kubeconfig fetched successfully")

        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
            prefix="rancher-kubeconfig-",
            encoding="utf-8",
        )
        temp_file.write(kubeconfig_yaml)
        temp_file.close()
        logger.info("Rancher dev mode: kubeconfig written to %s", temp_file.name)
        return temp_file.name

    def _exchange_token(self, user_token: str) -> dict:
        """Perform OAuth2 token exchange at the EGI Check-in endpoint."""
        try:
            response = requests.post(
                settings.rancher_dev_token_exchange_url,
                auth=(
                    settings.rancher_dev_client_id,
                    settings.rancher_dev_client_secret,
                ),
                data={
                    "grant_type": ("urn:ietf:params:oauth:grant-type:token-exchange"),
                    "subject_token": user_token,
                    "subject_token_type": (
                        "urn:ietf:params:oauth:token-type:access_token"
                    ),
                    "audience": settings.rancher_dev_audience,
                },
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.exception("Rancher token exchange failed")
            raise KubernetesDeploymentError(
                f"Token exchange to Rancher dev failed: {exc}"
            ) from exc

    def _fetch_rancher_kubeconfig(self, rancher_token: str) -> str:
        """Select an available Rancher cluster and download its kubeconfig."""
        base_url = settings.rancher_dev_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {rancher_token}",
            "Content-Type": "application/json",
        }

        logger.info("Rancher dev mode: listing available clusters")
        try:
            list_response = requests.get(
                f"{base_url}/v3/clusters",
                headers=headers,
                verify=False,
                timeout=30,
            )
            list_response.raise_for_status()
        except requests.RequestException as exc:
            raise KubernetesDeploymentError(
                f"Failed to list Rancher clusters: {exc}"
            ) from exc

        clusters = list_response.json().get("data", [])
        if not clusters:
            raise KubernetesDeploymentError(
                "No clusters found in Rancher dev. "
                "Import or create at least one cluster in the Rancher UI."
            )

        selected_cluster = next(
            (cluster for cluster in clusters if cluster.get("state") == "active"),
            clusters[0],
        )
        cluster_id = selected_cluster["id"]
        logger.info(
            "Rancher dev mode: using cluster '%s' (%s)",
            selected_cluster.get("name", cluster_id),
            cluster_id,
        )

        kubeconfig_url = (
            f"{base_url}/v3/clusters/{cluster_id}?action=generateKubeconfig"
        )
        try:
            response = requests.post(
                kubeconfig_url,
                headers=headers,
                verify=False,
                timeout=30,
            )
            response.raise_for_status()
            response_data = response.json()
            kubeconfig = (
                response_data.get("config") or response_data.get("kubeconfig") or ""
            )

            if kubeconfig:
                if isinstance(kubeconfig, str):
                    return kubeconfig
                return yaml.safe_dump(kubeconfig)

            raw_yaml = response.text
            try:
                parsed = yaml.safe_load(raw_yaml)
                if isinstance(parsed, dict) and "apiVersion" in parsed:
                    return raw_yaml
            except yaml.YAMLError:
                pass

            raise KubernetesDeploymentError("Rancher API did not return a kubeconfig")
        except requests.RequestException as exc:
            logger.exception("Failed to fetch kubeconfig from Rancher")
            raise KubernetesDeploymentError(
                f"Failed to fetch kubeconfig from Rancher dev: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Client setup and common values
    # ------------------------------------------------------------------

    @property
    def _command_environment(self) -> dict:
        """Environment used by Helm and kubectl commands."""
        return {**os.environ, "HOME": "/tmp"}

    def _setup_kubernetes_client(self) -> None:
        try:
            config.load_kube_config(config_file=self.kubeconfig)
            logger.info("Loaded config from %s", self.kubeconfig)
        except Exception as exc:
            raise KubernetesDeploymentError(f"K8s init failed: {exc}") from exc

    def _setup_helm_client(self) -> None:
        """Verify that Helm is installed and can reach the cluster."""
        try:
            version_check = subprocess.run(
                ["helm", "version", "--short"],
                capture_output=True,
                text=True,
                check=True,
                env=self._command_environment,
            )
            logger.info("Helm binary found: %s", version_check.stdout.strip())

            subprocess.run(
                [
                    "helm",
                    "list",
                    "--namespace",
                    self.namespace,
                    "--kubeconfig",
                    self.kubeconfig,
                    "--kube-context",
                    self.context,
                ],
                capture_output=True,
                text=True,
                check=True,
                env=self._command_environment,
            )
            logger.info("Helm connection to Kubernetes cluster verified")
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr or exc.stdout or str(exc)
            raise KubernetesDeploymentError(
                "Helm client setup failed. "
                f"Check the kubeconfig or permissions: {detail}"
            ) from exc
        except FileNotFoundError as exc:
            raise KubernetesDeploymentError(
                "Helm binary not found in the container"
            ) from exc

    @staticmethod
    def _sanitize_quantity(raw: str) -> str:
        """Convert a human-readable resource quantity to Kubernetes format."""
        if not raw:
            return raw
        sanitized = raw.replace(" ", "")
        return re.sub(
            r"(\d)([KMGTPE]i)B",
            r"\1\2",
            sanitized,
            flags=re.IGNORECASE,
        )

    def build_helm_values(self, runtime_platform: RuntimePlatform) -> Dict:
        """Build values for the original RuntimePlatform-based Helm flow."""
        values: Dict = {
            "tolerations": [
                {
                    "key": "node-role.kubernetes.io/control-plane",
                    "operator": "Exists",
                    "effect": "NoSchedule",
                },
                {
                    "key": "node-role.kubernetes.io/master",
                    "operator": "Exists",
                    "effect": "NoSchedule",
                },
            ],
            "podSecurityContext": {
                "runAsNonRoot": True,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"]},
                "runAsNonRoot": True,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
        }

        if runtime_platform.num_cpus > 1:
            cpu_value = str(runtime_platform.num_cpus)
            values.setdefault("resources", {}).setdefault("requests", {})[
                "cpu"
            ] = cpu_value
            values["resources"].setdefault("limits", {})["cpu"] = cpu_value

        if runtime_platform.memory:
            memory = self._sanitize_quantity(runtime_platform.memory)
            values.setdefault("resources", {}).setdefault("requests", {})[
                "memory"
            ] = memory
            values["resources"].setdefault("limits", {})["memory"] = memory

        if runtime_platform.storage:
            values.setdefault("persistence", {})["size"] = self._sanitize_quantity(
                runtime_platform.storage
            )

        if runtime_platform.input_files:
            values["inputFiles"] = [
                {"url": input_file.url} for input_file in runtime_platform.input_files
            ]

        return values

    def validate_kubernetes_config(self, dest: dict) -> None:
        """Validate that required Kubernetes configuration is provided."""
        if not dest.get("hasPart"):
            raise KubernetesDeploymentError(
                "Missing hasPart configuration with Helm chart repository"
            )

    def validate_kubernetes_uninstall_config(self, dest: dict) -> str:
        """Validate uninstall configuration and return the Helm release name."""
        release_name = dest.get("releaseName") or dest.get("release_name")
        has_part = dest.get("hasPart", [])
        if isinstance(has_part, dict):
            has_part = [has_part]

        if not release_name:
            for chart_info in has_part:
                release_name = chart_info.get("releaseName") or chart_info.get(
                    "release_name"
                )
                if release_name:
                    break

        if not release_name:
            raise KubernetesDeploymentError(
                "releaseName is required to uninstall a Helm release"
            )

        return str(release_name)

    def build_rocrate_values(
        self,
        service: dict | RuntimePlatform,
        chart_info: dict | None = None,
    ) -> Dict:
        """Build Helm values from service and chart configuration.

        Dispatches to a chart-specific builder based on the 'chartType' field
        in chart_info. Defaults to generic behaviour if chartType is absent.

        Args:
            service:    The #destination node from the ROCrate.
            chart_info: The Repo node from hasPart (optional, for backward compat).

        Returns:
            Dictionary of Helm values to pass to `helm upgrade --install`.
        """
        chart_type = (chart_info or {}).get("chartType", "generic")

        builders = {
            "generic": self._build_generic_values,
            "interlink": self._build_interlink_values,
        }

        if chart_type == "generic" and isinstance(service, RuntimePlatform):
            return self.build_helm_values(service)

        builder = builders.get(chart_type, self._build_generic_values)
        return builder(service, chart_info or {})

    def _build_generic_values(self, service: dict, chart_info: dict) -> Dict:
        """Original build_helm_values logic — unchanged."""
        values = {}

        # security values for rancher
        values["extraPodConfig"] = {
            "securityContext": {
                "runAsNonRoot": True,
                "fsGroupChangePolicy": "OnRootMismatch",
                "seccompProfile": {"type": "RuntimeDefault"},
            }
        }
        values["containerSecurityContext"] = {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "runAsNonRoot": True,
            "runAsUser": 1000,
            "runAsGroup": 1000,
            "readOnlyRootFilesystem": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        }
        values["podSecurityContext"] = values["extraPodConfig"]["securityContext"]
        values["securityContext"] = values["containerSecurityContext"]

        # Add resource requirements
        if service.get("processorRequirements"):
            cpus = service["processorRequirements"]
            if isinstance(cpus, list) and cpus:
                cpus = cpus[0]
            if isinstance(cpus, str) and "vCPU" in cpus:
                if values.get("resources") is None:
                    values["resources"] = {}
                if values["resources"].get("requests") is None:
                    values["resources"]["requests"] = {}
                if values["resources"].get("limits") is None:
                    values["resources"]["limits"] = {}

                cpu_value = cpus.replace("vCPU", "").strip()
                values["resources"]["requests"]["cpu"] = cpu_value
                values["resources"]["limits"]["cpu"] = cpu_value

        if service.get("memoryRequirements"):
            memory = service["memoryRequirements"]
            if values.get("resources") is None:
                values["resources"] = {}
            if values["resources"].get("requests") is None:
                values["resources"]["requests"] = {}
            if values["resources"].get("limits") is None:
                values["resources"]["limits"] = {}

            values["resources"]["requests"]["memory"] = memory
            values["resources"]["limits"]["memory"] = memory

        if service.get("storageRequirements"):
            storage = service["storageRequirements"]
            if values.get("persistence") is None:
                values["persistence"] = {}
            values["persistence"]["size"] = storage

        if service.get("input"):
            values["inputFiles"] = service["input"]

        return values

    def _build_interlink_values(self, service: dict, chart_info: dict) -> Dict:
        """Build Helm values for the interLink Virtual Kubelet chart.

        Maps ROCrate Repo fields to the interLink chart values schema:
        https://github.com/interlink-hq/interlink-helm-chart

        Required ROCrate fields on the Repo node:
            nodeName         - name of the virtual node in K8s
            interlinkAddress - HTTPS endpoint of the remote interLink API server

        Optional ROCrate fields:
            interlinkPort    - defaults to 443
            oauthAudience
            virtualNodeCPUs  - advertised CPU capacity of the virtual node
            virtualNodeMemGiB
            virtualNodePods
        """
        if not chart_info.get("nodeName"):
            raise KubernetesDeploymentError(
                "nodeName is required in Repo configuration for chartType: interlink"
            )
        if not chart_info.get("interlinkAddress"):
            raise KubernetesDeploymentError(
                "interlinkAddress is required in Repo configuration for chartType: interlink"
            )

        values = {}

        # Virtual node identity
        values["nodeName"] = chart_info["nodeName"]

        # Remote interLink API server endpoint
        values["interlink"] = {
            "address": chart_info["interlinkAddress"],
            "port": chart_info.get("interlinkPort", 443),
        }

        if not settings.client_id or not settings.client_secret:
            raise KubernetesDeploymentError(
                "Dispatcher OAuth client_id and client_secret must be configured "
                "for chartType: interlink"
            )

        values["OAUTH"] = {
            "enabled": True,
            "TokenURL": self.EGI_CHECKIN_TOKEN_URL,
            "ClientID": settings.client_id,
            "ClientSecret": settings.client_secret,
            "GrantType": "client_credentials",
            "RefreshToken": "",
            "Audience": chart_info.get("oauthAudience", ""),
        }

        values["virtualNode"] = {
            "resources": {
                "CPUs": chart_info.get("virtualNodeCPUs", 8),
                "memGiB": chart_info.get("virtualNodeMemGiB", 32),
                "pods": chart_info.get("virtualNodePods", 100),
            }
        }

        return values

    def build_chart_config(self, chart_info: dict) -> tuple:
        if not chart_info.get("chartName"):
            raise KubernetesDeploymentError(
                "chartName is required in hasPart Repo configuration"
            )
        if not chart_info.get("url"):
            raise KubernetesDeploymentError(
                "url is required in hasPart Repo configuration"
            )
        return (
            chart_info.get("url"),
            chart_info.get("chartName"),
            chart_info.get("version"),
        )

    # ------------------------------------------------------------------
    # Deployment helpers retained from upstream/kubernetes
    # ------------------------------------------------------------------

    def _find_deployment_name(self, release_name: str) -> str | None:
        """Find the Deployment created by a Helm release."""
        deployments = k8s_client.AppsV1Api().list_namespaced_deployment(
            namespace=self.namespace,
            label_selector=f"app.kubernetes.io/instance={release_name}",
        )
        if not deployments.items:
            return None
        return deployments.items[0].metadata.name

    def _patch_deployment_security(self, release_name: str) -> None:
        """Patch a Helm-created Deployment for PodSecurity compliance."""
        pod_security_context = k8s_client.V1PodSecurityContext(
            run_as_non_root=True,
            seccomp_profile=k8s_client.V1SeccompProfile(type="RuntimeDefault"),
        )
        container_security_context = k8s_client.V1SecurityContext(
            allow_privilege_escalation=False,
            capabilities=k8s_client.V1Capabilities(drop=["ALL"]),
            run_as_non_root=True,
            seccomp_profile=k8s_client.V1SeccompProfile(type="RuntimeDefault"),
        )

        try:
            deployment_name = self._find_deployment_name(release_name)
            if not deployment_name:
                logger.warning(
                    "No deployment found for release %s; " "skipping security patch",
                    release_name,
                )
                return

            apps_v1 = k8s_client.AppsV1Api()
            deployment = apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace,
            )
            deployment.spec.template.spec.security_context = pod_security_context
            for container in deployment.spec.template.spec.containers:
                container.security_context = container_security_context

            apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace,
                body=deployment,
            )
            logger.info(
                "Patched deployment %s with security context",
                deployment_name,
            )
        except ApiException as exc:
            logger.warning(
                "Failed to patch deployment security context for %s: %s",
                release_name,
                exc,
            )

    @staticmethod
    def is_github_url(url: str) -> bool:
        return "github.com" in url.lower()

    def parse_github_helm_url(self, url: str) -> dict:
        """Extract repository, branch and chart path from a GitHub URL."""
        pattern = r"github\.com/([^/]+)/([^/]+)/(?:tree|blob)/([^/]+)/?(.*)?"
        match = re.search(pattern, url)
        if not match:
            raise KubernetesDeploymentError(
                f"Invalid GitHub URL format: {url}. Expected "
                "https://github.com/<owner>/<repo>/tree/<branch>/<path>"
            )

        return {
            "owner": match.group(1),
            "repo": match.group(2),
            "branch": match.group(3),
            "chart_path": self._clean_chart_path(match.group(4) or ""),
        }

    @staticmethod
    def _clean_chart_path(path: str) -> str:
        """Remove Chart.yaml from a GitHub blob path."""
        if path.endswith("/Chart.yaml"):
            return path[: -len("/Chart.yaml")]
        if path.endswith("Chart.yaml"):
            return path[: -len("Chart.yaml")]
        return path

    def extract_chart_from_github(self, url: str) -> str:
        """Clone a GitHub repository and return its local Helm chart path."""
        parsed = self.parse_github_helm_url(url)
        temp_dir = tempfile.mkdtemp(prefix="dispatcher-helm-")
        clone_dir = os.path.join(temp_dir, "clone")

        try:
            repository_url = (
                f"https://github.com/{parsed['owner']}/{parsed['repo']}.git"
            )
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--single-branch",
                    "--branch",
                    parsed["branch"],
                    repository_url,
                    clone_dir,
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            chart_path = (
                os.path.join(clone_dir, parsed["chart_path"])
                if parsed["chart_path"]
                else clone_dir
            )
            if not os.path.exists(os.path.join(chart_path, "Chart.yaml")):
                raise KubernetesDeploymentError(f"Chart.yaml not found at {chart_path}")

            return chart_path
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def install_release(
        self,
        repo_url: str,
        chart_name: str,
        release_name: str,
        values: Dict | None = None,
        version: str | None = None,
        *,
        wait: bool = False,
        atomic: bool = False,
        timeout: str | None = None,
    ) -> None:
        """Install a Helm chart from a repository or GitHub URL."""
        temp_files: list[str] = []
        cleanup_directories: list[str] = []

        try:
            github_chart = self.is_github_url(repo_url)
            if github_chart:
                local_chart_path = self.extract_chart_from_github(repo_url)
                clone_marker = f"{os.sep}clone"
                temp_root, marker, _ = local_chart_path.partition(clone_marker)
                cleanup_directories.append(
                    temp_root if marker else os.path.dirname(local_chart_path)
                )

                subprocess.run(
                    ["helm", "repo", "update"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=self._command_environment,
                )
                dependency_result = subprocess.run(
                    ["helm", "dependency", "build", local_chart_path],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    env=self._command_environment,
                )
                if dependency_result.returncode != 0:
                    logger.warning(
                        "Helm dependency build failed: %s",
                        dependency_result.stderr,
                    )

                command = [
                    "helm",
                    "upgrade",
                    "--install",
                    release_name,
                    local_chart_path,
                ]
            else:
                repo_name = chart_name.replace("/", "-").lower()
                subprocess.run(
                    [
                        "helm",
                        "repo",
                        "add",
                        repo_name,
                        repo_url,
                        "--force-update",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=self._command_environment,
                )
                subprocess.run(
                    ["helm", "repo", "update"],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=self._command_environment,
                )
                command = [
                    "helm",
                    "upgrade",
                    "--install",
                    release_name,
                    f"{repo_name}/{chart_name}",
                ]

            command.extend(
                [
                    "--namespace",
                    self.namespace,
                    "--create-namespace",
                    "--kubeconfig",
                    self.kubeconfig,
                    "--kube-context",
                    self.context,
                ]
            )

            if values:
                values_file = tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".json",
                    delete=False,
                    encoding="utf-8",
                )
                json.dump(values, values_file)
                values_file.close()
                temp_files.append(values_file.name)
                command.extend(["--values", values_file.name])

            if not github_chart and chart_name == "interlink":
                command.extend(
                    [
                        "--version",
                        version or self.INTERLINK_CHART_VERSION,
                        "--devel",
                    ]
                )
            elif not github_chart and version:
                command.extend(["--version", version])

            if wait:
                command.append("--wait")
            if atomic:
                command.append("--atomic")
            if timeout:
                command.extend(["--timeout", timeout])

            logger.info("Executing: %s", " ".join(command))
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                env=self._command_environment,
            )
            logger.info("Helm Success: %s", result.stdout)
            self.release_name = release_name
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr or exc.stdout or str(exc)
            raise KubernetesDeploymentError(f"Helm failed: {detail}") from exc
        finally:
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            for directory in cleanup_directories:
                if os.path.exists(directory):
                    shutil.rmtree(directory, ignore_errors=True)

    def get_service_url(
        self,
        service_name: str,
        timeout: int = 300,
    ) -> str:
        """Get the service URL from Kubernetes."""
        try:
            logger.info(f"Retrieving URL for service {service_name}")

            v1 = k8s_client.CoreV1Api()
            start_time = time.time()

            while time.time() - start_time < timeout:
                try:
                    service = v1.read_namespaced_service(service_name, self.namespace)

                    # Check for LoadBalancer ingress
                    if service.status.load_balancer.ingress:
                        ingress = service.status.load_balancer.ingress[0]
                        service_url = ingress.hostname or ingress.ip
                        if service_url:
                            logger.info(f"Service URL: {service_url}")
                            return service_url

                    # Check for ClusterIP
                    if service.spec.type == "ClusterIP":
                        cluster_ip = service.spec.cluster_ip
                        if cluster_ip:
                            logger.info(f"Service ClusterIP: {cluster_ip}")
                            return f"http://{cluster_ip}"

                    # Check for NodePort
                    if service.spec.type == "NodePort":
                        node_port = service.spec.ports[0].node_port
                        logger.info(f"Service NodePort: {node_port}")
                        return f"localhost:{node_port}"

                except ApiException as e:
                    if e.status != 404:
                        raise

                time.sleep(5)

            raise TimeoutError(
                f"Service {service_name} did not get an external address within {timeout}s"
            )

        except TimeoutError as e:
            raise KubernetesDeploymentError(str(e))
        except ApiException as e:
            raise KubernetesDeploymentError(f"Failed to get service: {e}")
        except Exception as e:
            raise KubernetesDeploymentError(f"Error getting service URL: {e}")

    def wait_for_virtual_node(
        self,
        node_name: str,
        timeout: int = 300,
    ) -> str:
        logger.info(f"Waiting for virtual node '{node_name}' to become Ready...")
        v1 = k8s_client.CoreV1Api()
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                node = v1.read_node(node_name)
                for condition in node.status.conditions:
                    if condition.type == "Ready" and condition.status == "True":
                        logger.info(f"Virtual node '{node_name}' is Ready")
                        return f"Virtual node '{node_name}' is Ready"
            except ApiException as e:
                if e.status != 404:
                    raise KubernetesDeploymentError(
                        f"K8s API error while waiting for node: {e}"
                    )
                # 404 means the node doesn't exist yet — keep polling
            time.sleep(10)

        raise KubernetesDeploymentError(
            f"Virtual node '{node_name}' did not become Ready within {timeout}s"
        )

    def _inject_node_selector(self, doc: dict, node_name: str) -> dict:
        """Inject a nodeSelector and interLink tolerations into a Kubernetes resource's pod spec.

        Handles Pod, Deployment, StatefulSet, DaemonSet, Job, ReplicaSet,
        and CronJob resource kinds. Tolerations are merged (no duplicates added).
        """
        node_selector = {"kubernetes.io/hostname": node_name}
        kind = doc.get("kind", "")

        if kind == "Pod":
            pod_spec = doc.setdefault("spec", {})
            pod_spec.setdefault("nodeSelector", {}).update(node_selector)
            self._merge_tolerations(pod_spec)

        elif kind in ("Deployment", "StatefulSet", "DaemonSet", "Job", "ReplicaSet"):
            pod_spec = (
                doc.setdefault("spec", {})
                .setdefault("template", {})
                .setdefault("spec", {})
            )
            pod_spec.setdefault("nodeSelector", {}).update(node_selector)
            self._merge_tolerations(pod_spec)

        elif kind == "CronJob":
            pod_spec = (
                doc.setdefault("spec", {})
                .setdefault("jobTemplate", {})
                .setdefault("spec", {})
                .setdefault("template", {})
                .setdefault("spec", {})
            )
            pod_spec.setdefault("nodeSelector", {}).update(node_selector)
            self._merge_tolerations(pod_spec)

        return doc

    def _merge_tolerations(self, pod_spec: dict) -> None:
        """Merge interLink tolerations into a pod spec, avoiding duplicates."""
        existing = pod_spec.setdefault("tolerations", [])
        existing_keys = {t.get("key") for t in existing}
        for toleration in self.INTERLINK_TOLERATIONS:
            if toleration["key"] not in existing_keys:
                existing.append(toleration)

    def apply_manifest(self, manifest_url: str, node_name: str = None) -> None:
        """Fetch a Kubernetes manifest from a URL and apply it via kubectl.

        If node_name is provided, injects a nodeSelector into every resource
        in the manifest so pods are scheduled on the specified virtual node.
        """
        try:
            response = requests.get(manifest_url, timeout=30)
            response.raise_for_status()
            manifest_content = response.text
        except requests.RequestException as e:
            raise KubernetesDeploymentError(
                f"Failed to fetch manifest from {manifest_url}: {e}"
            )

        if node_name:
            docs = [
                doc for doc in yaml.safe_load_all(manifest_content) if doc is not None
            ]
            docs = [self._inject_node_selector(doc, node_name) for doc in docs]
            manifest_content = yaml.dump_all(docs)
            logger.info(
                f"Injected nodeSelector '{node_name}' into {len(docs)} manifest resource(s)"
            )

        helm_env = {**os.environ, "HOME": "/tmp"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
            tf.write(manifest_content)
            manifest_file = tf.name

        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "apply",
                    "-f",
                    manifest_file,
                    "--namespace",
                    self.namespace,
                    "--kubeconfig",
                    self.kubeconfig,
                    "--context",
                    self.context,
                ],
                capture_output=True,
                text=True,
                check=True,
                env=helm_env,
            )
            logger.info(f"kubectl apply succeeded: {result.stdout.strip()}")
        except subprocess.CalledProcessError as e:
            raise KubernetesDeploymentError(
                f"kubectl apply failed: {e.stderr or e.stdout}"
            )
        finally:
            if os.path.exists(manifest_file):
                os.remove(manifest_file)

    def _log_pod_statuses(self, deployment_name: str) -> None:
        """Log pod statuses for a Deployment."""
        try:
            deployment = k8s_client.AppsV1Api().read_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace,
            )
            label_selector = None
            if deployment.spec.selector.match_labels:
                label_selector = ",".join(
                    f"{key}={value}"
                    for key, value in deployment.spec.selector.match_labels.items()
                )

            pods = k8s_client.CoreV1Api().list_namespaced_pod(
                namespace=self.namespace,
                label_selector=label_selector,
            )
            for pod in pods.items:
                status_parts = [f"phase={pod.status.phase}"]

                conditions = [
                    f"{condition.type}={condition.status}:{condition.reason}"
                    for condition in (pod.status.conditions or [])
                    if condition.status != "True"
                ]
                if conditions:
                    status_parts.append(f"conditions=[{', '.join(conditions)}]")

                containers = []
                for container_status in pod.status.container_statuses or []:
                    waiting = getattr(
                        container_status.state,
                        "waiting",
                        None,
                    )
                    terminated = getattr(
                        container_status.state,
                        "terminated",
                        None,
                    )
                    if waiting:
                        containers.append(
                            f"{container_status.name}:"
                            f"Waiting({waiting.reason}:{waiting.message})"
                        )
                    elif terminated:
                        containers.append(
                            f"{container_status.name}:"
                            f"Terminated({terminated.reason})"
                        )
                    elif not container_status.ready:
                        containers.append(f"{container_status.name}:NotReady")

                if containers:
                    status_parts.append(f"containers=[{', '.join(containers)}]")

                logger.info(
                    "Pod %s: %s",
                    pod.metadata.name,
                    ", ".join(status_parts),
                )
        except Exception as exc:
            logger.warning("Failed to fetch pod statuses: %s", exc)

    def _wait_for_rollout(
        self,
        release_name: str,
        timeout: int = 300,
    ) -> None:
        """Wait for the Deployment associated with a Helm release."""
        poll_interval = 10
        deadline = time.time() + timeout
        deployment_name = None

        while time.time() < deadline:
            try:
                if deployment_name is None:
                    deployment_name = self._find_deployment_name(release_name)
                    if not deployment_name:
                        raise KubernetesDeploymentError(
                            f"No deployment found for release {release_name}"
                        )

                deployment = k8s_client.AppsV1Api().read_namespaced_deployment(
                    name=deployment_name,
                    namespace=self.namespace,
                )
                conditions = deployment.status.conditions or []
                available = next(
                    (
                        condition
                        for condition in conditions
                        if condition.type == "Available"
                    ),
                    None,
                )
                ready_replicas = deployment.status.ready_replicas or 0
                replicas = deployment.status.replicas or 0

                if (
                    available
                    and available.status == "True"
                    and ready_replicas == replicas
                    and replicas > 0
                ):
                    logger.info(
                        "Deployment %s is ready (%s/%s replicas)",
                        deployment_name,
                        ready_replicas,
                        replicas,
                    )
                    return

                self._log_pod_statuses(deployment_name)
            except Exception as exc:
                logger.warning(
                    "Error checking deployment status for %s: %s",
                    release_name,
                    exc,
                )

            time.sleep(poll_interval)

        raise KubernetesDeploymentError(
            f"Deployment rollout timed out after {timeout}s " f"for {release_name}"
        )

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def run_service(
        self,
        runtime_or_destination: RuntimePlatform | dict,
        chart_info: dict | None = None,
    ) -> Dict:
        """Run either the upstream or the RO-Crate deployment flow.

        Existing upstream callers pass ``RuntimePlatform`` plus a chart
        dictionary. The InterLink flow can pass a destination dictionary plus
        an optional service dictionary.
        """
        if isinstance(runtime_or_destination, RuntimePlatform):
            return self._run_runtime_platform_service(
                runtime_or_destination,
                chart_info or {},
            )

        if isinstance(runtime_or_destination, dict):
            return self._run_rocrate_service(
                runtime_or_destination,
                chart_info,
            )

        raise KubernetesDeploymentError(
            "Unsupported Kubernetes service configuration: "
            f"{type(runtime_or_destination).__name__}"
        )

    def _run_runtime_platform_service(
        self,
        runtime_platform: RuntimePlatform,
        chart_info: dict,
    ) -> Dict:
        """Original upstream RuntimePlatform deployment path."""
        chart_name = None
        try:
            if not runtime_platform.install_url:
                raise KubernetesDeploymentError(
                    "installUrl is required for Kubernetes deployment"
                )
            if not chart_info.get("chartName"):
                raise KubernetesDeploymentError(
                    "chartName is required in chart configuration"
                )

            chart_name = chart_info["chartName"]
            release_name = f"{chart_name}-{str(uuid.uuid4())[:8]}"
            values = self.build_helm_values(runtime_platform)

            self.install_release(
                repo_url=runtime_platform.install_url,
                chart_name=chart_name,
                release_name=release_name,
                values=values,
            )

            self._patch_deployment_security(release_name)
            self._wait_for_rollout(release_name)
            service_url = self.get_service_url(release_name)

            return {
                "url": service_url,
                "releaseName": release_name,
                "namespace": self.namespace,
                "serviceName": release_name,
            }
        except Exception as exc:
            if chart_name:
                self.cleanup_old_releases(chart_name)
            raise KubernetesDeploymentError(f"Deployment failed: {exc}") from exc

    def _run_rocrate_service(self, dest: dict, service: dict = None) -> Dict:
        """Deploy or uninstall Helm releases requested by a Kubernetes service node.

        Install requests deploy all charts listed in hasPart sequentially. If
        an interlink chart is encountered, the dispatcher waits for its virtual
        node to become Ready before proceeding, and automatically injects its
        nodeName as a nodeSelector into all subsequent charts so their pods are
        scheduled on the VK-HPC node.
        """
        has_part = dest.get("hasPart", [])
        if isinstance(has_part, dict):
            has_part = [has_part]
        first_chart = has_part[0] if has_part else {}
        action = str(
            dest.get("action")
            or dest.get("operation")
            or first_chart.get("action")
            or first_chart.get("operation")
            or "install"
        ).lower()

        if action in ("uninstall", "delete", "remove"):
            release_name = self.validate_kubernetes_uninstall_config(dest)
            logger.info(
                f"Uninstalling release '{release_name}' from namespace '{self.namespace}'"
            )
            self.uninstall_release(release_name)
            return {
                "type": "helm-release",
                "action": "uninstall",
                "status": "uninstalled",
                "releaseName": release_name,
                "namespace": self.namespace,
                "url": f"helm://{self.namespace}/{release_name}",
            }

        if action != "install":
            raise KubernetesDeploymentError(
                f"Unsupported Kubernetes action: {action!r}. "
                "Expected 'install' or 'uninstall'."
            )

        self.validate_kubernetes_config(dest)

        last_result = None
        vk_node_name = None  # set after an interlink chart is deployed

        for chart_info in has_part:
            chart_name = None
            try:
                chart_type = chart_info.get("chartType", "generic")

                if chart_type == "manifest":
                    manifest_url = chart_info.get("manifestUrl")
                    if not manifest_url:
                        raise KubernetesDeploymentError(
                            "manifestUrl is required for chartType: manifest"
                        )
                    target_node = vk_node_name or chart_info.get("nodeName")
                    logger.info(
                        f"Applying manifest from '{manifest_url}'"
                        + (f" targeting node '{target_node}'" if target_node else "")
                    )
                    self.apply_manifest(manifest_url, node_name=target_node)
                    last_result = {
                        "type": "manifest",
                        "manifestUrl": manifest_url,
                        "namespace": self.namespace,
                    }
                    logger.info(f"Manifest applied successfully: {last_result}")
                    continue

                # --- Helm path ---
                repo_url, chart_name, chart_version = self.build_chart_config(
                    chart_info
                )

                unique_id = str(uuid.uuid4())[:8]
                release_name = f"{chart_name}-{unique_id}"

                values = self.build_rocrate_values(service or {}, chart_info)

                target_node = vk_node_name or (
                    chart_info.get("nodeName") if chart_type != "interlink" else None
                )
                if target_node:
                    values.setdefault("nodeSelector", {})
                    values["nodeSelector"]["kubernetes.io/hostname"] = target_node
                    logger.info(
                        f"Injecting nodeSelector '{target_node}' into release '{release_name}'"
                    )

                logger.info(
                    f"Deploying release '{release_name}' "
                    f"(chartType={chart_type}, version={chart_version or 'latest'}) "
                    f"to namespace '{self.namespace}'"
                )

                self.install_release(
                    repo_url=repo_url,
                    chart_name=chart_name,
                    release_name=release_name,
                    values=values,
                    version=chart_version,
                    wait=True,
                    atomic=True,
                    timeout="5m",
                )

                if chart_type == "interlink":
                    vk_node_name = chart_info["nodeName"]
                    status = self.wait_for_virtual_node(vk_node_name)
                    last_result = {
                        "type": "virtual-node",
                        "nodeName": vk_node_name,
                        "status": status,
                        "releaseName": release_name,
                        "namespace": self.namespace,
                    }
                else:
                    service_url = self.get_service_url(release_name)
                    last_result = {
                        "type": "service",
                        "url": service_url,
                        "releaseName": release_name,
                        "namespace": self.namespace,
                        "serviceName": release_name,
                    }

                logger.info(
                    f"Release '{release_name}' deployed successfully: {last_result}"
                )

            except Exception as e:
                if chart_name:
                    self.cleanup_old_releases(chart_name)
                raise KubernetesDeploymentError(f"Deployment failed: {e}")

        if last_result is None:
            raise KubernetesDeploymentError("No charts found in hasPart configuration")

        return last_result

    def uninstall_release(self, release_name: str) -> None:
        """Uninstall a Helm release."""
        try:
            command = [
                "helm",
                "uninstall",
                release_name,
                "--namespace",
                self.namespace,
                "--wait",
                "--kubeconfig",
                self.kubeconfig,
                "--kube-context",
                self.context,
            ]
            logger.info("Executing: %s", " ".join(command))
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                env=self._command_environment,
            )
            logger.info("Helm uninstall succeeded: %s", result.stdout)
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr or exc.stdout or str(exc)
            raise KubernetesDeploymentError(f"Helm uninstall failed: {detail}") from exc

    def cleanup_old_releases(self, chart_name: str) -> None:
        """Remove releases matching the generated chart-name prefix."""
        command = (
            f"helm list -n {self.namespace} --filter '{chart_name}-' -q "
            f"--kubeconfig {self.kubeconfig} "
            f"--kube-context {self.context} "
            "| xargs -r helm uninstall "
            f"-n {self.namespace} "
            f"--kubeconfig {self.kubeconfig} "
            f"--kube-context {self.context}"
        )
        subprocess.run(
            command,
            shell=True,
            capture_output=True,
            env=self._command_environment,
        )
