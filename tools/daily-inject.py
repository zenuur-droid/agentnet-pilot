#!/usr/bin/env python3
"""
daily-inject.py — инжектирует AI-блок в ежедневную заметку Obsidian.

Запускается каждые 10 минут (LaunchAgent com.daily.inject).
Структура блока:
  ### 🔴 Алерты    — только status: open из active-alerts.yaml (SSoT)
  ### 🏗 AgentNet  — тренды/влияние/идеи для Проекта
  ### 💡 Клод      — паттерны для агента
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
# Проверяем по наличию папки Дни — признак рабочего worktree
_VAULT_CANDIDATES = [
    Path.home() / "obsidian-backup",   # Mac
    Path.home() / "obsidian-vault",    # Linux
    Path.home() / "obsidian",          # Laptop (Windows)
]
VAULT = next(
    (p for p in _VAULT_CANDIDATES if (p / "Дни").exists()),
    _VAULT_CANDIDATES[0]
)

DAYS_DIR       = VAULT / "Дни"
AGENTNET       = Path.home() / "agentnet-pilot"
AG_PROJ_FILE   = AGENTNET / "feeds" / "agentnet-project" / "signals.jsonl"
CLAUDE_FILE    = AGENTNET / "feeds" / "claude-ideas" / "ideas.jsonl"
MARKET_FILE    = AGENTNET / "feeds" / "market-intel" / "signals.jsonl"
PENDING_HYPO   = VAULT / "AI" / "Claude Code" / "pending-claude-hypotheses.md"
ALERTS_FILE    = AGENTNET / "alerts" / "active-alerts.yaml"
TASKS_INDEX    = VAULT / "1_Задачи" / "Claude Code задачи.md"
ECC_INSIGHTS   = AGENTNET / "feeds" / "ecc-insights" / "latest.json"

DOW_RU = {0: "пн", 1: "вт", 2: "ср", 3: "чт", 4: "пт", 5: "сб", 6: "вс"}


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


def build_tasks_section() -> str | None:
    """Читает ВСЕ активные задачи из индекса (все исполнители).
    Группирует: просроченные → сегодня → ближайшие 3 дня.
    Пропускает секцию Выполненные.
    Показывает исполнителя если не 'all'."""
    if not TASKS_INDEX.exists():
        return None

    today = datetime.now().date()
    upcoming_days = 3

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
        title      = parts[3].strip().lstrip("[[").rstrip("]]").rstrip()

        try:
            import datetime as dt
            deadline = dt.date.fromisoformat(raw_date)
        except ValueError:
            continue

        who = f"`{assignee}` " if assignee != "all" else ""
        rec_tag = f" `{recurrence}`" if recurrence not in ("once", "none", "") else ""
        item = (title, who, rec_tag, raw_date)

        delta = (today - deadline).days
        if delta > 0:
            overdue.append((delta, item))
        elif delta == 0:
            today_tasks.append(item)
        elif delta >= -upcoming_days:
            upcoming.append((-delta, item))

    if not overdue and not today_tasks and not upcoming:
        return None

    total = len(overdue) + len(today_tasks) + len(upcoming)
    lines = [f"### 📅 Задачи — {total} к выполнению"]

    for days, (title, who, rec_tag, _) in sorted(overdue, reverse=True):
        lines.append(f"- [ ] {who}**{title}**{rec_tag} ⚠️ просрочено {days}д")

    for title, who, rec_tag, _ in today_tasks:
        lines.append(f"- [ ] {who}**{title}**{rec_tag} *(сегодня)*")

    for days, (title, who, rec_tag, date) in sorted(upcoming):
        lines.append(f"- [ ] {who}**{title}**{rec_tag} *(через {days}д — {date})*")

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


def build_agentnet_section(signals: list) -> str:
    if not signals:
        return ("### 🏗 AgentNet\n"
                "*(нет сигналов — появятся после следующего прогона в 06:00)*")

    urgent  = [s for s in signals if s.get("urgency") == "now"]
    weekly  = [s for s in signals if s.get("urgency") == "week"]
    monthly = [s for s in signals if s.get("urgency") == "month"]

    lines = [f"### 🏗 AgentNet — {len(signals)} сигналов"]

    for s in urgent[:3]:
        lines.append("")
        lines.append(f"⚡ {s.get('impact', '')}")
        idea = s.get("idea", "")
        if idea:
            lines.append(f"→ {idea}  *({s.get('source', '')})*")
        else:
            lines.append(f"*({s.get('source', '')})*")

    for s in weekly[:3]:
        lines.append("")
        lines.append(f"📡 {s.get('trend', '')}")
        idea = s.get("idea", "")
        if idea:
            lines.append(f"→ {idea}  *({s.get('source', '')})*")
        else:
            lines.append(f"*({s.get('source', '')})*")

    for s in monthly[:2]:
        lines.append("")
        lines.append(f"🔭 {s.get('trend', '')}  *({s.get('source', '')})*")

    return "\n".join(lines)


def build_claude_section(ideas: list) -> str:
    if not ideas:
        return "### 💡 Клод\n*(нет инсайтов за неделю)*"

    MAX = 7
    # Приоритет категорий: дефицитные важные — выше; cost последний (избыток)
    cat_priority = {
        "memory": 0, "meta": 1, "autonomy": 2,
        "coordination": 3, "reasoning": 4, "tools": 5, "cost": 6,
    }

    # Дедупликация: один инсайт на паттерн (оставляем самый свежий)
    seen_patterns: set[str] = set()
    deduped: list = []
    for idea in reversed(ideas):  # reversed → свежие первыми при dedup
        key = idea.get("pattern", "").lower().strip()[:40]
        if key and key not in seen_patterns:
            seen_patterns.add(key)
            deduped.append(idea)
    deduped.reverse()  # вернуть хронологический порядок

    sorted_ideas = sorted(deduped, key=lambda i: cat_priority.get(i.get("category", ""), 9))

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
    lines = [f"### 💡 Клод — топ-{shown_count} из {len(deduped)} уникальных ({len(ideas)} всего)"]
    for idea in selected:
        pattern = idea.get("pattern", "")
        insight = idea.get("insight", "")
        cat     = idea.get("category", "")
        lines.append("")
        lines.append(f"**{pattern}** *({cat})*")
        lines.append(insight)

    return "\n".join(lines)


def build_ideas_section(signals: list) -> str:
    dir_icon = {"рост": "↑", "новое": "★", "спад": "↓", "зрелость": "→"}
    relevant = [s for s in signals if s.get("relevant_to_oleg")]
    if not relevant:
        return "### 📬 Новости\n*(нет новостей за 3 дня)*"

    # Сортируем по важности direction: новое > рост > зрелость > спад
    dir_priority = {"новое": 0, "рост": 1, "зрелость": 2, "спад": 3}
    sorted_rel = sorted(relevant, key=lambda s: dir_priority.get(s.get("direction", ""), 9))
    lines = [f"### 📬 Новости — {len(relevant)} релевантных"]
    shown = 0
    for s in sorted_rel:
        if shown >= 7:
            break
        icon   = dir_icon.get(s.get("direction", ""), "·")
        topic  = s.get("topic", "")
        signal = s.get("signal", "")
        action = s.get("action", "")
        src    = s.get("source", "")
        lines.append("")
        lines.append(f"{icon} **{topic}**  *({src})*")
        lines.append(signal)
        if action:
            lines.append(f"→ {action}")
        shown += 1

    return "\n".join(lines)


def build_ecc_insights_section() -> str | None:
    """Читает ~/agentnet-pilot/feeds/ecc-insights/latest.json.
    Показывает инсайты из последнего обзора everything-claude-code.
    Секция видна 35 дней после обзора — потом исчезает до следующего."""
    if not ECC_INSIGHTS.exists():
        return None
    try:
        data = json.loads(ECC_INSIGHTS.read_text(encoding="utf-8"))
    except Exception:
        return None

    try:
        reviewed = datetime.fromisoformat(data.get("reviewed_at", ""))
        if (datetime.now() - reviewed).days > 35:
            return None  # Старый обзор — ждём следующего
    except Exception:
        return None

    insights = data.get("insights", [])
    if not insights:
        return None

    source = data.get("source", "")
    review_date = reviewed.strftime("%Y-%m-%d")
    notes = data.get("review_notes", "")

    lines = [f"### 🔭 ECC Инсайты — обзор {review_date}"]
    if notes:
        lines.append(f"*{notes}*")
    lines.append(f"*Источник: {source}*")
    lines.append("")

    for ins in insights:
        title = ins.get("title", "")
        what  = ins.get("what", "")
        why   = ins.get("why", "")
        prio  = ins.get("priority", "")
        p_tag = f" `{prio}`" if prio else ""
        lines.append(f"**{title}**{p_tag}")
        lines.append(f"→ *Что*: {what}")
        lines.append(f"→ *Зачем*: {why}")
        lines.append("")

    return "\n".join(lines)


def briefing_date_str(today=None) -> str:
    """Дата в формате ДД.ММ.ГГГГ для имени брифинга."""
    if today is None:
        today = datetime.now().date()
    return today.strftime("%d.%m.%Y")


BRIEFINGS_DIR = VAULT / "Брифинги"

def briefing_note_path(today=None) -> Path:
    if today is None:
        today = datetime.now().date()
    BRIEFINGS_DIR.mkdir(exist_ok=True)
    return BRIEFINGS_DIR / f"Брифинг {briefing_date_str(today)}.md"


def write_briefing_note(today, ag_signals: list, cl_ideas: list, mkt_signals: list):
    """Создаёт/обновляет заметку-брифинг с аналитическими секциями."""
    path = briefing_note_path(today)

    tasks_section = build_tasks_section()
    parts = [f"# Брифинг {briefing_date_str(today)}\n"]
    if tasks_section:
        parts += [tasks_section, "", "---", ""]

    ecc_section = build_ecc_insights_section()
    if ecc_section:
        parts += [ecc_section, "", "---", ""]

    time_section = build_time_analysis_section()
    if time_section:
        parts += [time_section, "", "---", ""]

    parts += [
        build_agentnet_section(ag_signals),
        "",
        "---",
        "",
        build_claude_section(cl_ideas),
        "",
        "---",
        "",
        build_ideas_section(mkt_signals),
        "",
    ]

    path.write_text("\n".join(parts), encoding="utf-8")
    print(f"✅ Брифинг создан: {path.name}")


def inject(note_path: Path):
    today  = datetime.now().date()
    # Признак "уже инжектировано" — наличие ссылки на брифинг в заметке
    briefing_name = f"Брифинг {briefing_date_str(today)}"
    briefing_link = f"[[{briefing_name}]]"

    # Читаем данные из agentnet (нужны всегда — для брифинга)
    ag_signals  = load_recent(AG_PROJ_FILE, days=7)
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

    # В ежедневную заметку — только алерты (задачи теперь в брифинге)
    alerts_section = build_alerts_section()

    parts = []
    if alerts_section:
        parts += [
            "<!-- alerts-start -->",
            alerts_section,
            "<!-- alerts-end -->",
            "",
            "---",
            "",
        ]

    block = "\n".join(parts)

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

    # Git push (SSH ключ как в obsidian-sync.sh)
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = (
        "ssh -i /Users/user/.ssh/github_ed25519 -o StrictHostKeyChecking=no"
    )
    try:
        briefing_rel = str(briefing_note_path(today).relative_to(VAULT))
        daily_rel    = str(note_path.relative_to(VAULT))
        subprocess.run(
            ["git", "-C", str(VAULT), "add", daily_rel, briefing_rel],
            capture_output=True, timeout=15, env=env
        )
        r = subprocess.run(
            ["git", "-C", str(VAULT), "commit", "-m",
             f"daily inject: AI-блок {today}"],
            capture_output=True, timeout=15, env=env
        )
        if b"nothing to commit" not in r.stdout:
            subprocess.run(
                ["git", "-C", str(VAULT), "push"],
                capture_output=True, timeout=30, env=env
            )
    except Exception as e:
        print(f"  [git] {e}")


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

    # Git push
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = (
        "ssh -i /Users/user/.ssh/github_ed25519 -o StrictHostKeyChecking=no"
    )
    try:
        rel = str(note_path.relative_to(VAULT))
        subprocess.run(["git", "-C", str(VAULT), "add", rel],
                       capture_output=True, timeout=15, env=env)
        r = subprocess.run(["git", "-C", str(VAULT), "commit", "-m",
                            f"daily inject: предложения {today}"],
                           capture_output=True, timeout=15, env=env)
        if b"nothing to commit" not in r.stdout:
            subprocess.run(["git", "-C", str(VAULT), "push"],
                           capture_output=True, timeout=30, env=env)
    except Exception as e:
        print(f"  [git proposals] {e}")


def proposals_count(section: str) -> list:
    return re.findall(r"^- \[ \]", section, flags=re.MULTILINE)


TIME_REPORT = Path.home() / "AI/tools/time-analyst/latest-report.json"
TARGETS = {
    "ПРОЕКТ":        {"min": 50, "op": ">="},
    "ИНФРАСТРУКТУРА":{"max": 15, "op": "<="},
    "DEBUGGING":     {"max": 10, "op": "<="},
    "КЛОД_РАЗВИТИЕ": {"max": 20, "op": "<="},
    "УПРАВЛЕНИЕ":    {"max": 10, "op": "<="},
}


def build_time_analysis_section() -> str | None:
    """Читает latest-report.json и формирует markdown-блок анализа времени."""
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
    # Ищем существующий блок задач
    m = re.search(r"(### 📅 Задачи[^\n]*\n(?:.*\n)*?)(?=\n---|\Z)", text)
    if not m:
        return  # Блока задач нет — inject сам разберётся

    current_block = m.group(1).rstrip()
    fresh_block = build_tasks_section()
    if fresh_block is None:
        fresh_block = ""

    if fresh_block.rstrip() == current_block:
        return  # Актуально, не трогаем

    new_text = text[:m.start()] + fresh_block + text[m.end():]
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


def main():
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

    note = today_note_path()
    if not note.exists():
        print(f"Заметка не создана ещё: {note.name} — жду")
        sys.exit(0)
    inject(note)
    patch_stale_alerts(note)   # Патч алертов из SSoT (Mac мог показать resolved алерты)
    patch_empty_news(note)     # Патч пустых Новостей в брифинге (Mac мог заинжектировать раньше)
    patch_stale_tasks(note)    # Патч устаревших Задач (Mac мог заинжектировать раньше)
    patch_briefing_link(note)  # Ссылка на брифинг в конце ежедневной (если отсутствует)
    run_proposal_agent()
    inject_proposals(note)


if __name__ == "__main__":
    main()
