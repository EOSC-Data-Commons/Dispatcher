import logging
import subprocess
import time
from typing import Dict
from kubernetes import client as k8s_client, config
from kubernetes.client.rest import ApiException
from vre_rocrate import RuntimePlatform
import tempfile
import os
import yaml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KubernetesDeploymentError(Exception):
    """Exception raised for Kubernetes deployment errors."""

    pass


class KubernetesClient:
    """Client for deploying services to Kubernetes clusters using Helm 3 CLI."""

    def __init__(self, kubeconfig: str = None, context: str = None):
        self.kubeconfig = "/usr/src/app/k8s-config.yaml"
        self.context = "kuba-cluster"
        self.namespace = "vondrak-ns"
        self.release_name = None
        self._setup_kubernetes_client()

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

    def build_helm_values(self, rp: RuntimePlatform) -> Dict:
        """Build Helm values from RuntimePlatform configuration.

        Args:
            rp: RuntimePlatform with resource requirements.

        Returns:
            Dictionary of Helm values.
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

        if rp.num_cpus > 1:
            cpu_value = str(rp.num_cpus)
            values.setdefault("resources", {}).setdefault("requests", {})["cpu"] = cpu_value
            values["resources"].setdefault("limits", {})["cpu"] = cpu_value

        if rp.memory:
            values.setdefault("resources", {}).setdefault("requests", {})["memory"] = rp.memory
            values["resources"].setdefault("limits", {})["memory"] = rp.memory

        if rp.storage:
            values.setdefault("persistence", {})["size"] = rp.storage

        if rp.input_files:
            values["inputFiles"] = [{"url": f.url} for f in rp.input_files]

        return values

    def install_release(
        self,
        repo_url: str,
        chart_name: str,
        release_name: str,
        values: Dict = None,
    ) -> None:
        """Install Helm chart using helm CLI via subprocess.

        Args:
            repo_url: URL of the Helm repository
            chart_name: Name of the chart
            release_name: Name for the Helm release
            values: Dictionary of Helm values

        Raises:
            KubernetesDeploymentError: If installation fails
        """
        try:
            repo_name = "dynamic-repo"
            subprocess.run(["helm", "repo", "add", repo_name, repo_url], check=True)
            subprocess.run(["helm", "repo", "update"], check=True)

            cmd = [
                "helm", "install", release_name,
                f"{repo_name}/{chart_name}",
                "--namespace", self.namespace,
                "--wait", "--atomic",
                "--kubeconfig", self.kubeconfig,
                "--kube-context", self.context,
            ]

            if values:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".yaml", delete=False
                ) as f:
                    yaml.safe_dump(values, f)
                    values_file = f.name
                cmd.extend(["--values", values_file])
                try:
                    logger.info(
                        f"Installing release {release_name} with chart {chart_name}"
                    )
                    subprocess.run(cmd, check=True)
                finally:
                    os.unlink(values_file)
            else:
                logger.info(
                    f"Installing release {release_name} with chart {chart_name}"
                )
                subprocess.run(cmd, check=True)

            logger.info(
                f"Helm release installed successfully: {release_name}"
            )
            self.release_name = release_name

        except subprocess.CalledProcessError as e:
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

    def run_service(self, rp: RuntimePlatform, chart_info: dict) -> Dict:
        """Deploy service to Kubernetes cluster.

        Args:
            rp: RuntimePlatform with resource requirements and install_url (helm repo).
            chart_info: Chart configuration dict with chartName.

        Returns:
            Dictionary with deployment results including URL.

        Raises:
            KubernetesDeploymentError: If deployment fails.
        """
        try:
            if not rp.install_url:
                raise KubernetesDeploymentError(
                    "installUrl (helm repo URL) is required for Kubernetes deployment"
                )
            if not chart_info.get("chartName"):
                raise KubernetesDeploymentError(
                    "chartName is required in chart configuration"
                )

            release_name = rp.name or f"release-{os.urandom(4).hex()}"
            service_name = release_name

            values = self.build_helm_values(rp)

            logger.info(f"Deploying release {release_name} with values: {values}")

            self.install_release(
                repo_url=rp.install_url,
                chart_name=chart_info["chartName"],
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

    def uninstall_release(self, release_name: str) -> None:
        """Uninstall Helm release using helm CLI subprocess."""
        try:
            logger.info(f"Uninstalling Helm release {release_name}")
            subprocess.run(
                [
                    "helm", "uninstall", release_name,
                    "--namespace", self.namespace,
                    "--wait",
                    "--kubeconfig", self.kubeconfig,
                    "--kube-context", self.context,
                ],
                check=True,
            )
            logger.info(f"Helm release uninstalled successfully: {release_name}")
        except subprocess.CalledProcessError as e:
            raise KubernetesDeploymentError(f"Failed to uninstall Helm release: {e}")
