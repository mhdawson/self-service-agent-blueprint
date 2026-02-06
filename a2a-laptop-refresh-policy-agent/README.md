# Laptop Refresh Policy Agent

A2A (Agent-to-Agent) agent that provides laptop refresh policy information, built with LangGraph.

## Overview

This agent implements the [A2A protocol](https://a2a-protocol.org/latest/specification/) and provides a simple service that returns the laptop refresh interval policy (default: 3 years).

## Features

- **A2A Protocol Compliant**: Implements standard A2A endpoints
- **LangGraph**: Built using LangGraph for state management
- **FastAPI**: REST API server with automatic OpenAPI documentation
- **Configurable**: Refresh interval configurable via environment variables

## Endpoints

### A2A Protocol Endpoints

- `GET /.well-known/agent-card.json` - Agent card metadata
- `POST /message/send` - Handle A2A messages (JSON-RPC 2.0)
- `GET /health` - Health check endpoint

## Configuration

Environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `SERVER_HOST` | Server bind address | `0.0.0.0` |
| `SERVER_PORT` | Server port | `8001` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `REFRESH_INTERVAL_YEARS` | Laptop refresh interval in years | `3` |

## Running Locally

### Prerequisites

- Python 3.12+
- uv or pip

### Install Dependencies

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

### Run the Server

```bash
python -m laptop_refresh_policy_agent.main
```

The server will start on `http://localhost:8001`.

### Test the Endpoints

```bash
# Get agent card
curl http://localhost:8001/.well-known/agent-card.json

# Health check
curl http://localhost:8001/health

# Send a message (JSON-RPC 2.0)
curl -X POST http://localhost:8001/message/send \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "test-001",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "What is the laptop refresh interval?"}]
      }
    }
  }'
```

## Building Container Image

This agent uses the shared `Containerfile.a2a-template` for building. Use the Makefile target:

```bash
# Build the container using the template
make build-a2a-laptop-refresh-policy-agent

# Or build manually with podman/docker
podman build -t self-service-agent-laptop-refresh-policy-agent:latest \
  -f ../Containerfile.a2a-template \
  --build-arg AGENT_NAME=a2a-laptop-refresh-policy-agent \
  --build-arg MODULE_NAME=laptop_refresh_policy_agent.main \
  ..

# Run the container
podman run -p 8001:8001 self-service-agent-laptop-refresh-policy-agent:latest
```

## Deploying to Kubernetes

This agent is automatically deployed when added to the IT self-service agent system:

1. Copy `agent_card.json` to `agent-service/config/a2a-agents/laptop-refresh-policy-agent-card.json`
2. Run `helm install self-service-agent ./helm`

The agent will be automatically discovered and deployed with smart defaults.

## Development

### Project Structure

```
a2a-laptop-refresh-policy-agent/
├── src/
│   └── laptop_refresh_policy_agent/
│       ├── __init__.py
│       ├── agent.py         # LangGraph agent implementation
│       ├── config.py        # Configuration
│       └── main.py          # FastAPI server
├── agent_card.json          # A2A agent card metadata
├── pyproject.toml           # Project dependencies
└── README.md                # This file

Note: Uses ../Containerfile.a2a-template for building (shared across all A2A agents)
```

### Running Tests

```bash
pytest
```

## Architecture

```
┌─────────────────────────────────────────┐
│         FastAPI Server                  │
│  (A2A Protocol Implementation)          │
│                                         │
│  /.well-known/agent-card.json          │
│  /message/send                          │
│  /health                                │
└──────────────┬──────────────────────────┘
               │
               │ Invokes
               ▼
┌─────────────────────────────────────────┐
│       LangGraph Agent                   │
│  (State Machine)                        │
│                                         │
│  ┌─────────┐                           │
│  │  START  │                           │
│  └────┬────┘                           │
│       │                                 │
│       ▼                                 │
│  ┌─────────────────┐                   │
│  │  process node   │                   │
│  │ (get_refresh_   │                   │
│  │  interval)      │                   │
│  └────┬────────────┘                   │
│       │                                 │
│       ▼                                 │
│  ┌─────────┐                           │
│  │   END   │                           │
│  └─────────┘                           │
└─────────────────────────────────────────┘
```

## License

See main project LICENSE file.
