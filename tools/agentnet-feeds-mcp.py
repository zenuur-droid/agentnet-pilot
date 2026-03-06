#!/usr/bin/env python3
"""
agentnet-feeds-mcp — MCP сервер для AgentNet фидов.

Инструменты:
  get_market_signals(days, limit)    — рыночные сигналы из market-intel
  get_claude_ideas(days, limit)      — инсайты агента из claude-ideas
  get_agentnet_signals(days, urgency)— сигналы для Проекта из agentnet-project
  get_morning_briefing(short)        — готовый брифинг для начала сессии
  get_weekly_digest(feed)            — последний недельный дайджест

Регистрация:
  claude mcp add agentnet-feeds /usr/local/bin/python3 \
      /Users/user/agentnet-pilot/tools/agentnet-feeds-mcp.py
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from mcp.server.fastmcp import FastMCP

REPO         = Path(__file__).parent.parent
MARKET_FILE      = REPO / "feeds" / "market-intel"    / "signals.jsonl"
CLAUDE_FILE      = REPO / "feeds" / "claude-ideas"    / "ideas.jsonl"
AGENTNET_FILE    = REPO / "feeds" / "agentnet-project" / "signals.jsonl"
PERSONALOS_FILE  = REPO / "feeds" / "personalos"      / "signals.jsonl"
INTEL_DIR        = REPO / "feeds" / "market-intel"

mcp = FastMCP("agentnet-feeds")


def _load(path: Path, days: int, limit: int) -> list:
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


@mcp.tool()
def get_market_signals(days: int = 3, limit: int = 15) -> str:
    """Рыночные AI-сигналы из RSS за последние N дней.

    Args:
        days:  Глубина выборки в днях (по умолчанию 3)
        limit: Максимальное число записей (по умолчанию 15)
    """
    records = _load(MARKET_FILE, days, limit)
    if not records:
        return f"Нет рыночных сигналов за последние {days} дней."

    dir_icon = {"рост": "↑", "новое": "★", "спад": "↓", "зрелость": "→"}
    dir_priority = {"новое": 0, "рост": 1, "зрелость": 2, "спад": 3}
    relevant = [r for r in records if r.get("relevant_to_oleg")]
    all_sorted = sorted(records, key=lambda s: dir_priority.get(s.get("direction", ""), 9))

    lines = [f"## Рыночные сигналы — {len(records)} за {days} дн. ({len(relevant)} релевантных)\n"]
    for r in all_sorted:
        icon  = dir_icon.get(r.get("direction", ""), "·")
        rel   = " ✓" if r.get("relevant_to_oleg") else ""
        action = r.get("action", "")
        lines.append(f"{icon} **{r.get('topic','')}**{rel}  ({r.get('source','')})")
        lines.append(f"   {r.get('signal','')}")
        if action:
            lines.append(f"   → {action}")

    return "\n".join(lines)


@mcp.tool()
def get_claude_ideas(days: int = 7, limit: int = 10) -> str:
    """Инсайты и паттерны для Claude-агента за последние N дней.

    Args:
        days:  Глубина выборки (по умолчанию 7)
        limit: Максимум записей (по умолчанию 10)
    """
    records = _load(CLAUDE_FILE, days, limit)
    if not records:
        return f"Нет claude-ideas за последние {days} дней."

    cat_priority = {
        "memory": 0, "coordination": 1, "autonomy": 2,
        "tools": 3, "cost": 4, "reasoning": 5, "meta": 6,
    }
    sorted_ideas = sorted(records, key=lambda i: cat_priority.get(i.get("category", ""), 9))

    lines = [f"## Claude-идеи — {len(records)} за {days} дн.\n"]
    for r in sorted_ideas:
        lines.append(f"**{r.get('pattern','')}** *({r.get('category','')})*")
        lines.append(f"   {r.get('insight','')}")
        lines.append(f"   Источник: {r.get('source','')}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def get_agentnet_signals(days: int = 7, urgency: str = "") -> str:
    """Сигналы для AgentNet Project за последние N дней.

    Args:
        days:    Глубина выборки (по умолчанию 7)
        urgency: Фильтр: 'now' | 'week' | 'month' | '' (все)
    """
    records = _load(AGENTNET_FILE, days, 30)
    if not records:
        return "Нет agentnet-project сигналов. Появятся после следующего прогона rss-collector (06:00 UTC)."

    if urgency:
        records = [r for r in records if r.get("urgency") == urgency]

    urgency_order = {"now": 0, "week": 1, "month": 2}
    records.sort(key=lambda r: urgency_order.get(r.get("urgency", ""), 9))

    icon_map = {"now": "⚡", "week": "📡", "month": "🔭"}
    lines = [f"## AgentNet Project — {len(records)} сигналов за {days} дн.\n"]
    for r in records:
        icon = icon_map.get(r.get("urgency", ""), "·")
        lines.append(f"{icon} [{r.get('urgency','')}] {r.get('impact','')}")
        lines.append(f"   Тренд: {r.get('trend','')}")
        lines.append(f"   Идея: {r.get('idea','')}")
        lines.append(f"   Источник: {r.get('source','')}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def get_personalos_signals(days: int = 7, domain: str = "") -> str:
    """Сигналы PersonalOS: здоровье, longevity, quantified-self, AI+health.

    Args:
        days:   Глубина выборки (по умолчанию 7)
        domain: Фильтр: 'longevity' | 'health-tech' | 'quantified-self' | 'ai-health' | '' (все)
    """
    records = _load(PERSONALOS_FILE, days, 30)
    if not records:
        return "Нет personalos сигналов. Появятся после следующего прогона rss-collector (06:00 UTC)."

    if domain:
        records = [r for r in records if r.get("domain") == domain]

    urgency_order = {"now": 0, "week": 1, "month": 2}
    records.sort(key=lambda r: urgency_order.get(r.get("urgency", ""), 9))

    domain_icon = {"longevity": "🧬", "health-tech": "⌚", "quantified-self": "📊", "ai-health": "🤖", "biohacking": "⚡"}
    urgency_icon = {"now": "⚡", "week": "📡", "month": "🔭"}

    lines = [f"## PersonalOS — {len(records)} сигналов за {days} дн.\n"]
    for r in records:
        d_icon = domain_icon.get(r.get("domain", ""), "·")
        u_icon = urgency_icon.get(r.get("urgency", ""), "·")
        lines.append(f"{d_icon} {u_icon} **{r.get('domain', '')}** ({r.get('source', '')})")
        lines.append(f"   {r.get('signal', '')}")
        relevance = r.get("relevance", "")
        if relevance:
            lines.append(f"   → {relevance}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def get_morning_briefing(short: bool = True) -> str:
    """Утренний брифинг для начала сессии: рынок + AgentNet + claude-ideas.

    Args:
        short: True = топ-5 сигналов (по умолчанию), False = полный
    """
    market   = _load(MARKET_FILE,   days=3, limit=30)
    ideas    = _load(CLAUDE_FILE,   days=7, limit=10)
    ag_proj  = _load(AGENTNET_FILE, days=7, limit=20)

    now = datetime.now()
    lines = [f"# Брифинг — {now.strftime('%d %b %Y, %H:%M')}\n"]

    # Рынок
    relevant = [s for s in market if s.get("relevant_to_oleg")]
    new_things = [s for s in relevant if s.get("direction") == "новое"]
    rising     = [s for s in relevant if s.get("direction") == "рост"]
    limit = 3 if short else 6

    lines.append(f"## 📡 Рынок — {len(market)} сигналов, {len(relevant)} для тебя\n")
    if new_things:
        lines.append("★ НОВОЕ:")
        for s in new_things[:2]:
            lines.append(f"  {s.get('topic','')}: {s.get('signal','')[:90]}")
    if rising:
        lines.append("↑ РАСТЁТ:")
        for s in rising[:limit]:
            lines.append(f"  {s.get('topic','')}: {s.get('signal','')[:90]}")

    # AgentNet Project
    if ag_proj:
        urgent = [s for s in ag_proj if s.get("urgency") == "now"]
        lines.append(f"\n## 🏗 AgentNet Project — {len(ag_proj)} сигналов\n")
        if urgent:
            lines.append("⚡ СРОЧНО:")
            for s in urgent[:2]:
                lines.append(f"  {s.get('impact','')[:90]}")
                lines.append(f"  → {s.get('idea','')[:80]}")
        if not short:
            weekly = [s for s in ag_proj if s.get("urgency") == "week"]
            for s in weekly[:3]:
                lines.append(f"  📡 {s.get('trend','')[:90]}")

    # Claude-идеи
    if ideas:
        cat_priority = {"memory": 0, "coordination": 1, "autonomy": 2, "tools": 3, "cost": 4}
        top = sorted(ideas, key=lambda i: cat_priority.get(i.get("category", ""), 9))
        lines.append(f"\n## 💡 Клод — {len(ideas)} инсайтов\n")
        for idea in top[:3]:
            lines.append(f"  **{idea.get('pattern','')}** ({idea.get('category','')})")
            lines.append(f"  {idea.get('insight','')[:100]}")

    # Context string
    if market:
        topics = list({s.get("topic", "") for s in relevant if s.get("topic")})[:5]
        lines.append(f"\nContext: {', '.join(topics)}")
    if ag_proj:
        urgent_ideas = [s.get("idea","") for s in ag_proj if s.get("urgency") == "now" and s.get("idea")][:2]
        if urgent_ideas:
            lines.append(f"AgentNet urgent: {' | '.join(urgent_ideas)}")

    return "\n".join(lines)


@mcp.tool()
def get_weekly_digest(feed: str = "agentnet-project") -> str:
    """Последний недельный дайджест из фида.

    Args:
        feed: 'agentnet-project' | 'market-intel'
    """
    feed_dir = REPO / "feeds" / feed
    if not feed_dir.exists():
        return f"Фид '{feed}' не найден."

    files = sorted(feed_dir.glob("weekly-*.md"))
    if not files:
        return f"Нет недельных дайджестов в {feed}. Появятся в воскресенье после rss-collector."

    latest = files[-1]
    return f"## {latest.name}\n\n{latest.read_text(encoding='utf-8')}"


if __name__ == "__main__":
    mcp.run()
