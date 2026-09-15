# service.py - A Windows service that periodically runs the Cleaner to manage qBittorrent torrents based on rules defined in a YAML config file.

import win32serviceutil
import win32service
import win32event
import servicemanager
import time
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from plyer import notification
from cleaner import Cleaner
from schedule import seconds_until_next_run, record_run

# -------------------------
# LOGGING SETUP
# -------------------------

# FIX: Use absolute path so Windows service doesn't write to System32
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "qb-cleaner.log")

# Load config for logging settings (before creating logger)
import yaml
config_path = os.path.join(BASE_DIR, "rules.yaml")
with open(config_path, "r") as f:
    config = yaml.safe_load(f)
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

# Create handler for Windows Event Log
class EventLogHandler(logging.Handler):
    def emit(self, record):
        servicemanager.LogInfoMsg(self.format(record))

event_handler = EventLogHandler()
event_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(event_handler)

def log(msg):
    logger.info(msg)

def notify(msg):
    if enable_notifications:
        notification.notify(
            title="qBittorrent Cleaner",
            message=msg,
            app_name="qBittorrent Cleaner"
        )


class QBCleanerService(win32serviceutil.ServiceFramework):
    _svc_name_ = "QBCleanerService"
    _svc_display_name_ = "qBittorrent Auto Cleaner"
    _svc_description_ = "Automatically cleans torrents based on rules.yaml"

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):
        log("Service stop requested")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

    def _wait(self, timeout_ms):
        rc = win32event.WaitForSingleObject(self.stop_event, int(timeout_ms))
        return rc == win32event.WAIT_OBJECT_0

    def SvcDoRun(self):
        log("QBCleanerService starting...")

        # REQUIRED: Tell Windows the service is running
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)

        log("QBCleanerService started")

        while True:
            try:
                wait_s = seconds_until_next_run()
            except Exception as e:
                log(f"Error reading schedule: {e}")
                if self._wait(5000):
                    log("Stop event received, exiting service loop")
                    break
                continue

            if wait_s is None:
                # Schedule is paused
                if self._wait(1000):
                    log("Stop event received, exiting service loop")
                    break
                continue

            if wait_s > 0:
                timeout_ms = min(max(int(wait_s * 1000), 50), 1000)
                if self._wait(timeout_ms):
                    log("Stop event received, exiting service loop")
                    break
                continue

            try:
                cleaner = Cleaner(logger=log, notifier=notify)
            except Exception as e:
                log(f"Error creating cleaner: {e}")
                try:
                    record_run(source="service", deleted=0, error=str(e), scheduled=True)
                except Exception:
                    pass
                if self._wait(5000):
                    log("Stop event received, exiting service loop")
                    break
                continue

            try:
                cleaner.run(source="service")
            except Exception as e:
                log(f"Error during cleaner run: {e}")

            # Always yield so a failed state write cannot tight-loop
            if self._wait(1000):
                log("Stop event received, exiting service loop")
                break


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(QBCleanerService)
