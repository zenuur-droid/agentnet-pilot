#!/usr/bin/env python3
"""
AgentNet Telemetry Logger

Автодетект агента по hostname:
  macdevs-imac  → @oleg-mac
  oleg-ms-7c91  → @oleg-linux
  laptop-*      → @oleg-win

Usage:
  python3 log-telemetry.py --task debugging --exchanges 12 --success true
  python3 log-telemetry.py --task new_feature --exchanges 8 --success true --skill @oleg/pdca-loop
  python3 log-telemetry.py --task research --exchanges 5 --success false --notes "причина"
"""

import argparse
import json
import platform
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent
TASK_TYPES = ["debugging", "new_feature", "refactoring", "research", "writing", "config", "other"]

HOSTNAME_MAP = {
    "macdevs-imac":  "oleg-mac",
    "oleg-ms-7c91":  "oleg-linux",
}


def git(cmd, cwd=REPO_DIR):
    result = subprocess.run(["git"] + cmd, cwd=cwd, capture_output=True, text=True)
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def detect_agent() -> str:
    hostname = socket.gethostname().lower()
    node     = platform.node().lower()

    for h, agent in HOSTNAME_MAP.items():
        if h in hostname or h in node:
            return agent

    if "laptop" in hostname or "laptop" in node or platform.system() == "Windows":
        return "oleg-win"

    agents_dir = REPO_DIR / "agents"
    if agents_dir.exists():
        agent_dirs = [d.name for d in agents_dir.iterdir()
                      if d.is_dir() and d.name.startswith("oleg-")]
        if len(agent_dirs) == 1:
            return agent_dirs[0]

    return "oleg-mac"


def main():
    parser = argparse.ArgumentParser(description="AgentNet: log task telemetry")
    parser.add_argument("--agent", default=None)
    parser.add_argument("--task", choices=TASK_TYPES, required=True)
    parser.add_argument("--exchanges", type=int, required=True)
    parser.add_argument("--success", type=lambda x: x.lower() in ("true", "1", "yes"), required=True)
    parser.add_argument("--skill", default=None)
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    agent    = args.agent or detect_agent()
    agent_id = f"@{agent}"
    skill    = args.skill if args.skill and args.skill.lower() not in ("none", "null", "") else None

    record = {
        "ts":         datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent_id":   agent_id,
        "task_type":  args.task,
        "skill_used": skill,
        "applied":    skill is not None,
        "exchanges":  args.exchanges,
        "success":    args.success,
    }
    if args.notes:
        record["notes"] = args.notes[:256]

    telemetry_path = REPO_DIR / "agents" / agent / "telemetry" / "telemetry.jsonl"
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)

    with open(telemetry_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    status    = "✓" if args.success else "✗"
    skill_str = f" | skill: {skill}" if skill else ""
    print(f"AgentNet: {status} {args.task} | {args.exchanges} обменов | {agent_id}{skill_str}")

    ok, _, err = git(["pull", "--ff-only"])
    if not ok:
        print(f"  ⚠ pull не удался ({err}) — запись сохранена локально")
        return

    git(["add", str(telemetry_path)])

    commit_msg = f"telemetry: {agent} {args.task} ex={args.exchanges} {status}"
    if skill:
        commit_msg += f" [{skill.split('/')[-1]}]"

    ok, out, _ = git(["commit", "-m", commit_msg])
    if not ok or "nothing to commit" in out:
        return

    ok, _, err = git(["push"])
    if not ok:
        print(f"  ⚠ push не удался ({err}) — закоммичено локально")


if __name__ == "__main__":
    main()
