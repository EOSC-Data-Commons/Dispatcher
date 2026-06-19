"""Unit tests for GitHub helm chart support in KubernetesClient."""

import pytest
import os
import tempfile
from unittest.mock import patch, MagicMock
from app.services.kubernetes import KubernetesClient, KubernetesDeploymentError


class TestGitHubURLParsing:
    """Tests for GitHub URL parsing functionality."""

    def test_parse_github_url_tree_format(self):
        """Test parsing GitHub URL with /tree/ format."""
        client = KubernetesClient.__new__(KubernetesClient)  # Create without init

        url = "https://github.com/CERIT-SC/mddash/tree/edc2/helm"
        result = client.parse_github_helm_url(url)

        assert result["owner"] == "CERIT-SC"
        assert result["repo"] == "mddash"
        assert result["branch"] == "edc2"
        assert result["chart_path"] == "helm"

    def test_parse_github_url_with_nested_path(self):
        """Test parsing GitHub URL with nested chart path."""
        client = KubernetesClient.__new__(KubernetesClient)

        url = "https://github.com/user/repo/tree/main/charts/myapp"
        result = client.parse_github_helm_url(url)

        assert result["owner"] == "user"
        assert result["repo"] == "repo"
        assert result["branch"] == "main"
        assert result["chart_path"] == "charts/myapp"

    def test_parse_github_url_blob_format(self):
        """Test parsing GitHub URL with /blob/ format (points to Chart.yaml)."""
        client = KubernetesClient.__new__(KubernetesClient)

        url = "https://github.com/user/repo/blob/develop/chart/Chart.yaml"
        result = client.parse_github_helm_url(url)

        assert result["owner"] == "user"
        assert result["repo"] == "repo"
        assert result["branch"] == "develop"
        assert (
            result["chart_path"] == "chart"
        )  # Should extract directory from file path

    def test_parse_github_url_no_chart_path(self):
        """Test parsing GitHub URL without explicit chart path."""
        client = KubernetesClient.__new__(KubernetesClient)

        url = "https://github.com/user/repo/tree/main"
        result = client.parse_github_helm_url(url)

        assert result["owner"] == "user"
        assert result["repo"] == "repo"
        assert result["branch"] == "main"
        assert result["chart_path"] == ""

    def test_parse_github_url_invalid_format(self):
        """Test that invalid GitHub URLs raise an error."""
        client = KubernetesClient.__new__(KubernetesClient)

        with pytest.raises(KubernetesDeploymentError) as exc_info:
            client.parse_github_helm_url("https://gitlab.com/user/repo/tree/main")

        assert "Invalid GitHub URL format" in str(exc_info.value)

    def test_is_github_url_true(self):
        """Test is_github_url returns True for GitHub URLs."""
        client = KubernetesClient.__new__(KubernetesClient)

        assert client.is_github_url("https://github.com/user/repo") is True
        assert client.is_github_url("https://GITHUB.com/user/repo") is True
        assert client.is_github_url("http://github.com/user/repo/tree/main") is True

    def test_is_github_url_false(self):
        """Test is_github_url returns False for non-GitHub URLs."""
        client = KubernetesClient.__new__(KubernetesClient)

        assert client.is_github_url("https://charts.bitnami.com/bitnami") is False
        assert client.is_github_url("https://example.com/chart") is False
        assert client.is_github_url("ftp://example.com/chart") is False


class TestValidateKubernetesConfig:
    """Tests for updated validate_kubernetes_config functionality."""

    def test_validate_valid_github_config(self):
        """Test validation passes for valid GitHub config."""
        client = KubernetesClient.__new__(KubernetesClient)

        dest = {
            "hasPart": [
                {
                    "chartName": "mddashboard",
                    "url": "https://github.com/CERIT-SC/mddash/tree/edc2/helm",
                }
            ]
        }

        # Should not raise
        client.validate_kubernetes_config(dest)

    def test_validate_valid_helm_repo_config(self):
        """Test validation passes for valid Helm repo config."""
        client = KubernetesClient.__new__(KubernetesClient)

        dest = {
            "hasPart": [
                {"chartName": "nginx", "url": "https://charts.bitnami.com/bitnami"}
            ]
        }

        # Should not raise
        client.validate_kubernetes_config(dest)

    def test_validate_missing_has_part(self):
        """Test validation fails when hasPart is missing."""
        client = KubernetesClient.__new__(KubernetesClient)

        with pytest.raises(KubernetesDeploymentError) as exc_info:
            client.validate_kubernetes_config({})

        assert "Missing hasPart" in str(exc_info.value)

    def test_validate_missing_chart_name(self):
        """Test validation fails when chartName is missing."""
        client = KubernetesClient.__new__(KubernetesClient)

        dest = {"hasPart": [{"url": "https://github.com/user/repo/tree/main"}]}

        with pytest.raises(KubernetesDeploymentError) as exc_info:
            client.validate_kubernetes_config(dest)

        assert "chartName is required" in str(exc_info.value)

    def test_validate_missing_url(self):
        """Test validation fails when url is missing."""
        client = KubernetesClient.__new__(KubernetesClient)

        dest = {"hasPart": [{"chartName": "mychart"}]}

        with pytest.raises(KubernetesDeploymentError) as exc_info:
            client.validate_kubernetes_config(dest)

        assert "url is required" in str(exc_info.value)

    def test_validate_empty_has_part_list(self):
        """Test validation fails when hasPart is empty list."""
        client = KubernetesClient.__new__(KubernetesClient)

        with pytest.raises(KubernetesDeploymentError) as exc_info:
            client.validate_kubernetes_config({"hasPart": []})

        assert "non-empty list" in str(exc_info.value)


class TestBuildChartConfig:
    """Tests for build_chart_config functionality."""

    def test_build_chart_config_github(self):
        """Test building chart config from GitHub URL."""
        client = KubernetesClient.__new__(KubernetesClient)

        chart_info = {
            "chartName": "mddashboard",
            "url": "https://github.com/CERIT-SC/mddash/tree/edc2/helm",
        }

        url, name = client.build_chart_config(chart_info)

        assert url == "https://github.com/CERIT-SC/mddash/tree/edc2/helm"
        assert name == "mddashboard"

    def test_build_chart_config_helm_repo(self):
        """Test building chart config from Helm repo URL."""
        client = KubernetesClient.__new__(KubernetesClient)

        chart_info = {"chartName": "nginx", "url": "https://charts.bitnami.com/bitnami"}

        url, name = client.build_chart_config(chart_info)

        assert url == "https://charts.bitnami.com/bitnami"
        assert name == "nginx"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
