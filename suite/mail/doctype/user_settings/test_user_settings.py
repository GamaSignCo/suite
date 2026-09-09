# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from suite.mail.utils.user import DEFAULT_UNDO_SEND_PERIOD, get_undo_send_period

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestUserSettings(IntegrationTestCase):
    """
    Integration tests for UserSettings.
    Use this class for testing interactions between multiple components.
    """

    def test_undo_send_period(self):
        # Every user's plain Send is held for their own period. Anything off the list (no settings
        # row yet, a direct DB edit) falls back to the default, so the hold is never 0 or unbounded.
        user = frappe.get_doc(
            doctype="User",
            email=f"undo-send-{frappe.generate_hash(length=6)}@example.test",
            first_name="Undo",
            send_welcome_email=0,
        ).insert(ignore_permissions=True)
        settings = frappe.db.get_value("User Settings", {"user": user.name})
        self.assertTrue(settings, "User Settings should be created with the user.")
        self.assertEqual(get_undo_send_period(user.name), DEFAULT_UNDO_SEND_PERIOD)

        frappe.db.set_value("User Settings", settings, "undo_send_period", "30")
        self.assertEqual(get_undo_send_period(user.name), 30)

        frappe.db.set_value("User Settings", settings, "undo_send_period", "7")
        self.assertEqual(get_undo_send_period(user.name), DEFAULT_UNDO_SEND_PERIOD)

        self.assertEqual(get_undo_send_period("nobody@example.test"), DEFAULT_UNDO_SEND_PERIOD)

        # The form itself only offers the listed periods.
        doc = frappe.get_doc("User Settings", settings)
        doc.undo_send_period = "7"
        self.assertRaises(frappe.ValidationError, doc.save)
