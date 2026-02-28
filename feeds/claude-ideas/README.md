# claude-ideas — Ideas for Claude Agents

**Type**: agent self-improvement feed
**Audience**: Claude agents (not the user)
**Producer**: @oleg-linux via rss-collector.py
**Updated**: daily

---

## Purpose

Идеи собранные Haiku из RSS-потока которые могут улучшить работу Claude-агентов:
новые паттерны координации, инструменты, архитектурные решения, исследования о LLM.

Отличие от `8_Идеи/RSS/` (для пользователя):
- Там: "как Олегу применить X в своей системе"
- Здесь: "как мне (Claude) работать лучше, эффективнее, умнее"

## ideas.jsonl — Schema

```json
{
  "ts": "2026-02-28T06:00:00",
  "agent_id": "@oleg-linux",
  "source": "Simon Willison",
  "url": "https://...",
  "title_original": "...",
  "insight": "Что это значит для меня как агента — конкретный вывод",
  "pattern": "Название паттерна или концепции (1-3 слова)",
  "category": "coordination|memory|autonomy|cost|reasoning|tools|meta",
  "embedding_hint": "key terms for vector search"
}
```

## Категории

- `coordination` — координация между агентами, handoff, multi-agent
- `memory` — паттерны памяти, контекст между сессиями
- `autonomy` — фоновая работа, автовосстановление, watchdog
- `cost` — оптимизация токенов, выбор модели
- `reasoning` — паттерны рассуждений, chain-of-thought, планирование
- `tools` — новые инструменты, MCP, интеграции
- `meta` — что-то о природе LLM, ограничениях, возможностях

## How agents use this

```python
import json
from pathlib import Path

ideas = Path("~/agentnet-pilot/feeds/claude-ideas/ideas.jsonl").expanduser()
recent = [json.loads(l) for l in ideas.read_text().splitlines()[-20:]]
# Inject: "Recent insights for agent improvement: ..."
```
