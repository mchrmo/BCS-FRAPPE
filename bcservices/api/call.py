# apps/bcservices/bcservices/api/call.py

import frappe
from frappe.utils import now_datetime
from .utils import (
    verify_clerk_bearer_and_get_sub,
)

# -----------------------------------------------------------------------------
# START CALL
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    """Vytvorí záznam v 'BC Dennik hovorov' a pošle VoIP push."""
    from .utils import send_voip_push

    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller = data.get("callerId")
    advisor = data.get("advisorId")

    if not caller or not advisor:
        frappe.throw("Missing callerId or advisorId")

    # 🔥 Mapovanie admin -> reálny clerk_id
    if advisor == "admin":
        advisor = "user_30p94nuw9O2UHOEsXmDhV2SgP8N"

    # 🔥 Vytvorenie záznamu (Doctype nemá pole 'stav')
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller,
        "poradca": advisor,
        "zaciatok": now_datetime()
    })
    call.insert(ignore_permissions=True)

    # 🔥 Nájsť device poradcu
    advisor_user_ids = frappe.get_all(
        "Pouzivatel",
        filters={"clerk_id": advisor},
        pluck="name"
    )

    devices = []
    if advisor_user_ids:
        devices = frappe.get_all(
            "Zariadenie",
            filters={"parent": ["in", advisor_user_ids]},
            fields=["voip_token"],
            limit_page_length=5,
        )

    # 🔥 Poslať VoIP push
    if devices:
        token = devices[0].get("voip_token")
        if token:
            try:
                send_voip_push(
				    token,
				    {
				        "callId": call.name,
				        "callerId": caller,             # ← NUTNÉ PRE CALLKIT
				        "callerName": caller,           # ← voliteľné, ale odporúčané
				        "title": "Prichádzajúci hovor",
				        "body": "Volá druhá strana",
				    }
				)

            except Exception as e:
                frappe.log_error(f"VoIP push failed: {e}", "BC VoIP Error")

    return {
        "success": True,
        "callId": call.name
    }

# -----------------------------------------------------------------------------
# ACCEPT CALL
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def accept():
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}

    call_id = data.get("callId")
    if not call_id:
        frappe.throw("Missing callId")

    doc = frappe.get_doc("Dennik hovorov", call_id)

    if doc.poradca != clerk_id:
        frappe.throw("You cannot accept someone else's call", frappe.PermissionError)

    # Tento Doctype nemá pole 'odpoved'
    doc.save(ignore_permissions=True)

    return {"success": True, "callId": call_id}

# -----------------------------------------------------------------------------
# END CALL
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def end():
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}

    call_id = data.get("callId")
    if not call_id:
        frappe.throw("Missing callId")

    doc = frappe.get_doc("Dennik hovorov", call_id)

    doc.koniec = now_datetime()

    # vypočítaj trvanie
    try:
        if doc.zaciatok and doc.koniec:
            seconds = int((doc.koniec - doc.zaciatok).total_seconds())
            doc.trvanie_s = seconds
    except Exception:
        pass

    doc.save(ignore_permissions=True)

    return {"success": True, "callId": call_id}

# -----------------------------------------------------------------------------
# CALL HISTORY
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str):
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    if clerk_id != userId:
        frappe.throw("Forbidden", frappe.PermissionError)

    calls = frappe.get_all(
        "Dennik hovorov",
        filters={"volajuci": userId},
        fields=["name", "poradca", "zaciatok", "koniec", "trvanie_s"],
        order_by="zaciatok desc",
    )

    return {"success": True, "calls": calls}