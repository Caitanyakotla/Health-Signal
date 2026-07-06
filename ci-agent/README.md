# CI/CD Guardian — Autonomous Pipeline Agent

An AI agent (built with the [Agent SDK](https://code.claude.com/docs/en/agent-sdk/python))
that replaces the "human watching the pipeline" role for this repo:


```
poll gh run list (python)
        │ failure detected
        ▼
fetch failure logs via gh (python)
        │
        ▼
TRIAGE — small model (~$0.01)
        │
        ├── transient (flaky runner/network) ─► "just rerun it", done
        │
        ▼ real code/config problem

FIX AGENT — main model
  1. prints ROOT CAUSE
  2. prints SUGGESTED FIX steps
  3. edits the repo files to apply the fix
  4. git commit
  5. git push  ──► ⛔ HUMAN APPROVAL [y/N]
        │ approved
        ▼
Push re-triggers the pipeline → green ✅
```

Successful runs are short-circuited in Python and never touch a model at all.

## Safety model

The approval gate is **enforced in code, not just in the prompt**. A
`can_use_tool` permission callback intercepts every Bash command the agent
attempts:

| Command | Policy |
|---|---|
| `git push`, `gh pr create/merge`, `gh run rerun` | **Blocked until you type `y`** in the terminal |
| `git push --force`, `git reset --hard`, `git clean -f`, `rm -rf`, `branch -D` | **Always denied** — the agent is told to find another way |
| File edits inside the repo | Auto-applied (local + reversible; review with `git diff`) |
| Everything else (reading logs, grep, etc.) | Allowed |

The agent is also instructed to stage only the files it changed (never
`git add -A`), so your unrelated work-in-progress is never swept into a fix
commit. Filesystem permission settings (`.claude/settings.json`) are
deliberately not loaded, so no allow-rule can bypass the gate.

## Prerequisites

- Python 3.10+
- [GitHub CLI](https://cli.github.com/) authenticated: `gh auth status`
- Code CLI installed and logged in (the SDK uses its credentials),


## Install

```bash
pip install -r ci-agent/requirements.txt
```

## Usage

```bash
# Watch mode — poll every 60s, handle failures as they appear
python3 ci-agent/agent.py

# One-shot check (good for cron)
python3 ci-agent/agent.py --once

# Diagnose a specific run (post-mortems, testing)
python3 ci-agent/agent.py --run 28748943912

# Suggestions only — pushing is disabled no matter what
python3 ci-agent/agent.py --dry-run

# Custom poll interval
python3 ci-agent/agent.py --interval 300
```

## Configuration

| Env var | Default | Purpose |
|---              |---                               |---                    |
| `CI_AGENT_REPO` | auto-detected via `gh repo view` | `owner/repo` to watch |
| `CI_AGENT_MODEL` | `AI Module` | Fix agent (diagnosis + repair).  |
| `CI_AGENT_TRIAGE_MODEL` | `AI Module` | Cheap transient-vs-real triage classifier |

State (which failed runs were already handled) lives in `ci-agent/.state.json`.
On first launch the agent sets a baseline at the newest existing run, so old
historical failures are not dredged up — it only reacts to failures that
happen after it starts watching.

## Trying it out

All runs green? Simulate a failure on a branch:

```bash
git checkout -b break-the-build
# introduce a deliberate error, e.g. corrupt the Dockerfile
echo "FROM does-not-exist:latest" > Dockerfile
git commit -am "test: break the build" && git push -u origin break-the-build
# open a PR to main so the Security Scan workflow runs, watch it fail, then:
python3 ci-agent/agent.py --once
```
