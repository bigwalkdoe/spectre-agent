from abc import ABC, abstractmethod
from typing import Any


class AgentContext:
    """Context provided to agents for accessing core services."""

    def __init__(self, kernel: Any = None, service_bus: Any = None, memory: Any = None):
        self.kernel = kernel
        self.service_bus = service_bus
        self.memory = memory


class BaseAgent(ABC):
    def __init__(self, name: str, config: dict[str, Any] | None = None, context: AgentContext | None = None):
        self.name = name
        self.config = config or {}
        self.context = context

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the agent, check dependencies, system privileges, etc."""
        pass

    @abstractmethod
    def plan(self) -> list[str]:
        """Formulate a list of steps or tasks to be run."""
        pass

    @abstractmethod
    def execute(self, plan: list[str]) -> dict[str, Any]:
        """Execute the planned actions, returning execution details/results."""
        pass

    @abstractmethod
    def observe(self) -> dict[str, Any]:
        """Perform system checks or gather metrics to verify health/results."""
        pass

    @abstractmethod
    def verify(self) -> bool:
        """Verify that the agent's last execution was successful.

        Returns True if verification passed, False otherwise.
        """
        pass

    @abstractmethod
    def report(self, results: dict[str, Any]) -> str:
        """Generate a user-facing summary report of the agent's operations."""
        pass

    @abstractmethod
    def recover(self, error: Exception) -> bool:
        """Attempt to self-heal or rollback if a failure occurs.

        Returns True if recovery succeeded, False otherwise.
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Clean up resources and prepare for agent shutdown."""
        pass

    def load_memory(self) -> dict[str, Any]:
        """Load agent-specific memory from persistent storage.

        Override to load agent state from the memory engine.
        """
        return {}

    def save_memory(self, data: dict[str, Any]) -> None:
        """Save agent-specific memory to persistent storage.

        Override to persist agent state to the memory engine.
        """
        pass
