# Kafka Knowledge

## Overview

Apache Kafka is a distributed event streaming platform. Suitable for high-throughput, real-time data pipelines and event sourcing.

## Key Concepts

- **Topic**: Logical channel for events (e.g., `user-events`, `orders`)
- **Partition**: Ordered subset of a topic (enables parallelism)
- **Producer**: Writes events to topics
- **Consumer**: Reads events from topics (part of consumer group)
- **Consumer Group**: Set of consumers that share topic consumption
- **Offset**: Position of a consumer in a partition
- **Broker**: Kafka server that stores topics
- **Retention**: How long events are kept (time or size-based)

## Event Structure

- Key: Optional partitioning key (determines partition)
- Value: Event payload (JSON, Avro, Protobuf)
- Headers: Metadata key-value pairs
- Timestamp: Event or log append time

## Modelink Usage

- Event sourcing for domain events
- Real-time analytics and monitoring
- Service communication via events
- Log aggregation and streaming
- CQRS read model updates

## Best Practices

- Use meaningful topic names (e.g., `user.created`, `order.placed`)
- Design events for immutability (no updates, only new events)
- Use schema registry (Avro/Protobuf) for compatibility
- Set appropriate retention based on use case
- Monitor consumer lag (offset lag)
- Handle serialization/deserialization errors
- Use idempotent consumers for at-least-once delivery

## Python Libraries

- `confluent-kafka`: High-performance client
- `kafka-python`: Pure Python client
- `aiokafka`: Async Kafka for asyncio

## Connection Details

- Default port: 9092 (broker), 9091 (schema registry)
- Requires ZooKeeper (older versions) or KRaft mode (newer)
- Use SASL/SSL for production security
- Enable JMX for monitoring

## vs RabbitMQ

- Kafka: Higher throughput, replayable, event sourcing
- RabbitMQ: Simpler setup, routing flexibility, task queues
