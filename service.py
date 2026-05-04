# service.py - A Windows service that periodically runs the Cleaner to manage qBittorrent torrents based on rules defined in a YAML config file.

import win32serviceutil
import win32service
import win32event
import servicemanager
import time
import os
from cleaner import Cleaner

# -------------------------
# LOGGING SETUP
# -------------------------

# FIX: Use absolute path so Windows service doesn't write to System32
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "qb-cleaner.log")

def log(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"

    # Write to Windows Event Log
    servicemanager.LogInfoMsg(line)

    # Write to log file
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class QBCleanerService(win32serviceutil.ServiceFramework):
    _svc_name_ = "QBCleanerService"
    _svc_display_name_ = "qBittorrent Auto Cleaner"
    _svc_description_ = "Automatically cleans torrents based on rules.yaml"

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)

        # Pass logger into Cleaner
        self.cleaner = Cleaner(logger=log)

    def SvcStop(self):
        log("Service stop requested")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        log("QBCleanerService starting...")

        # REQUIRED: Tell Windows the service is running
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)

        log("QBCleanerService started")

        while True:
            rc = win32event.WaitForSingleObject(self.stop_event, 30000)
            if rc == win32event.WAIT_OBJECT_0:
                log("Stop event received, exiting service loop")
                break

            try:
                self.cleaner.run()
            except Exception as e:
                log(f"Error during cleaner run: {e}")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(QBCleanerService)
