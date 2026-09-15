# update_check.py - Compare local VERSION to the latest GitHub release.

import json
import os
import time
import urllib.error
import urllib.request

from version import read_local_version, version_tuple, normalize_version

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "update_check_cache.json")
GITHUB_OWNER = "cillroy"
GITHUB_REPO = "qbittorrent-cleaner"
LATEST_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
CACHE_SECONDS = 6 * 3600


def _empty_result(local, **extra):
    result = {
        "local": local,
        "latest": None,
        "update_available": False,
        "release_url": RELEASES_PAGE,
        "name": None,
        "notes": "",
        "checked_at": time.time(),
        "error": False,
        "message": "",
    }
    result.update(extra)
    return result


def _load_cache():
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _save_cache(result):
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
            f.write("\n")
    except OSError:
        pass


def check_for_update(force=False, timeout=8):
    """Return a dict describing local vs latest GitHub release.

    Never raises. On 404 (no releases yet) or network errors, update_available
    is False and message explains why.
    """
    local = read_local_version()
    if not force:
        cached = _load_cache()
        if cached and (time.time() - float(cached.get("checked_at") or 0)) < CACHE_SECONDS:
            cached["local"] = local
            latest = cached.get("latest")
            if latest:
                cached["update_available"] = version_tuple(latest) > version_tuple(local)
            return cached

    request = urllib.request.Request(
        LATEST_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"qBittorrent-Cleaner/{local}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            result = _empty_result(
                local,
                message="No GitHub releases yet. Tag vX.Y.Z in Azure DevOps to publish one.",
            )
            _save_cache(result)
            return result
        result = _empty_result(
            local,
            error=True,
            message=f"GitHub returned HTTP {exc.code} while checking for updates.",
        )
        return result
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return _empty_result(
            local,
            error=True,
            message=f"Could not reach GitHub: {exc}",
        )

    latest = normalize_version(payload.get("tag_name") or "")
    result = _empty_result(
        local,
        latest=latest or None,
        update_available=bool(latest) and version_tuple(latest) > version_tuple(local),
        release_url=payload.get("html_url") or RELEASES_PAGE,
        name=payload.get("name") or payload.get("tag_name"),
        notes=payload.get("body") or "",
        message="",
    )
    _save_cache(result)
    return result
