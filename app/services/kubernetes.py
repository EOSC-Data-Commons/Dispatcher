import logging
import subprocess
import time
from typing import Dict
from kubernetes import client as k8s_client, config
from kubernetes.client.rest import ApiException
from vre_rocrate import RuntimePlatform
import uuid
import json
import tempfile
import os
import re
import shutil

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
        self.namespace = "eosc-data-commons-ns"
        self.release_name = None
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

    def build_helm_values(self, rp: RuntimePlatform) -> Dict:
        """Build Helm values from RuntimePlatform configuration.

        Args:
            rp: RuntimePlatform with resource requirements.

        Returns:
            Dictionary of Helm values.
        """
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

    def is_github_url(self, url: str) -> bool:
        return "github.com" in url.lower()

    def parse_github_helm_url(self, url: str) -> dict:
        """Parse GitHub URL to extract repo, branch, and chart path.

        Supports URL formats like:
        - https://github.com/user/repo/tree/branch/path/to/chart
        - https://github.com/user/repo/blob/branch/path/to/Chart.yaml

        Args:
            url: GitHub URL to parse

        Returns:
            Dictionary with owner, repo, branch, and chart_path keys

        Raises:
            KubernetesDeploymentError: If URL format is invalid
        """
        # Pattern for github.com/user/repo/tree/branch/path or blob/branch/path
        pattern = r"github\.com/([^/]+)/([^/]+)/(?:tree|blob)/([^/]+)/?(.*)?"
        match = re.search(pattern, url)

        if not match:
            raise KubernetesDeploymentError(
                f"Invalid GitHub URL format: {url}. "
                f"Expected format: https://github.com/<owner>/<repo>/tree/<branch>/<path>"
            )

        return {
            "owner": match.group(1),
            "repo": match.group(2),
            "branch": match.group(3),
            "chart_path": self._clean_chart_path(match.group(4) or ""),
        }

    @staticmethod
    def _clean_chart_path(path: str) -> str:
        """Strip filename from a blob path to get the chart directory.

        e.g. 'chart/Chart.yaml' → 'chart'
        """
        if path.endswith("/Chart.yaml"):
            return path[: -len("/Chart.yaml")]
        if path.endswith("Chart.yaml"):
            return path[: -len("Chart.yaml")]
        return path

    def extract_chart_from_github(self, url: str) -> str:
        """Extract helm chart from GitHub URL.

        Clones the repository at the specified branch and returns the path
        to the chart directory.

        Args:
            url: GitHub URL pointing to the chart

        Returns:
            Path to local chart directory

        Raises:
            KubernetesDeploymentError: If clone or extraction fails
        """
        parsed = self.parse_github_helm_url(url)

        # Create temp directory for cloning
        temp_dir = tempfile.mkdtemp(prefix="dispatcher-helm-")
        clone_dir = os.path.join(temp_dir, "clone")

        try:
            # Clone repo at specific branch (shallow clone for speed)
            repo_url = f"https://github.com/{parsed['owner']}/{parsed['repo']}.git"
            logger.info(f"Cloning {repo_url} branch {parsed['branch']} to {clone_dir}")

            result = subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--single-branch",
                    "--branch",
                    parsed["branch"],
                    repo_url,
                    clone_dir,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"Git clone successful: {result.stdout}")

            # Build full path to chart directory
            if parsed["chart_path"]:
                chart_path = os.path.join(clone_dir, parsed["chart_path"])
            else:
                chart_path = clone_dir

            # Verify Chart.yaml exists
            chart_yaml = os.path.join(chart_path, "Chart.yaml")
            if not os.path.exists(chart_yaml):
                raise KubernetesDeploymentError(
                    f"Chart.yaml not found at {chart_path}. "
                    f"Please verify the chart_path in the GitHub URL is correct."
                )

            logger.info(f"Chart extracted successfully to {chart_path}")
            return chart_path

        except subprocess.CalledProcessError as e:
            # Clean up on failure
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise KubernetesDeploymentError(
                f"Failed to clone GitHub repository: {e.stderr or e.stdout}"
            )
        except Exception as e:
            # Clean up on failure
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise KubernetesDeploymentError(f"Failed to extract chart from GitHub: {e}")

    def install_release(
        self,
        repo_url: str,
        chart_name: str,
        release_name: str,
        values: Dict = None,
    ) -> None:
        """Install Helm chart using helm CLI via subprocess.

        Supports both Helm repository URLs and GitHub URLs.
        For GitHub URLs, clones the repository and uses the local chart path.

        Args:
            repo_url: URL of the Helm repository or GitHub chart URL
            chart_name: Name of the chart
            release_name: Name for the Helm release
            values: Dictionary of Helm values

        Raises:
            KubernetesDeploymentError: If installation fails
        """
        temp_files = []
        clone_dirs = []

        try:
            if self.is_github_url(repo_url):
                logger.info(f"Detected GitHub URL, extracting chart...")
                local_chart_path = self.extract_chart_from_github(repo_url)
                clone_dirs.append(os.path.dirname(local_chart_path))

                # Build Helm dependencies for cloned chart
                logger.info("Building Helm dependencies for cloned chart...")
                update_result = subprocess.run(
                    ["helm", "repo", "update"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if update_result.returncode != 0:
                    logger.warning(
                        f"Helm repo update warning: {update_result.stderr}"
                    )

                dep_result = subprocess.run(
                    ["helm", "dependency", "build", local_chart_path],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if dep_result.returncode != 0:
                    logger.warning(
                        f"Helm dependency build failed (may continue without deps): {dep_result.stderr}"
                    )
                else:
                    logger.info(
                        f"Helm dependency build successful: {dep_result.stdout}"
                    )

                cmd = [
                    "helm",
                    "upgrade",
                    "--install",
                    release_name,
                    local_chart_path,
                    "--namespace",
                    self.namespace,
                    "--kubeconfig",
                    self.kubeconfig,
                    "--kube-context",
                    self.context,
                    "--wait",
                    "--atomic",
                    "--timeout",
                    "5m",
                ]
            else:
                repo_name = chart_name.replace("/", "-").lower()
                logger.info(f"Adding helm repo: {repo_name} {repo_url}")
                subprocess.run(
                    ["helm", "repo", "add", repo_name, repo_url, "--force-update"],
                    check=True,
                )
                subprocess.run(["helm", "repo", "update"], check=True)

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
                    "--wait",
                    "--atomic",
                    "--timeout",
                    "5m",
                ]

            if values:
                tf = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False
                )
                json.dump(values, tf)
                tf.close()
                temp_files.append(tf.name)
                cmd.extend(["--values", tf.name])

            logger.info(f"Installing release {release_name} with chart {chart_name}")
            logger.info(f"Executing: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info(f"Helm Success: {result.stdout}")

            logger.info(
                f"Helm release installed successfully: {release_name}"
            )
            self.release_name = release_name

        except subprocess.CalledProcessError as e:
            raise KubernetesDeploymentError(f"Helm failed: {e.stderr}")
        finally:
            for f in temp_files:
                if os.path.exists(f):
                    os.remove(f)
            for d in clone_dirs:
                if os.path.exists(d):
                    shutil.rmtree(d, ignore_errors=True)

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
        chart_name = None
        try:
            if not rp.install_url:
                raise KubernetesDeploymentError(
                    "installUrl (helm repo URL) is required for Kubernetes deployment"
                )
            if not chart_info.get("chartName"):
                raise KubernetesDeploymentError(
                    "chartName is required in chart configuration"
                )

            chart_name = chart_info["chartName"]
            unique_id = str(uuid.uuid4())[:8]
            release_name = f"{chart_name}-{unique_id}"
            service_name = release_name

            values = self.build_helm_values(rp)

            logger.info(
                f"Deploying UNIQUE release {release_name} to namespace {self.namespace}"
            )

            self.install_release(
                repo_url=rp.install_url,
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
            if chart_name:
                self.cleanup_old_releases(chart_name)
            raise KubernetesDeploymentError(f"Deployment failed: {e}")

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

    def cleanup_old_releases(self, chart_name):
        cmd = f"helm list -n {self.namespace} --filter '{chart_name}-' -q | xargs -r helm uninstall -n {self.namespace}"
        subprocess.run(cmd, shell=True)
