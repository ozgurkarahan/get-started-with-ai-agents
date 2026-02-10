# Azure AI Foundry: Endpoint Architecture, API Compatibility & A2A Exposition

## Table of Contents

- [1. Azure AI Foundry Resource Hierarchy](#1-azure-ai-foundry-resource-hierarchy)
- [2. AI Foundry Project Endpoint](#2-ai-foundry-project-endpoint)
- [3. OpenAI-Compatible API Surface](#3-openai-compatible-api-surface)
- [4. How This Project Consumes the Agent](#4-how-this-project-consumes-the-agent)
- [5. Multi-Channel Compatibility](#5-multi-channel-compatibility)
- [6. A2A Protocol Overview](#6-a2a-protocol-overview)
- [7. Foundry Agent + A2A: Current State](#7-foundry-agent--a2a-current-state)
- [8. Exposing a Foundry Agent via A2A + Azure APIM](#8-exposing-a-foundry-agent-via-a2a--azure-apim)
- [9. End-to-End Architecture](#9-end-to-end-architecture)
- [10. Implementation Details](#10-implementation-details)
- [11. Connecting APIM as AI Gateway in AI Foundry](#11-connecting-apim-as-ai-gateway-in-ai-foundry)
- [Sources](#sources)

---

## 1. Azure AI Foundry Resource Hierarchy

### Overview

Azure AI Foundry organizes resources in a hierarchical structure. Understanding this
hierarchy is essential because the **project endpoint**, **agent**, **model**, and
**connections** are all scoped within it.

### Complete Resource Tree

```
Azure Subscription
│
└── Resource Group  (rg-<environment>)
    │
    ├── Microsoft.CognitiveServices/accounts  (AI Services Account)
    │   │
    │   │   The top-level resource. Kind: "AIServices". Hosts model deployments,
    │   │   connections, and projects. Has its own system-assigned managed identity.
    │   │   SKU: S0.
    │   │
    │   │   Key properties:
    │   │   - allowProjectManagement: true
    │   │   - customSubDomainName: <account-name>
    │   │   - endpoints:
    │   │       'OpenAI Language Model Instance API' → used by AOAI connection
    │   │       'AI Foundry API' → used by project endpoint
    │   │
    │   ├── /connections/aoai-connection  (Azure OpenAI Connection)
    │   │       category: AzureOpenAI
    │   │       authType: AAD (Entra ID)
    │   │       target: account.endpoints['OpenAI Language Model Instance API']
    │   │       Points back to the same account's OpenAI endpoint.
    │   │
    │   ├── /connections/appinsights-connection  (App Insights Connection)
    │   │       category: AppInsights
    │   │       authType: ApiKey
    │   │       Links telemetry data to Application Insights.
    │   │
    │   ├── /connections/storageAccount  (Storage Connection)
    │   │       category: AzureStorageAccount
    │   │       authType: AAD (Entra ID)
    │   │       target: storage account blob endpoint
    │   │       Used for file uploads (knowledge base documents).
    │   │
    │   ├── /deployments/gpt-5-mini  (Chat Model Deployment)
    │   │       model:
    │   │         format: OpenAI
    │   │         name: gpt-5-mini
    │   │         version: 2024-07-18
    │   │       sku: GlobalStandard, capacity: 30
    │   │       This is the LLM that powers the agent.
    │   │
    │   ├── /deployments/text-embedding-3-small  (Embedding Model Deployment)
    │   │       model:
    │   │         format: OpenAI
    │   │         name: text-embedding-3-small
    │   │         version: 1
    │   │       sku: Standard, capacity: 30
    │   │       Only deployed when Azure AI Search is enabled (useSearchService=true).
    │   │       Used by the search skillset for vectorization.
    │   │
    │   └── /projects/<project-name>  (AI Foundry Project)
    │       │
    │       │   The project is a CHILD resource of the AI Services account.
    │       │   It has its own system-assigned managed identity.
    │       │   All agent operations are scoped to this project.
    │       │
    │       │   Key output:
    │       │   - projectEndpoint = properties.endpoints['AI Foundry API']
    │       │     → https://<account>.services.ai.azure.com/api/projects/<project>
    │       │   - projectResourceId = /subscriptions/.../accounts/<acct>/projects/<proj>
    │       │
    │       └── /connections/search  (AI Search Connection) [optional]
    │               category: CognitiveSearch
    │               authType: ApiKey
    │               target: https://<search>.search.windows.net/
    │               Only created when Azure AI Search is enabled.
    │
    ├── Microsoft.Storage/storageAccounts  (Storage Account)
    │       Hosts blob containers for document storage.
    │       Used by:
    │       - File uploads for agent knowledge base
    │       - Azure AI Search datasource (indexer reads from here)
    │
    ├── Microsoft.Search/searchServices  (Azure AI Search) [optional]
    │       SKU: basic
    │       semanticSearch: free
    │       Only deployed when useSearchService=true.
    │       Connected to the project via a search connection.
    │       Has its own system-assigned identity for accessing blob storage.
    │
    ├── Microsoft.OperationalInsights/workspaces  (Log Analytics)
    │       Backend for Application Insights.
    │
    ├── Microsoft.Insights/components  (Application Insights) [optional]
    │       Application performance monitoring and distributed tracing.
    │       Connected to the AI Services account via appinsights-connection.
    │
    ├── Microsoft.App/managedEnvironments  (Container Apps Environment)
    │       Hosting environment for the container app.
    │
    ├── Microsoft.App/containerApps  (Container App - the web application)
    │       Runs the FastAPI + React app.
    │       Target port: 50505.
    │       Uses a user-assigned managed identity for Azure AD auth.
    │
    ├── Microsoft.ContainerRegistry/registries  (Container Registry)
    │       Stores the Docker image built from src/Dockerfile.
    │
    └── Microsoft.ManagedIdentity/userAssignedIdentities  (App Identity)
            Used by the Container App to authenticate to AI Services.
```

### How Resources Relate to Each Other

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AI Services Account                               │
│                    (Microsoft.CognitiveServices/accounts)            │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ gpt-5-mini    │  │ text-embed-  │  │  Connections              │  │
│  │ deployment    │  │ 3-small      │  │  ├── aoai-connection      │  │
│  │               │  │ deployment   │  │  ├── appinsights-conn     │  │
│  │ (chat model)  │  │ (embeddings) │  │  └── storageAccount      │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────────┘  │
│         │                 │                                          │
│  ┌──────▼─────────────────▼──────────────────────────────────────┐  │
│  │              AI Foundry Project                                │  │
│  │              (child resource of account)                       │  │
│  │                                                                │  │
│  │  project endpoint:                                             │  │
│  │  https://<acct>.services.ai.azure.com/api/projects/<proj>     │  │
│  │                                                                │  │
│  │  ┌────────────────────────────────────────────────────────┐   │  │
│  │  │  AI Agent (created at runtime via SDK)                  │   │  │
│  │  │                                                         │   │  │
│  │  │  name: agent-template-assistant                         │   │  │
│  │  │  model: gpt-5-mini (references the deployment above)    │   │  │
│  │  │  tools: FileSearchTool OR AzureAISearchAgentTool        │   │  │
│  │  │  instructions: "Use File Search always with citations"  │   │  │
│  │  │                                                         │   │  │
│  │  │  ID format: <agent-name>:<version>                      │   │  │
│  │  └────────────────────────────────────────────────────────┘   │  │
│  │                                                                │  │
│  │  Optional: /connections/search → AI Search service             │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
         │                              │                     │
         │ AAD auth                     │ AAD auth            │ API key
         ▼                              ▼                     ▼
┌────────────────┐            ┌─────────────────┐   ┌────────────────┐
│ Storage Account │            │  AI Search       │   │ App Insights   │
│ (blob: docs)    │            │  (index, indexer) │   │ (telemetry)    │
└────────────────┘            └─────────────────┘   └────────────────┘
```

### Resource Construction in Bicep (This Project)

The infrastructure is built in layers via Bicep modules:

```
main.bicep                          (orchestrator)
  │
  ├── ai-environment.bicep          (creates all AI resources together)
  │     │
  │     ├── storage-account.bicep       → Storage Account
  │     ├── loganalytics.bicep          → Log Analytics Workspace
  │     ├── applicationinsights.bicep   → App Insights
  │     ├── cognitiveservices.bicep     → AI Services Account
  │     │     │                              + AI Project (child)
  │     │     │                              + AOAI Connection
  │     │     │                              + App Insights Connection
  │     │     │                              + Storage Connection
  │     │     │                              + Model Deployments
  │     │     │
  │     │     └── outputs: projectEndpoint, projectResourceId, ...
  │     │
  │     └── search-services.bicep       → AI Search [optional]
  │           │                              + Search Connection (on project)
  │           └── outputs: endpoint, searchConnectionId
  │
  ├── container-apps.bicep          (Container Apps Environment + Registry)
  │
  └── api.bicep                     (Container App + env vars)
        │
        └── Injects all config as environment variables:
              AZURE_EXISTING_AIPROJECT_ENDPOINT
              AZURE_EXISTING_AGENT_ID
              AZURE_AI_AGENT_DEPLOYMENT_NAME
              AZURE_AI_AGENT_NAME
              ... (17 env vars total)
```

### Model Deployment Details

The project deploys two models (configured in `infra/main.bicep`):

#### Chat Model (Always deployed)

| Property | Value | Bicep Param |
|----------|-------|-------------|
| Name | `gpt-5-mini` | `agentModelName` |
| Deployment name | `gpt-5-mini` | `agentDeploymentName` |
| Format | `OpenAI` | `agentModelFormat` |
| Version | `2024-07-18` | `agentModelVersion` |
| SKU | `GlobalStandard` | `agentDeploymentSku` |
| Capacity | `30` (TPM) | `agentDeploymentCapacity` |

This model is referenced by the agent definition at runtime:

```python
# gunicorn.conf.py - agent creation
agent = await ai_project.agents.create_version(
    agent_name=os.environ["AZURE_AI_AGENT_NAME"],     # "agent-template-assistant"
    definition=PromptAgentDefinition(
        model=os.environ["AZURE_AI_AGENT_DEPLOYMENT_NAME"],  # "gpt-5-mini"
        instructions=instructions,
        tools=tools,
    ),
)
```

#### Embedding Model (Only when AI Search is enabled)

| Property | Value | Bicep Param |
|----------|-------|-------------|
| Name | `text-embedding-3-small` | `embedModelName` |
| Deployment name | `text-embedding-3-small` | `embeddingDeploymentName` |
| Format | `OpenAI` | `embedModelFormat` |
| Version | `1` | `embedModelVersion` |
| SKU | `Standard` | `embedDeploymentSku` |
| Capacity | `30` (TPM) | `embedDeploymentCapacity` |
| Dimensions | `100` | `embeddingDeploymentDimensions` |

The embedding model is used by the Azure AI Search skillset to generate vector
embeddings when indexing documents. It is NOT used directly by the agent.

```python
# gunicorn.conf.py - embedding client (used by search indexer)
embedding_client = AsyncAzureOpenAI(
    azure_endpoint=aoai_connection.target,
    azure_ad_token_provider=creds.get_token
)
search_mgr = SearchIndexManager(
    model=embedding,                    # "text-embedding-3-small"
    dimensions=int(os.getenv('AZURE_AI_EMBED_DIMENSIONS', '1536')),  # 100
    embedding_client=embedding_client
)
```

### Region Constraints

Model deployments are region-limited. This project restricts deployment to:

| Region | Code |
|--------|------|
| East US | `eastus` |
| East US 2 | `eastus2` |
| Sweden Central | `swedencentral` |
| West US | `westus` |
| West US 3 | `westus3` |

These are the regions where `gpt-5-mini` supports agent creation via the Foundry
Agent Service.

### Identity & RBAC

The project uses **five managed identities** with specific role assignments:

```
┌─────────────────────────────────────────────────────────────────┐
│  AI Services Account Identity (System-Assigned)                  │
│  Principal: 16f8dbdc-61c3-42ff-a3c7-8692833c692e                │
│  Roles:                                                          │
│  - Storage Blob Data Contributor (on storage account)            │
│  - API Management Service Reader (on oz-ai-gateway APIM)         │
│  Purpose: Account-level access to blob storage + APIM gateway    │
├──────────────────────────────────────────────────────────────────┤
│  AI Project Identity (System-Assigned)                           │
│  Roles: Storage Blob Data Contributor + Azure AI User            │
│  Purpose: Project-level access to storage and AI services        │
├──────────────────────────────────────────────────────────────────┤
│  Container App Identity (User-Assigned)                          │
│  Roles:                                                          │
│  - Azure AI Developer (on resource group)                        │
│  - Azure AI User (on resource group)                             │
│  - Cognitive Services User (on resource group)                   │
│  - Storage Blob Data Contributor [if search enabled]             │
│  - Search Index Data Contributor [if search enabled]             │
│  - Search Index Data Reader [if search enabled]                  │
│  - Search Service Contributor [if search enabled]                │
│  - Storage Account Contributor [if search enabled]               │
│  Purpose: The web app authenticates as this identity to call     │
│           the AI Foundry Project endpoint via DefaultAzureCredential │
├──────────────────────────────────────────────────────────────────┤
│  APIM Identity (System-Assigned)                                 │
│  Principal: 2537ea5e-881b-4c5f-9e72-5861340170b8                │
│  Roles:                                                          │
│  - Cognitive Services User (on aoai-c544zegk5tvc2)               │
│  Purpose: Allows APIM to call AI Foundry endpoints using         │
│           managed identity auth (no API keys)                    │
└──────────────────────────────────────────────────────────────────┘
```

### Agent Lifecycle (Runtime vs Infrastructure)

The agent itself is **not an Azure ARM resource** — it is not created by Bicep.
Instead, it is created at **application runtime** via the SDK:

```
INFRASTRUCTURE (Bicep/ARM)              RUNTIME (Python SDK)
─────────────────────────               ────────────────────
AI Services Account          ─────▶     AIProjectClient(endpoint=...)
  └── Project                               │
  └── Model Deployments                     ├── agents.create_version()
  └── Connections                           │     → creates the agent
                                            │     → assigns model + tools
                                            │
                                            ├── agents.get_version()
                                            │     → fetches existing agent
                                            │
                                            └── get_openai_client()
                                                  → conversations, responses
```

The Bicep outputs provide the **agent name** (`AZURE_AI_AGENT_NAME`) and optionally
an existing **agent ID** (`AZURE_EXISTING_AGENT_ID`), but the agent definition
(model, instructions, tools) is managed by `gunicorn.conf.py` at startup time.

### Environment Variables Summary

All configuration flows from Bicep outputs → Container App env vars → Python code:

| Env Var | Source | Used By |
|---------|--------|---------|
| `AZURE_EXISTING_AIPROJECT_ENDPOINT` | `projectEndpoint` (Bicep output) | `main.py` → `AIProjectClient` |
| `AZURE_EXISTING_AIPROJECT_RESOURCE_ID` | `projectResourceId` (Bicep output) | `routes.py` → playground URL |
| `AZURE_EXISTING_AGENT_ID` | `agentID` param or set at runtime | `main.py` → agent fetch |
| `AZURE_AI_AGENT_NAME` | `agentName` param | `gunicorn.conf.py` → agent creation |
| `AZURE_AI_AGENT_DEPLOYMENT_NAME` | `agentDeploymentName` param | `gunicorn.conf.py` → model reference |
| `AZURE_AI_EMBED_DEPLOYMENT_NAME` | `embeddingDeploymentName` param | `gunicorn.conf.py` → search embeddings |
| `AZURE_AI_EMBED_DIMENSIONS` | `embeddingDeploymentDimensions` param | `gunicorn.conf.py` → vector index |
| `AZURE_AI_SEARCH_ENDPOINT` | `searchServiceEndpoint` (Bicep output) | `gunicorn.conf.py` → search manager |
| `AZURE_AI_SEARCH_INDEX_NAME` | `aiSearchIndexName` param | `gunicorn.conf.py` → index name |
| `SEARCH_CONNECTION_ID` | `searchConnectionId` (Bicep output) | `gunicorn.conf.py` → AI Search tool |
| `STORAGE_ACCOUNT_RESOURCE_ID` | `storageAccountId` (Bicep output) | `gunicorn.conf.py` → blob connection |
| `AZURE_BLOB_CONTAINER_NAME` | `blobContainerName` param | `gunicorn.conf.py` → container name |
| `USE_AZURE_AI_SEARCH_SERVICE` | `useAzureAISearch` param | `gunicorn.conf.py` → tool selection |
| `AZURE_CLIENT_ID` | Container App identity | `DefaultAzureCredential` |
| `RUNNING_IN_PRODUCTION` | hardcoded `true` | `main.py` → skip local .env |
| `ENABLE_AZURE_MONITOR_TRACING` | `enableAzureMonitorTracing` param | `main.py` → telemetry setup |

---

## 2. AI Foundry Project Endpoint

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

## 3. OpenAI-Compatible API Surface

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

## 4. How This Project Consumes the Agent

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

## 5. Multi-Channel Compatibility

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

## 6. A2A Protocol Overview

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

## 7. Foundry Agent + A2A: Current State

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

## 8. Exposing a Foundry Agent via A2A + Azure APIM

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

## 9. End-to-End Architecture

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

## 10. Implementation Details

This section documents the actual A2A server implementation built for this project.

### File Structure

```
src/a2a_server/
  __init__.py               # Package marker
  main.py                   # Starlette entry point (A2AStarletteApplication)
  agent_executor.py          # FoundryAgentExecutor - A2A -> Foundry translation
  foundry_client.py          # FoundryClient - AIProjectClient + OpenAI wrapper
  agent_card_config.py       # Agent Card definition
  requirements.txt           # Python dependencies (a2a-sdk, azure SDKs)
  Dockerfile                 # Container image (python:3.13.9-slim, port 8080)
```

### Infrastructure (Bicep)

```
infra/
  a2a-server.bicep           # Container App module (mirrors api.bicep)
  apim/
    apim-a2a-api.bicep       # APIM backend, product, logger
  main.bicep                 # Updated: new params, A2A module, RBAC, outputs
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| A2A SDK | `a2a-sdk[http-server]==0.3.22` | Official SDK, Starlette integration |
| Stateless | Each A2A task = new Foundry conversation | Simplicity, no session management |
| Streaming | Disabled in v1 (`capabilities.streaming: false`) | Simpler initial implementation |
| Identity | Separate user-assigned managed identity | Follows existing api.bicep pattern |
| Port | 8080 | Distinct from web app (50505) |

### APIM Configuration (Portal)

After deploying the A2A Container App, complete the APIM setup in Azure Portal:

1. Navigate to `oz-ai-gateway` > APIs > + Add API > **A2A Agent**
2. Enter Agent Card URL: `https://ca-a2a-{token}.{region}.azurecontainerapps.io/.well-known/agent.json`
3. APIM auto-discovers the agent (name, skills, runtime URL)
4. Configure policies: rate limiting, JWT validation, telemetry headers
5. Associate with the `a2a-agents` product

### Deployment Sequence

```bash
# 1. Enable A2A server
azd env set DEPLOY_A2A_SERVER true
azd env set APIM_SERVICE_NAME oz-ai-gateway

# 2. Deploy all infrastructure + apps
azd up

# 3. Import A2A API in APIM (Portal, manual)
# 4. Configure APIM policies (Portal, manual)
```

### Testing

```bash
# Direct A2A server test
curl https://ca-a2a-{token}.{region}.azurecontainerapps.io/.well-known/agent.json

# Via APIM
curl https://oz-ai-gateway.azure-api.net/{path}/.well-known/agent.json \
  -H "Ocp-Apim-Subscription-Key: <key>"
```

### Architecture Diagram (with resource names)

```
External Agent
    │
    │  A2A (JSON-RPC 2.0)
    ▼
┌──────────────────────────┐
│  oz-ai-gateway (APIM)    │  BasicV2, swedencentral
│  Ocp-Apim-Subscription   │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  ca-a2a-{token}          │  Container App, port 8080
│  A2A Server (Starlette)  │
│  id-a2a-{token}          │  User-assigned identity
└──────────┬───────────────┘
           │  OpenAI API + Azure AD
           ▼
┌──────────────────────────┐
│  ca-api-c544zegk5tvc2    │  Existing Foundry agent
│  AI Foundry Project      │
│  aoai-c544zegk5tvc2      │  AI Services account
└──────────────────────────┘
```

---

## 11. Connecting APIM as AI Gateway in AI Foundry

To use Azure API Management as an AI Gateway in AI Foundry, APIM must be registered
as a connected resource on the AI Foundry project. Without this connection, the
AI Foundry portal reports "no service principal ID" when attempting to add the gateway.

### Prerequisites

| Resource | Status | Details |
|----------|--------|---------|
| APIM instance | `oz-ai-gateway` | Must have system-assigned managed identity enabled |
| APIM identity | `2537ea5e-881b-4c5f-9e72-5861340170b8` | Needs `Cognitive Services User` role on AI Services account |
| AI Services account | `aoai-c544zegk5tvc2` | Must have system-assigned managed identity enabled |
| AI Services identity | `16f8dbdc-61c3-42ff-a3c7-8692833c692e` | Needs `API Management Service Reader` role on APIM |

### What Was Configured

#### 1. APIM → AI Services Role Assignment (already existed)

APIM's managed identity was granted `Cognitive Services User` on the AI Services
account. This allows APIM to forward requests to AI Foundry endpoints using
managed identity authentication instead of API keys.

```bash
az role assignment create \
  --assignee-object-id 2537ea5e-881b-4c5f-9e72-5861340170b8 \
  --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services User" \
  --scope "/subscriptions/44026b8b-9f88-44d9-8f46-0898baa4bcd5/resourceGroups/rg-ai-search-agent/providers/Microsoft.CognitiveServices/accounts/aoai-c544zegk5tvc2"
```

#### 2. AI Foundry Project Connection (was missing)

The AI Foundry project needs an `ApiManagement` category connection that points
to the APIM instance and includes its service principal ID. Without this, the
portal cannot discover the gateway.

Created via REST API:

```bash
az rest --method PUT \
  --url "https://management.azure.com/subscriptions/44026b8b-9f88-44d9-8f46-0898baa4bcd5/resourceGroups/rg-ai-search-agent/providers/Microsoft.CognitiveServices/accounts/aoai-c544zegk5tvc2/projects/proj-c544zegk5tvc2/connections/apim-gateway?api-version=2025-06-01" \
  --body '{
    "properties": {
      "authType": "AAD",
      "category": "ApiManagement",
      "target": "https://oz-ai-gateway.azure-api.net",
      "isSharedToAll": true,
      "metadata": {
        "ApiType": "Azure",
        "ResourceId": "/subscriptions/.../providers/Microsoft.ApiManagement/service/oz-ai-gateway",
        "ServicePrincipalId": "2537ea5e-881b-4c5f-9e72-5861340170b8"
      }
    }
  }'
```

The key fields:
- **category**: `ApiManagement` — identifies this as an APIM gateway connection
- **authType**: `AAD` — uses Entra ID managed identity, not API keys
- **target**: The APIM gateway URL
- **ServicePrincipalId**: The APIM managed identity principal — this is what resolves
  the "no service principal ID" error in the portal

#### 3. AI Services → APIM Role Assignment (was missing)

The AI Services account's managed identity needs read access to the APIM instance
so AI Foundry can query gateway configuration:

```bash
az rest --method PUT \
  --url "https://management.azure.com/.../providers/Microsoft.ApiManagement/service/oz-ai-gateway/providers/Microsoft.Authorization/roleAssignments/{guid}?api-version=2022-04-01" \
  --body '{
    "properties": {
      "roleDefinitionId": "/subscriptions/.../providers/Microsoft.Authorization/roleDefinitions/71522526-b88f-4d52-b57f-d31fc3546d0d",
      "principalId": "16f8dbdc-61c3-42ff-a3c7-8692833c692e",
      "principalType": "ServicePrincipal"
    }
  }'
```

Role definition `71522526-b88f-4d52-b57f-d31fc3546d0d` = **API Management Service Reader Role**.

### Connection Topology

```
┌──────────────────────────────────────────────────────────────────┐
│  AI Services Account: aoai-c544zegk5tvc2                          │
│  Identity: 16f8dbdc-...                                           │
│                                                                    │
│  └── Project: proj-c544zegk5tvc2                                  │
│        │                                                           │
│        ├── connection: aoai-connection     → Azure OpenAI          │
│        ├── connection: appinsights-conn    → App Insights          │
│        ├── connection: storageAccount      → Blob Storage          │
│        ├── connection: search              → AI Search             │
│        └── connection: apim-gateway (NEW)  → APIM Gateway          │
│              category: ApiManagement                                │
│              target: https://oz-ai-gateway.azure-api.net           │
│              ServicePrincipalId: 2537ea5e-...                      │
│                                                                    │
└───────────────────┬──────────────────────────────────────────────┘
                    │  API Management Service Reader
                    ▼
┌──────────────────────────────────────────────────────────────────┐
│  APIM: oz-ai-gateway                                               │
│  Identity: 2537ea5e-...                                            │
│  Gateway: https://oz-ai-gateway.azure-api.net                      │
│                                                                    │
└───────────────────┬──────────────────────────────────────────────┘
                    │  Cognitive Services User
                    ▼
┌──────────────────────────────────────────────────────────────────┐
│  AI Services Account: aoai-c544zegk5tvc2                          │
│  Endpoint: https://aoai-c544zegk5tvc2.cognitiveservices.azure.com │
└──────────────────────────────────────────────────────────────────┘
```

### Verification

List project connections and confirm the APIM gateway appears:

```bash
az rest --method GET \
  --url "https://management.azure.com/subscriptions/44026b8b-9f88-44d9-8f46-0898baa4bcd5/resourceGroups/rg-ai-search-agent/providers/Microsoft.CognitiveServices/accounts/aoai-c544zegk5tvc2/projects/proj-c544zegk5tvc2/connections?api-version=2025-06-01" \
  --query "value[?properties.category=='ApiManagement'].{name:name, target:properties.target, principal:properties.metadata.ServicePrincipalId}" \
  -o table
```

Expected output:

```
Name          Target                                 Principal
-----------   ------------------------------------   ------------------------------------
apim-gateway  https://oz-ai-gateway.azure-api.net    2537ea5e-881b-4c5f-9e72-5861340170b8
```

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
