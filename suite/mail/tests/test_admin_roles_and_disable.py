# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import secrets

import frappe

from suite.mail.api.account import get_user_for_reset_password_key, send_reset_password_link
from suite.mail.api.admin import (
    add_member_email,
    change_member_password,
    delete_members,
    disable_members,
    enable_members,
    get_member,
    get_permissions,
    get_role,
    get_roles_list,
    remove_member_email,
    set_member_email_enabled,
    update_member,
    update_role,
)
from suite.mail.api.admin import delete_roles as delete_admin_roles
from suite.mail.doctype.user_account.user_account import get_user_personal_jmap_account
from suite.mail.tests.base import StalwartIntegrationTestCase, unique_name


class TestAdminRolesAndDisable(StalwartIntegrationTestCase):
    def test_role_crud(self):
        permissions = get_permissions()
        self.assertTrue(permissions)
        self.assertIn("authenticate", [p["value"] for p in permissions])

        description = f"Test role {unique_name('role')}"
        role_id = self.create_role(description=description, disabled_permissions=["authenticate"])

        rows = get_roles_list(search=description)
        self.assertEqual([r["id"] for r in rows], [role_id])
        self.assertEqual(rows[0]["disabled_count"], 1)

        detail = get_role(role_id)
        self.assertEqual(detail["description"], description)
        self.assertEqual(detail["disabled_permissions"], ["authenticate"])

        update_role(
            role_id, description=f"{description} v2", disabled_permissions=["authenticate", "emailSend"]
        )
        detail = get_role(role_id)
        self.assertEqual(detail["description"], f"{description} v2")
        self.assertEqual(sorted(detail["disabled_permissions"]), ["authenticate", "emailSend"])

        throwaway = self.create_role()
        delete_admin_roles([throwaway])
        self.assertEqual([r for r in get_roles_list() if r["id"] == throwaway], [])

    def test_disable_and_enable_member(self):
        # The "Disabled" role denies sign-in on the server, exactly as the dashboard configures it.
        role_description = f"Disabled {unique_name('role')}"
        self.create_role(description=role_description, disabled_permissions=["authenticate"])

        member = self.create_member()
        app_password = self.get_app_password(member.email)
        self.assertTrue(self.stalwart_auth_ok(member.email, app_password))

        with self.mail_settings(disabled_account_role=role_description):
            disable_members([member.email])

            self.assertFalse(frappe.db.get_value("User", member.email, "enabled"))
            self.assertFalse(get_member(member.email)["enabled"])
            # The role revokes `authenticate`, so even the app password stops working.
            self.wait_until(
                lambda: not self.stalwart_auth_ok(member.email, app_password),
                message="Disabled member can still authenticate on Stalwart.",
            )

            enable_members([member.email])

            self.assertTrue(frappe.db.get_value("User", member.email, "enabled"))
            self.wait_until(
                lambda: self.stalwart_auth_ok(member.email, app_password),
                message="Re-enabled member cannot authenticate on Stalwart.",
            )

    def test_change_member_password(self):
        member = self.create_member()
        new_password = f"Tst@{secrets.token_hex(8)}"

        change_member_password(member.email, new_password)

        # The change propagates to the member's Stalwart account password.
        self.assertTrue(self.stalwart_auth_ok(member.email, new_password))
        self.assertFalse(self.stalwart_auth_ok(member.email, member.password))

        # The guard that keeps member management away from standard users.
        self.assertRaises(frappe.PermissionError, change_member_password, "Administrator", new_password)

    def test_member_email_aliases(self):
        member = self.create_member()
        sender = self.create_member()
        other_domain = self.create_domain()
        self.disable_screening(member)

        # A cross-domain alias, like the dashboard's "Add email address" flow.
        alias = f"{unique_name('alias')}@{other_domain}"
        add_member_email(member.email, alias, description="Alias identity")

        addresses = {e["email"]: e for e in get_member(member.email)["email_addresses"]}
        self.assertIn(alias, addresses)
        self.assertFalse(addresses[alias]["is_primary"])
        self.assertTrue(addresses[alias]["enabled"])

        # Mail sent to the alias lands in the member's inbox.
        subject = f"Alias delivery {unique_name('subject')}"
        result = self.send_mail(sender, alias, subject=subject)
        self.assertEqual(result["status"], "Submitted", result.get("error"))
        self.wait_until(
            lambda: any(subject in str(thread) for thread in self.get_inbox_threads(member)),
            timeout=60,
            message=f"Mail to alias {alias} did not reach {member.email}'s inbox.",
        )

        set_member_email_enabled(member.email, alias, 0)
        addresses = {e["email"]: e for e in get_member(member.email)["email_addresses"]}
        self.assertFalse(addresses[alias]["enabled"])

        remove_member_email(member.email, alias)
        self.assertNotIn(alias, [e["email"] for e in get_member(member.email)["email_addresses"]])

    def test_update_member(self):
        member = self.create_member()

        update_member(member.email, description="Updated Name", quota_gb=2, time_zone="Asia/Kolkata")

        detail = get_member(member.email)
        self.assertEqual(detail["full_name"], "Updated Name")
        self.assertEqual(detail["quota"]["total"], 2 * 1024**3)
        self.assertEqual(detail["time_zone"], "Asia/Kolkata")

        update_member(member.email, role="admin")
        self.assertIn("Suite Admin", frappe.get_roles(member.email))
        self.assertTrue(get_member(member.email)["is_admin"])

        update_member(member.email, role="member")
        self.assertNotIn("Suite Admin", frappe.get_roles(member.email))

    def test_delete_member(self):
        member = self.create_member()
        self.assertTrue(get_user_personal_jmap_account(member.email))

        delete_members([member.email])

        self.assertFalse(frappe.db.exists("User", member.email))
        self.assertFalse(frappe.db.exists("User Settings", {"user": member.email}))
        self.assertFalse(frappe.db.exists("User Account", {"user": member.email}))
        # The Stalwart principal is gone too: its credentials no longer authenticate.
        self.assertFalse(self.stalwart_auth_ok(member.email, member.password))

        # Self-deletion and standard users are rejected.
        self.assertRaisesRegex(frappe.ValidationError, "cannot delete", delete_members, [frappe.session.user])
        self.assertRaises(frappe.PermissionError, delete_members, ["Guest"])

    def test_reset_password_link(self):
        from suite.mail.api.account import set_reset_password_key

        member = self.create_member()

        censored = send_reset_password_link(member.email)
        self.assertIn("*", censored)  # backup email comes back censored

        key = set_reset_password_key(member.email)
        self.assertEqual(get_user_for_reset_password_key(key), member.email)

    def test_update_password_via_reset_key(self):
        from suite.mail.api.account import set_reset_password_key
        from suite.mail.events import update_password

        member = self.create_member()
        key = set_reset_password_key(member.email)
        new_password = f"Tst@{secrets.token_hex(8)}"

        # The whitelisted override propagates the reset to the Stalwart account. Frappe's core
        # update_password logs the user in afterwards, which needs a session login_manager
        # that the test context does not have - stub it.
        from unittest.mock import MagicMock, patch

        with self.set_user("Guest"), patch.object(frappe.local, "login_manager", MagicMock(), create=True):
            update_password(new_password=new_password, key=key)

        self.assertTrue(self.stalwart_auth_ok(member.email, new_password))
        self.assertFalse(self.stalwart_auth_ok(member.email, member.password))

    def test_non_admin_cannot_manage_roles(self):
        member = self.create_member()
        with self.set_user(member.email):
            self.assertRaises(frappe.PermissionError, get_roles_list)
            self.assertRaises(frappe.PermissionError, get_permissions)
            self.assertRaises(frappe.PermissionError, disable_members, ["someone@example.test"])
            self.assertRaises(frappe.PermissionError, delete_members, ["someone@example.test"])
