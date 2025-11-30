import asyncio
from typing import List, Sequence

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient


def _last_chat_text(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> str:
    """Return the textual content of the latest chat message in a TaskResult."""
    for message in reversed(messages):
        if isinstance(message, BaseChatMessage):
            return message.to_text()
    raise RuntimeError("TaskResult did not contain any chat messages.")


async def main() -> None:
    """
    Run a three-agent panel where each participant uses a different model (gpt-4o, gpt-4.1-mini, gpt-4.1)
    and contributes exactly one message in sequence.
    """

    panel_task = (
        "Draft the key talking points for a two-minute community talk on preparing neighborhoods for heat waves. "
        "Focus on actionable advice regular residents can follow."
    )

    visionary_client = OpenAIChatCompletionClient(model="gpt-4o")
    planner_client = OpenAIChatCompletionClient(model="gpt-4.1-mini")
    skeptic_client = OpenAIChatCompletionClient(model="gpt-4.1")

    visionary = AssistantAgent(
        "visionary",
        model_client=visionary_client,
        description="Big-picture strategist using GPT-4o.",
        system_message=(
            "You are Visionary using the gpt-4o model. Offer bold, forward-looking ideas. "
            "Provide exactly one response under 120 words, prefixed with 'Visionary:'. "
            "Do NOT ask questions or mention handing off to other agents."
        ),
        model_client_stream=False,
    )

    planner = AssistantAgent(
        "planner",
        model_client=planner_client,
        description="Pragmatic planner using GPT-4.1-mini.",
        system_message=(
            "You are Planner using the gpt-4.1-mini model. Translate previous ideas into concrete steps. "
            "Provide exactly one response under 120 words, prefixed with 'Planner:'. "
            "Do NOT ask questions or start a new conversation; reference earlier remarks if helpful."
        ),
        model_client_stream=False,
    )

    skeptic = AssistantAgent(
        "skeptic",
        model_client=skeptic_client,
        description="Risk-focused reviewer using GPT-4.1.",
        system_message=(
            "You are Skeptic using the gpt-4.1 model. Stress-test the plan and highlight gaps. "
            "Provide exactly one response under 120 words, prefixed with 'Skeptic:'. "
            "No questions—close with a verdict such as APPROVED or NEEDS WORK."
        ),
        model_client_stream=False,
    )

    panelists = [
        ("Visionary (gpt-4o)", visionary),
        ("Planner (gpt-4.1-mini)", planner),
        ("Skeptic (gpt-4.1)", skeptic),
    ]

    contributions: List[str] = []
    for label, agent in panelists:
        prior_section = "\n".join(contributions) if contributions else "No prior contributions."
        prompt = (
            f"Shared task: {panel_task}\n\n"
            f"Prior contributions:\n{prior_section}\n\n"
            "Respond once as instructed in your system message. Stay within 120 words."
        )
        result = await agent.run(task=prompt)
        response_text = _last_chat_text(result.messages).strip()
        contributions.append(response_text)
        print(f"--- {label} ---")
        print(response_text)
        print()


if __name__ == "__main__":
    asyncio.run(main())
