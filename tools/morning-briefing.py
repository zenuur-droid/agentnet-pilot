#!/usr/bin/env python3
"""
morning-briefing.py — утренний брифинг для @oleg-mac

Читает из agentnet:
  1. Последние market signals (что произошло на рынке)
  2. AgentNet Project intel (тренды/влияние/идеи для Проекта)
  3. Последние claude-ideas (что полезно мне как агенту)
  4. Частотный анализ текущей недели

Запускается в начале каждой сессии Mac.
Вывод — короткий, без лишнего. Инжектируется как контекст.

Usage:
  python3 morning-briefing.py          # полный брифинг
  python3 morning-briefing.py --short  # только топ-5 сигналов
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).parent.parent
SIGNALS_FILE    = REPO / "feeds" / "market-intel" / "signals.jsonl"
CLAUDE_IDEAS    = REPO / "feeds" / "claude-ideas" / "ideas.jsonl"
AGENTNET_PROJ   = REPO / "feeds" / "agentnet-project" / "signals.jsonl"
INTEL_DIR       = REPO / "feeds" / "market-intel"

SHORT_MODE = "--short" in sys.argv


def load_recent(path: Path, days: int = 3, limit: int = 30) -> list[dict]:
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


def load_latest_freq() -> dict | None:
    files = sorted(INTEL_DIR.glob("freq-*.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def fmt_direction(d: str) -> str:
    return {"рост": "↑", "новое": "★", "спад": "↓", "зрелость": "→"}.get(d, "·")


def main():
    now = datetime.now()
    signals  = load_recent(SIGNALS_FILE, days=3)
    ideas    = load_recent(CLAUDE_IDEAS, days=7, limit=10)
    ag_proj  = load_recent(AGENTNET_PROJ, days=7, limit=20)
    freq     = load_latest_freq()

    print(f"\n{'━'*55}")
    print(f"  Market Briefing — {now.strftime('%d %b %Y, %H:%M')}")
    print(f"{'━'*55}")

    # ── Рыночные сигналы ─────────────────────────────────────────
    if signals:
        # Группируем по direction, показываем самое важное
        new_things   = [s for s in signals if s.get("direction") == "новое"]
        rising       = [s for s in signals if s.get("direction") == "рост"]
        falling      = [s for s in signals if s.get("direction") == "спад"]

        print(f"\n📡 Рынок AI — последние {len(signals)} сигналов за 3 дня")
        print()

        shown = set()
        limit = 3 if SHORT_MODE else 5

        if new_things:
            print("  ★ НОВОЕ:")
            for s in new_things[:2]:
                topic = s.get("topic", "?")
                if topic not in shown:
                    shown.add(topic)
                    print(f"    {topic}: {s.get('signal','')[:80]}")
                    print(f"    [{s.get('source','')}]")
            print()

        if rising:
            print("  ↑ РАСТЁТ:")
            for s in rising[:limit]:
                topic = s.get("topic", "?")
                if topic not in shown:
                    shown.add(topic)
                    print(f"    {topic}: {s.get('signal','')[:80]}")
            print()

        if falling and not SHORT_MODE:
            print("  ↓ Теряет вес:")
            for s in falling[:2]:
                print(f"    {s.get('topic','?')}: {s.get('signal','')[:70]}")
            print()
    else:
        print("\n  (нет данных — rss-collector ещё не запускался)")

    # ── AgentNet Project intel ────────────────────────────────────
    if ag_proj:
        urgent = [s for s in ag_proj if s.get("urgency") == "now"]
        weekly = [s for s in ag_proj if s.get("urgency") == "week"]
        strategic = [s for s in ag_proj if s.get("urgency") == "month"]

        print(f"{'━'*55}")
        print(f"  🏗  AgentNet Project — {len(ag_proj)} сигналов за неделю")
        print()

        limit_ag = 2 if SHORT_MODE else 4

        if urgent:
            print("  ⚡ СРОЧНО:")
            for s in urgent[:2]:
                print(f"    {s.get('impact','')[:80]}")
                print(f"    → {s.get('idea','')[:75]}")
                print(f"    [{s.get('source','')}]")
            print()

        if weekly and not SHORT_MODE:
            print("  📡 На неделе:")
            for s in weekly[:3]:
                print(f"    {s.get('trend','')[:80]}")
                print(f"    → {s.get('idea','')[:75]}")
            print()

        if strategic and not SHORT_MODE:
            print("  🔭 Тренды:")
            for s in strategic[:limit_ag]:
                print(f"    {s.get('trend','')[:85]}")
            print()
    else:
        if not SHORT_MODE:
            print(f"\n  (нет agentnet-project сигналов — появятся после следующего rss-collector)")

    # ── Частотный анализ ─────────────────────────────────────────
    if freq and not SHORT_MODE:
        rising_terms = freq.get("rising", [])[:6]
        if rising_terms:
            print(f"  📈 Термины недели (биграммы):")
            for r in rising_terms:
                print(f"    {r['term']:<28} {r['label']}")
            print()

    # ── Идеи для меня (Claude) ───────────────────────────────────
    if ideas:
        print(f"{'━'*55}")
        print(f"  💡 Идеи для меня — {len(ideas)} за неделю")
        print()
        by_cat: dict = {}
        for idea in ideas:
            cat = idea.get("category", "meta")
            by_cat.setdefault(cat, []).append(idea)

        limit_ideas = 3 if SHORT_MODE else 6
        shown_ideas = 0
        for cat, cat_ideas in sorted(by_cat.items()):
            if shown_ideas >= limit_ideas:
                break
            print(f"  [{cat}]")
            for idea in cat_ideas[:2]:
                if shown_ideas >= limit_ideas:
                    break
                pattern  = idea.get("pattern", "")
                insight  = idea.get("insight", "")
                print(f"    {pattern}: {insight[:80]}")
                shown_ideas += 1
            print()
    else:
        print(f"\n  (нет claude-ideas — подождём первого прогона rss-collector)")

    print(f"{'━'*55}\n")

    # Краткая строка для инжекции в контекст
    if signals:
        topics = list({s.get("topic","") for s in signals if s.get("topic")})[:5]
        print(f"Context: AI market this week — {', '.join(topics)}")
        if ideas:
            patterns = [i.get("pattern","") for i in ideas[:3] if i.get("pattern")]
            print(f"Agent insights available: {', '.join(patterns)}")
    if ag_proj:
        urgent_ideas = [s.get("idea","") for s in ag_proj if s.get("urgency") == "now" and s.get("idea")][:2]
        if urgent_ideas:
            print(f"AgentNet urgent: {' | '.join(urgent_ideas)}")
    print()


if __name__ == "__main__":
    main()
