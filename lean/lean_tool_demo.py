import asyncio
import subprocess
import tempfile
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console
from autogen_core.tools import FunctionTool
from autogen_ext.models.openai import OpenAIChatCompletionClient


def run_lean(code: str, timeout_seconds: int = 30) -> str:
    """
    Write `code` to a temporary Lean file and return the compiler output.
    Requires the `lean` executable to be available on PATH.
    """

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "AgentScript.lean"
        tmp_path.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                ["lean", tmp_path.name],
                cwd=tmp_path.parent,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError:
            return "Lean executable not found. Install Lean 4 and ensure `lean` is on PATH."
        except subprocess.TimeoutExpired as exc:
            return f"Lean timed out after {timeout_seconds}s. Partial stdout:\n{exc.stdout}\nPartial stderr:\n{exc.stderr}"
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        return f"exit_code={proc.returncode}\nstdout:\n{stdout}\n\nstderr:\n{stderr}"


lean_runner_tool = FunctionTool(
    run_lean,
    description=(
        "Compile and run Lean 4 code snippets. Provide the Lean source as `code`. "
        "The tool returns compiler stdout/stderr so you can inspect proof results."
    ),
    strict=False,
)


async def main() -> None:
    """
    Small bench where two agents collaborate to run Lean code and inspect the output.
    """

    planner_client = OpenAIChatCompletionClient(model="gemini-3-pro-preview")
    executor_client = OpenAIChatCompletionClient(model="gemini-2.5-flash")

    planner = AssistantAgent(
        "planner",
        description="Hypothesizes Lean proof strategies.",
        system_message=(
        "You are the theorist (Gemini 3 Pro). Keep the conversation flowing: greet the executor, describe the next proof idea "
        "in plain English (no Lean code), and react to their feedback. Avoid shortcuts like `simp`, `ring`, or quoting existing "
        "lemmas—outline how to reconstruct the proof from first principles. Keep replies under 60 words and do not call `run_lean`."
        ),
        model_client=planner_client,
        model_client_stream=True,
    )
    executor = AssistantAgent(
        "executor",
        description="Implements the planner suggestions and runs Lean.",
        system_message=(
        "You are the implementer (Gemini 2.5 Flash). Rephrase the planner's idea, produce Lean code that follows their guidance "
        "without relying on `simp`/`ring`/out-of-the-box lemmas, call `run_lean`, and summarize the output. Keep 2-3 sentences under "
        "80 words, translate errors into plain language, and always ask the planner what to try next."
        ),
        model_client=executor_client,
        tools=[lean_runner_tool],
        model_client_stream=True,
    )

    termination = MaxMessageTermination(20)
    team = RoundRobinGroupChat(
        [planner, executor],
        termination_condition=termination,
        max_turns=20,
    )

    task = (
        "Have a short conversation while proving a simple Lean lemma (e.g., `2 + 3 = 3 + 2`) or evaluating `#eval`. "
        "Talk through each step, avoid quoting high-level tactics, run `run_lean` as needed, and only wrap up after at least one "
        "reflection round on why the proof worked."
    )
    await Console(team.run_stream(task=task))


if __name__ == "__main__":
    asyncio.run(main())
