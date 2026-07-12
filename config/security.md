# Security Baselines

Spectre Agent measures hosts against these baselines. A finding means the host diverges from the baseline.

## Linux Hardening
- SSH `PermitRootLogin no`
- SSH `PasswordAuthentication no`
- Unattended security updates enabled
- Core dumps disabled (`* hard core 0`)
- GRUB boot password set
- Host firewall active

## Kubernetes
- No privileged containers
- All containers `runAsNonRoot=true`
- No `hostPath` mounts in untrusted workloads
- At least one default-deny `NetworkPolicy` per namespace

## Firewall
- A host firewall (ufw/nftables/iptables) is active
- No sensitive services (22, 23, 3389, 3306, 5432, 6379, 9200, 11211) exposed to `0.0.0.0`

## SSH Monitoring
- Fewer than 10 failed-password attempts per source IP in the sampled window
- Fewer than 5 unknown-user probes per source IP

## Container Security
- Images run as a non-root USER
- No `:latest` or untagged image references
- No privileged containers, no added Linux capabilities
