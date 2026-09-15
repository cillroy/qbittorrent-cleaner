# self_update.py - Download the latest GitHub release and apply it with install.ps1.

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from paths import BASE_DIR
from update_check import check_for_update, GITHUB_OWNER, GITHUB_REPO
from version import read_local_version


def _download(url, dest, timeout=60):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": f"qBittorrent-Cleaner/{read_local_version()}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with open(dest, "wb") as fh:
            shutil.copyfileobj(response, fh)


def _find_source_root(extracted):
    for root, _dirs, files in os.walk(extracted):
        if "install.ps1" in files and "service.py" in files:
            return root
    raise FileNotFoundError("Downloaded zip did not contain install.ps1 / service.py")


def download_latest(work_dir=None, force=False):
    info = check_for_update(force=True)
    if info.get("error"):
        raise RuntimeError(info.get("message") or "GitHub update check failed")
    if not info.get("latest"):
        raise RuntimeError(info.get("message") or "No GitHub releases yet")
    if not info.get("update_available") and not force:
        return {
            "skipped": True,
            "message": f"Already up to date ({info['local']})",
            "info": info,
            "source": None,
        }

    tag = info.get("tag_name") or f"v{info['latest']}"
    url = info.get("zipball_url") or (
        f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/archive/refs/tags/{tag}.zip"
    )
    work_dir = work_dir or tempfile.mkdtemp(prefix="qb-cleaner-update-")
    zip_path = os.path.join(work_dir, f"{tag}.zip")
    extract_dir = os.path.join(work_dir, "extract")
    os.makedirs(extract_dir, exist_ok=True)
    print(f"Downloading {url}")
    _download(url, zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)
    source = _find_source_root(extract_dir)
    print(f"Extracted {tag} to {source}")
    return {"skipped": False, "info": info, "source": source, "work_dir": work_dir}


def apply_update(dest, python=None, force=False, start_web=False):
    dest = os.path.abspath(dest)
    result = download_latest(force=force)
    if result.get("skipped"):
        print(result["message"])
        return 0
    installer = os.path.join(result["source"], "install.ps1")
    args = [
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        installer,
        "update",
        "-Source",
        result["source"],
        "-Dest",
        dest,
    ]
    if python:
        args.extend(["-Python", python])
    if start_web:
        args.append("-StartWeb")
    print("Running", " ".join(args))
    completed = subprocess.call(args)
    return completed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download and install the latest GitHub release")
    parser.add_argument("--apply", action="store_true", help="Download and run install.ps1 update")
    parser.add_argument("--force", action="store_true", help="Reinstall even if VERSION matches")
    parser.add_argument("--dest", default=BASE_DIR, help="Install folder")
    parser.add_argument("--python", default="", help="python.exe for pip/service")
    parser.add_argument("--start-web", action="store_true")
    args = parser.parse_args(argv)

    if args.apply:
        return apply_update(
            args.dest,
            python=args.python or None,
            force=args.force,
            start_web=args.start_web,
        )

    result = download_latest(force=args.force)
    if result.get("skipped"):
        print(result["message"])
        return 0
    print(result["source"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
