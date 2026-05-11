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
        config_path = os.path.join(base_dir, config_path)

        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        qb = self.config["qbittorrent"]

        username = qb.get("username")
        password = qb.get("password")

        self.client = QBClient(
            qb["url"],
            username=username,
            password=password
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

    def run(self):
        torrents = self.client.get_torrents()

        for t in torrents:
            for rule in self.config["rules"]:
                if self.match_rule(t, rule):
                    action = rule["action"]
                    if action.get("delete_torrent"):
                        self.client.delete(
                            t["hash"],
                            action.get("delete_files", False)
                        )
                        msg = f"Deleted: {t['name']} via rule {rule['name']}"
                        self.logger(msg)
                        if self.notifier:
                            self.notifier(msg)

    # Wrapper for manual testing
    def run_once(self):
        self.run()
