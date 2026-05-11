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
import socket
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
# WEB SERVER MANAGEMENT
# -------------------------

web_process = None  # Global variable to track web server process

def get_web_status():
    web_config = config.get("web", {})
    port = web_config.get("port", 8081)
    logging.debug(f"Checking web server status on port {port}")

    try:
        # Try to connect to the web server port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        logging.debug(f"Port {port} connection result: {result}")

        if result == 0:
            logging.debug(f"Web server detected as Running on port {port}")
            return "Running"
        else:
            logging.debug(f"Web server detected as Stopped (port {port} not responding)")
            return "Stopped"
    except Exception as e:
        logging.debug(f"Error checking web server status: {e}")
        return "Unknown"

def web_status_text():
    s = get_web_status()
    return {
        "Running": "🌐 Web: Running",
        "Stopped": "🌐 Web: Stopped",
        "Unknown": "🌐 Web: Unknown"
    }.get(s, "🌐 Web: Unknown")

def start_web_server(icon, item):
    global web_process
    logging.debug("start_web_server() called")

    current_status = get_web_status()
    logging.debug(f"Current web server status: {current_status}")

    if current_status == "Running":
        logging.debug("Web server already running, skipping start")
        icon.notify("Web server is already running")
        return

    try:
        logging.debug(f"Starting web server subprocess with: {sys.executable} web.py")
        logging.debug(f"Working directory: {BASE_DIR}")

        # Start web server as subprocess
        web_process = subprocess.Popen(
            [sys.executable, "web.py"],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        logging.debug(f"Subprocess created with PID: {web_process.pid}")

        logging.debug("Waiting 2 seconds for web server to start...")
        time.sleep(2)  # Give it time to start

        final_status = get_web_status()
        logging.debug(f"Final web server status after start attempt: {final_status}")

        if final_status == "Running":
            logging.debug("Web server start successful")
            icon.notify("Web server started successfully")
        else:
            logging.debug("Web server start failed - port not responding")
            icon.notify("Web server failed to start")
    except Exception as e:
        logging.debug(f"Exception during web server start: {e}")
        icon.notify(f"Failed to start web server: {str(e)}")

def stop_web_server(icon, item):
    global web_process
    logging.debug("stop_web_server() called")

    current_status = get_web_status()
    logging.debug(f"Current web server status: {current_status}")

    if current_status == "Stopped":
        logging.debug("Web server already stopped, skipping stop")
        icon.notify("Web server is already stopped")
        return

    try:
        logging.debug(f"Web process object: {web_process}")
        if web_process:
            logging.debug(f"Web process PID: {web_process.pid}, poll status: {web_process.poll()}")

        # Try to terminate the process gracefully first
        if web_process and web_process.poll() is None:
            logging.debug("Terminating web server process...")
            web_process.terminate()
            web_process.wait(timeout=5)
            logging.debug("Web server process terminated")
            web_process = None
        else:
            logging.debug("No active web server process found")

        # Double-check if it's actually stopped
        logging.debug("Waiting 1 second then checking final status...")
        time.sleep(1)
        final_status = get_web_status()
        logging.debug(f"Final web server status after stop attempt: {final_status}")

        if final_status == "Stopped":
            logging.debug("Web server stop successful")
            icon.notify("Web server stopped successfully")
        else:
            logging.debug("Web server stop may have failed - still responding on port")
            icon.notify("Web server may still be running")
    except Exception as e:
        logging.debug(f"Exception during web server stop: {e}")
        icon.notify(f"Error stopping web server: {str(e)}")

def open_web_interface(icon, item):
    logging.debug("open_web_interface() called")

    web_config = config.get("web", {})
    port = web_config.get("port", 8081)
    url = f"http://localhost:{port}"
    logging.debug(f"Opening web interface URL: {url}")

    try:
        import webbrowser
        webbrowser.open(url)
        logging.debug("Browser opened successfully")
        icon.notify(f"Opened web interface: {url}")
    except Exception as e:
        logging.debug(f"Failed to open browser: {e}")
        icon.notify(f"Failed to open browser: {str(e)}")

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
    title=f"qBittorrent Cleaner (Service: {status_text()} | {web_status_text()})",
    menu=pystray.Menu(
        item(lambda _: f"Service: {status_text()}", None, enabled=False),
        item(lambda _: f"{web_status_text()}", None, enabled=False),
        item("---", None, enabled=False),  # Separator
        item("Run Cleanup Now", run_cleanup_now),
        item("Refresh Status", lambda icon, item: None),  # Placeholder for refresh
        item("---", None, enabled=False),  # Separator
        item("Start Service", start_service),
        item("Stop Service", stop_service),
        item("Restart Service", restart_service),
        item("---", None, enabled=False),  # Separator
        item("Start Web Server", start_web_server),
        item("Stop Web Server", stop_web_server),
        item("Open Web Interface", open_web_interface),
        item("---", None, enabled=False),  # Separator
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
