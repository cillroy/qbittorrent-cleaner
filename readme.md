# qBittorrent Auto Cleaner (Windows Service + Tray Application)

A fully automated, rule‑driven cleanup system for qBittorrent on Windows.  
This project includes:

- A **Windows Service** that runs cleanup rules on a schedule  
- A **Tray Application** that lets you monitor and control the service  
- A **rules.yaml** file defining flexible cleanup logic  
- Full logging and optional debug mode  

Designed for automation‑heavy setups (Sonarr, Radarr, Lidarr, etc.) where torrents accumulate and need safe, predictable cleanup.

---

# ✨ Features

### Windows Service
- Runs as a **true Windows Service** (pywin32)
- Uses qBittorrent’s **Web API**
- Fully configurable via `rules.yaml`
- Supports **any torrent field** (ratio, state, size, labels, last activity, added time, etc.)
- Flexible operators:
  - `*_gt`, `*_lt`, `*_eq`
  - `label`, `label_in`
  - `state`, `category`
  - `ratio_gt`, `ratio_lt`
  - `size_gt`, `size_lt`
  - `last_activity_hours_gt`
  - `added_on_hours_gt`
  - `tracker_contains`
- Hot‑reloads configuration every cycle
- **Automatic log rotation** (daily, configurable retention)
- **Windows toast notifications** when torrents are deleted
- Logs actions to `qb-cleaner.log` (with rotation)

### Tray Application
- Shows **live service status** (Running / Stopped / Unknown / Not Elevated)
- Color‑coded tray icon:
  - 🟢 Running  
  - 🔴 Stopped  
  - 🟡 Unknown  
  - 🔵 Not Elevated  
- Right‑click menu:
  - **Service Control**: Start / Stop / Restart service
  - **Web Server Control**: Start / Stop web server, Open web interface
  - **Manual Operations**: Run cleanup immediately
  - **File Access**: Open log file, rules.yaml, installation folder
- Optional debug logging (`python tray.py debug`)
- Auto‑starts via Scheduled Task (with elevation)

---

# 📁 Project Structure

```
qBittorrent Cleaner/
│
├── qb_api.py            # qBittorrent Web API wrapper
├── cleaner.py           # Rule engine + cleanup logic
├── service.py           # Windows service wrapper
├── tray.py              # Tray application
├── rules.yaml           # User-defined cleanup rules
├── qb-cleaner.log       # Runtime log (created automatically)
└── tray-debug.log       # Optional debug log (only when enabled)
```

---

# ⚙️ Requirements

- Windows 10 or 11  
- Python 3.11+  
- qBittorrent with Web UI enabled  
- Python packages:
`pip install pywin32 requests pyyaml pystray pillow plyer`
---

# 🚀 Installation

## 1. Clone or extract the project
Place it somewhere stable, e.g.: 
`C:\qBittorrent Cleaner`


## 2. Install Python dependencies
`pip install -r requirements.txt`

(or install manually as listed above)

## 3. Configure qBittorrent Web UI
Enable Web UI:

- Tools → Options → Web UI  
- Set username/password  
- Ensure the port matches your `rules.yaml`

---

# 🧩 Configuration (rules.yaml)

All behavior is controlled through `rules.yaml`.  
The service reloads this file every cycle.

Optional (but suggested):
- `username`
- `password`

### Example default rule (40 days inactivity, Sonarr/Radarr labels)

```yaml
qbittorrent:
  url: "http://127.0.0.1:8080"
  username: "admin"
  password: "adminadmin"

logging:
  max_days: 30          # Keep 30 days of logs
  enable_notifications: true  # Show Windows notifications

rules:
  - name: "Delete inactive Sonarr/Radarr torrents"
    match:
      label_in: ["sonarr", "radarr"]
      last_activity_hours_gt: 960   # 40 days
    action:
      delete_torrent: true
      delete_files: true
```

## Supported Match Operators
| Operator | Description |
| --- | --- |
| label | Exact label match |
| label_in | Match any label in a list |
| state | qBittorrent state string |
| ratio_gt / ratio_lt | Ratio comparisons |
| size_gt / size_lt | Size in bytes |
| last_activity_hours_gt | Inactivity threshold |
| added_on_hours_gt | Age threshold |
| tracker_contains | Match tracker substring |
| progress_eq | Match progress (0.0–1.0) |

# 🛠 Installing the Windows Service
Run from an elevated terminal:
```python
python service.py install
python service.py start
```

To stop:
```
python service.py stop
```

To remove:
```
python service.py remove
```

Logs are written to:
`qb-cleaner.log`

# 🖥️ Tray Application Setup
The tray app provides:
- Live service status
- Color‑coded icon
- Start/Stop/Restart controls
- Cleanup‑now button
- Log + rules quick access

## Run manually (for testing)
`python tray.py`

Enable debug logging
`python tray.py debug`

Debug logs go to:
`tray-debug.log`

# 🔁 Auto‑Start the Tray App (Recommended)

The tray app must run as your user, with elevation, and only when logged in.

## 1. Save the provided Scheduled Task XML
Example: QBCleanerTray.xml

## 2. Import it
Task Scheduler → Import Task

## 3. Update paths
    - pythonw.exe
    - tray.py
    - Working directory
## 4. Ensure these settings:
    - Run only when user is logged on
    - Run with highest privileges
    - User account = your actual Windows user (not Administrator)

This ensures:
- No UAC prompt
- Tray icon loads correctly
- Service control works
- Status updates work

# 🧪 Debugging
## Enable debug mode:
```
python tray.py debug
```

## Check logs:
qb-cleaner.log → service activity

tray-debug.log → tray status, icon updates, service queries

## Common issues:
| Symptom | Cause | Fix |
| --- | --- | --- |
| Tray icon stays yellow | Explorer not repainting | Fixed in latest tray.py (icon handle refresh) |
| Tray shows blue icon | Not elevated | Fix Scheduled Task settings |
| Service not starting | Wrong Web UI credentials | Update rules.yaml |
| Cleanup not happening | Rule mismatch | Check debug logs |

# 🌐 Web Interface

The web interface provides remote access to monitor and control the qBittorrent Cleaner from any browser.

## Features

- **Dashboard**: View service status, qBittorrent connection, recent torrents, and activity logs
- **Rules Management**: Add, edit, and delete cleanup rules through a web form
- **Logs**: View complete application logs from all archived files with chronological ordering
- **Settings**: Configure qBittorrent connection, web server settings, and logging preferences
- **Manual Cleanup**: Trigger cleanup runs on demand

## Starting the Web Server

Run the web server (can be done independently of the Windows service):
```bash
python web.py
```

The web interface will be available at: `http://localhost:8082` (configurable in `rules.yaml`)

## Configuration

Web settings are configured in `rules.yaml`:

```yaml
web:
  port: 8082                    # Web server port
  username: "admin"             # Web interface username
  password: "webadmin"          # Web interface password
  enable_auth: true             # Enable/disable authentication
```

## Security

- HTTP Basic Authentication (username/password)
- Configurable credentials
- Can be disabled for local networks

## Running as a Service

To run the web server automatically, you can:

1. Create a Windows Scheduled Task to run `python web.py` at startup
2. Use a process manager like NSSM to create a Windows service for the web server
3. Run it manually when needed

The web server is completely independent and can run even when the cleanup service is stopped.

# 🧹 Uninstall
Stop and remove the service:
```
python service.py stop
python service.py remove
```

Stop the web server (if running):
```
# Find the python process running web.py and terminate it
```

Delete the Scheduled Task:

Task Scheduler → Delete task

Remove the folder:
```
C:\qBittorrent Cleaner
```
