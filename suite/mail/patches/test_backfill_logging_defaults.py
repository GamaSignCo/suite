import frappe
from frappe.tests import IntegrationTestCase

from suite.mail.patches.backfill_logging_defaults import execute


class MailLoggingDefaultsTest(IntegrationTestCase):
    def test_existing_site_gets_required_logging_defaults(self):
        for field in ("log_level", "log_max_file_size_mb", "log_file_count"):
            frappe.db.set_single_value("Mail Settings", field, None)
        execute()
        settings = frappe.get_single("Mail Settings")
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.log_max_file_size_mb, 5)
        self.assertEqual(settings.log_file_count, 10)

    def test_configured_values_survive_repeated_runs(self):
        values = {"log_level": "WARNING", "log_max_file_size_mb": 20, "log_file_count": 2}
        for field, value in values.items():
            frappe.db.set_single_value("Mail Settings", field, value)
        execute()
        execute()
        settings = frappe.get_single("Mail Settings")
        self.assertEqual({field: settings.get(field) for field in values}, values)
