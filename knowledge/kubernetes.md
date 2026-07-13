# Kubernetes Reference

Spectre Agent reads cluster state via `kubectl`:

- `kubectl get pods -A -o json` — security contexts, hostPath mounts
- `kubectl get networkpolicies -A -o json` — network segmentation

Look for: `securityContext.privileged`, `runAsNonRoot`, `runAsUser`, `hostPath`, and the presence of `NetworkPolicy` objects. Pair with Pod Security Admission (restricted) at the namespace level.
