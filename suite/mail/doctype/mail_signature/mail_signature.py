# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

from suite.utils.permissions import OwnerFromUser


class MailSignature(OwnerFromUser, Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        html_body: DF.Code | None
        signature_name: DF.Data
        user: DF.Link
    # end: auto-generated types

    pass
