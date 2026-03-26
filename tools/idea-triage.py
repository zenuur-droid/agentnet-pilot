#!/usr/bin/env python3
"""
idea-triage.py — Idea Triage Agent.

ПРИНЦИП: агент НЕ удаляет — только маркирует.
         Идеи с low-confidence помечаются ⚠️ для человека.
         Все идеи попадают в брифинг — изменяется только порядок и метки.

Читает: signals.jsonl, ideas.jsonl (последние 3 дня)
        SURVEILLANCE-CONFIG.md (tracked topics для дедупликации)
Пишет: feeds/triage-cache.jsonl  (url → {urgency, type, confidence})
Запуск: cron 06:15 (после rss-collector 06:00, до daily-inject 06:30)

Urgency: hot | warm | cold
Type:    инфра | клод | бизнес | знание | шум
Confidence: high | low
"""

import json
import re
import time
import fcntl
import urllib.request
import urllib.error
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

OLLAMA_URL   = "http://localhost:11434/api/generate"
MODEL        = "mistral-nemo:12b"
DAYS_BACK    = 3   # обрабатываем только свежие
BATCH_SIZE   = 50  # максимум за один запуск

PROMPT_TEMPLATE = """Ты — фильтр идей для AI-агента. Оцени идею по трём осям.

ИДЕЯ:
{text}

Ответь ТОЛЬКО JSON, без пояснений:
{{
  "urgency": "hot|warm|cold",
  "type": "инфра|клод|бизнес|знание|шум",
  "confidence": "high|low",
  "reason": "одна фраза почему"
}}

Правила:
- hot = нужно действовать на этой неделе
- warm = полезно в течение месяца
- cold = интересно но не срочно
- шум = не применимо, общеизвестно или реклама
- confidence=low если идея нетривиальная/специфическая и ты не уверен в оценке
  (лучше пометить low, чем неверно отфильтровать ценную идею)
"""


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
    """Парсит SURVEILLANCE-CONFIG.md → tracked topics с задачами (T-088)."""
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
        # 2+ совпадения, или 1 из 1 ключевого слова
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
    """Формирует текст для Ollama из полей записи."""
    parts = []
    if item.get("topic"):
        parts.append(f"Тема: {item['topic']}")
    if item.get("signal"):
        parts.append(f"Сигнал: {item['signal']}")
    if item.get("pattern"):
        parts.append(f"Паттерн: {item['pattern']}")
    if item.get("insight"):
        parts.append(f"Инсайт: {item['insight']}")
    if item.get("title_original"):
        parts.append(f"Заголовок: {item['title_original']}")
    return "\n".join(parts) or item.get("url", "")


def ollama_triage(text: str) -> dict | None:
    prompt = PROMPT_TEMPLATE.format(text=text[:800])  # limit context
    payload = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 120},
    }).encode()

    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            raw = data.get("response", "").strip()
            # Извлечь JSON из ответа
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return None
            result = json.loads(m.group())
            # Валидация полей
            if result.get("urgency") not in ("hot", "warm", "cold"):
                result["urgency"] = "cold"
            if result.get("confidence") not in ("high", "low"):
                result["confidence"] = "low"
            return result
    except Exception as e:
        log(f"Ollama error: {e}")
        return None


def main():
    log("Запуск idea-triage")
    cache = load_triage_cache()
    items = load_recent_items()
    tracked = load_tracked_topics()

    new_items = [i for i in items if i.get("url") and i["url"] not in cache]
    log(f"Всего свежих: {len(items)}, не в кэше: {len(new_items)}")

    if not new_items:
        log("Всё уже в кэше — выход")
        return

    # Приоритет: relevant_to_oleg первыми (они попадут в брифинг)
    relevant_first = sorted(new_items, key=lambda i: (0 if i.get("relevant_to_oleg") else 1))
    to_process = relevant_first[:BATCH_SIZE]
    processed = 0
    skipped_tracked = 0
    errors = 0

    for item in to_process:
        # T-088: дедупликация по SURVEILLANCE-CONFIG
        tracked_theme = is_already_tracked(item, tracked)
        if tracked_theme:
            record = {
                "url": item["url"],
                "feed": item.get("_feed", "?"),
                "ts_item": item.get("ts", ""),
                "ts_triage": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "urgency": "cold",
                "type": "знание",
                "confidence": "high",
                "reason": f"already tracked: {tracked_theme}",
                "already_tracked": True,
            }
            with open(TRIAGE_CACHE, "a", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                fcntl.flock(f, fcntl.LOCK_UN)
            skipped_tracked += 1
            continue

        text = build_text(item)
        result = ollama_triage(text)
        if result is None:
            # Если Ollama не ответил — помечаем low confidence warm
            result = {"urgency": "warm", "type": "знание",
                      "confidence": "low", "reason": "ollama timeout"}
            errors += 1

        record = {
            "url": item["url"],
            "feed": item.get("_feed", "?"),
            "ts_item": item.get("ts", ""),
            "ts_triage": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "urgency": result.get("urgency", "cold"),
            "type": result.get("type", "знание"),
            "confidence": result.get("confidence", "low"),
            "reason": result.get("reason", ""),
        }
        with open(TRIAGE_CACHE, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)
        processed += 1
        time.sleep(0.3)  # не перегружать Ollama

    log(f"Обработано: {processed}, tracked-skip: {skipped_tracked}, ошибок: {errors}")

    # Статистика кэша
    all_cache = load_triage_cache()
    hot = sum(1 for v in all_cache.values() if v.get("urgency") == "hot")
    warm = sum(1 for v in all_cache.values() if v.get("urgency") == "warm")
    cold = sum(1 for v in all_cache.values() if v.get("urgency") == "cold")
    low_conf = sum(1 for v in all_cache.values() if v.get("confidence") == "low")
    log(f"Кэш: {len(all_cache)} записей | hot={hot} warm={warm} cold={cold} low_conf={low_conf}")


if __name__ == "__main__":
    main()
