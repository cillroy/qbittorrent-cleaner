# self_update.py - Download the latest GitHub release and apply it with install.ps1.

import argparse
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import zipfile

import yaml

from paths import BASE_DIR, UPDATE_LOG, UPDATE_LOG_DIR, ensure_runtime_dirs
from update_check import check_for_update, GITHUB_OWNER, GITHUB_REPO
from version import read_local_version

log = logging.getLogger("qb_cleaner.update")


def setup_update_log():
    ensure_runtime_dirs()
    os.makedirs(UPDATE_LOG_DIR, exist_ok=True)
    log.setLevel(logging.INFO)
    if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == os.path.abspath(UPDATE_LOG) for h in log.handlers):
        file_handler = logging.FileHandler(UPDATE_LOG, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(file_handler)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in log.handlers):
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(stream)
    log.propagate = False
    return UPDATE_LOG


def _download(url, dest, timeout=60):
    log.info("GET %s -> %s", url, dest)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json, application/zip, */*",
            "User-Agent": f"qBittorrent-Cleaner/{read_local_version()}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            log.info("HTTP %s %s", getattr(response, "status", "?"), response.geturl())
            with open(dest, "wb") as fh:
                shutil.copyfileobj(response, fh)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read()[:500]
            if isinstance(body, bytes):
                body = body.decode("utf-8", "replace")
        except Exception:
            pass
        log.error("Download failed HTTP %s: %s %s", exc.code, exc.reason, body)
        raise
    size = os.path.getsize(dest)
    log.info("Downloaded %s bytes", size)
    if size < 100:
        raise RuntimeError(f"Download too small ({size} bytes); not a release zip")


def _find_source_root(extracted):
    for root, _dirs, files in os.walk(extracted):
        if "install.ps1" in files and "service.py" in files:
            return root
    listing = []
    for root, dirs, files in os.walk(extracted):
        listing.append(f"{root}: {files[:20]}")
        if len(listing) >= 15:
            break
    log.error("Zip layout:\n%s", "\n".join(listing) or "(empty)")
    raise FileNotFoundError("Downloaded zip did not contain install.ps1 / service.py")


def download_latest(work_dir=None, force=False):
    log.info("Checking GitHub releases (force=%s, local=%s)", force, read_local_version())
    info = check_for_update(force=True)
    log.info(
        "Check result: latest=%s tag=%s available=%s error=%s message=%s zipball=%s",
        info.get("latest"),
        info.get("tag_name"),
        info.get("update_available"),
        info.get("error"),
        info.get("message"),
        info.get("zipball_url"),
    )
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
    if not tag.startswith("v"):
        tag = f"v{tag}"
    # Public archive zip, not api.github.com/zipball (that 415s on octet-stream).
    url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/archive/refs/tags/{tag}.zip"
    work_dir = work_dir or tempfile.mkdtemp(prefix="qb-cleaner-update-")
    zip_path = os.path.join(work_dir, "release.zip")
    extract_dir = os.path.join(work_dir, "extract")
    os.makedirs(extract_dir, exist_ok=True)
    log.info("Work dir %s", work_dir)
    _download(url, zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()[:30]
        log.info("Zip entries (%s): %s", len(zf.namelist()), names)
        zf.extractall(extract_dir)
    source = _find_source_root(extract_dir)
    log.info("Extracted %s to %s", tag, source)
    return {"skipped": False, "info": info, "source": source, "work_dir": work_dir}


def _web_port(dest):
    path = os.path.join(dest, "rules.yaml")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        return int((cfg.get("web") or {}).get("port", 8002))
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        log.warning("Could not read web port from %s: %s", path, exc)
        return 8002


def start_web_ui(dest, python):
    python = python or sys.executable
    pythonw = python
    if python.lower().endswith("python.exe"):
        candidate = python[:-10] + "pythonw.exe"
        if os.path.isfile(candidate):
            pythonw = candidate
    web_py = os.path.join(dest, "web.py")
    if not os.path.isfile(web_py):
        log.error("web.py not found at %s", web_py)
        return False
    flags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        flags |= subprocess.DETACHED_PROCESS
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags |= subprocess.CREATE_NO_WINDOW
    log.info("Starting web UI: %s %s (cwd=%s)", pythonw, web_py, dest)
    subprocess.Popen(
        [pythonw, web_py],
        cwd=dest,
        close_fds=True,
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    port = _web_port(dest)
    for _ in range(40):
        sock = socket.socket()
        sock.settimeout(0.4)
        try:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                url = f"http://127.0.0.1:{port}/"
                log.info("Web UI is listening at %s", url)
                print(f"Web UI started at {url}")
                try:
                    import webbrowser
                    webbrowser.open(url)
                except Exception as exc:
                    log.warning("Could not open browser: %s", exc)
                return True
        finally:
            sock.close()
        time.sleep(0.25)
    log.warning("Web UI did not open port %s in time", port)
    print(f"Web UI did not respond on port {port} yet; try opening it from the tray.")
    return False


def apply_update(dest, python=None, force=False, start_web=True):
    dest = os.path.abspath(dest.rstrip('\\/'))
    python = python or sys.executable
    log.info("Apply update dest=%s python=%s force=%s start_web=%s", dest, python, force, start_web)
    result = download_latest(force=force)
    if result.get("skipped"):
        log.info(result["message"])
        print(result["message"])
        if start_web:
            start_web_ui(dest, python)
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
        "-Python",
        python,
    ]
    log.info("Running: %s", " ".join(args))
    print("Running", " ".join(args))
    with open(UPDATE_LOG, "a", encoding="utf-8") as log_fh:
        log_fh.write("----- install.ps1 output -----\n")
        log_fh.flush()
        completed = subprocess.call(args, stdout=log_fh, stderr=subprocess.STDOUT)
        log_fh.write(f"----- install.ps1 exit {completed} -----\n")
    log.info("install.ps1 exit code %s", completed)
    if completed == 0 and start_web:
        # Zip's install.ps1 may be older and ignore -StartWeb; start web.py ourselves.
        start_web_ui(dest, python)
    return completed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download and install the latest GitHub release")
    parser.add_argument("--apply", action="store_true", help="Download and run install.ps1 update")
    parser.add_argument("--force", action="store_true", help="Reinstall even if VERSION matches")
    parser.add_argument("--dest", default=BASE_DIR, help="Install folder")
    parser.add_argument("--python", default="", help="python.exe for pip/service")
    parser.add_argument("--start-web", action="store_true", default=True)
    parser.add_argument("--no-start-web", action="store_false", dest="start_web")
    args = parser.parse_args(argv)
    log_path = setup_update_log()
    log.info("==== self_update start ====")
    log.info("python=%s argv=%s cwd=%s log=%s", sys.executable, argv or sys.argv, os.getcwd(), log_path)
    try:
        if args.apply:
            code = apply_update(
                args.dest,
                python=args.python or None,
                force=args.force,
                start_web=args.start_web,
            )
        else:
            result = download_latest(force=args.force)
            if result.get("skipped"):
                log.info(result["message"])
                print(result["message"])
                code = 0
            else:
                print(result["source"])
                code = 0
        log.info("==== self_update finished exit=%s ====", code)
        if code:
            print(f"Update failed. See {log_path}")
        return code
    except Exception:
        log.exception("self_update failed")
        print(f"Update failed. See {log_path}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
