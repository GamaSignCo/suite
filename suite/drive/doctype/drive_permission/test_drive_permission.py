# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from suite.drive.utils.overrides import filter_file

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class UnitTestDrivePermission(UnitTestCase):
    """
    Unit tests for DrivePermission.
    Use this class for testing individual functions and methods.
    """

    def test_file_permission_query_uses_mariadb_identifier_quotes(self):
        with (
            patch.object(frappe, "get_roles", return_value=["Suite User"]),
            patch("suite.drive.utils.overrides.get_principals", return_value=["user@example.com"]),
            patch("suite.drive.utils.overrides.get_doctypes_with_read", return_value=[]),
        ):
            condition = filter_file("user@example.com")

        self.assertIn("`tabDrive Permission`", condition)
        self.assertIn("`tabDocShare`", condition)
        self.assertNotIn('"tabDrive Permission"', condition)
        self.assertNotIn('"tabDocShare"', condition)


class IntegrationTestDrivePermission(IntegrationTestCase):
    """
    Integration tests for DrivePermission.
    Use this class for testing interactions between multiple components.
    """

    pass
