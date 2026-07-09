# Template: Kubernetes

Production-grade Kubernetes manifests.

## Contents

- `deployment.yml` — stateless deployment with probes and resource limits
- `service.yml` — ClusterIP service
- `ingress.yml` — TLS ingress with cert-manager
- `configmap.yml` — non-sensitive config
- `secret.yml` — secret template (fill in with sealed secret or external secret)
- `hpa.yml` — horizontal pod autoscaling
- `pdb.yml` — pod disruption budget
- `network-policy.yml` — network isolation
