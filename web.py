# web.py - Web interface for qBittorrent Cleaner

import os
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
from cleaner import Cleaner
from qb_api import QBClient
from schedule import (
    get_schedule_status,
    apply_interval_change,
    seconds_to_unit,
    MIN_INTERVAL_SECONDS,
    MAX_INTERVAL_SECONDS,
)
import logging
from logging.handlers import TimedRotatingFileHandler

# -------------------------
# CONFIGURATION
# -------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
RULES_PATH = os.path.join(BASE_DIR, "rules.yaml")
LOG_PATH = os.path.join(BASE_DIR, "qb-cleaner.log")

# Load config
with open(RULES_PATH, "r") as f:
    config = yaml.safe_load(f)

web_config = config.get("web", {})
PORT = web_config.get("port", 8081)
WEB_USERNAME = web_config.get("username", "admin")
WEB_PASSWORD = web_config.get("password", "admin")
ENABLE_AUTH = web_config.get("enable_auth", True)

qb_config = config["qbittorrent"]
QB_URL = qb_config["url"]
QB_USERNAME = qb_config.get("username")
QB_PASSWORD = qb_config.get("password")

SERVICE_NAME = "QBCleanerService"

# -------------------------
# LOGGING SETUP
# -------------------------

logging_config = config.get("logging", {})
max_days = logging_config.get("max_days", 30)
enable_notifications = logging_config.get("enable_notifications", True)

# Set up logging with rotation
logger = logging.getLogger("qb_cleaner")
logger.setLevel(logging.INFO)

# Create handler for file logging with rotation
handler = TimedRotatingFileHandler(
    LOG_PATH,
    when="midnight",
    interval=1,
    backupCount=max_days
)
handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(handler)

# -------------------------
# FASTAPI SETUP
# -------------------------

app = FastAPI(title="qBittorrent Cleaner Web", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/static/logs", StaticFiles(directory=BASE_DIR), name="logs")
from jinja2 import Environment, FileSystemLoader
jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), cache_size=0)
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

def _log_file_sort_key(path):
    basename = os.path.basename(path)
    if basename == "qb-cleaner.log":
        return "9999-99-99"
    return basename.rsplit(".", 1)[-1]

def get_log_files():
    import glob
    log_files = glob.glob(os.path.join(BASE_DIR, "qb-cleaner.log*"))
    log_files.sort(key=_log_file_sort_key)
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

def get_qb_status():
    try:
        client = QBClient(QB_URL, QB_USERNAME, QB_PASSWORD)
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

def get_recent_logs(lines=50):
    try:
        log_files = get_log_files()

        if not log_files:
            return ["No log files found"]

        all_lines = []

        for log_file in log_files:
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    file_lines = f.readlines()

                # Add file separator for archived logs
                if log_file != LOG_PATH:
                    filename = os.path.basename(log_file)
                    all_lines.append(f"\n--- Archived Log: {filename} ---\n")

                # Add all lines from this file
                all_lines.extend(file_lines)

            except Exception as e:
                all_lines.append(f"Error reading {os.path.basename(log_file)}: {e}\n")
                continue

        # Return the most recent lines, newest first
        if all_lines:
            return list(reversed(all_lines[-lines:]))
        else:
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
        log_pattern = os.path.join(BASE_DIR, "qb-cleaner.log*")
        log_files = glob.glob(log_pattern)

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

def load_config():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(new_config):
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(new_config, f, default_flow_style=False, sort_keys=False)

# -------------------------
# ROUTES
# -------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, auth=Depends(authenticate)):
    service_status = get_service_status()
    qb_status = get_qb_status()
    recent_logs = get_recent_logs(10)
    deletion_stats = get_deletion_stats()
    schedule_status = get_schedule_status(load_config(), service_status=service_status)

    template = jinja_env.get_template("dashboard.html")
    html_content = template.render(
        service_status=service_status,
        qb_status=qb_status,
        recent_logs=recent_logs,
        deletion_stats=deletion_stats,
        schedule=schedule_status,
        current_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    return HTMLResponse(content=html_content)

@app.get("/rules", response_class=HTMLResponse)
def rules_page(request: Request, auth=Depends(authenticate)):
    current = load_config()
    template = jinja_env.get_template("rules.html")
    html_content = template.render(
        rules=current.get("rules", []),
        qb_config=current.get("qbittorrent", {})
    )
    return HTMLResponse(content=html_content)

@app.post("/rules/add")
def add_rule(
    name: str = Form(...),
    match_json: str = Form(...),
    delete_torrent: bool = Form(False),
    delete_files: bool = Form(False),
    auth=Depends(authenticate)
):
    try:
        import json
        match_criteria = json.loads(match_json)
    except:
        match_criteria = {}

    new_rule = {
        "name": name,
        "match": match_criteria,
        "action": {
            "delete_torrent": delete_torrent,
            "delete_files": delete_files
        }
    }

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
    auth=Depends(authenticate)
):
    try:
        import json
        match_criteria = json.loads(match_json)
    except:
        match_criteria = {}

    current = load_config()
    if "rules" not in current:
        current["rules"] = []

    if 0 <= rule_index < len(current["rules"]):
        current["rules"][rule_index] = {
            "name": name,
            "match": match_criteria,
            "action": {
                "delete_torrent": delete_torrent,
                "delete_files": delete_files
            }
        }
        save_config(current)

    return RedirectResponse(url="/rules", status_code=303)

@app.post("/cleanup")
def run_cleanup(auth=Depends(authenticate)):
    try:
        def web_logger(msg):
            logger.info(msg)

        cleaner = Cleaner(logger=web_logger)
        cleaner.run(source="web")
        return {"status": "success", "message": "Cleanup completed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, auth=Depends(authenticate)):
    all_logs = get_recent_logs(200)
    template = jinja_env.get_template("logs.html")
    html_content = template.render(logs=all_logs)
    return HTMLResponse(content=html_content)

@app.get("/download-logs")
def download_logs(auth=Depends(authenticate)):
    try:
        from fastapi.responses import PlainTextResponse

        log_files = get_log_files()

        if not log_files:
            return PlainTextResponse("No log files found", status_code=404)

        combined_content = []

        for log_file in log_files:
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    file_content = f.read()

                # Add file separator for archived logs
                if log_file != LOG_PATH:
                    filename = os.path.basename(log_file)
                    combined_content.append(f"\n--- Archived Log: {filename} ---\n")

                # Add all content from this file
                combined_content.append(file_content)

            except Exception as e:
                combined_content.append(f"Error reading {os.path.basename(log_file)}: {e}\n")

        # Join all content
        full_content = "".join(combined_content)

        if not full_content.strip():
            return PlainTextResponse("No logs available", status_code=404)

        # Return as downloadable text file
        return PlainTextResponse(
            content=full_content,
            headers={
                "Content-Disposition": "attachment; filename=qb-cleaner-full.log"
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


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, auth=Depends(authenticate)):
    template = jinja_env.get_template("settings.html")
    html_content = template.render(config=load_config())
    return HTMLResponse(content=html_content)

@app.post("/settings")
def update_settings(
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

    current.setdefault("qbittorrent", {})
    current["qbittorrent"]["url"] = qb_url
    if qb_username:
        current["qbittorrent"]["username"] = qb_username
    if qb_password:
        current["qbittorrent"]["password"] = qb_password

    current.setdefault("web", {})
    current["web"]["port"] = web_port
    current["web"]["username"] = web_username
    current["web"]["password"] = web_password
    current["web"]["enable_auth"] = enable_auth

    current.setdefault("logging", {})
    current["logging"]["max_days"] = max_days
    current["logging"]["enable_notifications"] = enable_notifications

    save_config(current)

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