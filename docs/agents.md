# Spectre Agents

## Overview

Spectre uses specialized agents for different domains. Each agent follows the standard lifecycle: `initialize → plan → execute → observe → report → recover`.

## Agent Reference

### Linux Agent

**Purpose:** System health, package management, service control.

**Actions:**
| Action | Description |
|--------|-------------|
| `system-health-check` | Check failed systemd services |
| `dnf-check-update` | Check for available package updates |
| `flatpak-prune` | Remove unused Flatpak runtimes |
| `journal-cleanup` | Vacuum systemd journal logs |
| `selinux-check` | Check SELinux enforcement mode |
| `firewall-check` | Check firewalld status |

**Metrics:** CPU, RAM, swap, disk, battery, temperature.

---

### DevOps Agent

**Purpose:** Container management (Podman, Docker, Kubernetes).

**Actions:**
| Action | Description |
|--------|-------------|
| `podman-status` | List Podman containers |
| `podman-prune` | Prune Podman system |
| `docker-status` | List Docker containers |
| `docker-prune` | Prune Docker system |
| `kubectl-status` | Check Kubernetes cluster connection |

**Metrics:** Running container count, Kubernetes context.

---

### Security Agent

**Purpose:** Security auditing and compliance.

**Actions:**
| Action | Description |
|--------|-------------|
| `selinux-audit` | Audit SELinux mode |
| `firewall-audit` | Audit firewalld status |
| `ports-audit` | Scan listening ports |
| `secrets-scan` | Scan for exposed secrets |
| `ssh-audit` | Audit SSH configuration |

**Metrics:** Listening ports, incident count.

---

### AI Agent

**Purpose:** Ollama LLM management and benchmarking.

**Actions:**
| Action | Description |
|--------|-------------|
| `ollama-ping` | Check Ollama availability |
| `list-models` | List installed models |
| `benchmark-model` | Run inference benchmark |

**Metrics:** Available models, model count.

---

### Developer Agent

**Purpose:** Software development tooling.

**Actions:**
| Action | Description |
|--------|-------------|
| `git-status` | Check git working tree status |
| `dependency-audit` | Check for outdated packages |
| `test-runner` | Run pytest |
| `lint-check` | Run ruff linter |
| `type-check` | Run mypy type checker |

**Metrics:** Branch, dirty status, ahead count.

---

### Monitoring Agent

**Purpose:** Continuous system metrics collection.

**Actions:**
| Action | Description |
|--------|-------------|
| `collect-metrics` | Collect and persist system metrics |
| `check-thresholds` | Alert if metrics exceed thresholds |

**Metrics:** Full system snapshot (CPU, RAM, swap, disk, battery, temperature, network).

**Thresholds:** Configurable per metric in settings.

---

### Documentation Agent

**Purpose:** Documentation generation and maintenance.

**Actions:**
| Action | Description |
|--------|-------------|
| `scan-docs` | Inventory documentation files |
| `check-links` | Check for broken internal links |
| `coverage-report` | Report docstring coverage |

**Metrics:** Markdown file count, Python file count, documented modules.

---

### Publishing Agent

**Purpose:** Release management and publishing.

**Actions:**
| Action | Description |
|--------|-------------|
| `check-version` | Read version from pyproject.toml |
| `validate-dist` | Check dist/ directory contents |
| `check-git-status` | Check for uncommitted changes |

**Metrics:** Version, git tag, dirty status.

---

## Workflow Engine

The `WorkflowEngine` orchestrates agents into predefined workflows:

| Workflow | Agents Used |
|----------|-------------|
| `morning-startup` | Linux, AI |
| `weekly-maintenance` | Linux, DevOps, Security |
| `security-audit` | Security |
| `container-cleanup` | DevOps |
| `model-cleanup` | AI |
| `shutdown` | Linux, DevOps |
| `monthly-optimization` | Linux, DevOps, Security, Developer |
| `dependency-updates` | Developer |
| `backup` | Linux, Developer |
| `restore` | Linux, DevOps |

Run workflows via CLI: `spectre workflows <name>`
Or via API: `POST /api/workflows/<name>`
