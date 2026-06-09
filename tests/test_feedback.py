import copy
import unittest

from tender_agent.feedback import (
    FeedbackConflict,
    apply_events,
    apply_rules_to_payload,
    empty_rules,
    parse_feedback_body,
)


def event(action, event_id, **extra):
    return {
        "id": event_id,
        "action": action,
        "url": "https://example.com/1",
        "item": {
            "url": "https://example.com/1",
            "title": "原项目名称",
            "buyer": "原采购人",
        },
        **extra,
    }


class FeedbackTests(unittest.TestCase):
    def test_parse_machine_readable_issue_body(self):
        body = (
            "人工反馈\n\n<!-- TENDER_FEEDBACK_JSON\n"
            '{"events":[{"id":"1","action":"confirm",'
            '"url":"https://example.com/1"}]}\n-->'
        )
        self.assertEqual(parse_feedback_body(body)[0]["action"], "confirm")

    def test_confirmed_item_is_restored_and_correction_is_applied(self):
        rules = apply_events(
            empty_rules(),
            [
                event("confirm", "1"),
                event(
                    "correct",
                    "2",
                    field="buyer",
                    old_value="原采购人",
                    new_value="纠正后的采购人",
                ),
            ],
            "2026-06-10T08:00:00+08:00",
        )
        payload = {"items": []}
        apply_rules_to_payload(payload, rules)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["buyer"], "纠正后的采购人")
        self.assertEqual(payload["items"][0]["review_status"], "confirmed")

    def test_excluded_item_is_removed(self):
        rules = apply_events(
            empty_rules(),
            [event("exclude", "1", reason="采购内容与图文广告无关")],
        )
        payload = {"items": [copy.deepcopy(event("confirm", "x")["item"])]}
        apply_rules_to_payload(payload, rules)
        self.assertEqual(payload["items"], [])
        self.assertEqual(
            rules["summary"]["exclusion_reasons"][0]["reason"],
            "采购内容与图文广告无关",
        )

    def test_opposite_status_requires_recheck(self):
        rules = apply_events(empty_rules(), [event("confirm", "1")])
        with self.assertRaises(FeedbackConflict):
            apply_events(
                rules,
                [event("exclude", "2", reason="实际无关")],
            )

    def test_processed_event_is_idempotent(self):
        rules = apply_events(empty_rules(), [event("confirm", "1")])
        repeated = apply_events(rules, [event("confirm", "1")])
        self.assertEqual(
            len(repeated["items"]["https://example.com/1"]["history"]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
