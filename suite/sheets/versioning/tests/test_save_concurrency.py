from __future__ import annotations

from threading import Barrier, Thread
from unittest import mock
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase

from suite.sheets.versioning import save as save_mod


class ConcurrentSaveRetryTest(IntegrationTestCase):
    def setUp(self):
        token = uuid4().hex
        self.sheet = f"test-sheet-{token}"
        self.request_id = f"test-request-{token}"
        self.site = frappe.local.site
        self.sites_path = frappe.local.sites_path
        frappe.get_doc(
            {
                "doctype": "Sheet",
                "name": self.sheet,
                "title": "Concurrent Retry",
                "sheets_data": "{}",
                "head_seq": 0,
            }
        ).db_insert()
        frappe.get_doc(
            {
                "doctype": "Sheet Seq",
                "sheet": self.sheet,
                "next_seq": 1,
            }
        ).db_insert()
        frappe.db.commit()

    def tearDown(self):
        frappe.db.delete("Sheet Snapshot", {"sheet": self.sheet})
        frappe.db.delete("Sheet Op Log", {"sheet": self.sheet})
        frappe.db.delete("Sheet Seq", {"name": self.sheet})
        frappe.db.delete("Sheet", {"name": self.sheet})
        frappe.db.commit()

    def test_concurrent_retry_returns_the_committed_result(self):
        precheck = Barrier(2)
        results = []
        errors = []
        validate_payload = save_mod._validate_payload

        def synchronized_validation(payload):
            precheck.wait(timeout=5)
            return validate_payload(payload)

        def save():
            results.append(
                save_mod.save_sheet(
                    "Concurrent Retry",
                    "{}",
                    name=self.sheet,
                    ops=[{"op_type": "edit", "summary": "Retried edit"}],
                    request_id=self.request_id,
                )
            )

        with (
            mock.patch.object(save_mod, "_validate_payload", side_effect=synchronized_validation),
            mock.patch.object(save_mod.snapshots_mod, "maybe_snapshot"),
        ):
            self._run_workers(save, save, errors=errors)

        self.assertEqual(errors, [])
        self.assertEqual(results, [{"name": self.sheet, "head_seq": 2}] * 2)
        self.assertEqual(frappe.db.count("Sheet Op Log", {"request_id": self.request_id}), 1)
        self.assertEqual(frappe.db.count("Sheet Op Log", {"sheet": self.sheet, "op_type": "edit"}), 1)
        self.assertEqual(frappe.db.get_value("Sheet Seq", self.sheet, "next_seq"), 3)

    def _run_workers(self, *workers, errors):
        def run(worker):
            frappe.init(site=self.site, sites_path=self.sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                worker()
                frappe.db.commit()
            except Exception as exc:
                frappe.db.rollback()
                errors.append(exc)
            finally:
                frappe.destroy()

        threads = [Thread(target=run, args=(worker,)) for worker in workers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertFalse(any(thread.is_alive() for thread in threads), "Database workers deadlocked")
