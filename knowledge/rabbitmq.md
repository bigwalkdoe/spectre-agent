# RabbitMQ Knowledge

## Overview

RabbitMQ is a message broker that implements AMQP (Advanced Message Queuing Protocol). Suitable for task queues, pub/sub, and routing scenarios.

## Key Concepts

- **Exchange**: Receives messages from producers and routes them to queues
  - Direct: Routes based on exact routing key match
  - Topic: Routes based on pattern matching with routing keys
  - Fanout: Broadcasts to all bound queues
  - Headers: Routes based on message headers

- **Queue**: Stores messages until consumed
  - Durable: Survives broker restart
  - Exclusive: Only used by one connection
  - Auto-delete: Deleted when last consumer unsubscribes

- **Binding**: Links exchange to queue with routing key/pattern

- **Message**: Contains payload, properties, and headers

## Modelink Usage

- Task queues for async job processing
- Event notification between services
- Work distribution across workers
- Retry and dead-letter handling

## Best Practices

- Use durable queues for critical data
- Set TTL on messages to prevent buildup
- Implement dead-letter exchanges for failed messages
- Use separate connections for producers/consumers
- Prefetch count to control consumer load
- Monitor queue depth and consumer lag

## Python Libraries

- `pika`: Pure Python AMQP client
- `aio-pika`: Async AMQP for asyncio
- `celery`: Task queue with RabbitMQ backend

## Connection Details

- Default port: 5672 (AMQP), 15672 (Management UI)
- Default user: guest/guest (development only)
- Use vhosts for environment separation
- Enable management plugin for monitoring
