# apps/bcservices/bcservices/api/chat.py

import frappe
from frappe.utils import now_datetime


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------

def _get_client_name_by_clerk_id(clerk_id: str) -> str:
    """
    Preloží Clerk ID -> Klienti.name
    """
    if not clerk_id:
        frappe.throw("Missing clerk_id")

    name = frappe.db.get_value(
        "Klienti",
        {"clerk_id": clerk_id},
        "name"
    )

    if not name:
        frappe.throw(f"Unknown clerk_id: {clerk_id}")

    return name


def _sanitize_text(text: str) -> str:
    """
    Základná validácia textu správy
    """
    text = (text or "").strip()

    if not text:
        frappe.throw("Empty message")

    if len(text) > 5000:
        frappe.throw("Message too long")

    return text


# ---------------------------------------------------------------------
# API: SAVE MESSAGE (TEST MODE)
# ---------------------------------------------------------------------

@frappe.whitelist(methods=["POST"], allow_guest=True)
def save_message():
    """
    ⚠️ TESTOVACIA VERZIA
    - allow_guest=True
    - set_user("Administrator") -> obchádza permissions

    PARAMETRE:
      - from     : clerk_id odosielateľa
      - to       : clerk_id príjemcu
      - content  : text správy
      - room_id  : optional
    """

    # ⛔ DOČASNE – LEN NA TEST
    frappe.set_user("Administrator")

    data = frappe.local.form_dict

    from_clerk = data.get("from")
    to_clerk = data.get("to")
    content = data.get("content")
    room_id = data.get("room_id")

    # --- validácia ---
    sender = _get_client_name_by_clerk_id(from_clerk)
    recipient = _get_client_name_by_clerk_id(to_clerk)
    content = _sanitize_text(content)

    # --- vytvorenie dokumentu ---
    doc = frappe.get_doc({
        "doctype": "Sprava chatu",
        "odosielatel": sender,
        "prijemca": recipient,
        "obsah": content,
        "datum_cas": now_datetime(),
    })

    # ak máš pole room_id v Doctype Sprava chatu
    if room_id and doc.meta.has_field("room_id"):
        doc.room_id = room_id

    doc.insert()

    return {
        "success": True,
        "message_id": doc.name,
        "timestamp": doc.datum_cas,
    }


# ---------------------------------------------------------------------
# API: GET CHAT HISTORY (TIEŽ TEST MODE)
# ---------------------------------------------------------------------

@frappe.whitelist(methods=["GET"], allow_guest=True)
def get_history():
    """
    ⚠️ TESTOVACIA VERZIA
    Vracia históriu chatu medzi dvoma používateľmi.

    PARAMETRE:
      - user_a : clerk_id
      - user_b : clerk_id
      - limit  : optional (default 50)
    """

    # ⛔ DOČASNE – LEN NA TEST
    frappe.set_user("Administrator")

    data = frappe.local.form_dict

    clerk_a = data.get("user_a")
    clerk_b = data.get("user_b")
    limit = int(data.get("limit") or 50)

    if not clerk_a or not clerk_b:
        frappe.throw("Missing users")

    client_a = _get_client_name_by_clerk_id(clerk_a)
    client_b = _get_client_name_by_clerk_id(clerk_b)

    rows = frappe.db.get_all(
        "Sprava chatu",
        filters=[
            ["odosielatel", "in", [client_a, client_b]],
            ["prijemca", "in", [client_a, client_b]],
        ],
        fields=[
            "name",
            "odosielatel",
            "prijemca",
            "obsah",
            "datum_cas",
        ],
        order_by="datum_cas asc",
        limit=limit,
    )

    clerk_map = {
        client_a: clerk_a,
        client_b: clerk_b,
    }

    return [
        {
            "id": r.name,
            "from": clerk_map.get(r.odosielatel),
            "to": clerk_map.get(r.prijemca),
            "content": r.obsah,
            "timestamp": r.datum_cas,
        }
        for r in rows
    ]
