"""Compare observable fork requirements against an unmodified upstream checkout."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from suite.drive.api.storage import get_storage_usage
from suite.drive.utils import apply_file_size_delta, create_drive_file, get_root_folder, get_user_folder
from suite.drive.utils.files import FileManager
from suite.drive.webdav import copy as copy_module
from suite.drive.webdav import put as put_module
from suite.drive.webdav.errors import InsufficientStorage
from suite.drive.webdav.tests.utils import make_ctx, write_file_fixture
from suite.tests.utils import ensure_user

OWNER = "fork-cleanup-audit@example.com"
OBSERVED_UPLOADS = []


def observe_upload(file_name, content_hash):
    row = frappe.get_doc("File", file_name)
    OBSERVED_UPLOADS.append((FileManager().get_local_path(row.file_url).read_bytes(), content_hash))


class TestForkCleanupBehavior(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ensure_user(OWNER)
        user = frappe.get_doc("User", OWNER)
        user.add_roles("Suite User")
        with cls.set_user(OWNER):
            cls.home = get_user_folder(OWNER).name
        frappe.db.commit()

    def setUp(self):
        frappe.set_user(OWNER)
        self.folder = self.make_folder(self.home, "Audit")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def make_folder(self, parent, label):
        return create_drive_file(
            label + "-" + frappe.generate_hash(length=8),
            parent,
            "Folder",
            lambda row: FileManager().create_folder(row),
        )

    def test_normal_user_can_list_owned_files_without_sql_errors(self):
        document = write_file_fixture(self.folder.name, "visible.txt", b"visible")
        rows = frappe.get_list("File", filters={"name": document.name}, pluck="name")
        self.assertEqual(rows, [document.name])

    def test_shared_files_do_not_consume_personal_home_quota(self):
        before = get_storage_usage(OWNER)["total_size"]
        with self.set_user("Administrator"):
            shared = create_drive_file(
                "SharedAudit-" + frappe.generate_hash(length=8),
                get_root_folder().name,
                "Folder",
                lambda row: FileManager().create_folder(row),
                owner=OWNER,
            )
        write_file_fixture(shared.name, "project.txt", b"shared-project-content")
        self.assertEqual(get_storage_usage(OWNER)["total_size"], before)
        write_file_fixture(self.folder.name, "personal.txt", b"home")
        self.assertEqual(get_storage_usage(OWNER)["total_size"], before + 4)

    def test_upload_extension_observes_committed_bytes(self):
        original_hooks = frappe.get_hooks
        OBSERVED_UPLOADS.clear()
        body = b"committed audit bytes"

        def configured_hooks(key=None, *args, **kwargs):
            if key == "after_drive_webdav_upload":
                return [__name__ + ".observe_upload"]
            return original_hooks(key, *args, **kwargs)

        with patch.object(frappe, "get_hooks", side_effect=configured_hooks):
            response = put_module.handle(
                make_ctx(
                    "PUT",
                    f"/dav/Home/{self.folder.file_name}/observed.txt",
                    OWNER,
                    data=body,
                    content_type="application/octet-stream",
                )
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(OBSERVED_UPLOADS, [])
            frappe.db.commit()
        self.assertEqual(OBSERVED_UPLOADS, [(body, hashlib.sha256(body).hexdigest())])

    def test_recursive_copy_honors_the_configured_item_budget(self):
        write_file_fixture(self.folder.name, "member.txt", b"member")
        with patch.dict(frappe.local.conf, {"drive_webdav_max_copy_items": 1}):
            with self.assertRaises(InsufficientStorage):
                copy_module.handle(
                    make_ctx(
                        "COPY",
                        f"/dav/Home/{self.folder.file_name}",
                        OWNER,
                        headers={"Destination": "/dav/Home/AuditBudgetCopy"},
                    )
                )

    def test_existing_trash_bytes_are_preserved_on_a_second_removal(self):
        with TemporaryDirectory() as directory:
            manager = object.__new__(FileManager)
            manager.site_folder = Path(directory)
            manager.s3_enabled = False
            manager.flat = False
            entity = frappe._dict(name="audit-trash", file_url="private/files/source", mime_type="Folder")
            source = manager.site_folder / entity.file_url
            previous = manager.site_folder / "private/files/.trash/audit-trash"
            source.mkdir(parents=True)
            previous.mkdir(parents=True)
            (source / "current.txt").write_bytes(b"current")
            (previous / "previous.txt").write_bytes(b"previous")
            with patch(
                "suite.drive.utils.files.get_root_folder", return_value={"file_url": "private/files/"}
            ):
                with self.assertRaises(FileExistsError):
                    manager.move_to_trash(entity)
            self.assertEqual((source / "current.txt").read_bytes(), b"current")
            self.assertEqual((previous / "previous.txt").read_bytes(), b"previous")

    def test_size_delta_uses_current_ancestry_without_strict_snapshot_checks(self):
        self.assert_size_delta_after_reparent(strict_snapshot=False)

    def test_strict_snapshot_conflict_never_commits_partial_rollups(self):
        self.assert_size_delta_after_reparent(strict_snapshot=True)

    def assert_size_delta_after_reparent(self, *, strict_snapshot):
        old_parent = self.make_folder(self.home, "OldParent")
        new_parent = self.make_folder(self.home, "NewParent")
        child = self.make_folder(old_parent.name, "MovingChild")
        frappe.db.commit()
        site, sites_path = frappe.local.site, frappe.local.sites_path
        snapshot_ready, moved = Event(), Event()
        errors = []

        def update_from_older_snapshot():
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            frappe.set_user(OWNER)
            try:
                # MariaDB 11.8 defaults to strict checks; older supported versions did not.
                frappe.db.sql("SET SESSION innodb_snapshot_isolation=%s", (int(strict_snapshot),))
                frappe.db.sql("START TRANSACTION WITH CONSISTENT SNAPSHOT")
                frappe.db.sql("SELECT folder FROM tabFile WHERE name=%s", (child.name,))
                snapshot_ready.set()
                if not moved.wait(10):
                    raise TimeoutError("The concurrent relocation did not finish")
                apply_file_size_delta(child.name, 7)
                frappe.db.commit()
            except Exception as error:
                frappe.db.rollback()
                errors.append(error)
            finally:
                frappe.destroy()

        worker = Thread(target=update_from_older_snapshot)
        worker.start()
        try:
            self.assertTrue(snapshot_ready.wait(10), "The older transaction did not start")
            frappe.db.set_value("File", child.name, "folder", new_parent.name, update_modified=False)
            frappe.db.commit()
        finally:
            moved.set()
            worker.join(15)
        self.assertFalse(worker.is_alive(), "The size update deadlocked")
        if errors and strict_snapshot:
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], frappe.QueryDeadlockError)
            for folder in [old_parent, new_parent, child]:
                self.assertEqual(frappe.db.get_value("File", folder.name, "file_size"), 0)
            return
        self.assertEqual(errors, [])
        self.assertEqual(frappe.db.get_value("File", new_parent.name, "file_size"), 7)
        self.assertEqual(frappe.db.get_value("File", old_parent.name, "file_size"), 0)
