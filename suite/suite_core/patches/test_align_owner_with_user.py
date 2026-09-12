# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase

from suite.suite_core.patches.align_owner_with_user import OWNER_FROM_USER_DOCTYPES, execute


def make_suite_user() -> str:
    email = f"align-owner-{uuid4().hex[:8]}@example.com"
    user = frappe.new_doc("User")
    user.email = email
    user.first_name = "Align Owner Test"
    user.append("roles", {"role": "Suite User"})
    user.insert(ignore_permissions=True)
    return email


def insert_bare_row(doctype: str, user: str | None, owner: str) -> str:
    """Insert a minimal legacy-style row directly, bypassing controllers.

    The patch is a plain UPDATE, so document validation is irrelevant to what it sees;
    a bare row is enough and keeps the expensive doctypes (exchanges, queue) cheap to
    populate. Setting owner explicitly sidesteps the OwnerFromUser mixin, which is
    exactly the state of records that predate it.
    """

    doc = frappe.new_doc(doctype)
    doc.name = uuid4().hex
    doc.user = user
    doc.owner = owner
    doc.db_insert()
    return doc.name


class AlignOwnerWithUser(IntegrationTestCase):
    """Regression tests for the owner backfill over legacy per-user records.

    Records created before the OwnerFromUser mixin are owned by whoever provisioned
    them (typically Administrator), which locks the actual user out of their own record
    through the Suite User role's if_owner permissions. The patch must restore access
    on those records without rewriting rows that are already correct or that carry no
    user at all.
    """

    def setUp(self) -> None:
        self.addCleanup(frappe.set_user, "Administrator")
        self.user = make_suite_user()
        # Created by the User after_insert hook, owner already pinned to the user.
        self.settings = frappe.db.get_value("User Settings", {"user": self.user}, "name")

    def test_realigns_stale_owner_and_restores_access(self) -> None:
        frappe.db.set_value("User Settings", self.settings, "owner", "Administrator", update_modified=False)

        frappe.set_user(self.user)
        self.assertFalse(frappe.has_permission("User Settings", "read", doc=self.settings))

        frappe.set_user("Administrator")
        execute()

        self.assertEqual(frappe.db.get_value("User Settings", self.settings, "owner"), self.user)
        frappe.set_user(self.user)
        self.assertTrue(frappe.has_permission("User Settings", "read", doc=self.settings))

    def test_realigns_every_owner_from_user_doctype(self) -> None:
        rows = {
            doctype: insert_bare_row(doctype, user=self.user, owner="Administrator")
            for doctype in OWNER_FROM_USER_DOCTYPES
            if doctype != "User Settings"  # covered via the hook-created record above
        }

        execute()

        for doctype, name in rows.items():
            self.assertEqual(frappe.db.get_value(doctype, name, "owner"), self.user, doctype)

    def test_leaves_aligned_and_userless_rows_untouched(self) -> None:
        aligned_modified = frappe.db.get_value("User Settings", self.settings, "modified")
        orphan = insert_bare_row("Mail Signature", user=None, owner="Administrator")

        execute()

        self.assertEqual(frappe.db.get_value("User Settings", self.settings, "owner"), self.user)
        self.assertEqual(frappe.db.get_value("User Settings", self.settings, "modified"), aligned_modified)
        self.assertEqual(frappe.db.get_value("Mail Signature", orphan, "owner"), "Administrator")

    def test_rerun_is_a_noop(self) -> None:
        frappe.db.set_value("User Settings", self.settings, "owner", "Administrator", update_modified=False)
        execute()
        modified = frappe.db.get_value("User Settings", self.settings, "modified")

        execute()

        self.assertEqual(frappe.db.get_value("User Settings", self.settings, "owner"), self.user)
        self.assertEqual(frappe.db.get_value("User Settings", self.settings, "modified"), modified)
