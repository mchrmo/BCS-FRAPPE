# apps/bcservices/bcservices/api/call.py

import frappe
from frappe.utils import now_datetime
from datetime import datetime
from .utils import verify_clerk_bearer_and_get_sub, send_voip_push


# ----------------------------------------------------------------------
# HELPER — map clerk_id → Klient.name
# ----------------------------------------------------------------------
def get_klient_name_from_clerk(clerk_id: str | None):
    if not clerk_id:
        return None

    return frappe.db.get_value("Klient", {"clerk_id": clerk_id}, "name")


# ----------------------------------------------------------------------
# START CALL
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    # Overenie Clerk JWT
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller_clerk = data.get("callerId")
    advisor_clerk = data.get("advisorId")

    if not caller_clerk or not advisor_clerk:
        frappe.throw("Missing callerId or advisorId")

    # 🔥 iOS posiela "admin"? Prevedieme na reálny Clerk ID admina
    if advisor_clerk == "admin":
        advisor_clerk = "user_30p94nuw9O2UHOEsXmDhV2SgP8N"

    # -------------------------------------------------------------------
    # Získaj Klient.name (primárny key)
    # -------------------------------------------------------------------
    caller_name = get_klient_name_from_clerk(caller_clerk)
    advisor_name = get_klient_name_from_clerk(advisor_clerk)

    if not caller_name:
        frappe.throw(
            f"Could not find caller in Klient: {caller_clerk}",
            frappe.LinkValidationError
        )

    if not advisor_name:
        frappe.throw(
            f"Could not find advisor in Klient: {advisor_clerk}",
            frappe.LinkValidationError
        )

    # -------------------------------------------------------------------
    # Vytvor nový záznam hovoru
    # -------------------------------------------------------------------
    now = now_datetime()
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,
        "poradca": advisor_name,
        "zaciatok_datum": now.date(),
        "zaciatok_cas": now.time().strftime("%H:%M:%S"),
    })
    call.insert(ignore_permissions=True)

    # -------------------------------------------------------------------
    # Nájdeme všetky zariadenia poradcu (multi-device)
    # -------------------------------------------------------------------
    devices = frappe.get_all(
        "Zariadenie",
        filters={"parent": advisor_name},
        fields=["voip_token"],
        limit_page_length=20,
    )

    # -------------------------------------------------------------------
    # Pošleme VoIP push na KAŽDÉ zariadenie
    # -------------------------------------------------------------------
    for d in devices:
        token = d.get("voip_token")
        if not token:
            continue

        try:
            # 🔥 Získaj username volajúceho (z Doctype Klient)
            caller_username = frappe.db.get_value(
			    "Klient",
			    {"clerk_id": caller_clerk},
			    "username"
			)
			
			send_voip_push(
			    token,
			    {
			        "callId": call.name,
			        "callerId": caller_clerk,
			        "callerName": caller_username or caller_clerk,
			        "title": "Prichádzajúci hovor",
			        "body": f"Volá {caller_username or caller_clerk}",
			    }
			)

        except Exception as e:
            frappe.log_error(
                f"VoIP push failed for device {token}: {e}",
                "BC VoIP Error"
            )

    # -------------------------------------------------------------------
    return {"success": True, "callId": call.name}

# ----------------------------------------------------------------------
# ACCEPT CALL
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def accept():
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}

    call_id = data.get("callId")
    if not call_id:
        frappe.throw("Missing callId")

    doc = frappe.get_doc("Dennik hovorov", call_id)

    advisor_name = get_klient_name_from_clerk(clerk_id)

    if doc.poradca != advisor_name:
        frappe.throw("You cannot accept someone else's call", frappe.PermissionError)

    # Pri accept nič nemeníme, len validujeme
    doc.save(ignore_permissions=True)

    return {"success": True, "callId": call_id}


# ----------------------------------------------------------------------
# END CALL
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def end():
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}

    call_id = data.get("callId")
    if not call_id:
        frappe.throw("Missing callId")

    doc = frappe.get_doc("Dennik hovorov", call_id)
    now = now_datetime()

    # 🔥 Ulož ukončenie hovoru
    doc.koniec_datum = now.date()
    doc.koniec_cas = now.time().strftime("%H:%M:%S")

    # 🔥 Výpočet trvania
    try:
        start_dt = datetime.combine(
            doc.zaciatok_datum,
            datetime.strptime(doc.zaciatok_cas, "%H:%M:%S").time()
        )
        end_dt = datetime.combine(
            doc.koniec_datum,
            datetime.strptime(doc.koniec_cas, "%H:%M:%S").time()
        )
        doc.trvanie_s = int((end_dt - start_dt).total_seconds())
    except Exception as e:
        frappe.log_error(f"Duration calc error: {e}", "BC Call Duration Error")

    doc.save(ignore_permissions=True)

    return {"success": True, "callId": call_id}


# ----------------------------------------------------------------------
# CALL HISTORY
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str):
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    if clerk_id != userId:
        frappe.throw("Forbidden", frappe.PermissionError)

    klient_name = get_klient_name_from_clerk(userId)

    calls = frappe.get_all(
        "Dennik hovorov",
        filters={"volajuci": klient_name},
        fields=[
            "name",
            "poradca",
            "zaciatok_datum",
            "zaciatok_cas",
            "koniec_datum",
            "koniec_cas",
            "trvanie_s",
        ],
        order_by="zaciatok_datum desc, zaciatok_cas desc",
    )

    return {"success": True, "calls": calls}
