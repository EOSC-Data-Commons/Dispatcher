import logging
import subprocess
import time
from typing import Dict, Optional
from pyhelm3 import Client
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
            if self.kubeconfig:
                config.load_kube_config(config_file=self.kubeconfig)
                logger.info(f"Loaded config from {self.kubeconfig}")
            else:
                try:
                    config.load_incluster_config()
                    logger.info("Loaded in-cluster config")
                except config.ConfigException:
                    config.load_kube_config()
                    logger.info("Loaded local default kubeconfig (~/.kube/config)")
        except Exception as e:
            raise KubernetesDeploymentError(f"K8s init failed: {e}")

    def _setup_helm_client(self) -> None:
        try:
            self.helm_client = Client(
                kubeconfig=self.kubeconfig, kubecontext=self.context
            )
            logger.info("Helm client (pyhelm3) configured successfully")
        except Exception as e:
            raise KubernetesDeploymentError(f"Failed to initialize Helm client: {e}")

    def validate_kubernetes_config(self, dest: dict) -> None:
        """Validate that required Kubernetes configuration is provided."""

        required_fields = ["releaseName"]
        # for field in required_fields:
        #     if not dest.get(field):
        #         raise KubernetesDeploymentError(
        #             f"Missing required field in Kubernetes config: {field}"
        #        )

        if not dest.get("hasPart"):
            raise KubernetesDeploymentError(
                "Missing hasPart configuration with Helm chart repository"
            )

        if dest.get("namespace"):
            self.namespace = dest["namespace"]

    def build_helm_values(self, service: dict) -> Dict:
        """Build Helm values from service configuration.

        Args:
            service: Service configuration dictionary

        Returns:
            Dictionary of Helm values
        """
        values = {}

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
        """Build chart repo and name from ro-crate Repo info.

        Args:
            chart_info: Chart information from ro-crate hasPart

        Returns:
            Tuple of (repo_url, chart_name)

        Raises:
            KubernetesDeploymentError: If required info is missing
        """
        if not chart_info.get("chartName"):
            raise KubernetesDeploymentError(
                "chartName is required in hasPart Repo configuration"
            )

        if not chart_info.get("url"):
            raise KubernetesDeploymentError(
                "url is required in hasPart Repo configuration"
            )

        return chart_info.get("url"), chart_info.get("chartName")

    async def install_release(
        self,
        repo_url: str,
        chart_name: str,
        release_name: str,
        values: Dict = None,
    ) -> None:
        """Install Helm chart using pyhelm3.

        Args:
            repo_url: URL of the Helm repository
            chart_name: Name of the chart
            release_name: Name for the Helm release
            values: Dictionary of Helm values

        Raises:
            KubernetesDeploymentError: If installation fails
        """
        try:
            if not self.helm_client:
                raise KubernetesDeploymentError("Helm client not initialized")

            repo_name = "dynamic-repo"
            subprocess.run(["helm", "repo", "add", repo_name, repo_url], check=True)
            subprocess.run(["helm", "repo", "update"], check=True)

            logger.info(f"Fetching chart {chart_name} from {repo_url}")
            chart = await self.helm_client.get_chart(
                chart_name,
                repo=repo_url,
            )

            logger.info(f"Installing release {release_name} with chart {chart_name}")
            revision = await self.helm_client.install_or_upgrade_release(
                release_name,
                chart,
                reset_values=values,
                atomic=True,
                wait=True,
                namespace=self.namespace,
            )

            logger.info(
                f"Helm release installed successfully: {release_name} "
                f"(revision {revision.revision}, status: {revision.status})"
            )
            self.release_name = release_name

        except Exception as e:
            raise KubernetesDeploymentError(f"Failed to install Helm release: {e}")

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
        """Deploy service to Kubernetes cluster.

        Args:
            dest: Destination configuration with Kubernetes details
            service: Service configuration (optional)

        Returns:
            Dictionary with deployment results including URL

        Raises:
            KubernetesDeploymentError: If deployment fails
        """
        try:
            self.validate_kubernetes_config(dest)

            # release_name = dest["releaseName"]
            # service_name = dest.get("serviceName", release_name)
            release_name = self.release_name
            service_name = self.release_name

            has_part = dest.get("hasPart")
            if not isinstance(has_part, list) or not has_part:
                raise KubernetesDeploymentError("hasPart must be a non-empty list")

            chart_info = has_part[0]
            repo_url, chart_name = self.build_chart_config(chart_info)

            values = {}
            if service:
                values = self.build_helm_values(service)

            logger.info(f"Deploying release {release_name} with values: {values}")

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

        except KubernetesDeploymentError:
            raise
        except Exception as e:
            raise KubernetesDeploymentError(
                f"Unexpected error deploying to Kubernetes: {e}"
            )

    async def uninstall_release(self, release_name: str) -> None:
        try:
            if not self.helm_client:
                raise KubernetesDeploymentError("Helm client not initialized")

            logger.info(f"Uninstalling Helm release {release_name}")
            await self.helm_client.uninstall_release(
                release_name, namespace=self.namespace, wait=True
            )
            logger.info(f"Helm release uninstalled successfully: {release_name}")
        except Exception as e:
            raise KubernetesDeploymentError(f"Failed to uninstall Helm release: {e}")
