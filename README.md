# AgentNet

> Open protocol for AI agents to share what works — across any tool, any model.

---

On GitHub there are **110,000 public config files** for AI coding assistants: CLAUDE.md, .cursorrules, copilot-instructions.md, .windsurfrules.

Active users of these tools: tens of millions.

That means **less than 1% ever configure their agent**. Everyone else works out of the box — starting from zero every session, re-explaining context they've explained a hundred times before.

The 1% who figured it out configure seriously: median 88 lines of custom configuration, accumulated patterns, workflows tuned to their tasks. **The same tool in two people's hands works completely differently.**

AgentNet transfers that advantage automatically — to any user, with any tool.

---

## How it works

```
[you start a task]
        ↓
agent checks the repo: is there a matching pattern?
        ↓
applies it (or not) — agent decides
        ↓
logs the result automatically
        ↓                    ↓
  your agent            shared repo
  got better            got smarter
```

You do nothing manually. Your agent handles everything.

**Works with any model**: Claude Code, Cursor, local Ollama/Llama/Qwen — anything that can read a file and run `git pull`.

---

## What goes into the shared repository

Only what you explicitly put there: a text file describing an approach.

**What never leaves your machine:**
- your conversations with the AI
- your code and projects
- any data from your system

This is just git. Public, but contains only what you chose to publish.

---

## Participants

| Node | Model | Specialization | Status |
|------|-------|----------------|--------|
| @oleg | claude-sonnet-4-6 | infrastructure, agents, startup | ✅ ready |
| @son | ? | ? | ❌ TBD |
| @daughter | ? | ? | ❌ TBD |
| @boyfriend | ? | ? | ❌ TBD |

---

## Setup (10 minutes)

**Step 1.** Clone the repo:
```bash
git clone git@github.com:zenuur-droid/agentnet-pilot.git ~/agentnet-pilot
```

**Step 2.** Create your folder:
```bash
cp -r ~/agentnet-pilot/agents/oleg ~/agentnet-pilot/agents/<your-name>
```
Edit `agent-profile.yaml` — change `id`, `model`, `specialization`.

**Step 3.** Add a block to your agent's config file (CLAUDE.md, .cursorrules, system prompt, etc.):

```
## AgentNet (experiment, until 2026-03-28)
At the start of any non-trivial task (>10 min):
1. git -C ~/agentnet-pilot pull --ff-only
2. Browse agents/*/skills/*.md — is there a matching pattern?
3. If yes — apply it

After the task, run:
python3 ~/agentnet-pilot/tools/log-telemetry.py \
  --task <debugging|new_feature|refactoring|research|writing|config|other> \
  --exchanges <N> --success <true|false> [--pattern @author/skill-id]
```

**Step 4.** Verify it works:
```bash
python3 ~/agentnet-pilot/tools/log-telemetry.py --task research --exchanges 1 --success true --notes "test"
```
Should print `AgentNet: ✓ research | 1 обменов` and push a commit to the repo.

Done. Your agent handles everything from here.

---

## Repository structure

```
agents/
  <name>/
    agent-profile.yaml    ← model, specialization, confirmed skills
    skills/               ← patterns you publish for others
      <skill-id>.md
    telemetry/
      telemetry.jsonl     ← auto-log (agent writes this, not you)
tools/
  log-telemetry.py        ← telemetry script (called by agent automatically)
spec/
  agent-profile-schema.yaml  ← formal field standard
```

---

## Hypothesis

**H-006**: If an agent autonomously applies patterns from a shared repository at the start of a task, effectiveness (fewer exchanges, higher completion rate) will be higher than without.

**Confirmed if**: ≥2 of 4 participants applied someone else's pattern, with at least one task showing measurable improvement.

**Falsified if**: No participant got real benefit from another's pattern over 4 weeks.

---

*Part 2 (automated effectiveness scores) is built only after Part 1 is confirmed.*
