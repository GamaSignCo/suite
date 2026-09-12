# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from suite.calendar.api import get_calendars
from suite.calendar.doctype.calendar.calendar import (
    add_calendar,
    bulk_delete,
    delete_calendars,
    fetch_calendars,
    get_calendar,
    update_calendar,
)
from suite.mail.tests.base import StalwartIntegrationTestCase, unique_name


class TestCalendarCalendars(StalwartIntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.member = cls.create_member()
        cls.account = cls.personal_account(cls.member)

    def _calendars(self) -> dict[str, dict]:
        with self.set_user(self.member.email):
            return {c["_name"]: c for c in fetch_calendars(self.account, limit=50)}

    def test_default_calendar(self):
        with self.set_user(self.member.email):
            rows = get_calendars(self.account)
        self.assertTrue(rows)
        self.assertTrue(any(c["default"] for c in self._calendars().values()))

    def test_calendar_lifecycle(self):
        name = unique_name("cal")
        with self.set_user(self.member.email):
            calendar_id = add_calendar(self.account, name, color="#336699", description="Test calendar")

            detail = get_calendar(self.account, calendar_id)
            self.assertEqual(detail["_name"], name)
            self.assertEqual(detail["color"], "#336699")

            renamed = f"{name}-renamed"
            update_calendar(self.account, calendar_id, renamed, color="#993366")
            detail = get_calendar(self.account, calendar_id)
            self.assertEqual(detail["_name"], renamed)
            self.assertEqual(detail["color"], "#993366")

            delete_calendars(self.account, [calendar_id], remove_events=True)
        self.assertNotIn(renamed, self._calendars())

    def test_bulk_delete(self):
        name = unique_name("cal")
        with self.set_user(self.member.email):
            calendar_id = add_calendar(self.account, name)
            bulk_delete([f"{self.account}|{calendar_id}"])
        self.assertNotIn(name, self._calendars())

    def test_foreign_account_denied(self):
        other = self.create_member()
        with self.set_user(other.email):
            self.assertRaises(Exception, add_calendar, self.account, unique_name("cal"))
