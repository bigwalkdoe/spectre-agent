from __future__ import annotations

from spectre.deployer import _image_tag


def test_deployer_image_tag_default() -> None:
    assert _image_tag("api", "v1") == "api:v1"


def test_deployer_image_tag_with_registry() -> None:
    assert _image_tag("api", "v1", "ghcr.io/myorg") == "ghcr.io/myorg/api:v1"


def test_deployer_image_tag_custom_name() -> None:
    assert _image_tag("api", "v1", "ghcr.io/myorg", "my-api") == "ghcr.io/myorg/my-api:v1"
