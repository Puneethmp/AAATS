#!/usr/bin/env python3
"""
AAATS Autonomous Build Runner

Calls Claude API to generate code for the next module, writes files to disk,
runs tests, and commits to git. Runs every 6 hours via GitHub Actions.

Usage:
    python scripts/autonomous_build.py [--dry-run]
"""

import os
import sys
import subprocess
import json
import re
from datetime import datetime
from pathlib import Path

import requests
from anthropic import Anthropic

PROJECT_ROOT = Path(__file__).parent.parent
SESSION_STATE = PROJECT_ROOT / "SESSION_STATE.md"
AUTO_BUILD_SYSTEM = PROJECT_ROOT / "AUTO_BUILD_SYSTEM.md"
AUTO_APPROVAL_RULES = PROJECT_ROOT / "AUTO_APPROVAL_RULES.md"


def log(message, level="INFO"):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{timestamp}] {level}: {message}")


def read_file_safe(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return ""


def read_session_state():
    if not SESSION_STATE.exists():
        log("SESSION_STATE.md not found", "ERROR")
        return None
    content = read_file_safe(SESSION_STATE)
    return {"content": content, "exists": True}


def get_next_module(state):
    content = state["content"]

    module_queue = [
        {
            "name": "US Momentum Strategy",
            "file": "strategies/us/momentum.py",
            "test_file": "tests/test_strategies/test_us/test_momentum.py",
            "marker": "US Momentum",
        },
        {
            "name": "US Mean Reversion Strategy",
            "file": "strategies/us/mean_reversion.py",
            "test_file": "tests/test_strategies/test_us/test_mean_reversion.py",
            "marker": "Mean Reversion",
        },
        {
            "name": "India Momentum Strategy",
            "file": "strategies/india/momentum.py",
            "test_file": "tests/test_strategies/test_india/test_momentum.py",
            "marker": "India Momentum",
        },
    ]

    for module in module_queue:
        file_path = PROJECT_ROOT / module["file"]
        if not file_path.exists():
            return {**module, "found": True}

    return {
        "name": "US Momentum Strategy",
        "file": "strategies/us/momentum.py",
        "test_file": "tests/test_strategies/test_us/test_momentum.py",
        "found": True,
    }


def call_claude_for_build(session_state, next_module):
    """Call Claude API to generate the next module's code."""
    api_key = os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        log("CLAUDE_API_KEY environment variable not set", "ERROR")
        return None

    client = Anthropic(api_key=api_key)

    system_prompt = """You are an autonomous Python code generator for AAATS (Autonomous Algorithmic Trading System).

Generate production-quality Python code for the specified trading module.

CRITICAL: Respond ONLY with a valid JSON object. No markdown fences, no explanation outside JSON.

Response format:
{
  "files": [
    {
      "path": "relative/path/from/project/root.py",
      "content": "complete python file content as a string"
    }
  ],
  "summary": "Brief description of what was built",
  "next_module": "Name of next module to build"
}

Code requirements:
- Python 3.12+ with full type hints
- Dataclass-based design for signals and results
- All methods fully implemented (no pass, no TODO, no placeholder)
- Python logging module (not print)
- Exception handling with informative messages
- Pandas for data calculations
- Tests use synthetic data only (no external API calls)
- Each test file has at minimum: test_happy_path, test_edge_cases, test_invalid_input
"""

    auto_build_context = read_file_safe(AUTO_BUILD_SYSTEM)[:2000]
    session_content = session_state["content"][:3000]

    user_message = f"""Build this module now:

Module: {next_module['name']}
Implementation file: {next_module['file']}
Test file: {next_module['test_file']}

Current project state:
{session_content}

Build system context:
{auto_build_context}

For US Momentum Strategy (SMA50/SMA200 crossover):
- Class MomentumStrategy with __init__(self, fast_period=50, slow_period=200)
- Method calculate_signals(df: pd.DataFrame) -> pd.DataFrame
  - Adds columns: sma_fast, sma_slow, signal (1/-1/0), momentum_score
  - Signal +1: sma_fast > sma_slow AND price above sma_fast (uptrend)
  - Signal -1: sma_fast < sma_slow AND price below sma_fast (downtrend)
  - Signal 0: neutral / insufficient data
- Method generate_orders(df_with_signals: pd.DataFrame, portfolio_value: float) -> list[dict]
  - Returns list of {{"symbol": str, "action": "BUY"/"SELL"/"HOLD", "quantity": int, "price": float}}
  - Position size: 5% of portfolio per signal
- Method backtest(df: pd.DataFrame) -> dict with keys: total_return, sharpe_ratio, max_drawdown, num_trades
- Include __init__.py in strategies/ and strategies/us/ directories

Respond with JSON only — no other text."""

    log(f"Calling Claude API to build: {next_module['name']}", "INFO")

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=8096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    return response.content[0].text


def parse_claude_response(response_text):
    """Parse Claude's JSON response, extracting JSON block if needed."""
    text = response_text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Find outermost JSON object
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    log("Failed to parse Claude response as JSON", "ERROR")
    log(f"Response preview: {response_text[:300]}", "DEBUG")
    return None


def write_generated_files(build_result):
    """Write all files from Claude's build result to disk."""
    if not build_result or "files" not in build_result:
        log("No files in build result", "ERROR")
        return False

    written = []
    for file_info in build_result["files"]:
        path = PROJECT_ROOT / file_info["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(file_info["content"])
        log(f"Written: {file_info['path']}", "INFO")
        written.append(file_info["path"])

    # Ensure __init__.py files exist for packages
    ensure_init_files(written)
    return len(written) > 0


def ensure_init_files(written_paths):
    """Create __init__.py for any new package directories."""
    dirs_needing_init = set()
    for rel_path in written_paths:
        path = PROJECT_ROOT / rel_path
        for parent in path.parents:
            if parent == PROJECT_ROOT:
                break
            init = parent / "__init__.py"
            if not init.exists():
                dirs_needing_init.add(parent)

    for d in dirs_needing_init:
        init = d / "__init__.py"
        init.write_text("")
        log(f"Created: {init.relative_to(PROJECT_ROOT)}", "INFO")


def run_health_checks():
    log("Running health checks...", "INFO")
    try:
        result = subprocess.run(["python", "--version"], capture_output=True, text=True)
        log(f"Python: {result.stdout.strip()}", "INFO")
        result = subprocess.run(["pytest", "--version"], capture_output=True, text=True)
        log(f"Pytest: {result.stdout.strip()}", "INFO")
        result = subprocess.run(
            ["git", "status", "--short"], capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        log(f"Git status: {result.stdout.strip() or 'clean'}", "INFO")
        return True
    except Exception as e:
        log(f"Health check failed: {e}", "ERROR")
        return False


def run_tests(test_path="tests/"):
    log(f"Running tests: {test_path}", "INFO")
    try:
        result = subprocess.run(
            ["pytest", str(test_path), "-v", "--tb=short", "-q"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout
        log(f"Test output:\n{output}", "INFO")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log("Tests timed out after 300s", "ERROR")
        return False
    except Exception as e:
        log(f"Test run failed: {e}", "ERROR")
        return False


def update_session_state(module_info, success, summary=""):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    status = "COMPLETED" if success else "FAILED"

    update_text = f"""
## Build Session: {timestamp}
- **Status:** {status}
- **Module:** {module_info.get('name', 'Unknown')}
- **File:** {module_info.get('file', 'Unknown')}
- **Claude API:** Used (autonomous generation)
- **Summary:** {summary}
- **Trigger:** GitHub Actions (every 6 hours)
"""
    try:
        with open(SESSION_STATE, "a") as f:
            f.write(update_text)
        log("Updated SESSION_STATE.md", "INFO")
        return True
    except Exception as e:
        log(f"Failed to update SESSION_STATE.md: {e}", "ERROR")
        return False


def commit_changes(module_info):
    try:
        subprocess.run(["git", "add", "-A"], cwd=PROJECT_ROOT, check=True)

        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=PROJECT_ROOT
        )
        if result.returncode == 0:
            log("No changes to commit", "INFO")
            return True

        timestamp = datetime.utcnow().strftime("%Y-%m-%d")
        commit_msg = (
            f"Autonomous build: {timestamp} — {module_info.get('name', 'Phase 2')} (Claude API)"
        )

        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
        )
        log(f"Committed: {commit_msg}", "INFO")

        push = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if push.returncode == 0:
            log("Pushed to origin/main", "INFO")
        else:
            log(f"Push failed: {push.stderr}", "WARNING")

        return True
    except subprocess.CalledProcessError as e:
        log(f"Git operation failed: {e}", "ERROR")
        return False


def send_telegram_notification(status: str, message: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set, skipping notification", "WARNING")
        return False

    emoji = "✅" if status == "SUCCESS" else "🚨"
    text = f"{emoji} AAATS BUILD {status}\n\n{message}"

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        if response.ok:
            log("Telegram notification sent", "INFO")
            return True
        log(f"Telegram notification failed: {response.text}", "WARNING")
        return False
    except Exception as e:
        log(f"Telegram notification error: {e}", "WARNING")
        return False


def main():
    log("Starting AAATS Autonomous Build with Claude API", "INFO")
    log(f"Project root: {PROJECT_ROOT}", "INFO")

    dry_run = "--dry-run" in sys.argv
    if dry_run:
        log("DRY RUN MODE ENABLED", "WARNING")

    if not run_health_checks():
        log("Health checks failed, aborting", "ERROR")
        return 1

    state = read_session_state()
    if not state:
        log("Cannot read SESSION_STATE.md", "ERROR")
        return 1

    next_module = get_next_module(state)
    log(f"Next module: {next_module['name']} -> {next_module['file']}", "INFO")

    # Run existing tests before building
    run_tests()

    if dry_run:
        log("DRY RUN: Skipping Claude API call and file generation", "INFO")
        update_session_state(next_module, True, "Dry run — no API call made")
        commit_changes(next_module)
        return 0

    # Call Claude API to generate code
    claude_response = call_claude_for_build(state, next_module)
    if not claude_response:
        log("Claude API call failed", "ERROR")
        update_session_state(next_module, False, "Claude API call failed — check CLAUDE_API_KEY secret")
        send_telegram_notification("FAILURE", "Claude API call failed — check CLAUDE_API_KEY secret")
        commit_changes(next_module)
        return 1

    # Parse Claude's response
    build_result = parse_claude_response(claude_response)
    if not build_result:
        log("Failed to parse Claude response", "ERROR")
        update_session_state(next_module, False, "Failed to parse Claude response as JSON")
        send_telegram_notification("FAILURE", "Failed to parse Claude response as JSON")
        commit_changes(next_module)
        return 1

    # Write generated files
    success = write_generated_files(build_result)
    summary = build_result.get("summary", "Module generated by Claude API")
    log(f"Build summary: {summary}", "INFO")

    # Run tests on newly generated code
    if success:
        test_path = PROJECT_ROOT / next_module.get("test_file", "tests/")
        run_tests(test_path if test_path.exists() else "tests/")

    # Update session state and commit
    update_session_state(next_module, success, summary)
    send_telegram_notification("SUCCESS", f"Built {next_module['name']}: {summary}")
    commit_changes(next_module)

    log("Autonomous build completed successfully", "INFO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
