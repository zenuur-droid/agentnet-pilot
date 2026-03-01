#!/usr/bin/env python3
"""
idea-to-proposal.py — Автономный агент RSS-driven Pain Resolution.

Читает свежие claude-ideas из RSS-фидов + текущие боли (known-errors.yaml),
сопоставляет через Haiku, генерирует готовые предложения по реализации.

Результат пишет в pending-claude-hypotheses.md — подхватывается при старте
следующей сессии через system-signals MCP (get_startup_checklist).

Запуск: автоматически из daily-inject LaunchAgent (каждые 10 мин),
        или вручную: python3 ~/agentnet-pilot/tools/idea-to-proposal.py

Идемпотентен: не повторяет уже обработанные идеи (хранит ts последнего прогона).
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

import yaml

REPO         = Path(__file__).parent.parent
CLAUDE_IDEAS = REPO / "feeds" / "claude-ideas" / "ideas.jsonl"
AGENTNET_SIG = REPO / "feeds" / "agentnet-project" / "signals.jsonl"

VAULT        = Path.home() / "obsidian-backup"
PENDING_FILE = VAULT / "AI" / "Claude Code" / "pending-claude-hypotheses.md"
KEDB_FILE    = Path.home() / "tasks" / "known-errors.yaml"
STATE_FILE   = REPO / "feeds" / "claude-ideas" / ".proposal-last-run"

MODEL_HAIKU  = "claude-haiku-4-5-20251001"


# ── API ───────────────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=5,
        )
        raw = r.stdout.strip()
        if raw:
            data = json.loads(raw)
            return data.get("claudeAiOauth", {}).get("accessToken", "")
    except Exception:
        pass
    return ""


def _haiku(system: str, user: str) -> str:
    api_key = _get_api_key()
    if not api_key:
        return ""

    payload = json.dumps({
        "model": MODEL_HAIKU,
        "max_tokens": 600,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"[haiku] {e}", file=sys.stderr)
        return ""


# ── Data loading ──────────────────────────────────────────────────────────────

def _last_run_ts() -> datetime:
    if STATE_FILE.exists():
        try:
            return datetime.fromisoformat(STATE_FILE.read_text().strip())
        except Exception:
            pass
    return datetime.now() - timedelta(hours=25)  # первый запуск — берём за сутки


def _save_run_ts():
    STATE_FILE.write_text(datetime.now().isoformat())


def _load_new_ideas() -> list:
    """Загружает claude-ideas, появившиеся после последнего прогона."""
    if not CLAUDE_IDEAS.exists():
        return []
    cutoff = _last_run_ts()
    ideas = []
    for line in CLAUDE_IDEAS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ts = datetime.fromisoformat(r.get("ts", "2000-01-01T00:00:00"))
            if ts > cutoff:
                ideas.append(r)
        except Exception:
            continue
    return ideas


def _load_open_pains() -> list:
    """Загружает открытые боли из known-errors.yaml."""
    if not KEDB_FILE.exists():
        return []
    try:
        data = yaml.safe_load(KEDB_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [e for e in data if e.get("status") in ("open", "monitoring")]
    except Exception:
        return []


# ── Proposal generation ───────────────────────────────────────────────────────

SYSTEM_PROMPT = """Ты — архитектор AgentNet, помощник Claude-агента @oleg-mac.

Твоя задача: сопоставить идею из RSS с известными болями агента и сгенерировать
конкретное предложение по реализации.

Отвечай строго в JSON:
{
  "match": true/false,
  "pain_id": "KE-XXX или null",
  "pain_summary": "1 предложение — что болит",
  "proposal_title": "Название предложения (3-5 слов)",
  "proposal": "2-4 предложения — что сделать конкретно, какой результат",
  "effort": "low|medium|high",
  "priority": "P1|P2|P3"
}

match=true только если идея РЕАЛЬНО закрывает боль. Не натягивай связи."""


def _generate_proposal(idea: dict, pains: list) -> dict | None:
    pains_text = "\n".join(
        f"- {p['id']}: {p['problem']} [status={p['status']}, priority={p.get('priority','?')}]"
        for p in pains
    )

    user_prompt = f"""Идея из RSS:
Паттерн: {idea.get('pattern', '')}
Инсайт: {idea.get('insight', '')}
Категория: {idea.get('category', '')}
Источник: {idea.get('source', '')}

Известные боли агента:
{pains_text}

Есть ли совпадение? Если да — сгенерируй proposal."""

    response = _haiku(SYSTEM_PROMPT, user_prompt)
    if not response:
        return None

    try:
        # Haiku иногда оборачивает в ```json
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception:
        return None


# ── Output ────────────────────────────────────────────────────────────────────

def _write_proposals(proposals: list):
    """Дописывает новые предложения в pending-claude-hypotheses.md."""
    if not proposals:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"\n## Предложения из RSS — {now}\n"]

    for p in proposals:
        idea     = p["idea"]
        proposal = p["proposal"]
        priority = proposal.get("priority", "P3")
        effort   = proposal.get("effort", "?")
        pain_id  = proposal.get("pain_id", "")
        pain_sum = proposal.get("pain_summary", "")

        lines.append(f"### {proposal.get('proposal_title', idea.get('pattern', ''))}")
        lines.append(f"**Приоритет**: {priority} | **Усилие**: {effort}")
        if pain_id:
            lines.append(f"**Закрывает**: {pain_id} — {pain_sum}")
        lines.append(f"**Идея**: *{idea.get('pattern','')}* ({idea.get('category','')})")
        lines.append(f"> {idea.get('insight','')}")
        lines.append("")
        lines.append(f"**Предложение**: {proposal.get('proposal','')}")
        lines.append("")
        lines.append("---")
        lines.append("")

    block = "\n".join(lines)

    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PENDING_FILE.exists():
        current = PENDING_FILE.read_text(encoding="utf-8")
        PENDING_FILE.write_text(current.rstrip() + "\n" + block, encoding="utf-8")
    else:
        PENDING_FILE.write_text(block.lstrip(), encoding="utf-8")

    print(f"✅ Записано {len(proposals)} предложений → {PENDING_FILE.name}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    new_ideas = _load_new_ideas()
    if not new_ideas:
        print("Нет новых идей с последнего прогона — пропускаю.")
        _save_run_ts()
        return

    open_pains = _load_open_pains()
    if not open_pains:
        print("Нет открытых болей в known-errors.yaml — нечего сопоставлять.")
        _save_run_ts()
        return

    print(f"Анализирую {len(new_ideas)} идей × {len(open_pains)} болей...")
    proposals = []

    for idea in new_ideas:
        result = _generate_proposal(idea, open_pains)
        if result and result.get("match"):
            proposals.append({"idea": idea, "proposal": result})
            print(f"  ✓ {idea.get('pattern','')} → {result.get('pain_id','')} [{result.get('priority','')}]")
        else:
            print(f"  · {idea.get('pattern','')} — нет совпадения")

    _write_proposals(proposals)
    _save_run_ts()

    if not proposals:
        print("Совпадений не найдено.")


if __name__ == "__main__":
    main()
