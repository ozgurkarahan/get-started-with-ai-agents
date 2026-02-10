import logging
import os
from typing import AsyncGenerator

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import AgentReference
from azure.identity.aio import DefaultAzureCredential
from openai import AsyncOpenAI

logger = logging.getLogger("a2a_server")


class FoundryClient:
    """Client for invoking an Azure AI Foundry agent.

    Replicates the pattern from src/api/main.py and src/api/routes.py:
    - DefaultAzureCredential with managed identity
    - AIProjectClient -> get_openai_client()
    - responses.create() with AgentReference
    """

    def __init__(self) -> None:
        self._credential: DefaultAzureCredential | None = None
        self._project_client: AIProjectClient | None = None
        self._agent_name: str = ""
        self._agent_version: str = ""

    async def startup(self) -> None:
        proj_endpoint = os.environ["AZURE_EXISTING_AIPROJECT_ENDPOINT"]
        agent_id = os.environ.get("AZURE_EXISTING_AGENT_ID", "")
        agent_name_env = os.environ.get("AZURE_AI_AGENT_NAME", "agent-template-assistant")

        self._credential = DefaultAzureCredential()
        self._project_client = AIProjectClient(
            endpoint=proj_endpoint, credential=self._credential
        )

        # Try explicit agent ID first (name:version format)
        if agent_id and agent_id.count(":") == 1:
            self._agent_name, self._agent_version = agent_id.split(":")
            agent_obj = await self._project_client.agents.get_version(
                self._agent_name, self._agent_version
            )
            logger.info("Foundry client started with explicit agent ID: %s", agent_obj.id)
        else:
            # Discover agent by name (same pattern as gunicorn.conf.py)
            logger.info("No explicit agent ID, discovering by name: %s", agent_name_env)
            agents = await self._project_client.agents.get(agent_name_env)
            agent_obj = agents.versions.latest
            self._agent_name = agent_obj.name
            self._agent_version = agent_obj.version
            logger.info(
                "Foundry client started with discovered agent: %s:%s",
                self._agent_name, self._agent_version,
            )

    async def shutdown(self) -> None:
        if self._project_client:
            await self._project_client.close()
        if self._credential:
            await self._credential.close()
        logger.info("Foundry client shut down")

    async def invoke_sync(self, message: str) -> str:
        """Send a message and return the full response text."""
        async with self._project_client.get_openai_client() as openai_client:
            return await self._call_agent(openai_client, message, stream=False)

    async def invoke_stream(self, message: str) -> AsyncGenerator[str, None]:
        """Send a message and yield response text deltas."""
        async with self._project_client.get_openai_client() as openai_client:
            conv = await openai_client.conversations.create()
            response = await openai_client.responses.create(
                conversation=conv.id,
                input=message,
                extra_body={
                    "agent": AgentReference(
                        name=self._agent_name, version=self._agent_version
                    ).as_dict()
                },
                stream=True,
            )
            async for event in response:
                if event.type == "response.output_text.delta":
                    yield event.delta

    async def _call_agent(
        self, openai_client: AsyncOpenAI, message: str, *, stream: bool
    ) -> str:
        conv = await openai_client.conversations.create()
        logger.info("Created conversation %s", conv.id)

        response = await openai_client.responses.create(
            conversation=conv.id,
            input=message,
            extra_body={
                "agent": AgentReference(
                    name=self._agent_name, version=self._agent_version
                ).as_dict()
            },
            stream=stream,
        )

        if stream:
            full_text = ""
            async for event in response:
                if event.type == "response.output_text.delta":
                    full_text += event.delta
            return full_text
        else:
            return response.output_text
