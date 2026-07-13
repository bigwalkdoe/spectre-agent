# Monitoring Knowledge

## Stack

- **Metrics**: Prometheus + Grafana
- **Tracing**: OpenTelemetry + Jaeger/Tempo
- **Logging**: Loki or ELK Stack
- **Alerting**: Alertmanager + PagerDuty/Slack

## Key Concepts

### Metrics
- **Counter**: Monotonically increasing value (requests, errors)
- **Gauge**: Current value (memory, connections)
- **Histogram**: Distribution of values (latency buckets)
- **Summary**: Similar to histogram with client-side quantiles

### Tracing
- **Span**: Single operation in a trace
- **Trace**: Tree of spans representing a request
- **Context**: Propagated across service boundaries
- **Baggage**: Key-value pairs attached to spans

### SLOs
- **Availability**: Percentage of successful requests
- **Latency**: Response time percentiles (p50, p95, p99)
- **Error Rate**: Percentage of failed requests
- **Throughput**: Requests per second

## Best Practices

- Use RED method (Rate, Errors, Duration) for service metrics
- Add USE method (Utilization, Saturation, Errors) for resources
- Instrument business metrics alongside technical metrics
- Keep alert thresholds actionable
- Use dashboards for investigation, alerts for action
