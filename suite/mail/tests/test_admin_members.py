# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import secrets
from unittest.mock import patch

import frappe

from suite.mail.api.account import (
    create_account,
    get_account_request,
    get_account_setup_options,
    resend_otp,
    signup,
    validate_email_assigned,
    verify_otp,
)
from suite.mail.api.admin import (
    add_member,
    delete_account_requests,
    get_account_requests,
    get_member,
    get_members,
)
from suite.mail.doctype.user_account.user_account import get_user_personal_jmap_account
from suite.mail.tests.base import StalwartIntegrationTestCase, _delete_stalwart_account, unique_name


class TestAdminMembers(StalwartIntegrationTestCase):
    def test_force_create_admin_member(self):
        admin = self.create_member(is_admin=True)

        self.assertTrue(frappe.db.exists("User", admin.email))
        self.assertIn("Suite Admin", frappe.get_roles(admin.email))

        rows = get_members(search=admin.email)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_admin"])
        self.assertTrue(rows[0]["enabled"])

        # The full provisioning chain: Stalwart principal, app password, JMAP account links.
        self.assertTrue(get_user_personal_jmap_account(admin.email))
        self.assertTrue(self.get_app_password(admin.email))

    def test_force_create_member_provisions_working_account(self):
        member = self.create_member()

        self.assertNotIn("Suite Admin", frappe.get_roles(member.email))

        settings = frappe.get_doc("User Settings", {"user": member.email})
        self.assertEqual(settings.username, member.email)

        # The app password opens a live JMAP session - the same credentials the mail UI runs on.
        self.assertTrue(self.stalwart_auth_ok(member.email, self.get_app_password(member.email)))

        detail = get_member(member.email)
        self.assertTrue(detail["enabled"])
        self.assertFalse(detail["is_admin"])
        primary = [e for e in detail["email_addresses"] if e["is_primary"]]
        self.assertEqual(len(primary), 1)
        self.assertEqual(primary[0]["email"], member.email)
        self.assertIn("unlimited", detail["quota"])

    def test_invite_flow(self):
        username = unique_name("user")
        email = f"{username}@{self.domain}"
        password = f"Tst@{secrets.token_hex(8)}"
        add_member(
            username=username,
            domain=self.domain,
            is_admin=False,
            send_invite=True,
            backup_email=f"{username}@backup.example.test",
        )
        self._stalwart_cleanups.append(lambda email=email: _delete_stalwart_account(email))

        request = frappe.get_last_doc("Mail Account Request", {"account": email})
        self.assertFalse(request.is_verified)
        self.assertTrue(request.request_key)
        # Admin-created requests record the inviter, unlike self-signups.
        self.assertTrue(request.invited_by)

        with self.set_user("Guest"):
            details = get_account_request(request.request_key)
            self.assertEqual(details["account"], email)
            self.assertFalse(details["is_verified"])
            self.assertFalse(details["is_expired"])

            options = get_account_setup_options(request.request_key)
            self.assertIsInstance(options, dict)
            self.assertTrue(options)

            create_account(request.request_key, "Invited", "Member", password)

        self.assertTrue(frappe.db.exists("User", email))
        self.assertTrue(self.stalwart_auth_ok(email, self.get_app_password(email)))

        # Completing the same request again must not create anything twice.
        with self.set_user("Guest"):
            self.assertRaises(Exception, create_account, request.request_key, "Invited", "Member", password)

        accepted = get_account_requests(search=email, status="Accepted")
        self.assertEqual([r["account"] for r in accepted], [email])

        delete_account_requests([request.name])
        self.assertFalse(frappe.db.exists("Mail Account Request", request.name))

    def test_otp_signup_flow(self):
        from suite.mail.doctype.mail_account_request.mail_account_request import MailAccountRequest

        username = unique_name("user")
        email = f"{username}@{self.domain}"
        password = f"Tst@{secrets.token_hex(8)}"

        # The code only travels by email, so read it off the document instance before
        # send_verification_email consumes it.
        captured = {}
        original_send = MailAccountRequest.send_verification_email

        def capture_otp(doc):
            captured["otp"] = doc._signup_otp
            return original_send(doc)

        with self.mail_settings(allow_signup=1, signup_domains=self.domain):
            with (
                self.set_user("Guest"),
                patch.object(MailAccountRequest, "send_verification_email", capture_otp),
            ):
                request_name = signup(
                    username=username, domain=self.domain, email=f"{username}@backup.example.test"
                )
            self.assertTrue(captured["otp"])

            # Signup must not provision anything before the email is verified.
            request = frappe.get_doc("Mail Account Request", request_name)
            self.assertFalse(request.is_verified)
            self.assertFalse(frappe.db.exists("User", email))
            # An empty invited_by is what marks a self-signup request.
            self.assertFalse(request.invited_by)

            # resend_otp regenerates the code, invalidating the previous one.
            first_otp = captured["otp"]
            with (
                self.set_user("Guest"),
                patch.object(MailAccountRequest, "send_verification_email", capture_otp),
            ):
                resend_otp(request_name)
            self.assertTrue(captured["otp"])
            if first_otp != captured["otp"]:
                with self.set_user("Guest"):
                    self.assertRaisesRegex(
                        frappe.ValidationError, "Invalid OTP", verify_otp, request_name, first_otp
                    )

            wrong = "000000" if captured["otp"] != "000000" else "111111"
            with self.set_user("Guest"):
                self.assertRaisesRegex(frappe.ValidationError, "Invalid OTP", verify_otp, request_name, wrong)
                request_key = verify_otp(request_name, captured["otp"])
                self.assertEqual(request_key, request.request_key)
                # The OTP is single-use.
                self.assertRaisesRegex(
                    frappe.ValidationError, "Invalid OTP", verify_otp, request_name, captured["otp"]
                )

                # Only now, with the released request key, is the account created.
                create_account(request_key, "Signup", "Member", password)
            self._stalwart_cleanups.append(lambda email=email: _delete_stalwart_account(email))

            self.assertTrue(frappe.db.exists("User", email))
            self.assertTrue(self.stalwart_auth_ok(email, self.get_app_password(email)))

        # Signup is rejected when disabled or for a domain outside the allow-list.
        with self.set_user("Guest"):
            self.assertRaisesRegex(
                frappe.ValidationError,
                "disabled|not allowed",
                signup,
                username=unique_name("user"),
                domain=self.domain,
                email="someone@backup.example.test",
            )

    def test_add_member_negatives(self):
        member = self.create_member()

        # An address that already belongs to a User is reported as taken.
        self.assertRaisesRegex(frappe.ValidationError, "already taken", validate_email_assigned, member.email)
        validate_email_assigned(f"{unique_name('free')}@{self.domain}")  # free address passes

        # Duplicate primary address.
        self.assertRaises(
            Exception,
            add_member,
            username=member.username,
            domain=member.domain,
            is_admin=False,
            send_invite=False,
            backup_email="dup@backup.example.test",
            first_name="Dup",
            password=f"Tst@{secrets.token_hex(8)}",
        )

        # Domain that does not exist on the server.
        self.assertRaises(
            Exception,
            add_member,
            username=unique_name("user"),
            domain=f"{unique_name('missing')}.example.test",
            is_admin=False,
            send_invite=False,
            backup_email="missing@backup.example.test",
            first_name="Missing",
            password=f"Tst@{secrets.token_hex(8)}",
        )

        # A plain member cannot invite others (gated by Mail Account Request permissions).
        with self.set_user(member.email):
            self.assertRaises(
                frappe.PermissionError,
                add_member,
                username=unique_name("user"),
                domain=self.domain,
                is_admin=False,
                send_invite=True,
                backup_email="nope@backup.example.test",
            )
            self.assertRaises(frappe.PermissionError, get_members)
            self.assertRaises(frappe.PermissionError, get_account_requests)
