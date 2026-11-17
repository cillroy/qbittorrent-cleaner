"""Tests for dry-run rule preview (never deletes)."""
import unittest
from unittest.mock import Mock

from cleaner import preview_rule


def hours_since(ts):
    return float(ts)


def torrent(**kwargs):
    data = {
        "hash": "abc",
        "name": "Show",
        "category": "tv-sonarr",
        "label": "tv",
        "state": "uploading",
        "ratio": 1.25,
        "progress": 1.0,
        "last_activity": 50,
        "added_on": 80,
        "tags": "",
    }
    data.update(kwargs)
    return data


def make_rule(**kwargs):
    data = {
        "name": "idle",
        "match": {
            "category_in": ["tv-sonarr", "radarr"],
            "last_activity_hours_gte": 40,
        },
        "action": {"delete_torrent": True, "delete_files": True},
    }
    data.update(kwargs)
    return data


# rule() helper lives in test_match_rule; define locally to avoid import cycles.


class PreviewRuleTests(unittest.TestCase):
    def test_invalid_rule_returns_problems_and_no_rows(self):
        result = preview_rule(
            make_rule(match={"ratio_gt": 1}),
            [torrent()],
            hours_since,
            {"max_deletes_per_run": 20, "dry_run": False},
        )
        self.assertTrue(result["problems"])
        self.assertTrue(any("time condition" in p for p in result["problems"]))
        self.assertEqual(result["would_delete_count"], 0)
        self.assertEqual(result["would_delete"], [])
        self.assertTrue(result["dry_run"])

    def test_would_delete_fields(self):
        result = preview_rule(make_rule(), [torrent()], hours_since, {"max_deletes_per_run": 20})
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["would_delete_count"], 1)
        row = result["would_delete"][0]
        self.assertEqual(row["name"], "Show")
        self.assertEqual(row["category"], "tv-sonarr")
        self.assertEqual(row["ratio"], 1.25)
        self.assertEqual(row["state"], "uploading")
        self.assertEqual(row["progress"], 1.0)
        self.assertIn("last_activity_age", row)
        self.assertIn("added_on_age", row)

    def test_keep_tag_is_skipped(self):
        result = preview_rule(
            make_rule(),
            [torrent(tags="tv, KEEP")],
            hours_since,
            {"max_deletes_per_run": 20},
        )
        self.assertEqual(result["would_delete_count"], 0)
        self.assertEqual(result["skipped_counts"]["keep"], 1)
        self.assertEqual(result["skipped"][0]["reason"], "keep tag")

    def test_incomplete_is_skipped_unless_opted_in(self):
        items = [torrent(progress=0.4, name="Partial")]
        result = preview_rule(make_rule(), items, hours_since, {"max_deletes_per_run": 20})
        self.assertEqual(result["would_delete_count"], 0)
        self.assertEqual(result["skipped_counts"]["incomplete"], 1)
        self.assertEqual(result["skipped"][0]["reason"], "incomplete")
        opted = preview_rule(
            make_rule(include_incomplete=True),
            items,
            hours_since,
            {"max_deletes_per_run": 20},
        )
        self.assertEqual(opted["would_delete_count"], 1)
        self.assertEqual(opted["skipped_counts"]["incomplete"], 0)

    def test_cap_skips_remaining_matches(self):
        items = [torrent(hash=f"h{i}", name=f"T{i}") for i in range(3)]
        result = preview_rule(make_rule(), items, hours_since, {"max_deletes_per_run": 2})
        self.assertEqual(result["would_delete_count"], 2)
        self.assertEqual(result["skipped_counts"]["cap"], 1)
        self.assertEqual(result["skipped"][0]["reason"], "cap")
        self.assertEqual(result["delete_cap"], 2)

    def test_non_matching_torrents_are_omitted(self):
        result = preview_rule(
            make_rule(),
            [torrent(category="other", last_activity=50)],
            hours_since,
            {"max_deletes_per_run": 20},
        )
        self.assertEqual(result["would_delete_count"], 0)
        self.assertEqual(result["skipped"], [])

    def test_never_deletes(self):
        client = Mock()
        preview_rule(make_rule(), [torrent()], hours_since, {"max_deletes_per_run": 20})
        client.delete.assert_not_called()

    def test_no_delete_action_lists_none(self):
        result = preview_rule(
            make_rule(action={"delete_torrent": False, "delete_files": False}),
            [torrent()],
            hours_since,
            {"max_deletes_per_run": 20},
        )
        self.assertEqual(result["would_delete_count"], 0)
        self.assertFalse(result["delete_torrent"])


if __name__ == "__main__":
    unittest.main()
