import json
import os
import uuid

import frappe


def create_attachment_with_unique_name(doc):
    file_name = doc.file_name
    file_extension = os.path.splitext(file_name)[1]
    base_name = os.path.splitext(file_name)[0]
    unique_name = f"{base_name}_{uuid.uuid4().hex[:6]}{file_extension}"

    file_content = doc.get_content()
    new_file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": unique_name,
            "file_url": f"/private/files/{unique_name}",
            "attached_to_doctype": doc.attached_to_doctype,
            "attached_to_name": doc.attached_to_name,
            "is_private": 1,
            "content": file_content,
        }
    )

    new_file_doc.insert()

    return new_file_doc.file_url


def move_file_to_private(presentation, file_url):
    attachment = frappe.get_cached_value(
        "File",
        {
            "file_url": file_url,
            "attached_to_doctype": "Presentation",
            "attached_to_name": presentation,
        },
        "name",
    )
    if not attachment:
        return file_url

    file_doc = frappe.get_doc("File", attachment)
    if file_doc.is_private:
        return file_doc.file_url

    try:
        file_doc.is_private = 1
        file_doc.save()
        return file_doc.file_url
    except Exception:
        new_file_url = create_attachment_with_unique_name(file_doc)
        file_doc.delete()
        return new_file_url


def delete_public_attachments(presentation_name):
    public_attachments = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Presentation",
            "attached_to_name": presentation_name,
            "is_private": 0,
        },
        pluck="name",
    )
    for file_name in public_attachments:
        file_doc = frappe.get_doc("File", file_name)
        try:
            file_doc.delete()
        except Exception as e:
            frappe.log_error(f"Error deleting file {file_doc.file_url}: {e!s}")


def get_updated_elements(elements, presentation_name):
    elements = json.loads(elements or "[]")

    updated = False
    for element in elements:
        if element.get("type") in ("image", "video"):
            src = element.get("src", "")
            if not src.startswith("/assets"):
                element["src"] = move_file_to_private(presentation_name, src)
                updated = True

            poster = element.get("poster", "")
            if not poster.startswith("/assets"):
                element["poster"] = move_file_to_private(presentation_name, poster)
                updated = True

    if updated:
        return json.dumps(elements, indent=2)


def execute():
    if not frappe.db.has_column("Presentation", "is_public"):
        # The legacy flag never existed on this site — nothing to move.
        return

    presentations = frappe.get_all("Presentation", filters={"is_public": 1, "is_composite": 0}, pluck="name")

    for presentation_name in presentations:
        presentation = frappe.get_doc("Presentation", presentation_name)

        for slide in presentation.slides or []:
            if slide.thumbnail and slide.thumbnail.startswith("/files"):
                slide.thumbnail = move_file_to_private(presentation.name, slide.thumbnail)

            elements = slide.get("elements", [])
            if isinstance(elements, str):
                updated_elements = get_updated_elements(elements, presentation.name)
                if updated_elements:
                    slide.elements = updated_elements

        presentation.save()

        # can now delete all public attachments not being used in slides
        delete_public_attachments(presentation.name)
