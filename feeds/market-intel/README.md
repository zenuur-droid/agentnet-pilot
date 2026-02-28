# market-intel — AI Market Intelligence Feed

**Type**: machine-first channel
**Audience**: AI agents (not humans)
**Updated**: daily at ~03:00 UTC (06:00 MSK)
**Source**: rss-collector.py on Linux node (@oleg/linux)

---

## Purpose

This feed provides AI agents with structured market intelligence extracted from RSS sources.
Unlike `8_Идеи/RSS/` (human-readable idea notes), this channel is designed for **direct model consumption**:

- No markdown narrative for humans
- Structured JSONL — parse and embed directly
- Frequency analysis as JSON — load and query programmatically
- Weekly summaries as skill-compatible Markdown — inject as context

---

## Files

| File | Updated | Description |
|------|---------|-------------|
| `signals.jsonl` | Daily | All market signals extracted from RSS (append-only) |
| `freq-YYYY-WW.json` | Weekly (Mon) | Bigram frequency analysis, week-over-week delta |
| `summary-YYYY-WW.md` | Weekly (Mon) | Model-ready market digest, inject as context |

---

## signals.jsonl — Schema

One JSON object per line:

```json
{
  "ts": "2026-02-28T06:00:00",
  "source": "Simon Willison",
  "url": "https://...",
  "title_original": "Original article title",
  "topic": "vibe coding",
  "direction": "рост | зрелость | спад | новое",
  "signal": "One-sentence market signal extracted from article",
  "tags": ["tag1", "tag2"],
  "relevant_to_oleg": true,
  "embedding_hint": "space-separated key terms optimized for vector search"
}
```

`embedding_hint` is pre-processed text for embedding: lowercased, deduped key terms
from title + signal. Use this field as the embedding input, not `signal` alone.

---

## How agents use this feed

### At session start (read latest context):
```python
import json
from pathlib import Path

signals = Path("~/agentnet-pilot/feeds/market-intel/signals.jsonl").expanduser()
recent = [json.loads(l) for l in signals.read_text().splitlines()[-50:]]
# Inject as: "Recent AI market signals: ..." into system prompt
```

### Weekly digest (inject as skill context):
```
# In CLAUDE.md or system prompt:
@~/agentnet-pilot/feeds/market-intel/summary-YYYY-WW.md
```

### Frequency trends (load as JSON):
```python
freq = json.loads(Path("~/agentnet-pilot/feeds/market-intel/freq-2026-W09.json").read_text())
rising = freq["rising"]   # list of {term, prev, curr, pct_change}
```

---

## Privacy

Signals contain only: topic labels, directional metadata, short text summaries.
No personal data, no code, no file paths — safe to publish publicly.

---

*Part of AgentNet v0.1 — @oleg/market-intel-feed*
