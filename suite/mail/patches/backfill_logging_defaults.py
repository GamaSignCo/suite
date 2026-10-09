import frappe

DEFAULTS = {"log_level": "INFO", "log_max_file_size_mb": 5, "log_file_count": 10}


def execute() -> None:
    """Fill new required logging fields on sites with an existing Mail Settings singleton."""
    for field, default in DEFAULTS.items():
        if not frappe.db.get_single_value("Mail Settings", field):
            frappe.db.set_single_value("Mail Settings", field, default)
    frappe.clear_document_cache("Mail Settings", "Mail Settings")
