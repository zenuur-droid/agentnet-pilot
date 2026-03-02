#!/usr/bin/env python3
"""
daily-inject.py — инжектирует AI-блок в ежедневную заметку Obsidian.

Запускается каждые 10 минут (LaunchAgent com.daily.inject).
Структура блока:
  ### 🏗 AgentNet  — тренды/влияние/идеи для Проекта
  ### 💡 Клод      — паттерны для агента
  ### 📬 Новости   — RSS-новости дня
  ### 📋 Предложения — готовые предложения от idea-to-proposal (чекбоксы)
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

VAULT          = Path.home() / "obsidian-backup"
DAYS_DIR       = VAULT / "Дни"
AGENTNET       = Path.home() / "agentnet-pilot"
AG_PROJ_FILE   = AGENTNET / "feeds" / "agentnet-project" / "signals.jsonl"
CLAUDE_FILE    = AGENTNET / "feeds" / "claude-ideas" / "ideas.jsonl"
MARKET_FILE    = AGENTNET / "feeds" / "market-intel" / "signals.jsonl"
PENDING_HYPO   = VAULT / "AI" / "Claude Code" / "pending-claude-hypotheses.md"

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
    cat_priority = {
        "memory": 0, "coordination": 1, "autonomy": 2,
        "tools": 3, "cost": 4, "reasoning": 5, "meta": 6,
    }
    sorted_ideas = sorted(ideas, key=lambda i: cat_priority.get(i.get("category", ""), 9))
    shown_count = min(len(sorted_ideas), MAX)
    lines = [f"### 💡 Клод — топ-{shown_count} из {len(sorted_ideas)} инсайтов"]
    shown = 0
    for idea in sorted_ideas:
        if shown >= MAX:
            break
        pattern = idea.get("pattern", "")
        insight = idea.get("insight", "")
        cat     = idea.get("category", "")
        lines.append("")
        lines.append(f"**{pattern}** *({cat})*")
        lines.append(insight)
        shown += 1

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
    cl_ideas    = load_recent(CLAUDE_FILE,  days=7, limit=10)
    mkt_signals = load_recent(MARKET_FILE,  days=3, limit=50)

    block = "\n".join([
        marker,
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
    ])

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


def main():
    note = today_note_path()
    if not note.exists():
        print(f"Заметка не создана ещё: {note.name} — жду")
        sys.exit(0)
    inject(note)
    run_proposal_agent()
    inject_proposals(note)


if __name__ == "__main__":
    main()
