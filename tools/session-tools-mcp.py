#!/usr/bin/env python3
"""
session-tools-mcp — MCP сервер для инструментов сессии Claude Code.

Вместо запуска bash/python скриптов вручную в начале/конце сессии —
вызов инструментов напрямую из любой сессии.

Инструменты:
  get_session_cost()              — стоимость текущей сессии
  log_telemetry(...)              — логирование телеметрии AgentNet
  archive_session(summary)        — архивирование сессии в vault
  get_handoff()                   — прочитать handoff от предыдущей сессии
  write_handoff(content)          — записать handoff для следующей сессии
  append_session_log(content)     — дописать в лог сессии сегодняшнего дня

Регистрация:
  claude mcp add --scope user session-tools /usr/local/bin/python3 \
      /Users/user/agentnet-pilot/tools/session-tools-mcp.py
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from mcp.server.fastmcp import FastMCP

TASKS_DIR    = Path.home() / "tasks"
VAULT        = Path.home() / "obsidian-backup"
HANDOFF_FILE = VAULT / "AI" / "Claude Code" / "Mac" / "handoff.md"
LOGS_DIR     = VAULT / "AI" / "Claude Code" / "Mac"

mcp = FastMCP("session-tools")


def _run(cmd: list, timeout: int = 30) -> str:
    """Запускает команду и возвращает stdout+stderr."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        return out if out else "(нет вывода)"
    except subprocess.TimeoutExpired:
        return f"Timeout ({timeout}s) при выполнении: {' '.join(cmd)}"
    except Exception as e:
        return f"Ошибка: {e}"


@mcp.tool()
def get_session_cost() -> str:
    """Стоимость и статистика токенов текущей сессии Claude Code.

    Читает самый свежий JSONL-лог сессии и считает стоимость по API ценам.
    """
    script = TASKS_DIR / "session-cost.py"
    if not script.exists():
        return f"Скрипт не найден: {script}"
    return _run([sys.executable, str(script)], timeout=15)


@mcp.tool()
def log_telemetry(
    task: str,
    exchanges: int,
    success: bool,
    skill: str = "",
    notes: str = "",
) -> str:
    """Записывает телеметрию сессии в AgentNet.

    Args:
        task:      Тип задачи: debugging|new_feature|refactoring|research|writing|config|other
        exchanges: Количество обменов в сессии
        success:   True если задача выполнена успешно
        skill:     Применённый навык (например '@oleg-mac/daily-inject'), опционально
        notes:     Заметки о том, что помогло или почему паттерн не подошёл
    """
    script = Path.home() / "agentnet-pilot" / "tools" / "log-telemetry.py"
    if not script.exists():
        return f"Скрипт не найден: {script}"

    cmd = [
        sys.executable, str(script),
        "--task", task,
        "--exchanges", str(exchanges),
        "--success", str(success).lower(),
    ]
    if skill:
        cmd += ["--skill", skill]
    if notes:
        cmd += ["--notes", notes]

    return _run(cmd, timeout=30)


@mcp.tool()
def archive_session(summary: str = "") -> str:
    """Архивирует текущую сессию в Obsidian vault для RAG-поиска.

    Сохраняет фильтрованный лог + резюме в AI/Claude Code/Mac/chats/

    Args:
        summary: Готовое резюме сессии (что делали, что сделано, ключевые решения).
                 Если пусто — скрипт попробует сгенерировать автоматически.
    """
    script = TASKS_DIR / "session-archive.py"
    if not script.exists():
        return f"Скрипт не найден: {script}"

    cmd = [sys.executable, str(script)]
    if summary:
        cmd += ["--summary", summary]

    return _run(cmd, timeout=60)


@mcp.tool()
def get_handoff() -> str:
    """Читает handoff-файл от предыдущей сессии.

    Возвращает содержимое handoff.md или сообщение что файла нет.
    После прочтения — вызови delete_handoff() чтобы не читать повторно.
    """
    if not HANDOFF_FILE.exists():
        return "Handoff-файл не найден — предыдущая сессия не оставила задач."
    return HANDOFF_FILE.read_text(encoding="utf-8")


@mcp.tool()
def delete_handoff() -> str:
    """Удаляет handoff-файл после прочтения."""
    if not HANDOFF_FILE.exists():
        return "Handoff-файл уже отсутствует."
    HANDOFF_FILE.unlink()
    return "Handoff удалён."


@mcp.tool()
def write_handoff(content: str) -> str:
    """Записывает handoff для следующей сессии.

    Args:
        content: Текст handoff в markdown: текущая задача, модель, стоимость,
                 что сделано, что осталось, ключевые решения.
    """
    HANDOFF_FILE.parent.mkdir(parents=True, exist_ok=True)
    HANDOFF_FILE.write_text(content, encoding="utf-8")
    return f"Handoff записан: {HANDOFF_FILE}"


@mcp.tool()
def append_session_log(content: str) -> str:
    """Дописывает запись в лог сессии текущего дня.

    Args:
        content: Текст для добавления в лог (markdown).
                 Обычно: итоги задачи, решения, новые знания.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"{today}.md"

    if not log_file.exists():
        return f"Лог {today}.md не найден. Сначала создай его с правильным frontmatter."

    current = log_file.read_text(encoding="utf-8")
    new_text = current.rstrip() + "\n\n" + content.strip() + "\n"
    log_file.write_text(new_text, encoding="utf-8")
    return f"Добавлено в {log_file.name} ({len(content)} символов)"


if __name__ == "__main__":
    mcp.run()
