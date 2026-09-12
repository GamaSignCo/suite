import unittest
from unittest import mock

from suite.suite_core import setup


class BuildSetupArgs(unittest.TestCase):
    def setUp(self):
        self.frappe = self.enterContext(mock.patch("suite.suite_core.setup.frappe"))

    def test_prefers_prefilled_country(self):
        values = {"country": "India", "currency": "INR"}
        self.frappe.db.get_single_value.side_effect = lambda doctype, field: values.get(field)
        self.assertEqual(
            setup.build_setup_args("Asia/Kolkata"),
            {"country": "India", "currency": "INR", "timezone": "Asia/Kolkata"},
        )

    def test_derives_country_from_timezone(self):
        self.frappe.db.get_single_value.return_value = None
        with mock.patch(
            "frappe.geo.country_info.get_all",
            return_value={"India": {"timezones": ["Asia/Kolkata"], "currency": "INR"}},
        ):
            self.assertEqual(
                setup.build_setup_args("Asia/Kolkata"),
                {"country": "India", "currency": "INR", "timezone": "Asia/Kolkata"},
            )

    def test_falls_back_to_timezone_only(self):
        self.frappe.db.get_single_value.return_value = None
        with mock.patch("frappe.geo.country_info.get_all", return_value={}):
            self.assertEqual(setup.build_setup_args("Etc/UTC"), {"timezone": "Etc/UTC"})
