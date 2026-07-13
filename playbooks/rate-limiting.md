# Rate Limiting Implementation

## Steps

1. Choose rate limiting algorithm:
   - Token bucket - Smooth rate, allows bursts
   - Leaky bucket - Constant rate, smooths traffic
   - Fixed window - Simple, but allows bursts at boundaries
   - Sliding window - Accurate, more complex
   - Sliding window log - Most accurate, higher memory

2. Define rate limits by endpoint type:
   - Public endpoints: 100 req/min per IP
   - Auth endpoints: 10 req/min per IP (prevent brute force)
   - Authenticated users: 1000 req/min per user
   - Premium users: Higher limits based on tier
   - Internal services: No limits or very high

3. Implement with Redis:
   - Use Redis sorted sets for sliding window
   - Key format: `rate_limit:{user_id}:{endpoint}`
   - Store timestamps as scores
   - Remove entries outside window
   - Count remaining entries

4. Add rate limiting middleware:
   - Extract identifier (IP, user ID, API key)
   - Check current usage against limit
   - Return 429 if limit exceeded
   - Add RateLimit-* headers to response

5. Configure different limit strategies:
   - Per IP: Good for public APIs
   - Per user: Better for authenticated users
   - Per API key: For service accounts
   - Composite: IP + user for security

6. Handle rate limit exceeded:
   - Return HTTP 429 (Too Many Requests)
   - Include Retry-After header
   - Log rate limit violations
   - Consider CAPTCHA for repeated violations

7. Add rate limit bypass:
   - Internal IP ranges
   - Admin users
   - Service accounts
   - Health check endpoints

8. Monitor rate limiting:
   - Track 429 responses
   - Monitor Redis memory usage
   - Adjust limits based on usage patterns
   - Alert on unusual rate limit patterns

9. Test rate limiting:
   - Test normal usage within limits
   - Test exceeding limits
   - Test limit recovery after window
   - Test different user types
   - Test distributed scenarios

## Example Redis Sliding Window

```python
async def check_rate_limit(redis, key, limit, window_seconds):
    now = time.time()
    window_start = now - window_seconds
    
    # Remove old entries
    await redis.zremrangebyscore(key, 0, window_start)
    
    # Count current requests
    current = await redis.zcard(key)
    
    if current >= limit:
        return False, current
    
    # Add current request
    await redis.zadd(key, {str(now): now})
    await redis.expire(key, window_seconds)
    
    return True, current + 1
```
