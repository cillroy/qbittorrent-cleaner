# qBittorrent Cleaner Tray Application

import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import subprocess
import os
import win32serviceutil
import threading
import time
import ctypes
import logging
import sys
import yaml
from plyer import notification
from cleaner import Cleaner

SERVICE_NAME = "QBCleanerService"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "qb-cleaner.log")
RULES_PATH = os.path.join(BASE_DIR, "rules.yaml")
DEBUG_LOG = os.path.join(BASE_DIR, "tray-debug.log")

# -------------------------
# DEBUG FLAG
# -------------------------

ENABLE_DEBUG = "debug" in sys.argv

if ENABLE_DEBUG:
    logging.basicConfig(
        filename=DEBUG_LOG,
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("Debug logging enabled")
else:
    logging.basicConfig(level=logging.CRITICAL)

# -------------------------
# LOAD CONFIG
# -------------------------

with open(RULES_PATH, "r") as f:
    config = yaml.safe_load(f)
logging_config = config.get("logging", {})
enable_notifications = logging_config.get("enable_notifications", True)

# -------------------------
# ELEVATION CHECK
# -------------------------

def is_elevated():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

# -------------------------
# ICON GENERATION
# -------------------------

def make_icon(color):
    # Use 32x32 for better tray icon compatibility
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 28, 28), fill=color, outline="black", width=2)
    return img

def fresh_icon(color):
    # Force a new icon handle so Windows Explorer repaints
    return make_icon(color)

# Pre-generated colors
COLOR_MAP = {
    "Running": "green",
    "Stopped": "red",
    "Unknown": "yellow",
    "Not Elevated": "blue"
}

# -------------------------
# SERVICE STATUS
# -------------------------

def get_status():
    if not is_elevated():
        return "Not Elevated"

    try:
        status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
        raw = status[1]

        # Service status codes:
        # 1 = SERVICE_STOPPED
        # 2 = SERVICE_START_PENDING
        # 3 = SERVICE_STOP_PENDING
        # 4 = SERVICE_RUNNING
        # 5 = SERVICE_CONTINUE_PENDING
        # 6 = SERVICE_PAUSE_PENDING
        # 7 = SERVICE_PAUSED

        if raw == 4:
            return "Running"
        elif raw == 1:
            return "Stopped"
        elif raw in (2, 3, 5, 6):
            return "Unknown"  # Transitioning
        else:
            return "Unknown"

    except Exception as e:
        # Service might not exist or other error
        return "Unknown"

def status_text():
    s = get_status()
    return {
        "Running": "🟢 Running",
        "Stopped": "🔴 Stopped",
        "Not Elevated": "🔵 Not Elevated",
        "Unknown": "🟡 Unknown"
    }.get(s, "🟡 Unknown")

# -------------------------
# MENU ACTIONS
# -------------------------

def start_service(icon, item):
    if not is_elevated():
        icon.notify("Tray app is not elevated — cannot control service")
        return
    win32serviceutil.StartService(SERVICE_NAME)
    icon.notify("Service started")

def stop_service(icon, item):
    if not is_elevated():
        icon.notify("Tray app is not elevated — cannot control service")
        return
    win32serviceutil.StopService(SERVICE_NAME)
    icon.notify("Service stopped")

def restart_service(icon, item):
    if not is_elevated():
        icon.notify("Tray app is not elevated — cannot control service")
        return
    win32serviceutil.RestartService(SERVICE_NAME)
    icon.notify("Service restarted")

def run_cleanup_now(icon, item):
    def combined_logger(msg):
        icon.notify(msg)
        if enable_notifications:
            notification.notify(
                title="qBittorrent Cleaner",
                message=msg,
                app_name="qBittorrent Cleaner"
            )

    cleaner = Cleaner(logger=combined_logger, notifier=combined_logger)
    cleaner.run_once()
    icon.notify("Cleanup executed")

def open_log(icon, item):
    if os.path.exists(LOG_PATH):
        os.startfile(LOG_PATH)
    else:
        icon.notify("Log file not found")

def open_rules(icon, item):
    if os.path.exists(RULES_PATH):
        os.startfile(RULES_PATH)
    else:
        icon.notify("rules.yaml not found")

def open_folder(icon, item):
    os.startfile(BASE_DIR)

def quit_app(icon, item):
    icon.stop()

# -------------------------
# ICON AUTO-REFRESH THREAD
# -------------------------

def status_watcher(icon):
    last_status = None

    while icon.visible:
        s = get_status()

        # Debug logging
        if ENABLE_DEBUG:
            logging.debug(f"Service status: {s}")

        # Only recreate icon when status changes
        if s != last_status:
            color = COLOR_MAP.get(s, "yellow")
            new_icon = fresh_icon(color)
            icon.icon = new_icon
            # Force update
            icon.update_menu()
            last_status = s

            if ENABLE_DEBUG:
                logging.debug(f"Updated icon to color: {color} for status: {s}")

        icon.title = f"qBittorrent Cleaner ({status_text()})"

        time.sleep(1)

# -------------------------
# TRAY ICON SETUP
# -------------------------

icon = pystray.Icon(
    "QBCleaner",
    fresh_icon("yellow"),
    title=f"qBittorrent Cleaner ({status_text()})",
    menu=pystray.Menu(
        item(lambda _: f"Status: {status_text()}", None, enabled=False),
        item("Run Cleanup Now", run_cleanup_now),
        item("Refresh Status", lambda icon, item: None),  # Placeholder for refresh
        item("Start Service", start_service),
        item("Stop Service", stop_service),
        item("Restart Service", restart_service),
        item("Open Log File", open_log),
        item("View Config File", open_rules),
        item("Open Folder", open_folder),
        item("Quit", quit_app)
    )
)

def start_watcher_after_icon():
    time.sleep(0.5)
    threading.Thread(target=status_watcher, args=(icon,), daemon=True).start()

threading.Thread(target=start_watcher_after_icon, daemon=True).start()

icon.run()
