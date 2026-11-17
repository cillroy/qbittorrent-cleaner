"""Tests for delete-cap email cooldown behavior."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import notify_email


class DeleteCapEmailTests(unittest.TestCase):
    def test_disabled_email_does_not_send(self):
        logs = []
        with patch.object(notify_email, "load_email_config", return_value={
            "enabled": False, "cooldown_hours": 6,
        }), patch.object(notify_email, "load_alert_state", return_value={}), \
             patch.object(notify_email, "send_email") as send, \
             patch.object(notify_email, "save_alert_state"):
            notify_email.record_delete_cap_alert(20, 20, logger=logs.append)
        send.assert_not_called()

    def test_sends_when_enabled(self):
        logs = []
        cfg = {
            "enabled": True, "cooldown_hours": 6, "from_address": "a@b.c",
            "to": ["a@b.c"], "smtp_host": "smtp.example.com",
        }
        with patch.object(notify_email, "load_email_config", return_value=cfg), \
             patch.object(notify_email, "load_alert_state", return_value={}), \
             patch.object(notify_email, "send_email") as send, \
             patch.object(notify_email, "save_alert_state") as save, \
             patch.object(notify_email, "_app_version", return_value="1.0.12"):
            notify_email.record_delete_cap_alert(20, 20, logger=logs.append)
        send.assert_called_once()
        self.assertTrue(any("delete cap email sent" in m for m in logs))
        saved = save.call_args[0][0]
        self.assertIn("last_cap_alert_at", saved)

    def test_respects_cooldown(self):
        logs = []
        now = datetime(2026, 11, 16, 21, 0, 0)
        cfg = {"enabled": True, "cooldown_hours": 6}
        state = {"last_cap_alert_at": (now - timedelta(hours=1)).isoformat()}
        with patch.object(notify_email, "load_email_config", return_value=cfg), \
             patch.object(notify_email, "load_alert_state", return_value=state), \
             patch.object(notify_email, "send_email") as send, \
             patch.object(notify_email, "save_alert_state"):
            notify_email.record_delete_cap_alert(5, 5, logger=logs.append, now=now)
        send.assert_not_called()
        self.assertTrue(any("cooldown" in m for m in logs))


if __name__ == "__main__":
    unittest.main()
