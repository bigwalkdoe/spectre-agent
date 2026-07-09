# Performance Tuning Playbook

## Steps

1. **Profile** — identify slow endpoints with APM or manual timing
2. **Check database queries** — enable SQLAlchemy echo, look for N+1, missing indexes, sequential scans
3. **Add database indexes** — index foreign keys, frequently filtered columns, JSONB GIN indexes where appropriate
4. **Optimize queries** — use selectinload/joinedload for relationships, add limit/offset, use pagination
5. **Add caching** — Redis for frequently accessed data, cache LLM responses where safe
6. **Connection pooling** — tune SQLAlchemy pool_size and max_overflow, Redis max_connections
7. **Async everywhere** — ensure I/O-bound endpoints use async, avoid sync DB drivers
8. **Payload size** — compress responses, paginate lists, use sparse field selection
9. **Static assets** — CDN or nginx proxy for static files, far-future cache headers
10. **Load test** — use locust or k6 to verify improvements under realistic load
11. **Document baselines** — p50/p95/p99 latency, throughput, error rate before and after
