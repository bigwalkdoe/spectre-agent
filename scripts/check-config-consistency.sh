#!/bin/bash
# Checks that monitoring configuration refers to things that actually exist.
#
# The job this replaces ("Configuration Drift Detection") globbed the config
# files and echoed "OK" for each one it found. It could not fail, so a scrape
# target naming a service that no longer exists, or an nginx proxy pointing at a
# misspelled upstream, was only discovered at container start.
#
# The failure this exists to catch: a name in prometheus.yml or the dashboard's
# nginx proxy that is not a service in docker-compose.monitoring.yml. Those
# resolve to a permanently-down target, which looks like a Prometheus problem
# rather than a typo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE="$PROJECT_ROOT/docker-compose.monitoring.yml"
PROMETHEUS="$PROJECT_ROOT/prometheus/prometheus.yml"
NGINX_CONF="$PROJECT_ROOT/web-dashboard/nginx.conf"
ALERTMANAGER="$PROJECT_ROOT/prometheus/alertmanager.yml"
RULES="$PROJECT_ROOT/prometheus/alert_rules.yml"
EXPORTER="$PROJECT_ROOT/prometheus/business-metrics-exporter.sh"
BACKUP_DB="$PROJECT_ROOT/scripts/backups/backup-databases.sh"

# Hosts that are legitimately not compose service names.
ALLOWED_HOSTS="localhost 127.0.0.1 ::1 host.docker.internal"

fail=0

# Service names from the `services:` block only. A plain `^  name:$` match would
# also pick up the network and volume names further down the file, letting a
# typo that happens to collide with a volume name pass.
services=$(
    awk '
        /^services:/ { in_services = 1; next }
        /^[a-zA-Z]/   { in_services = 0 }
        in_services && /^  [a-zA-Z0-9._-]+:[[:space:]]*$/ {
            name = $0
            sub(/^  /, "", name)
            sub(/:[[:space:]]*$/, "", name)
            print name
        }
    ' "$COMPOSE" | sort -u
)

if [ -z "$services" ]; then
    echo "ERROR: could not read any service names from $COMPOSE" >&2
    exit 1
fi

# Host portion of every scrape target and of every relabel replacement.
# Every host named by a scrape target or a blackbox `replacement`, in both the
# inline form (targets: ['a', 'b']) and the block form:
#
#   targets:
#     - 'alertmanager:9093'
#
# The block form is how all six blackbox TCP probes are written, and the earlier
# regex only matched the inline form, so those targets were never checked. That
# is the same set of targets that produced eight false UptimeCheckFailed alerts
# when they pointed at host.docker.internal.
#
# The trailing `|| true` matters: grep exits 1 on no match, and under
# `set -o pipefail` that aborted the whole gate with no message, so an empty or
# restructured config produced a silent non-zero exit instead of a diagnosis.
referenced_hosts=$(
    awk '
        /targets:[[:space:]]*\[/ {
            line = $0
            sub(/.*targets:[[:space:]]*\[/, "", line)
            gsub(/[]\047]/, "", line)
            gsub(/[[:space:]]/, "", line)
            n = split(line, item, ",")
            for (i = 1; i <= n; i++) if (item[i] != "") print item[i]
        }
        /replacement:[[:space:]]*/ {
            line = $0
            sub(/.*replacement:[[:space:]]*/, "", line)
            gsub(/[\047]/, "", line)
            gsub(/[[:space:]]/, "", line)
            if (line != "") print line
        }
        /targets:[[:space:]]*$/ { inblock = 1; next }
        inblock && /^[[:space:]]*$/ { next }
        inblock && /^[[:space:]]*-[[:space:]]*/ {
            line = $0
            sub(/^[[:space:]]*-[[:space:]]*/, "", line)
            gsub(/[\047]/, "", line)
            gsub(/[[:space:]]/, "", line)
            if (line != "") print line
            next
        }
        inblock { inblock = 0 }
    ' "$PROMETHEUS" | sort -u || true
)

check_host() {
    local host="$1" source="$2"
    for allowed in $ALLOWED_HOSTS; do
        [ "$host" = "$allowed" ] && return 0
    done
    if ! printf '%s\n' "$services" | grep -qx "$host"; then
        echo "ERROR: $source refers to '$host', which is not a service in $(basename "$COMPOSE")" >&2
        fail=1
    fi
}

# Only host:port targets are service references. A bare public IP (1.1.1.1) or a
# URL (https://api.github.com) is an intentional external blackbox probe, not a
# misspelled service, and cannot be validated against docker-compose. Anything
# carrying an explicit port must name a service, or it is a typo that resolves to
# a permanently-down target.
for target in $referenced_hosts; do
    case "$target" in
        *://*) continue ;;   # external HTTP/ICMP/DNS probe
    esac
    if printf '%s' "$target" | grep -q ':'; then
        check_host "${target%%:*}" "prometheus.yml"
    fi
done

# The dashboard reaches Prometheus through this proxy, so a misspelled upstream
# breaks every dashboard query while Prometheus itself looks healthy.
if [ -f "$NGINX_CONF" ]; then
    nginx_upstreams=$(
        grep -oE 'proxy_pass[[:space:]]+https?://[^/]+' "$NGINX_CONF" \
            | sed -E 's#.*https?://([^/:]+).*#\1#' | sort -u
    )
    for host in $nginx_upstreams; do
        check_host "$host" "web-dashboard/nginx.conf"
    done
fi

# Every service's memory limit, read with the same `services:`-scoped awk pass so
# that a block cannot be attributed to a network or volume.
#
# This check exists because a `deploy:` block placed *before* the service it
# documents is still valid YAML: at four-space indentation it silently attaches
# to the preceding service instead. All eleven limits in this file were shifted by
# one -- Grafana's 1 GiB was applied to Prometheus, cAdvisor's 256 MiB to
# node-exporter, and web-dashboard's limit ended up on the `monitoring` network.
# `docker compose config` reported the file as valid, so nothing caught it. The
# table below pins the intended limit per service; changing one on purpose means
# changing it here too.
expected_limits="prometheus:none
grafana:1g
alertmanager:512m
node-exporter:256m
cadvisor:256m
redis-exporter:512m
postgres-exporter:128m
redis:128m
postgres:512m
blackbox-exporter:1g
web-dashboard:128m"

actual_limits=$(
    awk '
        /^services:/ { in_services = 1; next }
        /^[a-zA-Z]/   { in_services = 0 }
        !in_services  { next }
        /^  [a-zA-Z0-9._-]+:[[:space:]]*$/ {
            if (name != "") printf "%s:%s\n", name, (limit == "" ? "none" : limit)
            name = $0
            sub(/^  /, "", name); sub(/:[[:space:]]*$/, "", name)
            limit = ""; in_deploy = 0
            next
        }
        /^    deploy:/ { in_deploy = 1; next }
        /^    [a-zA-Z]/ { in_deploy = 0 }
        in_deploy && /^ *memory:/ { limit = $2 }
        END { if (name != "") printf "%s:%s\n", name, (limit == "" ? "none" : limit) }
    ' "$COMPOSE"
)

if [ "$actual_limits" != "$expected_limits" ]; then
    echo "ERROR: memory limits do not match the intended per-service table." >&2
    echo "  A 'deploy:' block written before the service it documents attaches to" >&2
    echo "  the previous service instead. Diff (expected vs actual):" >&2
    diff <(printf '%s\n' "$expected_limits") <(printf '%s\n' "$actual_limits") >&2 || true
    fail=1
fi

# A resource limit under a network or volume is always wrong: those accept none,
# and Compose ignores the stray key without complaining. Only limit-bearing keys
# are flagged, since `driver` and `name` are legitimate there.
stray=$(awk '
    /^services:/ { in_services = 1; next }
    /^[a-zA-Z]/   { in_services = 0 }
    !in_services && /^  (monitoring|prometheus-data|grafana-data|alertmanager-data|postgres-data):/ { in_net = 1; next }
    in_net && /^    (deploy|mem_limit|cpus|mem_reservation):/ { print "  - " $1 " attached to a network or volume" }
' "$COMPOSE")
  if [ -n "$stray" ]; then
      echo "ERROR: keys that cannot belong to a network or volume:" >&2
      printf '%s\n' "$stray" >&2
      fail=1
  fi

  # alertmanager.yml routes and inhibition rules are matched by alertname, and
  # Alertmanager does not validate those against any rule file. An alertname that
  # is spelled wrong, or a rule that was never written, produces a route that
  # silently never matches. That is how alertmanager.yml shipped a dedicated
  # Watchdog receiver with no Watchdog alert behind it, and two inhibition rules
  # naming InstanceDown/InstanceHealthcheck, neither of which has ever existed.
  alertnames=$(grep -oE '^[[:space:]]*-[[:space:]]*alert:[[:space:]]*.+$' "$RULES" \
      | sed 's/.*alert:[[:space:]]*//' | tr -d "'" | sed 's/[[:space:]]*$//' | sort -u || true)

  # Extracted with plain grep rather than a YAML parser on purpose: PyYAML is not
  # installed in the project's test venv, and CI only installs shellcheck, so a
  # python3 dependency here fails the build. Checking *every* alertname in the
  # file is also stricter than walking the route tree, and receivers use no other
  # alertname/receiver keys, so a full parse buys nothing.
  route_names=$(grep -oE "^[[:space:]]*alertname:[[:space:]]*'?[A-Za-z0-9_-]+" "$ALERTMANAGER" \
      | sed "s/.*alertname:[[:space:]]*'\{0,1\}//" | sort -u)
  recv_names=$(grep -oE "^[[:space:]]*receiver:[[:space:]]*'?[A-Za-z0-9_-]+" "$ALERTMANAGER" \
      | sed "s/.*receiver:[[:space:]]*'\{0,1\}//" | sort -u)
  recv_defined=$(grep -oE "^[[:space:]]*-[[:space:]]*name:[[:space:]]*'?[A-Za-z0-9_-]+" "$ALERTMANAGER" \
      | sed "s/.*name:[[:space:]]*'\{0,1\}//" | sort -u)

  # A hardcoded floor, so a broken extraction is itself a failure rather than a
  # vacuous pass. This is the failure mode that let a regex with a required
  # literal bracket verify nothing while reporting success.
  if [ "$(printf '%s\n' "$alertnames" | grep -c .)" -lt 1 ]; then
      echo "ERROR: no alert rules found in $(basename "$RULES")." >&2
      echo "  Every alertmanager alertname reference is now dangling." >&2
      fail=1
  fi
  if [ "$(printf '%s\n' "$route_names" | grep -c .)" -lt 1 ] \
      || [ "$(printf '%s\n' "$recv_names" | grep -c .)" -lt 1 ] \
      || [ "$(printf '%s\n' "$recv_defined" | grep -c .)" -lt 1 ]; then
      echo "ERROR: could not extract alertnames/receivers from alertmanager.yml." >&2
      echo "  Expected at least one of each. Refusing to pass on a partial check." >&2
      fail=1
  fi

  for name in $route_names; do
      if ! printf '%s\n' "$alertnames" | grep -qx "$name"; then
          echo "ERROR: alertmanager.yml references alertname '$name', but no rule in" >&2
          echo "  alert_rules.yml defines it. The route or inhibition can never match." >&2
          fail=1
      fi
  done

  for receiver in $recv_names; do
      if ! printf '%s\n' "$recv_defined" | grep -qx "$receiver"; then
          echo "ERROR: a route targets receiver '$receiver', which is not defined." >&2
          fail=1
      fi
  done

  # Alertmanager defaults to uid 65534 (nobody). The secrets directory is 0700
  # owned by the host user, so the container cannot traverse it and every
  # notification fails with "permission denied" -- while /-/ready returns 200 and
  # the stack looks healthy, because the failure only happens at send time.
  if grep -q 'alertmanager-secrets:/etc/alertmanager/secrets' "$COMPOSE" \
      && ! awk '/^  alertmanager:/{f=1; next} f&&/^  [a-zA-Z]/{f=0} f&&/^[[:space:]]*user:/{print}' "$COMPOSE" | grep -q .; then
      echo "ERROR: alertmanager bind-mounts a 0700 secrets directory but sets no" >&2
      echo "  'user:'. The image defaults to uid 65534 (nobody) and cannot read" >&2
      echo "  the secrets; notifications fail at send time only." >&2
      fail=1
  fi

  # `{{ .GeneratorURL }}` is a field of an alert, not of the alert group. In a
  # single-value field such as title_link it fails template execution, and the
  # damage is not confined to that field: color, text and fallback all rendered
  # empty while only the title survived, so Slack showed a bare heading with no
  # severity colour and no body. It is only valid inside {{ range .Alerts }}.
  # Omitting title_link entirely is the safe default; Alertmanager then links to
  # its own alert page.
  bad_genurl=$(
      awk '
          /^[[:space:]]*(title|title_link|pretext):/ && /\{\{[^}]*\.GeneratorURL/ {
              line = $0
              sub(/^[[:space:]]*/, "", line)
              print "    " line
          }
      ' "$ALERTMANAGER" || true
  )
  if [ -n "$bad_genurl" ]; then
      echo "ERROR: .GeneratorURL used outside 'range .Alerts'. It only exists on an" >&2
      echo "  alert, not on the group, and the template error empties color/text too:" >&2
      printf '%s\n' "$bad_genurl" >&2
      fail=1
  fi

  # Every bind-mounted file needs a shared SELinux label (`:z`). Without it the
  # host file carries whatever category it was created with while each container
  # gets its own MCS pair, so the mount is unreadable -- even to root -- and the
  # container crash-loops on "permission denied" reading its own config. Because
  # the label is per-inode, any rewrite of the file (git checkout, sed -i) resets
  # it, so this breaks on an ordinary pull rather than at deploy time.
  unlabelled=$(
      awk '
          /^services:/ { insvc = 1; next }
          /^[a-zA-Z]/ { insvc = 0 }
          insvc && /^  [a-zA-Z0-9_-]+:[[:space:]]*$/ {
              service = $1; sub(/:$/, "", service); next
          }
          insvc && /^[[:space:]]*-[[:space:]]*\.\// {
              mount = $0
              sub(/^[[:space:]]*-[[:space:]]*/, "", mount)
              n = split(mount, part, ":")
              opts = (n >= 3) ? part[n] : ""
              if (opts !~ /(^|,)(z|Z)(,|$)/) print "    " service ": " mount
          }
      ' "$COMPOSE" || true
  )
  if [ -n "$unlabelled" ]; then
      echo "ERROR: bind mounts without a shared SELinux label (:z). These are" >&2
      echo "  unreadable inside the container under SELinux, and any rewrite of" >&2
      echo "  the file resets the label:" >&2
      printf '%s\n' "$unlabelled" >&2
      fail=1
  fi

  # The exporter and the backup script must agree on where the backup markers
  # live. They are separate files, each with its own default, and a mismatch is
  # invisible: the exporter reports 0 for last success, BackupStale fires
  # forever, and nothing says the two are looking in different directories. The
  # default also has to be writable by whoever runs the cron jobs -- /var/lib is
  # root-only, so a non-root exporter could never read a root-written marker.
  if [ -f "$EXPORTER" ] && [ -f "$BACKUP_DB" ]; then
      exporter_state=$(grep -oE 'BACKUP_STATE_DIR:-[^}]+' "$EXPORTER" | head -1 | sed 's/.*BACKUP_STATE_DIR:-//')
      backup_state=$(grep -oE 'BACKUP_STATE_DIR:-[^}]+' "$BACKUP_DB" | head -1 | sed 's/.*BACKUP_STATE_DIR:-//')
      if [ -z "$exporter_state" ] || [ -z "$backup_state" ]; then
          echo "ERROR: could not read the BACKUP_STATE_DIR default from the exporter" >&2
          echo "  or backup-databases.sh." >&2
          fail=1
      elif [ "$exporter_state" != "$backup_state" ]; then
          echo "ERROR: BACKUP_STATE_DIR defaults disagree." >&2
          echo "  exporter reads           : $exporter_state" >&2
          echo "  backup-databases.sh writes: $backup_state" >&2
          echo "  The exporter would report last-success 0 forever and BackupStale" >&2
          echo "  would fire regardless of whether backups succeed." >&2
          fail=1
      elif [ "$exporter_state" = "/var/lib/backup-state" ]; then
          echo "ERROR: BACKUP_STATE_DIR defaults to /var/lib/backup-state, which is" >&2
          echo "  root-only. Backups run from cron as a normal user, so the marker" >&2
          echo "  cannot be written or read and the metric stays 0." >&2
          fail=1
      fi
  fi

  if [ "$fail" -ne 0 ]; then
      echo "config consistency check FAILED" >&2
      exit 1
  fi

  echo "config consistency OK: $(printf '%s\n' "$referenced_hosts" | grep -c .) prometheus target host(s) and $(printf '%s\n' "${nginx_upstreams:-}" | grep -c . || echo 0) nginx upstream(s) all resolve to compose services; $(printf '%s\n' "$actual_limits" | grep -c .) service memory limit(s) on the intended service; $(printf '%s\n' "$route_names" | grep -c .) alertmanager alertname reference(s) and $(printf '%s\n' "$recv_names" | grep -c .) receiver target(s) all exist"
