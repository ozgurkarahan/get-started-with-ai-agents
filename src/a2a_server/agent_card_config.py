import os

from a2a.types import AgentCapabilities, AgentCard, AgentSkill


def build_agent_card() -> AgentCard:
    """Build the A2A Agent Card describing this agent's capabilities."""
    base_url = os.getenv("A2A_SERVER_BASE_URL", "http://localhost:8080")

    return AgentCard(
        name="AI Foundry Search Agent",
        description="Answers questions using AI-powered document search over Azure AI Foundry",
        url=base_url,
        version="1.0.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="document-search",
                name="Document Search & QA",
                description="Search documents and answer questions using Azure AI Foundry agent with file search capabilities",
                tags=["document-search", "question-answering", "azure-ai-foundry"],
                input_modes=["text"],
                output_modes=["text"],
            )
        ],
    )
