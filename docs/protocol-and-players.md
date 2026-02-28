---
type: analysis
project: "[[AgentNet — сеть AI агентов]]"
created: 2026-02-28
updated: 2026-02-28
tags: [проект, agentnet, strategy, protocol, competitive]
---

# AgentNet — Спецификация, co-author, ответы игроков

> Развитие [[AgentNet — Стратегический анализ]].
> Два вопроса: что нужно чтобы быть протоколом + что сделают крупные игроки.

---

## Часть 1: Мы не первые. Что это означает.

Исследование выявило: Hugging Face Skills **уже существует**.

```
github.com/huggingface/skills
Apache 2.0, 6,500 GitHub stars, ноябрь 2025
Формат: SKILL.md (YAML frontmatter + instructions)
Поддержка: Claude Code, OpenAI Codex, Gemini CLI, Cursor
```

Ещё существуют:
- **Continue.dev Hub** — marketplace конфигураций, 26K stars, синхронизируется между IDE
- **A2A Protocol** (Google → Linux Foundation) — agent-to-agent коммуникация, июнь 2025
- **MCP** (Anthropic → Linux Foundation) — tool integration, 97M downloads/мес
- **OpenEnv** (Meta + HF) — shared execution environments

**Карта ландшафта:**

```
MCP          → как агент подключает инструменты
A2A          → как агенты общаются между собой
HF Skills    → как агент хранит/шарит patterns (БЕЗ метрик)
Continue Hub → как пользователь шарит конфигурацию
AgentNet     → ???
```

### Где реальная дыра

Всё что существует — это **хранение и шаринг паттернов без объективной оценки эффективности**.

HF Skills позволяет опубликовать паттерн. Но:
- Нет данных применялся ли он реально
- Нет метрики помог ли он
- Нет механизма устаревания
- Нет разницы между паттерном который применили 1000 раз успешно и тем который опубликовали вчера

**AgentNet's real differentiator = телеметрия + effectiveness scores.**

Не «шаринг паттернов» — это уже есть. А **доказанные паттерны с объективными метриками**.

Это меняет позиционирование:

| Было | Стало |
|------|-------|
| «открытый реестр паттернов» | «первый реестр с доказанной эффективностью» |
| конкурирует с HF Skills | дополняет HF Skills (adds proof layer) |
| нужно создать категорию | нужно занять незанятую нишу в существующей категории |

---

## Часть 2: Что нужно чтобы быть протоколом

### Разница между convention и protocol

Сейчас у нас: структура папок + README. Это **convention** — договорённость.

Протокол требует пяти компонентов:

**1. Формальная спецификация (RFC-style)**

Не «вот как структурировать папки» — а документ отвечающий на:
- Какие поля обязательны, какие опциональны (JSON Schema)
- Как версионировать паттерны
- Что значит «паттерн устарел»
- Как агент делает discovery (находит реестр)
- Как агент делает query (находит подходящий паттерн)
- Формат telemetry записи
- Что считается «effectiveness score» и как он вычисляется

**2. Wire format — как агент запрашивает паттерны**

Сейчас: `git pull` + ручной просмотр файлов.
Для протокола нужно:
```
GET /patterns?task_type=debugging&model=claude&min_score=0.7
→ [{"id": "@oleg/pdca-loop", "score": 0.87, "applied": 142, ...}]
```
Или: semantic search по описанию задачи.

**3. Reference implementation**

Минимум: Python библиотека которая:
- Публикует паттерн в реестр
- Запрашивает паттерны по задаче
- Записывает telemetry
- Вычисляет effectiveness score

**4. Governance**

Кто принимает изменения в спецификацию?
Кто модерирует реестр?
Как обрабатываются конфликты?

Без этого: нет доверия у enterprise, нет adoption у других инструментов.

**5. Тесты совместимости**

«Мы совместимы с AgentNet protocol» должно что-то значить конкретное.

### Реальный roadmap к спецификации

```
Сейчас (v0): convention (git + folders)  ← мы здесь
v0.1: JSON schema для agent-profile.yaml + telemetry формат
v0.2: HTTP API reference implementation
v0.3: Effectiveness score алгоритм задокументирован
v1.0: RFC-ready spec + compliance tests
```

v0.1 → это одна неделя работы. v1.0 → это несколько месяцев + input от community.

---

## Часть 3: Co-author с authority — кто и зачем

### Почему это критично

Simon Willison написал пост про что-то — тысячи разработчиков пробуют.
@oleg написал spec — никто не читает.

Это не несправедливо — это реальность. Authority = distribution = adoption.

### Кандидаты

**Вариант A: Hugging Face (лучший стратегически)**

HF Skills уже делает смежное. Если предложить им:
«Мы добавляем то чего у вас нет — telemetry + effectiveness scores — как слой поверх HF Skills»

Они получают: доказанность их реестра.
Мы получаем: их платформу (крупнейший open AI hub) и их governance.

Точка входа: MCP Dev Summit, NYC, апрель 2026. HF co-host вместе с Anthropic.

**Вариант B: Continue.dev (лучший технически)**

Они строят open-source Copilot. Уже имеют Hub для конфигураций.
Им нужно именно то что у нас: cross-tool knowledge sharing.
Их пользователи = наши пользователи.

Если AgentNet станет «the knowledge layer for Continue Hub» — instant distribution к 26K+ разработчикам.

**Вариант C: Simon Willison (@simonw)**

Не co-author спека — но early adopter + public writeup.
Один пост от него = тысячи разработчиков видят протокол.
Нужно: рабочий proof-of-concept + реальные данные (у нас есть: H-007 90 файлов).

**Вариант D: Swyx / Latent Space**

10M+ читателей/слушателей в год. Keynote «Agent Engineering» на summit 2025.
Не co-author — но идеальный канал для объяснения протокола широкой аудитории.
Realistically: питч на Latent Space episode после того как есть v0.1 спека.

### Рекомендованная последовательность

```
Февраль 2026 (сейчас):
  → Написать v0.1 спеку (1 неделя)
  → Открыть GitHub Discussion: "RFC: AgentNet Protocol v0.1"

Март 2026:
  → Continue.dev: открыть issue/discussion в их репо
  → Предложить интеграцию AgentNet как knowledge layer для их Hub

Апрель 2026 (MCP Dev Summit):
  → Hugging Face: предложить AgentNet как "proof layer" поверх HF Skills
  → Simon Willison: питч через Twitter/email с данными H-007

После подтверждения H-006 (март 2026):
  → Полноценный анонс: данные + спека + партнёры
```

---

## Часть 4: Стратегические ответы крупных игроков

### Как оценивать вероятность ответа

Игроки отвечают когда:
1. Видят угрозу своему moat
2. Видят возможность (дистрибуция, данные, revenue)
3. Community pressure вынуждает

Для протокола с 4 участниками — никто не отреагирует. При 1,000 участниках — начнут замечать. При 10,000 — будут отвечать.

Рассмотрим сценарии при **значимой traction (1,000+ участников)**:

---

### Anthropic

**Интересы**: экосистема Claude Code, MCP как стандарт, продажа compute.

**Вероятный ответ: Embrace + Extend**

Anthropic не будет конкурировать с открытым протоколом — это противоречит их стратегии (они уже отдали MCP в Linux Foundation). Скорее всего:

- Нативная поддержка AgentNet в Claude Code: `claude agentnet pull`
- AgentNet становится официальным расширением MCP для agent knowledge
- Возможно: Claude Code начинает автоматически логировать telemetry при использовании AgentNet

**Риск для нас**: Если они нативизируют, мы теряем uniqueness в Claude сегменте. Но AgentNet при этом получает огромный distribution.

**Стратегический ответ**: Идти к ним проактивно. Предложить AgentNet как «MCP extension для knowledge». Если они примут — мы выиграли даже если "проиграли" independence.

---

### Cursor

**Интересы**: $29B оценка, VC pressure, user lock-in, data moat.

**Вероятный ответ: Ignore → Clone**

Cursor не будет реализовывать открытый протокол — это угрожает их lock-in стратегии.

Более вероятно:
- **Cursor Patterns** — проприетарная фича в Cursor 3.0: sync `.cursor/rules` внутри команды / через Cursor платформу
- Не open protocol, но для большинства Cursor пользователей — «достаточно»
- Маркетинг: «Patterns sync» как платная фича Pro/Enterprise

**Timeline**: Если AgentNet наберёт заметную traction → Cursor выпустит это в течение одного квартала.

**Риск для нас**: Их 45K конфигов + встроенная дистрибуция = быстрое closed-ecosystem решение которое кажется «достаточным».

**Стратегический ответ**: Занять позицию ДО того как Cursor реагирует. Показать почему closed-ecosystem patterns менее ценны (нет cross-tool данных, нет endorsement от пользователей других инструментов).

---

### GitHub / Microsoft

**Интересы**: GitHub Marketplace revenue, VS Code ecosystem, enterprise tools.

**Вероятный ответ: GitHub Marketplace for AI Patterns**

Это буквально их бизнес. GitHub уже:
- GitHub Actions Marketplace (100K+ actions)
- GitHub Copilot Workspace
- VS Code Extension Marketplace

«AI Patterns Marketplace» = следующий логичный шаг. Если AgentNet доказывает что рынок существует — GitHub его займёт с полной силой: $2.5T Microsoft backing, distribution через github.com.

**Timeline**: 6-12 месяцев после того как паттерн будет очевиден.

**Риск**: Самый опасный сценарий. Microsoft может сделать это лучше нас с точки зрения infrastructure и distribution.

**Стратегический ответ**: Занять governance позицию через нейтральную организацию (Linux Foundation / Apache) ДО того как GitHub заходит. Если спека уже существует и принята сообществом — GitHub будет имплементировать наш стандарт, а не создавать свой.

---

### Hugging Face

**Интересы**: open AI ecosystem, быть hub для всего open source AI.

**Вероятный ответ: Partner или Merge**

HF не конкурент — они платформа. Если AgentNet доказывает ценность effectiveness scores поверх их Skills реестра — логичный шаг: host AgentNet registry на HF infrastructure.

Это win-win:
- HF получает: доказанные паттерны (не просто uploaded)
- AgentNet получает: HF distribution + governance + trust

**Timeline**: Можно инициировать прямо сейчас через их GitHub.

**Стратегический ответ**: Это самый приоритетный partner. Подойти с конкретным предложением: «AgentNet = effectiveness proof layer поверх HF Skills. Хотите co-develop?»

---

### Letta / MemGPT

**Интересы**: memory-first agents, enterprise API.

**Вероятный ответ: Complementary positioning**

Letta строит memory architecture (как агент хранит состояние). AgentNet строит knowledge registry (какие паттерны работают). Это разные уровни стека.

Возможно: Letta интегрирует AgentNet как knowledge source для своих агентов. Letta Code + AgentNet patterns = мощная комбинация.

**Риск**: Letta может добавить свой patterns layer поверх своей memory architecture. Это их «горизонтальная экспансия».

**Стратегический ответ**: Partnership proposal раньше чем они решат строить самостоятельно.

---

### Google (Gemini CLI + A2A)

**Интересы**: A2A protocol adoption, Gemini CLI ecosystem.

**Вероятный ответ: A2A extension**

Google уже co-lead Linux Foundation A2A Protocol. Если AgentNet создаст спеку, они могут:
- Принять AgentNet как «knowledge extension» для A2A
- Или предложить AgentNet лечь поверх A2A wire format

**Стратегический ответ**: Следить за A2A development. Убедиться что AgentNet спека совместима с A2A — тогда Google adoption = наш adoption.

---

## Часть 5: Итоговая карта угроз и возможностей

```
УГРОЗЫ (быстрые):
  Cursor Clone      → 1 квартал при traction → опередить спекой
  Anthropic native  → возможно в 2026 → идти проактивно

УГРОЗЫ (медленные):
  GitHub Marketplace → 6-12 мес → занять governance заранее

ВОЗМОЖНОСТИ (открыты сейчас):
  HF Skills + AgentNet telemetry = сильнее вместе
  Continue.dev Hub = distribution к 26K разработчикам
  MCP Dev Summit April 2026 NYC = точка входа

НЕЙТРАЛЬНО:
  Letta, Google A2A = партнёры, не конкуренты если правильно позиционироваться
```

---

## Часть 6: Что делать прямо сейчас

**Приоритет 1 (эта неделя):**
Написать `spec/PROTOCOL.md` — v0.1 RFC.
Цель: 2-3 страницы с JSON schema, wire format, telemetry format.
Это переводит нас из «convention» в «draft protocol».

**Приоритет 2 (этот месяц):**
Открыть GitHub issue в Continue.dev репо:
«Proposal: AgentNet knowledge layer for Continue Hub»
Один issue = первый external validation.

**Приоритет 3 (до MCP Dev Summit):**
Pitch deck для Hugging Face: «AgentNet effectiveness proof layer + HF Skills = полная картина».
Summit April 2026 NYC — идеальная точка для разговора.

**Не делать сейчас:**
- Не идти в public раньше чем есть v0.1 спека
- Не позиционировать против HF Skills (они потенциальный partner, не конкурент)
- Не говорить «первый в мире» — HF Skills уже есть, это неправда

---

## Ссылки

- [[AgentNet — Стратегический анализ]] — почему умные люди выбрали другой путь
- [[AgentNet — Исследование рынка]] — данные по рынку
- [[AgentNet — Часть 1 — MVP]] — текущий пилот
- [[Cursor]], [[Windsurf]], [[GitHub Copilot]], [[Ollama]], [[Anthropic Claude Code]]
