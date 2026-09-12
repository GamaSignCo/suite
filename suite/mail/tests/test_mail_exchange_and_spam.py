# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe

from suite.mail.api.account import (
    create_contacts_export,
    create_mail_export,
    create_mail_import,
)
from suite.mail.api.mail import get_mailboxes
from suite.mail.tests.base import StalwartIntegrationTestCase, unique_name
from suite.mail.utils import get_config


class TestMailExchangeAndSpam(StalwartIntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.member = cls.create_member()
        cls.peer = cls.create_member()
        cls.disable_screening(cls.member)
        cls.account = cls.personal_account(cls.member)

    def test_mail_export(self):
        self.deliver_mail(self.peer, self.member)

        with self.set_user(self.member.email):
            create_mail_export(self.account, "mbox", ".zip", "Received At (ASC)")
            doc = frappe.get_last_doc("Mail Exchange", {"account": self.account, "operation": "Export"})
            # The worker job is enqueued on commit (which tests never do) - run it inline.
            doc._export()
            doc.reload()

        self.assertEqual(doc.status, "Completed", doc.get("error"))
        self.assertTrue(frappe.db.exists("File", {"attached_to_name": doc.name}))

    def test_mail_import(self):
        subject = f"Imported {unique_name('subject')}"
        from email.utils import formatdate

        eml = (
            f"From: someone@elsewhere.example.org\r\n"
            f"To: {self.member.email}\r\n"
            f"Subject: {subject}\r\n"
            f"Date: {formatdate(usegmt=True)}\r\n"  # import requires a valid non-future date
            "\r\n"
            "Imported body.\r\n"
        )
        file = frappe.get_doc(
            {"doctype": "File", "file_name": "import.eml", "content": eml, "is_private": 1}
        ).insert(ignore_permissions=True)

        with self.set_user(self.member.email):
            inbox = {(m["role"] or "").lower(): m["id"] for m in get_mailboxes(self.account)}["inbox"]
            create_mail_import(self.account, "eml", file.file_url, mailbox=inbox, seen=True)
            doc = frappe.get_last_doc("Mail Exchange", {"account": self.account, "operation": "Import"})
            doc._import()
            doc.reload()

        self.assertEqual(doc.status, "Completed", doc.get("error"))
        self.wait_until(
            lambda: subject in [t["subject"] for t in self.get_inbox_threads(self.member)],
            message="Imported mail did not appear in the inbox.",
        )

    def test_contacts_export(self):
        from suite.mail.api.contacts import get_address_books
        from suite.mail.doctype.contact_card.contact_card import add_contact_card

        with self.set_user(self.member.email):
            # An empty account refuses to export ("No contacts found") - create one contact.
            default_book = next(b["id"] for b in get_address_books(self.account) if b["default"])
            add_contact_card(
                self.account,
                [default_book],
                full_name="Export Target",
                emails=[{"address": "export@elsewhere.example.org", "type": "Personal"}],
            )
            create_contacts_export(self.account, "vcf", ".zip")
            doc = frappe.get_last_doc("Contacts Exchange", {"account": self.account, "operation": "Export"})
            doc._export()
            doc.reload()

        self.assertEqual(doc.status, "Completed", doc.get("error"))

    def test_spamd_scan(self):
        from suite.mail.api.spamd import get_spam_score

        if not get_config("spamd_host"):
            self.skipTest("spamd is not configured for this site.")

        with self.set_user(self.member.email):
            score = get_spam_score("Subject: test\r\n\r\nhello")
            self.assertIsInstance(score, float)

    def test_push_notification_endpoint(self):
        from urllib.parse import quote

        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request

        from suite.mail.api.jmap import push_notification

        payload = {"@type": "StateChange", "changed": {self.account: {"Email": "state-1"}}}
        builder = EnvironBuilder(
            path="/api/method/suite.mail.api.jmap.push_notification",
            method="POST",
            query_string={"user": quote(self.member.email)},
            data=json.dumps(payload),
            content_type="application/json",
        )
        previous = getattr(frappe.local, "request", None)
        frappe.local.request = Request(builder.get_environ())
        try:
            result = push_notification()
        finally:
            if previous is None:
                delattr(frappe.local, "request")
            else:
                frappe.local.request = previous

        self.assertIsInstance(result, dict)
        self.assertNotEqual(result.get("status"), "error", result)
