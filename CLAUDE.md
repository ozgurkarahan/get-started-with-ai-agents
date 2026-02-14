# Project: Get Started with AI Agents (Azure AI Foundry)

## Architecture

This project deploys a web-based chat application powered by an Azure AI Foundry agent.

### Components

| Component | Location | Description |
|-----------|----------|-------------|
| Web App (FastAPI + React) | `src/api/`, `src/frontend/` | Human-facing chat UI, deployed as Container App on port 50505 |
| Foundry Agent | Azure AI Foundry | GPT model + file search tools, managed at runtime via SDK |
| Infrastructure | `infra/` | Bicep IaC for all Azure resources |

### Request Flows

```
Human  --> Web App (FastAPI/SSE) --> Foundry Agent (OpenAI API)
```

## Key Files

- `src/api/main.py` — FastAPI app factory, AIProjectClient lifecycle, tracing setup
- `src/api/routes.py` — Chat endpoints, SSE streaming, conversation management
- `src/gunicorn.conf.py` — Agent creation/recreation at startup, continuous evaluation
- `infra/main.bicep` — Top-level orchestrator, all modules and RBAC
- `infra/api.bicep` — Web app Container App definition
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

### Run web app locally
```bash
cd src
pip install -r requirements.txt
gunicorn api.main:create_app
```

## Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `AZURE_EXISTING_AIPROJECT_ENDPOINT` | Web App | Foundry project endpoint URL |
| `AZURE_EXISTING_AGENT_ID` | Web App | Agent name:version (e.g. `my-agent:1`) |
| `AZURE_CLIENT_ID` | Web App | Managed identity client ID |
| `ENABLE_AZURE_MONITOR_TRACING` | Web App | Enable Application Insights tracing |

## Conventions

- **Python**: Use `logging` module, async/await patterns, `DefaultAzureCredential`
- **Bicep**: Mirror `api.bicep` patterns for new Container Apps; use `core/security/role.bicep` for RBAC
- **Naming**: Resources use `{abbr}-{resourceToken}` pattern (e.g. `ca-api-{token}`)
- **Ports**: Web app on 50505
- **Docker**: Base image `python:3.13.9-slim-bookworm`
