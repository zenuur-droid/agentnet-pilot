#!/usr/bin/env python3
"""
system-signals-mcp — MCP сервер для системных сигналов и очередей улучшений.

Вместо запуска python/bash команд при старте сессии для проверки P1/P2 сигналов,
гипотез и обновлений знаний — всё доступно через MCP инструменты.

Инструменты:
  get_system_signals(priority)        — P1/P2 сигналы из signals.yaml
  get_pending_hypotheses()            — черновики гипотез для улучшения агента
  get_pending_knowledge_updates()     — предложения по обновлению конфигурации
  mark_signal_seen(source, message)   — пометить сигнал как seen
  get_startup_checklist()             — все проверки старта сессии одним вызовом

Регистрация:
  claude mcp add --scope user system-signals /usr/local/bin/python3 \
      /Users/user/agentnet-pilot/tools/system-signals-mcp.py
"""

import yaml
from datetime import datetime
from pathlib import Path
from mcp.server.fastmcp import FastMCP

VAULT          = Path.home() / "obsidian-backup"
SIGNALS_FILE   = VAULT / "AI" / "Claude Code" / "signals.yaml"
HYPOTHESES_FILE= VAULT / "AI" / "Claude Code" / "pending-claude-hypotheses.md"
KNOWLEDGE_FILE = VAULT / "AI" / "Claude Code" / "pending-knowledge-updates.md"

mcp = FastMCP("system-signals")


def _load_signals() -> list:
    if not SIGNALS_FILE.exists():
        return []
    try:
        data = yaml.safe_load(SIGNALS_FILE.read_text(encoding="utf-8"))
        return data.get("signals", []) if data else []
    except Exception:
        return []


@mcp.tool()
def get_system_signals(priority: str = "") -> str:
    """Системные сигналы от автономных процессов (P1/P2 = требуют внимания).

    Args:
        priority: Фильтр приоритета: 'P1' | 'P2' | 'P3' | '' (все новые)
    """
    signals = _load_signals()
    new_signals = [s for s in signals if s.get("status") == "new"]

    if priority:
        new_signals = [s for s in new_signals if s.get("priority") == priority]

    if not signals:
        return "signals.yaml пуст или не найден."
    if not new_signals:
        return f"Нет новых сигналов{' с приоритетом ' + priority if priority else ''}."

    lines = [f"## Системные сигналы — {len(new_signals)} новых\n"]
    priority_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    new_signals.sort(key=lambda s: priority_order.get(s.get("priority", "P4"), 9))

    for s in new_signals:
        p = s.get("priority", "?")
        src = s.get("source", "")
        msg = s.get("message", "")
        lines.append(f"**{p}** [{src}]: {msg}")

    return "\n".join(lines)


@mcp.tool()
def get_pending_hypotheses() -> str:
    """Черновики гипотез для улучшения агента, ожидающие проверки.

    Генерируются meta-analysis.py, требуют ответа 'да/нет' от пользователя.
    """
    if not HYPOTHESES_FILE.exists():
        return "Нет черновиков гипотез."
    content = HYPOTHESES_FILE.read_text(encoding="utf-8").strip()
    if not content:
        return "Файл pending-claude-hypotheses.md пуст."
    return f"## Черновики гипотез\n\n{content}"


@mcp.tool()
def get_pending_knowledge_updates() -> str:
    """Предложения по обновлению конфигурации из changelog/идей RSS.

    После просмотра — применить с Edit/Write, затем python3 ~/tasks/knowledge-updater.py --apply
    """
    if not KNOWLEDGE_FILE.exists():
        return "Нет предложений по обновлению знаний."
    content = KNOWLEDGE_FILE.read_text(encoding="utf-8").strip()
    if not content:
        return "Файл pending-knowledge-updates.md пуст."
    return f"## Предложения по обновлению знаний\n\n{content}"


@mcp.tool()
def mark_signal_seen(source: str, message_fragment: str = "") -> str:
    """Помечает сигнал как seen (обработан).

    Args:
        source:           Источник сигнала (поле source в signals.yaml)
        message_fragment: Часть текста сообщения для идентификации (опционально)
    """
    if not SIGNALS_FILE.exists():
        return "signals.yaml не найден."

    try:
        data = yaml.safe_load(SIGNALS_FILE.read_text(encoding="utf-8")) or {}
        signals = data.get("signals", [])
        changed = 0
        for s in signals:
            if s.get("source") == source and s.get("status") == "new":
                if not message_fragment or message_fragment in s.get("message", ""):
                    s["status"] = "seen"
                    changed += 1

        if changed == 0:
            return f"Сигнал от '{source}' не найден или уже seen."

        data["signals"] = signals
        SIGNALS_FILE.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8"
        )
        return f"Помечено как seen: {changed} сигнал(ов) от '{source}'."
    except Exception as e:
        return f"Ошибка: {e}"


@mcp.tool()
def get_startup_checklist() -> str:
    """Все проверки старта сессии одним вызовом.

    Заменяет 5 отдельных проверок из CLAUDE.md:
    - P1/P2 сигналы
    - Pending hypotheses
    - Pending knowledge updates
    - Наличие handoff
    - Наличие лога сегодняшнего дня
    """
    lines = [f"## Чеклист старта сессии — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]

    # P1/P2 сигналы
    signals = _load_signals()
    urgent = [s for s in signals if s.get("status") == "new" and s.get("priority") in ("P1", "P2")]
    if urgent:
        lines.append(f"🔴 **{len(urgent)} срочных сигналов P1/P2** — вызови get_system_signals('P1')")
        for s in urgent:
            lines.append(f"   {s.get('priority')} [{s.get('source')}]: {s.get('message','')[:80]}")
    else:
        lines.append("✅ P1/P2 сигналы: нет")

    # Hypotheses
    if HYPOTHESES_FILE.exists() and HYPOTHESES_FILE.stat().st_size > 0:
        lines.append("💡 **Есть черновики гипотез** — вызови get_pending_hypotheses()")
    else:
        lines.append("✅ Гипотезы: нет")

    # Knowledge updates
    if KNOWLEDGE_FILE.exists() and KNOWLEDGE_FILE.stat().st_size > 0:
        lines.append("📚 **Есть обновления знаний** — вызови get_pending_knowledge_updates()")
    else:
        lines.append("✅ Обновления знаний: нет")

    # Handoff
    handoff = Path.home() / "obsidian-backup" / "AI" / "Claude Code" / "Mac" / "handoff.md"
    if handoff.exists():
        lines.append("📋 **Есть handoff** — вызови session_tools.get_handoff()")
    else:
        lines.append("✅ Handoff: нет")

    # Лог сегодня
    today = datetime.now().strftime("%Y-%m-%d")
    log = Path.home() / "obsidian-backup" / "AI" / "Claude Code" / "Mac" / f"{today}.md"
    if log.exists():
        lines.append(f"✅ Лог сессии: {today}.md существует")
    else:
        lines.append(f"⚠️  **Лог {today}.md не создан** — создай с frontmatter machine: mac")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
