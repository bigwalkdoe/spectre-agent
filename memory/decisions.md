# Decisions

## 2026-07-09 — Spectre Foundation

- Established Spectre as the primary workstation agent for the Modelink ecosystem.
- Directory structure: `~/.spectre/` with config/, playbooks/, knowledge/, templates/, scripts/, memory/, logs/.
- AGENTS.md as the single source of truth for Spectre's operating instructions.
- Config files cover workstation, coding, architecture, security, git, testing, deployment, style.
- Playbooks define repeatable workflows: create-service, create-api, debug, review, refactor, documentation, release, incident.
- Knowledge base captures stack expertise: modelink, fastapi, nextjs, postgres, redis, ollama, podman, linux.
- All code changes should follow the lifecycle: Understand → Plan → Inspect → Implement → Test → Validate → Document → Report.
