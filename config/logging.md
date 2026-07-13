# Logging Configuration

## Standards

- **Format**: Structured JSON logging
- **Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Output**: stdout (containerized), file (local dev)
- **Rotation**: Daily rotation, 30-day retention
- **Aggregation**: Centralized with Loki or ELK

## Log Structure

```json
{
  "timestamp": "2026-07-12T10:30:00Z",
  "level": "INFO",
  "service": "user-service",
  "environment": "production",
  "request_id": "uuid",
  "user_id": "uuid",
  "message": "User created successfully",
  "context": {
    "user_email": "user@example.com",
    "ip_address": "192.168.1.1"
  },
  "tags": ["user", "creation"]
}
```

## Python Libraries

- `structlog`: Structured logging
- `python-json-logger`: JSON formatter
- `loguru`: Modern logging interface

## Log Levels

- **DEBUG**: Detailed diagnostic information
- **INFO**: General informational messages
- **WARNING**: Warning messages for potential issues
- **ERROR**: Error events that might still allow the application to continue
- **CRITICAL**: Critical errors that may cause application failure

## Best Practices

- Never log sensitive data (passwords, tokens, PII)
- Include correlation IDs for request tracing
- Use structured data for context
- Set appropriate log levels per environment
- Monitor log volume and costs
- Add log sampling for high-volume events
