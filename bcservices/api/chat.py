import frappe
from frappe.utils import now_datetime

from .utils import get_actor_by_clerk_id


# ----------------------------------------------------------------------
# POMOCNÉ FUNKCIE
# ----------------------------------------------------------------------

def _get_actor_name_by_clerk_id(clerk_id: str) -> str:
    if not clerk_id:
        frappe.throw("Missing clerk_id")

    doctype, doc = get_actor_by_clerk_id(clerk_id)

    if not doc:
        frappe.throw(f"Unknown clerk_id: {clerk_id}")

    return doc.name


def _sanitize_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        frappe.throw("Empty message")
    if len(text) > 5000:
        frappe.throw("Message too long")
    return text


# ----------------------------------------------------------------------
# SAVE MESSAGE
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def save_message(from_clerk=None, to_clerk=None, content=None, room_id=None):
    # ⚠️ zatiaľ ponechané ako máš (test / trusted env)
    frappe.set_user("Administrator")

    sender = _get_actor_name_by_clerk_id(from_clerk)
    recipient = _get_actor_name_by_clerk_id(to_clerk)
    content = _sanitize_text(content)

    doc = frappe.get_doc({
        "doctype": "Sprava Chatu",
        "odosielatel": sender,
        "prijemca": recipient,
        "obsah": content,
        "datum_cas": now_datetime(),
    })

    if room_id and doc.meta.has_field("room_id"):
        doc.room_id = room_id

    doc.insert(ignore_permissions=True)

    return {
        "success": True,
        "message_id": doc.name,
        "timestamp": doc.datum_cas,
    }


# ----------------------------------------------------------------------
# UPLOAD FILE
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def upload_file():
    frappe.set_user("Administrator")

    if "file" not in frappe.request.files:
        frappe.throw("No file provided")

    uploaded = frappe.request.files["file"]

    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": uploaded.filename,
        "content": uploaded.stream.read(),
        "is_private": 1
    })
    file_doc.save(ignore_permissions=True)

    return {
        "success": True,
        "file_url": file_doc.file_url,
        "file_name": file_doc.file_name
    }


# ----------------------------------------------------------------------
# GET MESSAGES
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["GET"], allow_guest=True)
def get_messages(user_a=None, user_b=None, limit=100):
    frappe.set_user("Administrator")

    if not user_a or not user_b:
        frappe.throw("Missing user_a or user_b")

    actor_a = _get_actor_name_by_clerk_id(user_a)
    actor_b = _get_actor_name_by_clerk_id(user_b)

    limit = int(limit or 100)

    messages = frappe.get_all(
        "Sprava Chatu",
        filters=[
            ["odosielatel", "in", [actor_a, actor_b]],
            ["prijemca", "in", [actor_a, actor_b]],
        ],
        fields=[
            "odosielatel",
            "prijemca",
            "obsah",
            "datum_cas",
        ],
        order_by="datum_cas asc",
        limit_page_length=limit,
    )

    return {
        "success": True,
        "messages": [
            {
                "from": user_a if m["odosielatel"] == actor_a else user_b,
                "to": user_b if m["prijemca"] == actor_b else user_a,
                "content": m["obsah"],
                "timestamp": m["datum_cas"].isoformat(),
            }
            for m in messages
        ],
    }
