import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import frappe

from suite.meet.api.recording import _limits
from suite.meet.doctype.meet_recording.meet_recording import MeetRecording


class TestCommandLimits(unittest.TestCase):
    def test_capture_start_does_not_change_reservation_identity(self):
        recording = frappe._dict(
            pending_deadline=datetime(2026, 8, 1, 12, 31, 45, 123456),
            max_ends_at=datetime(2026, 8, 1, 16, 31, 45, 123456),
            budget_bytes=100,
        )
        with patch("frappe.utils.get_system_timezone", return_value="UTC"):
            reserved = _limits(recording)
            recording.max_ends_at = datetime(2026, 8, 1, 16, 31, 10, 987654)
            active = _limits(recording)

        self.assertEqual(reserved["max_ends_at"], "2026-08-01T16:31:45.123Z")
        self.assertEqual(active, reserved)

    def test_reservation_is_converted_from_system_timezone(self):
        recording = frappe._dict(
            pending_deadline="2026-10-15 15:01:02.345678",
            max_ends_at="2026-10-15 19:00:50",
            budget_bytes=100,
        )
        with patch("frappe.utils.get_system_timezone", return_value="Europe/Istanbul"):
            limits = _limits(recording)

        self.assertEqual(limits["max_ends_at"], "2026-10-15T16:01:02.345Z")

    def test_legacy_recording_without_startup_deadline_uses_maximum(self):
        recording = frappe._dict(
            max_ends_at="2026-08-01 16:31:45.123456", budget_bytes=100
        )
        with patch("frappe.utils.get_system_timezone", return_value="UTC"):
            limits = _limits(recording)

        self.assertEqual(limits["max_ends_at"], "2026-08-01T16:31:45.123Z")

    def test_budget_can_grow_without_changing_deadline(self):
        recording = frappe._dict(
            pending_deadline="2026-08-01 12:31:45", budget_bytes=100
        )
        with patch("frappe.utils.get_system_timezone", return_value="UTC"):
            before = _limits(recording)
            recording.budget_bytes = 200
            after = _limits(recording)

        self.assertEqual(before["budget_bytes"], 100)
        self.assertEqual(after["budget_bytes"], 200)
        self.assertEqual(after["max_ends_at"], "2026-08-01T16:31:45.000Z")
        self.assertEqual(before["max_ends_at"], after["max_ends_at"])

    def test_reservation_deadline_cannot_be_changed_after_creation(self):
        previous = frappe._dict(pending_deadline="2026-08-01 12:31:45")
        current = frappe._dict(previous, pending_deadline="2026-08-01 12:32:45")
        recording = Mock()
        recording.is_new.return_value = False
        recording.get_doc_before_save.return_value = previous
        recording.get.side_effect = current.get
        recording.has_value_changed.side_effect = lambda field: current.get(field) != previous.get(field)

        with patch("frappe.throw", side_effect=ValueError) as throw:
            with self.assertRaises(ValueError):
                MeetRecording.validate_parties(recording)

        self.assertEqual(throw.call_args.args[0], "Recording configuration cannot change")
