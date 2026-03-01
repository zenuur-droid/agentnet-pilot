# agentnet-project — Intel Feed for AgentNet Project

**Type**: project intelligence feed
**Audience**: all agents (@oleg-mac, @oleg-linux, @oleg-win) + user (Oleg)
**Producer**: @oleg-linux via rss-collector.py
**Updated**: daily (cron 03:00 UTC)

---

## Purpose

Целевая разведка для Проекта AgentNet как самостоятельного объекта слежения.

Отличие от других фидов:
- `feeds/market-intel/` — широкий рынок AI (всё что происходит)
- `feeds/claude-ideas/` — что из этого полезно МНЕ как агенту
- **Здесь**: что из этого влияет на ПРОЕКТ AgentNet конкретно

## signals.jsonl — Schema

```json
{
  "ts": "2026-03-01T06:00:00",
  "agent_id": "@oleg-linux",
  "source": "LangChain Blog",
  "url": "https://...",
  "title_original": "...",
  "trend":  "куда движется это направление (1 предл.)",
  "impact": "как это влияет на AgentNet конкретно (1 предл.)",
  "idea":   "что применить буквально и немедленно (1 предл.)",
  "urgency": "now|week|month"
}
```

## Urgency

- `now` — нужна реакция сегодня (новый инструмент/API/критическое изменение)
- `week` — стоит обсудить и спланировать в ближайшие дни
- `month` — стратегический тренд, держать в фокусе

## Tracked Topics

Haiku фильтрует для AgentNet:
- Паттерны координации агентов (AutoGen, CrewAI, LangGraph)
- MCP серверы и инструменты для Claude
- Автономные кодинг-агенты (Devin, SWE-agent, аналоги)
- Память между сессиями, persistent context
- Стоимость API, модельный выбор, оптимизация
- Обновления Claude / Claude Code
- Multi-agent frameworks и протоколы

## Weekly Digest

- `weekly-YYYY-WW.md` — для агентов в сети (без frontmatter)
- `2_Проекты/AgentNet/_intel-YYYY-WW.md` — для пользователя в vault
