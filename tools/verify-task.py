#!/usr/bin/env python3
"""
verify-task.py — приёмка задачи: verify + Haiku review.

Два этапа:
  1. Запуск bash-команд из verify: (frontmatter YAML или ```bash блок после ## Verify)
  2. Haiku сравнивает Progress vs Чеклист — всё ли сделано?

Использование:
  python3 verify-task.py <путь_к_задаче.md>
  python3 verify-task.py <путь_к_задаче.md> --no-haiku   # только verify без Haiku
  python3 verify-task.py <путь_к_задаче.md> --dry-run     # показать команды без запуска

Выход:
  0 — PASS (verify ok + Haiku ok)
  1 — FAIL (verify или Haiku нашли проблемы)
  2 — ERROR (файл не найден, нет verify секции, etc.)

Лог: ~/logs/verify-task.log
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / "logs" / "verify-task.log"
HARNESS_STATE = Path.home() / ".claude" / "harness-state.json"


def log(msg: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [verify-task] {msg}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")



def _parse_frontmatter(text: str) -> dict:
    """Парсит YAML frontmatter между --- ... ---"""
    m = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
    if not m:
        return {}
    # Простой парсер YAML для verify: list
    result = {}
    lines = m.group(1).split("\n")
    current_key = None
    current_list = []
    for line in lines:
        if re.match(r'^[a-z_]+:', line):
            if current_key and current_list:
                result[current_key] = current_list
            kv = line.split(":", 1)
            current_key = kv[0].strip()
            val = kv[1].strip()
            if val and not val.startswith("["):
                result[current_key] = val
                current_list = []
            else:
                current_list = []
        elif line.strip().startswith("- ") and current_key:
            current_list.append(line.strip()[2:])
    if current_key and current_list:
        result[current_key] = current_list
    return result


def _extract_verify_commands(text: str) -> list[str]:
    """Извлекает verify команды из frontmatter или ```bash блока после ## Verify."""
    # 1. Из frontmatter
    fm = _parse_frontmatter(text)
    if "verify" in fm and isinstance(fm["verify"], list):
        return fm["verify"]

    # 2. Из ```bash блока после ## Verify
    m = re.search(r'## Verify\s*\n+```bash\n(.*?)```', text, re.DOTALL)
    if m:
        cmds = []
        for line in m.group(1).strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                cmds.append(line)
        return cmds

    return []


def _extract_sections(text: str) -> dict:
    """Извлекает Чеклист и Progress из тела задачи."""
    sections = {}
    for name in ("Чеклист", "Progress"):
        m = re.search(rf'## {name}\s*\n(.*?)(?=\n## |\Z)', text, re.DOTALL)
        if m:
            sections[name] = m.group(1).strip()
    return sections


def run_verify(commands: list[str], dry_run: bool = False) -> tuple[int, int, list[str]]:
    """Запускает verify команды. Возвращает (pass_count, fail_count, details)."""
    passed = 0
    failed = 0
    details = []

    for i, cmd in enumerate(commands, 1):
        if dry_run:
            details.append(f"  [{i}] DRY-RUN: {cmd}")
            continue

        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30,
                cwd=str(Path.home()),
            )
            if r.returncode == 0:
                passed += 1
                details.append(f"  [{i}] PASS: {cmd}")
            else:
                failed += 1
                stderr = r.stderr.strip()[:100] if r.stderr else ""
                details.append(f"  [{i}] FAIL: {cmd}" + (f" ({stderr})" if stderr else ""))
        except subprocess.TimeoutExpired:
            failed += 1
            details.append(f"  [{i}] TIMEOUT: {cmd}")
        except Exception as e:
            failed += 1
            details.append(f"  [{i}] ERROR: {cmd} ({e})")

    return passed, failed, details


def haiku_review(task_text: str, verify_results: str) -> tuple[bool, str]:
    """Haiku через claude -p сравнивает Progress vs Чеклист."""
    sections = _extract_sections(task_text)
    checklist = sections.get("Чеклист", "(нет чеклиста)")
    progress = sections.get("Progress", "(нет прогресса)")

    prompt = f"""Ты приёмщик задач. Проверяешь: выполнена ли задача полностью?
Сравни Чеклист с Progress и результатами verify.
Ответь СТРОГО в формате:
VERDICT: PASS или FAIL
REASON: одно предложение почему
GAPS: список незакрытых пунктов (или 'нет')

## Чеклист
{checklist}

## Progress
{progress}

## Verify результаты
{verify_results}"""

    cmd = [
        "claude", "-p", prompt,
        "--model", "haiku",
        "--max-budget-usd", "0.10",
        "--output-format", "text",
        "--no-session-persistence",
    ]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=30, env=env,
        )
        if result.returncode != 0:
            return False, f"claude -p error (exit {result.returncode}): {result.stderr[:200]}"
        verdict_text = result.stdout.strip()
        clean = re.sub(r'[*_`]', '', verdict_text.upper())
        ok = "VERDICT: PASS" in clean or "VERDICT:PASS" in clean
        return ok, verdict_text
    except subprocess.TimeoutExpired:
        return False, "claude -p timeout (30s)"
    except FileNotFoundError:
        return False, "claude CLI не найден — установи Claude Code"
    except Exception as e:
        return False, f"Haiku error: {e}"


def _mark_verified(task_path: Path):
    """Записывает имя задачи в harness-state — гейт разрешит закрытие."""
    try:
        state = json.loads(HARNESS_STATE.read_text()) if HARNESS_STATE.exists() else {}
        verified = state.get("verified_tasks", [])
        basename = task_path.name
        if basename not in verified:
            verified.append(basename)
        state["verified_tasks"] = verified
        HARNESS_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        log(f"Marked verified: {basename}")
    except Exception as e:
        log(f"Warning: не удалось записать в harness-state: {e}")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Использование: verify-task.py <задача.md> [--no-haiku] [--dry-run]")
        sys.exit(2)

    task_path = Path(args[0]).expanduser()
    no_haiku = "--no-haiku" in args
    dry_run = "--dry-run" in args

    if not task_path.exists():
        log(f"ERROR: файл не найден: {task_path}")
        sys.exit(2)

    text = task_path.read_text(encoding="utf-8")
    task_name = task_path.stem

    log(f"{'='*60}")
    log(f"Приёмка: {task_name}")

    # Извлекаем verify команды
    commands = _extract_verify_commands(text)
    if not commands:
        log(f"ERROR: нет verify секции в {task_name}")
        sys.exit(2)

    log(f"Verify: {len(commands)} команд")

    # Этап 1: запуск verify
    passed, failed, details = run_verify(commands, dry_run)
    for d in details:
        log(d)

    if dry_run:
        log(f"DRY-RUN: {len(commands)} команд показано")
        sys.exit(0)

    verify_ok = failed == 0
    log(f"Verify: {passed} PASS, {failed} FAIL → {'PASS' if verify_ok else 'FAIL'}")

    if not verify_ok:
        log(f"РЕЗУЛЬТАТ: FAIL (verify {failed} ошибок)")
        sys.exit(1)

    # Этап 2: Haiku review
    if no_haiku:
        log(f"РЕЗУЛЬТАТ: PASS (verify {passed}/{passed}, Haiku пропущен)")
        _mark_verified(task_path)
        sys.exit(0)

    verify_summary = "\n".join(details)
    haiku_ok, verdict = haiku_review(text, verify_summary)
    log(f"Haiku: {verdict}")

    if haiku_ok:
        log(f"РЕЗУЛЬТАТ: PASS (verify {passed}/{passed}, Haiku PASS)")
        _mark_verified(task_path)
        sys.exit(0)
    else:
        log(f"РЕЗУЛЬТАТ: FAIL (verify PASS, Haiku FAIL)")
        sys.exit(1)


if __name__ == "__main__":
    main()
