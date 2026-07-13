from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class DeploymentStatus(StrEnum):
    pending = "pending"
    building = "building"
    deploying = "deploying"
    healthy = "healthy"
    failed = "failed"
    rolled_back = "rolled_back"


class Strategy(StrEnum):
    rolling = "rolling"
    blue_green = "blue_green"
    canary = "canary"


class Stage(StrEnum):
    pre_check = "pre_check"
    build = "build"
    deploy = "deploy"
    health_check = "health_check"
    record = "record"
    rollback = "rollback"


@dataclass
class StepResult:
    stage: Stage
    status: DeploymentStatus
    message: str
    detail: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass
class Service:
    name: str
    build_type: str = "docker"
    deploy_type: str = "docker-compose"
    strategy: str = "rolling"
    build_context: str = "."
    dockerfile: str = "Dockerfile"
    health_endpoint: str = "/health"
    port: int = 8000
    push_image: bool = False
    registry: str = ""
    image_name: str = ""
    secrets_file: str = ""
    secrets: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Service:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Environment:
    name: str
    hosts: list[str] = field(default_factory=list)
    compose_file: str = "docker-compose.yml"
    kube_namespace: str | None = None
    kube_context: str | None = None
    env_vars: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Environment:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Deployment:
    service: str
    environment: str
    version: str
    status: DeploymentStatus = DeploymentStatus.pending
    steps: list[StepResult] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "environment": self.environment,
            "version": self.version,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Deployment:
        steps = [StepResult(**s) for s in data.get("steps", [])]
        return cls(
            service=data["service"],
            environment=data["environment"],
            version=data["version"],
            status=DeploymentStatus(data.get("status", "pending")),
            steps=steps,
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
        )
