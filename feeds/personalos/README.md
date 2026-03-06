# personalos — Personal Intelligence Feed

**Type**: personal knowledge + health + AI convergence feed
**Audience**: Orchestrator (@oleg-mac), all agents
**Producer**: @oleg-linux via rss-collector.py
**Updated**: daily (cron 03:00 UTC)

---

## Purpose

Разведка на пересечении трёх направлений:
- **Health & Longevity** — биомаркеры, wearables, превентивная медицина
- **Quantified Self** — измерение себя, паттерны данных, self-tracking
- **AI + Health** — AI в медицине, персональные ассистенты здоровья

Конечная цель: **PersonalOS** — локальная векторная база данных о себе,
которая принадлежит пользователю и работает с любой моделью.

## signals.jsonl — Schema

```json
{
  "ts": "2026-03-02T06:00:00",
  "agent_id": "@oleg-linux",
  "source": "Peter Attia",
  "url": "https://...",
  "title_original": "...",
  "domain": "longevity | health-tech | quantified-self | ai-health | biohacking",
  "signal": "Ключевой инсайт за 1 предложение",
  "relevance": "Как это связано с PersonalOS целями (1 предл.)",
  "urgency": "now | week | month",
  "embedding_hint": "key terms для векторного поиска через пробел"
}
```

## Urgency

- `now` — новый инструмент/протокол/данные — применить немедленно
- `week` — изучить и решить нужно ли нам это
- `month` — стратегический тренд, держать в фокусе

## Tracked Topics

Haiku фильтрует из RSS:
- Wearables данные: HRV, sleep staging, recovery, CGM (непрерывный глюкоза)
- Биомаркеры крови: стандартные панели, что добавить, как интерпретировать
- AI + персональное здоровье: модели, которые работают с личными данными
- Longevity протоколы: что доказано, что спорно
- Quantified Self паттерны: корреляции, методологии измерений
- Векторные базы + личные данные: инструменты, privacy-first подходы
- Данные Whoop / Oura / Apple Health: API, экспорт, анализ

## Источники RSS

Добавлены в `rss-sources.json` с category `health-longevity` / `quantified-self`:

| Источник | Фокус |
|----------|-------|
| Peter Attia (The Drive) | Longevity, биомаркеры, протоколы |
| FoundMyFitness (Rhonda Patrick) | Нутриция, генетика, ЗОЖ |
| Longevity Technology | Индустрия longevity |
| Fight Aging! | Наука против старения |
| Levels Health Blog | CGM, метаболическое здоровье |
| Whoop Blog | HRV, sleep, recovery data |
| STAT News | AI в медицине |
| Quantified Self Blog | QS методологии, кейсы |

## Локальные гипотезы

- [[H-009-personalos-quantified-memory]] — количество → качество
- [[H-010-temporal-decay-health-data]] — старение разных типов данных (будущая)

## Связи

- **Проект**: [[PersonalOS]]
- **Инфраструктура**: Qdrant на Linux → MCP → Orchestrator
- **Данные**: Whoop API, ручной ввод крови/чекапов, температура
