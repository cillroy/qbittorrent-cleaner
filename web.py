# web.py - Web interface for qBittorrent Cleaner

import os
import subprocess
import yaml
import uvicorn
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.base import BaseHTTPMiddleware
import secrets
from datetime import datetime
import win32serviceutil
from cleaner import (
    Cleaner,
    rule_match_problems,
    load_cleanup_settings,
    preview_rule,
    hours_since_now,
)
from yamlutil import apply_yaml_updates
from qb_api import QBClient
from schedule import (
    get_schedule_status,
    apply_interval_change,
    seconds_to_unit,
    MIN_INTERVAL_SECONDS,
    MAX_INTERVAL_SECONDS,
)
from logutil import setup_logging, ACTION_LOG, SCHEDULE_LOG
from paths import LOGS_DIR, ACTIONS_LOG_DIR, migrate_legacy_files
from version import read_local_version
from drivesutil import get_local_drives
from update_check import check_for_update
from notify_email import (
    load_email_config,
    load_alert_state,
    send_test_email,
    split_addresses,
    validate_email_config,
)

# -------------------------
# CONFIGURATION
# -------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
RULES_PATH = os.path.join(BASE_DIR, "rules.yaml")
LOG_PATH = ACTION_LOG
LOG_KINDS = {
    "action": {
        "name": "qb-cleaner.log",
        "path": ACTION_LOG,
        "download": "qb-cleaner-actions.log",
        "label": "Actions",
    },
    "schedule": {
        "name": "qb-schedule.log",
        "path": SCHEDULE_LOG,
        "download": "qb-cleaner-schedule.log",
        "label": "Schedule",
    },
}

# Load config
with open(RULES_PATH, "r") as f:
    config = yaml.safe_load(f)

web_config = config.get("web", {})
PORT = web_config.get("port", 8081)
WEB_USERNAME = web_config.get("username", "admin")
WEB_PASSWORD = web_config.get("password", "admin")
ENABLE_AUTH = web_config.get("enable_auth", True)

# qBittorrent URL/credentials are read from rules.yaml on each status check
# (see get_qb_client_settings). Do not cache them at import time.

SERVICE_NAME = "QBCleanerService"

# -------------------------
# LOGGING SETUP
# -------------------------

logging_config = config.get("logging", {})
max_days = logging_config.get("max_days", 30)
enable_notifications = logging_config.get("enable_notifications", True)

action_logger, schedule_logger = setup_logging(max_days)
logger = action_logger

# -------------------------
# FASTAPI SETUP
# -------------------------

app = FastAPI(title="qBittorrent Cleaner Web", version=read_local_version())
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/static/logs", StaticFiles(directory=LOGS_DIR), name="logs")
from jinja2 import Environment, FileSystemLoader
jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), cache_size=0)
jinja_env.globals.update(
    brand_name="cwhateverc",
    brand_url="https://cwhateverc.com",
    brand_email="support@cwhateverc.com",
    github_url="https://github.com/cillroy/qbittorrent-cleaner",
    app_version=read_local_version,
)
templates = Jinja2Templates(env=jinja_env)

security = HTTPBasic()

# -------------------------
# AUTHENTICATION
# -------------------------

def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    if not ENABLE_AUTH:
        return True

    correct_username = secrets.compare_digest(credentials.username, WEB_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, WEB_PASSWORD)

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

# -------------------------
# UTILITY FUNCTIONS
# -------------------------

def _normalize_log_kind(kind):
    if kind in LOG_KINDS:
        return kind
    return "action"


def _log_file_sort_key(path, current_name):
    basename = os.path.basename(path)
    if basename == current_name:
        return "9999-99-99"
    return basename.rsplit(".", 1)[-1]


def get_log_files(kind="action"):
    import glob
    kind = _normalize_log_kind(kind)
    current_name = LOG_KINDS[kind]["name"]
    current_path = LOG_KINDS[kind]["path"]
    log_files = glob.glob(current_path + "*")
    log_files.sort(key=lambda p: _log_file_sort_key(p, current_name))
    return log_files

def get_service_status():
    try:
        status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
        raw = status[1]
        if raw == 4:  # SERVICE_RUNNING
            return "Running"
        elif raw == 1:  # SERVICE_STOPPED
            return "Stopped"
        else:
            return "Unknown"
    except:
        return "Unknown"

def get_qb_client_settings():
    """Load qBittorrent connection settings from rules.yaml on each call."""
    qb = (load_config().get("qbittorrent") or {})
    return qb.get("url"), qb.get("username"), qb.get("password")


def get_qb_status():
    try:
        url, username, password = get_qb_client_settings()
        if not url:
            return {
                "status": "Error: qBittorrent URL is not set in rules.yaml",
                "torrent_count": 0,
                "torrents": []
            }
        client = QBClient(url, username, password)
        torrents = client.get_torrents()
        return {
            "status": "Connected",
            "torrent_count": len(torrents),
            "torrents": torrents[:10]  # Show first 10
        }
    except Exception as e:
        return {
            "status": f"Error: {str(e)}",
            "torrent_count": 0,
            "torrents": []
        }

def get_recent_logs(lines=50, kind="action"):
    try:
        kind = _normalize_log_kind(kind)
        current_path = LOG_KINDS[kind]["path"]
        log_files = get_log_files(kind)

        if not log_files:
            return ["No log files found"]

        all_lines = []

        for log_file in log_files:
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    file_lines = f.readlines()

                if log_file != current_path:
                    filename = os.path.basename(log_file)
                    all_lines.append(f"\n--- Archived Log: {filename} ---\n")

                all_lines.extend(file_lines)

            except Exception as e:
                all_lines.append(f"Error reading {os.path.basename(log_file)}: {e}\n")
                continue

        if all_lines:
            return list(reversed(all_lines[-lines:]))
        return ["No logs available"]

    except Exception as e:
        return [f"Error aggregating logs: {e}"]

def get_deletion_stats():
    """Count torrents deleted in the last 24 hours and 30 days"""
    try:
        import glob
        import os
        from datetime import datetime, timedelta

        # Find all log files (main + archived)
        log_pattern = os.path.join(ACTIONS_LOG_DIR, "qb-cleaner.log*")
        log_files = glob.glob(log_pattern)
        if not log_files:
            log_files = glob.glob(os.path.join(BASE_DIR, "qb-cleaner.log*"))

        if not log_files:
            return {"last_24h": 0, "last_30d": 0}

        now = datetime.now()
        last_24h = now - timedelta(hours=24)
        last_30d = now - timedelta(days=30)

        deletions_24h = 0
        deletions_30d = 0

        # Read all log files
        for log_file in log_files:
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        # Look for deletion lines
                        if "Deleted:" in line:
                            # Extract timestamp from log line
                            # Format: 2026-05-09 10:13:35,010 [INFO] Deleted: ...
                            try:
                                timestamp_str = line.split(" [")[0]  # Get timestamp part
                                # Handle different formats
                                if "," in timestamp_str:
                                    # Format: 2026-05-09 10:13:35,010
                                    log_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
                                else:
                                    # Format: [2026-05-04 12:11:45]
                                    timestamp_str = timestamp_str.strip("[]")
                                    log_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                                if log_time >= last_24h:
                                    deletions_24h += 1
                                if log_time >= last_30d:
                                    deletions_30d += 1

                            except (ValueError, IndexError):
                                # Skip lines that don't match expected format
                                continue

            except Exception as e:
                # Skip files that can't be read
                continue

        return {
            "last_24h": deletions_24h,
            "last_30d": deletions_30d
        }

    except Exception as e:
        return {"last_24h": 0, "last_30d": 0}

def is_local_client(request: Request):
    host = (request.client.host if request.client else "") or ""
    return host in ("127.0.0.1", "::1", "localhost")


def load_config():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(new_config):
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(new_config, f, default_flow_style=False, sort_keys=False)

# -------------------------
# RULE DISPLAY / VALIDATION
# -------------------------

def rules_for_display(rules, global_dry_run=False):
    """Copy rules for the Rules page, with shared validation attached."""
    displayed = []
    for rule in rules or []:
        match = rule.get("match") if isinstance(rule.get("match"), dict) else {}
        action = rule.get("action") if isinstance(rule.get("action"), dict) else {}
        problems = rule_match_problems(rule)
        include_incomplete = bool(
            rule.get("include_incomplete") or match.get("include_incomplete")
        )
        displayed.append({
            "name": rule.get("name") or "(unnamed rule)",
            "match": match,
            "action": action,
            "include_incomplete": include_incomplete,
            "dry_run": bool(rule.get("dry_run") or global_dry_run),
            "rule_dry_run": bool(rule.get("dry_run")),
            "validation_problems": problems,
            "is_invalid": bool(problems),
        })
    return displayed


def invalid_rules_summary(rules):
    summary = []
    for rule in rules or []:
        problems = rule_match_problems(rule)
        if problems:
            summary.append({
                "name": (rule or {}).get("name") or "(unnamed rule)",
                "problems": problems,
            })
    return summary


def _form_flag(*values):
    for value in values:
        if str(value or "").strip().lower() in ("on", "true", "1", "yes"):
            return True
    return False


def _rule_from_form(name, match_criteria, delete_torrent, delete_files, include_incomplete, dry_run):
    if not isinstance(match_criteria, dict):
        match_criteria = {}
    else:
        match_criteria = dict(match_criteria)
    if match_criteria.pop("include_incomplete", None):
        include_incomplete = True
    data = {
        "name": name,
        "match": match_criteria,
        "action": {
            "delete_torrent": bool(delete_torrent),
            "delete_files": bool(delete_files),
        },
    }
    if include_incomplete:
        data["include_incomplete"] = True
    if dry_run:
        data["dry_run"] = True
    return data

# -------------------------
# ROUTES
# -------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, auth=Depends(authenticate)):
    service_status = get_service_status()
    qb_status = get_qb_status()
    recent_logs = get_recent_logs(10)
    deletion_stats = get_deletion_stats()
    drives = get_local_drives()
    current = load_config()
    schedule_status = get_schedule_status(current, service_status=service_status)
    cleanup = load_cleanup_settings(current)
    invalid_rules = invalid_rules_summary(current.get("rules") or [])
    update = check_for_update()

    template = jinja_env.get_template("dashboard.html")
    html_content = template.render(
        service_status=service_status,
        qb_status=qb_status,
        recent_logs=recent_logs,
        deletion_stats=deletion_stats,
        drives=drives,
        schedule=schedule_status,
        cleanup=cleanup,
        invalid_rules=invalid_rules,
        update=update,
        local_client=is_local_client(request),
        current_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    return HTMLResponse(content=html_content)

@app.get("/rules", response_class=HTMLResponse)
def rules_page(request: Request, auth=Depends(authenticate)):
    current = load_config()
    cleanup = load_cleanup_settings(current)
    template = jinja_env.get_template("rules.html")
    html_content = template.render(
        rules=rules_for_display(current.get("rules", []), cleanup["dry_run"]),
        qb_config=current.get("qbittorrent", {}),
        cleanup=cleanup,
    )
    return HTMLResponse(content=html_content)

@app.post("/rules/add")
def add_rule(
    name: str = Form(...),
    match_json: str = Form(...),
    delete_torrent: bool = Form(False),
    delete_files: bool = Form(False),
    include_incomplete: bool = Form(False),
    dry_run: bool = Form(False),
    auth=Depends(authenticate)
):
    try:
        import json
        match_criteria = json.loads(match_json)
    except Exception:
        match_criteria = {}

    new_rule = _rule_from_form(
        name, match_criteria, delete_torrent, delete_files,
        include_incomplete, dry_run,
    )

    current = load_config()
    if "rules" not in current:
        current["rules"] = []
    current["rules"].append(new_rule)
    save_config(current)

    return RedirectResponse(url="/rules", status_code=303)

@app.post("/rules/delete/{rule_index}")
def delete_rule(rule_index: int, auth=Depends(authenticate)):
    current = load_config()
    if "rules" in current and 0 <= rule_index < len(current["rules"]):
        current["rules"].pop(rule_index)
        save_config(current)
    return RedirectResponse(url="/rules", status_code=303)

@app.post("/rules/edit/{rule_index}")
def edit_rule(
    rule_index: int,
    name: str = Form(...),
    match_json: str = Form(...),
    delete_torrent: bool = Form(False),
    delete_files: bool = Form(False),
    include_incomplete: bool = Form(False),
    dry_run: bool = Form(False),
    auth=Depends(authenticate)
):
    try:
        import json
        match_criteria = json.loads(match_json)
    except Exception:
        match_criteria = {}

    current = load_config()
    if "rules" not in current:
        current["rules"] = []

    if 0 <= rule_index < len(current["rules"]):
        current["rules"][rule_index] = _rule_from_form(
            name, match_criteria, delete_torrent, delete_files,
            include_incomplete, dry_run,
        )
        save_config(current)

    return RedirectResponse(url="/rules", status_code=303)

@app.post("/api/rules/test")
async def api_rules_test(request: Request, auth=Depends(authenticate)):
    """Dry-run an unsaved rule against live torrents. Never deletes."""
    form = await request.form()
    try:
        import json
        match_criteria = json.loads(form.get("match_json") or "{}")
    except Exception:
        match_criteria = {}
    rule = _rule_from_form(
        form.get("name") or "",
        match_criteria,
        form.get("delete_torrent") == "on",
        form.get("delete_files") == "on",
        form.get("include_incomplete") == "on",
        True,
    )
    url, username, password = get_qb_client_settings()
    if not url:
        return {
            "status": "error",
            "message": "qBittorrent URL is not set in rules.yaml",
            "would_delete_count": 0,
        }
    try:
        client = QBClient(url, username, password)
        torrents = client.get_torrents()
    except Exception as e:
        return {
            "status": "error",
            "message": f"Could not read torrents from qBittorrent: {e}",
            "would_delete_count": 0,
        }
    result = preview_rule(
        rule,
        torrents,
        hours_since_now,
        load_cleanup_settings(load_config()),
        force_dry_run=True,
    )
    logger.info(
        "Test run of rule %s: %s would be deleted",
        result.get("rule_name") or "(unnamed rule)",
        result.get("would_delete_count", 0),
    )
    result["status"] = "invalid" if result.get("problems") else "ok"
    return result

@app.post("/cleanup")
def run_cleanup(auth=Depends(authenticate)):
    try:
        def web_logger(msg):
            action_logger.info(msg)

        def web_slog(msg):
            schedule_logger.info(msg)

        cleaner = Cleaner(logger=web_logger, schedule_logger=web_slog)
        cleaner.run(source="web")
        return {"status": "success", "message": "Cleanup completed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, kind: str = "action", auth=Depends(authenticate)):
    kind = _normalize_log_kind(kind)
    all_logs = get_recent_logs(200, kind=kind)
    template = jinja_env.get_template("logs.html")
    html_content = template.render(
        logs=all_logs,
        kind=kind,
        kind_label=LOG_KINDS[kind]["label"],
    )
    return HTMLResponse(content=html_content)

@app.get("/download-logs")
def download_logs(kind: str = "action", auth=Depends(authenticate)):
    try:
        from fastapi.responses import PlainTextResponse

        kind = _normalize_log_kind(kind)
        meta = LOG_KINDS[kind]
        log_files = get_log_files(kind)

        if not log_files:
            return PlainTextResponse("No log files found", status_code=404)

        combined_content = []

        for log_file in log_files:
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    file_content = f.read()

                if log_file != meta["path"]:
                    filename = os.path.basename(log_file)
                    combined_content.append(f"\n--- Archived Log: {filename} ---\n")

                combined_content.append(file_content)

            except Exception as e:
                combined_content.append(f"Error reading {os.path.basename(log_file)}: {e}\n")

        full_content = "".join(combined_content)

        if not full_content.strip():
            return PlainTextResponse("No logs available", status_code=404)

        return PlainTextResponse(
            content=full_content,
            headers={
                "Content-Disposition": f"attachment; filename={meta['download']}"
            }
        )

    except Exception as e:
        return PlainTextResponse(f"Error generating log file: {e}", status_code=500)

@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request, saved: int = 0, auth=Depends(authenticate)):
    service_status = get_service_status()
    status = get_schedule_status(load_config(), service_status=service_status)
    template = jinja_env.get_template("schedule.html")
    html_content = template.render(schedule=status, saved=bool(saved))
    return HTMLResponse(content=html_content)



@app.get("/api/drives")
def drives_api(auth=Depends(authenticate)):
    return {"drives": get_local_drives()}


@app.get("/api/qb-status")
def qb_status_api(auth=Depends(authenticate)):
    status = get_qb_status()
    return {
        "status": status["status"],
        "torrent_count": status["torrent_count"],
    }


@app.get("/api/schedule")
def schedule_api(auth=Depends(authenticate)):
    service_status = get_service_status()
    return get_schedule_status(load_config(), service_status=service_status)


@app.post("/schedule")
def update_schedule(
    interval_value: int = Form(...),
    interval_unit: str = Form("seconds"),
    enabled: str | None = Form(None),
    auth=Depends(authenticate)
):
    unit = interval_unit if interval_unit in ("seconds", "minutes", "hours") else "seconds"
    seconds = seconds_to_unit(max(1, interval_value), unit)
    seconds = max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, seconds))

    current = load_config()
    current["schedule"] = {
        "enabled": enabled == "on",
        "interval_seconds": seconds,
    }
    save_config(current)
    apply_interval_change(seconds)

    return RedirectResponse(url="/schedule?saved=1", status_code=303)


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request, auth=Depends(authenticate)):
    template = jinja_env.get_template("help.html")
    return HTMLResponse(content=template.render(update=check_for_update()))


@app.get("/api/updates")
def updates_api(refresh: int = 0, auth=Depends(authenticate)):
    return check_for_update(force=bool(refresh))


@app.post("/api/updates/install")
def install_github_update_api(request: Request, auth=Depends(authenticate)):
    if not is_local_client(request):
        return {
            "status": "error",
            "message": "Install from the web UI only works on the machine running qBittorrent Cleaner. On this server use the tray (Install GitHub update) or double-click update-from-github.cmd.",
        }
    cmd = os.path.join(BASE_DIR, "update-from-github.cmd")
    if not os.path.isfile(cmd):
        return {"status": "error", "message": "update-from-github.cmd is missing"}
    try:
        subprocess.Popen(["cmd.exe", "/c", cmd], cwd=BASE_DIR)
        return {
            "status": "started",
            "message": "Updater started. Accept the UAC prompt if it appears. The web UI will restart.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, auth=Depends(authenticate)):
    current = load_config()
    email_cfg = load_email_config(current)
    template = jinja_env.get_template("settings.html")
    html_content = template.render(
        config=current,
        cleanup=load_cleanup_settings(current),
        email=email_cfg,
        email_password_set=bool(email_cfg.get("password")),
        email_password_from_env=bool(email_cfg.get("password")) and not email_cfg.get("password_saved"),
        email_state=load_alert_state(),
        web_auto_start=(current.get("web") or {}).get("auto_start", True),
    )
    return HTMLResponse(content=html_content)


def _email_block_from_form(existing, form):
    """Merge posted email fields over the saved notifications.email block.

    A blank password field keeps the saved password (the UI never shows it).
    """
    block = dict(existing or {})
    block["enabled"] = form.get("email_enabled") == "on"
    block["smtp_host"] = (form.get("email_smtp_host") or "").strip()
    try:
        block["smtp_port"] = int(form.get("email_smtp_port") or 587)
    except ValueError:
        block["smtp_port"] = 587
    security = form.get("email_security") or "starttls"
    block["starttls"] = security == "starttls"
    block["use_ssl"] = security == "ssl"
    block["username"] = (form.get("email_username") or "").strip()
    new_password = form.get("email_password") or ""
    if form.get("email_password_clear") == "on":
        block["password"] = ""
    elif new_password:
        block["password"] = new_password
    else:
        block.setdefault("password", "")
    block["from_address"] = (form.get("email_from") or "").strip()
    block["to"] = split_addresses(form.get("email_to") or "")
    try:
        block["failure_threshold"] = max(1, int(form.get("email_failure_threshold") or 10))
    except ValueError:
        block["failure_threshold"] = 10
    try:
        block["cooldown_hours"] = max(0.0, float(form.get("email_cooldown_hours") or 6))
    except ValueError:
        block["cooldown_hours"] = 6
    if block["cooldown_hours"] == int(block["cooldown_hours"]):
        block["cooldown_hours"] = int(block["cooldown_hours"])
    block["send_recovery"] = form.get("email_send_recovery") == "on"
    block.setdefault("password_env", "QB_CLEANER_SMTP_PASSWORD")
    return block


@app.post("/api/notifications/test-email")
async def test_email_api(request: Request, auth=Depends(authenticate)):
    """Send a test email using the form values (unsaved edits included)."""
    try:
        form = await request.form()
        current = load_config()
        existing = ((current.get("notifications") or {}).get("email")) or {}
        if "email_smtp_host" in form:
            block = _email_block_from_form(existing, form)
        else:
            block = existing
        cfg = load_email_config({"notifications": {"email": block}})
        problems = validate_email_config(cfg)
        if problems:
            return {"status": "error", "message": "; ".join(problems)}
        send_test_email(cfg)
        logger.info(f"Test email sent to {', '.join(cfg['to'])}")
        return {"status": "success", "message": f"Test email sent to {', '.join(cfg['to'])}"}
    except Exception as e:
        logger.info(f"Test email failed: {e}")
        return {"status": "error", "message": f"Test email failed: {e}"}

@app.post("/settings")
async def update_settings(
    request: Request,
    qb_url: str = Form(...),
    qb_username: str = Form(""),
    qb_password: str = Form(""),
    web_port: int = Form(...),
    web_username: str = Form(...),
    web_password: str = Form(...),
    enable_auth: bool = Form(True),
    max_days: int = Form(30),
    enable_notifications: bool = Form(True),
    auth=Depends(authenticate)
):
    current = load_config()

    form = await request.form()
    updates = [
        (["qbittorrent", "url"], qb_url),
        (["web", "port"], int(web_port)),
        (["web", "username"], web_username),
        (["web", "password"], web_password),
        (["web", "enable_auth"], form.get("enable_auth") == "on"),
        (["web", "auto_start"], form.get("web_auto_start") == "on"),
        (["logging", "max_days"], int(max_days)),
        (["logging", "enable_notifications"], form.get("enable_notifications") == "on"),
    ]
    if qb_username:
        updates.append((["qbittorrent", "username"], qb_username))
    if qb_password:
        updates.append((["qbittorrent", "password"], qb_password))

    if "email_smtp_host" in form:
        block = _email_block_from_form(
            ((current.get("notifications") or {}).get("email")) or {}, form
        )
        email_root = ["notifications", "email"]
        for key in (
            "enabled", "smtp_host", "smtp_port", "starttls", "use_ssl",
            "username", "password", "from_address", "to",
            "failure_threshold", "cooldown_hours", "send_recovery",
            "password_env",
        ):
            if key in block:
                updates.append((email_root + [key], block[key]))

    if "max_deletes_per_run" in form:
        try:
            cap = int(form.get("max_deletes_per_run") or 20)
        except (TypeError, ValueError):
            cap = 20
        if cap < 0:
            cap = 20
        updates.append((["cleanup", "max_deletes_per_run"], cap))
        updates.append((["cleanup", "dry_run"], form.get("cleanup_dry_run") == "on"))

    with open(RULES_PATH, "r", encoding="utf-8") as f:
        original = f.read()
    updated, _changed = apply_yaml_updates(original, updates)
    if updated != original:
        with open(RULES_PATH, "w", encoding="utf-8") as f:
            f.write(updated)

    return RedirectResponse(url="/settings", status_code=303)

# -------------------------
# MAIN
# -------------------------

if __name__ == "__main__":
    print(f"Starting qBittorrent Cleaner Web on port {PORT}")
    print(f"Access at: http://localhost:{PORT}")
    if ENABLE_AUTH:
        print(f"Username: {WEB_USERNAME}")
    else:
        print("Authentication disabled")

    uvicorn.run(app, host="0.0.0.0", port=PORT)