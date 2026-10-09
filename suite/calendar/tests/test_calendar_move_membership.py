from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from suite.calendar.doctype.calendar_event import calendar_event


class CalendarMoveMembershipTest(UnitTestCase):
    def test_moving_an_event_without_calendar_ids_keeps_its_calendars(self):
        event = self.update_event()
        self.assertEqual(event["calendar_ids"], ["team-calendar"])

    def test_an_explicit_calendar_change_is_respected(self):
        event = self.update_event(calendar_ids=["other-calendar"])
        self.assertEqual(event["calendar_ids"], ["other-calendar"])

    def test_an_explicit_empty_list_keeps_the_default_calendar_behavior(self):
        event = self.update_event(calendar_ids=[])
        self.assertEqual(event["calendar_ids"], [])

    def update_event(self, **kwargs):
        stored = {"id": "event-1", "calendarIds": {"team-calendar": True, "removed-calendar": False}}
        with (
            patch.object(calendar_event, "get_account_client"),
            patch.object(calendar_event.jmap_events, "get_events", return_value=[stored]),
            patch.object(
                calendar_event.jmap_events,
                "update_events",
                return_value=frappe._dict(updated={"event-1": None}),
            ) as update,
            patch.object(calendar_event, "_reanchor_overrides"),
        ):
            calendar_event.update_calendar_event(
                "account-1", "event-1", start="2026-10-10T09:00:00", duration="PT1H", **kwargs
            )
        return update.call_args.args[2][0]
