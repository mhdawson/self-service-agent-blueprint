"""Agent executor for Laptop Refresh Policy Agent using a2a-sdk."""

import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState, TextPart
from a2a.utils import new_agent_text_message, new_task
from langchain_core.messages import HumanMessage

from .agent import agent
from .config import REFRESH_INTERVAL_YEARS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LaptopRefreshPolicyAgentExecutor(AgentExecutor):
    """Executor for the Laptop Refresh Policy Agent."""

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute the agent request."""
        # Get user input
        query = context.get_user_input()
        logger.info(f"Processing query: {query}")

        # Get or create task
        task = context.current_task
        if not task:
            task = new_task(context.message)  # type: ignore
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        try:
            # Update status to working
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(
                    "Processing your request...",
                    task.context_id,
                    task.id,
                ),
            )

            # Invoke the LangGraph agent
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=query)]}
            )

            # Extract the response from the LangGraph result
            if result and "messages" in result and len(result["messages"]) > 0:
                last_message = result["messages"][-1]
                response_text = last_message.content
            else:
                response_text = f"The laptop refresh interval is {REFRESH_INTERVAL_YEARS} years."

            # Send completion with result
            await updater.add_artifact(
                [Part(root=TextPart(text=response_text))],
                name='refresh_policy_result',
            )
            await updater.complete()

        except Exception as e:
            logger.error(f"Error executing agent: {e}")
            # Send error status
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(
                    f"An error occurred: {str(e)}",
                    task.context_id,
                    task.id,
                ),
                final=True,
            )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Cancel the agent execution (not supported)."""
        logger.info("Cancel not supported for this agent")
