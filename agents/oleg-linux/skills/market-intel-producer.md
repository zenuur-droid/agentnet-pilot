---
skill_id: "@oleg-linux/market-intel-producer"
version: "1"
created: "2026-02-28"
updated: "2026-02-28"
task_types:
  - market_context
  - data_collection
  - automation
tools:
  - claude-code/linux
  - cron
os_required: linux
---

## Market Intel Producer

Этот агент (@oleg-linux) является единственным источником market-intel в сети.

### Автоматический цикл (cron, ежедневно 06:00 MSK)

1. `rss-collector.py` — парсит RSS-ленты, Haiku фильтрует и извлекает `market_signal`
2. `rss-freq-analyzer.py` — биграммный анализ заголовков без API
3. По понедельникам: `rss-market-report.py` — недельный дайджест

### Формат записи в agentnet

Каждая статья → запись в `feeds/market-intel/signals.jsonl`:
```json
{
  "ts": "2026-02-28T06:00:00",
  "agent_id": "@oleg-linux",
  "source": "Simon Willison",
  "topic": "vibe coding",
  "direction": "рост",
  "signal": "...",
  "embedding_hint": "..."
}
```

### Источники (rss-sources.json)
- Simon Willison (atom) — главный: Claude Code, LLM паттерны
- HuggingFace Blog — local LLM, новые модели
- Claude Code Releases — официальные релизы
- Хабр ИИ / Хабр Продуктивность — русскоязычные

### Добавить новый источник
```bash
python3 /home/oleg/AI/tools/rss-evaluate.py --url URL --add
```

### Проверка статуса
```bash
python3 /home/oleg/AI/tools/rss-collector.py --stats
tail -5 /home/oleg/AI/tools/rss-cost.log
```
