# Logging Implementation

## Steps

1. Set up structured logging:
   - Install logging library (structlog, loguru)
   - Configure JSON formatter
   - Add correlation ID middleware
   - Set up log rotation

2. Configure logging levels:
   - Development: DEBUG
   - Staging: INFO
   - Production: WARNING (ERROR for critical services)

3. Add logging to application layers:
   - Request/response logging middleware
   - Service layer business logic logging
   - Database query logging
   - External API call logging

4. Implement correlation IDs:
   - Generate on incoming requests
   - Extract from headers if present
   - Pass to downstream services
   - Include in all log entries

5. Add context to logs:
   - User ID (if authenticated)
   - Request ID
   - IP address
   - Service name
   - Environment

6. Handle sensitive data:
   - Sanitize passwords and tokens
   - Mask PII (emails, phone numbers)
   - Exclude request bodies for sensitive endpoints
   - Use environment-specific configuration

7. Set up log aggregation:
   - Centralize logs with Loki or ELK
   - Configure log shipping
   - Set up retention policies
   - Add log indexing

8. Monitor logging:
   - Track log volume
   - Monitor error rates
   - Set up alerts for critical errors
   - Review logs regularly

9. Test logging:
   - Verify log format
   - Check correlation ID propagation
   - Test sensitive data sanitization
   - Validate log aggregation

## Python Example

```python
import structlog
from fastapi import Request

def configure_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer()
        ],
        logger_factory=structlog.PrintLoggerFactory()
    )

async def logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(request_id=request_id)
    
    logger = structlog.get_logger()
    logger.info("request_started", method=request.method, path=request.url.path)
    
    try:
        response = await call_next(request)
        logger.info("request_completed", status_code=response.status_code)
        return response
    except Exception as e:
        logger.error("request_failed", error=str(e))
        raise
```
