# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from uuid import uuid4

import frappe

from suite.calendar.api.invites import add_invite_to_calendar, get_invite_details, rsvp_to_invite
from suite.calendar.doctype.calendar_event.calendar_event import (
    get_calendar_events as get_events_by_ids,
)
from suite.mail.api.mail import create_mail
from suite.mail.tests.base import StalwartIntegrationTestCase, unique_name


class TestCalendarMailInvites(StalwartIntegrationTestCase):
    """The mail-invite flow: an inbound message carrying a text/calendar REQUEST attachment."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.member = cls.create_member()
        cls.peer = cls.create_member()
        cls.disable_screening(cls.member)
        cls.account = cls.personal_account(cls.member)

    def _send_ics_invite(self, title: str, uid: str) -> str:
        """Sends the member a mail with an ICS invite attached, returns the attachment blob id."""

        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Suite Tests//EN\r\n"
            "METHOD:REQUEST\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260801T000000Z\r\n"
            "DTSTART:20261012T100000Z\r\n"
            "DTEND:20261012T110000Z\r\n"
            f"SUMMARY:{title}\r\n"
            f"ORGANIZER;CN=Peer:mailto:{self.peer.email}\r\n"
            f"ATTENDEE;CN=Member;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{self.member.email}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        file = frappe.get_doc(
            {"doctype": "File", "file_name": "invite.ics", "content": ics, "is_private": 1}
        ).insert(ignore_permissions=True)

        subject = f"Invitation: {title}"
        with self.set_user(self.peer.email):
            result = create_mail(
                account=self.personal_account(self.peer),
                from_email=self.peer.email,
                to=[{"email": self.member.email}],
                cc=[],
                bcc=[],
                subject=subject,
                html_body="<p>You are invited.</p>",
                attachments=[
                    {
                        "file_url": file.file_url,
                        "file_name": "invite.ics",
                        "type": "text/calendar",
                        "size": len(ics),
                        "disposition": "attachment",
                    }
                ],
            )
        self.assertEqual(result["status"], "Submitted", result.get("error"))

        thread = self.wait_until(
            lambda: next((t for t in self.get_inbox_threads(self.member) if t["subject"] == subject), None),
            timeout=60,
            message="Invite mail did not arrive.",
        )
        return thread["messages"][-1]["attachments"][0]["blob_id"]

    def test_mail_invite_flow(self):
        title = f"Quarterly planning {unique_name('event')}"
        uid = uuid4().hex
        blob_id = self._send_ics_invite(title, uid)

        with self.set_user(self.member.email):
            details = get_invite_details(self.account, blob_id)
            self.assertIsNotNone(details)
            self.assertEqual(details["event"]["title"], title)
            self.assertIsNotNone(details["participant"])
            self.assertFalse(details["exists"])

            added = add_invite_to_calendar(self.account, blob_id)
            event_id = added["id"]
            detail = get_events_by_ids(self.account, [event_id])[0]
            self.assertEqual(detail["title"], title)
            self.assertEqual(detail["uid"], uid)

            # Idempotent by UID: adding again returns the same event (poll - the uid lookup
            # runs on the server's async search index).
            def add_again_is_same():
                return add_invite_to_calendar(self.account, blob_id)["id"] == event_id or None

            self.wait_until(add_again_is_same, message="Second add created a duplicate event.")
            self.assertEqual(len(get_events_by_ids(self.account, [event_id])), 1)

            self.wait_until(
                lambda: get_invite_details(self.account, blob_id)["exists"],
                message="Invite details never flipped to exists=True.",
            )

            # RSVP straight from the invite.
            rsvp_to_invite(self.account, blob_id, "accepted")
            detail = get_events_by_ids(self.account, [event_id])[0]
            me = next(p for p in detail["participants"] if p["email"] == self.member.email)
            self.assertEqual(me["participation_status"], "ACCEPTED")

    def test_non_calendar_blob(self):
        # A plain attachment holds no VEVENT - the preview endpoint answers None.
        content = b"just text"
        file = frappe.get_doc(
            {"doctype": "File", "file_name": "note.txt", "content": content, "is_private": 1}
        ).insert(ignore_permissions=True)

        subject = f"No invite {unique_name('subject')}"
        with self.set_user(self.peer.email):
            result = create_mail(
                account=self.personal_account(self.peer),
                from_email=self.peer.email,
                to=[{"email": self.member.email}],
                cc=[],
                bcc=[],
                subject=subject,
                html_body="<p>plain</p>",
                attachments=[
                    {
                        "file_url": file.file_url,
                        "file_name": "note.txt",
                        "type": "text/plain",
                        "size": len(content),
                        "disposition": "attachment",
                    }
                ],
            )
        self.assertEqual(result["status"], "Submitted", result.get("error"))

        thread = self.wait_until(
            lambda: next((t for t in self.get_inbox_threads(self.member) if t["subject"] == subject), None),
            timeout=60,
            message="Plain mail did not arrive.",
        )
        blob_id = thread["messages"][-1]["attachments"][0]["blob_id"]

        with self.set_user(self.member.email):
            self.assertIsNone(get_invite_details(self.account, blob_id))
