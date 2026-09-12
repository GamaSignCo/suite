# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe

from suite.calendar.doctype.calendar_event.calendar_event import add_calendar_event
from suite.calendar.doctype.event_notification.event_notification import fetch_event_notifications
from suite.mail.api.account import create_calendar_export, create_calendar_import
from suite.mail.tests.base import StalwartIntegrationTestCase, unique_name


class TestCalendarExchangeAndNotifications(StalwartIntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.member = cls.create_member()
        cls.account = cls.personal_account(cls.member)

    def test_calendar_import(self):
        titles = [f"Imported A {unique_name('event')}", f"Imported B {unique_name('event')}"]
        vevents = "".join(
            "BEGIN:VEVENT\r\n"
            f"UID:{unique_name('uid')}\r\n"
            "DTSTAMP:20260801T000000Z\r\n"
            f"DTSTART:2026111{i}T090000Z\r\n"
            f"DTEND:2026111{i}T100000Z\r\n"
            f"SUMMARY:{title}\r\n"
            "END:VEVENT\r\n"
            for i, title in enumerate(titles)
        )
        ics = f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Suite Tests//EN\r\n{vevents}END:VCALENDAR\r\n"
        file = frappe.get_doc(
            {"doctype": "File", "file_name": "import.ics", "content": ics, "is_private": 1}
        ).insert(ignore_permissions=True)

        with self.set_user(self.member.email):
            create_calendar_import(self.account, "ics", file.file_url)
            doc = frappe.get_last_doc("Calendar Exchange", {"account": self.account, "operation": "Import"})
            doc._import()
            doc.reload()
        self.assertEqual(doc.status, "Completed", doc.get("output"))

        from suite.calendar.api import get_calendar_events

        def imported():
            with self.set_user(self.member.email):
                events = get_calendar_events(
                    self.account, "2026-11-01T00:00:00Z", "2026-11-30T00:00:00Z", "UTC"
                )
                return set(titles) <= {e["title"] for e in events} or None

        self.wait_until(imported, timeout=60, message="Imported events did not appear.")

    def test_calendar_export(self):
        with self.set_user(self.member.email):
            add_calendar_event(
                self.account,
                title=f"Exportable {unique_name('event')}",
                start="2026-11-20T09:00:00",
                duration="PT1H",
                time_zone="UTC",
            )
            create_calendar_export(self.account, "ics", ".zip", "Start (ASC)")
            doc = frappe.get_last_doc("Calendar Exchange", {"account": self.account, "operation": "Export"})
            doc._export()
            doc.reload()

        self.assertEqual(doc.status, "Completed", doc.get("output"))
        self.assertTrue(frappe.db.exists("File", {"attached_to_name": doc.name}))

    def test_calendar_jmap_round_trip(self):
        """Export in the jmap format and re-import the artifact."""

        with self.set_user(self.member.email):
            add_calendar_event(
                self.account,
                title=f"JMAP round trip {unique_name('event')}",
                start="2026-11-25T09:00:00",
                duration="PT1H",
                time_zone="UTC",
            )
            create_calendar_export(self.account, "jmap", ".tgz", "Start (DESC)")
            export = frappe.get_last_doc(
                "Calendar Exchange", {"account": self.account, "operation": "Export"}
            )
            export._export()
            export.reload()
            self.assertEqual(export.status, "Completed", export.get("output"))

            file_url = frappe.db.get_value(
                "File",
                {"attached_to_doctype": "Calendar Exchange", "attached_to_name": export.name},
                "file_url",
            )
            self.assertTrue(file_url)

            create_calendar_import(self.account, "jmap", file_url)
            imported = frappe.get_last_doc(
                "Calendar Exchange", {"account": self.account, "operation": "Import"}
            )
            imported._import()
            imported.reload()
            self.assertEqual(imported.status, "Completed", imported.get("output"))

    def test_event_notifications_contract(self):
        # Without server-side scheduling traffic the listing stays empty but must answer cleanly.
        with self.set_user(self.member.email):
            notifications, total = fetch_event_notifications(self.account)
            self.assertIsInstance(notifications, list)
            self.assertIsInstance(total, int)

        # Another user cannot read this account's notifications.
        other = self.create_member()
        with self.set_user(other.email):
            self.assertRaises(Exception, fetch_event_notifications, self.account)
