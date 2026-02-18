import logging
import requests
import time
import yaml
import tarfile
from pathlib import Path
from typing import Dict, Optional
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException
from pyhelm.client import HelmClient
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KubernetesDeploymentError(Exception):
    """Exception raised for Kubernetes deployment errors."""

    pass


class KubernetesClient:
    """Client for deploying services to Kubernetes clusters using Helm."""

    def __init__(
        self, access_token: str = None, kubeconfig: str = None, context: str = None
    ):
        """Initialize the Kubernetes client.

        Args:
            access_token: Optional token for authentication with cloud providers
            kubeconfig: Path to kubeconfig file
            context: Kubernetes context to use
        """
        self.access_token = access_token
        self.kubeconfig = kubeconfig
        self.context = context
        self.namespace = "default"
        self.release_name = None
        self.helm_client = None
        self._setup_kubernetes_client()

    def _setup_kubernetes_client(self) -> None:
        """Setup Kubernetes Python client."""
        try:
            if self.kubeconfig:
                config.load_kube_config(
                    config_file=self.kubeconfig, context=self.context
                )
            else:
                config.load_incluster_config()
            logger.info("Kubernetes client configured successfully")
        except Exception as e:
            logger.warning(
                f"Failed to load kubeconfig: {e}. Will attempt in-cluster config."
            )
            try:
                config.load_incluster_config()
            except Exception as e:
                raise KubernetesDeploymentError(
                    f"Failed to initialize Kubernetes client: {e}"
                )

    def _setup_helm_client(self) -> None:
        """Setup Helm client."""
        try:
            self.helm_client = HelmClient(
                kubeconfig=self.kubeconfig, context=self.context
            )
            logger.info("Helm client configured successfully")
        except Exception as e:
            raise KubernetesDeploymentError(f"Failed to initialize Helm client: {e}")

    def validate_kubernetes_config(self, dest: dict) -> None:
        """Validate that required Kubernetes configuration is provided.

        Args:
            dest: Destination configuration dictionary

        Raises:
            KubernetesDeploymentError: If required fields are missing
        """
        required_fields = ["releaseName"]
        for field in required_fields:
            if not dest.get(field):
                raise KubernetesDeploymentError(
                    f"Missing required field in Kubernetes config: {field}"
                )

        # Either helmChartUrl or hasPart with chart info must be present
        if not dest.get("helmChartUrl") and not dest.get("hasPart"):
            raise KubernetesDeploymentError(
                "Missing Helm chart URL or hasPart configuration"
            )

        if dest.get("namespace"):
            self.namespace = dest["namespace"]

    def download_helm_chart(self, chart_url: str, dest_dir: str = "/tmp") -> str:
        """Download Helm chart from URL.

        Args:
            chart_url: URL to the Helm chart (tar.gz file)
            dest_dir: Destination directory for the chart

        Returns:
            Path to the downloaded chart

        Raises:
            KubernetesDeploymentError: If download fails
        """
        try:
            logger.info(f"Downloading Helm chart from {chart_url}")
            response = requests.get(chart_url, timeout=300)
            response.raise_for_status()

            # Extract filename from URL
            filename = chart_url.split("/")[-1]
            if not filename.endswith(".tar.gz"):
                filename = "chart.tar.gz"

            file_path = Path(dest_dir) / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, "wb") as f:
                f.write(response.content)

            logger.info(f"Helm chart downloaded to {file_path}")
            return str(file_path)

        except requests.RequestException as e:
            raise KubernetesDeploymentError(f"Failed to download Helm chart: {e}")
        except Exception as e:
            raise KubernetesDeploymentError(f"Error saving Helm chart: {e}")

    def extract_helm_chart(self, chart_archive: str, dest_dir: str = "/tmp") -> str:
        """Extract Helm chart from tar.gz archive.

        Args:
            chart_archive: Path to the tar.gz chart archive
            dest_dir: Destination directory for extraction

        Returns:
            Path to the extracted chart directory

        Raises:
            KubernetesDeploymentError: If extraction fails
        """
        try:
            logger.info(f"Extracting Helm chart from {chart_archive}")

            extract_path = Path(dest_dir) / "helm_charts"
            extract_path.mkdir(parents=True, exist_ok=True)

            with tarfile.open(chart_archive, "r:gz") as tar:
                tar.extractall(path=str(extract_path))

            logger.info(f"Helm chart extracted to {extract_path}")

            # Find the chart directory (first directory in the extracted content)
            subdirs = list(extract_path.glob("*/"))
            if subdirs:
                chart_dir = subdirs[0]
            else:
                chart_dir = extract_path

            return str(chart_dir)

        except tarfile.TarError as e:
            raise KubernetesDeploymentError(f"Failed to extract Helm chart: {e}")
        except Exception as e:
            raise KubernetesDeploymentError(f"Error extracting Helm chart: {e}")

    def build_helm_values(self, service: dict) -> Dict:
        """Build Helm values from service configuration.

        Args:
            service: Service configuration dictionary

        Returns:
            Dictionary of Helm values
        """
        values = {}

        # Add resource requirements
        if service.get("processorRequirements"):
            cpus = service["processorRequirements"]
            if isinstance(cpus, list) and cpus:
                cpus = cpus[0]
            if isinstance(cpus, str) and "vCPU" in cpus:
                values["resources"] = values.get("resources", {})
                values["resources"]["requests"] = values["resources"].get(
                    "requests", {}
                )
                cpu_value = cpus.replace("vCPU", "").strip()
                values["resources"]["requests"]["cpu"] = cpu_value
                values["resources"]["limits"] = values["resources"].get("limits", {})
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

        # Add input files if any
        if service.get("input"):
            values["inputFiles"] = service["input"]

        return values

    def add_helm_repository(self, repo_name: str, repo_url: str) -> None:
        """Add a Helm repository.

        Args:
            repo_name: Name for the repository
            repo_url: URL of the Helm repository

        Raises:
            KubernetesDeploymentError: If adding repository fails
        """
        try:
            if not self.helm_client:
                self._setup_helm_client()

            logger.info(f"Adding Helm repository {repo_name} from {repo_url}")
            self.helm_client.repo_add(repo_name, repo_url)
            self.helm_client.repo_update()
            logger.info(f"Helm repository {repo_name} added successfully")

        except Exception as e:
            raise KubernetesDeploymentError(f"Failed to add Helm repository: {e}")

    def install_helm_chart(
        self,
        chart: str,
        release_name: str,
        values: Dict = None,
        repo_name: str = None,
        repo_url: str = None,
    ) -> None:
        """Install Helm chart to Kubernetes cluster.

        Args:
            chart: Helm chart name or path
            release_name: Name for the Helm release
            values: Dictionary of Helm values
            repo_name: Optional Helm repository name
            repo_url: Optional Helm repository URL

        Raises:
            KubernetesDeploymentError: If installation fails
        """
        try:
            if not self.helm_client:
                self._setup_helm_client()

            # Add repository if provided
            if repo_url and repo_name:
                self.add_helm_repository(repo_name, repo_url)
                chart = f"{repo_name}/{chart}"

            logger.info(
                f"Installing Helm chart {chart} with release name {release_name}"
            )

            self.helm_client.install(
                chart=chart,
                release_name=release_name,
                namespace=self.namespace,
                values=values or {},
                wait=True,
                timeout=600,
            )

            logger.info(f"Helm chart installed successfully: {release_name}")
            self.release_name = release_name

        except Exception as e:
            raise KubernetesDeploymentError(f"Failed to install Helm chart: {e}")

    def wait_for_deployment(
        self,
        deployment_name: str,
        timeout: int = 600,
    ) -> None:
        """Wait for Kubernetes deployment to be ready.

        Args:
            deployment_name: Name of the deployment
            timeout: Maximum time to wait in seconds

        Raises:
            KubernetesDeploymentError: If deployment fails or times out
        """
        try:
            logger.info(f"Waiting for deployment {deployment_name} to be ready...")

            v1 = client.AppsV1Api()
            w = watch.Watch()

            start_time = time.time()
            for event in w.stream(
                v1.list_namespaced_deployment,
                self.namespace,
                field_selector=f"metadata.name={deployment_name}",
                timeout_seconds=timeout,
            ):
                deployment = event["object"]
                if deployment.status.updated_replicas == deployment.spec.replicas:
                    logger.info(f"Deployment {deployment_name} is ready")
                    return

                if time.time() - start_time > timeout:
                    raise TimeoutError(
                        f"Deployment {deployment_name} did not become ready within {timeout}s"
                    )

        except TimeoutError as e:
            raise KubernetesDeploymentError(str(e))
        except ApiException as e:
            raise KubernetesDeploymentError(f"Failed to check deployment status: {e}")
        except Exception as e:
            raise KubernetesDeploymentError(f"Error waiting for deployment: {e}")

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

            v1 = client.CoreV1Api()
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

    def run_service(self, dest: dict, service: dict = None) -> Dict:
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
            # Validate configuration
            self.validate_kubernetes_config(dest)

            release_name = dest["releaseName"]
            service_name = dest.get("serviceName", release_name)

            # Determine chart source
            chart_name = None
            repo_name = None
            repo_url = None

            if dest.get("helmChartUrl"):
                # Download and extract chart from URL
                chart_archive = self.download_helm_chart(dest["helmChartUrl"])
                chart_path = self.extract_helm_chart(chart_archive)
                chart_name = chart_path
            elif dest.get("hasPart"):
                # Extract from hasPart (ro-crate format)
                has_part = dest.get("hasPart")
                if isinstance(has_part, list) and has_part:
                    chart_info = has_part[0]
                    chart_name = chart_info.get("chartName", "hello-world")
                    repo_url = chart_info.get("url")
                    repo_name = chart_info.get("name", "default")

            if not chart_name:
                raise KubernetesDeploymentError("No valid chart source found")

            # Build Helm values
            values = {}
            if service:
                values = self.build_helm_values(service)

            # Install Helm chart
            self.install_helm_chart(
                chart=chart_name,
                release_name=release_name,
                values=values,
                repo_name=repo_name,
                repo_url=repo_url,
            )

            # Wait for deployment
            self.wait_for_deployment(release_name)

            # Get service URL
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

    def destroy_service(self, release_name: str) -> None:
        """Uninstall Helm release.

        Args:
            release_name: Name of the Helm release to uninstall

        Raises:
            KubernetesDeploymentError: If uninstall fails
        """
        try:
            if not self.helm_client:
                self._setup_helm_client()

            logger.info(f"Uninstalling Helm release {release_name}")
            self.helm_client.uninstall(release_name, namespace=self.namespace)
            logger.info(f"Helm release uninstalled successfully: {release_name}")

        except Exception as e:
            raise KubernetesDeploymentError(f"Failed to uninstall Helm release: {e}")
