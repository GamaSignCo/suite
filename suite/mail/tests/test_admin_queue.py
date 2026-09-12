# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import UTC, datetime, timedelta

import frappe

from suite.mail.api.admin import (
    cancel_all_queued_messages,
    cancel_queued_messages,
    get_queue_recipient_options,
    get_queued_message,
    get_queued_message_source,
    get_queued_messages,
    remove_queued_recipient,
    retry_all_queued_messages,
    retry_queued_messages,
    run_action,
    update_queued_message,
    update_queued_recipient,
)
from suite.mail.tests.base import StalwartIntegrationTestCase, unique_name


def _utc_z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestAdminQueue(StalwartIntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sender = cls.create_member()
        cls.recipient = cls.create_member()
        cls.cc_recipient = cls.create_member()

    def _park_mail_in_queue(self) -> tuple[str, str]:
        """Pauses MTA queue processing and sends a mail so it parks in the queue.

        Stalwart validates recipient domains at submission, so an unroutable address cannot be
        used to fill the queue - pausing the queue with a deliverable message is deterministic.
        """

        run_action("PauseMtaQueue")
        self.addCleanup(run_action, "ResumeMtaQueue")

        subject = f"Queued mail {unique_name('subject')}"
        result = self.send_mail(
            self.sender,
            self.recipient.email,
            subject=subject,
            cc=[{"email": self.cc_recipient.email}],
        )
        self.assertEqual(result["status"], "Submitted", result.get("error"))

        message = self.wait_until(
            lambda: next(
                (
                    m
                    for m in get_queued_messages(to=self.recipient.email, page_length=10)["messages"]
                    if self.recipient.email in m["recipients"]
                ),
                None,
            ),
            message="Mail never appeared in the paused queue.",
        )
        return message["id"], self.recipient.email

    def test_queue_lifecycle(self):
        message_id, recipient = self._park_mail_in_queue()

        listing = get_queued_messages(to=recipient)
        self.assertGreaterEqual(listing["total"], 1)

        detail = get_queued_message(message_id)
        self.assertEqual(detail["id"], message_id)
        self.assertIn(recipient, [r["email"] for r in detail["recipients"]])
        self.assertTrue(detail["has_content"])
        self.assertTrue(detail["created_at"])

        source = get_queued_message_source(message_id)
        self.assertIn("Subject:", source["source"])

        options = get_queue_recipient_options()
        for key in ("status_types", "error_types", "expiry_types"):
            self.assertTrue(options[key])

        # Queue retry edits round-trip on Stalwart v0.16.16+ (older stock builds accepted the
        # update but silently ignored nextRetry/retryDue writes).
        next_retry = _utc_z(datetime.now(UTC) + timedelta(hours=6))
        update_queued_message(message_id, next_retry=next_retry)
        self.assertEqual(get_queued_message(message_id)["next_retry"], next_retry)

        recipient_retry = _utc_z(datetime.now(UTC) + timedelta(hours=2))
        update_queued_recipient(message_id, recipient, next_retry=recipient_retry)
        row = next(r for r in get_queued_message(message_id)["recipients"] if r["email"] == recipient)
        self.assertEqual(row["next_retry"], recipient_retry)

        # Removing a recipient cancels its delivery: the server keeps the row but marks it
        # permanently failed ("Delivery canceled."). The other recipient stays scheduled.
        # (There is deliberately no add endpoint - the server only patches recipients that
        # exist in the envelope.)
        remove_queued_recipient(message_id, self.cc_recipient.email)
        rows = {r["email"]: r for r in get_queued_message(message_id)["recipients"]}
        cc_row = rows.get(self.cc_recipient.email)
        if cc_row is not None:
            self.assertEqual(cc_row["status_type"], "PermanentFailure")
        self.assertIn(recipient, rows)

        # Retry schedules immediate delivery: the next retry moves back from the +6h we set.
        retry_queued_messages([message_id])
        self.assertLess(get_queued_message(message_id)["next_retry"] or _utc_z(datetime.now(UTC)), next_retry)

        cancel_queued_messages([message_id])
        self.wait_until(
            lambda: not get_queued_messages(to=recipient)["messages"],
            message="Cancelled message is still in the queue.",
        )

    def test_cancel_all_with_filter(self):
        _message_id, recipient = self._park_mail_in_queue()

        # The filtered retry-all variant schedules matching messages without erroring.
        retry_all_queued_messages(to=recipient)

        cancel_all_queued_messages(to=recipient)
        self.wait_until(
            lambda: not get_queued_messages(to=recipient)["messages"],
            message="cancel_all_queued_messages left the filtered message behind.",
        )

    def test_non_admin_cannot_manage_queue(self):
        with self.set_user(self.sender.email):
            self.assertRaises(frappe.PermissionError, get_queued_messages)
            self.assertRaises(frappe.PermissionError, retry_queued_messages, ["any-id"])
            self.assertRaises(frappe.PermissionError, cancel_queued_messages, ["any-id"])
            self.assertRaises(frappe.PermissionError, get_queued_message_source, "any-id")
