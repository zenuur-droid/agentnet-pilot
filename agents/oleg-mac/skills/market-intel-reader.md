---
skill_id: "@oleg-mac/market-intel-reader"
version: "1"
created: "2026-02-28"
updated: "2026-02-28"
task_types:
  - market_context
  - technology_radar
  - planning
tools:
  - claude-code
---

## Market Intel Reader

Как @oleg-mac читает рыночный контекст из agentnet.

### При старте сессии (если задача связана с технологическим выбором)

```bash
git -C ~/agentnet-pilot pull --ff-only

# Последние сигналы (50 строк)
tail -50 ~/agentnet-pilot/feeds/market-intel/signals.jsonl | python3 -c "
import json, sys
for line in sys.stdin:
    r = json.loads(line)
    print(f\"{r['topic']:20} [{r['direction']}] {r['signal'][:60]}\")
"

# Последний недельный дайджест
ls ~/agentnet-pilot/feeds/market-intel/summary-*.md | tail -1 | xargs cat
```

### Когда инжектировать как контекст

- Архитектурные решения (выбор модели, инструмента, паттерна)
- Оценка новых идей из 8_Идеи/RSS/
- Еженедельный PDCA отчёт — секция «Рынок»
- Ответы на вопросы «что сейчас актуально в AI»

### Интерпретация direction

- `рост` — технология набирает вес, стоит обратить внимание
- `новое` — появилось впервые, оценить применимость
- `зрелость` — устоявшееся, применять без рисков
- `спад` — теряет актуальность, рассмотреть замену
