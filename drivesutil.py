# drivesutil.py - Local fixed-drive capacity helpers for the dashboard.
import ctypes
import string


def format_bytes(num_bytes):
    """Human-readable size with one decimal (KB/MB/GB/TB)."""
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return "0.0 B"
    if value < 0:
        value = 0.0
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = value
    unit = units[0]
    for candidate in units:
        unit = candidate
        if size < 1024.0 or candidate == units[-1]:
            break
        size /= 1024.0
    if unit == "B":
        return f"{int(size)} B"
    return f"{size:.1f} {unit}"


def get_local_drives():
    """Return fixed local drives with capacity and free space (Windows)."""
    DRIVE_FIXED = 3
    kernel32 = ctypes.windll.kernel32
    drives = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        try:
            if kernel32.GetDriveTypeW(root) != DRIVE_FIXED:
                continue
            free_avail = ctypes.c_ulonglong(0)
            total_bytes = ctypes.c_ulonglong(0)
            total_free = ctypes.c_ulonglong(0)
            ok = kernel32.GetDiskFreeSpaceExW(
                root,
                ctypes.byref(free_avail),
                ctypes.byref(total_bytes),
                ctypes.byref(total_free),
            )
            if not ok:
                continue
            label_buf = ctypes.create_unicode_buffer(261)
            kernel32.GetVolumeInformationW(
                root, label_buf, 261, None, None, None, None, 0
            )
            total = int(total_bytes.value)
            free = int(free_avail.value)
            if total < 0:
                total = 0
            if free < 0:
                free = 0
            if free > total:
                free = total
            used = total - free
            percent_used = round((used / total) * 100.0, 1) if total else 0.0
            drives.append(
                {
                    "letter": f"{letter}:",
                    "label": label_buf.value or "",
                    "total_bytes": total,
                    "free_bytes": free,
                    "used_bytes": used,
                    "percent_used": percent_used,
                    "total_human": format_bytes(total),
                    "free_human": format_bytes(free),
                    "used_human": format_bytes(used),
                }
            )
        except OSError:
            continue
    return drives
