# qBittorrent Auto Cleaner (Windows Service + Tray + Web)

A rule-driven cleanup system for qBittorrent on Windows. It includes:

- A **Windows Service** that runs cleanup rules on a configurable interval
- A **tray app** to watch status and start/stop the service and web UI
- A **web UI** for dashboard, rules, scheduler, logs, and settings
- **`rules.yaml`** for qBittorrent connection, schedule, web auth, and rules

Built for setups (Sonarr, Radarr, Lidarr, etc.) where torrents pile up and need predictable cleanup.

**Built by [cwhateverc](https://cwhateverc.com)** · [cwhateverc.com](https://cwhateverc.com) · [support@cwhateverc.com](mailto:support@cwhateverc.com)

Source: [github.com/cillroy/qbittorrent-cleaner](https://github.com/cillroy/qbittorrent-cleaner)

---

# Features

### Windows service
- True Windows Service (pywin32)
- Talks to qBittorrent’s Web API
- Reloads `rules.yaml` every cycle
- Interval comes from `schedule:` in `rules.yaml` (not hardcoded)
- Daily log rotation, configurable retention
- Toast notifications on deletions
- Windows Event Log gets **action** events only (not every schedule tick)

### Tray
- Color-coded icon (both Windows service **and** web UI):
  - Green — both running
  - Yellow — only one running, or status unknown
  - Red — both stopped
- Right-click menu: status rows, open web UI, run cleanup, Service / Web / Open submenus
- `start-tray.cmd` launches it elevated (needed to start/stop the service)
- Optional debug: `python tray.py debug` → `tray-debug.log`
- Auto-start via Scheduled Task (`QBCleanerTray.xml`)

### Web UI
- **Dashboard** — service, qBittorrent, next cleanup, deletion counts
- **Rules** — add / edit / delete
- **Scheduler** — next run countdown, last run, interval, pause, run now
- **Logs** — **Actions** vs **Schedule** tabs
- **Settings** — qBittorrent, web, logging
- **Help** — short in-app guide, support contacts, GitHub
- HTTP basic auth (optional)

### Logs
| File | Contents |
| --- | --- |
| `qb-cleaner.log` | Actions: deletions, errors, service start/stop |
| `qb-schedule.log` | Every pass (started / finished), including empty runs |
| `tray-debug.log` | Tray internals, only with `python tray.py debug` |

Rotated daily; keep `logging.max_days` days.

---

# Project layout

```
qBittorrent Cleaner/
├── install.ps1 / install.cmd / update.cmd   # install or update (elevated)
├── start-tray.cmd                           # start the tray icon
├── qb_api.py                                # qBittorrent Web API
├── cleaner.py                               # rule engine
├── schedule.py                              # interval + last/next run state
├── logutil.py                               # action vs schedule loggers
├── service.py                               # Windows service
├── tray.py                                  # tray app
├── web.py                                   # FastAPI web UI
├── templates/                               # HTML pages
├── rules.yaml                               # your config (never overwritten by update)
├── QBCleanerTray.xml                        # optional logon task for the tray
└── requirements.txt
```

Runtime files (created as needed, not overwritten by update): `rules.yaml`, `qb-cleaner.log*`, `qb-schedule.log*`, `schedule_state.json`.

---

# Requirements

- Windows 10 or 11
- Python 3.11+
- qBittorrent with Web UI enabled
- `pip install -r requirements.txt`

Packages: pywin32, requests, PyYAML, pystray, Pillow, plyer, FastAPI, uvicorn, Jinja2, python-multipart.

---

# Install / update

Prefer the scripts. They handle execution policy, pip, and the Windows service.

**First install** (elevated):

```bat
install.cmd
```

**Later updates** after you copy new code into the install folder (do **not** overwrite prod `rules.yaml`):

```bat
update.cmd
```

Or:

```bat
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 update
```

Useful flags:

```bat
install.cmd status
install.cmd update -DryRun
install.cmd update -Dest "C:\qBittorrent Cleaner"
install.cmd update -StartWeb
install.cmd install -RegisterTrayTask
```

`update.cmd` / `install.ps1 update` will:

1. Stop the service and `web.py`
2. Backup program files under `.backup\<timestamp>\`
3. Copy new code **unless** you already copied into the same folder (in-place)
4. Leave `rules.yaml`, logs, and `schedule_state.json` alone
5. Insert a `schedule:` block if `rules.yaml` does not have one
6. `pip install -r requirements.txt`
7. Start the Windows service
8. Start the web UI only if it was already running (`-StartWeb` to force it)

Restart the **tray** yourself (`start-tray.cmd` or Quit then start again). The updater does not restart it.

Default dest is `C:\qBittorrent Cleaner` if that already has `service.py`, otherwise the folder you run from.

### Manual service commands

Elevated:

```bat
python service.py install
python service.py start
python service.py stop
python service.py remove
```

---

# Tray

**Start it:** double-click `start-tray.cmd` (UAC so service control works).

Or:

```bat
pythonw tray.py
python tray.py debug
```

### Auto-start at logon

1. Import `QBCleanerTray.xml` in Task Scheduler, or `install.cmd install -RegisterTrayTask`
2. Point the action at `pythonw.exe`, `tray.py`, and the install folder
3. Run only when the user is logged on, **highest privileges**, your Windows user (not Administrator)

---

# Configuration (`rules.yaml`)

The service reloads this every cycle. Update never overwrites an existing file.

```yaml
qbittorrent:
  url: "http://127.0.0.1:8080"
  username: "admin"          # optional
  password: "adminadmin"     # optional

logging:
  max_days: 30
  enable_notifications: true

schedule:
  enabled: true
  interval_seconds: 30       # 15–60 minutes is plenty for a 40-day rule

web:
  port: 8002
  username: "admin"
  password: "webadmin"
  enable_auth: true

rules:
  - name: "Auto-clean inactive labeled torrents : >=40 days"
    match:
      category_in: ["radarr", "tv-sonarr"]
      last_activity_hours_gte: 960
    action:
      delete_torrent: true
      delete_files: true
```

Change the interval on the **Scheduler** page; the service picks it up on the next wake (about a second).

### Match operators the engine actually uses

| Operator | Meaning |
| --- | --- |
| `label` / `label_in` | Exact label, or any of a list |
| `category` / `category_in` | Exact category, or any of a list |
| `state` | qBittorrent state string |
| `ratio_gt` | Ratio greater than |
| `last_activity_hours_gt` / `_gte` | Hours since last activity |
| `added_on_hours_gt` / `_gte` | Hours since added |

The rules form also lists `ratio_lt`, `size_*`, `tracker_contains`, and `progress_eq`. Those are **not** applied by the engine yet.

---

# Web UI

```bat
python web.py
```

Or tray → **Web → Start**, then **Open web interface**.

URL is `http://localhost:<web.port>` from `rules.yaml` (default **8002**).

---

# Debugging

| Log | What |
| --- | --- |
| `qb-cleaner.log` | Deletions, errors, service lifecycle |
| `qb-schedule.log` | Every scheduled/manual pass |
| `tray-debug.log` | Tray internals (`python tray.py debug`) |

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| Tray icon yellow | Only one of service/web is up, or status unknown | Check the menu status rows |
| Tray icon red | Both service and web stopped | Start them from the tray (elevated) |
| `.\install.ps1` blocked | Execution policy | Use `update.cmd` / `install.cmd` |
| Service not starting | Bad Web UI URL/credentials | Fix `rules.yaml` |
| Cleanup not happening | Rule mismatch, or schedule paused | Scheduler page + action log |
| Notifications show old color | Stale tray | Quit tray, run `start-tray.cmd` |

---

# Uninstall

```bat
install.cmd uninstall
```

That stops/removes the Windows service (and the tray task if registered). Files stay unless you pass `-Purge`.

Or manually:

```bat
python service.py stop
python service.py remove
```

Stop `web.py` if it is running, delete the Scheduled Task, then remove the folder if you want it gone.
