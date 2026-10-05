# logutil.py - Action log (deletes/errors) vs schedule log (run ticks).

import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler

from paths import (
    ACTION_LOG,
    SCHEDULE_LOG,
    ensure_runtime_dirs,
    migrate_legacy_files,
)

ACTION_LOGGER_NAME = "qb_cleaner.action"
SCHEDULE_LOGGER_NAME = "qb_cleaner.schedule"

_FORMAT = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")


def _has_handler_for(logger, path):
    target = os.path.abspath(path)
    for handler in logger.handlers:
        if isinstance(handler, TimedRotatingFileHandler):
            if os.path.abspath(getattr(handler, "baseFilename", "")) == target:
                return True
    return False


class SharedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Daily log that keeps writing when midnight rotation cannot rename the file.

    The service, tray, and web UI log to the same files. TimedRotatingFileHandler
    holds the file open, so on Windows the midnight rename fails, the stream is
    left closed, and that process never writes another line.
    """

    def __init__(self, filename, backup_count):
        super().__init__(
            filename,
            when="midnight",
            interval=1,
            backupCount=backup_count,
            encoding="utf-8",
            delay=True,
        )

    def emit(self, record):
        try:
            if int(time.time()) >= self.rolloverAt:
                self._rollover()
            self._append(record)
        except Exception:
            self.handleError(record)

    def _append(self, record):
        if self.stream is None:
            self.stream = self._open()
        try:
            logging.FileHandler.emit(self, record)
            self.stream.flush()
        finally:
            self._close_stream()

    def _close_stream(self):
        stream = self.stream
        self.stream = None
        if stream is None:
            return
        try:
            stream.close()
        except Exception:
            pass

    def _archive_name(self, current_time):
        started = self.rolloverAt - self.interval
        if self.utc:
            time_tuple = time.gmtime(started)
        else:
            time_tuple = time.localtime(started)
            dst_now = time.localtime(current_time)[-1]
            dst_then = time_tuple[-1]
            if dst_now != dst_then:
                addend = 3600 if dst_now else -3600
                time_tuple = time.localtime(started + addend)
        return self.rotation_filename(
            self.baseFilename + "." + time.strftime(self.suffix, time_tuple)
        )

    def _rollover(self):
        # Drop our handle first. Another process can still block the rename;
        # in that case leave rolloverAt alone and retry on the next line.
        self._close_stream()
        current_time = int(time.time())
        archive = self._archive_name(current_time)
        try:
            if os.path.exists(self.baseFilename) and not os.path.exists(archive):
                os.rename(self.baseFilename, archive)
            if self.backupCount > 0:
                for old in self.getFilesToDelete():
                    try:
                        os.remove(old)
                    except OSError:
                        pass
        except OSError:
            return
        self.rolloverAt = self.computeRollover(current_time)
        while self.rolloverAt <= current_time:
            self.rolloverAt += self.interval


def _file_handler(path, max_days):
    handler = SharedTimedRotatingFileHandler(path, max_days)
    handler.setFormatter(_FORMAT)
    return handler


def setup_logging(max_days=30):
    """Attach rotating file handlers. Safe to call more than once per process."""
    migrate_legacy_files()
    ensure_runtime_dirs()
    action = logging.getLogger(ACTION_LOGGER_NAME)
    schedule = logging.getLogger(SCHEDULE_LOGGER_NAME)
    action.setLevel(logging.INFO)
    schedule.setLevel(logging.INFO)
    action.propagate = False
    schedule.propagate = False

    if not _has_handler_for(action, ACTION_LOG):
        action.addHandler(_file_handler(ACTION_LOG, max_days))
    if not _has_handler_for(schedule, SCHEDULE_LOG):
        schedule.addHandler(_file_handler(SCHEDULE_LOG, max_days))

    return action, schedule
