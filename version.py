# version.py - Local app version from the VERSION file.

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_PATH = os.path.join(BASE_DIR, "VERSION")
DEFAULT_VERSION = "0.0.0"


def normalize_version(value):
    text = (value or "").strip()
    if text.lower().startswith("v") and len(text) > 1 and text[1].isdigit():
        text = text[1:]
    return text or DEFAULT_VERSION


def version_tuple(value):
    parts = []
    for piece in normalize_version(value).split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits or 0))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def read_local_version():
    try:
        with open(VERSION_PATH, "r", encoding="utf-8") as f:
            return normalize_version(f.read())
    except OSError:
        return DEFAULT_VERSION
