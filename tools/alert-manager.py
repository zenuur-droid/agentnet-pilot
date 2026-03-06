#!/usr/bin/env python3
"""
alert-manager.py — управление алертами системы.

SSoT: ~/agentnet-pilot/alerts/active-alerts.yaml
Статусы: open | watching | resolved

Использование (CLI):
  python3 alert-manager.py --list              # открытые алерты
  python3 alert-manager.py --list --all        # все алерты
  python3 alert-manager.py --close vault-pollution --reason "проверил, норм"
  python3 alert-manager.py --watch files-return-after-delete
  python3 alert-manager.py --reopen vault-pollution

Использование (как библиотека):
  from alert_manager import load_alerts, upsert_alert, save_alerts
"""

import sys
import yaml
from datetime import datetime, timedelta
from pathlib import Path

ALERTS_PATH = Path.home() / "agentnet-pilot" / "alerts" / "active-alerts.yaml"

# Сколько дней watching-алерт живёт без новых инцидентов до auto-close
WATCHING_TTL_DAYS = 14


# ---------- IO ----------

def load_alerts() -> list:
    if not ALERTS_PATH.exists():
        return []
    data = yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8")) or {}
    return data.get("alerts", [])


def save_alerts(alerts: list):
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "alerts": alerts}
    ALERTS_PATH.write_text(
        "# SSoT активных алертов системы\n"
        "# Producer: ~/tasks/meta-analysis.py\n"
        "# Consumer: ~/agentnet-pilot/tools/daily-inject.py\n"
        "# CLI:      ~/agentnet-pilot/tools/alert-manager.py\n\n"
        + yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


# ---------- Core logic ----------

def upsert_alert(
    alerts: list,
    alert_id: str,
    title: str,
    category: str,
    severity: str,
    level: str,
    dates: list,
    occurrences: int,
) -> list:
    """Создаёт или обновляет алерт. Возвращает обновлённый список."""
    today = datetime.now().strftime("%Y-%m-%d")

    for a in alerts:
        if a["id"] != alert_id:
            continue
        # Алерт уже есть
        if a["status"] == "resolved":
            resolved_date = a.get("resolved_date") or "2000-01-01"
            days_since = (datetime.now() - datetime.fromisoformat(resolved_date)).days
            if days_since >= 7:
                # Проблема вернулась — переоткрываем
                a["status"] = "open"
                a["resolved_date"] = None
                a["resolved_by"] = None
            else:
                # Закрыт недавно — не трогаем
                return alerts

        a["last_seen"] = today
        a["occurrences"] = occurrences
        a["dates"] = dates
        if a["severity"] != severity:
            a["severity"] = severity  # обновить если изменился
        return alerts

    # Нового алерта ещё нет — создаём
    alerts.append({
        "id": alert_id,
        "title": title,
        "category": category,
        "severity": severity,
        "level": level,
        "status": "open",
        "first_seen": today,
        "last_seen": today,
        "occurrences": occurrences,
        "dates": dates,
        "resolved_date": None,
        "resolved_by": None,
    })
    return alerts


def auto_close_watching(alerts: list) -> list:
    """Закрывает watching-алерты, не видевшиеся WATCHING_TTL_DAYS дней."""
    today = datetime.now()
    for a in alerts:
        if a["status"] != "watching":
            continue
        last = a.get("last_seen") or a.get("first_seen") or "2000-01-01"
        days_since = (today - datetime.fromisoformat(last)).days
        if days_since >= WATCHING_TTL_DAYS:
            a["status"] = "resolved"
            a["resolved_date"] = today.strftime("%Y-%m-%d")
            a["resolved_by"] = f"auto-close (не видели {days_since}д)"
    return alerts


# ---------- CLI commands ----------

def cmd_list(show_all: bool):
    alerts = load_alerts()
    if not show_all:
        alerts = [a for a in alerts if a["status"] == "open"]

    if not alerts:
        print("✅ Нет открытых алертов")
        return

    icons = {"open": "🔴", "watching": "👁", "resolved": "✅"}
    for a in alerts:
        icon = icons.get(a["status"], "?")
        print(f"{icon} [{a['severity']}] {a['id']} — {a['title']}")
        print(f"   status={a['status']} | last_seen={a.get('last_seen')} | "
              f"occurrences={a.get('occurrences', '?')}")
        if a.get("resolved_by"):
            print(f"   resolved_by: {a['resolved_by']}")
        print()


def cmd_close(alert_id: str, reason: str):
    alerts = load_alerts()
    today = datetime.now().strftime("%Y-%m-%d")
    found = False
    for a in alerts:
        if a["id"] == alert_id:
            a["status"] = "resolved"
            a["resolved_date"] = today
            a["resolved_by"] = reason or "manual"
            found = True
            break
    if not found:
        print(f"❌ Алерт не найден: {alert_id}")
        sys.exit(1)
    save_alerts(alerts)
    print(f"✅ Закрыт: {alert_id}")


def cmd_watch(alert_id: str):
    alerts = load_alerts()
    found = False
    for a in alerts:
        if a["id"] == alert_id:
            a["status"] = "watching"
            found = True
            break
    if not found:
        print(f"❌ Алерт не найден: {alert_id}")
        sys.exit(1)
    save_alerts(alerts)
    print(f"👁 Watching: {alert_id}")


def cmd_reopen(alert_id: str):
    alerts = load_alerts()
    found = False
    for a in alerts:
        if a["id"] == alert_id:
            a["status"] = "open"
            a["resolved_date"] = None
            a["resolved_by"] = None
            found = True
            break
    if not found:
        print(f"❌ Алерт не найден: {alert_id}")
        sys.exit(1)
    save_alerts(alerts)
    print(f"🔴 Переоткрыт: {alert_id}")


def main():
    args = sys.argv[1:]

    if not args or "--list" in args:
        cmd_list(show_all="--all" in args)
    elif "--close" in args:
        idx = args.index("--close")
        alert_id = args[idx + 1] if idx + 1 < len(args) else ""
        reason = ""
        if "--reason" in args:
            r_idx = args.index("--reason")
            reason = args[r_idx + 1] if r_idx + 1 < len(args) else ""
        cmd_close(alert_id, reason)
    elif "--watch" in args:
        idx = args.index("--watch")
        cmd_watch(args[idx + 1])
    elif "--reopen" in args:
        idx = args.index("--reopen")
        cmd_reopen(args[idx + 1])
    elif "--auto-close-watching" in args:
        alerts = load_alerts()
        alerts = auto_close_watching(alerts)
        save_alerts(alerts)
        print("✅ Auto-close watching выполнен")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
