# Spectre

AI Engineering Operating System for the Modelink ecosystem.

## LLM Gateway Service

This repository includes a production-ready LLM Gateway service providing central routing, load balancing, failover, and cost tracking for multiple LLM providers.

### Gateway Features

**Core Functionality**
- **Multi-Provider Support**: OpenAI, Azure OpenAI, and Ollama
- **Intelligent Routing**: Automatic provider selection based on model
- **Load Balancing**: Distribute requests across providers
- **Failover**: Automatic fallback on provider failures
- **Cost Tracking**: Monitor token usage and costs

**Security & Reliability**
- **API Key Authentication**: Secure endpoint protection with X-API-Key headers
- **Rate Limiting**: Redis-based rate limiting with sliding window algorithm
- **Security Headers**: Comprehensive web security headers (CSP, HSTS, X-Frame-Options, etc.)
- **Request Validation**: Pydantic-based input validation and sanitization
- **Structured Logging**: Production-ready logging with structlog
- **Health Checks**: `/health` and `/ready` endpoints for monitoring

**Developer Experience**
- **Docker Support**: Multi-stage Docker builds for production
- **Docker Compose**: Easy local development with Redis
- **Comprehensive Tests**: 83% test coverage with 36 tests
- **Type Safety**: Full mypy type checking
- **Code Quality**: Ruff linting and formatting
- **Configuration**: Environment-based configuration with .env support

### Gateway Quick Start

1. **Navigate to gateway service**
```bash
cd backend/gateway
```

2. **Set up environment**
```bash
cp .env.example .env
# Edit .env with your configuration
```

3. **Install dependencies**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

4. **Start Redis**
```bash
docker-compose -f docker/docker-compose.yml up -d redis
```

5. **Run the gateway**
```bash
uvicorn gateway.main:app --reload --host 0.0.0.0 --port 8000
```

### Gateway API Usage

```bash
# Health check
curl http://localhost:8000/health

# Chat completion with authentication
curl -X POST http://localhost:8000/api/v1/completions \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Spectre Structure

```
~/.spectre/
├── AGENTS.md            # Master operating instructions
├── config/              # Workstation and code standards
├── playbooks/           # Repeatable workflows
├── knowledge/           # Stack expertise reference
├── templates/           # Project and code templates
├── scripts/             # Automation scripts
├── memory/              # Persistent memory (decisions, architecture, changelog)
└── logs/                # Activity logs
```

## Usage

Spectre is a config layer for agentic coding environments. Point your agent to `~/.spectre/AGENTS.md` as its instructions, and it will have full context on how to operate within the Modelink ecosystem.

## Gateway Documentation

For detailed LLM Gateway documentation including configuration, security features, deployment, and troubleshooting, see the [backend/gateway/](backend/gateway/) directory.
