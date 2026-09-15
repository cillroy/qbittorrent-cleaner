# schedule.py - Shared schedule config and run-state for the service and web UI.

import json
import os
from datetime import datetime, timedelta

from paths import BASE_DIR, SCHEDULE_STATE_PATH as STATE_PATH, ensure_runtime_dirs, migrate_legacy_files

RULES_PATH = os.path.join(BASE_DIR, "rules.yaml")

DEFAULT_INTERVAL_SECONDS = 30
MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 7 * 24 * 3600

SOURCE_LABELS = {
    "service": "Windows service",
    "web": "Web UI",
    "tray": "Tray app",
    "manual": "Manual",
}


def _clamp_interval(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, seconds))


def load_schedule_config(config=None):
    if config is None:
        import yaml
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    schedule = config.get("schedule") or {}
    return {
        "enabled": bool(schedule.get("enabled", True)),
        "interval_seconds": _clamp_interval(
            schedule.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)
        ),
    }


def load_state():
    migrate_legacy_files()
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    ensure_runtime_dirs()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, STATE_PATH)


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def to_iso(dt):
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat()


def format_interval(seconds):
    seconds = int(seconds)
    if seconds % 3600 == 0:
        n = seconds // 3600
        return f"{n} hour{'s' if n != 1 else ''}"
    if seconds % 60 == 0:
        n = seconds // 60
        return f"{n} minute{'s' if n != 1 else ''}"
    return f"{seconds} second{'s' if seconds != 1 else ''}"


def split_interval(seconds):
    seconds = int(seconds)
    if seconds % 3600 == 0:
        return seconds // 3600, "hours"
    if seconds % 60 == 0:
        return seconds // 60, "minutes"
    return seconds, "seconds"


def seconds_to_unit(seconds, unit):
    seconds = int(seconds)
    if unit == "hours":
        return seconds * 3600
    if unit == "minutes":
        return seconds * 60
    return seconds


def apply_interval_change(interval_seconds):
    """Recompute next_run_at after the user changes the interval."""
    interval_seconds = _clamp_interval(interval_seconds)
    state = load_state()
    now = datetime.now()
    last_scheduled = parse_iso(state.get("last_scheduled_run_at"))
    if last_scheduled:
        next_run = last_scheduled + timedelta(seconds=interval_seconds)
    else:
        next_run = now + timedelta(seconds=interval_seconds)
    state["next_run_at"] = to_iso(next_run)
    save_state(state)
    return state


def record_run(source, deleted=0, error=None, scheduled=True, interval_seconds=None):
    now = datetime.now()
    if interval_seconds is None:
        interval_seconds = load_schedule_config()["interval_seconds"]
    interval_seconds = _clamp_interval(interval_seconds)
    state = load_state()
    state["last_run_at"] = to_iso(now)
    state["last_run_source"] = source
    state["last_run_deleted"] = int(deleted)
    state["last_run_error"] = error
    if scheduled:
        state["last_scheduled_run_at"] = to_iso(now)
        state["next_run_at"] = to_iso(now + timedelta(seconds=interval_seconds))
    elif not state.get("next_run_at"):
        state["next_run_at"] = to_iso(now + timedelta(seconds=interval_seconds))
    save_state(state)
    return state


def _upcoming_runs(next_run_at, interval_seconds, count=5):
    if next_run_at is None or interval_seconds <= 0:
        return []
    runs = []
    t = next_run_at
    now = datetime.now()
    # If the stored next run is in the past, still show it first, then future slots.
    for _ in range(count):
        runs.append(to_iso(t))
        t = t + timedelta(seconds=interval_seconds)
        if t < now and len(runs) == 1:
            # Jump remaining slots onto the future cadence.
            elapsed = (now - next_run_at).total_seconds()
            steps = int(elapsed // interval_seconds) + 1
            t = next_run_at + timedelta(seconds=steps * interval_seconds)
            if t <= now:
                t = t + timedelta(seconds=interval_seconds)
    return runs


def get_schedule_status(config=None, service_status=None):
    sched = load_schedule_config(config)
    state = load_state()
    now = datetime.now()
    interval = sched["interval_seconds"]
    last_run_at = parse_iso(state.get("last_run_at"))
    last_scheduled = parse_iso(state.get("last_scheduled_run_at"))
    next_run_at = parse_iso(state.get("next_run_at"))

    if last_scheduled:
        next_run_at = last_scheduled + timedelta(seconds=interval)
    elif next_run_at is None and sched["enabled"]:
        next_run_at = now

    seconds_until = None
    if next_run_at is not None:
        seconds_until = int((next_run_at - now).total_seconds())

    overdue = bool(
        sched["enabled"]
        and next_run_at is not None
        and next_run_at <= now
    )

    value, unit = split_interval(interval)
    source = state.get("last_run_source")

    return {
        "enabled": sched["enabled"],
        "interval_seconds": interval,
        "interval_label": format_interval(interval),
        "interval_value": value,
        "interval_unit": unit,
        "last_run_at": to_iso(last_run_at),
        "last_run_source": source,
        "last_run_source_label": SOURCE_LABELS.get(source, source or "—"),
        "last_run_deleted": state.get("last_run_deleted", 0) or 0,
        "last_run_error": state.get("last_run_error"),
        "last_scheduled_run_at": to_iso(last_scheduled),
        "next_run_at": to_iso(next_run_at),
        "seconds_until_next": seconds_until,
        "overdue": overdue,
        "service_status": service_status,
        "now": to_iso(now),
        "upcoming": _upcoming_runs(next_run_at, interval) if sched["enabled"] else [],
        "min_interval_seconds": MIN_INTERVAL_SECONDS,
        "max_interval_seconds": MAX_INTERVAL_SECONDS,
    }


def seconds_until_next_run(config=None):
    """Seconds until the next scheduled run.

    Returns 0 if a run is due now, or None if the schedule is paused.
    """
    status = get_schedule_status(config)
    if not status["enabled"]:
        return None
    remaining = status["seconds_until_next"]
    if remaining is None:
        return 0
    return max(0, remaining)
