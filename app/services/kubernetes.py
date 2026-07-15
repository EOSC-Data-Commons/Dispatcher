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

import requests
import urllib3
import yaml

from app.config import settings

# Suppress warnings from the dev Rancher's self-signed certificate.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KubernetesDeploymentError(Exception):
    """Exception raised for Kubernetes deployment errors."""

    pass


class KubernetesClient:
    """Client for deploying services to Kubernetes clusters using Helm 3 CLI.

    Supports two modes via ``Settings.rancher_mode``:

    * ``"local"`` — uses a static kubeconfig file (default path
      ``/usr/src/app/k8s-config.yaml``).
    * ``"dev"``   — exchanges the user's EGI Check-in token for a Rancher
      token, fetches a kubeconfig from the Rancher API, and uses that
      temporary kubeconfig for Helm operations.
    """

    def __init__(
        self,
        user_token: str | None = None,
        kubeconfig: str | None = None,
        context: str | None = None,
    ):
        self._temp_kubeconfig: str | None = None

        if settings.rancher_mode == "dev" and user_token:
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
    # Dev Rancher helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_kubeconfig_context(kubeconfig_path: str) -> str:
        """Read the first context name from a kubeconfig file."""
        with open(kubeconfig_path) as f:
            cfg = yaml.safe_load(f)
        contexts = cfg.get("contexts", [])
        if contexts:
            return contexts[0]["name"]
        raise KubernetesDeploymentError(
            "No context found in Rancher-generated kubeconfig"
        )

    def _generate_rancher_kubeconfig(self, user_token: str) -> str:
        """Exchange the EGI token for a Rancher token and download a kubeconfig.

        Returns the path to a temporary kubeconfig file that MUST be cleaned
        up by the caller (or left for the OS to reclaim).
        """
        logger.info("Rancher dev mode: exchanging EGI token for Rancher token")
        exchanged = self._exchange_token(user_token)
        rancher_token = exchanged["access_token"]
        logger.info("Rancher dev mode: token exchange successful")

        logger.info("Rancher dev mode: fetching kubeconfig from Rancher API")
        kubeconfig_yaml = self._fetch_rancher_kubeconfig(rancher_token)
        logger.info("Rancher dev mode: kubeconfig fetched successfully")

        tf = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, prefix="rancher-kubeconfig-"
        )
        tf.write(kubeconfig_yaml)
        tf.close()
        logger.info(f"Rancher dev mode: kubeconfig written to {tf.name}")
        return tf.name

    def _exchange_token(self, user_token: str) -> dict:
        """Perform OAuth2 token exchange at the EGI Check-in token endpoint."""
        token_url = settings.rancher_dev_token_exchange_url
        client_id = settings.rancher_dev_client_id
        client_secret = settings.rancher_dev_client_secret
        audience = settings.rancher_dev_audience

        try:
            resp = requests.post(
                token_url,
                auth=(client_id, client_secret),
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "subject_token": user_token,
                    "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                    "audience": audience,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.exception("Rancher token exchange failed")
            raise KubernetesDeploymentError(
                f"Token exchange to Rancher dev failed: {e}"
            )

    def _fetch_rancher_kubeconfig(self, rancher_token: str) -> str:
        """Discover first available cluster and download its kubeconfig.

        Lists clusters from the Rancher API, picks the first active one,
        and calls the ``generateKubeconfig`` action on it.
        """
        base = settings.rancher_dev_url.rstrip("/")
        auth_headers = {
            "Authorization": f"Bearer {rancher_token}",
            "Content-Type": "application/json",
        }

        # Step 1 — list clusters and pick the first active one
        logger.info("Rancher dev mode: listing available clusters")
        try:
            list_resp = requests.get(
                f"{base}/v3/clusters",
                headers=auth_headers,
                verify=False,
                timeout=30,
            )
            list_resp.raise_for_status()
        except requests.RequestException as e:
            raise KubernetesDeploymentError(f"Failed to list Rancher clusters: {e}")

        clusters = list_resp.json().get("data", [])
        if not clusters:
            raise KubernetesDeploymentError(
                "No clusters found in Rancher dev. "
                "Import or create at least one cluster in the Rancher UI."
            )

        # Prefer the first active cluster
        cluster_id = None
        for c in clusters:
            if c.get("state") == "active":
                cluster_id = c["id"]
                cluster_name = c.get("name", cluster_id)
                logger.info(
                    f"Rancher dev mode: using cluster '{cluster_name}' ({cluster_id})"
                )
                break

        if not cluster_id:
            # Fall back to the first cluster, even if not active
            cluster_id = clusters[0]["id"]
            logger.warning(
                f"Rancher dev mode: no active cluster found, "
                f"falling back to '{clusters[0].get('name', cluster_id)}'"
            )

        # Step 2 — generate kubeconfig for the selected cluster
        kubeconfig_url = f"{base}/v3/clusters/{cluster_id}?action=generateKubeconfig"
        logger.info(f"Rancher dev mode: generating kubeconfig for cluster {cluster_id}")
        try:
            resp = requests.post(
                kubeconfig_url,
                headers=auth_headers,
                verify=False,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            kubeconfig = data.get("config") or data.get("kubeconfig") or ""
            if not kubeconfig:
                raw_yaml = resp.text
                try:
                    parsed = yaml.safe_load(raw_yaml)
                    if isinstance(parsed, dict) and "apiVersion" in parsed:
                        return raw_yaml
                except yaml.YAMLError:
                    pass
                raise KubernetesDeploymentError(
                    "Rancher API did not return a kubeconfig"
                )
            return (
                kubeconfig
                if isinstance(kubeconfig, str)
                else yaml.safe_dump(kubeconfig)
            )
        except requests.RequestException as e:
            logger.exception("Failed to fetch kubeconfig from Rancher")
            raise KubernetesDeploymentError(
                f"Failed to fetch kubeconfig from Rancher dev: {e}"
            )

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

    @staticmethod
    def _sanitize_quantity(raw: str) -> str:
        """Convert a human-readable resource quantity to Kubernetes format.

        ``"4 GiB"`` → ``"4Gi"``, ``"200 GiB"`` → ``"200Gi"``.
        """
        if not raw:
            return raw
        # Remove spaces and trailing 'B' from binary prefixes (MiB → Mi, GiB → Gi, etc.)
        sanitized = raw.replace(" ", "")
        sanitized = re.sub(r"(\d)([KMGTPE]i)B", r"\1\2", sanitized, flags=re.IGNORECASE)
        return sanitized

    def build_helm_values(self, rp: RuntimePlatform) -> Dict:
        """Build Helm values from RuntimePlatform configuration.

        Args:
            rp: RuntimePlatform with resource requirements.

        Returns:
            Dictionary of Helm values.
        """
        values = {}

        # Standard Helm chart keys (used by charts created via 'helm create')
        values["podSecurityContext"] = {
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        }
        values["securityContext"] = {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        }

        if rp.num_cpus > 1:
            cpu_value = str(rp.num_cpus)
            values.setdefault("resources", {}).setdefault("requests", {})[
                "cpu"
            ] = cpu_value
            values["resources"].setdefault("limits", {})["cpu"] = cpu_value

        if rp.memory:
            mem = self._sanitize_quantity(rp.memory)
            values.setdefault("resources", {}).setdefault("requests", {})[
                "memory"
            ] = mem
            values["resources"].setdefault("limits", {})["memory"] = mem

        if rp.storage:
            values.setdefault("persistence", {})["size"] = self._sanitize_quantity(
                rp.storage
            )

        if rp.input_files:
            values["inputFiles"] = [{"url": f.url} for f in rp.input_files]

        return values

    def _find_deployment_name(self, release_name: str) -> str:
        """Find the deployment name created by a Helm release.

        Args:
            release_name: Helm release name.

        Returns:
            Deployment name, or None if not found.
        """
        apps_v1 = k8s_client.AppsV1Api()
        label_selector = f"app.kubernetes.io/instance={release_name}"
        deployments = apps_v1.list_namespaced_deployment(
            namespace=self.namespace, label_selector=label_selector
        )
        if not deployments.items:
            return None
        return deployments.items[0].metadata.name

    def _patch_deployment_security(self, release_name: str) -> None:
        """Patch the deployment created by Helm to enforce PodSecurity compliance.

        Uses the Python Kubernetes client (AppsV1Api) instead of ``kubectl``
        to avoid kubectl connectivity issues through Rancher proxies.

        Uses proper V1 model objects (not plain dicts) to ensure correct
        serialization when patching the deployment.

        Args:
            release_name: Name of the Helm release (used to find the deployment).
        """
        pod_sc = k8s_client.V1PodSecurityContext(
            run_as_non_root=True,
            seccomp_profile=k8s_client.V1SeccompProfile(type="RuntimeDefault"),
        )
        container_sc = k8s_client.V1SecurityContext(
            allow_privilege_escalation=False,
            capabilities=k8s_client.V1Capabilities(drop=["ALL"]),
            run_as_non_root=True,
            seccomp_profile=k8s_client.V1SeccompProfile(type="RuntimeDefault"),
        )

        try:
            deployment_name = self._find_deployment_name(release_name)
            if not deployment_name:
                logger.warning(
                    f"No deployment found for release {release_name}, "
                    f"skipping security patch"
                )
                return

            apps_v1 = k8s_client.AppsV1Api()
            deploy = apps_v1.read_namespaced_deployment(
                name=deployment_name, namespace=self.namespace
            )

            # Apply pod-level security context
            deploy.spec.template.spec.security_context = pod_sc

            # Apply container-level security context to every container
            for container in deploy.spec.template.spec.containers:
                container.security_context = container_sc

            apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace,
                body=deploy,
            )
            logger.info(
                f"Patched deployment {deployment_name} with security context "
                f"for release {release_name}"
            )
        except ApiException as e:
            logger.warning(
                f"Failed to patch deployment security context for "
                f"{release_name}: {e}. The chart may already apply these "
                f"settings or the deployment may not be ready yet."
            )

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
                    logger.warning(f"Helm repo update warning: {update_result.stderr}")

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
                ]

            if values:
                tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
                json.dump(values, tf)
                tf.close()
                temp_files.append(tf.name)
                cmd.extend(["--values", tf.name])

            logger.info(f"Installing release {release_name} with chart {chart_name}")
            logger.info(f"Executing: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info(f"Helm Success: {result.stdout}")

            logger.info(f"Helm release installed successfully: {release_name}")
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

    def _log_pod_statuses(self, deployment_name: str) -> None:
        """Log pod statuses for a deployment to help debug readiness issues."""
        try:
            v1 = k8s_client.CoreV1Api()
            label_selector = None
            deploy = k8s_client.AppsV1Api().read_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace,
            )
            if deploy.spec.selector.match_labels:
                labels = ",".join(
                    f"{k}={v}" for k, v in deploy.spec.selector.match_labels.items()
                )
                label_selector = labels

            pods = v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=label_selector,
            )
            for pod in pods.items:
                phase = pod.status.phase
                conditions = []
                if pod.status.conditions:
                    for c in pod.status.conditions:
                        if c.status != "True":
                            conditions.append(f"{c.type}={c.status}:{c.reason}")
                container_statuses = []
                if pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        waiting = getattr(cs.state, "waiting", None)
                        if waiting:
                            container_statuses.append(
                                f"{cs.name}:Waiting({waiting.reason}:{waiting.message})"
                            )
                        terminated = getattr(cs.state, "terminated", None)
                        if terminated:
                            container_statuses.append(
                                f"{cs.name}:Terminated({terminated.reason})"
                            )
                        if not cs.ready and not waiting and not terminated:
                            container_statuses.append(f"{cs.name}:NotReady")

                status_parts = [f"phase={phase}"]
                if conditions:
                    status_parts.append(f"conditions=[{', '.join(conditions)}]")
                if container_statuses:
                    status_parts.append(f"containers=[{', '.join(container_statuses)}]")

                logger.info(f"Pod {pod.metadata.name}: {', '.join(status_parts)}")
        except Exception as e:
            logger.warning(f"Failed to fetch pod statuses: {e}")

    def _wait_for_rollout(self, release_name: str, timeout: int = 300) -> None:
        """Wait for the deployment matching a Helm release to become ready.

        Uses the Python Kubernetes client (AppsV1Api) instead of ``kubectl``
        to avoid connectivity issues through Rancher proxies.

        Args:
            release_name: Helm release name (used to find deployment via label).
            timeout: Maximum seconds to wait.

        Raises:
            KubernetesDeploymentError: If rollout times out or fails.
        """
        poll = 10  # seconds per poll
        deadline = time.time() + timeout
        deployment_name = None

        while time.time() < deadline:
            remaining = int(deadline - time.time())
            try:
                if deployment_name is None:
                    deployment_name = self._find_deployment_name(release_name)
                    if not deployment_name:
                        raise KubernetesDeploymentError(
                            f"No deployment found for release {release_name}"
                        )
                    logger.info(
                        f"Waiting for deployment {deployment_name} "
                        f"to be ready (timeout remaining: {remaining}s)..."
                    )

                apps_v1 = k8s_client.AppsV1Api()
                deploy = apps_v1.read_namespaced_deployment(
                    name=deployment_name,
                    namespace=self.namespace,
                )
                conditions = deploy.status.conditions or []
                available = next((c for c in conditions if c.type == "Available"), None)
                ready_replicas = deploy.status.ready_replicas or 0
                replicas = deploy.status.replicas or 0

                if (
                    available
                    and available.status == "True"
                    and ready_replicas == replicas
                    and replicas > 0
                ):
                    logger.info(
                        f"Deployment {deployment_name} is ready "
                        f"({ready_replicas}/{replicas} replicas)"
                    )
                    return

                # Fetch pods to diagnose why they aren't ready
                self._log_pod_statuses(deployment_name)

                time.sleep(poll)

            except Exception as e:
                logger.warning(
                    f"Error checking deployment status for "
                    f"{release_name}: {e}. Retrying in {poll}s..."
                )
                time.sleep(poll)

        raise KubernetesDeploymentError(
            f"Deployment rollout timed out after {timeout}s for {release_name}"
        )

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

            # Patch the resulting deployment to enforce PodSecurity compliance,
            # since many Helm charts do not template securityContext values themselves.
            self._patch_deployment_security(release_name)

            # Now wait for the rollout to complete — pods will be accepted
            # now that the security context has been patched in.
            self._wait_for_rollout(release_name)

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
                ],
                check=True,
            )
            logger.info(f"Helm release uninstalled successfully: {release_name}")
        except subprocess.CalledProcessError as e:
            raise KubernetesDeploymentError(f"Failed to uninstall Helm release: {e}")

    def cleanup_old_releases(self, chart_name):
        cmd = (
            f"helm list -n {self.namespace} --filter '{chart_name}-' -q "
            f"--kubeconfig {self.kubeconfig} --kube-context {self.context} "
            f"| xargs -r helm uninstall -n {self.namespace} "
            f"--kubeconfig {self.kubeconfig} --kube-context {self.context}"
        )
        subprocess.run(cmd, shell=True, capture_output=True)
