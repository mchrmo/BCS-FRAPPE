# apps/bcservices/bcservices/api/chat.py

import frappe
from frappe.utils import now_datetime


def _get_client_name_by_clerk_id(clerk_id: str) -> str:
    if not clerk_id:
        frappe.throw("Missing clerk_id")

    name = frappe.db.get_value(
        "Klient",   # ⬅️ PRESNE PODĽA SCREENSHOTU
        {"clerk_id": clerk_id},
        "name"
    )

    if not name:
        frappe.throw(f"Unknown clerk_id: {clerk_id}")

    return name


def _sanitize_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        frappe.throw("Empty message")
    if len(text) > 5000:
        frappe.throw("Message too long")
    return text


@frappe.whitelist(methods=["POST"], allow_guest=True)
def save_message(from_clerk=None, to_clerk=None, content=None, room_id=None):
    # ⚠️ LEN NA TEST
    frappe.set_user("Administrator")

    sender = _get_client_name_by_clerk_id(from_clerk)
    recipient = _get_client_name_by_clerk_id(to_clerk)
    content = _sanitize_text(content)

    doc = frappe.get_doc({
        "doctype": "Sprava chatu",
        "odosielatel": sender,
        "prijemca": recipient,
        "obsah": content,
        "datum_cas": now_datetime(),
    })

    if room_id and doc.meta.has_field("room_id"):
        doc.room_id = room_id

    doc.insert()

    return {
        "success": True,
        "message_id": doc.name,
        "timestamp": doc.datum_cas,
    }
