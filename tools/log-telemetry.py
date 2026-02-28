#!/usr/bin/env python3
"""
AgentNet Telemetry Logger

Логирует результат задачи в telemetry.jsonl и пушит в общий репо.
Вызывается автоматически Claude Code в конце каждой нетривиальной задачи.

Участник ничего не делает вручную — всё происходит само.

Usage:
  python3 log-telemetry.py --task debugging --exchanges 12 --success true
  python3 log-telemetry.py --task new_feature --exchanges 8 --success true --pattern @oleg/pdca-loop
  python3 log-telemetry.py --task research --exchanges 5 --success true --notes "паттерн не подходил"
"""

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent
TASK_TYPES = ["debugging", "new_feature", "refactoring", "research", "writing", "config", "other"]


def git(cmd, cwd=REPO_DIR):
    result = subprocess.run(["git"] + cmd, cwd=cwd, capture_output=True, text=True)
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def detect_agent_name():
    """Определяет имя агента из папки agents/ в репо."""
    agents_dir = REPO_DIR / "agents"
    if not agents_dir.exists():
        return None
    candidates = [d.name for d in agents_dir.iterdir() if d.is_dir()]
    return candidates[0] if len(candidates) == 1 else None


def main():
    parser = argparse.ArgumentParser(
        description="AgentNet: log task telemetry (called automatically by Claude)"
    )
    parser.add_argument("--agent", default=None,
                        help="Agent name (auto-detected from agents/ folder)")
    parser.add_argument("--task", choices=TASK_TYPES, required=True,
                        help=f"Task type: {', '.join(TASK_TYPES)}")
    parser.add_argument("--exchanges", type=int, required=True,
                        help="Number of conversation exchanges")
    parser.add_argument("--success", type=lambda x: x.lower() in ("true", "1", "yes"),
                        required=True, help="Task completed successfully? (true/false)")
    parser.add_argument("--pattern", default=None,
                        help="Pattern used from network, e.g. @oleg/pdca-loop (omit if none)")
    parser.add_argument("--notes", default=None,
                        help="Optional notes about why pattern helped or didn't")
    args = parser.parse_args()

    # Определяем агента
    agent = args.agent or detect_agent_name()
    if not agent:
        print("❌ Не удалось определить имя агента. Укажи --agent <name>", file=sys.stderr)
        sys.exit(1)

    pattern = args.pattern if args.pattern and args.pattern.lower() != "none" else None

    record = {
        "date": date.today().isoformat(),
        "task_type": args.task,
        "pattern_used": pattern,
        "applied": pattern is not None,
        "exchanges": args.exchanges,
        "success": args.success,
    }
    if args.notes:
        record["notes"] = args.notes

    # Пишем в telemetry.jsonl
    telemetry_path = REPO_DIR / "agents" / agent / "telemetry" / "telemetry.jsonl"
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)

    with open(telemetry_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    status = "✓" if args.success else "✗"
    pat_str = f" | паттерн: {pattern}" if pattern else ""
    print(f"AgentNet: {status} {args.task} | {args.exchanges} обменов{pat_str}")

    # Синк с репо
    ok, _, err = git(["pull", "--ff-only"])
    if not ok:
        print(f"  ⚠ pull не удался ({err}) — запись сохранена локально, пуш позже")
        return

    git(["add", str(telemetry_path)])

    commit_msg = f"telemetry: {agent} {args.task} ex={args.exchanges} {status}"
    if pattern:
        commit_msg += f" pattern={pattern.split('/')[-1]}"

    ok, _, _ = git(["commit", "-m", commit_msg])
    if not ok:
        return  # нечего коммитить

    ok, _, err = git(["push"])
    if not ok:
        print(f"  ⚠ push не удался ({err}) — закоммичено локально")


if __name__ == "__main__":
    main()
