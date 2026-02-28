---
skill_id: "@oleg-win/vault-rag-query"
version: "1"
created: "2026-02-28"
updated: "2026-02-28"
task_types:
  - research
  - knowledge_retrieval
  - context_building
tools:
  - claude-code
  - mcp-vault-rag
os_required: windows
---

## Vault RAG Query

@oleg-win единственный агент в сети с MCP vault-rag — семантический поиск по всему Obsidian vault.

### Доступные инструменты

```
vault_search(query, filter_tags, limit)  — семантический поиск
vault_status()                           — статус индекса
```

### Когда использовать

- Поиск решений из прошлых сессий ("как мы решали X?")
- Поиск паттернов в Knowledge Base
- Контекст по конкретным людям/компаниям/концепциям
- Поиск по логам сессий ("что делали в феврале?")

### Стратегия запросов

Конкретные термины > общие фразы:
```
✓ vault_search("tailscale amnezia split tunnel")
✗ vault_search("vpn настройка")

✓ vault_search("rss-collector market signal")
✗ vault_search("система сбора информации")
```

### Ограничения

- Индекс обновляется с задержкой (~10 мин после git pull на Linux)
- Новые файлы появляются в поиске только после переиндексации
- Максимум 15 результатов за запрос

### Делиться результатами

Если нашёл что-то полезное для других агентов — записать в навык или MEMORY.md,
а не держать только в контексте текущей сессии.
