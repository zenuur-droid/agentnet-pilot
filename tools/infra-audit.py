#!/usr/bin/env python3
"""
infra-audit.py — Проактивный ежедневный аудит инфраструктуры.

Уровень 1: Повторяющиеся проблемы в session logs (3+ упоминаний за 7 дней = P1)
Уровень 2: Sync-скрипты (порядок команд, запрещённые флаги), размер папок vault,
           застрявшие git-операции, состояние сервисов
Уровень 3: Git-конфиги на всех машинах (pull.rebase, pull.ff)

Результат: P1/P2 сигналы в signals.yaml → автоматически попадают в smart_briefing().

Запуск:
  python3 ~/agentnet-pilot/tools/infra-audit.py
  python3 ~/agentnet-pilot/tools/infra-audit.py --verbose
"""

import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import yaml

# ── Пути ────────────────────────────────────────────────────────────────────

VAULT        = Path.home() / "obsidian-backup"
SIGNALS_FILE = VAULT / "AI" / "Claude Code" / "signals.yaml"
KEDB_FILE    = Path.home() / "tasks" / "known-errors.yaml"

SESSION_LOG_DIRS = [
    VAULT / "AI" / "Claude Code" / "Mac",
    VAULT / "AI" / "Claude Code" / "Linux",
    VAULT / "AI" / "Claude Code" / "Laptop",
    VAULT / "AI" / "Claude Code" / "Claudian",
]

SYNC_SCRIPTS_LOCAL = {
    "mac": Path.home() / "obsidian-sync.sh",
}

VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv

# ── Утилиты ─────────────────────────────────────────────────────────────────

def log(msg: str):
    if VERBOSE:
        print(msg)


def ssh(host: str, cmd: str, timeout: int = 10) -> tuple[int, str]:
    """Выполняет команду по SSH. Возвращает (returncode, stdout+stderr)."""
    try:
        r = subprocess.run(
            ["ssh", "-o", f"ConnectTimeout={timeout}", "-o", "BatchMode=yes", host, cmd],
            capture_output=True, text=True, timeout=timeout + 2
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -1, str(e)


def write_signal(source: str, category: str, priority: str, message: str):
    """Добавляет сигнал в signals.yaml (дедупликация по source+message)."""
    data = {}
    if SIGNALS_FILE.exists():
        try:
            data = yaml.safe_load(SIGNALS_FILE.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}

    signals = data.get("signals", [])

    # Дедупликация: не дублируем тот же сигнал если уже есть new
    for s in signals:
        if s.get("source") == source and s.get("message") == message and s.get("status") == "new":
            log(f"  [skip dup] {priority} {message[:60]}")
            return

    signals.append({
        "source":    source,
        "category":  category,
        "priority":  priority,
        "message":   message,
        "status":    "new",
        "created":   datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    data["signals"] = signals

    SIGNALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SIGNALS_FILE.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8"
    )
    print(f"  → [{priority}] {message[:80]}")


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 1: Повторяющиеся проблемы в session logs
# ══════════════════════════════════════════════════════════════════════════════

# Паттерны для поиска. (regex, human-readable name, threshold_days, min_hits, priority)
RECURRING_PATTERNS = [
    (
        r"5_люди|папку люди|засрали|посторонн.*заметк|чужие.*заметк",
        "Засорение 5_Люди посторонними файлами",
        7, 2, "P1"
    ),
    (
        r"20\s*000\s*токен|токен.*на ветер|чудовищно.*токен|трата токен",
        "Чрезмерный расход токенов (>20K за задачу)",
        14, 2, "P2"
    ),
    (
        r"туннель упал|tunnel.*down|api.*недоступ|api.*не работ|connect.*timeout.*anthropic",
        "Недоступность Anthropic API / туннель",
        7, 3, "P1"
    ),
    (
        r"git.*rebase|rebase.*откатил|rebase.*вернул|отменил.*коммит",
        "Использование git rebase (запрещено в vault)",
        14, 1, "P2"
    ),
    (
        r"файл.*вернул|вернул.*файл|снова.*появил|опять.*появил|восстановил.*файл",
        "Файлы возвращаются после удаления (git sync)",
        7, 2, "P1"
    ),
    (
        r"не смог удалить|не могу удалить|bash.*заблокирован|rm.*запрещ",
        "Claudian не может удалить файлы (Bash ограничен)",
        14, 2, "P2"
    ),
    (
        r"vpn.*не поднял|vpn.*упал|amnezia.*не запуст|amnezia.*crash",
        "Amnezia VPN падает при старте Linux",
        7, 2, "P2"
    ),
    (
        r"опять|снова|в который раз|уже .*(раз|делали|было|решали)",
        "Общий паттерн повторения проблемы",
        7, 5, "P2"
    ),
]


def scan_session_logs(days: int = 7) -> dict[str, list[tuple[str, str]]]:
    """
    Сканирует ежедневные логи за последние N дней.
    Возвращает {pattern_name: [(date, snippet), ...]}
    """
    cutoff = datetime.now() - timedelta(days=days)
    hits: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for log_dir in SESSION_LOG_DIRS:
        if not log_dir.exists():
            continue
        for f in sorted(log_dir.glob("20??-??-??.md")):
            try:
                date = datetime.strptime(f.stem, "%Y-%m-%d")
            except ValueError:
                continue
            if date < cutoff:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace").lower()
            except Exception:
                continue

            for pattern, name, _, _, _ in RECURRING_PATTERNS:
                m = re.search(pattern, text)
                if m:
                    start = max(0, m.start() - 30)
                    snippet = text[start:m.end() + 50].replace("\n", " ").strip()
                    hits[name].append((f.stem, snippet[:100]))

    return hits


def check_level1_recurring():
    """Уровень 1: детектор повторяющихся проблем."""
    print("\n📋 Уровень 1: Повторяющиеся проблемы в логах...")
    hits = scan_session_logs(days=14)

    found_any = False
    for pattern, name, threshold_days, min_hits, priority in RECURRING_PATTERNS:
        occurrences = hits.get(name, [])
        # Фильтруем по threshold_days
        cutoff = datetime.now() - timedelta(days=threshold_days)
        recent = [(d, s) for d, s in occurrences
                  if datetime.strptime(d, "%Y-%m-%d") >= cutoff]

        if len(recent) >= min_hits:
            found_any = True
            dates = sorted(set(d for d, _ in recent))
            msg = (f"[L1] Повторяется {len(recent)}× за {threshold_days}д: «{name}» "
                   f"(даты: {', '.join(dates[-3:])})")
            write_signal("infra-audit/L1", "recurring_problem", priority, msg)
        else:
            log(f"  ✅ {name}: {len(recent)} упоминаний (порог {min_hits}) — OK")

    if not found_any:
        print("  ✅ Повторяющихся проблем не обнаружено")


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 2: Инфраструктурные проверки
# ══════════════════════════════════════════════════════════════════════════════

# Паттерны ПРАВИЛЬНОГО порядка в sync-скриптах
CORRECT_ORDER_RE  = re.compile(
    r'(git add|git commit|git status).*\n.*git pull',
    re.DOTALL | re.IGNORECASE
)
WRONG_ORDER_RE    = re.compile(r'git pull.*--rebase', re.IGNORECASE)
ANY_REBASE_RE     = re.compile(r'git pull\s+--rebase', re.IGNORECASE)


def _check_sync_script_content(name: str, content: str) -> list[str]:
    """Возвращает список найденных нарушений в тексте sync-скрипта."""
    issues = []

    # Нарушение 1: запрещённый --rebase
    if ANY_REBASE_RE.search(content):
        issues.append(f"запрещённый 'git pull --rebase' в {name}")

    # Нарушение 2: pull ДО commit (неправильный порядок)
    lines = [l.strip() for l in content.splitlines() if l.strip() and not l.strip().startswith('#')]
    pull_idx   = next((i for i, l in enumerate(lines) if re.search(r'git pull', l, re.I)), None)
    commit_idx = next((i for i, l in enumerate(lines) if re.search(r'git commit', l, re.I)), None)

    if pull_idx is not None and commit_idx is not None:
        if pull_idx < commit_idx:
            issues.append(f"неверный порядок в {name}: pull ({pull_idx}) перед commit ({commit_idx})")

    return issues


def check_sync_scripts():
    """Уровень 2: проверка sync-скриптов на Mac, Linux, Windows."""
    print("\n🔧 Уровень 2: Проверка sync-скриптов...")

    # Mac (локально)
    mac_script = Path.home() / "obsidian-sync.sh"
    if mac_script.exists():
        content = mac_script.read_text(encoding="utf-8")
        issues = _check_sync_script_content("obsidian-sync.sh (Mac)", content)
        if issues:
            for issue in issues:
                write_signal("infra-audit/L2/sync", "sync_script", "P1", f"[L2] {issue}")
        else:
            log("  ✅ Mac obsidian-sync.sh: OK")
    else:
        write_signal("infra-audit/L2/sync", "sync_script", "P2",
                     "[L2] Mac: obsidian-sync.sh не найден!")

    # Linux (via SSH)
    rc, content = ssh("linux", "cat ~/AI/tools/obsidian-sync.sh 2>/dev/null")
    if rc == 0 and content:
        issues = _check_sync_script_content("obsidian-sync.sh (Linux)", content)
        if issues:
            for issue in issues:
                write_signal("infra-audit/L2/sync", "sync_script", "P1", f"[L2] {issue}")
        else:
            log("  ✅ Linux obsidian-sync.sh: OK")
    else:
        write_signal("infra-audit/L2/sync", "sync_script", "P2",
                     "[L2] Linux: не удалось прочитать obsidian-sync.sh")

    # Windows (via SSH to laptop)
    rc, content = ssh("laptop", "type C:\\Users\\Admin\\obsidian-sync.ps1 2>nul", timeout=15)
    if rc == 0 and content:
        issues = _check_sync_script_content("obsidian-sync.ps1 (Windows)", content)
        if issues:
            for issue in issues:
                write_signal("infra-audit/L2/sync", "sync_script", "P1", f"[L2] {issue}")
        else:
            log("  ✅ Windows obsidian-sync.ps1: OK")
    else:
        log("  ⚠️  Windows: ноутбук недоступен (пропускаем)")


def check_vault_folder_sizes():
    """Уровень 2: мониторинг размеров проблемных папок vault."""
    print("\n📁 Уровень 2: Размеры папок vault...")

    # 5_Люди — не должна расти (бот отключён от создания там файлов)
    lyudi_dir = VAULT / "5_Люди"
    if lyudi_dir.exists():
        files = list(lyudi_dir.glob("*.md"))
        count = len(files)
        log(f"  5_Люди/: {count} файлов")

        # Сравниваем с baseline из KEDB
        baseline = _read_kedb_baseline("5_Люди_count")
        if baseline is None:
            _write_kedb_baseline("5_Люди_count", count)
            log(f"  5_Люди/: baseline установлен = {count}")
        elif count > baseline + 2:
            write_signal(
                "infra-audit/L2/vault", "vault_folder", "P1",
                f"[L2] 5_Люди/ выросла: {baseline} → {count} файлов "
                f"(+{count - baseline}) — возможно бот снова пишет туда"
            )
        elif count > baseline:
            write_signal(
                "infra-audit/L2/vault", "vault_folder", "P2",
                f"[L2] 5_Люди/ незначительно выросла: {baseline} → {count} файлов"
            )
        else:
            log(f"  ✅ 5_Люди/: {count} файлов (baseline {baseline}) — OK")

    # 168Bot — должна расти (бот в simple mode пишет сюда)
    bot_dir = VAULT / "168Bot"
    if bot_dir.exists():
        count = len(list(bot_dir.glob("*.md")))
        log(f"  ✅ 168Bot/: {count} файлов (активный)")


def check_git_stuck_operations():
    """Уровень 2: проверка застрявших git операций."""
    print("\n🔀 Уровень 2: Застрявшие git операции...")

    checks = [
        ("Mac",    str(VAULT),                          None,    "local"),
        ("Linux",  "/home/oleg/obsidian-vault",         "linux", "ssh"),
        ("Linux2", "/home/oleg/obsidian-backup/.git",   "linux", "ssh_git_dir"),
    ]

    for name, path, host, mode in checks:
        if mode == "local":
            rebase_dir = Path(path) / ".git" / "rebase-merge"
            merge_head = Path(path) / ".git" / "MERGE_HEAD"
            cherry_dir = Path(path) / ".git" / "rebase-apply"
            stuck = []
            if rebase_dir.exists():
                stuck.append("rebase-merge (interactive rebase)")
            if merge_head.exists():
                stuck.append("MERGE_HEAD (незавершённый merge)")
            if cherry_dir.exists():
                stuck.append("rebase-apply (am/rebase)")
        elif mode == "ssh":
            rc, out = ssh(host, f"ls {path}/.git/rebase-merge {path}/.git/MERGE_HEAD 2>/dev/null")
            stuck = [f for f in ["rebase-merge", "MERGE_HEAD"] if f in out]
        elif mode == "ssh_git_dir":
            # obsidian-backup имеет отдельный .git dir
            rc, out = ssh(host,
                f"ls {path}/rebase-merge {path}/MERGE_HEAD 2>/dev/null")
            stuck = [f for f in ["rebase-merge", "MERGE_HEAD"] if f in out]
        else:
            stuck = []

        if stuck:
            write_signal(
                "infra-audit/L2/git", "git_stuck", "P1",
                f"[L2] {name}: застрявшая git операция: {', '.join(stuck)} — "
                f"требует ручного 'git rebase --abort' или 'git merge --abort'"
            )
        else:
            log(f"  ✅ {name} git: чисто")


def check_bot_status():
    """Уровень 2: убеждаемся что бот в simple mode (не пишет в 5_Люди)."""
    print("\n🤖 Уровень 2: Статус бота (Telegram 168Bot)...")
    rc, out = ssh("linux",
        "grep -n 'resolved_entities = \\[\\]\\|# DISABLED\\|process_entities' "
        "~/AI/telegram-voice-notes/src/telegram_bot.py 2>/dev/null | head -5",
        timeout=15
    )
    if rc == 0 and "resolved_entities = []" in out:
        log("  ✅ Бот: simple mode подтверждён (resolved_entities = [])")
    elif rc == 0:
        write_signal(
            "infra-audit/L2/bot", "bot_status", "P2",
            "[L2] Бот: 'resolved_entities = []' не найден — возможно entity processing включён снова"
        )
    else:
        log("  ⚠️  Linux недоступен для проверки бота")


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 3: Git-конфиги на всех машинах
# ══════════════════════════════════════════════════════════════════════════════

# Эталонные значения
GIT_REQUIRED = {
    "pull.rebase": "false",   # НЕ должен быть true
}
# pull.ff=only желательно, но при --no-rebase это уже не критично (P3)


def _get_git_config(host: str | None, key: str, git_dir: str | None = None) -> str:
    """Читает git config. host=None = локально."""
    if git_dir:
        cmd = f"git --git-dir={git_dir} config --get {key} 2>/dev/null || echo NOT_SET"
    else:
        cmd = f"git config --global --get {key} 2>/dev/null || git config --get {key} 2>/dev/null || echo NOT_SET"

    if host is None:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
            return r.stdout.strip()
        except Exception:
            return "ERROR"
    else:
        rc, out = ssh(host, cmd)
        return out.strip() if rc == 0 else "ERROR"


def check_git_configs():
    """Уровень 3: аудит git-конфигов на всех машинах."""
    print("\n⚙️  Уровень 3: Git-конфиги...")

    machines = [
        ("Mac (local)",  None,     str(VAULT / ".git")),
        ("Linux vault",  "linux",  "/home/oleg/obsidian-vault/.git"),
        ("Linux backup", "linux",  "/home/oleg/obsidian-backup/.git"),
    ]

    for name, host, git_dir in machines:
        for key, expected in GIT_REQUIRED.items():
            value = _get_git_config(host, key, git_dir)
            if value in ("NOT_SET", ""):
                # Не задан явно — pull.rebase по умолчанию false в git, но лучше явно
                log(f"  ⚠️  {name}: {key} не задан (default=false — OK)")
            elif value == "ERROR":
                log(f"  ⚠️  {name}: не удалось проверить {key}")
            elif value.lower() != expected:
                write_signal(
                    "infra-audit/L3/git-config", "git_config", "P1",
                    f"[L3] {name}: {key}={value} (ожидалось {expected}) — "
                    f"риск потери пользовательских изменений при git pull"
                )
            else:
                log(f"  ✅ {name}: {key}={value}")

    # Laptop — отдельно (Windows может быть выключен)
    rc, val = ssh("laptop",
        "git -C C:/Users/Admin/ObsidianVault config pull.rebase 2>nul || echo NOT_SET",
        timeout=15)
    if rc == 0:
        val = val.strip()
        if val not in ("", "NOT_SET", "false"):
            write_signal(
                "infra-audit/L3/git-config", "git_config", "P1",
                f"[L3] Windows vault: pull.rebase={val} (ожидалось false)"
            )
        else:
            log(f"  ✅ Windows vault: pull.rebase={val or 'NOT_SET (default false)'}")
    else:
        log("  ⚠️  Windows: ноутбук недоступен (пропускаем)")


# ══════════════════════════════════════════════════════════════════════════════
# KEDB baseline helpers
# ══════════════════════════════════════════════════════════════════════════════

BASELINE_FILE = Path.home() / "tasks" / "infra-baselines.yaml"


def _read_kedb_baseline(key: str):
    if not BASELINE_FILE.exists():
        return None
    try:
        data = yaml.safe_load(BASELINE_FILE.read_text(encoding="utf-8")) or {}
        return data.get(key)
    except Exception:
        return None


def _write_kedb_baseline(key: str, value):
    data = {}
    if BASELINE_FILE.exists():
        try:
            data = yaml.safe_load(BASELINE_FILE.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    data[key] = value
    data[f"{key}_updated"] = datetime.now().strftime("%Y-%m-%d")
    BASELINE_FILE.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Обновление KEDB
# ══════════════════════════════════════════════════════════════════════════════

def update_kedb_with_signals():
    """
    Если есть открытые P1 сигналы от infra-audit — проверяем есть ли
    соответствующая запись в KEDB. Если нет — предупреждаем.
    """
    if not SIGNALS_FILE.exists() or not KEDB_FILE.exists():
        return

    try:
        signals = yaml.safe_load(SIGNALS_FILE.read_text(encoding="utf-8")) or {}
        kedb    = yaml.safe_load(KEDB_FILE.read_text(encoding="utf-8")) or []
    except Exception:
        return

    new_p1 = [s for s in signals.get("signals", [])
               if s.get("source", "").startswith("infra-audit")
               and s.get("priority") == "P1"
               and s.get("status") == "new"]

    kedb_problems = [ke.get("problem", "").lower() for ke in (kedb or [])]

    for sig in new_p1:
        msg = sig.get("message", "")
        # Простая эвристика: есть ли похожая проблема в KEDB
        keywords = re.findall(r'\b\w{5,}\b', msg.lower())[:4]
        covered = any(any(kw in problem for kw in keywords) for problem in kedb_problems)
        if not covered:
            log(f"  ⚠️  KEDB: нет записи для P1 '{msg[:60]}' — добавь вручную")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"🔍 infra-audit.py — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    check_level1_recurring()
    check_sync_scripts()
    check_vault_folder_sizes()
    check_git_stuck_operations()
    check_bot_status()
    check_git_configs()
    update_kedb_with_signals()

    # Итог
    if SIGNALS_FILE.exists():
        try:
            data  = yaml.safe_load(SIGNALS_FILE.read_text(encoding="utf-8")) or {}
            new_p = [s for s in data.get("signals", [])
                     if s.get("status") == "new"
                     and s.get("source", "").startswith("infra-audit")]
            p1 = sum(1 for s in new_p if s.get("priority") == "P1")
            p2 = sum(1 for s in new_p if s.get("priority") == "P2")
            if new_p:
                print(f"\n⚠️  Записано {len(new_p)} новых сигналов: P1={p1}, P2={p2}")
                print("   → Появятся в следующем smart_briefing()")
            else:
                print("\n✅ Инфраструктура чиста — новых сигналов нет")
        except Exception:
            pass

    print("=" * 60)


if __name__ == "__main__":
    main()
