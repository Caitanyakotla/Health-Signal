# CI/CD Guardian — Autonomous Pipeline Agent

An AI agent (built with the [Agent SDK](https://code.claude.com/docs/en/agent-sdk/python))
that replaces the "human watching the pipeline" role for this repo:


```
┌──────────────────────────────────────┐
│  poll gh run list (python)           │
└──────────────────────────────────────┘
                   │  failure detected
                   ▼
┌──────────────────────────────────────┐
│  fetch failure logs via gh (python)  │
└──────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  TRIAGE — small model                │
└──────────────────────────────────────┘
                   │
                   ├── transient (flaky runner / network) ──►  "just rerun it" — done
                   │
                   ▼  real code / config problem
┌──────────────────────────────────────┐
│  FIX AGENT — main model              │
│                                      │
│   1. prints ROOT CAUSE               │
│   2. prints SUGGESTED FIX steps      │
│   3. edits repo files to apply fix   │
│   4. git commit                      │
└──────────────────────────────────────┘
                   │  git push
                   ▼
┌──────────────────────────────────────┐
│  HUMAN APPROVAL             [y / N]  │  ⛔ enforced in code
└──────────────────────────────────────┘
                   │  approved
                   ▼
     push re-triggers the pipeline → green ✅
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

## Agent knowledge as Skills (SKILL.md)

The fix agent's procedural knowledge follows the
[Agent Skills](https://code.claude.com/docs/en/agent-sdk/skills) standard:
it lives in `SKILL.md` files, not in Python string prompts.

```
ci-agent/
├── agent.py                     # orchestration, safety gate, polling
└── plugin/                      # local Claude Code plugin
    ├── .claude-plugin/
    │   └── plugin.json          # plugin manifest ("ci-guardian")
    └── skills/
        └── diagnosing-ci-failures/
            ├── SKILL.md         # the fix workflow (loaded when triggered)
            └── references/
                └── pipeline.md  # this repo's CI jobs + usual failure classes
```

Split of responsibilities:

| Layer | Contains |
|---|---|
| `system_prompt` (Python) | Identity + hard safety rules only (no history rewriting, no AI attribution, stay in repo) |
| `SKILL.md` | The diagnose → report → fix → commit/push workflow |
| `references/pipeline.md` | Repo-specific pipeline knowledge, loaded only when the agent needs it (progressive disclosure) |
| `can_use_tool` callback (Python) | Enforcement — the only layer that can actually block a push |

The skills are loaded via the SDK's `plugins` option
(`plugins=[{"type": "local", "path": "ci-agent/plugin"}]`) rather than from
`.claude/skills/` — skill discovery from `.claude/skills/` requires
`setting_sources=["project"]`, which would also load
`.claude/settings.json`, where a `git push` allow-rule could silently bypass
the approval gate. The plugin path keeps `setting_sources=[]` and the gate
intact. The single-turn triage classifier stays as a plain prompt on
purpose: it uses no tools, so a model-invoked skill would only add cost.

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
