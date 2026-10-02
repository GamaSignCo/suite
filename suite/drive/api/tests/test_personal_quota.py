"""Personal storage charges follow the Home tree, never file ownership alone."""

import unittest
from unittest.mock import patch

from suite.drive.api import storage


class TestPersonalQuota(unittest.TestCase):
    def test_shared_project_has_no_personal_quota_owner(self):
        with patch.object(storage.frappe.db, "sql", return_value=[("project",), ("Drive",)]):
            self.assertIsNone(storage.personal_storage_owner("project"))

    def test_personal_folder_charges_home_owner_not_uploader(self):
        with (
            patch.object(storage.frappe.db, "sql", return_value=[("project",), ("bob-home",), ("Users",)]),
            patch.object(storage.frappe.db, "get_value", return_value="bob@example.com"),
        ):
            self.assertEqual(storage.personal_storage_owner("project"), "bob@example.com")

    def test_shared_upload_does_not_check_even_an_over_quota_uploader(self):
        with (
            patch.object(storage, "personal_storage_owner", return_value=None),
            patch.object(storage, "get_storage_usage") as usage,
        ):
            storage.validate_quota("alice@example.com", 100, folder="shared-project")
        usage.assert_not_called()

    def test_home_upload_charges_the_home_owner(self):
        with (
            patch.object(storage, "personal_storage_owner", return_value="bob@example.com"),
            patch.object(storage, "get_storage_usage", return_value={"limit": 100, "total_size": 70}) as usage,
        ):
            storage.validate_quota("alice@example.com", 30, folder="bob-home")
        usage.assert_called_once_with("bob@example.com")
