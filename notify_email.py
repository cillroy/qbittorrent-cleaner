# notify_email.py - Optional SMTP email alerts when cleanup keeps failing.
#
# Config lives in rules.yaml under notifications.email (see readme.md).
# Uses only the standard library (smtplib / email). Nothing here may raise
# into the service loop: every public helper catches and logs its own errors.

import json
import os
import smtplib
import socket
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from paths import BASE_DIR, DATA_DIR, ensure_runtime_dirs

RULES_PATH = os.path.join(BASE_DIR, "rules.yaml")
STATE_PATH = os.path.join(DATA_DIR, "email_alert_state.json")

DEFAULT_PASSWORD_ENV = "QB_CLEANER_SMTP_PASSWORD"
SMTP_TIMEOUT_SECONDS = 20

DEFAULTS = {
    "enabled": False,
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "starttls": True,
    "use_ssl": False,
    "username": "",
    "password": "",
    "password_env": DEFAULT_PASSWORD_ENV,
    "from_address": "",
    "to": [],
    "failure_threshold": 10,
    "cooldown_hours": 6,
    "send_recovery": True,
}


def _to_bool(value, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return default


def _to_int(value, default, minimum=None, maximum=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _to_float(value, default, minimum=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    return result


def split_addresses(value):
    """Accept a list or a comma/semicolon separated string of addresses."""
    if value is None:
        return []
    if isinstance(value, str):
        items = value.replace(";", ",").split(",")
    else:
        items = list(value)
    return [str(item).strip() for item in items if str(item or "").strip()]


def _read_rules():
    import yaml
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_email_config(config=None):
    """Normalized notifications.email settings with defaults filled in.

    The password comes from rules.yaml, or (when that is blank) from the
    environment variable named by password_env.
    """
    if config is None:
        try:
            config = _read_rules()
        except Exception:
            config = {}
    raw = ((config or {}).get("notifications") or {}).get("email") or {}
    cfg = dict(DEFAULTS)
    cfg["enabled"] = _to_bool(raw.get("enabled"), DEFAULTS["enabled"])
    cfg["smtp_host"] = str(raw.get("smtp_host") or DEFAULTS["smtp_host"]).strip()
    cfg["smtp_port"] = _to_int(raw.get("smtp_port"), DEFAULTS["smtp_port"], 1, 65535)
    cfg["starttls"] = _to_bool(raw.get("starttls"), DEFAULTS["starttls"])
    cfg["use_ssl"] = _to_bool(raw.get("use_ssl"), DEFAULTS["use_ssl"])
    cfg["username"] = str(raw.get("username") or "").strip()
    cfg["password_env"] = str(raw.get("password_env") or DEFAULT_PASSWORD_ENV).strip()
    password = raw.get("password") or ""
    if not password and cfg["password_env"]:
        password = os.environ.get(cfg["password_env"], "")
    cfg["password"] = str(password)
    cfg["password_saved"] = bool(raw.get("password"))
    cfg["from_address"] = str(raw.get("from_address") or cfg["username"] or "").strip()
    cfg["to"] = split_addresses(raw.get("to"))
    cfg["failure_threshold"] = _to_int(raw.get("failure_threshold"), DEFAULTS["failure_threshold"], 1, 100000)
    cfg["cooldown_hours"] = _to_float(raw.get("cooldown_hours"), DEFAULTS["cooldown_hours"], 0)
    cfg["send_recovery"] = _to_bool(raw.get("send_recovery"), DEFAULTS["send_recovery"])
    return cfg


def validate_email_config(cfg):
    """Return a list of human-readable problems (empty when usable)."""
    problems = []
    if not cfg.get("smtp_host"):
        problems.append("SMTP host is empty")
    if not cfg.get("from_address"):
        problems.append("From address is empty")
    if not cfg.get("to"):
        problems.append("No recipient (to) addresses")
    if cfg.get("username") and not cfg.get("password"):
        problems.append(
            f"SMTP username is set but no password (rules.yaml or %{cfg.get('password_env') or DEFAULT_PASSWORD_ENV}%)"
        )
    return problems


def send_email(cfg, subject, body):
    """Send one plain-text email. Raises on failure (callers catch)."""
    problems = validate_email_config(cfg)
    if problems:
        raise ValueError("; ".join(problems))

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from_address"]
    msg["To"] = ", ".join(cfg["to"])
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=None)
    msg.set_content(body)

    host = cfg["smtp_host"]
    port = int(cfg["smtp_port"])
    context = ssl.create_default_context()
    if cfg.get("use_ssl"):
        server = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)
    try:
        server.ehlo()
        if cfg.get("starttls") and not cfg.get("use_ssl"):
            server.starttls(context=context)
            server.ehlo()
        if cfg.get("username"):
            server.login(cfg["username"], cfg.get("password") or "")
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def _app_version():
    try:
        from version import read_local_version
        return read_local_version()
    except Exception:
        return "unknown"


def send_test_email(cfg):
    host = socket.gethostname()
    subject = f"[qBittorrent Cleaner] Test email from {host}"
    body = (
        "This is a test email from qBittorrent Cleaner.\n\n"
        f"Host: {host}\n"
        f"Version: {_app_version()}\n"
        f"Sent: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "Failure alerts are sent after "
        f"{cfg.get('failure_threshold')} consecutive failed cleanup runs, "
        f"at most once every {cfg.get('cooldown_hours')} hour(s).\n"
    )
    send_email(cfg, subject, body)


# -------------------------
# Failure tracking
# -------------------------

def load_alert_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_alert_state(state):
    ensure_runtime_dirs()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, STATE_PATH)


def _iso(dt):
    return dt.replace(microsecond=0).isoformat() if dt else None


def _parse(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


SEND_RETRY_MINUTES = 10


def _recent_attempt(state, now):
    """After a failed send, wait SEND_RETRY_MINUTES before trying SMTP again."""
    last_try = _parse(state.get("last_send_attempt_at"))
    return bool(last_try and now - last_try < timedelta(minutes=SEND_RETRY_MINUTES))


def _failure_body(state, cfg, host):
    return (
        f"qBittorrent Cleaner on {host} has failed {state['consecutive_failures']} "
        "cleanup runs in a row.\n\n"
        f"First failure: {state.get('first_failure_at')}\n"
        f"Latest failure: {state.get('last_failure_at')}\n"
        f"Latest error: {state.get('last_error')}\n\n"
        "Check that qBittorrent is running and its Web UI URL / credentials in "
        "rules.yaml are correct. See logs/actions/qb-cleaner.log.\n\n"
        f"You will not get another failure email for this outage, and at most one "
        f"every {cfg['cooldown_hours']} hour(s).\n"
        f"Version: {_app_version()}\n"
    )


def _recovery_body(state, host, now):
    return (
        f"qBittorrent Cleaner on {host} is working again.\n\n"
        f"Failed runs: {state.get('consecutive_failures')}\n"
        f"First failure: {state.get('first_failure_at')}\n"
        f"Recovered: {_iso(now)}\n"
        f"Last error: {state.get('last_error')}\n"
    )


def record_cleanup_result(success, error=None, config=None, logger=None, now=None):
    """Track consecutive failures and email when the threshold is crossed.

    Safe to call after every run; never raises.
    """
    log = logger or (lambda _msg: None)
    try:
        cfg = load_email_config(config)
        now = now or datetime.now()
        state = load_alert_state()
        host = socket.gethostname()

        if success:
            failures = int(state.get("consecutive_failures") or 0)
            if failures == 0:
                return
            alerted = bool(state.get("episode_alerted"))
            if alerted and cfg["enabled"] and cfg["send_recovery"]:
                try:
                    send_email(
                        cfg,
                        f"[qBittorrent Cleaner] Recovered on {host}",
                        _recovery_body(state, host, now),
                    )
                    log(f"Email alert: recovery email sent after {failures} failed run(s)")
                except Exception as e:
                    log(f"Email alert: could not send recovery email: {e}")
            new_state = {"last_alert_at": state.get("last_alert_at")}
            save_alert_state(new_state)
            return

        failures = int(state.get("consecutive_failures") or 0) + 1
        state["consecutive_failures"] = failures
        if not state.get("first_failure_at"):
            state["first_failure_at"] = _iso(now)
        state["last_failure_at"] = _iso(now)
        state["last_error"] = (str(error) if error is not None else "unknown error")[:1000]

        if (
            cfg["enabled"]
            and failures >= cfg["failure_threshold"]
            and not state.get("episode_alerted")
        ):
            last_alert = _parse(state.get("last_alert_at"))
            cooldown = timedelta(hours=cfg["cooldown_hours"])
            if last_alert and now - last_alert < cooldown:
                if not state.get("cooldown_logged"):
                    log(
                        f"Email alert: {failures} consecutive failures, but an alert was sent "
                        f"at {state.get('last_alert_at')} (cooldown {cfg['cooldown_hours']} h); not emailing yet"
                    )
                    state["cooldown_logged"] = True
            elif _recent_attempt(state, now):
                pass
            else:
                state["last_send_attempt_at"] = _iso(now)
                try:
                    send_email(
                        cfg,
                        f"[qBittorrent Cleaner] Cleanup failing on {host} ({failures} runs in a row)",
                        _failure_body(state, cfg, host),
                    )
                    state["episode_alerted"] = True
                    state["last_alert_at"] = _iso(now)
                    log(f"Email alert: failure email sent after {failures} consecutive failed run(s)")
                except Exception as e:
                    # Retry on a later failed run, but only log the error once per episode.
                    if not state.get("send_error_logged"):
                        log(f"Email alert: could not send failure email: {e}")
                        state["send_error_logged"] = True
        save_alert_state(state)
    except Exception as e:
        try:
            log(f"Email alert: internal error (ignored): {e}")
        except Exception:
            pass
