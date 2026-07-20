# CLI Reference

## Usage

```bash
spectre [OPTIONS] COMMAND [ARGS]...
```

## Commands

### spectre doctor

Run system diagnostics and report health.

```bash
spectre doctor
```

Checks: system health, Podman status, Ollama availability, git status.

---

### spectre health

Display system health metrics.

```bash
spectre health
```

Shows: CPU, RAM, swap, disk usage, threshold alerts.

---

### spectre status

Show overall system status.

```bash
spectre status
```

Displays a table with status from all agents.

---

### spectre monitor

Display live system metrics.

```bash
spectre monitor                    # One-shot
spectre monitor --interval 5       # Continuous (every 5s)
```

Press `Ctrl+C` to stop continuous monitoring.

---

### spectre update

Check for system updates.

```bash
spectre update
```

Runs `dnf check-update` and reports available packages.

---

### spectre clean

Clean system caches and unused packages.

```bash
spectre clean
```

Cleans: Flatpak unused runtimes, systemd journal, Podman/Docker containers.

---

### spectre repair

Attempt system repair and health restoration.

```bash
spectre repair
```

Checks for failed services and attempts recovery.

---

### spectre optimize

Run system optimization workflows.

```bash
spectre optimize
```

Runs the monthly optimization workflow: full maintenance cycle.

---

### spectre security

Security status and auditing.

```bash
spectre security                   # Quick status
spectre security --audit           # Full audit
```

Full audit includes: SELinux, firewall, ports, secrets scan, SSH audit.

---

### spectre services

Manage systemd services.

```bash
spectre services
```

Shows failed systemd services.

---

### spectre containers

List and manage containers.

```bash
spectre containers                 # List containers
spectre containers --prune         # Prune unused containers
```

---

### spectre models

Manage AI models (Ollama).

```bash
spectre models                     # Ping Ollama
spectre models --list              # List installed models
spectre models --benchmark         # Benchmark first model
```

---

### spectre workflows

Execute or list maintenance workflows.

```bash
spectre workflows                  # List available workflows
spectre workflows --list           # List available workflows
spectre workflows morning-startup  # Run a workflow
```

Available workflows: `morning-startup`, `weekly-maintenance`, `security-audit`, `container-cleanup`, `model-cleanup`, `shutdown`, `monthly-optimization`, `dependency-updates`, `backup`, `restore`.

---

### spectre backup

Backup configuration and data.

```bash
spectre backup
```

---

### spectre restore

Restore configuration and data.

```bash
spectre restore
```

---

### spectre report

Generate system reports.

```bash
spectre report                                      # Daily report to stdout
spectre report --report-type weekly                  # Weekly report
spectre report --output /tmp/report.md               # Save to file
```

Report types: `daily`, `weekly`, `security`, `maintenance`.

---

## Global Options

| Option | Description |
|--------|-------------|
| `--help` | Show help message and exit |

## Exit Codes

| Code | Description |
|------|-------------|
| 0 | Success |
| 1 | Error or failure |
