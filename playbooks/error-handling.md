# Error Handling Patterns

## Steps

1. Define custom exception hierarchy:
   - Create base exception class
   - Create domain-specific exceptions (UserNotFound, InvalidInput)
   - Create HTTP-specific exceptions (BadRequest, Unauthorized)
   - Include error codes and user-friendly messages

2. Implement global exception handler:
   - Create exception handler middleware
   - Catch all exceptions and format responses
   - Log errors with context
   - Return appropriate HTTP status codes

3. Use consistent error response format:
   ```json
   {
     "error": {
       "code": "USER_NOT_FOUND",
       "message": "User not found",
       "details": {...},
       "request_id": "uuid"
     }
   }
   ```

4. Add request correlation:
   - Generate request ID on incoming requests
   - Include in error responses
   - Pass to downstream services
   - Use for log aggregation

5. Handle database errors:
   - Catch integrity errors (unique violations)
   - Handle connection errors gracefully
   - Implement retry logic for transient failures
   - Log query context on errors

6. Handle external API errors:
   - Implement circuit breaker pattern
   - Add retry with exponential backoff
   - Timeout external calls
   - Fallback to cached data if available

7. Add validation error handling:
   - Use Pydantic validation
   - Return field-specific error messages
   - Include validation rules in error response
   - Log validation failures

8. Implement error monitoring:
   - Send errors to monitoring system
   - Track error rates by type
   - Alert on critical errors
   - Generate error reports

9. Add graceful degradation:
   - Return cached data on failures
   - Disable non-critical features
   - Queue operations for later
   - Inform users of temporary issues

10. Test error scenarios:
    - Test with invalid input
    - Test with unavailable services
    - Test with rate limits
    - Test with network failures

## Exception Hierarchy Example

```python
class AppError(Exception):
    def __init__(self, code: str, message: str, details: dict = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

class NotFoundError(AppError):
    pass

class ValidationError(AppError):
    pass

class AuthenticationError(AppError):
    pass

class ExternalServiceError(AppError):
    pass
```

## Global Handler Example

```python
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request.state.request_id
            }
        }
    )
```
