import time
from typing import Any

import httpx

from packages.core.agent import BaseAgent
from packages.memory.db import MaintenanceRecord, save_maintenance_record


class AIAgent(BaseAgent):
    def __init__(self, config: dict[str, Any] | None = None, context: Any = None):
        super().__init__(name="ai", config=config, context=context)
        self.ollama_url = self.config.get("ollama_url", "http://localhost:11434")

    def initialize(self) -> None:
        """Check if Ollama service is reachable."""
        self.ollama_available = False
        try:
            resp = httpx.get(f"{self.ollama_url}/api/tags", timeout=3.0)
            if resp.status_code == 200:
                self.ollama_available = True
        except Exception:
            self.ollama_available = False
        if self.context and hasattr(self.context, "service_bus") and self.context.service_bus:
            self.context.service_bus.register_service(
                "ai", "agent", self, actions=["ollama-ping", "list-models", "benchmark-model"]
            )

    def plan(self) -> list[str]:
        """Formulate AI tasks (Ollama health check, model listings, benchmark)."""
        plan_steps = ["ollama-ping"]
        if self.ollama_available:
            plan_steps.append("list-models")
            # Run benchmark if configured or if a preferred test model exists
            plan_steps.append("benchmark-model")
        return plan_steps

    def execute(self, plan: list[str]) -> dict[str, Any]:
        """Run AI tasks."""
        results = {}
        for action in plan:
            start_time = time.monotonic()
            status = "success"
            log_output = ""

            try:
                if action == "ollama-ping":
                    log_output = self._run_ollama_ping()
                elif action == "list-models":
                    log_output = self._run_list_models()
                elif action == "benchmark-model":
                    log_output = self._run_benchmark()
                else:
                    log_output = f"Unknown action: {action}"
                    status = "failed"
            except Exception as e:
                log_output = f"Execution failed: {e}"
                status = "failed"

            elapsed = int((time.monotonic() - start_time) * 1000)
            results[action] = {
                "status": status,
                "log_output": log_output,
                "duration_ms": elapsed,
            }

            save_maintenance_record(
                MaintenanceRecord(
                    agent=self.name,
                    action=action,
                    status=status,
                    log_output=log_output,
                    duration_ms=elapsed,
                )
            )
        return results

    def observe(self) -> dict[str, Any]:
        """Observe Ollama stats: active models, latency baseline."""
        models = []
        available = False

        try:
            resp = httpx.get(f"{self.ollama_url}/api/tags", timeout=2.0)
            if resp.status_code == 200:
                available = True
                models = [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            pass

        return {
            "ollama_available": available,
            "installed_models": models,
            "installed_models_count": len(models),
        }

    def report(self, results: dict[str, Any]) -> str:
        """Format operations report."""
        lines = ["=== AI Operations Report ==="]
        for action, data in results.items():
            icon = "✓" if data["status"] == "success" else "✗"
            lines.append(f"{icon} {action}: {data['status'].upper()} ({data['duration_ms']}ms)")
            lines.append(f"  Details: {data['log_output']}")
        return "\n".join(lines)

    def recover(self, error: Exception) -> bool:
        """Recovery logic."""
        return True

    def verify(self) -> bool:
        """Verify Ollama is reachable."""
        return self.ollama_available

    def shutdown(self) -> None:
        """Clean up before shutdown."""
        pass

    # Helper operations
    def _run_ollama_ping(self) -> str:
        try:
            resp = httpx.get(self.ollama_url, timeout=2.0)
            return f"Ollama is running at {self.ollama_url}. Status: {resp.text.strip() or 'OK'}"
        except Exception as e:
            return f"Ollama ping failed: {e}"

    def _run_list_models(self) -> str:
        try:
            resp = httpx.get(f"{self.ollama_url}/api/tags", timeout=3.0)
            models = resp.json().get("models", [])
            if not models:
                return "Ollama is responsive, but no local models are installed."
            details = [f"{m['name']} ({m.get('size', 0) // (1024 * 1024)} MB)" for m in models]
            return f"Available models: {', '.join(details)}."
        except Exception as e:
            return f"Failed to list models: {e}"

    def _run_benchmark(self) -> str:
        # Check first available model to run benchmark
        try:
            resp = httpx.get(f"{self.ollama_url}/api/tags", timeout=3.0)
            models = resp.json().get("models", [])
            if not models:
                return "Cannot run benchmark: No models installed."

            # Select first model (or configuration model)
            target_model = self.config.get("benchmark_model", models[0]["name"])

            start = time.monotonic()
            post_resp = httpx.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": target_model,
                    "prompt": "Respond with exactly one word: 'Ready'.",
                    "stream": False,
                    "options": {"num_predict": 5},
                },
                timeout=30.0,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            if post_resp.status_code == 200:
                reply = post_resp.json().get("response", "").strip()
                return f"Model '{target_model}' benchmark complete: response '{reply}', latency: {latency_ms}ms"
            return f"Model benchmark response error {post_resp.status_code}: {post_resp.text}"
        except Exception as e:
            return f"Model benchmark failed: {e}"
