# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase

from suite.suite_core.patches.remove_desk_access_from_suite_roles import execute

SUITE_ROLES = ("Suite User", "Suite Admin")


def make_user(*roles: str) -> str:
    """A user as sites had them before the patch: Suite User (assigned on insert) plus `roles`."""

    user = frappe.new_doc("User")
    user.email = f"desk-access-{uuid4().hex[:8]}@example.com"
    user.first_name = "Desk Access Test"
    for role in roles:
        user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return user.name


def start_session(user: str) -> None:
    sessions = frappe.qb.DocType("Sessions")
    (
        frappe.qb.into(sessions)
        .columns(sessions.user, sessions.sid, sessions.sessiondata, sessions.status)
        .insert(user, uuid4().hex, "{}", "Active")
    ).run()


def has_session(user: str) -> bool:
    return bool(frappe.db.count("Sessions", {"user": user}))


def user_type(user: str) -> str:
    return frappe.db.get_value("User", user, "user_type")


class RemoveDeskAccessFromSuiteRoles(IntegrationTestCase):
    """The Suite roles stop opening Desk, for the roles and for the users who relied on them.

    Flipping the roles alone is not enough on an existing site: users keep the System User
    type they were given while the roles carried Desk access, and their sessions keep it too.
    """

    def setUp(self) -> None:
        # Frappe commits as it deletes a session; keep that inside the test's transaction.
        self.enterContext(patch.object(frappe.db, "commit"))
        # The state the patch upgrades from. Users created now resolve to System Users.
        for role in SUITE_ROLES:
            frappe.db.set_value("Role", role, "desk_access", 1)

    def test_suite_roles_lose_desk_access(self) -> None:
        execute()

        for role in SUITE_ROLES:
            self.assertEqual(frappe.db.get_value("Role", role, "desk_access"), 0)

    def test_user_with_only_suite_roles_becomes_a_website_user(self) -> None:
        member = make_user()
        admin = make_user("Suite Admin")
        self.assertEqual(user_type(member), "System User")
        self.assertEqual(user_type(admin), "System User")

        execute()

        self.assertEqual(user_type(member), "Website User")
        self.assertEqual(user_type(admin), "Website User")

    def test_user_with_another_desk_role_stays_a_system_user(self) -> None:
        system_manager = make_user("System Manager")
        start_session(system_manager)

        execute()

        self.assertEqual(user_type(system_manager), "System User")
        self.assertTrue(has_session(system_manager))

    def test_demoted_user_is_logged_out(self) -> None:
        member = make_user()
        start_session(member)

        execute()

        self.assertFalse(has_session(member))

    def test_administrator_stays_a_system_user(self) -> None:
        execute()

        self.assertEqual(user_type("Administrator"), "System User")

    def test_running_twice_changes_nothing_more(self) -> None:
        member = make_user()
        execute()
        start_session(member)

        execute()

        self.assertEqual(user_type(member), "Website User")
        self.assertTrue(has_session(member))
