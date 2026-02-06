"""FastAPI server implementing A2A protocol for Laptop Refresh Policy Agent using a2a-sdk."""

import json
import logging
from pathlib import Path
from typing import Any, Dict

import uvicorn
from starlette.responses import JSONResponse
from starlette.routing import Route
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard

from .agent_executor import LaptopRefreshPolicyAgentExecutor
from .config import SERVER_HOST, SERVER_PORT, LOG_LEVEL

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load agent card
AGENT_CARD_PATH = Path(__file__).parent.parent.parent / "agent_card.json"


def load_agent_card() -> AgentCard:
    """Load the agent card from file and convert to AgentCard object."""
    if not AGENT_CARD_PATH.exists():
        raise FileNotFoundError(
            f"Agent card file not found at {AGENT_CARD_PATH}. "
            "This file is required for the A2A agent to function."
        )

    try:
        with open(AGENT_CARD_PATH, "r") as f:
            card_data = json.load(f)

        # Convert dict to AgentCard object
        return AgentCard(**card_data)
    except Exception as e:
        logger.error(f"Error loading agent card: {e}")
        raise


# Load agent card configuration
agent_card = load_agent_card()

# Create request handler with agent executor
request_handler = DefaultRequestHandler(
    agent_executor=LaptopRefreshPolicyAgentExecutor(),
    task_store=InMemoryTaskStore(),
)

# Create A2A Starlette application
server = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=request_handler
)

# Create Starlette app
app = server.build()


# Add health endpoint
async def health(request):
    """Health check endpoint for Kubernetes probes."""
    return JSONResponse({"status": "healthy"})


app.routes.append(Route("/health", health, methods=["GET"]))

logger.info("Laptop Refresh Policy Agent initialized with a2a-sdk")


if __name__ == "__main__":
    logger.info(f"Starting Laptop Refresh Policy Agent on {SERVER_HOST}:{SERVER_PORT}")
    uvicorn.run(
        app,
        host=SERVER_HOST,
        port=SERVER_PORT,
        log_level=LOG_LEVEL.lower()
    )
