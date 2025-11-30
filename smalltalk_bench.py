import asyncio

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient


async def main() -> None:
    """
    Run a short round-robin bench where two models greet each other and make small talk.
    """

    max_messages = 10
    starter_client = OpenAIChatCompletionClient(model="gemini-2.5-flash")
    responder_client = OpenAIChatCompletionClient(model="gemini-2.0-flash")

    starter = AssistantAgent(
        "starter",
        model_client=starter_client,
        description="Friendly greeter using 2.5 flash.",
        system_message=(
            "Keep responses under 40 words. Start with a warm greeting, ask one light question, "
            "and wait for a reply. Do not switch tasks or ramble."
        ),
        model_client_stream=True,
    )

    responder = AssistantAgent(
        "responder",
        model_client=responder_client,
        description="Relaxed conversationalist using 2.0 flash.",
        system_message=(
            "Reply casually in under 40 words. Mention something you enjoy, ask or answer a small-talk question, "
            "and keep the tone upbeat."
        ),
        model_client_stream=True,
    )

    termination = MaxMessageTermination(max_messages)
    team = RoundRobinGroupChat(
        [starter, responder],
        termination_condition=termination,
        max_turns=max_messages,
    )

    await Console(team.run_stream(task="Have a quick friendly chat about your day and weekend plans."))


if __name__ == "__main__":
    asyncio.run(main())
