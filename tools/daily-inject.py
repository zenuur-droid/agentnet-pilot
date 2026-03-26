#!/usr/bin/env python3
"""
daily-inject.py — инжектирует AI-блок в ежедневную заметку Obsidian.

Запускается каждые 10 минут (LaunchAgent com.daily.inject).
Структура блока:
  ### 🔴 Алерты    — только status: open из active-alerts.yaml (SSoT)
  ### 📡 Разведка  — рыночные тренды и сигналы
  ### 🧠 Развитие Клода — паттерны, техники, новые возможности
  ### 📬 Новости   — RSS-новости дня
  ### 📋 Предложения — готовые предложения от idea-to-proposal (чекбоксы)

Алерты управляются через:
  python3 ~/agentnet-pilot/tools/alert-manager.py --close ID --reason "..."
  python3 ~/agentnet-pilot/tools/alert-manager.py --list
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import yaml as _yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False

# Vault path: Mac = ~/obsidian-backup, Linux = ~/obsidian-vault, Win = ~/obsidian
# Linux имеет обе директории (backup — git repo, vault — worktree для Obsidian).
# Inject должен писать туда, откуда Obsidian читает.
import platform as _platform
if _platform.system() == "Darwin":
    VAULT = Path.home() / "obsidian-backup"
elif (Path.home() / "obsidian-vault" / "Дни").exists():
    VAULT = Path.home() / "obsidian-vault"
elif (Path.home() / "obsidian").exists():
    VAULT = Path.home() / "obsidian"
else:
    VAULT = Path.home() / "obsidian-backup"

DAYS_DIR       = VAULT / "Дни"
AGENTNET       = Path.home() / "agentnet-pilot"
# AG_PROJ_FILE закрыт 23.03.2026 — AgentNet отключён (KE-BRIEF-001)
# AG_PROJ_FILE   = AGENTNET / "feeds" / "agentnet-project" / "signals.jsonl"
CLAUDE_FILE    = AGENTNET / "feeds" / "claude-ideas" / "ideas.jsonl"
MARKET_FILE    = AGENTNET / "feeds" / "market-intel" / "signals.jsonl"
TRIAGE_CACHE   = AGENTNET / "feeds" / "triage-cache.jsonl"
PENDING_HYPO   = VAULT / "AI" / "Claude Code" / "pending-claude-hypotheses.md"
ALERTS_FILE    = AGENTNET / "alerts" / "active-alerts.yaml"
TASKS_INDEX    = VAULT / "1_Задачи" / "Claude Code задачи.md"
ECC_INSIGHTS   = AGENTNET / "feeds" / "ecc-insights" / "latest.json"
RULES_EVAL     = AGENTNET / "feeds" / "rules-eval.jsonl"
HARNESS_VIOLATIONS = Path.home() / "logs" / "harness-violations.jsonl"

DOW_RU = {0: "пн", 1: "вт", 2: "ср", 3: "чт", 4: "пт", 5: "сб", 6: "вс"}


def _sig_date(s: dict) -> str:
    """Извлекает короткую дату из ts сигнала: '12.03'."""
    ts = s.get("ts", "")
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%d.%m")
    except Exception:
        return ""


def _sig_link(s: dict) -> str:
    """Возвращает markdown-ссылку [source](url) или просто (source).
    Очищает utm-параметры для чистоты отображения."""
    url = s.get("url", "")
    src = s.get("source", "")
    if url:
        clean = _normalize_url(url)
        return f"[{src}]({clean})"
    return src


def load_triage_cache() -> dict:
    """url → triage dict. При дубликатах оставляем запись с наивысшим urgency."""
    _urg_rank = {"hot": 0, "warm": 1, "cold": 2}
    cache = {}
    if not TRIAGE_CACHE.exists():
        return cache
    for line in TRIAGE_CACHE.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            url = r["url"]
            if url in cache:
                old_rank = _urg_rank.get(cache[url].get("urgency", ""), 9)
                new_rank = _urg_rank.get(r.get("urgency", ""), 9)
                if new_rank < old_rank:
                    cache[url] = r
            else:
                cache[url] = r
        except Exception:
            pass
    return cache


URGENCY_ICON = {"hot": "🔴", "warm": "🟡", "cold": "⚪"}
_TRIAGE = None  # lazy-loaded singleton


def get_triage(url: str) -> dict | None:
    global _TRIAGE
    if _TRIAGE is None:
        _TRIAGE = load_triage_cache()
    return _TRIAGE.get(url)


def triage_prefix(url: str) -> str:
    """Возвращает префикс вида '🔴 hot ' или '⚠️ ' или ''."""
    t = get_triage(url)
    if not t:
        return ""
    icon = URGENCY_ICON.get(t.get("urgency", ""), "")
    conf = " ⚠️" if t.get("confidence") == "low" else ""
    urgency = t.get("urgency", "")
    return f"{icon} {urgency}{conf} " if icon else ""


def today_note_path() -> Path:
    today = datetime.now().date()
    dow   = DOW_RU[today.weekday()]
    week  = today.isocalendar()[1]
    name  = f"{today.strftime('%d.%m.%Y')}  {dow}  {week}.md"
    return DAYS_DIR / name


def load_recent(path: Path, days: int = 7, limit: int = 20) -> list:
    if not path.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ts = datetime.fromisoformat(r.get("ts", "2000-01-01T00:00:00"))
            if ts >= cutoff:
                records.append(r)
        except Exception:
            continue
    return records[-limit:]


def get_machine_last_active(machine: str):
    """Возвращает дату последнего лог-файла сессии для машины или None."""
    machine_dir_map = {"linux": "Linux", "mac": "Mac", "laptop": "Laptop"}
    dir_name = machine_dir_map.get(machine.lower())
    if not dir_name:
        return None
    machine_log_dir = VAULT / "AI" / "Claude Code" / dir_name
    if not machine_log_dir.exists():
        return None
    import re as _re
    from datetime import date as _date
    dates = []
    for f in machine_log_dir.iterdir():
        m = _re.match(r"(\d{4}-\d{2}-\d{2})\.md$", f.name)
        if m:
            try:
                dates.append(_date.fromisoformat(m.group(1)))
            except ValueError:
                pass
    return max(dates) if dates else None


# Агент → русский алиас для отображения в брифинге
AGENT_DISPLAY = {
    "sysadmin-mac": "@админ-мак",
    "sysadmin-linux": "@админ-линукс",
    "sysadmin-laptop": "@админ-ноут",
    "orchestrator": "@оркестратор",
    "obsidian-vault-manager": "@хранитель",
    "claudian": "@клодиан",
    "matrix-knowledge-agent": "@матрица",
    "book-downloader": "@книжник",
    "source-crawler": "@поисковик",
    "health": "@здоровяк",
    "personalos-agent": "@память",
    "market-intel": "@разведка",
    "telegram-bot": "@бот",
    "site-agent": "@сайт",
    "briefing": "@брифинг",
    "claude-dev": "@развитие",
    "comfyui": "@художник",
    "principles-auditor": "@аудитор",
    # Алиасы машин → канонические агенты (R-028: assignee = агент, не машина)
    "linux": "@админ-линукс",
    "mac": "@админ-мак",
    "laptop": "@админ-ноут",
    "win": "@админ-ноут",
}


def _agent_display(assignee: str) -> str:
    """Преобразует assignee в русский алиас для брифинга."""
    if assignee in ("all", "", "human"):
        return f"`{assignee}` " if assignee != "all" else ""
    display = AGENT_DISPLAY.get(assignee, f"@{assignee}")
    return f"`{display}` "


def _escalation_tag(assignee: str, overdue_days: int, today) -> str:
    """Метка для просроченных задач: 💤 спит (catch-up) или 🆘 эскалация (активна но не делает)."""
    if assignee in ("all", "") or overdue_days < 2:
        return ""
    last_active = get_machine_last_active(assignee)
    if last_active is None:
        return ""
    silence_days = (today - last_active).days
    if silence_days >= 2:
        # Машина спит — не эскалация, а ожидание catch-up
        return f" 💤 *{assignee} спит {silence_days}д — catch-up при пробуждении*"
    return ""


def build_tasks_section() -> str | None:
    """Читает ВСЕ активные задачи из индекса (все исполнители).
    Группирует: просроченные → сегодня → ближайшие 3 дня.
    Пропускает секцию Выполненные.
    Показывает исполнителя если не 'all'.
    Добавляет метку эскалации если assignee молчит >= 2 дней."""
    if not TASKS_INDEX.exists():
        return None

    today = datetime.now().date()

    overdue, today_tasks, upcoming = [], [], []

    in_active = False
    for line in TASKS_INDEX.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Активные"):
            in_active = True
            continue
        if line.startswith("## Выполненные"):
            break  # дальше не читаем
        if not in_active or not line.startswith("- "):
            continue

        # Формат: - YYYY-MM-DD | assignee | recurrence | [[title]]
        parts = line[2:].split("|")
        if len(parts) < 4:
            continue
        raw_date   = parts[0].strip()
        assignee   = parts[1].strip()
        recurrence = parts[2].strip()
        raw_title  = parts[3].strip()
        # Сохраняем wikilink для кликабельности в Obsidian (R-021)
        # Формат: [[T-NNN]] Название (номер кликабелен, название читаемо)
        if raw_title.startswith("[[") and raw_title.endswith("]]"):
            inner = raw_title[2:-2]
        else:
            inner = raw_title
        import re as _re
        t_match = _re.match(r"(T-\d{3})\s+(.*)", inner)
        if t_match:
            title = f"[[{t_match.group(1)}]] {t_match.group(2)}"
        else:
            title = f"[[{inner}]]"

        try:
            import datetime as dt
            deadline = dt.date.fromisoformat(raw_date)
        except ValueError:
            continue

        who = _agent_display(assignee)
        rec_tag = f" `{recurrence}`" if recurrence not in ("once", "none", "") else ""
        item = (title, who, rec_tag, raw_date, assignee)

        delta = (today - deadline).days
        if delta > 0:
            overdue.append((delta, item))
        elif delta == 0:
            today_tasks.append(item)
        elif delta >= -3:
            # Ближайшие 3 дня — показываем в брифинге
            upcoming.append((-delta, item))

    if not overdue and not today_tasks and not upcoming:
        return None

    total = len(overdue) + len(today_tasks) + len(upcoming)
    # Склонение: 1 задача, 2-4 задачи, 5+ задач
    if total % 10 == 1 and total % 100 != 11:
        word = "задача"
    elif 2 <= total % 10 <= 4 and not (12 <= total % 100 <= 14):
        word = "задачи"
    else:
        word = "задач"
    lines = [f"### 📅 Задачи — {total} {word}"]

    def _fmt_date(iso_date: str) -> str:
        """2026-03-26 → 26.03.26"""
        try:
            from datetime import date
            d = date.fromisoformat(iso_date)
            return d.strftime("%d.%m.%y")
        except Exception:
            return iso_date

    for days, (title, who, rec_tag, raw_date, assignee) in sorted(overdue, reverse=True):
        esc = _escalation_tag(assignee, days, today)
        lines.append(f"- [ ] {who}{title}{rec_tag} = {_fmt_date(raw_date)} ⚠️ просрочено {days}д{esc}")

    for title, who, rec_tag, raw_date, _a in today_tasks:
        lines.append(f"- [ ] {who}{title}{rec_tag} = {_fmt_date(raw_date)} *(сегодня)*")

    for days, (title, who, rec_tag, raw_date, _a) in sorted(upcoming):
        lines.append(f"- [ ] {who}{title}{rec_tag} = {_fmt_date(raw_date)}")

    return "\n".join(lines)



def build_action_section() -> str | None:
    """🔴 Требует действия: просроченные задачи + P1 алерты + KEDB P1."""
    import datetime as dt
    import re
    today = dt.date.today()
    items = []

    # Просроченные задачи
    if TASKS_INDEX.exists():
        in_active = False
        for line in TASKS_INDEX.read_text(encoding="utf-8").splitlines():
            if line.startswith("## Активные"):
                in_active = True; continue
            if line.startswith("## Выполненные"):
                break
            if not in_active or not line.startswith("- "):
                continue
            parts = line[2:].split("|")
            if len(parts) < 4: continue
            try:
                deadline = dt.date.fromisoformat(parts[0].strip())
            except ValueError:
                continue
            delta = (today - deadline).days
            if delta > 0:
                title = parts[3].strip().lstrip("[[").rstrip("]]").rstrip()
                items.append(f"- 🔴 **{title}** — просрочено {delta}д")

    # P1 алерты
    if ALERTS_FILE.exists() and _YAML_OK:
        data = _yaml.safe_load(ALERTS_FILE.read_text(encoding="utf-8")) or {}
        for a in data.get("alerts", []):
            if a.get("status") == "open" and a.get("severity") == "P1":
                items.append(f"- 🔴 **[ALERT]** {a.get('title','?')} (`{a.get('id','?')}`)")

    # KEDB P1
    ke_path = Path.home() / "tasks" / "known-errors.yaml"
    if ke_path.exists() and _YAML_OK:
        try:
            ke_data = _yaml.safe_load(ke_path.read_text(encoding="utf-8")) or []
            if isinstance(ke_data, list):
                for ke in ke_data:
                    if ke.get("priority") == "P1" and ke.get("status") == "open":
                        items.append(f"- 🔴 **[KE]** {ke.get('title','?')} (`{ke.get('id','?')}`)")
        except Exception:
            pass

    if not items:
        return None
    lines = ["### 🔴 Требует действия сегодня"] + items
    return "\n".join(lines)

def build_alerts_section() -> str | None:
    """Читает open-алерты из SSoT. Возвращает markdown или None если нет открытых."""
    if not ALERTS_FILE.exists() or not _YAML_OK:
        return None

    data = _yaml.safe_load(ALERTS_FILE.read_text(encoding="utf-8")) or {}
    open_alerts = [a for a in data.get("alerts", []) if a.get("status") == "open"]

    if not open_alerts:
        return None

    icons = {"P1": "🔴", "P2": "🟠", "P3": "🟡", "P4": "⚪"}
    lines = [f"### 🔴 Алерты — {len(open_alerts)} открытых"]
    for a in open_alerts:
        icon = icons.get(a.get("severity", "P2"), "🔴")
        sid  = a.get("id", "?")
        sev  = a.get("severity", "?")
        lvl  = a.get("level", "")
        title = a.get("title", "?")
        occ  = a.get("occurrences", "?")
        last = a.get("last_seen", "?")
        lines.append(f"- {icon} **[{sev}]** `{sid}` {title}")
        lines.append(f"  *{occ}× | last: {last}*")
    lines.append("")
    lines.append(
        "*Закрыть: `python3 ~/agentnet-pilot/tools/alert-manager.py "
        "--close ID --reason \"...\"`*"
    )
    return "\n".join(lines)


def _cluster_by_theme(items: list, key_field: str = "topic") -> list:
    """Кластеризует сигналы по близости тем.

    Группирует записи по URL-домену + keyword overlap (≥2 общих слов из topic/signal).
    Возвращает список кластеров: [{"lead": item, "related": [items], "cluster_label": str}].
    Одиночные записи → кластер из 1.
    """
    if not items:
        return []

    def _words(item):
        text = f"{item.get(key_field, '')} {item.get('signal', '')} {item.get('insight', '')}"
        return set(re.findall(r'[a-zA-Zа-яА-ЯёЁ]{3,}', text.lower()))

    def _domain(item):
        url = item.get("url", "")
        m = re.search(r'https?://(?:www\.)?([^/]+)', url)
        return m.group(1) if m else ""

    assigned = [False] * len(items)
    clusters = []

    for i, item in enumerate(items):
        if assigned[i]:
            continue
        assigned[i] = True
        group = [item]
        words_i = _words(item)
        domain_i = _domain(item)

        for j in range(i + 1, len(items)):
            if assigned[j]:
                continue
            words_j = _words(items[j])
            domain_j = _domain(items[j])
            # Кластер: совпадение домена + ≥1 слово ИЛИ ≥3 общих слова
            common = len(words_i & words_j)
            same_domain = domain_i and domain_i == domain_j
            if (same_domain and common >= 1) or common >= 3:
                assigned[j] = True
                group.append(items[j])

        # Lead — с наивысшим urgency или первый
        _urg_rank = {"now": 0, "hot": 0, "week": 1, "warm": 1, "month": 2, "cold": 2}
        group.sort(key=lambda x: _urg_rank.get(x.get("urgency", ""), 9))
        lead = group[0]
        related = group[1:]
        label = lead.get(key_field, lead.get("pattern", ""))
        clusters.append({"lead": lead, "related": related, "cluster_label": label})

    return clusters


# --- Quality gate: отсеивает hollow/generic сигналы ---
_HOLLOW_PHRASES = [
    "может быть полезно", "может быть интересно", "может оказать влияние",
    "предлагает инструменты", "предлагает практические", "предлагает новые методы",
    "существуют инструменты", "продолжает развиваться", "растущий интерес",
    "набирает популярность", "становится всё более", "открывает новые возможности",
    "демонстрирует эффективность", "повышение понимания", "улучшение взаимодействия",
    "является актуальной проблемой", "может увеличить", "может улучшить",
    "улучшающие эффективность", "увеличение доверия",
    "может повысить", "может снизить", "повышение производительности",
    "улучшение пользовательского опыта", "интеграция современных",
]


def _is_hollow_signal(s: dict) -> bool:
    """Сигнал без конкретного тезиса — generic filler.
    Проверяет ТОЛЬКО текст signal на hollow phrases.
    Не отсекает сигналы с конкретными action."""
    sig = (s.get("signal", "") or "").lower()
    return any(p in sig for p in _HOLLOW_PHRASES)

    return clusters


def _enrich_urgency(signals: list) -> list:
    """Обогащает сигналы urgency из triage-cache.
    Triage пишет hot/warm/cold → маппим в now/week/month для совместимости."""
    URGENCY_MAP = {"hot": "now", "warm": "week", "cold": "month"}
    for s in signals:
        if not s.get("urgency"):
            t = get_triage(s.get("url", ""))
            if t:
                raw = t.get("urgency", "")
                s["urgency"] = URGENCY_MAP.get(raw, raw)
    return signals


def build_recon_section(signals: list, decided: tuple | None = None) -> str:
    """📡 Разведка — рыночные сигналы с urgency-маркировкой."""
    if not signals:
        return ("### 📡 Разведка\n"
                "*(нет сигналов — появятся после следующего прогона в 06:00)*")

    # Обогащаем urgency из triage-cache
    signals = _enrich_urgency(signals)

    # Дедупликация: убираем сигналы с решениями из прошлых брифингов
    if decided is None:
        decided = _load_decided_items()
    decided_urls, decided_topics = decided
    signals = [s for s in signals if not _signal_is_decided(s, decided_urls, decided_topics)]

    # Только сигналы с urgency (остальные пойдут в Новости)
    triaged = [s for s in signals if s.get("urgency")]

    # Дедупликация по topic: один сигнал на topic (оставляем с наивысшим urgency)
    _urg_rank = {"now": 0, "week": 1, "month": 2}
    seen_topics: dict[str, int] = {}  # topic → best urgency rank
    deduped: list = []
    for s in sorted(triaged, key=lambda x: _urg_rank.get(x.get("urgency", ""), 9)):
        topic_key = s.get("topic", "").lower().strip()[:30]
        if topic_key and topic_key in seen_topics:
            continue
        seen_topics[topic_key] = _urg_rank.get(s.get("urgency", ""), 9)
        deduped.append(s)
    triaged = deduped
    if not triaged:
        return ("### 📡 Разведка\n"
                "*(все сигналы — в секции Новости, triage не добавил urgency)*")

    # Quality gate: cold без action или с hollow текстом не попадает в Разведку
    # Hot/warm проходят всегда
    triaged = [s for s in triaged
               if s.get("urgency") != "month" or (s.get("action") and not _is_hollow_signal(s))]

    urgent  = [s for s in triaged if s.get("urgency") == "now"]
    weekly  = [s for s in triaged if s.get("urgency") == "week"]
    monthly = [s for s in triaged if s.get("urgency") == "month"]

    # Кластеризация по теме
    all_ordered = urgent + weekly + monthly
    clusters = _cluster_by_theme(all_ordered, key_field="topic") or []

    # Лимит: до 10 кластеров
    clusters = clusters[:10]
    shown = len(clusters)
    lines = [
        f"### 📡 Разведка — {shown}/{len(triaged)}",
        "*(⚡ горячий — действовать · 📡 тёплый — мониторить · 🔭 холодный — к сведению)*",
        "",
    ]

    def _urgency_icon(s):
        u = s.get("urgency", "")
        return {"now": "⚡", "week": "📡", "month": "🔭"}.get(u, "·")

    def _render_cluster(cl, num):
        lead = cl["lead"]
        related = cl["related"]
        icon = _urgency_icon(lead)
        dt = _sig_date(lead)
        dt_pfx = f"({dt}) " if dt else ""
        link = _sig_link(lead)
        topic = lead.get("topic", lead.get("impact", lead.get("trend", "")))
        signal_text = lead.get("signal", lead.get("idea", ""))
        count_suffix = f" (+{len(related)})" if related else ""
        lines.append(f"{icon} **{num}. {topic}**{count_suffix} *{dt_pfx}{link}*")
        if signal_text:
            lines.append(f"→ *Что*: {signal_text}")
        also_parts = []
        for r in related[:2]:
            r_link = _sig_link(r)
            r_topic = r.get("topic", "")
            if r_topic and r_topic != topic:
                also_parts.append(f"{r_topic} {r_link}")
        if also_parts:
            lines.append(f"→ также: {' · '.join(also_parts)}")
        action = lead.get("action", "")
        benefit = lead.get("benefit", "")
        if action:
            lines.append(f"→ *Сделать*: {action}")
        if benefit:
            lines.append(f"→ *Зачем*: {benefit}")

    for idx, cl in enumerate(clusters, 1):
        if idx > 1:
            lines.append("")
        _render_cluster(cl, idx)

    return "\n".join(lines)


def build_claude_section(ideas: list, decided: tuple | None = None) -> str:
    if not ideas:
        return "### 💡 Клод\n*(нет инсайтов за неделю)*"

    # Дедупликация: убираем идеи с решениями из прошлых брифингов
    if decided is None:
        decided = _load_decided_items()
    decided_urls, decided_topics = decided
    ideas = [i for i in ideas if not _signal_is_decided(i, decided_urls, decided_topics)]

    MAX = 7
    # Приоритет категорий: дефицитные важные — выше; cost последний (избыток)
    cat_priority = {
        "memory": 0, "meta": 1, "autonomy": 2,
        "coordination": 3, "reasoning": 4, "tools": 5, "cost": 6,
    }

    # Фильтр нерелевантных (нет UI/фронтенда → design-system не нужна, и т.п.)
    _IRRELEVANT_PATTERNS = {"design-system", "ui kit", "ui-kit", "фронтенд компонент"}
    ideas = [i for i in ideas
             if not any(p in i.get("pattern", "").lower() for p in _IRRELEVANT_PATTERNS)]

    # Дедупликация: один инсайт на паттерн, плюс семантический dedup по keyword overlap
    seen_patterns: set[str] = set()
    deduped: list = []
    for idea in reversed(ideas):  # reversed → свежие первыми при dedup
        key = idea.get("pattern", "").lower().strip()[:40]
        if key and key not in seen_patterns:
            # Семантический dedup: проверяем overlap слов с уже принятыми
            words = set(re.findall(r'[a-zA-Z]{4,}', key))
            is_dup = False
            for existing_key in seen_patterns:
                existing_words = set(re.findall(r'[a-zA-Z]{4,}', existing_key))
                if len(words & existing_words) >= 2:
                    is_dup = True
                    break
            if not is_dup:
                seen_patterns.add(key)
                deduped.append(idea)
    deduped.reverse()  # вернуть хронологический порядок

    # Приоритет: ideas с action/why выше (обогащённые полезнее при walkthrough)
    sorted_ideas = sorted(deduped, key=lambda i: (
        0 if i.get("action") and i.get("why") else 1,
        cat_priority.get(i.get("category", ""), 9),
    ))

    # Отбираем MAX инсайтов с cap 2 на категорию для разнообразия
    MAX_PER_CAT = 2
    cat_counts: dict[str, int] = {}
    selected: list = []
    for idea in sorted_ideas:
        cat = idea.get("category", "other")
        if cat_counts.get(cat, 0) < MAX_PER_CAT:
            selected.append(idea)
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        if len(selected) >= MAX:
            break

    shown_count = len(selected)
    lines = [f"### 🧠 Развитие Клода — {shown_count}/{len(ideas)}", ""]
    for num, idea in enumerate(selected, 1):
        pattern = idea.get("pattern", "")
        insight = idea.get("insight", "")
        cat     = idea.get("category", "")
        if num > 1:
            lines.append("")
        dt = _sig_date(idea)
        dt_s = f" {dt}" if dt else ""
        link = _sig_link(idea)
        lines.append(f"**{num}. {pattern}** *({cat}{dt_s})*")
        lines.append(insight)
        if link:
            lines.append(f"*{link}*")
        action = idea.get("action", "")
        why = idea.get("why", "")
        # R-025: всегда показываем Сделать/Зачем — если пусто, помечаем для walkthrough
        lines.append(f"→ *Сделать*: {action}" if action else "→ *Сделать*: *(определить при walkthrough)*")
        lines.append(f"→ *Зачем*: {why}" if why else "→ *Зачем*: *(определить при walkthrough)*")

    return "\n".join(lines)


def build_ideas_section(signals: list, decided: tuple | None = None) -> str:
    dir_icon = {"рост": "↑", "новое": "★", "спад": "↓", "зрелость": "→"}
    relevant = [s for s in signals if s.get("relevant_to_oleg")]
    # T-088: убираем сигналы, уже отслеживаемые через SURVEILLANCE-CONFIG
    relevant = [s for s in relevant
                if not (get_triage(s.get("url", "")) or {}).get("already_tracked")]
    # Убираем только hot/warm сигналы — они в секции Разведка. Cold остаются в Новостях.
    _recon_urgencies = {"hot", "warm", "now", "week"}
    relevant = [s for s in relevant
                if (s.get("urgency", "") not in _recon_urgencies
                    and (get_triage(s.get("url", "")) or {}).get("urgency", "") not in _recon_urgencies)]
    if not relevant:
        return "### 📬 Новости\n*(нет новостей за 3 дня)*"

    # Дедупликация: убираем сигналы с решениями из прошлых брифингов
    if decided is None:
        decided = _load_decided_items()
    decided_urls, decided_topics = decided
    fresh = [s for s in relevant if not _signal_is_decided(s, decided_urls, decided_topics)]

    # Фильтр generic/hollow сигналов (reuse _is_hollow из build_recon_section)
    fresh = [s for s in fresh if not _is_hollow_signal(s)]

    # Сортируем: has_action первым, потом actionability, потом direction
    dir_priority = {"новое": 0, "рост": 1, "зрелость": 2, "спад": 3}
    sorted_rel = sorted(fresh, key=lambda s: (
        0 if s.get("action") else 1,
        -int(s.get("actionability", 1)),
        dir_priority.get(s.get("direction", ""), 9),
    ))
    # Только с action ИЛИ actionability >= 4 попадают в топ
    high_value = [s for s in sorted_rel
                  if s.get("action") or int(s.get("actionability", 1)) >= 4]
    # Если мало — добираем из actionability >= 3
    if len(high_value) < 3:
        rest = [s for s in sorted_rel
                if s not in high_value and int(s.get("actionability", 1)) >= 3]
        high_value = (high_value + rest)
    shown_items = high_value[:5]
    # Кластеризация
    clusters = _cluster_by_theme(shown_items, key_field="topic") or []
    clusters = clusters[:5]
    lines = [f"### 📬 Новости — {len(clusters)}/{len(relevant)}", ""]
    for num, cl in enumerate(clusters, 1):
        s = cl["lead"]
        related = cl["related"]
        icon   = dir_icon.get(s.get("direction", ""), "·")
        topic  = s.get("topic", "")
        signal = s.get("signal", "")
        action = s.get("action", "")
        pfx    = triage_prefix(s.get("url", ""))
        dt     = _sig_date(s)
        dt_pfx = f"({dt}) " if dt else ""
        link   = _sig_link(s)
        count_suffix = f" (+{len(related)})" if related else ""
        if num > 1:
            lines.append("")
        lines.append(f"{icon} {pfx}**{num}. {topic}**{count_suffix} *{dt_pfx}{link}*")
        lines.append(f"→ *Что*: {signal}")
        also_parts = []
        for r in related[:2]:
            r_link = _sig_link(r)
            r_topic = r.get("topic", "")
            if r_topic and r_topic != topic:
                also_parts.append(f"{r_topic} {r_link}")
        if also_parts:
            lines.append(f"→ также: {' · '.join(also_parts)}")
        if action:
            lines.append(f"→ *Сделать*: {action}")
        benefit = s.get("benefit", "")
        if benefit:
            lines.append(f"→ *Зачем*: {benefit}")

    return "\n".join(lines)


def build_ecc_insights_section() -> str | None:
    """Читает ~/agentnet-pilot/feeds/ecc-insights/latest.json.
    Показывает инсайты из последнего обзора everything-claude-code.
    Показывает ТОЛЬКО в день reviewed_at (первый брифинг после скана).
    Если брифинг за эту дату уже существует — инсайты уже были показаны.
    Если данных нет — placeholder (R-009)."""
    if not ECC_INSIGHTS.exists():
        return "### 🔭 ECC Инсайты\n*(нет данных — скан не запускался)*"
    try:
        data = json.loads(ECC_INSIGHTS.read_text(encoding="utf-8"))
    except Exception:
        return None

    try:
        reviewed = datetime.fromisoformat(data.get("reviewed_at", ""))
    except Exception:
        return None

    review_date_str = briefing_date_str(reviewed.date())
    existing_briefing = BRIEFINGS_DIR / f"Брифинг {review_date_str}.md"

    # Показываем инсайты если скан не старше 7 дней
    days_ago = (datetime.now().date() - reviewed.date()).days
    if days_ago > 7:
        return (f"### 🔭 ECC Инсайты\n"
                f"*(последний скан: {review_date_str}, {days_ago}д назад — устарел)*")

    insights = data.get("insights", [])
    if not insights:
        return None

    # Поддержка старого формата (source) и нового (sources)
    sources = data.get("sources", [])
    if not sources:
        s = data.get("source", "")
        sources = [s] if s else []
    review_date = reviewed.strftime("%Y-%m-%d")
    notes = data.get("review_notes", "")

    lines = [f"### 🔭 Инсайты — обзор {review_date}"]
    if notes:
        lines.append(f"*{notes}*")
    if sources:
        src_links = ", ".join(f"[{s.split('/')[-1]}]({s})" for s in sources)
        lines.append(f"*Источники: {src_links}*")
    lines.append("")

    for num, ins in enumerate(insights, 1):
        title = ins.get("title", "")
        repo = ins.get("repo", "")
        commit_url = ins.get("commit_url", "")
        what  = ins.get("what", "")
        why   = ins.get("why", "")
        prio  = ins.get("priority", "")
        p_tag = f" `{prio}`" if prio else ""
        if num > 1:
            lines.append("")
        if commit_url:
            lines.append(f"**{num}. [{title}]({commit_url})**{p_tag}")
        else:
            lines.append(f"**{num}. {title}**{p_tag}")
        lines.append(f"→ *Что*: {what}")
        action = ins.get("action", "")
        # R-025: всегда Сделать/Зачем
        lines.append(f"→ *Сделать*: {action}" if action else "→ *Сделать*: *(определить при walkthrough)*")
        lines.append(f"→ *Зачем*: {why}" if why else "→ *Зачем*: *(определить при walkthrough)*")

    return "\n".join(lines)


def briefing_date_str(today=None) -> str:
    """Дата в формате ДД.ММ.ГГГГ для имени брифинга."""
    if today is None:
        today = datetime.now().date()
    return today.strftime("%d.%m.%Y")


BRIEFINGS_DIR = VAULT / "Брифинги"


def _load_decided_items(days: int = 14) -> tuple[set[str], set[str]]:
    """Собирает URL и topic из прошлых брифингов, где есть *Решение*:.

    Разбивает текст на блоки (по пустым строкам), берёт только блоки
    содержащие *Решение*:. Из них извлекает:
    - URL из markdown-ссылок [text](url)
    - **bold topic** (Развитие Клода, Новости)
    - текст после ⚡/📡/🔭 маркеров (Тренды)
    """
    decided_urls: set[str] = set()
    decided_topics: set[str] = set()
    today = datetime.now().date()
    for i in range(1, days + 1):
        d = today - timedelta(days=i)
        path = BRIEFINGS_DIR / f"Брифинг {briefing_date_str(d)}.md"
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if "*Решение*:" not in text:
            continue
        # Разбиваем на блоки (пункты разделены пустыми строками)
        blocks = re.split(r"\n\n+", text)
        for block in blocks:
            if "*Решение*:" not in block:
                continue
            # URL из markdown-ссылок (нормализация: убираем utm_* параметры)
            for m in re.finditer(r"\]\((https?://[^)]+)\)", block):
                decided_urls.add(_normalize_url(m.group(1)))
            # **bold topic** (Развитие Клода, Новости)
            for m in re.finditer(r"\*\*([^*]+)\*\*", block):
                val = m.group(1).strip().lower()
                if val and val != "решение":
                    decided_topics.add(val)
            # Тренды: текст после emoji-маркеров ⚡/📡/🔭
            for m in re.finditer(
                r"^(?:⚡|📡|🔭)\s*(?:🔴|🟡|⚪)?\s*(?:hot|warm|cold)?\s*(.+)$",
                block, re.MULTILINE,
            ):
                val = m.group(1).strip().lower()
                if len(val) > 15:
                    decided_topics.add(val)
    return decided_urls, decided_topics


def _normalize_url(url: str) -> str:
    """Убирает utm_* параметры из URL для дедупликации."""
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(url)
    params = {k: v for k, v in parse_qs(parsed.query).items() if not k.startswith("utm_")}
    clean_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=clean_query))


def _signal_is_decided(signal: dict, decided_urls: set[str], decided_topics: set[str]) -> bool:
    """Проверяет, был ли сигнал уже рассмотрен в предыдущем брифинге."""
    url = signal.get("url", "")
    if url and _normalize_url(url) in decided_urls:
        return True
    for field in ("topic", "pattern", "impact", "trend"):
        val = signal.get(field, "").strip().lower()
        if val and val in decided_topics:
            return True
    return False


def build_compliance_section() -> str | None:
    """Секция соблюдения правил (только по вторникам).

    Два источника:
    1. harness-violations.jsonl — реальные нарушения из PostToolUse хука
    2. rules-eval.jsonl — Ollama-оценки по метаданным сессий (дополнительно)
    """
    if datetime.now().weekday() != 1:  # 0=Mon, 1=Tue
        return None

    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

    # --- Источник 1: harness-monitor (реальные данные) ---
    harness_by_type: dict[str, int] = {}
    harness_sessions: set[str] = set()
    harness_total = 0
    if HARNESS_VIOLATIONS.exists():
        for line in HARNESS_VIOLATIONS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if r.get("ts", "")[:10] >= cutoff:
                    for v in r.get("violations", []):
                        harness_by_type[v] = harness_by_type.get(v, 0) + 1
                        harness_total += 1
                    harness_sessions.add(r.get("session_id", ""))
            except Exception:
                pass

    # --- Источник 2: rules-evaluator (Ollama, метаданные) ---
    ollama_violations: list[str] = []
    if RULES_EVAL.exists():
        for line in RULES_EVAL.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if r.get("session_date", "") >= cutoff and r.get("violated") and r.get("confidence") == "high":
                    ollama_violations.append(f"{r['rule_id']} {r.get('rule_title', '')}")
            except Exception:
                pass

    if not harness_total and not ollama_violations:
        return None

    lines = [f"### 📏 Соблюдение правил — 14д ({len(harness_sessions)} сессий)"]
    lines.append("")

    # Harness (реальные нарушения)
    if harness_by_type:
        v_labels = {
            "V1:question": "Вопрос-разрешение вместо действия",
            "V3:variants": "Предложение вариантов вместо решения",
            "V4:trailing_question": "Концовка-вопрос",
            "V5:agent_simple_search": "Agent для простого поиска",
        }
        for vtype, count in sorted(harness_by_type.items(), key=lambda x: -x[1]):
            if vtype == "V2:english":
                continue  # отключён — 98% ложноположительных
            label = v_labels.get(vtype, vtype)
            lines.append(f"⚠️ **{vtype}** {label} — {count}×")
        lines.append(f"\nИтого: **{harness_total}** нарушений за 14д")

    # Ollama (дополнительно)
    if ollama_violations:
        lines.append("")
        for v in ollama_violations:
            lines.append(f"📊 Ollama: {v}")

    return "\n".join(lines)


def briefing_note_path(today=None) -> Path:
    if today is None:
        today = datetime.now().date()
    BRIEFINGS_DIR.mkdir(exist_ok=True)
    return BRIEFINGS_DIR / f"Брифинг {briefing_date_str(today)}.md"


def write_briefing_note(today, ag_signals: list, cl_ideas: list, mkt_signals: list):
    """Создаёт/обновляет заметку-брифинг с аналитическими секциями."""
    path = briefing_note_path(today)

    tasks_section = build_tasks_section()
    alerts_section = build_alerts_section()
    parts = [f"# Брифинг {briefing_date_str(today)}\n"]
    if alerts_section:
        parts += [alerts_section, "", "---", ""]
    if tasks_section:
        parts += [tasks_section, "", "---", ""]

    compliance_section = build_compliance_section()
    if compliance_section:
        parts += [compliance_section, "", "---", ""]

    ecc_section = build_ecc_insights_section()
    if ecc_section:
        parts += [ecc_section, "", "---", ""]

    # Анализ времени + Harness Health — только по вторникам (R-011, weekday() == 1)
    if datetime.now().weekday() == 1:
        time_section = build_time_analysis_section()
        if time_section:
            parts += [time_section, "", "---", ""]
        harness_section = build_harness_health_section()
        if harness_section:
            parts += [harness_section, "", "---", ""]

    # Один вызов дедупликации для всех секций (не 3 прохода по файлам)
    decided = _load_decided_items()

    # Разведка: market signals с urgency из triage-cache
    parts += [
        build_recon_section(mkt_signals, decided),
        "",
        "---",
        "",
        build_claude_section(cl_ideas, decided),
        "",
        "---",
        "",
        build_ideas_section(mkt_signals, decided),
        "",
    ]

    if path.exists():
        # Файл уже существует — НЕ перезаписываем (INC-007: решения walkthrough затирались).
        # Обновляем только секцию задач через patch_stale_tasks().
        print(f"⏭️ Брифинг уже существует: {path.name} — пропуск перезаписи")
        return
    path.write_text("\n".join(parts), encoding="utf-8")
    print(f"✅ Брифинг создан: {path.name}")


def inject(note_path: Path):
    today  = datetime.now().date()
    # Признак "уже инжектировано" — наличие ссылки на брифинг в заметке
    briefing_name = f"Брифинг {briefing_date_str(today)}"
    briefing_link = f"[[{briefing_name}]]"

    # Читаем данные для брифинга
    # ag_signals закрыт 23.03.2026 — AgentNet отключён (KE-BRIEF-001)
    ag_signals  = []
    cl_ideas    = load_recent(CLAUDE_FILE,  days=7, limit=500)
    mkt_signals = load_recent(MARKET_FILE,  days=3, limit=1000)

    # Брифинг создаём/обновляем каждый раз (данные могут обновиться)
    write_briefing_note(today, ag_signals, cl_ideas, mkt_signals)

    text = note_path.read_text(encoding="utf-8")

    # Убираем старый видимый маркер если остался
    old_marker = f"<!-- ai-inject: {today.isoformat()} -->"
    if old_marker in text:
        text = text.replace(old_marker + "\n", "").replace(old_marker, "")
        note_path.write_text(text, encoding="utf-8")

    if briefing_link in text:
        print(f"Уже инжектировано: {note_path.name}")
        return

    # Алерты теперь в брифинге, не в дневной заметке (23.03.2026)
    block = ""

    # Вставляем перед первым --- (разделитель после погоды)
    sep_idx = text.find("\n---")
    if sep_idx != -1:
        new_text = text[:sep_idx] + "\n\n" + block + text[sep_idx:]
    else:
        new_text = text.rstrip() + "\n\n" + block

    # Ссылка на брифинг — в самый низ (без HTML-комментария)
    briefing_name = f"Брифинг {briefing_date_str(today)}"
    new_text = new_text.rstrip() + f"\n\n\n\n[[{briefing_name}]]\n"

    note_path.write_text(new_text, encoding="utf-8")
    print(f"✅ AI-блок добавлен в {note_path.name}")
    print(f"   AgentNet: {len(ag_signals)} сигналов | "
          f"Клод: {len(cl_ideas)} инсайтов | "
          f"Идеи: {len([s for s in mkt_signals if s.get('relevant_to_oleg')])} новых")

    # Git: НЕ делаем здесь. obsidian-sync.sh подхватит через rsync vault→backup.


def build_proposals_section() -> str | None:
    """Читает сегодняшние предложения из pending-claude-hypotheses.md.
    Возвращает markdown-секцию с чекбоксами или None если предложений нет."""
    if not PENDING_HYPO.exists():
        return None

    text  = PENDING_HYPO.read_text(encoding="utf-8")
    today = datetime.now().strftime("%Y-%m-%d")

    # Ищем секцию с сегодняшней датой: "## Предложения из RSS — 2026-03-01 ..."
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    today_parts = [p for p in parts if today in p[:60]]
    if not today_parts:
        return None

    proposals = []
    for part in today_parts:
        for item in re.split(r"^### ", part, flags=re.MULTILINE)[1:]:
            lines  = item.strip().splitlines()
            title  = lines[0].strip() if lines else ""
            closes = plan = priority = ""
            for line in lines[1:]:
                if "Приоритет" in line:
                    m = re.search(r"(P\d)", line)
                    priority = m.group(1) if m else ""
                if "Закрывает" in line:
                    closes = re.sub(r"\*\*Закрывает\*\*:\s*", "", line).strip()
                if "Предложение" in line:
                    plan = re.sub(r"\*\*Предложение\*\*:\s*", "", line).strip()
            if title:
                proposals.append((title, priority, closes, plan))

    if not proposals:
        return None

    lines = [f"### 📋 Предложения — {len(proposals)} на сегодня\n"]
    for title, priority, closes, plan in proposals:
        p_tag = f" `{priority}`" if priority else ""
        lines.append(f"- [ ] **{title}**{p_tag}")
        if closes:
            lines.append(f"  *закрывает: {closes}*")
        if plan:
            lines.append(f"  → {plan[:130]}")
        lines.append("")

    return "\n".join(lines)


def inject_proposals(note_path: Path):
    """Добавляет секцию предложений в заметку (отдельный маркер, отдельный цикл)."""
    today   = datetime.now().date()
    marker  = f"<!-- proposals: {today.isoformat()} -->"
    text    = note_path.read_text(encoding="utf-8")

    if marker in text:
        return  # уже вставлено сегодня

    section = build_proposals_section()
    if section is None:
        return  # предложений ещё нет

    block = marker + "\n" + section

    # Вставляем перед финальным разделителем шаблона (---\n----)
    sep_idx = text.rfind("\n---\n----")
    if sep_idx != -1:
        new_text = text[:sep_idx] + "\n\n---\n\n" + block + text[sep_idx:]
    else:
        new_text = text.rstrip() + "\n\n---\n\n" + block + "\n"

    note_path.write_text(new_text, encoding="utf-8")
    print(f"✅ Предложения добавлены в {note_path.name} ({len(proposals_count(section))} шт.)")

    # Git: НЕ делаем здесь. obsidian-sync.sh подхватит через rsync vault→backup.


def proposals_count(section: str) -> list:
    return re.findall(r"^- \[ \]", section, flags=re.MULTILINE)


HARNESS_TOOLS = Path.home() / "AI" / "tools"
HOOKS_LOG = Path.home() / "logs" / "hooks.log"
HARNESS_SUMMARY = Path.home() / ".claude" / "harness-summary.json"


def build_harness_health_section() -> str | None:
    """Запускает evaluators и собирает метрики harness'а. R-011: только по вторникам."""
    if datetime.now().weekday() != 1:  # 0=пн, 1=вт
        return None
    lines = ["### 🛡️ Harness Health", ""]
    lines.append("| Pipeline | Score | Проблема |")
    lines.append("|----------|-------|----------|")

    # Cascade evaluator
    cascade_eval = HARNESS_TOOLS / "pattern-evaluate.py"
    if cascade_eval.exists():
        try:
            r = subprocess.run(
                [sys.executable, str(cascade_eval)],
                capture_output=True, text=True, timeout=60
            )
            score = "?"
            issues = []
            for line in r.stdout.splitlines():
                if "overall_health_score=" in line:
                    score = line.split("=")[1]
                elif line.strip().startswith("WARN:") or line.strip().startswith("CRITICAL:"):
                    issues.append(line.strip()[:60])
            issue_str = "; ".join(issues[:2]) if issues else "—"
            lines.append(f"| Cascade | {score}/100 | {issue_str} |")
        except Exception:
            lines.append("| Cascade | err | timeout |")

    # RSS evaluator
    rss_eval = HARNESS_TOOLS / "rss-evaluate.py"
    if rss_eval.exists():
        try:
            r = subprocess.run(
                [sys.executable, str(rss_eval)],
                capture_output=True, text=True, timeout=60
            )
            score = "?"
            issues = []
            for line in r.stdout.splitlines():
                if "overall_health_score=" in line:
                    score = line.split("=")[1]
                elif line.strip().startswith("Only ") or line.strip().startswith("Low ") or line.strip().startswith("Noise ") or line.strip().startswith("Stale") or line.strip().startswith("Triage"):
                    issues.append(line.strip()[:60])
            issue_str = "; ".join(issues[:2]) if issues else "—"
            lines.append(f"| RSS | {score}/100 | {issue_str} |")
        except Exception:
            lines.append("| RSS | err | timeout |")

    # Gate blocks (last 7 days from hooks.log)
    blocks_7d = 0
    if HOOKS_LOG.exists():
        cutoff = datetime.now() - timedelta(days=7)
        try:
            for log_line in HOOKS_LOG.read_text(encoding="utf-8").splitlines():
                if "BLOCKED" in log_line and log_line[:19].strip():
                    try:
                        log_dt = datetime.strptime(log_line[:19], "%Y-%m-%d %H:%M:%S")
                        if log_dt >= cutoff:
                            blocks_7d += 1
                    except ValueError:
                        pass
        except Exception:
            pass
    lines.append(f"| Gate | {blocks_7d} блокировок/7д | — |")

    # Language violations (from harness-summary.json)
    lang_violations = "?"
    if HARNESS_SUMMARY.exists():
        try:
            hs = json.loads(HARNESS_SUMMARY.read_text(encoding="utf-8"))
            lang_violations = hs.get("total_violations", "?")
        except Exception:
            pass
    lines.append(f"| Язык | {lang_violations} нарушений | — |")

    return "\n".join(lines)


TIME_REPORT = Path.home() / "AI/tools/time-analyst/latest-report.json"
TARGETS = {
    "ПРОЕКТ":        {"min": 50, "op": ">="},
    "ИНФРАСТРУКТУРА":{"max": 15, "op": "<="},
    "DEBUGGING":     {"max": 10, "op": "<="},
    "КЛОД_РАЗВИТИЕ": {"max": 20, "op": "<="},
    "УПРАВЛЕНИЕ":    {"max": 10, "op": "<="},
}


def build_time_analysis_section() -> str | None:
    """Читает latest-report.json и формирует markdown-блок анализа времени.
    R-011: показывается ТОЛЬКО по вторникам."""
    if datetime.now().weekday() != 1:  # 0=пн, 1=вт
        return None
    if not TIME_REPORT.exists():
        return None
    try:
        data = json.loads(TIME_REPORT.read_text(encoding="utf-8"))
    except Exception:
        return None
    # Проверяем свежесть (< 36 часов)
    try:
        gen = datetime.fromisoformat(data.get("generated", ""))
        if (datetime.now() - gen).total_seconds() > 36 * 3600:
            return None
    except Exception:
        pass

    results = data.get("sessions", [])
    days = data.get("days", 7)
    total_min = sum(r.get("dur_min", 0) for r in results)
    total_cost = sum(r.get("cost", 0.0) for r in results)

    if not total_min:
        return None

    # Группируем по категориям
    by_cat: dict[str, int] = {}
    for r in results:
        cat = r.get("cls", {}).get("category", "НЕИЗВЕСТНО")
        by_cat[cat] = by_cat.get(cat, 0) + r.get("dur_min", 0)

    lines = [f"### 📊 Анализ времени ({days} дней)", ""]
    lines.append("| Категория | % | Цель | |")
    lines.append("|---|---|---|---|")
    for cat, mins in sorted(by_cat.items(), key=lambda x: -x[1]):
        pct = mins / total_min * 100 if total_min else 0
        t = TARGETS.get(cat, {})
        if "min" in t:
            ok = pct >= t["min"]
            target_str = f"≥{t['min']}%"
        elif "max" in t:
            ok = pct <= t["max"]
            target_str = f"≤{t['max']}%"
        else:
            ok = True
            target_str = "—"
        status = "✅" if ok else "🔴"
        lines.append(f"| {cat} | {pct:.0f}% | {target_str} | {status} |")

    waste_min = sum(
        r.get("dur_min", 0)
        for r in results
        if r.get("cls", {}).get("waste_flag")
    )
    waste_str = f" | ⚠️ потеряно {waste_min} мин" if waste_min else ""
    lines.append(f"\n**Итого**: {total_min // 60}ч {total_min % 60}м | ${total_cost:.2f}{waste_str}")
    return "\n".join(lines)


def run_proposal_agent():
    """Запускает idea-to-proposal.py если появились новые claude-ideas."""
    script = AGENTNET / "tools" / "idea-to-proposal.py"
    if not script.exists():
        return
    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=60
        )
        if r.stdout.strip():
            print(f"[proposals] {r.stdout.strip()[:200]}")
    except Exception as e:
        print(f"[proposals] {e}")


def patch_empty_news(note_path: Path):
    """Если Новости пусты в брифинге — заменить секцию.
    Mac создаёт брифинг раньше Linux и получает пустые Новости
    (signals живут на Linux). Linux каждые 10 мин патчит брифинг."""
    today = datetime.now().date()
    briefing_path = briefing_note_path(today)
    if not briefing_path.exists():
        return

    EMPTY_MARKER = "*(нет новостей за 3 дня)*"
    text = briefing_path.read_text(encoding="utf-8")
    if EMPTY_MARKER not in text:
        return  # Новости уже заполнены

    mkt_signals = load_recent(MARKET_FILE, days=3, limit=1000)
    relevant = [s for s in mkt_signals if s.get("relevant_to_oleg")]
    if not relevant:
        return  # Данных нет и у нас — ничего не делаем

    new_section = build_ideas_section(mkt_signals)
    old_section = f"### 📬 Новости\n{EMPTY_MARKER}"
    new_text = text.replace(old_section, new_section)
    briefing_path.write_text(new_text, encoding="utf-8")
    print(f"✅ [patch] Новости обновлены в брифинге: {len(relevant)} сигналов")


def patch_stale_tasks(note_path: Path):
    """Если задачи в брифинге устарели — перегенерировать блок.
    Задачи теперь живут в брифинге, не в ежедневной заметке."""
    today = datetime.now().date()
    briefing_path = briefing_note_path(today)
    if not briefing_path.exists():
        return
    text = briefing_path.read_text(encoding="utf-8")
    # Ищем существующий блок задач (все варианты названий)
    m = re.search(r"(### (?:📋 (?:Повестка дня|Задачи)|📅 Задачи)[^\n]*\n(?:.*\n)*?)(?=\n---|\Z)", text)
    if not m:
        # Блока задач нет — вставим перед первой секцией (после заголовка)
        fresh_block = build_tasks_section()
        if fresh_block:
            header_end = text.index("\n", text.index("# Брифинг")) + 1
            new_text = text[:header_end] + "\n" + fresh_block + "\n\n---\n" + text[header_end:]
            briefing_path.write_text(new_text, encoding="utf-8")
            print(f"✅ [patch] Задачи добавлены в брифинг")
        return

    current_block = m.group(1).rstrip()

    # Если в блоке есть решения walkthrough (→ *Решение*:) — НЕ трогать.
    # Решения записываются пользователем и агентом при разборе брифинга.
    # patch_stale_tasks не имеет права их затирать.
    if "→ *Решение*:" in current_block or "→ *решение*:" in current_block.lower():
        return

    fresh_block = build_tasks_section()
    if fresh_block is None:
        fresh_block = ""

    if fresh_block.rstrip() == current_block:
        return  # Актуально, не трогаем

    new_text = text[:m.start()] + fresh_block + "\n" + text[m.end():]
    briefing_path.write_text(new_text, encoding="utf-8")
    print(f"✅ [patch] Задачи обновлены в брифинге")


def patch_stale_alerts(note_path: Path):
    """Заменяет блок алертов на актуальный из SSoT (active-alerts.yaml).
    Mac может инжектировать своей старой версией кода напрямую из meta-analysis.py —
    показывая resolved алерты. Linux каждые 10 мин перезаписывает блок по SSoT.
    Если open-алертов нет — блок удаляется полностью."""
    text = note_path.read_text(encoding="utf-8")
    # Найти блок alerts между маркерами
    m = re.search(r"<!-- alerts-start -->.*?<!-- alerts-end -->", text, re.DOTALL)
    if not m:
        return  # Блока нет — inject сам разберётся

    fresh_section = build_alerts_section()  # None если нет open-алертов

    if fresh_section is None:
        # Нет открытых алертов — удалить блок целиком (вместе с маркерами и пустой строкой)
        new_text = re.sub(r"\n?<!-- alerts-start -->.*?<!-- alerts-end -->\n?", "\n", text, flags=re.DOTALL)
        note_path.write_text(new_text, encoding="utf-8")
        print("✅ [patch] Алерты убраны (нет открытых)")
        return

    new_block = f"<!-- alerts-start -->\n{fresh_section}\n<!-- alerts-end -->"
    current_block = m.group(0)
    if new_block == current_block:
        return  # Актуально

    new_text = text[:m.start()] + new_block + text[m.end():]
    note_path.write_text(new_text, encoding="utf-8")
    print("✅ [patch] Алерты обновлены из SSoT")


def patch_briefing_link(note_path: Path):
    """Добавляет ссылку на брифинг в самый низ ежедневной заметки,
    если её там ещё нет. Также заменяет старый формат (с HTML-комментарием
    или YYYY-MM-DD датой) на новый [[Брифинг ДД.ММ.ГГГГ]]."""
    today = datetime.now().date()
    briefing_name = f"Брифинг {briefing_date_str(today)}"
    text = note_path.read_text(encoding="utf-8")

    # Заменяем старый HTML-маркер + ссылку на просто ссылку
    old_marker = f"<!-- briefing-link: {today.isoformat()} -->"
    if old_marker in text:
        new_text = text.replace(
            f"{old_marker}\n[[Брифинг {today.isoformat()}]]",
            f"[[{briefing_name}]]"
        )
        if new_text != text:
            note_path.write_text(new_text, encoding="utf-8")
            print(f"✅ [patch] Маркер брифинга заменён на [[{briefing_name}]]")
        return

    # Ссылка уже в новом формате — всё ок
    if f"[[{briefing_name}]]" in text:
        return

    # Ссылки нет вообще — добавляем
    new_text = text.rstrip() + f"\n\n[[{briefing_name}]]\n"
    note_path.write_text(new_text, encoding="utf-8")
    print(f"✅ [patch] Ссылка на брифинг добавлена: [[{briefing_name}]]")


def sync_tasks_index():
    """Запускает sync-tasks.sh чтобы индекс задач был свежим перед инжектом.
    KE-008: без этого daily-inject читает устаревший индекс — done-задачи попадают в Активные."""
    sync_sh = Path.home() / "sync-tasks.sh"
    if not sync_sh.exists():
        print("[sync-tasks] warn: ~/sync-tasks.sh не найден")
        return
    try:
        r = subprocess.run(
            ["bash", str(sync_sh)],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            print(f"[sync-tasks] ok: {r.stdout.strip()}")
        else:
            print(f"[sync-tasks] warn: {r.stderr.strip()}")
    except Exception as e:
        print(f"[sync-tasks] skip: {e}")


def validate_premises() -> list[str]:
    """Принцип 18: проверить предположения ДО работы.
    Возвращает список проблем (пустой = всё ок)."""
    issues = []
    # 1. Vault существует и содержит Дни/
    if not DAYS_DIR.exists():
        issues.append(f"DAYS_DIR не существует: {DAYS_DIR}")
    # 2. agentnet-pilot доступен
    if not AGENTNET.exists():
        issues.append(f"AGENTNET не существует: {AGENTNET}")
    # 3. Критические файлы данных
    for label, p in [("ALERTS_FILE", ALERTS_FILE),
                     ("TASKS_INDEX", TASKS_INDEX)]:
        if not p.exists():
            issues.append(f"{label} не существует: {p}")
    # 4. YAML доступен (нужен для алертов)
    if not _YAML_OK:
        issues.append("PyYAML не установлен — секция алертов будет пустой")
    # 5. F-037 lint: ссылки на локальную память в активных файлах vault
    f037_dirs = [
        VAULT / "AI" / "Claude Code" / "Skills",
        VAULT / "AI" / "Claude Code" / "AGENT-MEMORY",
    ]
    f037_pattern = ".claude/projects"
    f037_exclude = {"chats", "chat-digest.md", "Memory-FROZEN"}
    for d in f037_dirs:
        if not d.exists():
            continue
        for md in d.rglob("*.md"):
            if any(ex in str(md) for ex in f037_exclude):
                continue
            try:
                for line in md.read_text(errors="replace").splitlines():
                    if f037_pattern in line and not any(w in line.upper() for w in ("НЕ ИСПОЛЬЗ", "ЗАПРЕЩЕНО", "НЕ ЧИТАТЬ")):
                        issues.append(f"F-037: локальная память в {md.name}")
                        break
            except Exception:
                pass
    return issues


def main():
    # Принцип 18: premise validation
    issues = validate_premises()
    for issue in issues:
        print(f"[premise] ⚠️ {issue}")

    # Синхронизируем agentnet-pilot перед чтением фидов
    # Без этого Mac/Laptop читают устаревшие сигналы и блок Новости пустой
    try:
        r = subprocess.run(
            ["git", "-C", str(AGENTNET), "pull", "--ff-only", "-q"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode != 0:
            print(f"[agentnet pull] warn: {r.stderr.strip()}")
    except Exception as e:
        print(f"[agentnet pull] skip: {e}")

    # Обновляем индекс задач (KE-008: без этого done-задачи попадают в блок Активных)
    sync_tasks_index()

    # Выходные — без брифинга (сб=5, вс=6)
    if datetime.now().weekday() in (5, 6):
        print("⏭️ Выходной — брифинг не формируется")
        sys.exit(0)

    # Брифинг создаётся независимо от дневной заметки
    ag_signals  = []
    cl_ideas    = load_recent(CLAUDE_FILE,  days=7, limit=500)
    mkt_signals = load_recent(MARKET_FILE,  days=3, limit=1000)
    write_briefing_note(datetime.now().date(), ag_signals, cl_ideas, mkt_signals)

    note = today_note_path()
    if note.exists():
        inject(note)
        patch_empty_news(note)
        patch_stale_tasks(note)
        patch_briefing_link(note)
        run_proposal_agent()
        inject_proposals(note)
    else:
        print(f"Заметка не создана ещё: {note.name} — брифинг создан, инжекция ждёт")


if __name__ == "__main__":
    main()
