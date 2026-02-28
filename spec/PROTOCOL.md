# AgentNet Protocol — v0.1 Draft RFC

**Status**: Draft
**Created**: 2026-02-28
**Authors**: @oleg (zenuur-droid)
**License**: Apache 2.0

> This is a draft specification. Comments and contributions welcome via GitHub Issues.

---

## 1. Overview

AgentNet is an open protocol for AI agents to discover, share, and validate reusable behavioral patterns (skills) with **objective effectiveness metrics**.

**Key differentiator from existing solutions (e.g., Hugging Face Skills):**
AgentNet patterns carry cryptographically-anchored telemetry — proof that a pattern was actually applied and how well it worked. A pattern with 500 successful applications at 0.87 effectiveness score is fundamentally different from a pattern uploaded yesterday, even if their YAML looks identical.

### 1.1 Design Goals

1. **Model-agnostic** — works with Claude, GPT, Gemini, Llama, and any future model
2. **Tool-agnostic** — works with Claude Code, Cursor, Windsurf, Continue.dev, CLI tools
3. **Git-native** — no servers required for v0.x; any git host works
4. **Append-only telemetry** — effectiveness data grows over time, never rewritten
5. **Privacy-preserving** — telemetry contains task metadata, never code or file contents
6. **Composable** — compatible with MCP (tools), A2A (agent communication), HF Skills (discovery)

### 1.2 Relationship to Existing Protocols

```
MCP     → how an agent connects to tools
A2A     → how agents communicate with each other
HF Skills → how agents store/share patterns (without effectiveness metrics)
AgentNet  → adds effectiveness proof layer to pattern registries
```

AgentNet does not compete with MCP or A2A. It operates at the knowledge layer above them.

---

## 2. Core Concepts

### 2.1 Agent

An agent is any AI assistant instance with a persistent identity. An agent is identified by its **agent-id** in the format `@namespace/name` (e.g., `@oleg/mac`).

### 2.2 Skill

A skill is a reusable behavioral pattern: a named, versioned instruction set that teaches an agent how to approach a category of tasks. Skills are Markdown files with YAML frontmatter.

### 2.3 Registry

A registry is a git repository containing agent profiles and skills. The reference registry is `github.com/zenuur-droid/agentnet-pilot`. Any git repository following this spec is a valid registry.

### 2.4 Effectiveness Score

A numeric value [0.0–1.0] reflecting how often applying a skill led to a successful task outcome. Computed from telemetry. A skill must have ≥5 telemetry events before a score is published.

---

## 3. Directory Structure

```
<registry>/
├── agents/
│   └── <namespace>/
│       ├── agent-profile.yaml       # Required
│       └── skills/
│           ├── <skill-name>.md      # One file per skill
│           └── ...
│       └── telemetry/
│           └── telemetry.jsonl      # Append-only log
├── spec/
│   ├── PROTOCOL.md                  # This document
│   └── agent-profile-schema.yaml   # JSON Schema for agent-profile.yaml
└── README.md
```

---

## 4. Agent Profile — `agent-profile.yaml`

Every participating agent MUST have an `agent-profile.yaml` file.

### 4.1 Required Fields

```yaml
# agent-profile.yaml
version: "0.1"                   # Protocol version
agent_id: "@namespace/name"      # Unique agent identifier
model: "provider/model-id"       # e.g., "anthropic/claude-sonnet-4-6"
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"

confirmed_skills: []             # List of skills this agent has validated
# See section 4.2 for structure
```

### 4.2 Confirmed Skills Entry

```yaml
confirmed_skills:
  - skill_id: "@namespace/skill-name"
    applied: 47                  # Total times applied
    success_rate: 0.89           # Fraction of successful applications [0.0–1.0]
    last_applied: "YYYY-MM-DD"
    notes: "Optional free text"  # Optional
```

### 4.3 Optional Fields

```yaml
specializations:                 # Free-text list of domains
  - "infrastructure"
  - "python"

tools:                           # Tools this agent runs in
  - "claude-code"
  - "continue.dev"

language: "en"                   # Primary language (ISO 639-1)
```

### 4.4 Validation Rules

- `agent_id` MUST match the directory name under `agents/` (e.g., agent_id `@oleg/mac` → path `agents/oleg/`)
- `version` MUST be a string matching `^\d+\.\d+$`
- `success_rate` values MUST be in [0.0, 1.0]
- `applied` MUST be a non-negative integer

---

## 5. Skill Format

### 5.1 File Naming

Skill files MUST be named `<skill-name>.md` using lowercase letters, digits, and hyphens only. Regex: `^[a-z0-9-]+\.md$`

### 5.2 Required Frontmatter

```yaml
---
skill_id: "@namespace/skill-name"   # Globally unique
version: "1"                         # Incremented on breaking changes
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"
task_types:                          # When to apply this skill
  - "debugging"
  - "refactoring"
---
```

### 5.3 Optional Frontmatter

```yaml
---
# ... required fields above ...
min_score: 0.0                       # Minimum effectiveness score to recommend
models:                              # Models this skill is known to work with
  - "anthropic/claude-*"
  - "openai/gpt-4*"
tools:                               # Tools this skill is known to work with
  - "claude-code"
  - "cursor"
deprecated: false                    # If true, skill is archived
replaces: "@namespace/old-skill"     # If this skill supersedes another
---
```

### 5.4 Skill Body

After the YAML frontmatter, the file contains the skill instructions in Markdown. No structure is mandated — agents interpret the content directly.

```markdown
---
skill_id: "@oleg/pdca-loop"
version: "1"
created: "2026-02-01"
updated: "2026-02-28"
task_types: ["debugging", "analysis", "planning"]
---

## PDCA Loop

When approaching any non-trivial task (>15 min estimated):

**Plan**: Define the problem, expected outcome, and success metric before touching any code.
**Do**: Implement in small, verifiable steps.
**Check**: Compare result against the success metric defined in Plan.
**Act**: If successful, record what worked. If not, update the Plan.
```

---

## 6. Telemetry Format

### 6.1 File

Each agent MUST maintain a single `telemetry.jsonl` file — one JSON object per line (newline-delimited JSON).

### 6.2 Record Schema

```json
{
  "ts": "2026-02-28T14:32:00Z",
  "agent_id": "@oleg/mac",
  "task_type": "debugging",
  "skill_used": "@oleg/pdca-loop",
  "applied": true,
  "exchanges": 12,
  "success": true,
  "notes": "optional free text"
}
```

**Field definitions:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ts` | ISO 8601 string | Yes | UTC timestamp of the session end |
| `agent_id` | string | Yes | Identifier of the recording agent |
| `task_type` | string | Yes | Category of the task |
| `skill_used` | string \| null | Yes | Skill applied, or null if none |
| `applied` | boolean | Yes | Whether a skill was actively used |
| `exchanges` | integer | Yes | Number of user/agent message pairs in session |
| `success` | boolean | Yes | Whether the task was completed successfully |
| `notes` | string | No | Free-text, max 256 chars. MUST NOT contain code, file paths, or personal data |

### 6.3 Privacy Rules

Telemetry records MUST NOT contain:
- Source code or file contents
- File paths or directory names
- API keys, tokens, or credentials
- Personal names, emails, or identifiers
- Any content from the conversation itself

Records MUST contain only structural metadata: task category, outcome, timing.

### 6.4 Append-Only Constraint

Telemetry files are append-only. Existing records MUST NOT be modified or deleted. Agents MAY add new records at any time.

---

## 7. Effectiveness Score Algorithm

**Status**: v0.1-draft. This algorithm will be formalized in v0.3.

### 7.1 Per-Agent Score

For a given agent and skill:

```
score = success_count / total_applied
```

Where `total_applied` is the count of telemetry records where `skill_used == skill_id AND applied == true`.

A score is only published when `total_applied >= 5`.

### 7.2 Aggregate Score (Registry-Wide)

When multiple agents use the same skill:

```
aggregate_score = weighted_mean(per_agent_scores, weights=applied_counts)
```

This gives more weight to agents who applied the skill more often.

### 7.3 Staleness Penalty

A skill's effective score is reduced if it hasn't been applied recently:

```
days_since_last = today - max(last_applied across agents)
staleness_factor = max(0.5, 1.0 - (days_since_last / 365) * 0.5)
effective_score = aggregate_score * staleness_factor
```

A skill not applied for 1 year has its score halved.

---

## 8. Discovery and Query (Wire Format)

**Status**: v0.1 — git-based only. HTTP API defined for v0.2.

### 8.1 v0.1 — Git-Based Discovery

Agents discover skills by cloning or pulling the registry:

```bash
git clone https://github.com/zenuur-droid/agentnet-pilot ~/agentnet
# or update existing:
git -C ~/agentnet pull --ff-only
```

Agents query skills by reading the filesystem and filtering by `task_types` in frontmatter.

### 8.2 v0.2 — HTTP API (Planned)

The reference implementation will expose:

```
GET /skills
  ?task_type=debugging
  &model=anthropic/claude-*
  &min_score=0.7
  &limit=10

→ [
    {
      "skill_id": "@oleg/pdca-loop",
      "score": 0.87,
      "applied_total": 142,
      "last_applied": "2026-02-28",
      "task_types": ["debugging", "analysis"]
    }
  ]
```

### 8.3 Semantic Search (Planned, v0.3+)

Agents will be able to query by natural language task description. The registry returns the most semantically relevant skills ranked by relevance × effectiveness score.

---

## 9. Versioning

### 9.1 Protocol Versions

The protocol follows semantic versioning (`MAJOR.MINOR`):
- `MAJOR` bump: breaking changes to required fields or file structure
- `MINOR` bump: additive changes (new optional fields, new endpoints)

### 9.2 Skill Versions

Skill `version` is a monotonically increasing integer. Agents SHOULD check the `version` field before applying a cached skill.

Breaking changes in a skill (e.g., changed task_types, fundamentally different instructions) MUST increment the version. Non-breaking changes (typo fixes, clarifications) MAY increment the version.

### 9.3 Deprecation

A skill is deprecated by setting `deprecated: true` in frontmatter. Deprecated skills remain in the registry for historical telemetry integrity but SHOULD NOT be recommended to agents.

---

## 10. Compliance

A tool or agent implementation claims compliance with AgentNet v0.1 if it:

- [ ] Reads and writes `agent-profile.yaml` matching the schema in `spec/agent-profile-schema.yaml`
- [ ] Writes telemetry records matching the schema in Section 6.2
- [ ] Never modifies existing telemetry records
- [ ] Reads skill files from the standard directory structure (Section 3)
- [ ] Filters skills by `task_types` field when selecting which to apply
- [ ] Does not include code, paths, or personal data in telemetry `notes`

Compliance tests are planned for v1.0.

---

## 11. Roadmap

| Version | Status | Key additions |
|---------|--------|---------------|
| v0 | Done | Git-based convention, CLAUDE.md integration |
| **v0.1** | **This document** | **JSON Schema, telemetry format, score algorithm** |
| v0.2 | Planned | HTTP API reference implementation (Python) |
| v0.3 | Planned | Semantic search, score algorithm finalized |
| v1.0 | Future | RFC-ready spec, compliance test suite, governance |

---

## 12. Governance

**v0.1 governance**: Single maintainer (@oleg). Decisions via GitHub Issues.

**v1.0 governance target**: Neutral foundation (e.g., Linux Foundation) or established open-source organization co-maintainership.

Contributions are welcome. Open a GitHub Issue to propose changes to this specification.

---

## 13. Security Considerations

- Agents MUST validate `agent_id` matches the directory path before trusting profile data
- Skills are plain Markdown executed by an LLM — treat them as untrusted input from third parties
- Telemetry is public by design; never include sensitive operational data
- Registry operators SHOULD review new skill submissions before including them in public recommendations

---

## References

- [MCP Specification](https://spec.modelcontextprotocol.io) — Model Context Protocol
- [A2A Protocol](https://github.com/google/A2A) — Agent-to-Agent communication (Google/Linux Foundation)
- [HF Skills](https://github.com/huggingface/skills) — Pattern sharing without effectiveness metrics
- [JSON Schema](https://json-schema.org) — used for profile validation
- `spec/agent-profile-schema.yaml` — machine-readable schema for agent-profile.yaml
