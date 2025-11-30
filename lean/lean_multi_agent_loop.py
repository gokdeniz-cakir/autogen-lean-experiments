import asyncio
import subprocess
from pathlib import Path
from typing import Optional

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console
from autogen_core.tools import FunctionTool
from autogen_ext.models.openai import OpenAIChatCompletionClient


def _find_lake_root(start: Path) -> Optional[Path]:
    """
    Locate the Lake project root by searching upwards for a lakefile.
    This mirrors what VS Code / the Lean language server does so that
    `lake env lean` sees the same environment (including Mathlib).
    """
    for path in [start, *start.parents]:
        if (path / "lakefile.lean").exists() or (path / "lakefile.toml").exists():
            return path
    return None


# Files used in the loop
BASE_DIR = Path(__file__).resolve().parent  # e.g., .../MyBench/New_folder
LAKE_ROOT = _find_lake_root(BASE_DIR)
LEAN_FILE = BASE_DIR / "Copy00.lean"
DIAG_MD = Path("diagnosis.md")
PLAN_MD = Path("fix_plan.md")


def read_file(path: Path, start_line: int = 1, line_count: int = 80) -> str:
    if not path.exists():
        return f"{path} not found."
    lines = path.read_text(encoding="utf-8").splitlines()
    start = max(start_line, 1)
    end = min(start + max(line_count, 1) - 1, len(lines))
    snippet = "\n".join(f"{i+1:>4}: {content}" for i, content in enumerate(lines[start - 1 : end], start=start - 1))
    return snippet or "(empty)"


def write_md(path: Path, content: str, mode: str = "append") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "overwrite":
        path.write_text(content, encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as f:
            f.write(content)
    return f"Wrote to {path}."


def run_lean_file(dummy: Optional[str] = None, timeout_seconds: int = 60) -> str:
    if not LEAN_FILE.exists():
        return f"{LEAN_FILE} not found."
    if LAKE_ROOT is None or not LAKE_ROOT.exists():
        return f"Lake project root not found above {BASE_DIR}. Ensure a lakefile.lean exists."
    try:
        proc = subprocess.run(
            ["lake", "env", "lean", str(LEAN_FILE.resolve())],
            cwd=LAKE_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return "Lean executable not found. Install Lean 4 and ensure `lean` is on PATH."
    except subprocess.TimeoutExpired as exc:
        return f"Lean timed out after {timeout_seconds}s.\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
    stdout = (proc.stdout or "").strip() or "(empty)"
    stderr = (proc.stderr or "").strip() or "(empty)"
    return f"exit_code={proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"


def overwrite_lean(new_content: str) -> str:
    LEAN_FILE.write_text(new_content, encoding="utf-8")
    return f"Overwrote {LEAN_FILE}."


def read_lean_slice(start_line: int = 1, line_count: int = 80) -> str:
    return read_file(LEAN_FILE, start_line, line_count)


def read_diag_slice(start_line: int = 1, line_count: int = 80) -> str:
    return read_file(DIAG_MD, start_line, line_count)


def read_plan_slice(start_line: int = 1, line_count: int = 80) -> str:
    return read_file(PLAN_MD, start_line, line_count)


def append_diag(content: str) -> str:
    return write_md(DIAG_MD, content + "\n", mode="append")


def append_plan(content: str) -> str:
    return write_md(PLAN_MD, content + "\n", mode="append")


# Tools
read_lean_tool = FunctionTool(
    read_lean_slice,
    description="Read a slice of Copy00.lean by start_line and line_count.",
    strict=False,
)
read_diag_tool = FunctionTool(
    read_diag_slice,
    description="Read diagnosis.md for identified issues.",
    strict=False,
)
read_plan_tool = FunctionTool(
    read_plan_slice,
    description="Read fix_plan.md for proposed fixes.",
    strict=False,
)
append_diag_tool = FunctionTool(
    append_diag,
    description="Append notes to diagnosis.md. Provide `content` (Markdown).",
    strict=False,
)
append_plan_tool = FunctionTool(
    append_plan,
    description="Append notes to fix_plan.md. Provide `content` (Markdown).",
    strict=False,
)
run_lean_tool = FunctionTool(
    run_lean_file,
    description="Run `lean Copy00.lean` and return exit code/stdout/stderr.",
    strict=False,
)
overwrite_lean_tool = FunctionTool(
    overwrite_lean,
    description="Overwrite Copy00.lean with new content. Provide the full Lean source as `new_content`.",
    strict=True,
)


async def run_diagnosis_team() -> None:
    """
    Two agents read the Lean file and document issues in diagnosis.md.
    """

    model_a = OpenAIChatCompletionClient(model="gpt-5")
    model_b = OpenAIChatCompletionClient(model="gpt-5")

    diag1 = AssistantAgent(
        "diag_alpha",
        description="Finds issues in the Lean file.",
        system_message=(
            "You collaborate to identify problems in Copy00.lean. Read relevant sections and discuss errors. "
            "Seek feedback from your partner and reach consensus on what is wrong. Record findings in diagnosis.md "
            "using the provided append tool. Keep messages under 90 words."
        ),
        model_client=model_a,
        tools=[read_lean_tool, run_lean_tool, append_diag_tool],
        model_client_stream=True,
    )

    diag2 = AssistantAgent(
        "diag_beta",
        description="Finds issues in the Lean file.",
        system_message=(
            "You collaborate to identify problems in Copy00.lean. Ask for your partner's view, validate or refine it, "
            "and reach consensus. Log agreed issues in diagnosis.md via the append tool. Keep messages under 90 words."
        ),
        model_client=model_b,
        tools=[read_lean_tool, run_lean_tool, append_diag_tool],
        model_client_stream=True,
    )

    task = (
        "Identify all failing parts of Copy00.lean, agree on a concise list of issues, and append them to diagnosis.md "
        "with context (line ranges, error messages). Do not propose fixes here—just problems."
    )
    termination = MaxMessageTermination(10)
    team = RoundRobinGroupChat([diag1, diag2], termination_condition=termination, max_turns=12)
    await Console(team.run_stream(task=task))


async def run_planning_team() -> None:
    """
    Two agents read diagnosis.md and propose fixes in fix_plan.md.
    """

    model_a = OpenAIChatCompletionClient(model="gpt-5")
    model_b = OpenAIChatCompletionClient(model="gpt-5")

    planner1 = AssistantAgent(
        "plan_alpha",
        description="Proposes fixes based on diagnosis.",
        system_message=(
            "Read diagnosis.md, discuss issues with your partner, and propose specific Lean fixes. Seek feedback, "
            "agree on a concise plan with actionable steps and line references, and append the plan to fix_plan.md. "
            "Keep replies under 90 words."
        ),
        model_client=model_a,
        tools=[read_diag_tool, append_plan_tool],
        model_client_stream=True,
    )

    planner2 = AssistantAgent(
        "plan_beta",
        description="Proposes fixes based on diagnosis.",
        system_message=(
            "Collaborate on fixes using diagnosis.md. Question assumptions, refine suggestions, and ensure consensus "
            "before writing to fix_plan.md. Keep replies under 90 words."
        ),
        model_client=model_b,
        tools=[read_diag_tool, append_plan_tool],
        model_client_stream=True,
    )

    task = (
        "Read diagnosis.md, discuss each issue, and append a clear, step-by-step fix plan to fix_plan.md. "
        "Include which lines to change and the new Lean code to try. Avoid running tools—focus on planning."
    )
    termination = MaxMessageTermination(10)
    team = RoundRobinGroupChat([planner1, planner2], termination_condition=termination, max_turns=12)
    await Console(team.run_stream(task=task))


async def run_executor() -> None:
    """
    Executor reads fix_plan.md, applies changes (overwriting Copy00.lean when instructed), and runs Lean.
    If Lean fails, append a note to diagnosis.md to trigger another cycle.
    """

    model = OpenAIChatCompletionClient(model="gpt-5.1")

    executor = AssistantAgent(
        "executor",
        description="Applies fixes and reports results.",
        system_message=(
            "Read fix_plan.md, summarize the agreed steps, and apply them to Copy00.lean using overwrite_lean if needed. "
            "Run `run_lean_file` afterward. If compilation fails, append a concise failure note to diagnosis.md with "
            "errors and suggested next focus. Keep replies under 100 words."
        ),
        model_client=model,
        tools=[read_plan_tool, overwrite_lean_tool, run_lean_tool, append_diag_tool, read_lean_tool],
        model_client_stream=True,
    )

    task = (
        "Execute the latest plan in fix_plan.md. If Lean succeeds, state success. If it fails, append a brief failure "
        "summary to diagnosis.md so the next cycle can address it."
    )
    termination = MaxMessageTermination(8)
    team = RoundRobinGroupChat([executor], termination_condition=termination, max_turns=8)
    await Console(team.run_stream(task=task))


async def main() -> None:
    # Run the three phases sequentially. You can re-run the script to iterate.
    await run_diagnosis_team()
    await run_planning_team()
    await run_executor()


if __name__ == "__main__":
    asyncio.run(main())
