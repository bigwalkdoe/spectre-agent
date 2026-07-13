# Environment Management

## Environments

- **Development**: Local development, debug enabled, hot reload
- **Staging**: Pre-production testing, production-like data
- **Production**: Live environment, optimized, monitored

## Configuration Strategy

- Use environment variables for all configuration
- Store defaults in code (pydantic-settings)
- Override with .env files (not committed)
- Use separate .env files per environment
- Validate configuration at startup

## Environment Variables

### Database
- `DATABASE_URL`: PostgreSQL connection string
- `DATABASE_POOL_SIZE`: Connection pool size
- `DATABASE_MAX_OVERFLOW`: Max overflow connections

### Redis
- `REDIS_URL`: Redis connection string
- `REDIS_POOL_SIZE`: Connection pool size

### External Services
- `AZURE_OPENAI_ENDPOINT`: Azure OpenAI endpoint
- `AZURE_OPENAI_API_KEY`: Azure OpenAI API key
- `OPENAI_API_KEY`: OpenAI API key (fallback)
- `OLLAMA_HOST`: Ollama host URL

### Security
- `SECRET_KEY`: JWT signing key
- `ENCRYPTION_KEY`: Data encryption key
- `ALLOWED_ORIGINS`: CORS allowed origins

### Features
- `FEATURE_FLAG_X`: Enable/disable features
- `MAINTENANCE_MODE`: Enable maintenance mode

### Monitoring
- `SENTRY_DSN`: Error tracking DSN
- `LOG_LEVEL`: Logging level
- `METRICS_ENABLED`: Enable metrics collection

## .env Files

- `.env.example`: Template with placeholders
- `.env.development`: Development config
- `.env.staging`: Staging config
- `.env.production`: Production config (never commit)

## Loading

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    secret_key: str
    
    class Config:
        env_file = ".env.development"
        env_file_encoding = "utf-8"
```
