# Modelink Knowledge

Modelink is an AI engineering platform. Key concepts:

- **Gateway Service**: Central LLM routing — load balancing, failover, cost tracking
- **Agent Service**: Agent orchestration, tool execution, conversation management
- **Model Registry**: Catalog of available models with capabilities and pricing
- **Workspace Service**: User projects, environments, deployments
- **Evaluation Service**: Offline and online evaluation of model/agent performance
- **Hub**: UI for managing models, agents, deployments, monitoring

## Architecture

Microservices communicating via REST/gRPC. Async events via Redis. State in PostgreSQL. LLM calls through the Gateway.
