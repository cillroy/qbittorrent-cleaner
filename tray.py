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
from cleaner import Cleaner

SERVICE_NAME = "QBCleanerService"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "qb-cleaner.log")
RULES_PATH = os.path.join(BASE_DIR, "rules.yaml")

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
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=color, outline="black", width=3)
    return img

ICON_RUNNING = make_icon("green")
ICON_STOPPED = make_icon("red")
ICON_UNKNOWN = make_icon("yellow")
ICON_NOT_ELEVATED = make_icon("blue")

# -------------------------
# SERVICE STATUS
# -------------------------

def get_status():
    if not is_elevated():
        return "Not Elevated"

    try:
        status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]

        if status in (2, 4):  # Start Pending or Running
            return "Running"
        elif status == 1:
            return "Stopped"
        elif status in (3, 5, 6, 7):
            return "Unknown"
        else:
            return "Unknown"
    except Exception:
        return "Unknown"

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
    cleaner = Cleaner(logger=lambda msg: icon.notify(msg))
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
    while icon.visible:
        status = get_status()

        if status == "Not Elevated":
            icon.icon = ICON_NOT_ELEVATED
        elif status == "Running":
            icon.icon = ICON_RUNNING
        elif status == "Stopped":
            icon.icon = ICON_STOPPED
        else:
            icon.icon = ICON_UNKNOWN

        icon.title = f"qBittorrent Cleaner ({status})"
        time.sleep(1)

# -------------------------
# TRAY ICON SETUP
# -------------------------

initial_status = get_status()

icon = pystray.Icon(
    "QBCleaner",
    ICON_NOT_ELEVATED if initial_status == "Not Elevated" else ICON_UNKNOWN,
    title=f"qBittorrent Cleaner ({initial_status})",
    menu=pystray.Menu(
        item("Run Cleanup Now", run_cleanup_now),
        item("Start Service", start_service),
        item("Stop Service", stop_service),
        item("Restart Service", restart_service),
        item("Open Log File", open_log),
        item("View Config File", open_rules),
        item("Open Folder", open_folder),
        item("Quit", quit_app)
    )
)

threading.Thread(target=status_watcher, args=(icon,), daemon=True).start()

icon.run()
