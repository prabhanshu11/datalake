#!/usr/bin/env python3
"""Skill Comparison Test Harness using Claude Agent SDK.

Compare OLD (grep-based) vs NEW (FTS5-based) conversation-recall skill
by running the same query through both and measuring performance.

Usage:
    python run_test.py --skill old --query "search for agent subagent"
    python run_test.py --skill new --query "search for agent subagent"
    python run_test.py --compare --query "search for agent subagent"
"""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

# Agent SDK imports
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import HookMatcher

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results"
OLD_SKILL_PATH = SCRIPT_DIR / "old_skill.md"
NEW_SKILL_PATH = SCRIPT_DIR / "new_skill.md"

# PATH configurations
# OLD agent: minimal PATH (no access to datalake scripts)
OLD_PATH = "/usr/local/bin:/usr/bin:/bin"
# NEW agent: includes ~/.local/bin (has find-conversations, get-messages-from-current)
NEW_PATH = f"{Path.home()}/.local/bin:/usr/local/bin:/usr/bin:/bin"


@dataclass
class ToolCall:
    """Record of a single tool call."""
    tool_name: str
    arguments: dict
    start_time: float
    end_time: float
    duration_ms: int
    output_preview: str  # First 500 chars


@dataclass
class TestResult:
    """Complete result of a skill test run."""
    skill_version: str  # "old" or "new"
    query: str
    timestamp: str
    total_duration_ms: int
    tool_calls: list[ToolCall] = field(default_factory=list)
    message_count: int = 0
    final_output: str = ""
    sessions_found: int = 0  # Number of sessions mentioned in output
    error: str | None = None


async def run_skill_test(
    skill_version: Literal["old", "new"],
    query: str,
    max_turns: int = 15,
) -> TestResult:
    """Run a skill test and return detailed results.

    Args:
        skill_version: "old" for grep-based, "new" for FTS5-based
        query: The user's search query
        max_turns: Maximum agent turns before stopping

    Returns:
        TestResult with timing and output data
    """
    # Select skill file and PATH
    if skill_version == "old":
        skill_path = OLD_SKILL_PATH
        path_env = OLD_PATH
    else:
        skill_path = NEW_SKILL_PATH
        path_env = NEW_PATH

    # Load skill instructions
    skill_content = skill_path.read_text()

    # Track tool calls via hooks
    tool_calls: list[dict] = []
    tool_start_times: dict[str, float] = {}

    async def pre_tool_hook(input_data, stdout, context):
        """Record when a tool starts."""
        tool_name = input_data.get("tool_name", "unknown")
        tool_input = input_data.get("tool_input", {})
        key = f"{tool_name}:{json.dumps(tool_input, sort_keys=True)}"
        tool_start_times[key] = time.perf_counter()
        return {"continue": True}

    async def post_tool_hook(input_data, stdout, context):
        """Record when a tool completes and capture output."""
        tool_name = input_data.get("tool_name", "unknown")
        tool_input = input_data.get("tool_input", {})
        tool_response = input_data.get("tool_response", "")

        key = f"{tool_name}:{json.dumps(tool_input, sort_keys=True)}"
        start_time = tool_start_times.pop(key, time.perf_counter())
        end_time = time.perf_counter()

        # Get output preview
        output_str = str(tool_response)[:500] if tool_response else ""

        tool_calls.append({
            "tool_name": tool_name,
            "arguments": tool_input,
            "start_time": start_time,
            "end_time": end_time,
            "duration_ms": int((end_time - start_time) * 1000),
            "output_preview": output_str,
        })
        return {"continue": True}

    # Configure Claude Agent with skill as system prompt
    # Use native Claude Code tools (Bash, Grep, Read) - simpler than MCP
    system_prompt = f"""You are testing the conversation-recall skill.

{skill_content}

IMPORTANT: Follow the skill instructions above to answer the user's query.
Use the Bash tool to execute commands. Report your findings clearly.

PATH for commands: {path_env}
"""

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=["Bash", "Grep", "Read"],  # Native Claude Code tools
        max_turns=max_turns,
        model="claude-sonnet-4-20250514",
        env={"PATH": path_env},  # Set PATH for bash commands
        hooks={
            "PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_hook], timeout=30.0)],
            "PostToolUse": [HookMatcher(matcher=None, hooks=[post_tool_hook], timeout=30.0)],
        },
        permission_mode="bypassPermissions",  # Allow tool execution without prompts
    )

    # Run the test
    start_time = time.perf_counter()
    messages = []
    error = None

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(query)

            async for msg in client.receive_response():
                messages.append(str(msg))

    except Exception as e:
        error = str(e)

    end_time = time.perf_counter()
    total_ms = int((end_time - start_time) * 1000)

    # Count sessions found in output (look for UUID pattern)
    import re
    final_output = messages[-1] if messages else ""
    uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    sessions_found = len(set(re.findall(uuid_pattern, final_output, re.I)))

    # Build result
    result = TestResult(
        skill_version=skill_version,
        query=query,
        timestamp=datetime.now().isoformat(),
        total_duration_ms=total_ms,
        tool_calls=[ToolCall(**tc) for tc in tool_calls],
        message_count=len(messages),
        final_output=final_output[:5000],  # Truncate for storage
        sessions_found=sessions_found,
        error=error,
    )

    return result


def save_result(result: TestResult):
    """Save result to JSON file."""
    RESULTS_DIR.mkdir(exist_ok=True)

    filename = f"{result.skill_version}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = RESULTS_DIR / filename

    # Convert dataclass to dict
    data = asdict(result)

    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

    return filepath


def print_summary(result: TestResult):
    """Print a summary of the test result."""
    print(f"\n{'='*60}")
    print(f"SKILL TEST RESULT: {result.skill_version.upper()}")
    print(f"{'='*60}")
    print(f"Query: {result.query[:80]}...")
    print(f"Timestamp: {result.timestamp}")
    print(f"Total Duration: {result.total_duration_ms}ms ({result.total_duration_ms/1000:.2f}s)")
    print(f"Tool Calls: {len(result.tool_calls)}")
    print(f"Messages: {result.message_count}")
    print(f"Sessions Found: {result.sessions_found}")

    if result.error:
        print(f"ERROR: {result.error}")

    print(f"\n--- Tool Call Breakdown ---")
    for i, tc in enumerate(result.tool_calls, 1):
        cmd = tc.arguments.get("command", "")[:60]
        print(f"  {i}. [{tc.duration_ms}ms] {cmd}...")

    print(f"\n--- Final Output Preview ---")
    print(result.final_output[:1000])
    print("..." if len(result.final_output) > 1000 else "")


async def main():
    parser = argparse.ArgumentParser(description="Skill Comparison Test Harness")
    parser.add_argument("--skill", choices=["old", "new"], help="Which skill version to test")
    parser.add_argument("--compare", action="store_true", help="Run both OLD and NEW for comparison")
    parser.add_argument("--query", required=True, help="The search query to test")
    parser.add_argument("--max-turns", type=int, default=15, help="Maximum agent turns")
    parser.add_argument("--output", help="Output file path (default: auto-generated)")

    args = parser.parse_args()

    if args.compare:
        # Run both skills
        print("Running comparison test...")

        print("\n[1/2] Testing OLD skill (grep-based)...")
        old_result = await run_skill_test("old", args.query, args.max_turns)
        old_file = save_result(old_result)
        print_summary(old_result)

        print("\n[2/2] Testing NEW skill (FTS5-based)...")
        new_result = await run_skill_test("new", args.query, args.max_turns)
        new_file = save_result(new_result)
        print_summary(new_result)

        # Comparison
        print(f"\n{'='*60}")
        print("COMPARISON SUMMARY")
        print(f"{'='*60}")
        print(f"OLD: {old_result.total_duration_ms}ms, {len(old_result.tool_calls)} tools, {old_result.sessions_found} sessions")
        print(f"NEW: {new_result.total_duration_ms}ms, {len(new_result.tool_calls)} tools, {new_result.sessions_found} sessions")

        if new_result.total_duration_ms < old_result.total_duration_ms:
            speedup = old_result.total_duration_ms / new_result.total_duration_ms
            print(f"NEW is {speedup:.1f}x FASTER")
        else:
            slowdown = new_result.total_duration_ms / old_result.total_duration_ms
            print(f"NEW is {slowdown:.1f}x SLOWER")

        print(f"\nResults saved to:")
        print(f"  OLD: {old_file}")
        print(f"  NEW: {new_file}")

    elif args.skill:
        # Run single skill
        print(f"Testing {args.skill.upper()} skill...")
        result = await run_skill_test(args.skill, args.query, args.max_turns)

        if args.output:
            filepath = Path(args.output)
            filepath.parent.mkdir(exist_ok=True)
            with open(filepath, 'w') as f:
                json.dump(asdict(result), f, indent=2)
        else:
            filepath = save_result(result)

        print_summary(result)
        print(f"\nResult saved to: {filepath}")

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
