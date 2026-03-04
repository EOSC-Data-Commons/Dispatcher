import logging
import subprocess
import time
from typing import Dict, Optional
from kubernetes import client as k8s_client, config
from kubernetes.client.rest import ApiException
import uuid
import json
import tempfile
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KubernetesDeploymentError(Exception):
    """Exception raised for Kubernetes deployment errors."""

    pass


class KubernetesClient:
    """Client for deploying services to Kubernetes clusters using Helm 3 via pyhelm3."""

    def __init__(self, kubeconfig: str = None, context: str = None):
        self.kubeconfig = "/usr/src/app/k8s-config.yaml"
        self.context = "kuba-cluster"
        self.namespace = "vondrak-ns"
        self.release_name = None
        self.helm_client = None
        self._setup_kubernetes_client()
        self._setup_helm_client()

    def _setup_kubernetes_client(self) -> None:
        try:
            config.load_kube_config(config_file=self.kubeconfig)
            logger.info(f"Loaded config from {self.kubeconfig}")
        except Exception as e:
            raise KubernetesDeploymentError(f"K8s init failed: {e}")

    def _setup_helm_client(self) -> None:
        """Verify that the Helm CLI is installed and can reach the cluster."""
        try:
            version_check = subprocess.run(
                ["helm", "version", "--short"],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"Helm binary found: {version_check.stdout.strip()}")
            connection_check = subprocess.run(
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
            )
            logger.info("Helm connection to Kubernetes cluster verified successfully")

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr or e.stdout
            raise KubernetesDeploymentError(
                f"Helm client setup failed. Check your kubeconfig or permissions: {error_msg}"
            )
        except FileNotFoundError:
            raise KubernetesDeploymentError(
                "Helm binary not found in the container. Is it installed in your Dockerfile?"
            )

    def validate_kubernetes_config(self, dest: dict) -> None:
        """Validate that required Kubernetes configuration is provided."""
        if not dest.get("hasPart"):
            raise KubernetesDeploymentError(
                "Missing hasPart configuration with Helm chart repository"
            )

    def build_helm_values(self, service: dict) -> Dict:
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

    def build_chart_config(self, chart_info: dict) -> tuple:
        if not chart_info.get("chartName"):
            raise KubernetesDeploymentError(
                "chartName is required in hasPart Repo configuration"
            )
        if not chart_info.get("url"):
            raise KubernetesDeploymentError(
                "url is required in hasPart Repo configuration"
            )
        return chart_info.get("url"), chart_info.get("chartName")

    def get_service_url(
        self,
        service_name: str,
        timeout: int = 300,
    ) -> str:
        """Get the service URL from Kubernetes.

        Args:
            service_name: Name of the Kubernetes service
            timeout: Maximum time to wait for service to get external IP/hostname

        Returns:
            URL of the service

        Raises:
            KubernetesDeploymentError: If service URL cannot be obtained
        """
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

    async def run_service(self, dest: dict, service: dict = None) -> Dict:
        try:
            self.validate_kubernetes_config(dest)

            has_part = dest.get("hasPart")
            chart_info = has_part[0]
            repo_url, chart_name = self.build_chart_config(chart_info)

            unique_id = str(uuid.uuid4())[:8]
            release_name = f"{chart_name}-{unique_id}"
            service_name = release_name

            values = self.build_helm_values(service) if service else {}

            logger.info(
                f"Deploying UNIQUE release {release_name} to namespace {self.namespace}"
            )

            await self.install_release(
                repo_url=repo_url,
                chart_name=chart_name,
                release_name=release_name,
                values=values,
            )

            service_url = self.get_service_url(service_name)

            return {
                "url": service_url,
                "releaseName": release_name,
                "namespace": self.namespace,
                "serviceName": service_name,
            }
        except Exception as e:
            self.cleanup_old_releases(chart_name)
            raise KubernetesDeploymentError(f"Deployment failed: {e}")

    async def install_release(
        self,
        repo_url: str,
        chart_name: str,
        release_name: str,
        values: Dict = None,
    ) -> None:
        try:
            repo_name = chart_name.replace("/", "-").lower()
            subprocess.run(
                ["helm", "repo", "add", repo_name, repo_url, "--force-update"],
                check=True,
            )
            subprocess.run(["helm", "repo", "update"], check=True)

            # Create a temporary file for the values JSON
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tf:
                json.dump(values, tf)
                values_file = tf.name

            try:
                cmd = [
                    "helm",
                    "upgrade",
                    "--install",
                    release_name,
                    f"{repo_name}/{chart_name}",
                    "--namespace",
                    self.namespace,
                    "--kubeconfig",
                    self.kubeconfig,
                    "--kube-context",
                    self.context,
                    "--values",
                    values_file,
                    "--wait",
                    "--atomic",
                    "--timeout",
                    "5m",
                ]

                logger.info(f"Executing: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                logger.info(f"Helm Success: {result.stdout}")

            finally:
                if os.path.exists(values_file):
                    os.remove(values_file)

        except subprocess.CalledProcessError as e:
            raise KubernetesDeploymentError(f"Helm failed: {e.stderr}")

    def cleanup_old_releases(self, chart_name):
        cmd = f"helm list -n {self.namespace} --filter '{chart_name}-' -q | xargs -r helm uninstall -n {self.namespace}"
        subprocess.run(cmd, shell=True)
