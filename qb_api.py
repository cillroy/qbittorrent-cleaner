# qb_api.py - A simple client for interacting with the qBittorrent Web API.

import requests

class QBClient:
    def __init__(self, url, username=None, password=None):
        self.url = url.rstrip("/")
        self.session = requests.Session()
        self.login(username, password)

    def login(self, username, password):
        # Skip login if credentials are missing
        if not username or not password:
            return

        resp = self.session.post(
            f"{self.url}/api/v2/auth/login",
            data={"username": username, "password": password},
            timeout=10,
        )
        resp.raise_for_status()

    def get_torrents(self):
        resp = self.session.get(
            f"{self.url}/api/v2/torrents/info",
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def delete(self, torrent_hash, delete_files):
        resp = self.session.post(
            f"{self.url}/api/v2/torrents/delete",
            data={
                "hashes": torrent_hash,
                "deleteFiles": str(delete_files).lower(),
            },
            timeout=10,
        )
        resp.raise_for_status()