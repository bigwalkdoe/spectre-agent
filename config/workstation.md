# Workstation Configuration

- **OS**: Fedora Linux
- **Shell**: Bash
- **Editor**: OpenCode (Zen-compatible agentic coding environment)
- **Container Runtime**: Podman (alias `docker` if configured)
- **Orchestration**: Docker Compose (via podman-compose or docker-compose)
- **LLM Runtime**: Ollama (local), Azure OpenAI (cloud)
- **Package Managers**: pip, npm, rpm-ostree, dnf

## Environment Variables

Store in `~/.spectre/.env` (do not commit — file is in `.gitignore`). Key variables:

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `OPENAI_API_KEY`
- `OLLAMA_HOST` (default `http://localhost:11434`)
- `DATABASE_URL`
- `REDIS_URL`

Secrets in `docker-compose.yml` should use `${VAR:?error}` syntax referencing `.env` — never hardcode passwords.
