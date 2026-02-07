# Azure AI Foundry: Endpoint Architecture, API Compatibility & A2A Exposition

## Table of Contents

- [1. AI Foundry Project Endpoint](#1-ai-foundry-project-endpoint)
- [2. OpenAI-Compatible API Surface](#2-openai-compatible-api-surface)
- [3. How This Project Consumes the Agent](#3-how-this-project-consumes-the-agent)
- [4. Multi-Channel Compatibility](#4-multi-channel-compatibility)
- [5. A2A Protocol Overview](#5-a2a-protocol-overview)
- [6. Foundry Agent + A2A: Current State](#6-foundry-agent--a2a-current-state)
- [7. Exposing a Foundry Agent via A2A + Azure APIM](#7-exposing-a-foundry-agent-via-a2a--azure-apim)
- [8. End-to-End Architecture](#8-end-to-end-architecture)
- [Sources](#sources)

---

## 1. AI Foundry Project Endpoint

### What Is It?

The AI Foundry Project Endpoint is a scoped REST API endpoint tied to a specific
**AI Services account** and **project** in Azure. It provides access to all project
resources: agents, models, connections, evaluations, and telemetry.

### Endpoint Format

```
https://<ai-services-account>.services.ai.azure.com/api/projects/<project-name>
```

### Where It Comes From

There are two provisioning paths:

#### Path A: Foundry Creates the Project (Bicep IaC)

```
┌──────────────────────────────────────────────────────────────────┐
│  Microsoft.CognitiveServices/accounts (AI Services Account)      │
│                                                                  │
│   └── /projects/<name>  (AI Project - child resource)            │
│         │                                                        │
│         └── properties.endpoints['AI Foundry API']               │
│              = https://<account>.services.ai.azure.com/api/...   │
└──────────────────────────────────────────────────────────────────┘
```

The Bicep template (`infra/core/ai/cognitiveservices.bicep`) creates the project:

```bicep
resource aiProject 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: account
  name: aiProjectName
}

output projectEndpoint string = aiProject.properties.endpoints['AI Foundry API']
```

#### Path B: Bring Your Own Project (Existing Resource ID)

The endpoint is constructed from the ARM resource ID (`infra/main.bicep`):

```bicep
var existingProjEndpoint = format(
  'https://{0}.services.ai.azure.com/api/projects/{1}',
  split(azureExistingAIProjectResourceId, '/')[8],   // account name
  split(azureExistingAIProjectResourceId, '/')[10]    // project name
)
```

#### Flow Into the Application

```
Bicep output
    │
    ▼
AZURE_EXISTING_AIPROJECT_ENDPOINT  (env var)
    │
    ▼
main.py:  AIProjectClient(endpoint=proj_endpoint, credential=credential)
    │
    ▼
project_client.get_openai_client()  →  AsyncOpenAI(base_url=<project_endpoint>)
```

### Authentication

The endpoint uses **Azure AD (Entra ID)** authentication via `DefaultAzureCredential`.
No API keys are used — all access is identity-based through managed identity or
developer credentials.

```python
async with DefaultAzureCredential() as credential:
    AIProjectClient(endpoint=proj_endpoint, credential=credential)
```

---

## 2. OpenAI-Compatible API Surface

### The Key Design Choice

Azure AI Foundry exposes agents through an **OpenAI-compatible REST API**.
The runtime interaction layer is not proprietary — it follows the same API format
as OpenAI's Responses API.

### API Endpoints

| Operation | HTTP Method | Path | Description |
|-----------|-------------|------|-------------|
| Create conversation | `POST` | `/conversations` | Start a new stateful conversation |
| Retrieve conversation | `GET` | `/conversations/{id}` | Get conversation details |
| Send message (agent) | `POST` | `/responses` | Send input and get agent response |
| List messages | `GET` | `/conversations/{id}/items` | List messages in a conversation |
| Update conversation | `PATCH` | `/conversations/{id}` | Update metadata |

### Published Agent Endpoint (App Protocol)

When an agent is published as an Application, the endpoint format is:

```
POST https://<account>.services.ai.azure.com/api/projects/<project>/applications/<app>/protocols/openai/responses?api-version=2025-11-15-preview
```

### Agent Reference

The Azure-specific extension is the `agent` field in the request body, which
specifies which named/versioned agent should handle the request:

```json
{
  "conversation": "<conversation_id>",
  "input": "What products do you have?",
  "agent": {
    "name": "my-agent",
    "version": "1"
  },
  "stream": true
}
```

### SDK Mapping

The `AIProjectClient.get_openai_client()` method returns a standard `AsyncOpenAI`
client pointed at the Foundry endpoint. All subsequent calls use the OpenAI SDK:

```
┌──────────────────────────────┐
│      Your Application        │
│                              │
│  openai.responses.create()   │  ← Standard OpenAI SDK
│  openai.conversations.*()    │
└──────────────┬───────────────┘
               │  HTTPS + Azure AD Bearer Token
               ▼
┌──────────────────────────────┐
│  AI Foundry Project Endpoint │
│                              │
│  OpenAI-compatible REST API  │
│  + Azure extensions (agent)  │
└──────────────────────────────┘
```

### What This Means

Any client that can:
1. Make HTTP requests
2. Pass an Azure AD bearer token
3. Handle JSON (or SSE for streaming)

...can call the Foundry agent directly. No SDK required.

```bash
TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)

# Create conversation
curl -X POST "$ENDPOINT/conversations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'

# Send message
curl -X POST "$ENDPOINT/responses" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation": "<conv_id>",
    "input": "Hello",
    "agent": {"name": "my-agent", "version": "1"},
    "stream": false
  }'
```

---

## 3. How This Project Consumes the Agent

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    React Frontend                        │
│              (Fluent UI Copilot Chat)                    │
│                                                          │
│  User types message → POST /chat → receives SSE stream  │
└─────────────────────────┬────────────────────────────────┘
                          │ HTTP POST (JSON) + SSE response
                          ▼
┌─────────────────────────────────────────────────────────┐
│                   FastAPI Backend                         │
│                                                          │
│  1. Extract conversation_id & agent_id from cookies      │
│  2. get_or_create_conversation(openai_client, ...)       │
│  3. openai_client.responses.create(                      │
│       conversation=conv.id,                              │
│       input=user_message,                                │
│       extra_body={"agent": AgentReference(...)},         │
│       stream=True                                        │
│     )                                                    │
│  4. Forward SSE delta events to browser                  │
└─────────────────────────┬────────────────────────────────┘
                          │ OpenAI-compatible API
                          │ Azure AD Bearer Token
                          ▼
┌─────────────────────────────────────────────────────────┐
│              Azure AI Foundry Agent                       │
│                                                          │
│  Model: GPT-4 (or configured deployment)                 │
│  Tools: FileSearchTool or AzureAISearchAgentTool         │
│  State: Server-managed conversations                     │
└──────────────────────────────────────────────────────────┘
```

### Key Code Paths

| Step | File | Line | What Happens |
|------|------|------|-------------|
| App startup | `gunicorn.conf.py` | 500-502 | `on_starting` → `initialize_resources()` |
| Agent creation | `gunicorn.conf.py` | 371-401 | `create_agent()` via `agents.create_version()` |
| Client init | `main.py` | 30-33 | `AIProjectClient` + `DefaultAzureCredential` |
| Agent fetch | `main.py` | 59-63 | `agents.get_version(name, version)` |
| Chat request | `routes.py` | 302-348 | `POST /chat` handler |
| Conversation | `routes.py` | 107-138 | `get_or_create_conversation()` |
| Agent call | `routes.py` | 214-218 | `responses.create(stream=True)` |
| SSE streaming | `routes.py` | 221-231 | Forward delta events to client |

### Management vs Runtime SDKs

```
┌─────────────────────────────────────────────────────────────┐
│  MANAGEMENT PLANE (Azure-specific)                           │
│                                                              │
│  azure-ai-projects SDK (AIProjectClient)                     │
│  ├── agents.create_version()      Create/update agents       │
│  ├── agents.get_version()         Fetch agent definitions    │
│  ├── connections.get_default()    Get Azure connections       │
│  ├── evaluation_rules.create()    Setup evaluations          │
│  └── telemetry.*                  Application Insights        │
├──────────────────────────────────────────────────────────────┤
│  RUNTIME PLANE (OpenAI-compatible)                           │
│                                                              │
│  openai SDK (AsyncOpenAI via get_openai_client())            │
│  ├── conversations.create()       Create conversations       │
│  ├── conversations.retrieve()     Get conversation           │
│  ├── conversations.items.list()   List messages              │
│  ├── responses.create()           Send message + get reply   │
│  ├── vector_stores.create()       Create vector stores       │
│  └── evals.create()               Create evaluations         │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Multi-Channel Compatibility

Because the runtime is OpenAI-compatible HTTP, the Foundry agent is inherently
channel-agnostic. The agent doesn't know what channel is calling it.

```
┌──────────┐
│  Web App  │──┐
└──────────┘  │
┌──────────┐  │    ┌────────────────────────┐    ┌─────────────────────┐
│  Mobile   │──┼───▶│  Channel Adapter Layer  │───▶│  AI Foundry Agent   │
└──────────┘  │    │  (conversation mapping) │    │  (OpenAI-compat API)│
┌──────────┐  │    └────────────────────────┘    └─────────────────────┘
│  Teams    │──┤
└──────────┘  │
┌──────────┐  │
│  Slack    │──┤
└──────────┘  │
┌──────────┐  │
│  WhatsApp │──┘
└──────────┘
```

Each channel adapter needs to:
1. Map channel user identity → Foundry conversation ID
2. Call `POST /responses` with the user message
3. Forward the response back to the channel

The core agent logic and knowledge base remain the same across all channels.

---

## 5. A2A Protocol Overview

### What Is A2A?

The Agent-to-Agent (A2A) protocol is an open standard (initiated by Google, adopted
by Microsoft and others) that allows AI agents to discover, communicate, and
collaborate regardless of their underlying framework or vendor.

### Core Concepts

```
┌─────────────────────────────────────────────────────────────────┐
│                     A2A Protocol                                 │
│                                                                  │
│  ┌─────────────┐    JSON-RPC 2.0     ┌─────────────┐           │
│  │  A2A Client  │ ◄──────────────────▶ │  A2A Server  │           │
│  │  (Caller)    │    over HTTP/SSE    │  (Agent)     │           │
│  └─────────────┘                      └──────┬──────┘           │
│                                              │                   │
│                                    ┌─────────▼─────────┐        │
│                                    │   Agent Card       │        │
│                                    │   (Discovery)      │        │
│                                    │                     │        │
│                                    │  /.well-known/      │        │
│                                    │    agent.json       │        │
│                                    └─────────────────────┘        │
└──────────────────────────────────────────────────────────────────┘
```

### Agent Card (Discovery Document)

Hosted at `/.well-known/agent.json`, the Agent Card is a JSON document that
advertises an agent's capabilities:

```json
{
  "name": "Product Knowledge Agent",
  "description": "Answers questions about products using document search",
  "url": "https://my-agent.azurecontainerapps.io",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": false
  },
  "skills": [
    {
      "id": "product-search",
      "name": "Product Search",
      "description": "Search product documentation and answer questions",
      "inputModes": ["text/plain"],
      "outputModes": ["text/plain"]
    }
  ],
  "authentication": {
    "schemes": [
      {
        "scheme": "bearer",
        "bearerFormat": "JWT"
      }
    ]
  },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"]
}
```

### A2A Task Lifecycle

```
Client                              A2A Server
  │                                     │
  │  POST /tasks/send                   │
  │  {"jsonrpc":"2.0",                  │
  │   "method":"tasks/send",            │
  │   "params":{"message":...}}         │
  │────────────────────────────────────▶│
  │                                     │  Agent processes task
  │  Response                           │
  │  {"result":{"status":"completed",   │
  │   "artifacts":[...]}}               │
  │◀────────────────────────────────────│
  │                                     │
  │  (Or for streaming:)                │
  │  POST /tasks/sendSubscribe          │
  │────────────────────────────────────▶│
  │  SSE: status updates + artifacts    │
  │◀────────────────────────────────────│
```

---

## 6. Foundry Agent + A2A: Current State

### Two Directions of A2A in Foundry

```
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│  DIRECTION 1: Foundry Agent CALLS an A2A Agent (Supported)         │
│                                                                    │
│  ┌──────────────┐   A2A Tool    ┌──────────────┐                  │
│  │ Foundry Agent │──────────────▶│ External A2A  │                  │
│  │ (Orchestrator)│◀──────────────│ Agent         │                  │
│  └──────────────┘               └──────────────┘                  │
│                                                                    │
│  Configured in Foundry portal: Agent → Tools → A2A → endpoint URL  │
│  Auth: API key, OAuth, or Entra ID passthrough                     │
│                                                                    │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  DIRECTION 2: External Agent CALLS Foundry Agent (Requires Wrapper)│
│                                                                    │
│  ┌──────────────┐   A2A        ┌──────────────┐   OpenAI API     │
│  │ External A2A  │─────────────▶│ A2A Server    │────────────────▶ │
│  │ Client        │◀─────────────│ (Wrapper)     │◀──────────────── │
│  └──────────────┘              └──────────────┘                   │
│                                       │                            │
│                            ┌──────────▼──────────┐                │
│                            │  Foundry Agent       │                │
│                            │  (OpenAI-compat API) │                │
│                            └─────────────────────┘                │
│                                                                    │
│  Foundry does NOT natively expose agents as A2A servers.           │
│  You must build a wrapper (Semantic Kernel, a2a-sdk, custom).      │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### What Needs to Be Built for Direction 2

The A2A server wrapper translates between protocols:

| A2A Protocol (Inbound) | Wrapper Logic | Foundry API (Outbound) |
|------------------------|---------------|----------------------|
| `GET /.well-known/agent.json` | Serve static Agent Card | N/A |
| `POST /tasks/send` | Extract message from A2A task | `POST /conversations` + `POST /responses` |
| `POST /tasks/sendSubscribe` | Extract message, stream | `POST /responses` (stream=true) |
| `POST /tasks/get` | Return cached result | `GET /conversations/{id}/items` |

---

## 7. Exposing a Foundry Agent via A2A + Azure APIM

This is the complete architecture for exposing a Foundry agent to the outside
world via A2A, governed and secured by Azure API Management.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL CONSUMERS                               │
│                                                                          │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐           │
│  │ Agent A    │  │ Agent B    │  │ Agent C    │  │ Copilot    │           │
│  │ (Google)   │  │ (LangChain)│  │ (AWS)      │  │ Studio     │           │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘           │
│        │               │               │               │                 │
│        └───────────────┼───────────────┼───────────────┘                 │
│                        │               │                                  │
│                        ▼               ▼                                  │
│              ┌─────────────────────────────────┐                         │
│              │  A2A Protocol (JSON-RPC 2.0)     │                         │
│              │  Discovery: /.well-known/agent.json                        │
│              │  Tasks: /tasks/send, /tasks/get  │                         │
│              └────────────────┬────────────────┘                         │
└───────────────────────────────┼──────────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  LAYER 1: AZURE API MANAGEMENT (Governance, Security, Observability)     │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │  A2A Agent API (Imported)                                        │     │
│  │                                                                  │     │
│  │  - Agent Card auto-transformed (hostname → APIM gateway)         │     │
│  │  - Subscription key authentication (Ocp-Apim-Subscription-Key)   │     │
│  │  - Rate limiting policies                                        │     │
│  │  - Request/response logging                                      │     │
│  │  - Application Insights (GenAI telemetry: genai.agent.id)        │     │
│  │  - IP filtering, JWT validation, CORS                            │     │
│  │                                                                  │     │
│  │  Agent Card URL:                                                 │     │
│  │  https://<apim>.azure-api.net/<base-path>/.well-known/agent.json │     │
│  │                                                                  │     │
│  │  Runtime URL:                                                    │     │
│  │  https://<apim>.azure-api.net/<base-path>/                       │     │
│  └───────────────────────────────┬─────────────────────────────────┘     │
│                                  │                                        │
└──────────────────────────────────┼────────────────────────────────────────┘
                                   │  JSON-RPC (proxied)
                                   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  LAYER 2: A2A SERVER (Protocol Translation)                               │
│  Hosted on: Azure Container Apps / Azure App Service                      │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │  A2A Server Application (Python / .NET)                          │     │
│  │                                                                  │     │
│  │  Framework options:                                              │     │
│  │  - Semantic Kernel + a2a-sdk (Python or .NET)                    │     │
│  │  - a2a-samples/azureaifoundry_sdk (Python reference impl)       │     │
│  │  - Custom Starlette/FastAPI + a2a-python                         │     │
│  │                                                                  │     │
│  │  Responsibilities:                                               │     │
│  │  ┌────────────────────┐    ┌─────────────────────────┐          │     │
│  │  │ /.well-known/       │    │ A2A Task Handler         │          │     │
│  │  │   agent.json        │    │                          │          │     │
│  │  │ (Agent Card)        │    │ tasks/send → create conv │          │     │
│  │  │                     │    │           → call agent   │          │     │
│  │  │                     │    │           → return result│          │     │
│  │  │                     │    │                          │          │     │
│  │  │                     │    │ tasks/sendSubscribe      │          │     │
│  │  │                     │    │           → stream SSE   │          │     │
│  │  └────────────────────┘    └──────────┬──────────────┘          │     │
│  └───────────────────────────────────────┼──────────────────────────┘     │
│                                          │                                │
└──────────────────────────────────────────┼────────────────────────────────┘
                                           │  OpenAI-compatible API
                                           │  Azure AD Bearer Token
                                           ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  LAYER 3: AZURE AI FOUNDRY AGENT                                          │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │  Agent: product-knowledge-agent:1                                │     │
│  │  Model: GPT-4                                                    │     │
│  │  Tools: FileSearchTool / AzureAISearchAgentTool                  │     │
│  │                                                                  │     │
│  │  Endpoint:                                                       │     │
│  │  https://<account>.services.ai.azure.com/api/projects/<project>  │     │
│  │                                                                  │     │
│  │  API:                                                            │     │
│  │  POST /conversations          (create)                           │     │
│  │  POST /responses              (send message + get reply)         │     │
│  │  GET  /conversations/{id}/items (list messages)                  │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

### Step-by-Step Setup

#### Step 1: Build the A2A Server (Protocol Wrapper)

The A2A server wraps the Foundry agent. It translates A2A JSON-RPC requests into
OpenAI-compatible API calls.

**Python implementation pattern (using a2a-sdk + Azure AI Projects SDK):**

```python
# Conceptual structure - not runnable as-is

from a2a.server import A2AServer
from a2a.types import AgentCard, AgentSkill
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential

# 1. Define the Agent Card
agent_card = AgentCard(
    name="Product Knowledge Agent",
    description="Answers questions about products using document search",
    url="https://my-a2a-server.azurecontainerapps.io",
    version="1.0.0",
    capabilities={"streaming": True},
    skills=[AgentSkill(
        id="product-search",
        name="Product Search",
        description="Search product docs and answer questions",
        inputModes=["text/plain"],
        outputModes=["text/plain"],
    )],
)

# 2. Implement the task handler
class FoundryAgentExecutor:
    async def handle_task(self, task):
        async with DefaultAzureCredential() as cred:
            async with AIProjectClient(endpoint=ENDPOINT, credential=cred) as client:
                async with client.get_openai_client() as openai:
                    conv = await openai.conversations.create()
                    response = await openai.responses.create(
                        conversation=conv.id,
                        input=task.message.parts[0].text,
                        extra_body={"agent": {"name": AGENT_NAME, "version": AGENT_VERSION}},
                        stream=False,
                    )
                    return response.output_text

# 3. Start the A2A server
server = A2AServer(agent_card=agent_card, executor=FoundryAgentExecutor())
# Serve via uvicorn / Starlette on port 8080
```

#### Step 2: Containerize and Deploy

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Deploy to **Azure Container Apps** or **Azure App Service**:

```bash
# Build and push to ACR
az acr build --registry <acr-name> --image a2a-foundry-agent:v1 .

# Deploy to Container Apps
az containerapp create \
  --name a2a-foundry-agent \
  --resource-group <rg> \
  --environment <env> \
  --image <acr>.azurecr.io/a2a-foundry-agent:v1 \
  --target-port 8080 \
  --ingress external \
  --env-vars \
    AZURE_EXISTING_AIPROJECT_ENDPOINT=<endpoint> \
    AZURE_EXISTING_AGENT_ID=<name:version>
```

#### Step 3: Import into Azure API Management

```
Azure Portal → API Management → APIs → + Add API → A2A Agent
```

1. Enter Agent Card URL:
   `https://a2a-foundry-agent.<region>.azurecontainerapps.io/.well-known/agent.json`

2. APIM auto-discovers:
   - Agent name, description, skills
   - Runtime URL for JSON-RPC operations
   - Authentication requirements

3. APIM transforms the Agent Card:
   - Hostname → `<apim-instance>.azure-api.net`
   - Auth → APIM subscription key
   - Unsupported interfaces removed

4. Configure policies:

```xml
<policies>
  <inbound>
    <!-- Rate limiting -->
    <rate-limit calls="100" renewal-period="60" />

    <!-- JWT validation for callers -->
    <validate-jwt header-name="Authorization" require-scheme="Bearer">
      <openid-config url="https://login.microsoftonline.com/{tenant}/.well-known/openid-configuration" />
    </validate-jwt>

    <!-- Log to Application Insights -->
    <set-header name="x-apim-agent-id" exists-action="override">
      <value>product-knowledge-agent</value>
    </set-header>
  </inbound>
  <backend>
    <forward-request />
  </backend>
</policies>
```

#### Step 4: External Agents Connect

External agents discover and interact via the APIM-managed endpoint:

```
# Discovery
GET https://<apim>.azure-api.net/product-agent/.well-known/agent.json
Header: Ocp-Apim-Subscription-Key: <key>

# Send task
POST https://<apim>.azure-api.net/product-agent/
Header: Ocp-Apim-Subscription-Key: <key>
Header: Content-Type: application/json
Body: {
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "id": "1",
  "params": {
    "id": "task-123",
    "message": {
      "role": "user",
      "parts": [{"type": "text", "text": "What products do you offer?"}]
    }
  }
}
```

### What APIM Provides

| Capability | Description |
|-----------|-------------|
| **Governance** | Centralized API management alongside REST, GraphQL, MCP APIs |
| **Security** | Subscription keys, JWT validation, OAuth, IP filtering |
| **Rate Limiting** | Per-caller or per-agent throttling policies |
| **Observability** | Application Insights with GenAI telemetry (`genai.agent.id`) |
| **Transformation** | Auto-transforms Agent Card with APIM gateway hostname |
| **Versioning** | API versioning and revision management |
| **Developer Portal** | Self-service discovery for API consumers |

### Requirements and Limitations

- Azure APIM **v2 tiers** only (as of preview)
- Only **JSON-RPC-based** A2A agent APIs are supported
- The A2A server (Layer 2) must be built and hosted separately — Foundry does not
  natively serve A2A

---

## 8. End-to-End Architecture

Complete view showing both human channels and agent-to-agent communication:

```
                    HUMAN CHANNELS                          AGENT CHANNELS
              ┌─────────────────────┐              ┌─────────────────────────┐
              │  Web   Mobile  Teams│              │ Google   LangChain  AWS  │
              │  App   App     Bot  │              │ Agent    Agent      Agent│
              └────────┬────────────┘              └──────────┬──────────────┘
                       │                                      │
                       │ HTTP/SSE                             │ A2A (JSON-RPC)
                       │                                      │
              ┌────────▼────────────┐              ┌──────────▼──────────────┐
              │  Custom Web App     │              │  Azure API Management    │
              │  (like this project)│              │  (A2A API imported)      │
              │                     │              │                          │
              │  FastAPI + React    │              │  - Rate limiting         │
              │  Cookie-based state │              │  - Auth (sub key + JWT)  │
              │  SSE streaming      │              │  - Telemetry             │
              └────────┬────────────┘              └──────────┬──────────────┘
                       │                                      │
                       │                                      │ JSON-RPC (proxied)
                       │                                      │
                       │                           ┌──────────▼──────────────┐
                       │                           │  A2A Server Wrapper      │
                       │                           │  (Container Apps)        │
                       │                           │                          │
                       │                           │  Semantic Kernel /       │
                       │                           │  a2a-sdk + Foundry SDK   │
                       │                           └──────────┬──────────────┘
                       │                                      │
                       │  OpenAI-compatible API               │ OpenAI-compatible API
                       │  (Azure AD token)                    │ (Azure AD token)
                       │                                      │
                       └──────────────┬───────────────────────┘
                                      │
                                      ▼
                       ┌──────────────────────────────────────┐
                       │     Azure AI Foundry Agent            │
                       │                                       │
                       │  Endpoint:                            │
                       │  https://<acct>.services.ai.azure.com │
                       │         /api/projects/<project>       │
                       │                                       │
                       │  Agent: <name>:<version>              │
                       │  Model: GPT-4                         │
                       │  Tools: FileSearch / AI Search        │
                       │                                       │
                       │  The agent doesn't know or care       │
                       │  which channel called it.             │
                       └───────────────────────────────────────┘
```

### Summary

| Concern | Solution |
|---------|----------|
| Foundry agent endpoint | `https://<account>.services.ai.azure.com/api/projects/<project>` — scoped to a project, provisioned via Bicep or existing resource ID |
| API compatibility | OpenAI-compatible REST API (Responses API) — any HTTP client can call it |
| Native A2A exposure | Not supported — Foundry agents speak OpenAI API, not A2A |
| A2A outbound (agent calls A2A) | Supported via A2A Tool in Foundry portal |
| A2A inbound (agent receives A2A) | Requires an A2A server wrapper (Semantic Kernel, a2a-sdk, custom) |
| APIM for A2A governance | Import A2A Agent API in APIM v2 — auto-transforms Agent Card, adds policies, telemetry |
| Multi-channel | Build channel adapters that all call the same Foundry endpoint |

---

## Sources

- [Azure AI Foundry Agent Service REST API Reference](https://learn.microsoft.com/en-us/rest/api/aifoundry/aiagents/)
- [Azure OpenAI Responses API](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/responses?view=foundry-classic)
- [Add an A2A Agent Endpoint to Foundry Agent Service](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/agent-to-agent?view=foundry)
- [A2A Authentication in Foundry](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/agent-to-agent-authentication?view=foundry)
- [Import an A2A Agent API in Azure API Management (Preview)](https://learn.microsoft.com/en-us/azure/api-management/agent-to-agent-api)
- [Govern, Secure, and Observe A2A APIs with Azure APIM](https://techcommunity.microsoft.com/blog/integrationsonazureblog/preview-govern-secure-and-observe-a2a-apis-with-azure-api-management/4469800)
- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [Building AI Agents with the A2A .NET SDK](https://devblogs.microsoft.com/foundry/building-ai-agents-a2a-dotnet-sdk/)
- [Semantic Kernel Python + A2A Integration](https://devblogs.microsoft.com/foundry/semantic-kernel-a2a-integration/)
- [Deploying AI Foundry Agents + A2A to Azure Container Apps](https://baeke.info/2025/07/16/deploying-ai-foundry-agents-and-azure-container-apps-to-support-an-agent2agent-solution/)
- [Agent Factory: Connecting Agents with MCP and A2A](https://azure.microsoft.com/en-us/blog/agent-factory-connecting-agents-apps-and-data-with-new-open-standards-like-mcp-and-a2a/)
- [Microsoft Agent Framework: A2A Agent Type](https://learn.microsoft.com/en-us/agent-framework/user-guide/agents/agent-types/a2a-agent)
- [Announcing the Responses API in Azure AI Foundry](https://azure.microsoft.com/en-us/blog/announcing-the-responses-api-and-computer-using-agent-in-azure-ai-foundry/)
