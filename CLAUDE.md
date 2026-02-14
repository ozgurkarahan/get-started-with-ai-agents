# Project: Get Started with AI Agents (Azure AI Foundry)

## Architecture

This project deploys a web-based chat application powered by an Azure AI Foundry agent.

### Components

| Component | Location | Description |
|-----------|----------|-------------|
| Web App (FastAPI + React) | `src/api/`, `src/frontend/` | Human-facing chat UI, deployed as Container App on port 50505 |
| A2A Server | `src/a2a_server/` | Agent-to-Agent protocol wrapper, deployed as Container App on port 8080 |
| Foundry Agent | Azure AI Foundry | GPT model + file search tools, managed at runtime via SDK |
| Infrastructure | `infra/` | Bicep IaC for all Azure resources |

### Request Flows

```
Human  --> Web App (FastAPI/SSE) --> Foundry Agent (OpenAI API)
Agent  --> A2A Server (JSON-RPC) --> Foundry Agent (OpenAI API)
```

## Key Files

- `src/api/main.py` — FastAPI app factory, AIProjectClient lifecycle, tracing setup
- `src/api/routes.py` — Chat endpoints, SSE streaming, conversation management
- `src/gunicorn.conf.py` — Agent creation/recreation at startup, continuous evaluation
- `src/a2a_server/main.py` — A2A Starlette server entry point
- `src/a2a_server/foundry_client.py` — Foundry agent invocation (sync/stream)
- `src/a2a_server/agent_executor.py` — A2A protocol translation
- `infra/main.bicep` — Top-level orchestrator, all modules and RBAC
- `infra/api.bicep` — Web app Container App definition
- `infra/a2a-server.bicep` — A2A server Container App definition
- `azure.yaml` — AZD service definitions and hooks

## Commands

### Deploy everything
```bash
azd up
```

### Deploy only (skip provisioning)
```bash
azd deploy
```

### Deploy with A2A server enabled
```bash
azd env set DEPLOY_A2A_SERVER true
azd up
```

### Run web app locally
```bash
cd src
pip install -r requirements.txt
gunicorn api.main:create_app
```

### Run A2A server locally
```bash
cd src/a2a_server
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```

### Test A2A server
```bash
# Agent Card discovery
curl http://localhost:8080/.well-known/agent.json

# Send task
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tasks/send","id":"1","params":{"id":"test-1","message":{"role":"user","parts":[{"type":"text","text":"What products do you have?"}]}}}'
```

## Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `AZURE_EXISTING_AIPROJECT_ENDPOINT` | Web App, A2A | Foundry project endpoint URL |
| `AZURE_EXISTING_AGENT_ID` | Web App, A2A | Agent name:version (e.g. `my-agent:1`) |
| `AZURE_CLIENT_ID` | Both | Managed identity client ID |
| `ENABLE_AZURE_MONITOR_TRACING` | Both | Enable Application Insights tracing |
| `A2A_SERVER_BASE_URL` | A2A | Public URL for Agent Card |
| `A2A_SERVER_PORT` | A2A | Server port (default 8080) |
| `DEPLOY_A2A_SERVER` | Bicep | Toggle A2A server deployment |

## Conventions

- **Python**: Use `logging` module, async/await patterns, `DefaultAzureCredential`
- **Bicep**: Mirror `api.bicep` patterns for new Container Apps; use `core/security/role.bicep` for RBAC
- **Naming**: Resources use `{abbr}-{resourceToken}` pattern (e.g. `ca-a2a-{token}`)
- **Ports**: Web app on 50505, A2A server on 8080
- **Docker**: Base image `python:3.13.9-slim-bookworm`
