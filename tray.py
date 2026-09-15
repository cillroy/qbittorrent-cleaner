# qBittorrent Cleaner Tray Application

import os
import sys
import traceback

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CRASH_LOG = os.path.join(_BASE_DIR, "tray-crash.log")


def _log_crash(prefix, exc=None):
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as fh:
            fh.write(prefix + "\n")
            traceback.print_exc(file=fh)
            fh.write("\n")
    except OSError:
        pass


def _excepthook(exc_type, exc, tb):
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as fh:
            fh.write("unhandled exception\n")
            traceback.print_exception(exc_type, exc, tb, file=fh)
            fh.write("\n")
    except OSError:
        pass
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _excepthook

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
from logutil import setup_logging, ACTION_LOG, SCHEDULE_LOG

SERVICE_NAME = "QBCleanerService"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = ACTION_LOG
SCHEDULE_LOG_PATH = SCHEDULE_LOG
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

config = {}
enable_notifications = True

def load_config():
    global config, enable_notifications
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        enable_notifications = bool(
            (config.get("logging") or {}).get("enable_notifications", True)
        )
    except Exception as e:
        logging.debug(f"Failed to reload config: {e}")
    return config

load_config()
_max_days = 30
try:
    _max_days = int((config.get("logging") or {}).get("max_days", 30))
except (TypeError, ValueError):
    _max_days = 30
action_file_logger, schedule_file_logger = setup_logging(_max_days)

def get_web_port():
    load_config()
    try:
        return int((config.get("web") or {}).get("port", 8081))
    except (TypeError, ValueError):
        return 8081

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

def query_service_status():
    """Service state only — does not require elevation to read."""
    try:
        raw = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
        if raw == 4:
            return "Running"
        if raw == 1:
            return "Stopped"
        return "Unknown"
    except Exception:
        return "Unknown"


def get_status():
    if not is_elevated():
        return "Not Elevated"
    return query_service_status()


def service_dot(status=None):
    status = status or query_service_status()
    return {
        "Running": "🟢",
        "Stopped": "🔴",
        "Unknown": "🟡",
        "Not Elevated": "🔵",
    }.get(status, "🟡")


def status_text():
    if not is_elevated():
        svc = query_service_status()
        return f"{service_dot(svc)} {svc} (tray not elevated)"
    s = query_service_status()
    return f"{service_dot(s)} {s}"


def service_menu_text(_=None):
    s = query_service_status()
    return f"{service_dot(s)}  Service: {s}"


def web_dot(status=None):
    status = status or get_web_status()
    return {
        "Running": "🟢",
        "Stopped": "🔴",
        "Unknown": "🟡",
    }.get(status, "🟡")


def web_status_text():
    s = get_web_status()
    port = get_web_port()
    if s == "Running":
        return f"{web_dot(s)} Web: Running  :{port}"
    if s == "Stopped":
        return f"{web_dot(s)} Web: Stopped  :{port}"
    return f"{web_dot(s)} Web: Unknown  :{port}"


def web_menu_text(_=None):
    return web_status_text()


def noop(_icon=None, _item=None):
    return None

# -------------------------
# WEB SERVER MANAGEMENT
# -------------------------

web_process = None  # Global variable to track web server process

def get_web_status():
    port = get_web_port()
    logging.debug(f"Checking web server status on port {port}")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        logging.debug(f"Port {port} connection result: {result}")
        return "Running" if result == 0 else "Stopped"
    except Exception as e:
        logging.debug(f"Error checking web server status: {e}")
        return "Unknown"


def _kill_web_processes():
    """Stop any python process whose command line includes web.py."""
    killed = 0
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        wmi = win32com.client.GetObject("winmgmts:")
        for proc in wmi.ExecQuery(
            "SELECT ProcessId, CommandLine FROM Win32_Process "
            "WHERE Name='python.exe' OR Name='pythonw.exe'"
        ):
            cmd = proc.CommandLine or ""
            if "web.py" in cmd:
                logging.debug(f"Terminating web.py PID {proc.ProcessId}")
                proc.Terminate()
                killed += 1
    except Exception as e:
        logging.debug(f"WMI web stop failed: {e}")
    return killed


def start_web_server(icon, item, quiet=False):
    global web_process
    logging.debug("start_web_server() called")

    current_status = get_web_status()
    logging.debug(f"Current web server status: {current_status}")

    if current_status == "Running":
        logging.debug("Web server already running, skipping start")
        if not quiet:
            notify_now(icon, f"Web already running on :{get_web_port()}")
        return True

    try:
        logging.debug(f"Starting web server subprocess with: {sys.executable} web.py")
        logging.debug(f"Working directory: {BASE_DIR}")

        web_process = subprocess.Popen(
            [sys.executable, "web.py"],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        logging.debug(f"Subprocess created with PID: {web_process.pid}")

        wait_until(lambda: get_web_status() == "Running", timeout=8.0)

        final_status = get_web_status()
        logging.debug(f"Final web server status after start attempt: {final_status}")

        if final_status == "Running":
            logging.debug("Web server start successful")
            if not quiet:
                notify_now(icon, f"Web started — running on :{get_web_port()}")
            return True

        logging.debug("Web server start failed - port not responding")
        if not quiet:
            notify_now(icon, "Web failed to start (port not responding)")
        return False
    except Exception as e:
        logging.debug(f"Exception during web server start: {e}")
        if not quiet:
            notify_now(icon, f"Failed to start web server: {str(e)}")
        return False

def stop_web_server(icon, item, quiet=False):
    global web_process
    logging.debug("stop_web_server() called")

    current_status = get_web_status()
    logging.debug(f"Current web server status: {current_status}")

    if current_status == "Stopped":
        logging.debug("Web server already stopped, skipping stop")
        if not quiet:
            notify_now(icon, "Web is already stopped")
        return True

    try:
        logging.debug(f"Web process object: {web_process}")
        if web_process:
            logging.debug(f"Web process PID: {web_process.pid}, poll status: {web_process.poll()}")

        if web_process and web_process.poll() is None:
            logging.debug("Terminating web server process...")
            web_process.terminate()
            web_process.wait(timeout=5)
            logging.debug("Web server process terminated")
            web_process = None
        else:
            logging.debug("No tray-owned web process; scanning for web.py")
            _kill_web_processes()

        time.sleep(1)
        if get_web_status() != "Stopped":
            _kill_web_processes()
            time.sleep(1)

        final_status = get_web_status()
        logging.debug(f"Final web server status after stop attempt: {final_status}")

        if final_status == "Stopped":
            logging.debug("Web server stop successful")
            if not quiet:
                notify_now(icon, "Web stopped")
            return True

        logging.debug("Web server stop may have failed - still responding on port")
        if not quiet:
            notify_now(icon, "Web may still be running")
        return False
    except Exception as e:
        logging.debug(f"Exception during web server stop: {e}")
        if not quiet:
            notify_now(icon, f"Error stopping web server: {str(e)}")
        return False


def restart_web_server(icon, item):
    logging.debug("restart_web_server() called")
    if get_web_status() == "Running":
        if not stop_web_server(icon, item, quiet=True):
            notify_now(icon, "Web restart failed — could not stop the old process")
            return
        wait_until(lambda: get_web_status() == "Stopped", timeout=8.0)

    if start_web_server(icon, item, quiet=True):
        notify_now(icon, f"Web restarted — running on :{get_web_port()}")
    else:
        notify_now(icon, "Web restart failed (port not responding)")

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
        notify_now(icon, f"Opened {url}")
    except Exception as e:
        logging.debug(f"Failed to open browser: {e}")
        notify_now(icon, f"Failed to open browser: {str(e)}")

# -------------------------
# MENU ACTIONS
# -------------------------

def start_service(icon, item):
    if not is_elevated():
        notify_now(icon, "Tray is not elevated - cannot control the Windows service")
        return
    win32serviceutil.StartService(SERVICE_NAME)
    wait_until(lambda: query_service_status() == "Running")
    notify_now(icon, f"Windows service is {query_service_status()}")

def stop_service(icon, item):
    if not is_elevated():
        notify_now(icon, "Tray is not elevated - cannot control the Windows service")
        return
    win32serviceutil.StopService(SERVICE_NAME)
    wait_until(lambda: query_service_status() == "Stopped")
    notify_now(icon, f"Windows service is {query_service_status()}")

def restart_service(icon, item):
    if not is_elevated():
        notify_now(icon, "Tray is not elevated - cannot control the Windows service")
        return
    win32serviceutil.RestartService(SERVICE_NAME)
    wait_until(lambda: query_service_status() == "Running")
    notify_now(icon, f"Windows service is {query_service_status()}")


def _service_running(_item=None):
    return is_elevated() and query_service_status() == "Running"


def _service_stopped(_item=None):
    return is_elevated() and query_service_status() == "Stopped"


def _web_running(_item=None):
    return get_web_status() == "Running"


def _web_stopped(_item=None):
    return get_web_status() != "Running"


def explain_not_elevated(icon, _item=None):
    icon.notify("Restart the tray as Administrator to start/stop the Windows service")

def run_cleanup_now(icon, item):
    def action_logger(msg):
        action_file_logger.info(msg)
        icon.notify(msg)
        if enable_notifications:
            notification.notify(
                title="qBittorrent Cleaner",
                message=msg,
                app_name="qBittorrent Cleaner"
            )

    def schedule_logger(msg):
        schedule_file_logger.info(msg)

    cleaner = Cleaner(
        logger=action_logger,
        schedule_logger=schedule_logger,
        notifier=action_logger,
    )
    cleaner.run_once(source="tray")
    icon.notify("Cleanup executed")

def open_log(icon, item):
    if os.path.exists(LOG_PATH):
        os.startfile(LOG_PATH)
    else:
        icon.notify("Action log not found yet")

def open_schedule_log(icon, item):
    if os.path.exists(SCHEDULE_LOG_PATH):
        os.startfile(SCHEDULE_LOG_PATH)
    else:
        icon.notify("Schedule log not found yet")

def open_rules(icon, item):
    if os.path.exists(RULES_PATH):
        os.startfile(RULES_PATH)
    else:
        icon.notify("rules.yaml not found")

def open_folder(icon, item):
    os.startfile(BASE_DIR)

def quit_app(icon, item):
    icon.stop()


def check_updates(icon, item):
    from update_check import check_for_update
    result = check_for_update(force=True)
    if result.get("update_available"):
        notify_now(icon, f"Update available: {result['local']} → {result['latest']}")
        try:
            import webbrowser
            if result.get("release_url"):
                webbrowser.open(result["release_url"])
        except Exception:
            pass
        return
    if result.get("error"):
        notify_now(icon, result.get("message") or "Could not check for updates")
        return
    if result.get("latest"):
        notify_now(icon, f"Up to date ({result['local']})")
    else:
        notify_now(icon, result.get("message") or f"No GitHub releases yet (local {result['local']})")

# -------------------------
# ICON AUTO-REFRESH THREAD
# -------------------------

def overall_status():
    """Green only when both the Windows service and web UI are running."""
    svc = query_service_status()
    web = get_web_status()
    if svc == "Running" and web == "Running":
        return "Running"
    if svc == "Stopped" and web == "Stopped":
        return "Stopped"
    return "Unknown"


def icon_color_name():
    return COLOR_MAP.get(overall_status(), "yellow")


def icon_title_text():
    return f"qBittorrent Cleaner  {status_text()}  |  {web_status_text()}"


def refresh_appearance(icon):
    """Paint current status onto the tray icon before any toast is shown.

    Windows notification toasts reuse the current tray HICON, so notifying
    before this runs shows the previous (stale) color.
    """
    icon.icon = fresh_icon(icon_color_name())
    icon.title = icon_title_text()
    icon.update_menu()


def notify_now(icon, message):
    refresh_appearance(icon)
    time.sleep(0.15)
    icon.notify(message)


def wait_until(predicate, timeout=8.0, interval=0.25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def status_watcher(icon):
    last_key = None
    time.sleep(1.0)

    while True:
        try:
            if not icon._running:
                break
            if not icon.visible:
                time.sleep(0.2)
                continue

            svc = query_service_status()
            web = get_web_status()
            key = (svc, web, overall_status())

            if ENABLE_DEBUG:
                logging.debug(f"Service={svc} web={web} overall={key[2]} elevated={is_elevated()}")

            if key != last_key:
                refresh_appearance(icon)
                last_key = key
                if ENABLE_DEBUG:
                    logging.debug(f"Updated icon to {icon_color_name()}")

            time.sleep(1)
        except Exception:
            _log_crash("status_watcher failed")
            time.sleep(2)

# -------------------------
# TRAY ICON SETUP
# -------------------------

def iter_menu():
    yield item(service_menu_text, noop)
    yield item(web_menu_text, open_web_interface)
    if not is_elevated():
        yield item("🔵  Tray not elevated", explain_not_elevated)
    yield pystray.Menu.SEPARATOR
    yield item("Open web interface", open_web_interface, default=True)
    yield item("Run cleanup now", run_cleanup_now)
    yield item("Check for updates", check_updates)
    yield pystray.Menu.SEPARATOR
    yield item("Service", pystray.Menu(
        item("Start", start_service, enabled=_service_stopped),
        item("Stop", stop_service, enabled=_service_running),
        item("Restart", restart_service, enabled=_service_running),
    ))
    yield item("Web", pystray.Menu(
        item("Start", start_web_server, enabled=_web_stopped),
        item("Stop", stop_web_server, enabled=_web_running),
        item("Restart", restart_web_server, enabled=_web_running),
        pystray.Menu.SEPARATOR,
        item("Open in browser", open_web_interface),
    ))
    yield item("Open", pystray.Menu(
        item("Action log", open_log),
        item("Schedule log", open_schedule_log),
        item("rules.yaml", open_rules),
        item("Install folder", open_folder),
    ))
    yield pystray.Menu.SEPARATOR
    yield item("Quit", quit_app)


icon = pystray.Icon(
    "QBCleaner",
    fresh_icon(icon_color_name()),
    title=icon_title_text(),
    menu=pystray.Menu(iter_menu),
)

def on_icon_ready(icon):
    try:
        icon.visible = True
        threading.Thread(target=status_watcher, args=(icon,), daemon=True).start()
    except Exception:
        _log_crash("on_icon_ready failed")
        raise


if __name__ == "__main__":
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as fh:
            fh.write(
                f"start python={sys.executable} file={__file__} cwd={os.getcwd()} "
                f"elevated={is_elevated()}\n"
            )
        icon.run(setup=on_icon_ready)
        with open(_CRASH_LOG, "a", encoding="utf-8") as fh:
            fh.write("icon.run() returned (tray stopped)\n")
    except Exception:
        _log_crash("icon.run() failed")
        raise
