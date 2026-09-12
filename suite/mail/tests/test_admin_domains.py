# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import csv
import io
import json

import frappe

from suite.mail.api.admin import (
    add_domain,
    delete_domain,
    get_domain,
    get_domain_dns_csv,
    get_domain_dns_json,
    get_domain_dns_zone,
    get_domains,
    get_enabled_domains,
)
from suite.mail.stalwart import resolve_domain_id
from suite.mail.tests.base import StalwartIntegrationTestCase


class TestAdminDomains(StalwartIntegrationTestCase):
    def test_add_and_get_domain(self):
        rows = get_domains(txt=self.domain)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["name"], self.domain)
        self.assertTrue(row["is_enabled"])
        self.assertTrue(row["id"])

        detail = get_domain(row["id"])
        self.assertEqual(detail["name"], self.domain)
        self.assertTrue(detail["dns_records"])
        categories = {record["category"] for record in detail["dns_records"]}
        self.assertIn("Receiving", categories)  # MX
        self.assertIn("DMARC", categories)
        for record in detail["dns_records"]:
            self.assertTrue(record["ttl"])

    def test_add_duplicate_domain_fails(self):
        self.assertRaisesRegex(frappe.ValidationError, "already exists", add_domain, self.domain.upper())

    def test_dns_zone_exports(self):
        domain_id = resolve_domain_id(self.domain)

        zone = get_domain_dns_zone(domain_id)
        self.assertIn(self.domain, zone)

        rows = list(csv.DictReader(io.StringIO(get_domain_dns_csv(domain_id))))
        self.assertTrue(rows)
        self.assertEqual(set(rows[0].keys()), {"name", "ttl", "class", "type", "value"})

        records = json.loads(get_domain_dns_json(domain_id))
        self.assertIsInstance(records, list)
        self.assertTrue(records)

    def test_get_enabled_domains(self):
        self.assertIn(self.domain, get_enabled_domains())

    def test_delete_domain(self):
        throwaway = self.create_domain()
        domain_id = resolve_domain_id(throwaway)

        delete_domain(domain_id)

        self.assertEqual(get_domains(txt=throwaway), [])
        self.assertNotIn(throwaway, get_enabled_domains())

    def test_non_admin_cannot_manage_domains(self):
        member = self.create_member()

        with self.set_user(member.email):
            self.assertRaises(frappe.PermissionError, get_domains)
            self.assertRaises(frappe.PermissionError, add_domain, f"x-{self.domain}")
            self.assertRaises(frappe.PermissionError, delete_domain, "any-id")
