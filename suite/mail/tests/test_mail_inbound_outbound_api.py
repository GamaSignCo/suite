# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import io
from contextlib import contextmanager

import frappe

from suite.mail.api.auth import validate as auth_validate
from suite.mail.api.inbound import fetch_blob, pull, pull_raw
from suite.mail.api.outbound import send, send_raw, upload_attachment
from suite.mail.tests.base import StalwartIntegrationTestCase, unique_name


@contextmanager
def fake_request(files: dict | None = None):
    """The inbound/outbound endpoints are written for HTTP callers (they read frappe.request),
    so direct calls need a request in place."""

    from werkzeug.test import EnvironBuilder
    from werkzeug.wrappers import Request

    builder = EnvironBuilder(
        path="/api/method/test",
        method="POST",
        data=files or {},
        headers={"X-Site": "test-client.example.test"},  # the sync-history source
    )
    previous = getattr(frappe.local, "request", None)
    previous_ip = getattr(frappe.local, "request_ip", None)
    frappe.local.request = Request(builder.get_environ())
    frappe.local.request_ip = "127.0.0.1"  # the ip-based rate limiter requires an identity
    try:
        yield
    finally:
        frappe.local.request_ip = previous_ip
        if previous is None:
            delattr(frappe.local, "request")
        else:
            frappe.local.request = previous


class TestMailInboundOutboundAPI(StalwartIntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = cls.create_member()  # the "Frappe Mail client" user
        cls.peer = cls.create_member()
        cls.disable_screening(cls.client)
        cls.disable_screening(cls.peer)
        cls.account = cls.personal_account(cls.client)

    def test_auth_validate(self):
        with self.set_user(self.client.email):
            auth_validate(self.client.email)  # own address passes
            self.assertRaises(frappe.PermissionError, auth_validate, self.peer.email)

        # A user without JMAP settings is rejected outright.
        self.assertRaises(frappe.ValidationError, auth_validate, self.client.email)

    def test_inbound_pull(self):
        first = self.deliver_mail(self.peer, self.client, subject=f"Pull 1 {unique_name('subject')}")
        second = self.deliver_mail(self.peer, self.client, subject=f"Pull 2 {unique_name('subject')}")

        with self.set_user(self.client.email), fake_request():
            result = pull(limit=10)
            subjects = [m["subject"] for m in result["mails"]]
            self.assertIn(first["subject"], subjects)
            self.assertIn(second["subject"], subjects)
            self.assertEqual(subjects, sorted(subjects, key=lambda s: subjects.index(s)))  # ascending order
            self.assertTrue(result["last_received_at"])

            # The sync history advanced: an incremental pull returns nothing new.
            self.assertEqual(pull(limit=10, last_received_at=result["last_received_at"])["mails"], [])
            self.assertTrue(frappe.db.exists("Mail Sync History", {"account": self.account}))

            # The first pull advanced the shared sync history, so rewind explicitly for raw.
            raw = pull_raw(limit=10, last_received_at="2000-01-01T00:00:00Z")
            self.assertTrue(any(first["subject"] in m for m in raw["mails"]))

            # The sync limit is enforced.
            self.assertRaises(frappe.ValidationError, pull, limit=10_000_000)

    def test_fetch_blob(self):
        content = b"blob payload %s" % unique_name("blob").encode()
        file = frappe.get_doc(
            {"doctype": "File", "file_name": "blob.txt", "content": content, "is_private": 1}
        ).insert(ignore_permissions=True)

        subject = f"Blob {unique_name('subject')}"
        with self.set_user(self.peer.email):
            from suite.mail.api.mail import create_mail

            result = create_mail(
                account=self.personal_account(self.peer),
                from_email=self.peer.email,
                to=[{"email": self.client.email}],
                cc=[],
                bcc=[],
                subject=subject,
                html_body="<p>blob</p>",
                attachments=[
                    {
                        "file_url": file.file_url,
                        "file_name": "blob.txt",
                        "type": "text/plain",
                        "size": len(content),
                        "disposition": "attachment",
                    }
                ],
            )
        self.assertEqual(result["status"], "Submitted", result.get("error"))

        thread = self.wait_until(
            lambda: next((t for t in self.get_inbox_threads(self.client) if t["subject"] == subject), None),
            timeout=60,
            message="Blob mail did not arrive.",
        )
        blob_id = thread["messages"][-1]["attachments"][0]["blob_id"]

        with self.set_user(self.client.email), fake_request():
            self.assertEqual(bytes(fetch_blob(blob_id, as_bytes=True)), content)
            import base64

            self.assertEqual(base64.b64decode(fetch_blob(blob_id)), content)

    def test_outbound_send(self):
        subject = f"API send {unique_name('subject')}"
        with self.set_user(self.client.email), fake_request():
            queue_name = send(
                from_=f"Client <{self.client.email}>",
                subject=subject,
                to=self.peer.email,
                html="<p>via outbound API</p>",
            )

            # Enqueue mode: the queue doc waits for the worker - process it inline.
            doc = frappe.get_doc("Mail Queue", queue_name)
            self.assertNotEqual(doc.status, "Submitted")
            doc._process()
            self.assertEqual(frappe.get_doc("Mail Queue", queue_name).status, "Submitted")

        self.wait_until(
            lambda: subject in [t["subject"] for t in self.get_inbox_threads(self.peer)],
            timeout=60,
            message="Outbound API mail did not arrive.",
        )

    def test_outbound_send_raw(self):
        subject = f"API raw {unique_name('subject')}"
        raw_message = (
            f"From: {self.client.email}\r\nTo: {self.peer.email}\r\nSubject: {subject}\r\n\r\nRaw body.\r\n"
        )
        with self.set_user(self.client.email), fake_request():
            queue_name = send_raw(from_=self.client.email, to=self.peer.email, raw_message=raw_message)
            frappe.get_doc("Mail Queue", queue_name)._process()

        self.wait_until(
            lambda: subject in [t["subject"] for t in self.get_inbox_threads(self.peer)],
            timeout=60,
            message="Raw outbound mail did not arrive.",
        )

        # Oversize messages are rejected up front.
        with self.mail_settings(max_message_payload_size_mb=1):
            with self.set_user(self.client.email), fake_request():
                self.assertRaisesRegex(
                    frappe.ValidationError,
                    "maximum allowed size",
                    send_raw,
                    from_=self.client.email,
                    to=self.peer.email,
                    raw_message=raw_message + "x" * (2 * 1024 * 1024),
                )

    def test_upload_attachment(self):
        with self.set_user(self.client.email):
            with fake_request(files={"file": (io.BytesIO(b"upload payload"), "upload.txt")}):
                result = upload_attachment()
        self.assertEqual(result["file_name"], "upload.txt")
        self.assertTrue(result["file_url"])
        self.assertEqual(
            frappe.db.get_value("File", {"file_url": result["file_url"]}, "folder"), "Home/Frappe Mail"
        )
