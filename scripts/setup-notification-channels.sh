#!/bin/bash
# Configure Alertmanager notification channels and prove delivery works.
#
# This script used to fail. It resolved the repository root as "$SCRIPT_DIR/../..",
# which is the parent of the repository, so every secret was written to
# <parent>/prometheus/alertmanager-secrets -- a directory mkdir -p invented outside
# the repository, where the Compose bind mount cannot see it and no .gitignore
# covers it. It then tried to "apply" configuration with `docker cp` into
# alertmanager.yml and `sed -i` on prometheus.yml, both of which are read-only
# bind mounts, so it aborted on a read-only filesystem after writing the caller's
# password to the wrong place. It also printed the wrong Prometheus port.
#
# Nothing needs copying into a container here: both files are bind-mounted from
# the repository and take effect on restart.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ALERTMANAGER_CONTAINER="${ALERTMANAGER_CONTAINER:-alertmanager}"
PROMETHEUS_CONTAINER="${PROMETHEUS_CONTAINER:-prometheus}"
SECRETS_DIR="${SECRETS_DIR:-$REPO_ROOT/prometheus/alertmanager-secrets}"
AM_CONFIG="/etc/alertmanager/alertmanager.yml"
READY_TIMEOUT="${READY_TIMEOUT:-60}"
TEST_TIMEOUT="${TEST_TIMEOUT:-90}"
RUN_TEST=0

usage() {
    cat <<'EOF'
Usage: setup-notification-channels.sh [--test] [--help]

Writes notification credentials from the environment into
prometheus/alertmanager-secrets/ (mode 0600), restarts Alertmanager, and verifies
that it loaded the configuration.

  --test   After configuring, post a synthetic critical alert and report whether
           each receiver actually accepted it. This is the only step that proves
           delivery works: `amtool check-config` succeeds even when every secret
           file is missing, because *_file options are not existence-checked.

Environment:
  SLACK_WEBHOOK_URL      Slack incoming webhook URL (the only channel)

An existing secret file is retained when the variable is unset, so the script can
be re-run without discarding a working webhook.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --test) RUN_TEST=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

fail=0
note() { printf '  %s\n' "$*"; }
warn() { printf '  WARNING: %s\n' "$*" >&2; fail=1; }
err()  { printf '  ERROR: %s\n' "$*" >&2; fail=1; }

# Refuse to run if the repository root looks wrong, rather than inventing a
# directory outside the repository and writing credentials into it.
if [ ! -f "$REPO_ROOT/prometheus/alertmanager.yml" ]; then
    echo "ERROR: resolved repository root '$REPO_ROOT' has no prometheus/alertmanager.yml." >&2
    echo "  Expected the script to live in <repo>/scripts/." >&2
    exit 1
fi

if ! docker inspect "$ALERTMANAGER_CONTAINER" >/dev/null 2>&1; then
    echo "ERROR: container '$ALERTMANAGER_CONTAINER' not found. Start the stack first:" >&2
    echo "  docker compose -f docker-compose.monitoring.yml up -d" >&2
    exit 1
fi

echo "Writing notification secrets to $SECRETS_DIR"
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

write_secret() {
    local name="$1" value="${2:-}" path="$SECRETS_DIR/$1"

    if [ -z "$value" ]; then
        if [ -s "$path" ]; then
            note "keep   $name (no value supplied, existing file retained)"
        else
            note "SKIP   $name (no value supplied)"
        fi
        return 0
    fi

    printf '%s' "$value" > "$path"
    chmod 600 "$path"
    note "write  $name"
}

write_secret slack_webhook_url "${SLACK_WEBHOOK_URL:-}"

# Slack is the only channel, so its absence is the only thing that can break
# delivery. Anything else in the config is a formatting concern.
webhook_configured=0
[ -s "$SECRETS_DIR/slack_webhook_url" ] && webhook_configured=1

if [ "$webhook_configured" -eq 0 ]; then
    warn "no Slack webhook configured; every alert will fail to deliver"
    note "Create an incoming webhook in Slack, then:"
    note "  SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...' \\"
    note "    $0"
fi

# Check readability from inside the container. A mode 0700 secrets directory owned
# by the host user is invisible to the image's default uid 65534 (nobody), and
# Alertmanager reports that only when it tries to deliver -- so config loading and
# /-/ready both succeed while every notification fails. A host-side test cannot
# see this, which is exactly why it shipped.
if [ "$webhook_configured" -eq 1 ]; then
    echo
    echo "Checking that the container can read the secrets..."
    if docker exec "$ALERTMANAGER_CONTAINER" \
        sh -c "head -c1 /etc/alertmanager/secrets/slack_webhook_url >/dev/null 2>&1"; then
        note "readable in container: slack_webhook_url"
    else
        err "container cannot read slack_webhook_url (uid $(docker exec "$ALERTMANAGER_CONTAINER" id -u 2>/dev/null || echo '?'), dir mode $(stat -c '%a' "$SECRETS_DIR") owned by $(stat -c '%U' "$SECRETS_DIR"))"
        note "Set 'user:' on the alertmanager service in docker-compose.monitoring.yml,"
        note "or relax the directory mode. Do not assume a healthy Alertmanager means delivery works."
    fi
fi

# Validate before restarting, not after. The previous version restarted first and
# only then checked, so a bad config was already live by the time it complained.
echo
echo "Validating Alertmanager configuration..."
if docker exec "$ALERTMANAGER_CONTAINER" amtool check-config "$AM_CONFIG" >/dev/null 2>&1; then
    note "config is syntactically valid"
    note "note: this does not check that the secret files exist"
else
    err "Alertmanager rejected the configuration:"
    docker exec "$ALERTMANAGER_CONTAINER" amtool check-config "$AM_CONFIG" >&2 || true
    exit 1
fi

echo
echo "Restarting Alertmanager to load the new secrets..."
before_config=$(docker exec "$ALERTMANAGER_CONTAINER" \
    sha256sum "$AM_CONFIG" 2>/dev/null | cut -d' ' -f1 || true)
docker restart "$ALERTMANAGER_CONTAINER" >/dev/null

# Poll for readiness instead of sleeping a fixed ten seconds.
ready=0
for _ in $(seq 1 "$READY_TIMEOUT"); do
    if docker exec "$ALERTMANAGER_CONTAINER" \
        wget -qO- http://localhost:9093/-/ready >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 1
done

if [ "$ready" -ne 1 ]; then
    err "Alertmanager did not become ready within ${READY_TIMEOUT}s. Recent logs:"
    docker logs --tail 20 "$ALERTMANAGER_CONTAINER" >&2 || true
    exit 1
fi
note "ready"

# Confirm it reloaded rather than silently running a stale config.
after_config=$(docker exec "$ALERTMANAGER_CONTAINER" \
    sha256sum "$AM_CONFIG" 2>/dev/null | cut -d' ' -f1 || true)
if [ -n "$after_config" ] && [ "$after_config" != "$before_config" ]; then
    note "configuration file changed on disk and was re-read"
fi
loaded=$(docker exec "$ALERTMANAGER_CONTAINER" \
    wget -qO- http://localhost:9093/api/v2/status 2>/dev/null || true)
if printf '%s' "$loaded" | grep -q '"cluster"'; then
    note "config loaded and cluster is ready"
else
    warn "could not read status from the Alertmanager API"
fi

# Prometheus must actually be pointed at Alertmanager. This used to be "fixed" with
# sed -i against a read-only bind mount, which could only ever fail.
if docker inspect "$PROMETHEUS_CONTAINER" >/dev/null 2>&1; then
    if docker exec "$PROMETHEUS_CONTAINER" \
        grep -q "alertmanager:9093" /etc/prometheus/prometheus.yml 2>/dev/null; then
        note "Prometheus is configured to send to alertmanager:9093"
    else
        warn "Prometheus is not pointed at Alertmanager; add it under 'alerting:' in prometheus/prometheus.yml"
    fi
fi

if [ "$RUN_TEST" -eq 1 ]; then
    echo
    echo "Posting a synthetic critical alert to verify delivery..."

    # Two distinct signals, and the earlier one is the useful one:
    #   WARN  "Notify attempt failed, will retry later"  (retry_stage.go) -- first
    #         failed attempt, visible within ~group_wait
    #   ERROR "Notify for alerts failed"                (dispatch.go)   -- only
    #         after the retry budget is exhausted, which takes minutes
    # Waiting for the ERROR alone makes a working test look like a pass.
    #
    # Match on the critical receiver as well as the test alertname: the aggrGroup
    # field groups on severity, so the alertname is not always the discriminating
    # token in the line.
    count_test_failures() {
        docker logs "$ALERTMANAGER_CONTAINER" 2>&1 \
            | grep -E 'Notify attempt failed|Notify for alerts failed' \
            | grep 'receiver=critical-receiver' \
            | grep -c "$TEST_ALERTNAME" || true
    }

    # A unique instance label per run. Re-posting an identical still-active alert
    # is idempotent, so a second run would generate no new notification attempt
    # and would report success without testing anything.
    TEST_ALERTNAME='NotificationChannelTest'
    instance="setup-script-$(date +%s)"
    # startsAt in the past so it fires at once; endsAt lets it expire by itself.
    # DELETE /api/v2/alerts returns 405 in Alertmanager 0.34, so the previous
    # cleanup step silently did nothing and left the alert active.
    docker exec "$ALERTMANAGER_CONTAINER" wget -qO- --header='Content-Type: application/json' \
        --post-data="[{\"labels\":{\"alertname\":\"$TEST_ALERTNAME\",\"severity\":\"critical\",\"instance\":\"$instance\"},\"annotations\":{\"description\":\"Synthetic alert from setup-notification-channels.sh --test. Self-resolving.\"},\"startsAt\":\"$(date -u -d '60 seconds ago' +%Y-%m-%dT%H:%M:%SZ)\",\"endsAt\":\"$(date -u -d '3 minutes' +%Y-%m-%dT%H:%M:%SZ)\"}]" \
        http://localhost:9093/api/v2/alerts >/dev/null 2>&1 || true

    # The POST response body is empty on success, so confirm arrival by reading
    # the alert back rather than trusting the exit status.
    sleep 2
    if docker exec "$ALERTMANAGER_CONTAINER" wget -qO- \
        http://localhost:9093/api/v2/alerts 2>/dev/null | grep -q "$instance"; then
        note "test alert accepted (instance=$instance)"
    else
        err "test alert was not accepted by Alertmanager; delivery is untested"
    fi

    failures_before=$(count_test_failures)

    # group_wait is 30s in alertmanager.yml; allow for it plus scheduling.
    sleep "$TEST_TIMEOUT"
    failures_after=$(count_test_failures)

    if [ "$failures_after" -gt "$failures_before" ]; then
        err "critical-receiver failed to deliver ($((failures_after - failures_before)) failure(s))"
        docker logs "$ALERTMANAGER_CONTAINER" 2>&1 \
            | grep -E 'Notify attempt failed|Notify for alerts failed' \
            | grep 'receiver=critical-receiver' | grep "$TEST_ALERTNAME" \
            | tail -1 | sed 's/.*err=/  err=/' | cut -c1-200 >&2 || true
        note "Delivery is NOT working. See the warnings above."
    elif [ "$webhook_configured" -eq 0 ]; then
        note "no failure logged, but no webhook is configured, so delivery was never attempted"
    else
        note "critical-receiver's Slack integration accepted the alert with no failure logged"
        note "(check the Slack channel to confirm it arrived and looks right)"
    fi

    note "test alert self-resolves via endsAt (DELETE is not supported by Alertmanager 0.34)"
fi

echo
if [ "$fail" -ne 0 ]; then
    echo "Notification channels are INCOMPLETE -- see the warnings above."
    exit 1
fi
echo "Notification channels configured and verified."
echo "  Alertmanager:  http://localhost:9093"
echo "  Prometheus:    http://localhost:9090"
