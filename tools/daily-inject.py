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


def inject(note_path: Path):
    today  = datetime.now().date()
    marker = f"<!-- ai-inject: {today.isoformat()} -->"
    text   = note_path.read_text(encoding="utf-8")

    if marker in text:
        print(f"Уже инжектировано: {note_path.name}")
        return

    # Читаем данные из agentnet
    ag_signals  = load_recent(AG_PROJ_FILE, days=7)
    cl_ideas    = load_recent(CLAUDE_FILE,  days=7, limit=500)
    mkt_signals = load_recent(MARKET_FILE,  days=3, limit=1000)  # Много сигналов, фильтруем по relevant_to_oleg

    alerts_section = build_alerts_section()
    tasks_section  = build_tasks_section()

    parts = [marker]
    if alerts_section:
        parts += [
            "<!-- alerts-start -->",
            alerts_section,
            "<!-- alerts-end -->",
            "",
            "---",
            "",
        ]
    if tasks_section:
        parts += [
            tasks_section,
            "",
            "---",
            "",
        ]
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

    block = "\n".join(parts)

    # Вставляем перед первым --- (разделитель после погоды)
    sep_idx = text.find("\n---")
    if sep_idx != -1:
        new_text = text[:sep_idx] + "\n\n" + block + text[sep_idx:]
    else:
        new_text = text.rstrip() + "\n\n" + block + "\n\n---\n"

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
        rel = str(note_path.relative_to(VAULT))
        subprocess.run(
            ["git", "-C", str(VAULT), "add", rel],
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
    """Если маркер уже стоит, но Новости пусты — заменить секцию.
    Нужно потому что Mac может заинжектировать раньше Linux и получить пустые
    Новости (signals живут на Linux, у Mac нет свежих данных).
    Запускается каждый раз независимо от маркера."""
    EMPTY_MARKER = "*(нет новостей за 3 дня)*"
    text = note_path.read_text(encoding="utf-8")
    if EMPTY_MARKER not in text:
        return  # Новости уже заполнены

    mkt_signals = load_recent(MARKET_FILE, days=3, limit=1000)
    relevant = [s for s in mkt_signals if s.get("relevant_to_oleg")]
    if not relevant:
        return  # Данных нет и у нас — ничего не делаем

    new_section = build_ideas_section(mkt_signals)
    old_section = f"### 📬 Новости\n{EMPTY_MARKER}"
    new_text = text.replace(old_section, new_section)
    note_path.write_text(new_text, encoding="utf-8")
    print(f"✅ [patch] Новости обновлены: {len(relevant)} сигналов")


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

    note = today_note_path()
    if not note.exists():
        print(f"Заметка не создана ещё: {note.name} — жду")
        sys.exit(0)
    inject(note)
    patch_empty_news(note)   # Патч пустых Новостей (Mac мог заинжектировать раньше)
    run_proposal_agent()
    inject_proposals(note)


if __name__ == "__main__":
    main()
