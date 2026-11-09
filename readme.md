# qBittorrent Auto Cleaner (Windows Service + Tray + Web)

A rule-driven cleanup system for qBittorrent on Windows. It includes:

- A **Windows Service** that runs cleanup rules on a configurable interval
- A **tray app** to watch status and start/stop the service and web UI
- A **web UI** for dashboard, rules, scheduler, logs, and settings
- **`rules.yaml`** for qBittorrent connection, schedule, web auth, and rules

Built for setups (Sonarr, Radarr, Lidarr, etc.) where torrents pile up and need predictable cleanup.

**Built by [cwhateverc](https://cwhateverc.com)** · [cwhateverc.com](https://cwhateverc.com) · [support@cwhateverc.com](mailto:support@cwhateverc.com)

Source: [github.com/cillroy/qbittorrent-cleaner](https://github.com/cillroy/qbittorrent-cleaner) · current version is in `VERSION`

---

# Features

### Windows service
- True Windows Service (pywin32)
- Talks to qBittorrent’s Web API
- Reloads `rules.yaml` every cycle
- Interval comes from `schedule:` in `rules.yaml` (not hardcoded)
- Daily log rotation, configurable retention
- Toast notifications on deletions
- Optional **email alerts** when cleanup keeps failing (SMTP, standard library only)
- Windows Event Log gets **action** events only (not every schedule tick)

### Tray
- Color-coded icon (both Windows service **and** web UI):
  - Green — both running
  - Yellow — only one running, or status unknown
  - Red — both stopped
- Right-click menu: status rows, open web UI, run cleanup, check for updates, Service / Web (including Restart) / Open submenus
- `start-tray.cmd` self-elevates (UAC), then starts the tray — needed to start/stop the Windows service
- Optional debug: `python tray.py debug` → `logs/tray/tray-debug.log`
- If the icon appears then vanishes: `logs/tray/tray-crash.log`
- Auto-start via Scheduled Task (`QBCleanerTray.xml`)

### Web UI
- **Dashboard** — service, qBittorrent, next cleanup, deletion counts
- **Rules** — add / edit / delete
- **Scheduler** — next run countdown, last run, interval, pause, run now
- **Logs** — **Actions** vs **Schedule** tabs
- **Settings** — qBittorrent, web, logging, email alerts (with **Send test email**)
- **Help** — short in-app guide, support contacts, GitHub
- HTTP basic auth (optional)

### Logs
| File | Contents |
| --- | --- |
| `logs/actions/qb-cleaner.log` | Actions: deletions, errors, service start/stop |
| `logs/schedule/qb-schedule.log` | Every pass (started / finished), including empty runs |
| `logs/tray/tray-debug.log` | Tray internals, only with `python tray.py debug` |

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
├── notify_email.py                          # optional SMTP failure alerts
├── service.py                               # Windows service
├── tray.py                                  # tray app
├── web.py                                   # FastAPI web UI
├── templates/                               # HTML pages
├── rules.yaml                               # your config (never overwritten by update)
├── QBCleanerTray.xml                        # optional logon task for the tray
├── VERSION                                  # shipped version
├── version.py / update_check.py             # local version + GitHub latest check
└── requirements.txt
```

Runtime files (created as needed, not overwritten by update): `rules.yaml`, `logs/`, `data/`.

---

# Requirements

- Windows 10 or 11
- Python 3.11+
- qBittorrent with Web UI enabled
- `pip install -r requirements.txt`

Packages: pywin32, requests, PyYAML, pystray, Pillow, plyer, FastAPI, uvicorn, Jinja2, python-multipart.

---

# Install / update

Prefer the `.cmd` scripts. Double-click them; they self-elevate (UAC) so paths with spaces like `C:\qBittorrent Cleaner` work. The elevated window stays open so you can read errors.

**First install:**

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
cleanup.cmd          # organize leftover root logs (needs paths.py)
```

`update.cmd` / `install.ps1 update` will:

1. Stop the service and `web.py`
2. Backup program files under `.backup\<timestamp>\`
3. Copy new code **unless** you already copied into the same folder (in-place)
4. Leave `rules.yaml`, logs, and `schedule_state.json` alone
5. Insert a `schedule:` block if `rules.yaml` does not have one, and a disabled `notifications:` block if it has none
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

**Start it:** double-click `start-tray.cmd` (accept UAC). The elevated cmd window closes after launch; the icon should stay in the notification area.

Or:

```bat
pythonw tray.py
python tray.py debug
```

Tray → **Web → Restart** bounces `web.py`. **Check for updates** compares `VERSION` to GitHub releases (does not apply the update).

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
  password: "change-me"
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

### Email alerts (`notifications.email`)

Optional. When enabled, the cleaner emails you if cleanup **fails several runs in a row** — for example qBittorrent is stopped, unreachable, or rejects the login (`403 Forbidden`). It is off by default.

```yaml
notifications:
  email:
    enabled: false
    smtp_host: "smtp.example.com"
    smtp_port: 587
    starttls: true             # STARTTLS on port 587
    use_ssl: false             # true for implicit TLS (usually port 465)
    username: "user@example.com"
    password: ""               # blank = read env var named in password_env
    password_env: "QB_CLEANER_SMTP_PASSWORD"
    from_address: "user@example.com"
    to: ["user@example.com"]
    failure_threshold: 10      # consecutive failed runs before emailing
    cooldown_hours: 6          # at most one failure email per this many hours
    send_recovery: true        # one email when cleanup works again
```

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Turn email alerts on |
| `smtp_host` / `smtp_port` | `smtp.example.com` / `587` | Your mail server |
| `starttls` | `true` | Upgrade the connection with STARTTLS (port 587) |
| `use_ssl` | `false` | Implicit TLS instead (port 465); overrides `starttls` |
| `username` / `password` | blank | SMTP login. Leave `username` blank for servers without auth |
| `password_env` | `QB_CLEANER_SMTP_PASSWORD` | If `password` is blank, read it from this environment variable (set it machine-wide so the service sees it) |
| `from_address` | `username` | Sender address |
| `to` | `[]` | One or more recipients (list, or comma-separated in the web UI) |
| `failure_threshold` | `10` | Consecutive failed runs before the first email |
| `cooldown_hours` | `6` | Never send failure emails closer together than this |
| `send_recovery` | `true` | Send one "recovered" email after an alerted outage ends |

**How it decides to email**

- Every cleanup run (service, web **Run now**, tray) counts as a success or a failure. Failure streaks are kept in `data/email_alert_state.json`.
- With the default `interval_seconds: 30` and `failure_threshold: 10`, the first email goes out after about **5 minutes** of continuous failures. A short blip (a qBittorrent restart, a VPN reconnect) never emails.
- **One email per outage.** After the alert, nothing more is sent until a run succeeds. If `send_recovery` is on you then get one "recovered" email.
- `cooldown_hours` stops a flapping qBittorrent from sending an email every few minutes: a new outage within the cooldown is logged but not emailed until the cooldown has passed.
- If the email itself cannot be sent, the error goes to `logs/actions/qb-cleaner.log` and the cleaner keeps running; it retries at most every 10 minutes while the outage lasts.

**Gmail example** (use an [app password](https://myaccount.google.com/apppasswords), not your normal password; it needs 2-Step Verification):

```yaml
notifications:
  email:
    enabled: true
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    starttls: true
    use_ssl: false
    username: "your.name@gmail.com"
    password: "abcd efgh ijkl mnop"   # 16-character app password
    from_address: "your.name@gmail.com"
    to: ["you@example.com"]
```

To keep the password out of `rules.yaml`, leave `password: ""` and set a machine environment variable (elevated), then restart the service:

```bat
setx /M QB_CLEANER_SMTP_PASSWORD "abcd efgh ijkl mnop"
```

**Web UI:** **Settings → Email Alerts** edits the same keys. The password box never shows the saved password; leave it blank to keep it, or tick **Clear saved password**. **Send test email** sends one message with the values currently on the page (saved or not), so you can check them before saving.

`rules.yaml` holds credentials. Keep your real one out of source control; updates never overwrite it.

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
| `logs/actions/qb-cleaner.log` | Deletions, errors, service lifecycle |
| `logs/schedule/qb-schedule.log` | Every scheduled/manual pass |
| `logs/tray/tray-debug.log` | Tray internals (`python tray.py debug`) |
| `logs/tray/tray-crash.log` | Tray started then died (imports, icon loop) |
| `logs/update/self-update.log` | GitHub download/install (`update-from-github.cmd`) |
| `data/schedule_state.json` | Last/next run timestamps |
| `data/update_check_cache.json` | Cached GitHub latest-release check |
| `data/email_alert_state.json` | Failure streak and last email alert time |

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| Tray icon yellow | Only one of service/web is up, or status unknown | Check the menu status rows |
| Tray icon red | Both service and web stopped | Start them from the tray (elevated) |
| Tray flashes then vanishes | Crash after the icon is shown | Open `logs/tray/tray-crash.log` |
| `install.cmd` / `update.cmd` / `start-tray.cmd` close after UAC | Old launchers (path with spaces) | Copy the current `.cmd` files and run again; leave the elevated window open |
| `.\install.ps1` blocked | Execution policy | Use `update.cmd` / `install.cmd` |
| Service not starting | Bad Web UI URL/credentials | Fix `rules.yaml` |
| Cleanup not happening | Rule mismatch, or schedule paused | Scheduler page + action log |
| Notifications show old color | Stale tray | Quit tray, run `start-tray.cmd` |
| No alert email | Alerts disabled, threshold not reached, or SMTP error | **Settings → Send test email**; look for `Email alert:` lines in the action log |
| Gmail `535` / `Username and Password not accepted` | Normal password used, or app password revoked | Create a new Gmail app password |

---

# Releases (Azure DevOps → GitHub)

Azure DevOps is the source of truth. The pipeline mirrors `master` to GitHub `main` on every push. If `VERSION` is new (for example `1.0.0`), it also creates GitHub release `v1.0.0`. Later pushes with the same `VERSION` skip creating another release.

1. Set `VERSION` and commit on `master`.
2. `git push origin master`
3. The pipeline validates, pushes to GitHub, then creates [github.com/cillroy/qbittorrent-cleaner/releases](https://github.com/cillroy/qbittorrent-cleaner/releases) when that version does not exist yet.

The web UI and tray compare local `VERSION` to GitHub `releases/latest`. To apply:

```bat
update-from-github.cmd
```

That downloads the release zip, runs `install.ps1 update` from it, and leaves `rules.yaml`, `logs\`, and `data\` alone. Tray **Install GitHub update** and Dashboard **Install now** start the same script (UAC). Restart the tray afterward.

Do not tag every commit — only builds you want people to install.

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
