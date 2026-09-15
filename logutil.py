# logutil.py - Action log (deletes/errors) vs schedule log (run ticks).

import logging
import os
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


def _file_handler(path, max_days):
    handler = TimedRotatingFileHandler(
        path,
        when="midnight",
        interval=1,
        backupCount=max_days,
        encoding="utf-8",
    )
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
