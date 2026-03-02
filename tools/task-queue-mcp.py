#!/usr/bin/env python3
"""
task-queue-mcp — MCP сервер для очереди задач Claude Code.

Вместо python3 ~/tasks/task-accept.py и ~/check-tasks.sh при каждом старте —
инструменты доступны напрямую из сессии.

Инструменты:
  task_status()               — здоровье очереди (быстро, без API)
  task_accept()               — прогнать reported задачи через acceptance pipeline
  check_periodic_tasks(machine) — проверить просроченные периодические задачи
  get_task_queue()            — сырое содержимое task-queue.yaml

Регистрация:
  claude mcp add --scope user task-queue /usr/local/bin/python3 \
      /Users/user/agentnet-pilot/tools/task-queue-mcp.py
"""

import subprocess
import sys
import yaml
from pathlib import Path
from mcp.server.fastmcp import FastMCP

TASKS_DIR  = Path.home() / "tasks"
VAULT      = Path.home() / "obsidian-backup"
QUEUE_FILE = VAULT / "AI" / "Claude Code" / "task-queue.yaml"
CHECK_TASKS= Path.home() / "check-tasks.sh"

mcp = FastMCP("task-queue")


def _run(cmd: list, timeout: int = 60) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        return out if out else "(нет вывода — очередь чистая)"
    except subprocess.TimeoutExpired:
        return f"Timeout ({timeout}s)"
    except Exception as e:
        return f"Ошибка: {e}"


@mcp.tool()
def task_status() -> str:
    """Здоровье очереди задач — быстрая проверка без API-запросов.

    Показывает: количество задач по статусам, просроченные, ближайшие дедлайны.
    Запускать при старте каждой сессии.
    """
    script = TASKS_DIR / "task-accept.py"
    if not script.exists():
        return f"Скрипт не найден: {script}"
    return _run([sys.executable, str(script), "--status"], timeout=20)


@mcp.tool()
def task_accept() -> str:
    """Прогоняет reported задачи через acceptance pipeline.

    Автоматически закрывает задачи с типом 'none', запускает check_cmd для 'script'.
    Запускать при старте сессии после task_status().
    """
    script = TASKS_DIR / "task-accept.py"
    if not script.exists():
        return f"Скрипт не найден: {script}"
    return _run([sys.executable, str(script)], timeout=60)


@mcp.tool()
def check_periodic_tasks(machine: str = "mac") -> str:
    """Проверяет просроченные периодические задачи.

    Возвращает задачи с дедлайном сегодня или в прошлом.
    Пустой вывод = всё в порядке.

    Args:
        machine: 'mac' | 'linux' | 'win' (по умолчанию 'mac')
    """
    if not CHECK_TASKS.exists():
        return f"Скрипт не найден: {CHECK_TASKS}"
    return _run(["bash", str(CHECK_TASKS), machine], timeout=15)


@mcp.tool()
def get_task_queue() -> str:
    """Полное содержимое очереди задач task-queue.yaml.

    Показывает все задачи со статусами, критериями приёмки, результатами.
    """
    if not QUEUE_FILE.exists():
        return f"Очередь не найдена: {QUEUE_FILE}"

    try:
        data = yaml.safe_load(QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return f"Ошибка парсинга YAML: {e}"

    tasks = data.get("tasks", [])
    if not tasks:
        return "Очередь задач пуста."

    # Группируем по статусу
    by_status: dict = {}
    for t in tasks:
        st = t.get("status", "unknown")
        by_status.setdefault(st, []).append(t)

    lines = [f"## Task Queue — {len(tasks)} задач\n"]
    status_order = ["pending", "in_progress", "reported", "done", "rejected"]
    for st in status_order:
        if st not in by_status:
            continue
        lines.append(f"### {st.upper()} ({len(by_status[st])})")
        for t in by_status[st]:
            tid   = t.get("id", "?")
            title = t.get("title", "")
            due   = t.get("due", "")
            due_str = f" [до {due}]" if due else ""
            lines.append(f"- **{tid}**: {title}{due_str}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
