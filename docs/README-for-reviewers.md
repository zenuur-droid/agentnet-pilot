# AgentNet — Full Project Context for Review

This folder contains the complete strategic thinking behind AgentNet.
Read these to understand the full picture — then break it.

## Start here

**[PROTOCOL.md](../spec/PROTOCOL.md)** — the technical specification (v0.1 Draft RFC)

## Strategic documents (Russian, use your Claude to translate/summarize)

| File | What it contains |
|------|-----------------|
| [market-research.md](market-research.md) | GitHub data (13K CLAUDE.md files), Google Trends, TAM estimate |
| [strategic-analysis.md](strategic-analysis.md) | Why smart people chose proprietary path; why we chose open protocol |
| [protocol-and-players.md](protocol-and-players.md) | HF Skills discovery; what a real protocol requires; how each major player responds |
| [architectural-decisions.md](architectural-decisions.md) | AD-001 through AD-006 — all key decisions with context and rationale |

## The six architectural decisions in plain English

**AD-001** — AgentNet is LinkedIn for AI skills, not just an open protocol. Your cognitive patterns are YOUR professional asset, not your employer's.

**AD-002** — Public registry + private enterprise registries using the same protocol. Like HTTP — open protocol, private servers.

**AD-003** — Neutral governance (Linux Foundation target) is the only non-reproducible moat. Meta can copy the tools. They cannot copy structural neutrality.

**AD-004** — Marketplace model: 1% of power users sell configurations to 99% who benefit. Closes the documented AI productivity gap (top 10% get 5-10x gains vs median 10-20%).

**AD-005** — Both creators AND validators earn. Creators 70%, platform 20%, validation pool 10% distributed to users based on telemetry quality and volume. Clinical trial model — participants get paid for generating data.

**AD-006** — Threat map by stage. Most dangerous: Anthropic nativizing in next 3 months. Second: GitHub Marketplace in 6-12 months. Counter: engage Anthropic now, Linux Foundation by March.

## Questions worth attacking

1. Is AD-001 (LinkedIn framing) real differentiation or just rebranding?
2. Can effectiveness scores actually be gamed? (contribute fake telemetry to boost your pattern's score)
3. What's the actual legal basis for "cognitive patterns belong to the employee"? Is this solid in US law?
4. Does the validation economy (AD-005) create perverse incentives?
5. Is the window really as short as AD-006 says? What if Anthropic doesn't care about this space?

## How to use this as a reviewer

Give this entire `docs/` folder to your Claude Code and ask:
- "What are the weakest assumptions in these architectural decisions?"
- "What scenarios are not considered in the threat map?"
- "Is the LinkedIn analogy structurally valid or superficial?"
- "What would have to be true for this to succeed?"

Be brutal. The author wants real critique, not validation.
