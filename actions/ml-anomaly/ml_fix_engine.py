#!/usr/bin/env python3
"""
ML Fix Engine — anomaly diagnosis and safety-validated remediation.

Consumes a structured anomaly report produced by anomaly_detector.py, asks a
free local LLM (Ollama by default) for a root-cause analysis and a remediation
plan, then validates every proposed command against a strict safety policy.

Modes:
  report   (default) Write a remediation report, optionally POST to Alertmanager.
  apply              Apply only commands that pass the safety validator.
  dry-run            Print the commands that *would* run, without executing.

Safety model:
  * Every command is parsed and checked against a deny-list of dangerous
    tokens and an allow-list of permitted command prefixes.
  * Only root-cause "safe" automations (restart a known service, rotate a log,
    clear tmp, run a health check) are eligible for automatic apply.
  * Anything not explicitly allowed is dropped and flagged for human review.
"""

import os
import sys
import json
import logging
import shutil
import subprocess
import argparse
import urllib.request
import urllib.error
from datetime import datetime

LOG_DIR = os.environ.get("ML_LOG_DIR", "/var/log/ml-anomaly")
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(os.path.join(LOG_DIR, "remediation"), exist_ok=True)
except OSError:
    LOG_DIR = os.path.join("/tmp", "ml-anomaly")
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(os.path.join(LOG_DIR, "remediation"), exist_ok=True)

import providers

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'fix_engine.log')),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

REPORT_DIR = os.path.join(LOG_DIR, "remediation")
LATEST_ANOMALY = os.path.join(LOG_DIR, "latest_detection.json")

# Audit trail destination (mirrors audit-trail.sh resolution).
AUDIT_LOG_DIR = os.environ.get("AUDIT_LOG_DIR", "/var/log/audit")
try:
    os.makedirs(AUDIT_LOG_DIR, exist_ok=True)
except OSError:
    AUDIT_LOG_DIR = os.path.join("/tmp", "audit")
    os.makedirs(AUDIT_LOG_DIR, exist_ok=True)
AUDIT_LOG = os.path.join(AUDIT_LOG_DIR, "audit.log")


def log_to_audit(message):
    """Record an auto-applied remediation action to the audit trail."""
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] ML-FIX: {message}\n")
    except OSError:
        pass
    at_script = os.path.join(os.path.dirname(__file__), "..", "maintenance", "audit-trail.sh")
    if os.path.exists(at_script):
        try:
            subprocess.run(
                [at_script, "log-process", "ml-fix-engine", message],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            )
        except Exception:
            pass

# Services/daemons that may be safely restarted by the fix engine.
ALLOWED_SERVICES = {
    "prometheus", "grafana", "alertmanager", "node-exporter", "cadvisor",
    "redis-exporter", "postgres-exporter", "blackbox-exporter", "web-dashboard",
    "docker", "fail2ban", "ml-anomaly-detection", "ml-metrics-exporter",
}

# Dangerous tokens that must never appear in an auto-applied command.
DENY_TOKENS = (
    "rm -rf /", "rm -fr /", "mkfs", "dd if=", ":(){", "chmod -R 777 /",
    "chown -R", "> /dev/sd", "shutdown", "reboot", "init ", "wipefs",
    "curl", "wget",  # piping remote content into a shell is forbidden
)

# Allow-list: (prefix, validator) — command must start with one of these.
ALLOW_PREFIXES = (
    "systemctl restart ",
    "systemctl reload ",
    "docker restart ",
    "docker start ",
    "journalctl ",
    "logrotate ",
    "systemd-run ",
    "find /tmp ",
    "find /var/tmp ",
    "truncate -s 0 ",
    "sync",
    "echo ",
)


def load_anomaly_report(path):
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    if os.path.exists(LATEST_ANOMALY):
        with open(LATEST_ANOMALY) as f:
            return json.load(f)
    return None


def build_prompt(report, metrics_context):
    anomaly_summary = json.dumps(report, indent=2)
    ctx = json.dumps(metrics_context, indent=2) if metrics_context else "{}"
    return f"""You are a senior Linux SRE operating Spectre Suite.
A machine-learning anomaly detector flagged a system anomaly. Diagnose the root
cause and propose a remediation plan.

ANOMALY REPORT:
{anomaly_summary}

RECENT METRICS CONTEXT:
{ctx}

Respond with STRICT JSON only, no prose, in this schema:
{{
  "diagnosis": "<one paragraph root-cause hypothesis>",
  "severity": "low|medium|high|critical",
  "confidence": <float 0..1>,
  "remediation_steps": [
    {{
      "title": "<short step label>",
      "command": "<single shell command, or empty string if none>",
      "rationale": "<why this helps>",
      "risk": "safe|low|medium|high"
    }}
  ],
  "human_review_required": <bool>
}}
Only propose commands that are safe, non-destructive, and reversible.
Never propose: deleting system files, formatting disks, downloading/executing
remote scripts, changing passwords, or rebooting the host.
"""


def parse_llm_response(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return None


def command_is_denied(command):
    lowered = command.lower()
    for token in DENY_TOKENS:
        if token in lowered:
            return token
    return None


def command_is_allowed(command):
    if not command.strip():
        return False
    if "|" in command and ("curl" in command.lower() or "wget" in command.lower()):
        return False
    for prefix in ALLOW_PREFIXES:
        if command.startswith(prefix):
            if prefix in ("systemctl restart ", "systemctl reload ", "docker restart ", "docker start "):
                target = command.split(None, 2)[-1].strip()
                return target in ALLOWED_SERVICES
            return True
    return False


def validate_plan(plan):
    steps = plan.get("remediation_steps", [])
    validated = []
    for step in steps:
        command = step.get("command", "").strip()
        if not command:
            validated.append({**step, "auto_applicable": False, "safety": "no-op"})
            continue
        denied = command_is_denied(command)
        if denied:
            validated.append({
                **step, "auto_applicable": False,
                "safety": f"DENIED (contains '{denied}')",
            })
            continue
        if command_is_allowed(command):
            validated.append({**step, "auto_applicable": True, "safety": "allowed"})
        else:
            validated.append({
                **step, "auto_applicable": False,
                "safety": "needs human review (not on allow-list)",
            })
    return validated


def run_command(command):
    logger.info(f"Applying safe remediation: {command}")
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[:2000],
        "stderr": result.stderr[:2000],
    }


def write_report(plan, validated, mode, anomaly_report):
    os.makedirs(REPORT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "generated_at": datetime.now().isoformat(),
        "source_anomaly": anomaly_report,
        "diagnosis": plan.get("diagnosis"),
        "severity": plan.get("severity"),
        "confidence": plan.get("confidence"),
        "human_review_required": plan.get("human_review_required", True),
        "mode": mode,
        "steps": validated,
    }
    path = os.path.join(REPORT_DIR, f"remediation_{ts}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"Remediation report written to {path}")
    return path, report


def post_to_alertmanager(report, webhook_url):
    if not webhook_url:
        return
    payload = json.dumps({
        "text": (
            f"[ML Fix Engine] {report.get('severity', 'unknown').upper()} anomaly\n"
            f"Diagnosis: {report.get('diagnosis')}\n"
            f"Human review required: {report.get('human_review_required')}\n"
            f"Report: {report.get('generated_at')}"
        )
    }).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        logger.info("Posted remediation summary to Alertmanager webhook")
    except Exception as e:
        logger.warning(f"Failed to post to Alertmanager: {e}")


def collect_metrics_context(samples=10):
    metrics_dir = "/var/lib/ml-anomaly/metrics"
    if not os.path.isdir(metrics_dir):
        return []
    files = sorted((f for f in os.listdir(metrics_dir) if f.endswith(".json")),
                   reverse=True)[:samples]
    ctx = []
    for fn in files:
        try:
            with open(os.path.join(metrics_dir, fn)) as f:
                ctx.append(json.load(f))
        except Exception:
            continue
    return ctx


def main():
    parser = argparse.ArgumentParser(description="ML fix engine: diagnose and remediate anomalies with a free local LLM")
    parser.add_argument("--anomaly-report", help="Path to anomaly JSON (defaults to latest)")
    parser.add_argument("--mode", choices=["report", "apply", "dry-run"], default="report")
    parser.add_argument("--approval", default=os.environ.get("ML_FIX_APPROVAL_FILE"),
                        help="Path to an approval file required for --mode apply (safety gate)")
    parser.add_argument("--alertmanager-webhook", default=os.environ.get("ML_FIX_WEBHOOK", ""))
    args = parser.parse_args()

    report = load_anomaly_report(args.anomaly_report)
    if not report:
        logger.error("No anomaly report found. Run anomaly_detector.py first.")
        sys.exit(2)

    if not report.get("is_anomaly"):
        logger.info("No anomaly detected — fix engine has nothing to do.")
        sys.exit(0)

    # Fail fast for apply mode if no authorization is present (before any LLM call).
    if args.mode == "apply":
        approval = args.approval or os.environ.get("ML_FIX_APPROVAL_FILE")
        if not approval or not os.path.isfile(approval):
            logger.error(
                "apply mode requires an explicit approval file (--approval FILE or "
                "ML_FIX_APPROVAL_FILE). Refusing to auto-apply fixes without authorization."
            )
            sys.exit(5)
        try:
            with open(approval) as f:
                approver = (f.read().strip() or "unknown").replace("\n", " ")
        except OSError:
            approver = "unknown"
        logger.info(f"Apply authorized by approval file: {approval} (approver: {approver})")

    provider = providers.get_provider()
    if not provider:
        logger.error("No free LLM provider available (install/start Ollama).")
        sys.exit(3)

    logger.info(f"Querying free model '{provider.model}' for remediation plan...")
    metrics_context = collect_metrics_context()
    prompt = build_prompt(report, metrics_context)
    raw = provider.generate(prompt, expect_json=True)
    plan = parse_llm_response(raw)

    if not plan or "remediation_steps" not in plan:
        logger.error("LLM did not return a valid remediation plan.")
        sys.exit(4)

    validated = validate_plan(plan)
    report_path, report_obj = write_report(plan, validated, args.mode, report)

    if args.mode == "dry-run":
        print("\n=== Remediation plan (DRY RUN) ===")
        for i, step in enumerate(validated, 1):
            print(f"{i}. [{step.get('safety')}] {step.get('title')}")
            if step.get("command"):
                print(f"   $ {step['command']}")
        post_to_alertmanager(report_obj, args.alertmanager_webhook)
        sys.exit(0)

    if args.mode == "apply":
        approval = args.approval or os.environ.get("ML_FIX_APPROVAL_FILE")
        if not approval or not os.path.isfile(approval):
            logger.error(
                "apply mode requires an explicit approval file (--approval FILE or "
                "ML_FIX_APPROVAL_FILE). Refusing to auto-apply fixes without authorization."
            )
            sys.exit(5)
        try:
            with open(approval) as f:
                approver = (f.read().strip() or "unknown").replace("\n", " ")
        except OSError:
            approver = "unknown"
        logger.info(f"Apply authorized by approval file: {approval} (approver: {approver})")
        applied = 0
        for step in validated:
            if step.get("auto_applicable"):
                logger.info(f"Applying approved fix: {step['command']}")
                outcome = run_command(step["command"])
                step["outcome"] = outcome
                log_to_audit(
                    f"APPLIED step='{step.get('title')}' cmd='{step['command']}' "
                    f"rc={outcome.get('returncode')} approver='{approver}'"
                )
                applied += 1
        logger.info(f"Applied {applied} safe remediation command(s) (authorized by {approver}).")
        with open(report_path, "w") as f:
            json.dump(report_obj, f, indent=2)

    post_to_alertmanager(report_obj, args.alertmanager_webhook)
    logger.info("Fix engine complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
