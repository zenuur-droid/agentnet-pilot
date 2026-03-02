#!/usr/bin/env python3
"""
memory-search-mcp — MCP сервер для поиска по памяти агента.

Вместо загрузки всего MEMORY.md (295+ строк) в контекст —
запрос только нужных секций.

Инструменты:
  search_memory(query)          — поиск по MEMORY.md + topic-файлам
  get_memory_topic(topic)       — полное содержимое topic-файла
  list_memory_topics()          — список доступных topic-файлов
  get_memory_section(section)   — конкретная секция MEMORY.md по заголовку

Регистрация:
  claude mcp add --scope user memory-search /usr/local/bin/python3 \
      /Users/user/agentnet-pilot/tools/memory-search-mcp.py
"""

from pathlib import Path
from mcp.server.fastmcp import FastMCP

MEMORY_DIR  = Path.home() / ".claude" / "projects" / "-Users-user" / "memory"
MEMORY_FILE = MEMORY_DIR / "MEMORY.md"

mcp = FastMCP("memory-search")


def _parse_sections(text: str) -> list[dict]:
    """Разбивает markdown на секции по ## заголовкам."""
    sections = []
    current_title = "header"
    current_lines = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_lines:
                sections.append({"title": current_title, "content": "\n".join(current_lines)})
            current_title = line[3:].strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append({"title": current_title, "content": "\n".join(current_lines)})
    return sections


def _score(text: str, query: str) -> int:
    """Простой score: сколько слов из query есть в тексте."""
    words = query.lower().split()
    t = text.lower()
    return sum(1 for w in words if w in t)


@mcp.tool()
def search_memory(query: str) -> str:
    """Поиск по всем файлам памяти агента.

    Ищет в MEMORY.md и topic-файлах. Возвращает релевантные секции.

    Args:
        query: Поисковый запрос (например 'tailscale', 'ssh linux', 'proxy')
    """
    results = []

    # Поиск в MEMORY.md по секциям
    if MEMORY_FILE.exists():
        sections = _parse_sections(MEMORY_FILE.read_text(encoding="utf-8"))
        for sec in sections:
            score = _score(sec["content"], query)
            if score > 0:
                results.append((score, f"[MEMORY.md → {sec['title']}]\n{sec['content']}"))

    # Поиск в topic-файлах (каждый файл целиком как одна секция)
    for topic_file in sorted(MEMORY_DIR.glob("*.md")):
        if topic_file.name == "MEMORY.md":
            continue
        text = topic_file.read_text(encoding="utf-8")
        score = _score(text, query)
        if score > 0:
            # Показываем первые 60 строк чтобы не перегружать
            preview = "\n".join(text.splitlines()[:60])
            results.append((score, f"[topic: {topic_file.stem}]\n{preview}"))

    if not results:
        return f"По запросу «{query}» ничего не найдено в памяти агента."

    results.sort(key=lambda x: -x[0])
    parts = [f"## Результаты поиска: «{query}» — {len(results)} совпадений\n"]
    for i, (score, content) in enumerate(results[:5], 1):
        parts.append(f"### [{i}] relevance={score}\n{content}\n")

    return "\n".join(parts)


@mcp.tool()
def list_memory_topics() -> str:
    """Список всех topic-файлов памяти с кратким описанием первой строки."""
    files = sorted(MEMORY_DIR.glob("*.md"))
    lines = ["## Topic-файлы памяти агента\n"]
    for f in files:
        first_line = ""
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#"):
                    first_line = line.strip()[:80]
                    break
        except Exception:
            pass
        lines.append(f"- **{f.stem}** — {first_line}")
    lines.append(f"\nВсего файлов: {len(files)}")
    return "\n".join(lines)


@mcp.tool()
def get_memory_topic(topic: str) -> str:
    """Полное содержимое topic-файла памяти.

    Args:
        topic: Имя файла без .md (например 'tailscale-setup', 'networking', 'linux-survivability')
    """
    path = MEMORY_DIR / f"{topic}.md"
    if not path.exists():
        available = [f.stem for f in MEMORY_DIR.glob("*.md")]
        return f"Файл '{topic}.md' не найден.\nДоступные: {', '.join(available)}"
    return path.read_text(encoding="utf-8")


@mcp.tool()
def get_memory_section(section: str) -> str:
    """Конкретная секция из MEMORY.md по заголовку (частичное совпадение).

    Args:
        section: Часть заголовка секции (например 'Tailscale', 'SSH', 'Запреты')
    """
    if not MEMORY_FILE.exists():
        return "MEMORY.md не найден."

    sections = _parse_sections(MEMORY_FILE.read_text(encoding="utf-8"))
    query_l = section.lower()
    found = [s for s in sections if query_l in s["title"].lower()]

    if not found:
        titles = [s["title"] for s in sections]
        return f"Секция «{section}» не найдена.\nДоступные: {', '.join(titles)}"

    return "\n\n".join(s["content"] for s in found)


if __name__ == "__main__":
    mcp.run()
