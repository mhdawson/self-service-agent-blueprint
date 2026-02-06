"""A2A Agent Manager for discovering and communicating with A2A agents using a2a-sdk."""

import json
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import structlog
from a2a.types import AgentCard

logger = structlog.get_logger(__name__)


class A2AAgentInfo:
    """Container for A2A agent information."""

    def __init__(self, name: str, url: str, agent_card: AgentCard):
        self.name = name
        self.url = url
        self.agent_card = agent_card


class A2AAgentManager:
    """Manages remote A2A agent connections using official a2a-sdk."""

    def __init__(self):
        """Initialize the A2A agent manager."""
        self.a2a_agents: Dict[str, A2AAgentInfo] = {}
        self._load_a2a_agents()

    def _load_a2a_agents(self):
        """Load A2A agent configurations from agent cards."""
        # Find the config directory
        # Try multiple paths to handle different execution contexts
        possible_paths = [
            Path(__file__).parent.parent / "config" / "a2a-agents",
            Path("/app/agent-service/config/a2a-agents"),
            Path("config/a2a-agents"),
        ]

        config_dir = None
        for path in possible_paths:
            if path.exists():
                config_dir = path
                break

        if not config_dir or not config_dir.exists():
            logger.warning(
                "A2A agents config directory not found",
                searched_paths=[str(p) for p in possible_paths],
            )
            return

        logger.info(
            "Loading A2A agent configurations", config_dir=str(config_dir)
        )

        # Load all agent card files
        agent_cards_found = 0
        for card_file in config_dir.glob("*-card.json"):
            try:
                # Extract agent name from filename (remove -card.json suffix)
                agent_name = card_file.stem.replace("-card", "")

                with open(card_file, "r") as f:
                    card_data = json.load(f)

                # Parse into AgentCard object using a2a-sdk types
                agent_card = AgentCard(**card_data)

                # Get base URL from agent card
                base_url = agent_card.url
                if not base_url:
                    logger.warning(
                        "Agent card missing 'url' field",
                        agent_name=agent_name,
                        card_file=str(card_file),
                    )
                    continue

                # Store agent information
                agent_info = A2AAgentInfo(
                    name=agent_name,
                    url=base_url,
                    agent_card=agent_card
                )

                self.a2a_agents[agent_name] = agent_info
                agent_cards_found += 1

                logger.info(
                    "Loaded A2A agent",
                    agent_name=agent_name,
                    display_name=agent_card.name,
                    url=base_url,
                    description=agent_card.description,
                    skills_count=len(agent_card.skills) if agent_card.skills else 0,
                )

            except Exception as e:
                logger.error(
                    "Failed to load A2A agent card",
                    card_file=str(card_file),
                    error=str(e),
                    error_type=type(e).__name__,
                )

        logger.info(
            "A2A agent loading complete",
            agents_loaded=agent_cards_found,
            agent_names=list(self.a2a_agents.keys()),
        )

    def get_agent_info(self, agent_name: str) -> Optional[A2AAgentInfo]:
        """
        Get agent information by name.

        Args:
            agent_name: Name of the agent

        Returns:
            A2AAgentInfo if found, None otherwise
        """
        return self.a2a_agents.get(agent_name)

    def get_agent_card(self, agent_name: str) -> Optional[AgentCard]:
        """
        Get agent card by name.

        Args:
            agent_name: Name of the agent

        Returns:
            AgentCard if found, None otherwise
        """
        agent_info = self.a2a_agents.get(agent_name)
        return agent_info.agent_card if agent_info else None

    def get_agent_url(self, agent_name: str) -> Optional[str]:
        """
        Get agent URL by name.

        Args:
            agent_name: Name of the agent

        Returns:
            Agent URL if found, None otherwise
        """
        agent_info = self.a2a_agents.get(agent_name)
        return agent_info.url if agent_info else None

    def list_agents(self) -> List[str]:
        """
        List all available A2A agent names.

        Returns:
            List of agent names
        """
        return list(self.a2a_agents.keys())

    def get_agent_descriptions(self) -> Dict[str, str]:
        """
        Get descriptions of all available A2A agents.

        Returns:
            Dictionary mapping agent names to descriptions
        """
        return {
            name: info.agent_card.description
            for name, info in self.a2a_agents.items()
        }

    async def send_to_agent(
        self, agent_name: str, query: str
    ) -> str:
        """
        Send a query to an A2A agent and get the response.

        Args:
            agent_name: Name of the agent to query
            query: The question or request to send

        Returns:
            Response text from the agent

        Raises:
            ValueError: If agent not found
            Exception: If communication fails
        """
        from a2a.client import ClientFactory, ClientConfig
        from a2a.client.helpers import create_text_message_object
        from a2a.utils import get_message_text
        from a2a.types import Message

        agent_info = self.a2a_agents.get(agent_name)
        if not agent_info:
            raise ValueError(f"A2A agent '{agent_name}' not found")

        logger.info(
            "Sending query to A2A agent",
            agent_name=agent_name,
            query=query[:100],
        )

        # Create httpx client with timeout
        httpx_client = httpx.AsyncClient(timeout=30.0)

        try:
            # Create client config with httpx client
            client_config = ClientConfig(httpx_client=httpx_client)

            # Connect to the A2A agent using official a2a-sdk
            client = await ClientFactory.connect(
                agent=agent_info.url,
                client_config=client_config,
            )

            # Create and send message
            msg = create_text_message_object(content=query)

            logger.info(
                "Sending message to A2A agent",
                agent_name=agent_name,
                message_content=query,
            )

            response_text = ""
            event_count = 0

            # client.send_message() returns AsyncIterator[tuple[Task, Event] | Message]
            async for response in client.send_message(msg):
                event_count += 1

                logger.info(
                    "Received response from A2A agent",
                    agent_name=agent_name,
                    response_number=event_count,
                    response_type=type(response).__name__,
                )

                # Check if response is a Message (final response with text)
                if isinstance(response, Message):
                    text = get_message_text(response)
                    if text:
                        response_text = text
                        logger.info(
                            "Extracted text from Message",
                            agent_name=agent_name,
                            text_length=len(text),
                            text_preview=text[:100],
                        )
                # Otherwise it's a tuple of (Task, Event) - task updates
                elif isinstance(response, tuple):
                    task, event = response

                    # Log detailed task structure
                    task_attrs = dir(task) if task else []
                    task_state = task.status.state if task and hasattr(task, 'status') else "no-status"

                    logger.info(
                        "Received task event",
                        agent_name=agent_name,
                        event_type=type(event).__name__ if event else "None",
                        task_type=type(task).__name__ if task else "None",
                        task_state=task_state,
                        has_artifacts=bool(task.artifacts) if task and hasattr(task, 'artifacts') else False,
                        artifacts_count=len(task.artifacts) if task and hasattr(task, 'artifacts') and task.artifacts else 0,
                    )

                    # Extract text from task artifacts (plural) if present
                    if task and hasattr(task, 'artifacts') and task.artifacts:
                        from a2a.utils import get_artifact_text

                        for artifact in task.artifacts:
                            text = get_artifact_text(artifact)
                            if text:
                                response_text = text
                                logger.info(
                                    "Extracted text from task artifact",
                                    agent_name=agent_name,
                                    text_length=len(text),
                                    text_preview=text[:100],
                                )

            logger.info(
                "Received complete response from A2A agent",
                agent_name=agent_name,
                response_length=len(response_text),
                response_text=response_text,
                total_responses=event_count,
            )

            return response_text

        except Exception as e:
            logger.error(
                "Failed to communicate with A2A agent",
                agent_name=agent_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

        finally:
            # Always close the httpx client we created
            await httpx_client.aclose()
