# paths.py - Runtime folders so logs and state stay out of the install root.

import glob
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOGS_DIR = os.path.join(BASE_DIR, "logs")
ACTIONS_LOG_DIR = os.path.join(LOGS_DIR, "actions")
SCHEDULE_LOG_DIR = os.path.join(LOGS_DIR, "schedule")
TRAY_LOG_DIR = os.path.join(LOGS_DIR, "tray")
UPDATE_LOG_DIR = os.path.join(LOGS_DIR, "update")
DATA_DIR = os.path.join(BASE_DIR, "data")

ACTION_LOG = os.path.join(ACTIONS_LOG_DIR, "qb-cleaner.log")
SCHEDULE_LOG = os.path.join(SCHEDULE_LOG_DIR, "qb-schedule.log")
TRAY_DEBUG_LOG = os.path.join(TRAY_LOG_DIR, "tray-debug.log")
TRAY_CRASH_LOG = os.path.join(TRAY_LOG_DIR, "tray-crash.log")
UPDATE_LOG = os.path.join(UPDATE_LOG_DIR, "self-update.log")
SCHEDULE_STATE_PATH = os.path.join(DATA_DIR, "schedule_state.json")
UPDATE_CACHE_PATH = os.path.join(DATA_DIR, "update_check_cache.json")


def ensure_runtime_dirs():
    for folder in (ACTIONS_LOG_DIR, SCHEDULE_LOG_DIR, TRAY_LOG_DIR, UPDATE_LOG_DIR, DATA_DIR):
        os.makedirs(folder, exist_ok=True)


def _move_file(src, dest_dir):
    """Move src into dest_dir. Locked files are skipped, never raised."""
    if not src or not os.path.isfile(src):
        return None
    ensure_runtime_dirs()
    dest = os.path.join(dest_dir, os.path.basename(src))
    if os.path.abspath(src) == os.path.abspath(dest):
        return None
    try:
        if os.path.exists(dest):
            os.remove(src)
            return ("removed-duplicate", src, dest)
        os.replace(src, dest)
        return ("moved", src, dest)
    except OSError:
        return ("locked", src, dest)


def _iter_legacy_pairs():
    for src in glob.glob(os.path.join(BASE_DIR, "qb-cleaner.log*")):
        yield src, ACTIONS_LOG_DIR
    for src in glob.glob(os.path.join(BASE_DIR, "qb-schedule.log*")):
        yield src, SCHEDULE_LOG_DIR
    yield os.path.join(BASE_DIR, "tray-debug.log"), TRAY_LOG_DIR
    yield os.path.join(BASE_DIR, "tray-crash.log"), TRAY_LOG_DIR
    yield os.path.join(BASE_DIR, "schedule_state.json"), DATA_DIR
    yield os.path.join(BASE_DIR, "schedule_state.json.tmp"), DATA_DIR
    yield os.path.join(BASE_DIR, "update_check_cache.json"), DATA_DIR


_migrated = False


def migrate_legacy_files(force=False):
    """Move root-level log/state files from older installs into logs/ and data/.

    Safe to call often: locked files are skipped, and after the first attempt
    this process does not keep retrying (use force=True from cleanup.cmd).
    """
    global _migrated
    if _migrated and not force:
        return []
    ensure_runtime_dirs()
    results = []
    for src, dest_dir in _iter_legacy_pairs():
        outcome = _move_file(src, dest_dir)
        if outcome:
            results.append(outcome)
    _migrated = True
    return results


def cleanup_root(remove_pycache=True):
    """Organize leftover root files and optional __pycache__ folders."""
    results = list(migrate_legacy_files(force=True))
    if remove_pycache:
        for cache in glob.glob(os.path.join(BASE_DIR, "**", "__pycache__"), recursive=True):
            if os.path.isdir(cache) and ".venv" not in cache.replace("\\", "/"):
                try:
                    import shutil
                    shutil.rmtree(cache)
                    results.append(("removed", cache, None))
                except OSError:
                    results.append(("locked", cache, None))
    return results


if __name__ == "__main__":
    print(f"Cleaning {BASE_DIR}")
    locked = False
    for action, src, dest in cleanup_root():
        if dest:
            print(f"  {action}: {os.path.basename(src)} -> {dest}")
        else:
            print(f"  {action}: {src}")
        if action == "locked":
            locked = True
    if locked:
        print("Some files were in use. Stop the tray and web UI, then run cleanup.cmd again.")
    print("Done. Logs are under logs\\, state under data\\.")
