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
from cleaner import Cleaner

SERVICE_NAME = "QBCleanerService"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "qb-cleaner.log")
RULES_PATH = os.path.join(BASE_DIR, "rules.yaml")
DEBUG_LOG = os.path.join(BASE_DIR, "tray-debug.log")

# -------------------------
# DEBUG LOGGING
# -------------------------

logging.basicConfig(
    filename=DEBUG_LOG,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logging.info("Tray starting up")

# -------------------------
# ELEVATION CHECK
# -------------------------

def is_elevated():
    try:
        elevated = ctypes.windll.shell32.IsUserAnAdmin() != 0
        logging.debug(f"is_elevated() -> {elevated}")
        return elevated
    except Exception as e:
        logging.error(f"Elevation check failed: {e}")
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
        logging.debug("Status: Not Elevated")
        return "Not Elevated"

    try:
        raw = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
        logging.debug(f"Raw service status code: {raw}")

        if raw in (2, 4):
            logging.debug("Interpreted status: Running")
            return "Running"
        elif raw == 1:
            logging.debug("Interpreted status: Stopped")
            return "Stopped"
        else:
            logging.debug("Interpreted status: Unknown")
            return "Unknown"

    except Exception as e:
        logging.error(f"Error querying service status: {e}")
        return "Unknown"

def status_text():
    s = get_status()
    if s == "Running":
        return "🟢 Running"
    elif s == "Stopped":
        return "🔴 Stopped"
    elif s == "Not Elevated":
        return "🔵 Not Elevated"
    else:
        return "🟡 Unknown"

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
    logging.info("Status watcher thread started")

    while icon.visible:
        s = get_status()
        logging.debug(f"Watcher sees status: {s}")

        try:
            if s == "Not Elevated":
                icon.icon = ICON_NOT_ELEVATED
                logging.debug("Icon set to BLUE (Not Elevated)")
            elif s == "Running":
                icon.icon = ICON_RUNNING
                logging.debug("Icon set to GREEN (Running)")
            elif s == "Stopped":
                icon.icon = ICON_STOPPED
                logging.debug("Icon set to RED (Stopped)")
            else:
                icon.icon = ICON_UNKNOWN
                logging.debug("Icon set to YELLOW (Unknown)")

            new_title = f"qBittorrent Cleaner ({status_text()})"
            icon.title = new_title
            logging.debug(f"Tooltip updated to: {new_title}")

            icon.update_menu()
            logging.debug("Menu updated")

        except Exception as e:
            logging.error(f"Error updating icon/menu: {e}")

        time.sleep(1)

# -------------------------
# TRAY ICON SETUP
# -------------------------

icon = pystray.Icon(
    "QBCleaner",
    ICON_UNKNOWN,
    title=f"qBittorrent Cleaner ({status_text()})",
    menu=pystray.Menu(
        item(lambda _: f"Status: {status_text()}", None, enabled=False),
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

# -------------------------
# START ICON, THEN START WATCHER THREAD
# -------------------------

def start_watcher_after_icon():
    # Give pystray time to initialize the Windows message loop
    time.sleep(0.5)
    threading.Thread(target=status_watcher, args=(icon,), daemon=True).start()

threading.Thread(target=start_watcher_after_icon, daemon=True).start()

icon.run()
