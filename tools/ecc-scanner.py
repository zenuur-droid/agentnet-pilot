#!/usr/bin/env python3
"""
ecc-scanner.py — автоматический сканер everything-claude-code репо.

Архитектура: двухступенчатый Claude API фильтр.
  1. Читает дату последнего обзора из latest.json
  2. Забирает новые коммиты с GitHub API
  3. Для значимых коммитов извлекает diff
  4. Ступень 1: Haiku — фильтр «полезен ли коммит?» (да/нет)
  5. Ступень 2: Sonnet — глубокий анализ прошедших фильтр → инсайт с action
  6. Пишет в latest.json → брифинг подхватит автоматически

Стоимость: ~$0.06/день (Haiku фильтр ~$0.01, Sonnet анализ ~$0.05)

Запуск: python3 ~/agentnet-pilot/tools/ecc-scanner.py
Cron:   0 6 * * *  (ежедневно 06:00 UTC)
Лог:    ~/logs/ecc-scanner.log
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# Добавляем ~/AI/tools/ в path для shared_env
sys.path.insert(0, str(Path.home() / "AI" / "tools"))
from shared_env import get_anthropic_key

REPOS = [
    "affaan-m/everything-claude-code",
    "anthropics/claude-code",
    "karpathy/autoresearch",
    "karpathy/nanochat",
]
GITHUB_API   = "https://api.github.com"
CLAUDE_API   = "https://api.anthropic.com/v1/messages"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-6"

OUTPUT_FILE  = Path.home() / "agentnet-pilot/feeds/ecc-insights/latest.json"
LOG_FILE     = Path.home() / "logs/ecc-scanner.log"

MAX_COMMITS_PER_REPO = 15  # не больше N коммитов за репозиторий
MAX_DIFF_CHARS       = 3000  # обрезаем большие диффы
MAX_INSIGHTS         = 7     # итоговых инсайтов в брифинге (было 5, теперь 4 репо)
MIN_PRIORITY         = "P3"  # P1/P2/P3 — P4 не включаем

SKIP_PATTERNS = ["fix:", "chore:", "docs:", "test:", "ci:", "style:", "refactor:"]


# ── Утилиты ───────────────────────────────────────────────────────────────────

def log(msg: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [ecc-scanner] {msg}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def gh_get(path: str) -> dict | list | None:
    url = f"{GITHUB_API}{path}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "ecc-scanner/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log(f"GitHub API error {path}: {e}")
        return None


def _get_api_key() -> str:
    return get_anthropic_key()


def _claude_call(model: str, system: str, user: str, max_tokens: int = 300) -> str:
    """Вызов Claude API. Возвращает текст ответа или пустую строку."""
    api_key = _get_api_key()
    if not api_key:
        log("API key не найден")
        return ""

    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()

    req = urllib.request.Request(
        CLAUDE_API,
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        return data["content"][0]["text"].strip()
    except Exception as e:
        log(f"Claude API error ({model}): {e}")
        return ""


def haiku_filter(commit_msg: str, diff: str) -> bool:
    """Ступень 1: Haiku решает — полезен ли коммит. Быстро и дёшево."""
    system = ("Ты фильтр коммитов. Определи: содержит ли коммит паттерн/практику "
              "полезную для мульти-агентной AI-системы на Claude Code "
              "(hooks, memory, prompts, agents, cost, config, safety). "
              "Ответь ОДНИМ словом: YES или NO.")
    user = f"Коммит: {commit_msg}\n\nИзменения:\n{diff[:1500]}"
    result = _claude_call(MODEL_HAIKU, system, user, max_tokens=5)
    passed = "YES" in result.upper()
    log(f"    Haiku filter: {'PASS' if passed else 'SKIP'}")
    return passed


def sonnet_extract(commit_msg: str, diff: str) -> dict | None:
    """Ступень 2: Sonnet извлекает структурированный инсайт с action."""
    system = ("Ты анализируешь коммиты из репозиториев с лучшими практиками Claude Code. "
              "Извлеки применимый паттерн для личной AI-системы с несколькими Claude Code агентами. "
              "Ответ ТОЛЬКО JSON на русском языке, без пояснений.")

    user = f"""Коммит: {commit_msg}

Изменения (фрагмент):
{diff[:MAX_DIFF_CHARS]}

Формат:
{{
  "title": "короткое название паттерна (5-7 слов)",
  "what": "что это такое (1-2 предложения)",
  "action": "КОНКРЕТНОЕ действие для внедрения — что именно создать/изменить/проверить (1 предложение, начинается с глагола)",
  "why": "какой результат получим (1-2 предложения)",
  "priority": "P1|P2|P3"
}}"""

    text = _claude_call(MODEL_SONNET, system, user, max_tokens=400)
    if not text:
        return None

    m = re.search(r'\{[\s\S]+\}', text)
    if not m:
        return None
    try:
        result = json.loads(m.group(0))
    except json.JSONDecodeError:
        log(f"    Sonnet: невалидный JSON")
        return None

    if not all(k in result for k in ("title", "what", "action", "why", "priority")):
        return None
    if not result.get("action", "").strip():
        return None
    return result


def is_significant(msg: str) -> bool:
    """Пропускаем служебные коммиты."""
    msg_lower = msg.lower()
    return not any(msg_lower.startswith(p) for p in SKIP_PATTERNS)


# ── Основная логика ────────────────────────────────────────────────────────────

def scan_repo(repo: str, since_str: str, seen_titles: set) -> list:
    """Сканирует один репозиторий, возвращает список инсайтов."""
    log(f"\n── Репо: {repo} ──")
    path = f"/repos/{repo}/commits?since={urllib.parse.quote(since_str)}&per_page={MAX_COMMITS_PER_REPO}"
    commits = gh_get(path)
    if not commits:
        log(f"  Нет коммитов или ошибка API")
        return []

    significant = [
        c for c in commits
        if is_significant(c["commit"]["message"].split("\n")[0])
    ]
    log(f"  Коммитов: {len(commits)}, значимых: {len(significant)}")

    if not significant:
        return []

    repo_insights = []
    for commit in significant:
        if len(repo_insights) >= MAX_COMMITS_PER_REPO:
            break

        sha = commit["sha"]
        msg = commit["commit"]["message"].split("\n")[0]
        log(f"  {sha[:8]} {msg[:50]}")

        detail = gh_get(f"/repos/{repo}/commits/{sha}")
        if not detail:
            continue

        diff_parts = []
        for f in detail.get("files", []):
            fname = f.get("filename", "")
            patch = f.get("patch", "")
            if patch and fname.endswith((".md", ".py", ".yaml", ".json", ".ts", ".js")):
                diff_parts.append(f"# {fname}\n{patch}")
        diff = "\n".join(diff_parts)

        if not diff.strip():
            continue

        # Ступень 1: Haiku фильтр (дёшево)
        if not haiku_filter(msg, diff):
            continue
        # Ступень 2: Sonnet анализ (качественно)
        insight = sonnet_extract(msg, diff)
        if insight is None:
            log(f"    → пропущен")
            continue

        title_key = insight["title"].lower()[:30]
        if title_key in seen_titles:
            log(f"    → дубликат: {insight['title']}")
            continue

        seen_titles.add(title_key)
        insight["commit_url"] = f"https://github.com/{repo}/commit/{sha}"
        insight["repo"] = repo
        repo_insights.append(insight)
        log(f"    → [{insight['priority']}]: {insight['title']}")

    return repo_insights


def main():
    # Читаем дату последнего обзора
    since_dt = None
    if OUTPUT_FILE.exists():
        try:
            data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
            since_dt = datetime.fromisoformat(data.get("reviewed_at", ""))
            log(f"Последний обзор: {since_dt.strftime('%Y-%m-%d')}")
        except Exception:
            pass

    if since_dt is None:
        from datetime import timedelta
        since_dt = datetime.now(timezone.utc) - timedelta(days=7)
        log("Первый запуск — берём последние 7 дней")

    since_str = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Сканируем все репозитории
    all_insights = []
    seen_titles = set()
    total_significant = 0

    for repo in REPOS:
        repo_insights = scan_repo(repo, since_str, seen_titles)
        all_insights.extend(repo_insights)
        total_significant += len(repo_insights)

    if not all_insights:
        log("Инсайтов не найдено — обновляем reviewed_at")
        _update_reviewed_at()
        sys.exit(0)

    # Сортируем по приоритету, обрезаем
    priority_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    all_insights.sort(key=lambda x: priority_order.get(x.get("priority", "P4"), 9))
    all_insights = all_insights[:MAX_INSIGHTS]

    # Сохраняем
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    repos_str = ", ".join(r.split("/")[1] for r in REPOS)
    result = {
        "reviewed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "sources": [f"https://github.com/{r}" for r in REPOS],
        "review_notes": f"Авто-скан {datetime.now().strftime('%Y-%m-%d')}: {len(REPOS)} репо ({repos_str}) → {len(all_insights)} инсайтов",
        "insights": all_insights,
    }
    OUTPUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"✅ Записано {len(all_insights)} инсайтов из {len(REPOS)} репозиториев")


def _update_reviewed_at():
    """Обновляет только дату обзора, инсайты не трогает."""
    if not OUTPUT_FILE.exists():
        return
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        data["reviewed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        data["review_notes"] = f"Авто-скан {datetime.now().strftime('%Y-%m-%d')}: нет новых инсайтов"
        OUTPUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"Ошибка обновления reviewed_at: {e}")


if __name__ == "__main__":
    main()
