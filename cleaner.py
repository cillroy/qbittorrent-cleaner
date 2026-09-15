# cleaner.py - A script to clean up qBittorrent torrents based on rules defined in a YAML config file.

import yaml
import time
import os
from datetime import datetime
from qb_api import QBClient

class Cleaner:
    def __init__(self, config_path="rules.yaml", logger=print, notifier=None):
        self.logger = logger
        self.notifier = notifier

        # Resolve rules.yaml relative to this file (fixes Windows service crash)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(base_dir, config_path)
        self.config = None
        self.client = None
        self.reload_config()

    def reload_config(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}

        qb = self.config["qbittorrent"]
        self.client = QBClient(
            qb["url"],
            username=qb.get("username"),
            password=qb.get("password"),
        )

    def hours_since(self, unix_timestamp):
        dt = datetime.fromtimestamp(unix_timestamp)
        delta = datetime.now() - dt
        return delta.total_seconds() / 3600.0

    def match_rule(self, torrent, rule):
        m = rule.get("match", {})

        for key, value in m.items():

            # -------------------------
            # LABEL MATCHING
            # -------------------------
            if key == "label" and torrent.get("label") != value:
                return False

            if key == "label_in":
                if torrent.get("label") not in value:
                    return False

            # -------------------------
            # CATEGORY MATCHING
            # -------------------------
            if key == "category" and torrent.get("category") != value:
                return False

            if key == "category_in":
                if torrent.get("category") not in value:
                    return False

            # -------------------------
            # STATE MATCHING
            # -------------------------
            if key == "state" and torrent.get("state") != value:
                return False

            # -------------------------
            # GREATER THAN (existing)
            # -------------------------
            if key.endswith("_gt"):
                field = key.replace("_gt", "")

                if field == "ratio":
                    if float(torrent.get("ratio", 0)) <= float(value):
                        return False

                if field == "last_activity_hours":
                    if self.hours_since(torrent.get("last_activity", 0)) <= float(value):
                        return False

                if field == "added_on_hours":
                    if self.hours_since(torrent.get("added_on", 0)) <= float(value):
                        return False

            # -------------------------
            # GREATER OR EQUAL (new)
            # -------------------------
            if key.endswith("_gte"):
                field = key.replace("_gte", "")

                if field == "last_activity_hours":
                    if self.hours_since(torrent.get("last_activity", 0)) < float(value):
                        return False

                if field == "added_on_hours":
                    if self.hours_since(torrent.get("added_on", 0)) < float(value):
                        return False

        return True

    def run(self, source="service"):
        from schedule import load_schedule_config, record_run

        self.reload_config()
        deleted = 0
        error = None
        self.logger("Cleanup run started")
        try:
            torrents = self.client.get_torrents()
            rules = self.config.get("rules") or []

            for t in torrents:
                for rule in rules:
                    if self.match_rule(t, rule):
                        action = rule.get("action") or {}
                        if action.get("delete_torrent"):
                            self.client.delete(
                                t["hash"],
                                action.get("delete_files", False)
                            )
                            deleted += 1
                            msg = f"Deleted: {t['name']} via rule {rule['name']}"
                            self.logger(msg)
                            if self.notifier:
                                self.notifier(msg)

            self.logger(f"Cleanup run finished: {deleted} torrent(s) deleted")
        except Exception as e:
            error = str(e)
            self.logger(f"Cleanup run failed: {e}")
            raise
        finally:
            try:
                interval = load_schedule_config(self.config)["interval_seconds"]
                record_run(
                    source=source,
                    deleted=deleted,
                    error=error,
                    scheduled=(source == "service"),
                    interval_seconds=interval,
                )
            except Exception as e:
                self.logger(f"Failed to update schedule state: {e}")

    def run_once(self, source="manual"):
        self.run(source=source)
