# Getting Started with Spectre

## What is Spectre?

Spectre is an autonomous system maintenance and operations platform for Fedora Linux. It monitors, maintains, secures, and manages your workstation automatically.

## Quick Install

```bash
git clone https://github.com/deon/spectre.git
cd spectre
bash scripts/install.sh
```

## Manual Install

```bash
# Create virtual environment
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Add to PATH
export PATH="$(pwd)/.venv/bin:$PATH"
```

## First Run

```bash
# Run diagnostics
spectre doctor

# Check system health
spectre health

# View overall status
spectre status
```

## Key Commands

| Command | Description |
|---------|-------------|
| `spectre doctor` | Run system diagnostics |
| `spectre health` | Display system health metrics |
| `spectre status` | Show overall system status |
| `spectre monitor` | Display live system metrics |
| `spectre security --audit` | Run full security audit |
| `spectre workflows` | List available workflows |
| `spectre workflows morning-startup` | Run a workflow |

## Configuration

Spectre stores configuration at `~/.config/spectre/settings.yaml`:

```yaml
profile: laptop

ollama:
  url: "http://localhost:11434"

monitoring:
  interval_seconds: 30
  enabled: true
```

## Running as a Service

```bash
# Install systemd service
bash scripts/install.sh
# Answer 'y' to the systemd prompt

# Or manually
systemctl --user start spectre
systemctl --user enable spectre
```

## REST API

```bash
# Start the API server
make run-api

# Available at http://localhost:8080
curl http://localhost:8080/api/health
curl http://localhost:8080/api/agents
curl http://localhost:8080/api/system/status
```

## Web Dashboard

Open http://localhost:8080 in your browser after starting the API server. The dashboard shows:
- System status from all agents
- Available agents and workflows
- One-click workflow execution
- Live metrics refresh
