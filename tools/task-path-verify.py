#!/usr/bin/env python3
"""
task-path-verify.py — проверяет пути в файлах задач 1_Задачи/*.md

Находит все пути в bash-блоках и тексте задач, проверяет их существование.
Выводит отчёт + опционально пишет алерт в active-alerts.yaml.

Использование:
    python3 task-path-verify.py            # отчёт в stdout
    python3 task-path-verify.py --alert    # + записать в alerts если есть проблемы
    python3 task-path-verify.py --fix-hint # + показать подсказки по исправлению
"""

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Определяем vault
_VAULT_CANDIDATES = [
    Path.home() / "obsidian-backup",
    Path.home() / "obsidian-vault",
    Path.home() / "obsidian",
]
VAULT = next(
    (p for p in _VAULT_CANDIDATES if (p / "Дни").exists()),
    _VAULT_CANDIDATES[0]
)

TASKS_DIR   = VAULT / "1_Задачи"
ALERTS_FILE = Path.home() / "agentnet-pilot" / "alerts" / "active-alerts.yaml"

# Паттерны путей: ~/..., /home/..., /etc/..., /var/..., /data/...
PATH_RE = re.compile(
    r"(?:^|[\s`\"'(])("
    r"~\/[\w./-]+"
    r"|/home/\w+/[\w./-]+"
    r"|/etc/[\w./-]+"
    r"|/var/[\w./-]+"
    r"|/data/[\w./-]+"
    r"|/opt/[\w./-]+"
    r")"
    r"(?:[\s`\"')#\n]|$)"
)

# Статусы задач которые пропускаем
SKIP_STATUSES = {"done", "cancelled", "closed"}


def parse_frontmatter(text: str) -> dict:
    """Извлекает YAML frontmatter из markdown."""
    fm = {}
    if not text.startswith("---"):
        return fm
    end = text.find("---", 3)
    if end == -1:
        return fm
    for line in text[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def extract_paths(text: str) -> list[str]:
    """Извлекает все пути из текста (bash-блоки и обычный текст)."""
    paths = []
    for m in PATH_RE.finditer(text):
        p = m.group(1).rstrip("/.,;)")
        # Убираем суффиксы типа .csv, .py, .yaml если это файл (оставляем как есть)
        # Убираем shell-флаги случайно захваченные: -- не путь
        if p.startswith("-"):
            continue
        paths.append(p)
    return list(dict.fromkeys(paths))  # дедупликация с сохранением порядка


def resolve_path(p: str) -> Path:
    if p.startswith("~/"):
        return Path.home() / p[2:]
    return Path(p)


def check_task_file(md_file: Path) -> dict:
    """Возвращает: {file, title, paths_missing, paths_ok, skipped}."""
    text = md_file.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)

    status = fm.get("status", "").lower()
    if status in SKIP_STATUSES:
        return {"file": md_file, "skipped": True}

    title = md_file.stem
    paths = extract_paths(text)

    missing, ok = [], []
    for p in paths:
        resolved = resolve_path(p)
        # Проверяем parent-директорию или сам путь
        if resolved.exists():
            ok.append(p)
        elif resolved.parent.exists():
            # Файл не существует, но директория есть — возможно ещё не создан
            ok.append(p + "  *(dir exists)*")
        else:
            missing.append(p)

    return {
        "file": md_file,
        "title": title,
        "skipped": False,
        "assignee": fm.get("assignee", "?"),
        "status": status or "open",
        "paths_ok": ok,
        "paths_missing": missing,
    }


def find_actual_path(broken: str) -> str | None:
    """Ищет похожий путь в filesystem для подсказки fix-hint."""
    name = Path(broken.replace("~", str(Path.home()))).name
    search_dirs = [Path.home() / "health-monitor", Path.home() / "AI",
                   Path.home() / "agentnet-pilot", Path.home() / "tasks"]
    for d in search_dirs:
        if not d.exists():
            continue
        for found in d.rglob(name):
            return str(found).replace(str(Path.home()), "~")
    return None


def write_alert(broken_tasks: list[dict]) -> None:
    """Добавляет/обновляет алерт TASK-PATH-001 в active-alerts.yaml."""
    try:
        import yaml
    except ImportError:
        print("[alert] pyyaml не установлен, алерт не записан", file=sys.stderr)
        return

    ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"alerts": []}
    if ALERTS_FILE.exists():
        data = yaml.safe_load(ALERTS_FILE.read_text(encoding="utf-8")) or {"alerts": []}

    # Удаляем старый алерт если был
    data["alerts"] = [a for a in data["alerts"] if a.get("id") != "TASK-PATH-001"]

    summary = "; ".join(
        f"{t['title']} ({len(t['paths_missing'])} путей)"
        for t in broken_tasks
    )
    data["alerts"].append({
        "id": "TASK-PATH-001",
        "severity": "P3",
        "status": "open",
        "title": f"Битые пути в задачах: {len(broken_tasks)} файлов",
        "description": summary,
        "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "occurrences": 1,
    })

    ALERTS_FILE.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False),
                           encoding="utf-8")
    print(f"[alert] Записан TASK-PATH-001 в {ALERTS_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Проверка путей в задачах")
    parser.add_argument("--alert",    action="store_true", help="Записать в alerts если есть проблемы")
    parser.add_argument("--fix-hint", action="store_true", help="Показать подсказки по исправлению")
    parser.add_argument("--quiet",    action="store_true", help="Только итог, без деталей OK")
    args = parser.parse_args()

    if not TASKS_DIR.exists():
        print(f"Директория задач не найдена: {TASKS_DIR}")
        sys.exit(1)

    md_files = sorted(TASKS_DIR.glob("*.md"))
    results = [check_task_file(f) for f in md_files]

    checked  = [r for r in results if not r["skipped"]]
    skipped  = [r for r in results if r["skipped"]]
    broken   = [r for r in checked if r["paths_missing"]]
    clean    = [r for r in checked if not r["paths_missing"]]

    print(f"\n=== task-path-verify — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    print(f"Проверено: {len(checked)} задач | Пропущено (done/cancelled): {len(skipped)}")
    print(f"Чисто: {len(clean)} | Проблем: {len(broken)}\n")

    if broken:
        print("── БИТЫЕ ПУТИ ─────────────────────────────────────────────")
        for r in broken:
            print(f"\n  [{r['assignee']}] {r['title']}  ({r['file'].name})")
            for p in r["paths_missing"]:
                hint = ""
                if args.fix_hint:
                    actual = find_actual_path(p)
                    hint = f"  → попробуй: {actual}" if actual else "  → не найдено"
                print(f"    ✗ {p}{hint}")

    if not args.quiet and clean:
        print("\n── ОК ──────────────────────────────────────────────────────")
        for r in clean:
            if r["paths_ok"]:
                print(f"  ✓ {r['title']}: {len(r['paths_ok'])} путей")

    if broken and args.alert:
        write_alert(broken)

    sys.exit(1 if broken else 0)


if __name__ == "__main__":
    main()
