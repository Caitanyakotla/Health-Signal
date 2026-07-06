#!/usr/bin/env python3
"""HealthSignal CI/CD Guardian.

An autonomous agent (built on the Agent SDK) that watches the GitHub
Actions pipeline for this repo. When a run fails it:

  1. Pulls the failed run's logs via `gh`
  2. Diagnoses the root cause
  3. Prints suggested fix steps
  4. Implements the fix locally (file edits are auto-applied — they're local
     and reversible)
  5. Asks YOU for approval before anything is pushed to GitHub

The approval gate is enforced in code (a tool-permission callback), not just
in the prompt — the agent physically cannot `git push` without a "y" from the
terminal.

Usage:
    python3 ci-agent/agent.py                 # watch mode: poll every 60s
    python3 ci-agent/agent.py --once          # single check, then exit
    python3 ci-agent/agent.py --run <id>      # diagnose a specific run
    python3 ci-agent/agent.py --dry-run       # never push, suggestions only
    python3 ci-agent/agent.py --interval 120  # custom poll interval (seconds)

To keep AI usage (and cost/quota) minimal, the model is only involved where
it matters:

    polling / log fetching      plain Python + gh   free
    failure triage              cheap model (Haiku) ~a cent
    diagnosis + fix + push      main model          only for real code fixes

Config (env vars):
    CI_AGENT_REPO           owner/repo  (default: auto-detected via gh)
    CI_AGENT_MODEL          fix model override   (default: sonnet)
    CI_AGENT_TRIAGE_MODEL   triage model override (default: haiku)
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions as AgentOptions,
    ClaudeSDKClient as AgentClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
    ToolUseBlock,
    query,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = Path(__file__).resolve().parent / ".state.json"

# Model aliases, resolved by the CLI. Override with full model ids via env
# (e.g. CI_AGENT_MODEL) if you need to pin an exact version.
FIX_MODEL = os.environ.get("CI_AGENT_MODEL", "sonnet")
TRIAGE_MODEL = os.environ.get("CI_AGENT_TRIAGE_MODEL", "haiku")

FAILURE_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}

# Commands that are never allowed, approval or not.
FORBIDDEN_FRAGMENTS = (
    "push --force",
    "push -f",
    "reset --hard",
    "clean -f",
    "branch -D",
    "rm -rf",
)

# Commands that publish to GitHub and therefore require human approval.
GATED_FRAGMENTS = ("git push", "gh pr create", "gh pr merge", "gh run rerun")


# ---------------------------------------------------------------- shell utils

def sh(cmd: list[str], check: bool = True) -> str:
    result = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=check
    )
    return result.stdout.strip()


def detect_repo() -> str:
    repo = os.environ.get("CI_AGENT_REPO")
    if repo:
        return repo
    return sh(["gh", "repo", "view", "--json", "nameWithOwner",
               "-q", ".nameWithOwner"])


# --------------------------------------------------------------------- state

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"handled_run_ids": [], "baseline_run_id": None}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ------------------------------------------------------------- GitHub polling

RUN_FIELDS = ("databaseId,status,conclusion,displayTitle,headBranch,"
              "workflowName,createdAt,url")


def list_runs(repo: str, limit: int = 15) -> list[dict]:
    out = sh(["gh", "run", "list", "--repo", repo,
              "--limit", str(limit), "--json", RUN_FIELDS])
    return json.loads(out) if out else []


def get_run(repo: str, run_id: str) -> dict:
    out = sh(["gh", "run", "view", run_id, "--repo", repo,
              "--json", RUN_FIELDS.replace("databaseId,", "databaseId,")])
    return json.loads(out)


LOG_TAIL_CHARS = 12000


def fetch_failure_logs(repo: str, run_id) -> str:
    """Pre-fetch run summary + failed-step logs in plain Python (free), so
    the model doesn't spend paid turns running these commands itself."""
    summary = sh(["gh", "run", "view", str(run_id), "--repo", repo],
                 check=False)
    logs = sh(["gh", "run", "view", str(run_id), "--repo", repo,
               "--log-failed"], check=False)
    if len(logs) > LOG_TAIL_CHARS:
        logs = "...(earlier output truncated)...\n" + logs[-LOG_TAIL_CHARS:]
    return (f"=== RUN SUMMARY ===\n{summary}\n\n"
            f"=== FAILED STEP LOGS ===\n{logs or '(no logs available)'}")


def find_new_failures(runs: list[dict], state: dict) -> list[dict]:
    handled = set(state["handled_run_ids"])
    baseline = state.get("baseline_run_id") or 0
    return [
        r for r in runs
        if r["status"] == "completed"
        and r["conclusion"] in FAILURE_CONCLUSIONS
        and r["databaseId"] > baseline
        and r["databaseId"] not in handled
    ]


# ------------------------------------------------------------ approval gate

def make_permission_handler(dry_run: bool):
    async def handler(
        tool_name: str, input_data: dict, context: ToolPermissionContext
    ):
        if tool_name != "Bash":
            return PermissionResultAllow(updated_input=input_data)

        command = input_data.get("command", "")

        for frag in FORBIDDEN_FRAGMENTS:
            if frag in command:
                return PermissionResultDeny(
                    message=f"Command containing '{frag}' is forbidden for "
                            "the CI guardian. Find a non-destructive approach."
                )

        if any(frag in command for frag in GATED_FRAGMENTS):
            if dry_run:
                return PermissionResultDeny(
                    message="Dry-run mode: pushing/publishing is disabled. "
                            "Summarize the local changes instead."
                )
            return await ask_human(command)

        return PermissionResultAllow(updated_input=input_data)

    return handler


async def ask_human(command: str):
    print("\n" + "=" * 62)
    print("  APPROVAL REQUIRED — the agent wants to publish to GitHub")
    print("=" * 62)
    print(f"  Command: {command}\n")
    try:
        pending = sh(["git", "log", "origin/main..HEAD",
                      "--oneline", "--stat"], check=False)
        if pending:
            print("  Commits that would be pushed:")
            for line in pending.splitlines()[:25]:
                print(f"    {line}")
    except Exception:
        pass
    print()
    answer = (await asyncio.to_thread(input, "  Approve? [y/N] ")).strip().lower()
    if answer in ("y", "yes"):
        print("  -> approved\n")
        return PermissionResultAllow()
    print("  -> denied\n")
    return PermissionResultDeny(
        message="The human operator declined. Do NOT retry the command. "
                "Leave the fix as local changes and summarize what you did."
    )


# ------------------------------------------------------------- cheap triage

async def triage(run: dict, logs: str) -> tuple[bool, str]:
    """First-pass classification on a cheap model: is this failure transient
    (rerun fixes it) or does the code/config need a fix? Returns
    (is_transient, verdict_line). No tools, single turn — costs ~a cent."""
    prompt = f"""Classify this failed GitHub Actions run.

TRANSIENT  = external/flaky cause (runner outage, network timeout, rate
             limit, registry hiccup). Rerunning would likely fix it; no code
             change needed.
CODE_FIX   = the repo's code, config, or workflow caused it; a change is
             needed.

Reply with exactly one line, nothing else:
VERDICT: TRANSIENT — <one-line reason>
or
VERDICT: CODE_FIX — <one-line reason>

Run: {run['workflowName']} / "{run['displayTitle']}" on {run['headBranch']}

{logs}"""

    options = AgentOptions(
        cwd=str(REPO_ROOT),
        model=TRIAGE_MODEL,
        system_prompt="You are a CI failure triage classifier. Reply with "
                      "a single VERDICT line. Do not use any tools.",
        max_turns=1,
        setting_sources=[],
    )

    text = ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text += block.text
        elif isinstance(message, ResultMessage):
            cost = getattr(message, "total_cost_usd", None)
            if cost:
                print(f"  (triage cost: ${cost:.4f})")

    verdict = next((ln.strip() for ln in text.splitlines() if "VERDICT" in ln),
                   text.strip()[:200] or "VERDICT: CODE_FIX — unparseable")
    # On any ambiguity, escalate — a wasted diagnosis beats a missed fix.
    return "TRANSIENT" in verdict, verdict


# ------------------------------------------------------------ the agent run

def guardian_system_prompt(repo: str) -> str:
    return f"""You are the HealthSignal CI/CD Guardian, an autonomous pipeline
engineer for the GitHub repo {repo}. Your working directory is the repo checkout.

When given a workflow run to handle:

1. INVESTIGATE. The run summary and failed-step logs are already included in
   the task message — start from those. Only fetch more if they are not
   enough (gh run view <id> --repo {repo} --log-failed). Read any workflow
   or source files needed to understand the failure.

2. REPORT before changing anything, in exactly this format:
     ## ROOT CAUSE
     (2-4 sentences, plain language)
     ## SUGGESTED FIX
     (numbered steps a human could follow)

3. FIX. Implement the fix by editing files in the repo.

4. COMMIT & PUSH. Stage ONLY the files you changed (`git add <file>` — never
   `git add -A` or `git add .`; the checkout may contain unrelated
   work-in-progress that is not yours to commit). Commit with message:
     ci-fix: <one-line summary>
   Then push to the SAME branch the failed run was on:
     git push origin <branch>
   The push triggers a human approval prompt automatically — you don't need
   to ask first, just run it. If the human denies it, do not retry; summarize
   the local changes so they can review, and stop.

Rules:
- Never force-push, reset --hard, delete branches, or touch git history.
- If the failure is transient/external (runner outage, network flake, rate
  limit) do NOT change code. Say so and recommend `gh run rerun <id>`.
- If the run actually succeeded, say so, give a one-paragraph pipeline health
  summary, and stop.
- Stay within this repository. Do not modify anything outside it."""


def build_prompt(run: dict, repo: str, logs: str) -> str:
    return f"""Handle this GitHub Actions run:

Repo:      {repo}
Run ID:    {run['databaseId']}
Title:     {run['displayTitle']}
Workflow:  {run['workflowName']}
Branch:    {run['headBranch']}
Status:    {run['status']} / {run.get('conclusion') or 'n/a'}
URL:       {run['url']}

{logs}"""


def render(message) -> None:
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print(block.text)
            elif isinstance(block, ToolUseBlock):
                detail = (block.input.get("command")
                          or block.input.get("file_path")
                          or "")
                detail = detail.replace("\n", " ")
                if len(detail) > 100:
                    detail = detail[:97] + "..."
                print(f"  [{block.name}] {detail}")
    elif isinstance(message, ResultMessage):
        cost = getattr(message, "total_cost_usd", None)
        if cost:
            print(f"\n--- done (cost: ${cost:.4f}) ---")


async def handle_run(run: dict, repo: str, dry_run: bool) -> None:
    print(f"\n{'#' * 62}")
    print(f"# Run {run['databaseId']}: {run['displayTitle']}")
    print(f"# {run['workflowName']} on {run['headBranch']} -> "
          f"{run.get('conclusion') or run['status']}")
    print(f"{'#' * 62}\n")

    # Tier 0 (free): successful runs never touch a model.
    if run["status"] == "completed" and run.get("conclusion") == "success":
        print("Run succeeded — nothing to do. (No AI used.)")
        return

    # Tier 0 (free): fetch logs with plain gh, not paid agent turns.
    logs = fetch_failure_logs(repo, run["databaseId"])

    # Tier 1 (cheap): triage — transient failures just need a rerun.
    print("Triaging failure with cheap model...")
    is_transient, verdict = await triage(run, logs)
    print(f"  {verdict}")
    if is_transient:
        print(f"\nTransient failure — no code change needed. To retry:\n"
              f"  gh run rerun {run['databaseId']} --repo {repo}")
        return

    # Tier 2 (main model): real diagnosis + fix + gated push.
    print("\nEscalating to fix agent...\n")
    options = AgentOptions(
        cwd=str(REPO_ROOT),
        model=FIX_MODEL,
        system_prompt=guardian_system_prompt(repo),
        allowed_tools=["Read", "Grep", "Glob"],
        permission_mode="acceptEdits",
        can_use_tool=make_permission_handler(dry_run),
        # Don't load filesystem permission settings (.claude/settings.json) —
        # an allow-rule for git push would silently bypass the gate above.
        setting_sources=[],
        max_turns=30,
    )

    # AgentClient (not query()) — it keeps the connection open for the
    # duration of the turn, which the can_use_tool approval round-trip needs.
    async with AgentClient(options=options) as client:
        await client.query(build_prompt(run, repo, logs))
        async for message in client.receive_response():
            render(message)


# --------------------------------------------------------------------- modes

async def check_once(repo: str, dry_run: bool) -> bool:
    """Returns True if a failure was handled."""
    state = load_state()
    runs = list_runs(repo)
    if not runs:
        print("No workflow runs found.")
        return False

    if state.get("baseline_run_id") is None:
        # First launch: only react to failures newer than the newest existing
        # run, so we don't dredge up ancient history.
        state["baseline_run_id"] = max(r["databaseId"] for r in runs)
        save_state(state)
        print(f"Baseline set at run {state['baseline_run_id']} — "
              "watching for new failures from here on.")

    failures = find_new_failures(runs, state)
    if not failures:
        newest = runs[0]
        print(f"Pipeline healthy — latest run {newest['databaseId']} "
              f"({newest['workflowName']}): "
              f"{newest.get('conclusion') or newest['status']}.")
        return False

    for run in sorted(failures, key=lambda r: r["databaseId"]):
        await handle_run(run, repo, dry_run)
        state["handled_run_ids"].append(run["databaseId"])
        save_state(state)
    return True


async def watch(repo: str, interval: int, dry_run: bool) -> None:
    mode = " (dry-run)" if dry_run else ""
    print(f"CI/CD Guardian watching {repo}{mode} — "
          f"polling every {interval}s. Ctrl+C to stop.")
    while True:
        try:
            await check_once(repo, dry_run)
        except subprocess.CalledProcessError as exc:
            print(f"gh/git command failed: {exc.stderr or exc}", file=sys.stderr)
        await asyncio.sleep(interval)


async def main() -> None:
    parser = argparse.ArgumentParser(description="HealthSignal CI/CD Guardian")
    parser.add_argument("--once", action="store_true",
                        help="check once and exit")
    parser.add_argument("--run", metavar="ID",
                        help="diagnose a specific run id and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="diagnose and suggest only — pushing disabled")
    parser.add_argument("--interval", type=int, default=60,
                        help="poll interval in seconds (default 60)")
    args = parser.parse_args()

    repo = detect_repo()

    if args.run:
        await handle_run(get_run(repo, args.run), repo, args.dry_run)
    elif args.once:
        await check_once(repo, args.dry_run)
    else:
        await watch(repo, args.interval, args.dry_run)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
