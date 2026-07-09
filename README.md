# Spectre - Modelink LLM Gateway

A production-ready LLM Gateway service providing central routing, load balancing, failover, and cost tracking for multiple LLM providers.

## Features

### Core Functionality
- **Multi-Provider Support**: OpenAI, Azure OpenAI, and Ollama
- **Intelligent Routing**: Automatic provider selection based on model
- **Load Balancing**: Distribute requests across providers
- **Failover**: Automatic fallback on provider failures
- **Cost Tracking**: Monitor token usage and costs

### Security & Reliability
- **API Key Authentication**: Secure endpoint protection with X-API-Key headers
- **Rate Limiting**: Redis-based rate limiting with sliding window algorithm
- **Security Headers**: Comprehensive web security headers (CSP, HSTS, X-Frame-Options, etc.)
- **Request Validation**: Pydantic-based input validation and sanitization
- **Structured Logging**: Production-ready logging with structlog
- **Health Checks**: `/health` and `/ready` endpoints for monitoring

### Developer Experience
- **Docker Support**: Multi-stage Docker builds for production
- **Docker Compose**: Easy local development with Redis
- **Comprehensive Tests**: 83% test coverage with 36 tests
- **Type Safety**: Full mypy type checking
- **Code Quality**: Ruff linting and formatting
- **Configuration**: Environment-based configuration with .env support

## Quick Start

### Prerequisites
- Python 3.12+
- Redis server (for rate limiting)
- Docker and Docker Compose (optional)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/bigwalkdoe/spectre.git
cd spectre
```

2. **Set up environment**
```bash
cd backend/gateway
cp .env.example .env
# Edit .env with your configuration
```

3. **Install dependencies**
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

4. **Start Redis**
```bash
# Using Docker Compose
docker-compose -f docker/docker-compose.yml up -d redis

# Or start Redis manually
redis-server
```

5. **Run the gateway**
```bash
uvicorn gateway.main:app --reload --host 0.0.0.0 --port 8000
```

### Docker Setup

1. **Build and run with Docker Compose**
```bash
cd backend/gateway
docker-compose -f docker/docker-compose.yml up -d
```

2. **Run with Docker**
```bash
cd backend/gateway
docker build -f docker/Dockerfile -t modelink-gateway .
docker run -p 8000:8000 --env-file .env modelink-gateway
```

## Configuration

### Environment Variables

Create a `.env` file based on `.env.example`:

```bash
# Application Settings
APP_NAME=Modelink Gateway
DEBUG=false
LOG_LEVEL=INFO

# Server Configuration
HOST=0.0.0.0
PORT=8000

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# CORS Configuration
CORS_ORIGINS=http://localhost:3000,http://localhost:8080

# LLM Provider Credentials
OPENAI_API_KEY=your_openai_api_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_KEY=your_azure_openai_api_key_here
OLLAMA_BASE_URL=http://localhost:11434

# Rate Limiting
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW_SECONDS=60

# API Authentication (comma-separated list of valid API keys)
API_KEYS=key1,key2,key3

# Security
ALLOWED_HOSTS=localhost,127.0.0.1
```

## API Usage

### Authentication

All API endpoints (except health checks) require API key authentication:

```bash
curl -X POST http://localhost:8000/api/v1/completions \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "system", "content": "You are helpful"},
      {"role": "user", "content": "Hello!"}
    ],
    "temperature": 0.7,
    "max_tokens": 100
  }'
```

### Endpoints

#### Health Checks
```bash
# Health check
curl http://localhost:8000/health

# Readiness check
curl http://localhost:8000/ready
```

#### List Providers
```bash
curl http://localhost:8000/api/v1/providers
```

#### Chat Completions
```bash
curl -X POST http://localhost:8000/api/v1/completions \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "user", "content": "Explain quantum computing"}
    ]
  }'
```

## Security Features

### API Key Authentication
- Configurable via `API_KEYS` environment variable
- Supports multiple API keys (comma-separated)
- Skips authentication for health endpoints
- Development mode: disabled when no keys configured

### Rate Limiting
- Redis-based sliding window algorithm
- Configurable request limits and time windows
- Per-API-key or per-IP rate limiting
- Graceful degradation on Redis failures

### Security Headers
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- X-XSS-Protection: 1; mode=block
- Strict-Transport-Security: max-age=31536000; includeSubDomains
- Content-Security-Policy: default-src 'self'
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: geolocation=(), microphone=(), camera=()

### Request Validation
- Pydantic-based schema validation
- Content length limits
- Required field validation
- Type checking and sanitization

## Development

### Running Tests
```bash
cd backend/gateway
pytest tests/ -v --cov=src --cov-report=term-missing
```

### Code Quality
```bash
# Linting
ruff check src/ tests/

# Formatting
ruff format src/ tests/

# Type checking
mypy src/
```

### Test Coverage
Current test coverage: **83%** (36 tests)

## Architecture

### Components
- **auth.py**: API key authentication middleware
- **config.py**: Configuration management with Pydantic
- **logging_config.py**: Structured logging configuration
- **main.py**: Application setup and middleware
- **rate_limit.py**: Redis-based rate limiting
- **routes.py**: API endpoints and request handling
- **schemas.py**: Pydantic models for request/response validation
- **security.py**: Security headers and trusted host middleware
- **services.py**: Provider client and routing logic

### Middleware Stack
1. Security Headers
2. Trusted Host (production only)
3. API Key Authentication
4. Rate Limiting
5. Request Processing

## Deployment

### Production Considerations
- Set `DEBUG=false` in production
- Configure proper `ALLOWED_HOSTS`
- Use strong API keys via `API_KEYS`
- Configure Redis with persistence
- Enable HTTPS/TLS
- Set up monitoring and logging
- Configure proper CORS origins

### Docker Production
```bash
docker build -f docker/Dockerfile -t modelink-gateway .
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  --name modelink-gateway \
  modelink-gateway
```

## Monitoring

### Health Endpoints
- `/health` - Basic health check
- `/ready` - Readiness probe for Kubernetes

### Logging
Structured logs with context:
- Request metadata
- Authentication status
- Rate limiting events
- Provider routing decisions
- Error details

## Troubleshooting

### Common Issues

**Redis Connection Failed**
- Ensure Redis is running: `redis-cli ping`
- Check `REDIS_URL` in configuration
- Verify Redis is accessible from the gateway

**Authentication Failures**
- Verify `API_KEYS` is configured correctly
- Check `X-API-Key` header format
- Ensure health endpoints bypass auth

**Rate Limiting Issues**
- Check Redis connectivity
- Verify rate limit configuration
- Monitor Redis memory usage

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## License

[Specify your license here]

## Support

For issues and questions, please open an issue on GitHub.
