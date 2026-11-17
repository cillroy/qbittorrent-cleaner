"""Unit tests for rule matching, validation, and cleanup safeguards."""
import unittest
from unittest.mock import Mock, patch

from cleaner import (
    Cleaner,
    last_activity_timestamp,
    load_cleanup_settings,
    match_torrent,
    rule_has_include_incomplete,
    rule_is_dry_run,
    rule_match_problems,
    split_numeric_match_key,
    torrent_has_keep_tag,
    torrent_is_complete,
)


def hours_since(ts):
    """Treat the timestamp value itself as already-elapsed hours."""
    return float(ts)


def torrent(**kwargs):
    data = {
        "hash": "abc",
        "name": "Show",
        "category": "tv-sonarr",
        "label": "tv",
        "state": "uploading",
        "ratio": 1.0,
        "progress": 1.0,
        "last_activity": 50,
        "added_on": 80,
        "tags": "",
    }
    data.update(kwargs)
    return data


def rule(name="idle", match=None, **kwargs):
    data = {
        "name": name,
        "match": match if match is not None else {
            "category_in": ["tv-sonarr", "radarr"],
            "last_activity_hours_gte": 40,
        },
        "action": {"delete_torrent": True, "delete_files": True},
    }
    data.update(kwargs)
    return data


class SplitKeyTests(unittest.TestCase):
    def test_longer_operator_wins(self):
        self.assertEqual(split_numeric_match_key("ratio_gte"), ("ratio", "gte"))
        self.assertEqual(split_numeric_match_key("ratio_gt"), ("ratio", "gt"))
        self.assertEqual(split_numeric_match_key("ratio_lte"), ("ratio", "lte"))
        self.assertEqual(split_numeric_match_key("ratio_lt"), ("ratio", "lt"))
        self.assertEqual(
            split_numeric_match_key("last_activity_hours_gte"),
            ("last_activity_hours", "gte"),
        )
        self.assertIsNone(split_numeric_match_key("ratio_gtt")[0])
        self.assertIsNone(split_numeric_match_key("tracker_contains")[0])


class ValidationTests(unittest.TestCase):
    def test_valid_live_style_rule(self):
        self.assertEqual(rule_match_problems(rule()), [])

    def test_empty_match_is_invalid(self):
        self.assertEqual(rule_match_problems(rule(match={})), ["empty match block"])
        self.assertEqual(rule_match_problems({"name": "x", "match": None}), ["empty match block"])

    def test_unknown_key_is_invalid(self):
        problems = rule_match_problems(rule(match={
            "category_in": ["radarr"],
            "last_activity_hours_gte": 40,
            "size_gt": 1,
        }))
        self.assertTrue(any("size_gt" in p for p in problems))

    def test_unknown_key_without_time_reports_both(self):
        problems = rule_match_problems(rule(match={"ratio_gt": 1.5}))
        self.assertTrue(any("missing time condition" in p for p in problems))
        self.assertEqual(len(problems), 1)

    def test_ratio_only_is_invalid_without_time(self):
        problems = rule_match_problems(rule(match={
            "category": "radarr",
            "ratio_gte": 1.5,
        }))
        self.assertTrue(any("missing time condition" in p for p in problems))

    def test_include_incomplete_is_supported(self):
        self.assertEqual(rule_match_problems(rule(match={
            "last_activity_hours_gte": 40,
            "include_incomplete": True,
        })), [])

    def test_added_on_counts_as_time_condition(self):
        self.assertEqual(rule_match_problems(rule(match={
            "state": "stalledDL",
            "added_on_hours_gt": 168,
        })), [])


class OperatorTests(unittest.TestCase):
    def _check(self, field_key, torrent_kwargs, expected):
        r = rule(match={field_key: 10})
        self.assertTrue(match_torrent(torrent(**torrent_kwargs), r, hours_since) is expected)

    def test_ratio_operators(self):
        self.assertTrue(match_torrent(torrent(ratio=10.1), rule(match={
            "last_activity_hours_gte": 0, "ratio_gt": 10,
        }), hours_since))
        self.assertFalse(match_torrent(torrent(ratio=10), rule(match={
            "last_activity_hours_gte": 0, "ratio_gt": 10,
        }), hours_since))
        self.assertTrue(match_torrent(torrent(ratio=10), rule(match={
            "last_activity_hours_gte": 0, "ratio_gte": 10,
        }), hours_since))
        self.assertTrue(match_torrent(torrent(ratio=9.9), rule(match={
            "last_activity_hours_gte": 0, "ratio_lt": 10,
        }), hours_since))
        self.assertTrue(match_torrent(torrent(ratio=10), rule(match={
            "last_activity_hours_gte": 0, "ratio_lte": 10,
        }), hours_since))
        self.assertFalse(match_torrent(torrent(ratio=10.1), rule(match={
            "last_activity_hours_gte": 0, "ratio_lte": 10,
        }), hours_since))

    def test_last_activity_operators(self):
        self.assertTrue(match_torrent(torrent(last_activity=11), rule(match={
            "last_activity_hours_gt": 10,
        }), hours_since))
        self.assertFalse(match_torrent(torrent(last_activity=10), rule(match={
            "last_activity_hours_gt": 10,
        }), hours_since))
        self.assertTrue(match_torrent(torrent(last_activity=10), rule(match={
            "last_activity_hours_gte": 10,
        }), hours_since))
        self.assertTrue(match_torrent(torrent(last_activity=9), rule(match={
            "last_activity_hours_lt": 10,
        }), hours_since))
        self.assertTrue(match_torrent(torrent(last_activity=10), rule(match={
            "last_activity_hours_lte": 10,
        }), hours_since))

    def test_added_on_operators(self):
        self.assertTrue(match_torrent(torrent(added_on=11), rule(match={
            "added_on_hours_gt": 10,
        }), hours_since))
        self.assertFalse(match_torrent(torrent(added_on=10), rule(match={
            "added_on_hours_gt": 10,
        }), hours_since))
        self.assertTrue(match_torrent(torrent(added_on=10), rule(match={
            "added_on_hours_gte": 10,
        }), hours_since))
        self.assertTrue(match_torrent(torrent(added_on=9), rule(match={
            "added_on_hours_lt": 10,
        }), hours_since))
        self.assertTrue(match_torrent(torrent(added_on=10), rule(match={
            "added_on_hours_lte": 10,
        }), hours_since))

    def test_invalid_rule_never_matches(self):
        self.assertFalse(match_torrent(torrent(), rule(match={
            "last_activity_hours_gte": 0,
            "size_gt": 1,
        }), hours_since))
        self.assertFalse(match_torrent(torrent(), rule(match={}), hours_since))


class LastActivityFallbackTests(unittest.TestCase):
    def test_zero_last_activity_uses_added_on(self):
        self.assertEqual(last_activity_timestamp(torrent(last_activity=0, added_on=48)), 48)
        self.assertTrue(match_torrent(torrent(last_activity=0, added_on=48), rule(match={
            "last_activity_hours_gte": 40,
        }), hours_since))

    def test_missing_last_activity_uses_added_on(self):
        t = torrent(added_on=48)
        del t["last_activity"]
        self.assertEqual(last_activity_timestamp(t), 48)

    def test_both_missing_are_not_1970(self):
        t = torrent(last_activity=0, added_on=0)
        self.assertEqual(last_activity_timestamp(t), 0)
        self.assertFalse(match_torrent(t, rule(match={
            "last_activity_hours_gte": 40,
        }), hours_since))


class IncompleteAndKeepTests(unittest.TestCase):
    def test_incomplete_skipped_by_default(self):
        self.assertFalse(torrent_is_complete(torrent(progress=0.5)))
        self.assertFalse(match_torrent(torrent(progress=0.5), rule(), hours_since))

    def test_include_incomplete_at_rule_level(self):
        self.assertTrue(rule_has_include_incomplete(rule(include_incomplete=True)))
        self.assertTrue(match_torrent(
            torrent(progress=0.5),
            rule(include_incomplete=True),
            hours_since,
        ))

    def test_include_incomplete_in_match(self):
        r = rule(match={
            "last_activity_hours_gte": 40,
            "include_incomplete": True,
        })
        self.assertTrue(match_torrent(torrent(progress=0.2), r, hours_since))

    def test_keep_tag_case_insensitive_and_csv(self):
        self.assertTrue(torrent_has_keep_tag(torrent(tags="home, Keep, tv")))
        self.assertTrue(torrent_has_keep_tag(torrent(tags="KEEP")))
        self.assertTrue(torrent_has_keep_tag(torrent(tags=["tv", "keep"])))
        self.assertFalse(torrent_has_keep_tag(torrent(tags="keeper, tv")))
        self.assertFalse(torrent_has_keep_tag(torrent(tags="")))


class SettingsTests(unittest.TestCase):
    def test_default_cap_when_absent(self):
        self.assertEqual(load_cleanup_settings({})["max_deletes_per_run"], 20)
        self.assertFalse(load_cleanup_settings({})["dry_run"])

    def test_invalid_cap_uses_default(self):
        self.assertEqual(load_cleanup_settings({
            "cleanup": {"max_deletes_per_run": "nope"}
        })["max_deletes_per_run"], 20)
        self.assertEqual(load_cleanup_settings({
            "cleanup": {"max_deletes_per_run": -5}
        })["max_deletes_per_run"], 20)

    def test_explicit_zero_cap_is_allowed(self):
        self.assertEqual(load_cleanup_settings({
            "cleanup": {"max_deletes_per_run": 0}
        })["max_deletes_per_run"], 0)

    def test_global_dry_run(self):
        self.assertTrue(load_cleanup_settings({
            "cleanup": {"dry_run": True}
        })["dry_run"])
        self.assertTrue(rule_is_dry_run(rule(), global_dry_run=True))
        self.assertTrue(rule_is_dry_run(rule(dry_run=True)))
        self.assertFalse(rule_is_dry_run(rule()))


def _runner(rules, torrents, config_extra=None):
    cleaner = Cleaner.__new__(Cleaner)
    cleaner.logger = Mock()
    cleaner.schedule_logger = Mock()
    cleaner.notifier = Mock()
    cleaner.config = {"rules": rules, "qbittorrent": {"url": "http://x"}}
    if config_extra:
        cleaner.config.update(config_extra)
    cleaner.reload_config = Mock()
    cleaner.hours_since = hours_since
    cleaner.client = Mock()
    cleaner.client.get_torrents.return_value = torrents
    return cleaner


def _run(cleaner):
    with patch("schedule.load_schedule_config", return_value={"interval_seconds": 30}), \
            patch("schedule.record_run") as record_run, \
            patch("cleaner.record_cleanup_result"), \
            patch("cleaner.record_delete_cap_alert") as cap_alert:
        cleaner.run(source="test")
    return record_run, cap_alert


class RunBehaviorTests(unittest.TestCase):
    def test_first_matching_rule_wins(self):
        rules = [
            rule("first", match={"category": "tv-sonarr", "last_activity_hours_gte": 0},
                 **{"action": {"delete_torrent": True, "delete_files": False}}),
            rule("second", match={"category": "tv-sonarr", "last_activity_hours_gte": 0}),
        ]
        cleaner = _runner(rules, [torrent()])
        _run(cleaner)
        cleaner.client.delete.assert_called_once_with("abc", False)
        logged = " ".join(str(c.args[0]) for c in cleaner.logger.call_args_list)
        self.assertIn("via rule first", logged)
        self.assertNotIn("via rule second", logged)

    def test_unknown_key_is_logged_once_and_never_deletes(self):
        bad = rule(match={"category": "tv-sonarr", "last_activity_hours_gte": 0, "size_gt": 1})
        cleaner = _runner([bad], [torrent(), torrent(hash="def", name="Other")])
        _run(cleaner)
        cleaner.client.delete.assert_not_called()
        messages = [c.args[0] for c in cleaner.logger.call_args_list]
        skips = [m for m in messages if m.startswith("Skipping invalid rule")]
        self.assertEqual(len(skips), 1)
        self.assertIn("size_gt", skips[0])

    def test_keep_tag_never_deleted(self):
        cleaner = _runner([rule()], [torrent(tags="tv, KEEP")])
        _run(cleaner)
        cleaner.client.delete.assert_not_called()
        logged = " ".join(str(c.args[0]) for c in cleaner.logger.call_args_list)
        self.assertIn("Skipping delete (keep tag)", logged)

    def test_dry_run_logs_and_does_not_delete_or_count_toward_cap(self):
        items = [torrent(hash=f"h{i}", name=f"T{i}", last_activity=50) for i in range(3)]
        cleaner = _runner(
            [rule(dry_run=True)],
            items,
            {"cleanup": {"max_deletes_per_run": 1}},
        )
        record_run, cap_alert = _run(cleaner)
        cleaner.client.delete.assert_not_called()
        cap_alert.assert_not_called()
        logs = [c.args[0] for c in cleaner.logger.call_args_list]
        would = [m for m in logs if m.startswith("Would delete:")]
        self.assertEqual(len(would), 3)
        kwargs = record_run.call_args.kwargs
        self.assertEqual(kwargs["deleted"], 0)
        self.assertEqual(kwargs["would_delete"], 3)
        self.assertFalse(kwargs["capped"])

    def test_global_dry_run(self):
        cleaner = _runner([rule()], [torrent()], {"cleanup": {"dry_run": True}})
        _run(cleaner)
        cleaner.client.delete.assert_not_called()
        logged = " ".join(str(c.args[0]) for c in cleaner.logger.call_args_list)
        self.assertIn("Would delete:", logged)
        self.assertIn("Global dry_run is enabled", logged)

    def test_delete_cap_stops_and_alerts(self):
        items = [torrent(hash=f"h{i}", name=f"T{i}", last_activity=50) for i in range(3)]
        cleaner = _runner(
            [rule()],
            items,
            {"cleanup": {"max_deletes_per_run": 2}},
        )
        record_run, cap_alert = _run(cleaner)
        self.assertEqual(cleaner.client.delete.call_count, 2)
        cap_alert.assert_called_once()
        self.assertEqual(cap_alert.call_args.kwargs["cap"], 2)
        self.assertEqual(cap_alert.call_args.kwargs["deleted"], 2)
        logged = " ".join(str(c.args[0]) for c in cleaner.logger.call_args_list)
        self.assertIn("Delete cap reached", logged)
        kwargs = record_run.call_args.kwargs
        self.assertEqual(kwargs["deleted"], 2)
        self.assertTrue(kwargs["capped"])

    def test_incomplete_not_deleted_without_opt_in(self):
        cleaner = _runner([rule()], [torrent(progress=0.4)])
        _run(cleaner)
        cleaner.client.delete.assert_not_called()

    def test_incomplete_deleted_with_opt_in(self):
        cleaner = _runner([rule(include_incomplete=True)], [torrent(progress=0.4)])
        _run(cleaner)
        cleaner.client.delete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
