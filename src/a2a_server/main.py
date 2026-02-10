import logging
import os
import sys

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent_card_config import build_agent_card
from agent_executor import FoundryAgentExecutor
from foundry_client import FoundryClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("a2a_server")

# Reduce Azure SDK noise so we can see application errors
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("azure.monitor").setLevel(logging.WARNING)
logging.getLogger("azure.core").setLevel(logging.WARNING)

# Optionally enable Azure Monitor tracing
enable_trace_str = os.getenv("ENABLE_AZURE_MONITOR_TRACING", "").lower()
if enable_trace_str == "true":
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        logger.info("Azure Monitor tracing enabled for A2A server")
    except ModuleNotFoundError:
        logger.warning("azure-monitor-opentelemetry not installed, tracing disabled")
        enable_trace_str = ""

# Create Foundry client and A2A executor
foundry_client = FoundryClient()
executor = FoundryAgentExecutor(foundry_client)

# Build A2A components
agent_card = build_agent_card()
request_handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=InMemoryTaskStore(),
)
a2a_app = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=request_handler,
)


async def health(request):
    return JSONResponse({"status": "healthy"})


async def on_startup():
    # Configure tracing if enabled
    if enable_trace_str == "true":
        try:
            from azure.ai.projects.aio import AIProjectClient
            from azure.identity.aio import DefaultAzureCredential

            proj_endpoint = os.environ.get("AZURE_EXISTING_AIPROJECT_ENDPOINT", "")
            if proj_endpoint:
                async with DefaultAzureCredential() as cred:
                    async with AIProjectClient(
                        endpoint=proj_endpoint, credential=cred
                    ) as client:
                        conn_str = await client.telemetry.get_application_insights_connection_string()
                        if conn_str:
                            configure_azure_monitor(connection_string=conn_str)
                            logger.info("Configured Azure Monitor for A2A server")
        except Exception as e:
            logger.warning("Failed to configure Azure Monitor: %s", e)

    await foundry_client.startup()
    logger.info("A2A server started")


async def on_shutdown():
    await foundry_client.shutdown()
    logger.info("A2A server stopped")


# Build the Starlette app — A2A routes + health check
starlette_app = a2a_app.build()
starlette_app.add_route("/health", health, methods=["GET"])
starlette_app.add_event_handler("startup", on_startup)
starlette_app.add_event_handler("shutdown", on_shutdown)

app = starlette_app

if __name__ == "__main__":
    port = int(os.getenv("A2A_SERVER_PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
