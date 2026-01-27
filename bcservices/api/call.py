import math
import frappe
from frappe.utils import now_datetime, getdate, get_time
from datetime import datetime
from frappe import _

from .utils import (
    verify_clerk_bearer_and_get_sub,
    send_voip_push,
    get_klient_by_clerk_or_throw
)

# ----------------------------------------------------------------------
# POMOCNÉ FUNKCIE
# ----------------------------------------------------------------------

def is_friday(dt) -> bool:
    # Monday=0 ... Sunday=6, Friday=4
    return dt.weekday() == 4


def pick_active_token_for_holder(klient_name: str) -> str | None:
    rows = frappe.get_all(
        "Token",
        filters={
            "aktualny_drzitel": klient_name,
            "stav": "active",
            "minuty_ostavajuce": [">", 0],
        },
        fields=["name"],
        order_by="modified asc",
        limit_page_length=1,
    )
    return rows[0]["name"] if rows else None


# ----------------------------------------------------------------------
# START CALL
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    # 1. Overenie Clerk JWT
    auth_clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller_clerk = data.get("callerId")
    advisor_clerk = data.get("advisorId")

    # LOGOVANIE PRE DEBUGGING
    frappe.log_error(
        f"START Call Request: Caller={caller_clerk}, Advisor={advisor_clerk}",
        "BC Call Debug"
    )

    if not caller_clerk or not advisor_clerk:
        frappe.throw(_("Missing callerId or advisorId"))

    # Klient môže volať len sám za seba
    if auth_clerk_id != caller_clerk:
        frappe.throw(_("Forbidden"), frappe.PermissionError)

    # ------------------------------------------------------------------
    # 2. Lookup AKTOROV PODĽA ROLE
    # ------------------------------------------------------------------

    # Klient (volajúci)
    caller_name = frappe.db.get_value(
        "Klient",
        {"clerk_id": caller_clerk},
        "name"
    )
    if not caller_name:
        frappe.throw(_("Caller is not a valid client"), frappe.PermissionError)

    # Poradca (volaný)
    advisor_name = frappe.db.get_value(
        "Poradca",
        {"clerk_id": advisor_clerk},
        "name"
    )
    if not advisor_name:
        frappe.log_error(f"Advisor NOT FOUND for ID: {advisor_clerk}", "BC Call Error")
        frappe.throw(_("Advisor not found"), frappe.PermissionError)

    # ------------------------------------------------------------------
    # 3. Overenie vzťahu Klient → Poradca
    # ------------------------------------------------------------------
    allowed = frappe.db.exists(
        "Poradca Klienta",
        {
            "parent": caller_name,   # Klient
            "poradca": advisor_name  # Poradca
        }
    )
    if not allowed:
        frappe.throw(_("Advisor not assigned to this client"), frappe.PermissionError)

    now = now_datetime()

    # ------------------------------------------------------------------
    # 4. Token logika (iba klient, iba piatok)
    # ------------------------------------------------------------------
    token_required = is_friday(now)
    used_token = None

    if token_required:
        used_token = pick_active_token_for_holder(caller_name)
        if not used_token:
            return {
                "success": False,
                "error": "V piatok je potrebný token. Nemáte dostupné minúty."
            }

    # ------------------------------------------------------------------
    # 5. Vytvorenie hovoru
    # ------------------------------------------------------------------
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,   # Klient
        "poradca": advisor_name,   # Poradca
        "zaciatok_datum": now.date(),
        "zaciatok_cas": now.strftime("%H:%M:%S"),
        "pouzity_token": used_token,
    })
    call.insert(ignore_permissions=True)
    
    # Commit, aby sa ID hovoru uložilo pred odoslaním Pushu
    frappe.db.commit()

    # ------------------------------------------------------------------
    # 6. VoIP PUSH → IBA ZARIADENIA PORADCU (OPRAVENÉ)
    # ------------------------------------------------------------------
    try:
        # Načítame celý dokument poradcu, aby sme mali prístup k Child Table 'zariadenie'
        advisor_doc = frappe.get_doc("Poradca", advisor_name)
        devices = advisor_doc.get("zariadenie") or []
        
        frappe.log_error(f"Found {len(devices)} devices for advisor {advisor_name}", "BC Call Debug")
        
        sent_count = 0

        for device in devices:
            if not device.voip_token:
                continue
                
            try:
                frappe.log_error(f"Sending Push to device token prefix: {device.voip_token[:10]}...", "BC Call Debug")
                
                send_voip_push(device.voip_token, {
                    "callId": call.name,
                    "callerId": caller_clerk,
                    "callerName": caller_name, # Meno klienta z DB
                    "title": "Prichádzajúci hovor",
                    "body": f"Volá {caller_name}",
                })
                sent_count += 1
            except Exception as e:
                frappe.log_error(f"Push failed for one device: {e}", "BC Push Error")

        if sent_count == 0:
            frappe.log_error(f"Warning: No valid VoIP tokens or Push failed for advisor {advisor_name}", "BC Call Warning")

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "BC Call Critical Error")

    return {
        "success": True,
        "callId": call.name,
        "advisorName": advisor_name
    }

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
    
    # Overíme, či clerk_id patrí poradcovi, ktorý má tento hovor zdvihnúť
    advisor_name = frappe.db.get_value("Poradca", {"clerk_id": clerk_id}, "name")

    if doc.poradca != advisor_name:
        frappe.throw("Unauthorized - This call is not for you", frappe.PermissionError)

    now = now_datetime()
    doc.prijaty = 1
    doc.prijaty_cas = now
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
        frappe.throw(_("Missing callId"))

    doc = frappe.get_doc("Dennik hovorov", call_id)
    now = now_datetime()

    koniec_d = now.date()
    koniec_c = now.strftime("%H:%M:%S")

    frappe.db.set_value("Dennik hovorov", call_id, {
        "koniec_datum": koniec_d,
        "koniec_cas": koniec_c
    })

    duration = 0
    try:
        start_dt = datetime.combine(
            getdate(doc.zaciatok_datum),
            get_time(doc.zaciatok_cas)
        )
        duration = max(0, int((now - start_dt).total_seconds()))
        frappe.db.set_value("Dennik hovorov", call_id, "trvanie_s", duration)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Duration Error")

    if doc.pouzity_token and getattr(doc, "prijaty", 0):
        mins = int(math.ceil(duration / 360.0)) * 6
        frappe.db.set_value("Dennik hovorov", call_id, "minuty_pouzite", mins)

        token_doc = frappe.get_doc("Token", doc.pouzity_token)
        rem = max(0, int(token_doc.minuty_ostavajuce or 0) - mins)

        token_doc.db_set("minuty_ostavajuce", rem)
        if rem <= 0:
            token_doc.db_set("stav", "spent")

    frappe.db.commit()

    return {
        "success": True,
        "callId": call_id,
        "duration": duration,
        "end_time": koniec_c
    }


# ----------------------------------------------------------------------
# CALL HISTORY
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str):
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    if clerk_id != userId:
        frappe.throw("Forbidden", frappe.PermissionError)

    klient_name = get_klient_by_clerk_or_throw(userId)

    calls = frappe.get_all(
        "Dennik hovorov",
        filters={"volajuci": klient_name},
        fields=[
            "name",
            "poradca",
            "zaciatok_datum",
            "zaciatok_cas",
            "trvanie_s",
            "pouzity_token",
        ],
        order_by="zaciatok_datum desc, zaciatok_cas desc",
    )

    return {"success": True, "calls": calls}
