"""LangGraph agent for laptop refresh policy queries."""

from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from .config import REFRESH_INTERVAL_YEARS


class PolicyAgentState(TypedDict):
    """State for the policy agent - A2A compatible with messages field."""
    messages: Annotated[list[BaseMessage], add_messages]


def get_refresh_interval(state: PolicyAgentState) -> dict:
    """
    Process the user query and return the laptop refresh interval.

    Args:
        state: Current agent state with messages

    Returns:
        Updated state with AI response message
    """
    # Get the latest message from the user
    latest_message = state["messages"][-1] if state["messages"] else None

    if not latest_message:
        response = "No message provided."
    else:
        # Simple response with the configured refresh interval
        response = f"The laptop refresh interval is {REFRESH_INTERVAL_YEARS} years."

    # Return updated state with AI message
    return {
        "messages": [AIMessage(content=response)]
    }


# Build the LangGraph workflow
workflow = StateGraph(PolicyAgentState)

# Add the processing node
workflow.add_node("process", get_refresh_interval)

# Define the flow: START -> process -> END
workflow.add_edge(START, "process")
workflow.add_edge("process", END)

# Compile the graph
agent = workflow.compile()
