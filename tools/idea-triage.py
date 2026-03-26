#!/usr/bin/env python3
"""
idea-triage.py — Idea Triage Agent (keyword-based).

ПРИНЦИП: агент НЕ удаляет — только маркирует.
         Все идеи попадают в брифинг — изменяется только порядок и метки.

Читает: signals.jsonl, ideas.jsonl (последние N дней)
        SURVEILLANCE-CONFIG.md (tracked topics для дедупликации)
Пишет: feeds/triage-cache.jsonl  (url → {urgency, type, confidence})
Запуск: cron 06:15 (после rss-collector 06:00, до daily-inject 06:30)

v2: keyword-based вместо Ollama. Мгновенная обработка, без лимита батча.

Urgency: hot | warm | cold
Type:    инфра | клод | бизнес | знание | шум
Confidence: high (детерминированные правила)
"""

import json
import re
import fcntl
from datetime import datetime, timedelta
from pathlib import Path

AGENTNET = Path.home() / "agentnet-pilot"
SIGNALS_FILE = AGENTNET / "feeds" / "market-intel" / "signals.jsonl"
IDEAS_FILE   = AGENTNET / "feeds" / "claude-ideas" / "ideas.jsonl"
TRIAGE_CACHE = AGENTNET / "feeds" / "triage-cache.jsonl"
LOG_FILE     = Path.home() / "logs" / "idea-triage.log"

_VAULT_CANDIDATES = [
    Path.home() / "obsidian-vault",
    Path.home() / "obsidian-backup",
    Path.home() / "obsidian",
]
VAULT = next((p for p in _VAULT_CANDIDATES if (p / "Дни").exists()), _VAULT_CANDIDATES[0])
SURVEILLANCE_CONFIG = VAULT / "AI" / "Claude Code" / "SURVEILLANCE-CONFIG.md"

DAYS_BACK = 3

# --- Keyword sets for type classification ---

_KW_CLAUDE = {
    "claude", "agent", "llm", "gpt", "anthropic", "model", "prompt",
    "fine-tun", "rlhf", "alignment", "reasoning", "агент", "модел",
    "промпт", "safety", "autonomous", "автоном", "self-improv",
    "mcp", "tool_use", "function_call", "claude-code", "cursor",
    "copilot", "coding-agent", "agentic", "orchestr",
}

_KW_INFRA = {
    "api", "deploy", "infra", "docker", "kubernetes", "systemd",
    "server", "pipeline", "gpu", "vram", "ollama", "comfyui",
    "tailscale", "vpn", "ssh", "cron", "linux", "nginx",
    "сервер", "деплой", "инфра", "контейнер",
}

_KW_BUSINESS = {
    "business", "revenue", "startup", "funding", "market", "product",
    "saas", "pricing", "monetiz", "income", "бизнес", "доход",
    "продукт", "стартап", "монетиз", "заработ",
}

_KW_NOISE = {
    "реклам", "подборк", "рейтинг", "топ-10", "top-10", "listicle",
    "sponsored", "промо", "обзор лучших", "best of",
}

# Surveillance themes → hot urgency keywords (extracted from SURVEILLANCE-CONFIG)
_KW_HOT = {
    "персональн", "аватар", "multi-agent", "мульти-агент",
    "persistent memory", "самообуч", "self-learn", "safety",
    "claude code", "pkm", "obsidian", "local-first",
    "income", "доход", "монетиз", "учёный",
}


def log(msg: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"{ts} [idea-triage] {msg}\n")


def load_triage_cache() -> dict:
    """url → triage dict"""
    cache = {}
    if not TRIAGE_CACHE.exists():
        return cache
    for line in TRIAGE_CACHE.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            cache[r["url"]] = r
        except Exception:
            pass
    return cache


def load_tracked_topics() -> list[dict]:
    """Парсит SURVEILLANCE-CONFIG.md → tracked topics с задачами."""
    if not SURVEILLANCE_CONFIG.exists():
        log(f"SURVEILLANCE-CONFIG не найден: {SURVEILLANCE_CONFIG}")
        return []
    topics = []
    in_table = False
    for line in SURVEILLANCE_CONFIG.read_text(encoding="utf-8").splitlines():
        if "| ID |" in line:
            in_table = True
            continue
        if in_table and line.startswith("|--"):
            continue
        if in_table and line.startswith("|"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 4:
                wid, theme, status, task = parts[0], parts[1], parts[2], parts[3]
                if "closed" in status.lower() or "~~" in wid:
                    topics.append({"theme": theme, "status": "closed", "task": task})
                elif task and task != "—":
                    topics.append({"theme": theme, "status": "active", "task": task})
        elif in_table and not line.startswith("|"):
            break
    log(f"Tracked topics: {len(topics)} ({sum(1 for t in topics if t['status'] == 'closed')} closed)")
    return topics


def is_already_tracked(item: dict, tracked: list[dict]) -> str | None:
    """Проверяет совпадение сигнала с tracked topic. Возвращает тему или None."""
    text = build_text(item).lower()
    for t in tracked:
        keywords = [w.lower() for w in re.findall(r'[a-zA-Zа-яА-ЯёЁ]{4,}', t["theme"])]
        if not keywords:
            continue
        matches = sum(1 for kw in keywords if kw in text)
        if matches >= 2 or (len(keywords) <= 2 and matches >= 1):
            return t["theme"]
    return None


def load_recent_items() -> list:
    cutoff = datetime.now() - timedelta(days=DAYS_BACK)
    items = []

    for path in [SIGNALS_FILE, IDEAS_FILE]:
        if not path.exists():
            continue
        feed = "signals" if "market-intel" in str(path) else "ideas"
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line.strip())
                ts = datetime.fromisoformat(r.get("ts", "2000-01-01T00:00:00"))
                if ts >= cutoff:
                    r["_feed"] = feed
                    items.append(r)
            except Exception:
                pass

    return items


def build_text(item: dict) -> str:
    """Формирует текст для анализа из полей записи."""
    parts = []
    if item.get("topic"):
        parts.append(item["topic"])
    if item.get("signal"):
        parts.append(item["signal"])
    if item.get("pattern"):
        parts.append(item["pattern"])
    if item.get("insight"):
        parts.append(item["insight"])
    if item.get("title_original"):
        parts.append(item["title_original"])
    if item.get("action"):
        parts.append(item["action"])
    return " ".join(parts) or item.get("url", "")


def _count_kw_hits(text: str, kw_set: set) -> int:
    """Считает сколько ключевых слов из набора встречаются в тексте."""
    return sum(1 for kw in kw_set if kw in text)


def keyword_triage(item: dict) -> dict:
    """Классифицирует запись по keyword rules. Всегда возвращает результат."""
    text = build_text(item).lower()
    relevant = item.get("relevant_to_oleg", False)
    has_action = bool(item.get("action") and item.get("why"))
    feed = item.get("_feed", "?")

    # --- Type ---
    scores = {
        "клод": _count_kw_hits(text, _KW_CLAUDE),
        "инфра": _count_kw_hits(text, _KW_INFRA),
        "бизнес": _count_kw_hits(text, _KW_BUSINESS),
        "шум": _count_kw_hits(text, _KW_NOISE),
    }
    best_type = max(scores, key=scores.get)
    if scores[best_type] == 0:
        item_type = "знание"
    elif best_type == "шум" and scores["шум"] >= 1:
        item_type = "шум"
    else:
        item_type = best_type

    # --- Urgency ---
    hot_hits = _count_kw_hits(text, _KW_HOT)

    if item_type == "шум":
        urgency = "cold"
        reason = "noise keywords"
    elif hot_hits >= 2 and relevant:
        urgency = "hot"
        reason = f"surveillance match ({hot_hits} kw) + relevant"
    elif hot_hits >= 3:
        urgency = "hot"
        reason = f"strong surveillance match ({hot_hits} kw)"
    elif relevant and has_action and hot_hits >= 1:
        urgency = "hot"
        reason = "relevant + actionable + surveillance"
    elif relevant and has_action:
        urgency = "warm"
        reason = "relevant + actionable"
    elif feed == "ideas" and has_action:
        urgency = "warm"
        reason = "idea with action/why"
    elif hot_hits >= 2:
        urgency = "warm"
        reason = f"surveillance match ({hot_hits} kw)"
    else:
        # relevant без action, ideas без action, всё остальное → cold
        # cold попадает в Новости, не в Разведку
        urgency = "cold"
        reason = "relevant" if relevant else "no strong signals"

    return {
        "urgency": urgency,
        "type": item_type,
        "confidence": "high",
        "reason": reason,
    }


def write_record(record: dict):
    """Append record to triage cache with file lock."""
    with open(TRIAGE_CACHE, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def main():
    log("Запуск idea-triage (keyword-based v2)")
    cache = load_triage_cache()
    items = load_recent_items()
    tracked = load_tracked_topics()

    new_items = [i for i in items if i.get("url") and i["url"] not in cache]
    log(f"Всего свежих: {len(items)}, не в кэше: {len(new_items)}")

    if not new_items:
        log("Всё уже в кэше — выход")
        return

    processed = 0
    skipped_tracked = 0
    by_urgency = {"hot": 0, "warm": 0, "cold": 0}

    for item in new_items:
        # Дедупликация по SURVEILLANCE-CONFIG
        tracked_theme = is_already_tracked(item, tracked)
        if tracked_theme:
            write_record({
                "url": item["url"],
                "feed": item.get("_feed", "?"),
                "ts_item": item.get("ts", ""),
                "ts_triage": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "urgency": "cold",
                "type": "знание",
                "confidence": "high",
                "reason": f"already tracked: {tracked_theme}",
                "already_tracked": True,
            })
            skipped_tracked += 1
            continue

        result = keyword_triage(item)

        record = {
            "url": item["url"],
            "feed": item.get("_feed", "?"),
            "ts_item": item.get("ts", ""),
            "ts_triage": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "urgency": result["urgency"],
            "type": result["type"],
            "confidence": result["confidence"],
            "reason": result["reason"],
        }
        write_record(record)
        by_urgency[result["urgency"]] = by_urgency.get(result["urgency"], 0) + 1
        processed += 1

    log(f"Обработано: {processed}, tracked-skip: {skipped_tracked}")
    log(f"Распределение: hot={by_urgency.get('hot',0)} warm={by_urgency.get('warm',0)} cold={by_urgency.get('cold',0)}")

    # Статистика кэша
    all_cache = load_triage_cache()
    hot = sum(1 for v in all_cache.values() if v.get("urgency") == "hot")
    warm = sum(1 for v in all_cache.values() if v.get("urgency") == "warm")
    cold = sum(1 for v in all_cache.values() if v.get("urgency") == "cold")
    log(f"Кэш итого: {len(all_cache)} записей | hot={hot} warm={warm} cold={cold}")


if __name__ == "__main__":
    main()
