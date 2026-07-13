from __future__ import annotations

from spectre.builder import _image_tag, docker_push
from spectre.models import DeploymentStatus


def test_image_tag_default() -> None:
    assert _image_tag("api", "v1") == "api:v1"


def test_image_tag_with_registry() -> None:
    assert _image_tag("api", "v1", "ghcr.io/myorg") == "ghcr.io/myorg/api:v1"


def test_image_tag_with_custom_name() -> None:
    assert _image_tag("api", "v1", "ghcr.io/myorg", "my-api") == "ghcr.io/myorg/my-api:v1"


def test_image_tag_registry_no_custom_name() -> None:
    assert _image_tag("api", "v1", "docker.io/lib") == "docker.io/lib/api:v1"


def test_docker_push_fails_on_missing_image() -> None:
    result = docker_push("test:nonexistent-image-tag-12345")
    assert result.status == DeploymentStatus.failed
    assert result.message
