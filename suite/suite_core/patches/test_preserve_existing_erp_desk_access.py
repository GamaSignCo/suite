from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase

from suite.suite_core.patches import preserve_existing_erp_desk_access as preserve
from suite.suite_core.patches.remove_desk_access_from_suite_roles import execute as remove_suite_desk


class PreserveExistingERPDeskAccess(IntegrationTestCase):
    def setUp(self):
        self.enterContext(patch.object(frappe.db, "commit"))
        self.enterContext(patch.object(preserve, "is_erp_site", return_value=True))
        frappe.db.set_value("Role", "Suite User", "desk_access", 1)

    def test_existing_system_user_keeps_desk_without_new_document_permissions(self):
        user = self.make_user()
        before = frappe.has_permission("User", ptype="write", user=user.name)

        preserve.execute()
        remove_suite_desk()
        user.reload()

        self.assertEqual(user.user_type, "System User")
        self.assertIn(preserve.ROLE, {row.role for row in user.roles})
        self.assertEqual(frappe.has_permission("User", ptype="write", user=user.name), before)
        self.assertFalse(frappe.db.exists("DocPerm", {"role": preserve.ROLE}))
        self.assertFalse(frappe.db.exists("Custom DocPerm", {"role": preserve.ROLE}))

    def test_the_preservation_patch_is_idempotent(self):
        user = self.make_user()
        preserve.execute()
        preserve.execute()
        user.reload()
        self.assertEqual(sum(row.role == preserve.ROLE for row in user.roles), 1)

    def test_existing_website_user_is_not_promoted(self):
        frappe.db.set_value("Role", "Suite User", "desk_access", 0)
        user = self.make_user()
        self.assertEqual(user.user_type, "Website User")
        preserve.execute()
        user.reload()
        self.assertEqual(user.user_type, "Website User")
        self.assertNotIn(preserve.ROLE, {row.role for row in user.roles})

    def test_standalone_suite_does_not_preserve_erp_desk_access(self):
        user = self.make_user()
        with patch.object(preserve, "is_erp_site", return_value=False):
            preserve.execute()
        user.reload()
        self.assertNotIn(preserve.ROLE, {row.role for row in user.roles})

    def make_user(self):
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"suite-desk-{uuid4().hex}@example.com",
                "first_name": "Suite Desk Test",
                "send_welcome_email": 0,
                "roles": [{"role": "Suite User"}],
            }
        )
        user.insert(ignore_permissions=True)
        return user
