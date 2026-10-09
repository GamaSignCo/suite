import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import frappe

from suite.drive.api.files import toggle_entity_status
from suite.drive.utils.files import FileManager


class TestTrashSafety(unittest.TestCase):
    def test_document_permission_failure_does_not_move_a_blob(self):
        doc = Mock(name="file-id")
        doc.check_permission.side_effect = frappe.PermissionError
        manager = Mock()
        with (
            patch("suite.drive.api.files.user_has_permission", return_value=True),
            patch.object(frappe.db, "get_value"),
            self.assertRaises(frappe.PermissionError),
        ):
            toggle_entity_status(doc, manager, set())
        manager.move_to_trash.assert_not_called()
        manager.restore.assert_not_called()

    def test_existing_trash_copy_is_never_overwritten(self):
        with TemporaryDirectory() as directory:
            manager = object.__new__(FileManager)
            manager.site_folder = Path(directory)
            manager.s3_enabled = False
            manager.flat = False
            entity = frappe._dict(name="file-id", file_url="private/files/source", mime_type="Folder")
            source = manager.site_folder / entity.file_url
            previous = manager.site_folder / "private/files/.trash/file-id"
            source.mkdir(parents=True)
            previous.mkdir(parents=True)
            (source / "current.txt").write_bytes(b"current data")
            (previous / "previous.txt").write_bytes(b"previous data")
            with (
                patch("suite.drive.utils.files.get_root_folder", return_value={"file_url": "private/files/"}),
                self.assertRaises(FileExistsError),
            ):
                manager.move_to_trash(entity)
            self.assertEqual((source / "current.txt").read_bytes(), b"current data")
            self.assertEqual((previous / "previous.txt").read_bytes(), b"previous data")
