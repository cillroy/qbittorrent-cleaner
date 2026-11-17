# cleaner.py - A script to clean up qBittorrent torrents based on rules defined in a YAML config file.

import yaml
import time
import os
from datetime import datetime
from qb_api import QBClient
from notify_email import record_cleanup_result, record_delete_cap_alert

# Exact (non-numeric) match keys the engine supports.
EXACT_MATCH_KEYS = frozenset({
    "label",
    "label_in",
    "category",
    "category_in",
    "state",
})

# Rule behavior flags that may appear in the match block or at rule level.
BOOLEAN_MATCH_KEYS = frozenset({
    "include_incomplete",
})

KNOWN_RULE_KEYS = frozenset({
    "name",
    "match",
    "action",
    "include_incomplete",
    "dry_run",
})

TIME_FIELDS = frozenset({"last_activity_hours", "added_on_hours"})
KEEP_TAG = "keep"
DEFAULT_MAX_DELETES_PER_RUN = 20


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def load_cleanup_settings(config=None):
    """rules.yaml-level cleanup safeguards, with safe defaults if absent."""
    config = config or {}
    raw = config.get("cleanup")
    if not isinstance(raw, dict):
        raw = {}
    cap_raw = raw.get("max_deletes_per_run", config.get("max_deletes_per_run"))
    if cap_raw is None or cap_raw == "":
        cap = DEFAULT_MAX_DELETES_PER_RUN
    else:
        try:
            cap = int(cap_raw)
        except (TypeError, ValueError):
            cap = DEFAULT_MAX_DELETES_PER_RUN
        if cap < 0:
            cap = DEFAULT_MAX_DELETES_PER_RUN
    dry_raw = raw.get("dry_run", config.get("dry_run"))
    return {
        "max_deletes_per_run": cap,
        "dry_run": _truthy(dry_raw),
    }


def last_activity_timestamp(torrent):
    """Unix time of last activity, falling back to added_on.

    A missing or 0 last_activity must never be treated as idle since 1970.
    If added_on is also missing or 0, return 0 (meaning unknown / not idle).
    """
    ts = _as_int(torrent.get("last_activity"), 0)
    if ts <= 0:
        ts = _as_int(torrent.get("added_on"), 0)
    return ts if ts > 0 else 0


def _field_ratio(torrent, hours_since):
    return _as_float(torrent.get("ratio", 0), 0.0)


def _field_last_activity_hours(torrent, hours_since):
    ts = last_activity_timestamp(torrent)
    if ts <= 0:
        return 0.0
    return hours_since(ts)


def _field_added_on_hours(torrent, hours_since):
    ts = _as_int(torrent.get("added_on"), 0)
    if ts <= 0:
        return 0.0
    return hours_since(ts)


NUMERIC_FIELDS = {
    "ratio": _field_ratio,
    "last_activity_hours": _field_last_activity_hours,
    "added_on_hours": _field_added_on_hours,
}

# Longer operator names first so endswith("_gt") cannot steal "_gte".
NUMERIC_OPERATORS = ("gte", "lte", "gt", "lt")
OPERATOR_FUNCS = {
    "gt": lambda actual, expected: actual > expected,
    "gte": lambda actual, expected: actual >= expected,
    "lt": lambda actual, expected: actual < expected,
    "lte": lambda actual, expected: actual <= expected,
}


def split_numeric_match_key(key):
    """Return (field, operator) for a numeric match key, or (None, None)."""
    if not key:
        return None, None
    for op in NUMERIC_OPERATORS:
        suffix = "_" + op
        if key.endswith(suffix):
            field = key[:-len(suffix)]
            if field:
                return field, op
    return None, None


def rule_match_problems(rule):
    """Return a list of problems in a rule's match block.

    An empty list means the rule is valid and may match torrents.
    Unknown keys, unknown fields/operators, an empty match block, or a
    missing time condition make the whole rule invalid (it must never
    match or delete). Used by both the cleaner engine and the web UI.
    """
    if not isinstance(rule, dict):
        return ["invalid rule"]
    match = rule.get("match")
    if not match:
        return ["empty match block"]
    if not isinstance(match, dict):
        return ["empty match block"]

    problems = []
    has_time = False
    for key in match:
        if key in EXACT_MATCH_KEYS or key in BOOLEAN_MATCH_KEYS:
            continue
        field, op = split_numeric_match_key(key)
        if field in NUMERIC_FIELDS and op in OPERATOR_FUNCS:
            if field in TIME_FIELDS:
                has_time = True
            continue
        problems.append(f"unsupported condition '{key}'")
    if not has_time:
        problems.append(
            "missing time condition (last_activity_hours_* or added_on_hours_*)"
        )
    return problems


def rule_has_include_incomplete(rule):
    if not isinstance(rule, dict):
        return False
    if _truthy(rule.get("include_incomplete")):
        return True
    match = rule.get("match")
    if isinstance(match, dict) and _truthy(match.get("include_incomplete")):
        return True
    return False


def rule_is_dry_run(rule, global_dry_run=False):
    if global_dry_run:
        return True
    return isinstance(rule, dict) and _truthy(rule.get("dry_run"))


def torrent_has_keep_tag(torrent):
    tags = (torrent or {}).get("tags") or ""
    if isinstance(tags, (list, tuple, set)):
        parts = list(tags)
    else:
        parts = str(tags).split(",")
    return any(str(part).strip().lower() == KEEP_TAG for part in parts)


def torrent_is_complete(torrent):
    return _as_float((torrent or {}).get("progress", 0), 0.0) >= 1.0


def match_torrent(torrent, rule, hours_since):
    """Return True if a valid rule's every condition matches this torrent."""
    if rule_match_problems(rule):
        return False
    if not torrent_is_complete(torrent) and not rule_has_include_incomplete(rule):
        return False

    match = rule.get("match") or {}
    for key, value in match.items():
        if key in BOOLEAN_MATCH_KEYS:
            continue
        if key == "label":
            if torrent.get("label") != value:
                return False
            continue
        if key == "label_in":
            if torrent.get("label") not in value:
                return False
            continue
        if key == "category":
            if torrent.get("category") != value:
                return False
            continue
        if key == "category_in":
            if torrent.get("category") not in value:
                return False
            continue
        if key == "state":
            if torrent.get("state") != value:
                return False
            continue

        field, op = split_numeric_match_key(key)
        actual = NUMERIC_FIELDS[field](torrent, hours_since)
        if not OPERATOR_FUNCS[op](actual, float(value)):
            return False
    return True


class Cleaner:
    def __init__(self, config_path="rules.yaml", logger=print, schedule_logger=None, notifier=None):
        self.logger = logger
        self.schedule_logger = schedule_logger if schedule_logger is not None else logger
        self.notifier = notifier

        # Resolve rules.yaml relative to this file (fixes Windows service crash)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(base_dir, config_path)
        self.config = None
        self.client = None
        self.reload_config()

    def reload_config(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}

        qb = self.config["qbittorrent"]
        self.client = QBClient(
            qb["url"],
            username=qb.get("username"),
            password=qb.get("password"),
        )

    def hours_since(self, unix_timestamp):
        dt = datetime.fromtimestamp(unix_timestamp)
        delta = datetime.now() - dt
        return delta.total_seconds() / 3600.0

    def match_rule(self, torrent, rule):
        return match_torrent(torrent, rule, self.hours_since)

    def _log_invalid_rules(self, rules):
        """Log each invalid rule once per run to the actions log."""
        for rule in rules:
            problems = rule_match_problems(rule)
            if not problems:
                continue
            name = rule.get("name") if isinstance(rule, dict) else None
            name = name or "(unnamed rule)"
            self.logger(f"Skipping invalid rule '{name}': {', '.join(problems)}")

    def run(self, source="service"):
        from schedule import load_schedule_config, record_run

        deleted = 0
        would_delete = 0
        capped = False
        cap = DEFAULT_MAX_DELETES_PER_RUN
        error = None
        self.schedule_logger(f"Cleanup run started (source={source})")
        try:
            self.reload_config()
            settings = load_cleanup_settings(self.config)
            cap = settings["max_deletes_per_run"]
            global_dry_run = settings["dry_run"]
            torrents = self.client.get_torrents()
            rules = self.config.get("rules") or []
            self._log_invalid_rules(rules)
            if global_dry_run:
                self.logger(
                    "Global dry_run is enabled; no torrents will be deleted this run"
                )

            for t in torrents:
                for rule in rules:
                    if rule_match_problems(rule):
                        continue
                    if not self.match_rule(t, rule):
                        continue

                    action = rule.get("action") or {}
                    if not action.get("delete_torrent"):
                        break

                    name = t.get("name", "")
                    rule_name = rule.get("name") or "(unnamed rule)"

                    if torrent_has_keep_tag(t):
                        self.logger(
                            f"Skipping delete (keep tag): {name} via rule {rule_name}"
                        )
                        break

                    if rule_is_dry_run(rule, global_dry_run):
                        msg = f"Would delete: {name} via rule {rule_name}"
                        self.logger(msg)
                        if self.notifier:
                            self.notifier(msg)
                        would_delete += 1
                        break

                    if deleted >= cap:
                        if not capped:
                            capped = True
                            msg = (
                                f"Delete cap reached ({cap} per run); "
                                "remaining matches will not be deleted this run"
                            )
                            self.logger(msg)
                            if self.notifier:
                                self.notifier(msg)
                            record_delete_cap_alert(
                                deleted=deleted,
                                cap=cap,
                                config=self.config,
                                logger=self.logger,
                            )
                        break

                    self.client.delete(
                        t["hash"],
                        action.get("delete_files", False)
                    )
                    deleted += 1
                    msg = f"Deleted: {name} via rule {rule_name}"
                    self.logger(msg)
                    if self.notifier:
                        self.notifier(msg)
                    # First matching rule wins; do not delete/log twice.
                    break

            finished = f"Cleanup run finished: {deleted} torrent(s) deleted (source={source})"
            if would_delete:
                finished += f"; {would_delete} would-delete (dry run)"
            if capped:
                finished += f"; delete cap {cap} reached"
            self.schedule_logger(finished)
            if deleted or would_delete or capped:
                self.logger(finished)
        except Exception as e:
            error = str(e)
            fail = f"Cleanup run failed: {e} (source={source})"
            self.schedule_logger(fail)
            self.logger(fail)
            raise
        finally:
            try:
                interval = load_schedule_config(self.config)["interval_seconds"]
                record_run(
                    source=source,
                    deleted=deleted,
                    error=error,
                    scheduled=(source == "service"),
                    interval_seconds=interval,
                    capped=capped,
                    delete_cap=cap,
                    would_delete=would_delete,
                )
            except Exception as e:
                self.logger(f"Failed to update schedule state: {e}")
            # Email alert after N consecutive failures (never raises).
            record_cleanup_result(
                success=(error is None),
                error=error,
                config=self.config,
                logger=self.logger,
            )

    def run_once(self, source="manual"):
        self.run(source=source)
