import logging
import traceback

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message
from typing_extensions import override

from foundry_client import FoundryClient

logger = logging.getLogger("a2a_server")


class FoundryAgentExecutor(AgentExecutor):
    """Translates A2A protocol requests to Azure AI Foundry agent calls."""

    def __init__(self, foundry_client: FoundryClient) -> None:
        self._client = foundry_client

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        try:
            # Extract user message text
            user_input = context.get_user_input()
            if not user_input:
                raise Exception("No user input provided in A2A request")

            logger.info("Executing A2A task, input length: %d", len(user_input))

            # Call Foundry agent (synchronous, non-streaming)
            result = await self._client.invoke_sync(user_input)
            logger.info("Foundry agent returned result, length: %d", len(result))

            # Return result via the standard helper
            await event_queue.enqueue_event(new_agent_text_message(result))
            logger.info("Enqueued result event successfully")
        except Exception:
            logger.error("Error in executor: %s", traceback.format_exc())
            raise

    @override
    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        raise Exception("Cancel not supported")
