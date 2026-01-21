# apps/bcservices/bcservices/api/chat.py

import frappe
from frappe.utils import now_datetime

def _require_internal_token():
    token = frappe.get_request_header("X-Chat-Token")
    expected = frappe.conf.get("chat_internal_token")

    if not token or not expected or token != expected:
        frappe.throw("Unauthorized", frappe.PermissionError)


def _get_client_by_clerk_id(clerk_id: str) -> str:
    name = frappe.db.get_value("Klient", {"clerk_id": clerk_id}, "name")
    if not name:
        frappe.throw(f"Unknown clerk_id: {clerk_id}")
    return name


@frappe.whitelist(methods=["POST"])
def save_message():
    """
    Volá IBA signaling server.
    Header:
      X-Chat-Token: <secret>

    Body:
    {
      "from": "<clerk_id>",
      "to": "<clerk_id>",
      "content": "...",
      "room_id": "optional"
    }
    """
    _require_internal_token()

    data = frappe.local.form_dict

    from_clerk = data.get("from")
    to_clerk = data.get("to")
    content = data.get("content")

    if not from_clerk or not to_clerk or not content:
        frappe.throw("Missing required fields")

    sender = _get_client_by_clerk_id(from_clerk)
    recipient = _get_client_by_clerk_id(to_clerk)

    doc = frappe.get_doc({
        "doctype": "Sprava chatu",
        "odosielatel": sender,
        "prijemca": recipient,
        "obsah": content,
        "datum_cas": now_datetime(),
    })

    doc.insert(ignore_permissions=True)

    return {
        "success": True,
        "message_id": doc.name,
        "timestamp": doc.datum_cas
    }
