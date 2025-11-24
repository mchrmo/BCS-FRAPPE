# apps/bcservices/bcservices/api/call.py

import frappe
from frappe.utils import now_datetime
from .utils import (
    verify_clerk_bearer_and_get_sub,
    ensure_bc_user_by_clerk
)

# -----------------------------------------------------------------------------
# START CALL
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    """
    ADMIN → CLIENT (or CLIENT → ADMIN)
    Vytvorí záznam BC Call a pošle VoIP push advisorovi.
    """

    # 🔥 FIX — lazy import to avoid circular dependency
    from .utils import send_voip_push

    # Validate Clerk JWT
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller = data.get("callerId")
    advisor = data.get("advisorId")

    if not caller or not advisor:
        frappe.throw("Missing callerId or advisorId")

    # Create BC Call record
    call = frappe.get_doc({
        "doctype": "BC Call",
        "caller": caller,
        "advisor": advisor,
        "status": "ringing",
        "start_time": now_datetime()
    })
    call.insert(ignore_permissions=True)

    # Lookup advisor device
    advisor_user_ids = frappe.get_all(
        "BC Pouzivatel",
        filters={"clerk_id": advisor},
        pluck="name"
    )

    devices = []
    if advisor_user_ids:
        devices = frappe.get_all(
            "BC Zariadenie",
            filters={"parent": ["in", advisor_user_ids]},
            fields=["voip_token"],
            limit_page_length=5,
        )

    # Send VoIP push (if device exists)
    if devices:
        dev = devices[0]
        token = dev.get("voip_token")

        if token:
            try:
                send_voip_push(
                    token,
                    {
                        "callId": call.name,
                        "title": "Prichádzajúci hovor",
                        "body": "Volá druhá strana",
                    }
                )
            except Exception as e:
                frappe.log_error(f"VoIP push failed: {e}", "BC Call VoIP Error")

    return {
        "success": True,
        "callId": call.name,
        "status": "ringing"
    }

# -----------------------------------------------------------------------------
# ACCEPT CALL
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def accept():
    """Klient prijme hovor po VoIP push."""
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    call_id = data.get("callId")

    if not call_id:
        frappe.throw("Missing callId")

    doc = frappe.get_doc("BC Call", call_id)

    if doc.advisor != clerk_id:
        frappe.throw("You cannot accept someone else's call", frappe.PermissionError)

    doc.status = "ongoing"
    doc.answered_time = now_datetime()
    doc.save(ignore_permissions=True)

    return {"success": True, "callId": call_id, "status": "ongoing"}

# -----------------------------------------------------------------------------
# END CALL
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def end():
    """Ukončenie hovoru jednou zo strán."""
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    call_id = data.get("callId")

    if not call_id:
        frappe.throw("Missing callId")

    doc = frappe.get_doc("BC Call", call_id)

    doc.status = "ended"
    doc.end_time = now_datetime()
    doc.save(ignore_permissions=True)

    return {"success": True, "callId": call_id, "status": "ended"}

# -----------------------------------------------------------------------------
# CALL HISTORY
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str):
    """Prehľad hovorov pre daného používateľa (caller)."""
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    if clerk_id != userId:
        frappe.throw("Forbidden", frappe.PermissionError)

    calls = frappe.get_all(
        "BC Call",
        filters={"caller": userId},
        fields=["name", "advisor", "status", "start_time", "end_time"],
        order_by="start_time desc",
    )

    return {"success": True, "calls": calls}
