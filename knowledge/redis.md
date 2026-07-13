# Redis Cache Strategies

## Overview

Redis is an in-memory data store used for caching, session management, and real-time features.

## Cache Patterns

### Cache-Aside (Lazy Loading)
- Application checks cache first
- On miss, load from database and populate cache
- Pros: Simple, only caches requested data
- Cons: First request is slow, cache stampede risk

### Write-Through
- Write to cache and database synchronously
- Pros: Cache always consistent, low read latency
- Cons: Higher write latency, unused data cached

### Write-Behind (Write-Back)
- Write to cache immediately, database asynchronously
- Pros: Fast writes, batch database operations
- Cons: Data loss risk if cache fails, complexity

### Refresh-Ahead
- Proactively refresh cache before expiration
- Pros: Reduces cache misses, predictable latency
- Cons: Complexity, may refresh unused data

## Redis Data Structures

- **String**: Simple key-value, counters
- **Hash**: Object storage (e.g., user:123 -> {name, email})
- **List**: Queues, stacks, timelines
- **Set**: Unique collections, relationships
- **Sorted Set**: Leaderboards, rate limiting, rankings
- **Bitmap**: Binary flags, analytics
- **HyperLogLog**: Cardinality estimation

## Cache Invalidation

- **TTL**: Time-based expiration (e.g., 3600 seconds)
- **LRU**: Least Recently Used eviction
- **Manual**: Explicit delete on data changes
- **Versioning**: Include version in cache key
- **Tags**: Group related keys for bulk invalidation

## Best Practices

- Use connection pooling (redis-py connection pool)
- Set appropriate TTLs to prevent memory bloat
- Use compression for large values
- Monitor cache hit ratio (aim for 80%+)
- Handle cache failures gracefully (fallback to DB)
- Use pipeline for multi-key operations
- Consider Redis Cluster for horizontal scaling

## Modelink Usage

- API response caching (TTL 60-300s)
- Session storage (TTL 24h)
- Rate limiting (sliding window)
- Pub/Sub for real-time events
- Job queues with RQ/Celery
- Leaderboards and analytics

## Python Libraries

- `redis-py`: Core Redis client
- `hiredis`: C parser for performance
- `aioredis`: Async Redis for asyncio
- `cachelib`: Cache abstraction layer
