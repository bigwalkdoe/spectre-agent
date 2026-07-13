from __future__ import annotations

from pathlib import Path


def load_dotenv(path: str) -> dict[str, str]:
    p = Path(path)
    if not p.is_file():
        return {}
    secrets: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or \
           (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if key:
            secrets[key] = val
    return secrets


def collect_secrets(
    service_secrets: dict[str, str] | None = None,
    environment_secrets: dict[str, str] | None = None,
    secrets_file: str | None = None,
    cli_secrets_file: str | None = None,
) -> dict[str, str]:
    merged: dict[str, str] = {}
    if service_secrets:
        merged.update(service_secrets)
    if environment_secrets:
        merged.update(environment_secrets)
    for sf in (secrets_file, cli_secrets_file):
        if sf:
            merged.update(load_dotenv(sf))
    return merged


def merge_secrets(
    env_vars: dict[str, str] | None,
    secrets: dict[str, str],
) -> dict[str, str] | None:
    if not secrets:
        return env_vars
    merged = {**(env_vars or {})}
    merged.update(secrets)
    return merged
