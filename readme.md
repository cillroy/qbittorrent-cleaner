# qBittorrent Auto Cleaner (Windows Service)

A flexible, rule‑driven Windows service that automatically removes qBittorrent torrents based on inactivity, labels, ratio, size, state, or any other field exposed by the qBittorrent Web API.

This service is designed for automation-heavy setups (Sonarr, Radarr, Lidarr, etc.) where torrents accumulate over time and need to be cleaned up safely and predictably.

---

## ✨ Features

- Runs as a **true Windows Service** (pywin32)
- Uses qBittorrent’s **Web API**
- Fully configurable via **rules.yaml**
- Supports **any torrent field** (ratio, state, size, labels, last activity, added time, etc.)
- Supports flexible operators:
  - `*_gt`, `*_lt`, `*_eq`
  - `last_activity_hours_gt`
  - `added_on_hours_gt`
  - `ratio_gt`, `ratio_lt`
  - `label`, `state`, `category`
  - `tracker_contains`
- Hot‑reloads configuration every cycle
- Logs actions to `qb-cleaner.log`

---

## 📁 Project Structure

```
qb-cleaner/
│
├── qb_api.py        # qBittorrent API wrapper
├── cleaner.py       # Rule engine + core logic
├── service.py       # Windows service wrapper
└── rules.yaml       # User-defined rules
```

---

## ⚙️ Requirements

- Windows 11
- Python 3.11+
- qBittorrent with Web UI enabled
- Python packages:


---

## 🔧 Configuration (rules.yaml)

All behavior is controlled through `rules.yaml`.  
The service reloads this file every cycle, so you can update rules without restarting.

### Initial Default Rule (40 days inactivity, Sonarr/Radarr labels)

```yaml
qbittorrent:
url: "http://127.0.0.1:8080"
username: "admin"
password: "adminadmin"

service:
interval_seconds: 1800   # run every 30 minutes

rules:
- name: "Delete inactive Sonarr/Radarr torrents"
  match:
    label_in: ["sonarr", "radarr"]
    last_activity_hours_gt: 960   # 40 days
  action:
    delete_torrent: true
    delete_files: true
```

### Supported Match Operators

| Operator	       | Description |
| ---------------- | ----------- |
|label | Exact label match |
|label_in	| Match any label in a list |
|state | qBittorrent state string |
|ratio_gt, ratio_lt |	Ratio comparisons |
|size_gt, size_lt	| Size in bytes |
|last_activity_hours_gt	| Inactivity threshold |
|added_on_hours_gt | Age threshold |
|tracker_contains	| Match tracker substring |
|progress_eq | Match progress (0.0–1.0) |