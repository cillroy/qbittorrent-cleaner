"""Tests for comment-preserving YAML scalar updates."""
import unittest

from yamlutil import apply_yaml_updates, get_yaml_scalar, update_yaml_scalar, values_equal


SAMPLE = """qbittorrent:
  url: http://127.0.0.1:8113
# keep this comment
web:
  port: 8002
  username: admin
  password: 'change-me'   # do not lose me
  enable_auth: true
# notifications stay
notifications:
  email:
    enabled: true
    to: ["user@example.com"]
    # Email when cleanup fails
    cooldown_hours: 6
rules:
  - name: keep me
    match:
      category_in: ["radarr"]
"""


class YamlUtilTests(unittest.TestCase):
    def test_insert_auto_start_preserves_comments_and_rules(self):
        text, changed = apply_yaml_updates(SAMPLE, [(["web", "auto_start"], True)])
        self.assertEqual(changed, ["web.auto_start"])
        self.assertIn("auto_start: true", text)
        self.assertIn("password: 'change-me'   # do not lose me", text)
        self.assertIn("# keep this comment", text)
        self.assertIn("# Email when cleanup fails", text)
        self.assertIn('to: ["user@example.com"]', text)
        self.assertIn("  - name: keep me", text)
        self.assertIn('category_in: ["radarr"]', text)

    def test_noop_when_value_already_matches(self):
        text, changed = apply_yaml_updates(SAMPLE, [(["web", "enable_auth"], True)])
        self.assertEqual(text, SAMPLE)
        self.assertEqual(changed, [])

    def test_update_existing_keeps_trailing_comment(self):
        text = update_yaml_scalar(SAMPLE, ["web", "password"], "change-me")
        # same value, but update_yaml_scalar always writes; quoting may change
        text, changed = apply_yaml_updates(SAMPLE, [(["web", "port"], 8003)])
        self.assertEqual(changed, ["web.port"])
        self.assertIn("port: 8003", text)
        self.assertIn("password: 'change-me'   # do not lose me", text)
        self.assertNotIn("port: 8002", text)

    def test_flip_bool(self):
        seeded, _ = apply_yaml_updates(SAMPLE, [(["web", "auto_start"], True)])
        text, changed = apply_yaml_updates(seeded, [(["web", "auto_start"], False)])
        self.assertEqual(changed, ["web.auto_start"])
        self.assertIn("auto_start: false", text)
        self.assertNotIn("auto_start: true", text)

    def test_get_missing(self):
        found, value = get_yaml_scalar(SAMPLE, ["web", "auto_start"])
        self.assertFalse(found)
        self.assertIsNone(value)

    def test_values_equal_bools(self):
        self.assertTrue(values_equal(True, True))
        self.assertFalse(values_equal(True, 1))

    def test_creates_missing_cleanup_before_rules(self):
        text, changed = apply_yaml_updates(
            SAMPLE,
            [(["cleanup", "max_deletes_per_run"], 20), (["cleanup", "dry_run"], False)],
        )
        self.assertIn("cleanup:", text)
        self.assertIn("max_deletes_per_run: 20", text)
        self.assertLess(text.index("cleanup:"), text.index("rules:"))
        self.assertIn("  - name: keep me", text)
        self.assertIn("# Email when cleanup fails", text)


if __name__ == "__main__":
    unittest.main()
