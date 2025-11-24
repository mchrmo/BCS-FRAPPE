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
    Vytvorí záznam v 'BC Dennik hovorov' a pošle VoIP push poradcovi / klientovi.
    """

    # lazy import aby nevznikol circular
    from .utils import send_voip_push

    # Validate Clerk JWT
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller = data.get("callerId")
    advisor = data.get("advisorId")

    if not caller or not advisor:
        frappe.throw("Missing callerId or advisorId")

    # Create new call record in 'BC Dennik hovorov'
    call = frappe.get_doc({
        "doctype": "BC Dennik hovorov",
        "volajuci": caller,
        "poradca": advisor,
        "zaciatok": now_datetime(),
        "stav": "ringing"
    })
    call.insert(ignore_permissions=True)

    # Lookup target device (advisor side)
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

    # Send VoIP push
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
    """Poradca/klient prijme hovor."""
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    call_id = data.get("callId")

    if not call_id:
        frappe.throw("Missing callId")

    doc = frappe.get_doc("BC Dennik hovorov", call_id)

    if doc.poradca != clerk_id:
        frappe.throw("You cannot accept someone else's call", frappe.PermissionError)

    doc.stav = "ongoing"
    doc.odpoved = now_datetime()
    doc.save(ignore_permissions=True)

    return {"success": True, "callId": call_id, "status": "ongoing"}

# -----------------------------------------------------------------------------
# END CALL
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True])
def end():
    """Ukončenie hovoru jednou zo strán."""
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    call_id = data.get("callId")

    if not call_id:
        frappe.throw("Missing callId")

    doc = frappe.get_doc("BC Dennik hovorov", call_id)

    doc.stav = "ended"
    doc.koniec = now_datetime()

    # Calculate duration if possible
    try:
        if doc.zaciatok and doc.koniec:
            delta = (doc.koniec - doc.zaciatok).total_seconds()
            doc.trvanie = int(delta)
    except Exception:
        pass

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
        "BC Dennik hovorov",
        filters={"volajuci": userId},
        fields=["name", "poradca", "stav", "zaciatok", "koniec", "trvanie"],
        order_by="zaciatok desc",
    )

    return {"success": True, "calls": calls}
