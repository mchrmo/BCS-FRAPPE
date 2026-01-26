import math
import frappe
from frappe.utils import now_datetime, getdate, get_time
from datetime import datetime
from frappe import _

from .utils import verify_clerk_bearer_and_get_sub, send_voip_push

# ----------------------------------------------------------------------
# POMOCNÉ FUNKCIE
# ----------------------------------------------------------------------

def get_settings():
    return frappe.get_single("Nastavenie")


def get_actor_name_and_type(clerk_id: str):
    """
    Vráti (name, type) kde type ∈ {"Klient", "Poradca"}
    """
    klient = frappe.db.get_value("Klient", {"clerk_id": clerk_id}, "name")
    if klient:
        return klient, "Klient"

    poradca = frappe.db.get_value("Poradca", {"clerk_id": clerk_id}, "name")
    if poradca:
        return poradca, "Poradca"

    return None, None


def is_friday(dt) -> bool:
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


def client_has_advisor(client_name: str, advisor_name: str) -> bool:
    return bool(
        frappe.db.exists(
            "Poradca Klienta",
            {
                "parent": client_name,
                "poradca": advisor_name,
            },
        )
    )


def get_actor_name_from_clerk(clerk_id: str):
    name, _ = get_actor_name_and_type(clerk_id)
    return name


# ----------------------------------------------------------------------
# START CALL
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller_clerk = data.get("callerId")
    callee_clerk = data.get("advisorId")  # historický názov = callee

    if not caller_clerk or not callee_clerk:
        frappe.throw(_("Missing callerId or advisorId"))

    if clerk_id != caller_clerk:
        frappe.throw(_("Forbidden"), frappe.PermissionError)

    caller_name, caller_type = get_actor_name_and_type(caller_clerk)
    callee_name, callee_type = get_actor_name_and_type(callee_clerk)

    if not caller_name or not callee_name:
        frappe.throw(_("Caller or callee not found"))

    # Validácia vzťahu (cez Klienta)
    if caller_type == "Klient" and callee_type == "Poradca":
        if not client_has_advisor(caller_name, callee_name):
            frappe.throw(_("Tento poradca nepatrí klientovi"), frappe.PermissionError)

    elif caller_type == "Poradca" and callee_type == "Klient":
        if not client_has_advisor(callee_name, caller_name):
            frappe.throw(_("Tento klient nemá priradeného poradcu"), frappe.PermissionError)

    else:
        frappe.throw(_("Invalid caller/callee combination"), frappe.PermissionError)

    now = now_datetime()

    # Token logika (iba klient → poradca v piatok)
    used_token = None
    if caller_type == "Klient" and is_friday(now):
        used_token = pick_active_token_for_holder(caller_name)
        if not used_token:
            return {
                "success": False,
                "error": "V piatok je potrebný token. Nemáte dostupné minúty."
            }

    # Vytvorenie hovoru
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,
        "poradca": callee_name,  # historický názov = callee
        "zaciatok_datum": now.date(),
        "zaciatok_cas": now.strftime("%H:%M:%S"),
        "pouzity_token": used_token,
    })
    call.insert(ignore_permissions=True)

    # VoIP push → volaný
    devices = frappe.get_all(
        "Zariadenie",
        filters={"parent": callee_name},
        fields=["voip_token"],
    )

    for device in devices:
        if not device.voip_token:
            continue
        send_voip_push(device.voip_token, {
            "callId": call.name,
            "callerId": caller_clerk,
            "callerName": caller_name,
            "title": "Prichádzajúci hovor",
            "body": f"Volá {caller_name}",
        })

    return {
        "success": True,
        "callId": call.name,
        "tokenUsed": used_token,
        "calleeName": callee_name,
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
        frappe.throw(_("Missing callId"))

    doc = frappe.get_doc("Dennik hovorov", call_id)
    actor_name = get_actor_name_from_clerk(clerk_id)

    if doc.poradca != actor_name:
        frappe.throw(_("Unauthorized"), frappe.PermissionError)

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
    actor_name = get_actor_name_from_clerk(clerk_id)

    if actor_name not in (doc.volajuci, doc.poradca):
        frappe.throw(_("Unauthorized"), frappe.PermissionError)

    now = now_datetime()

    koniec_d = now.date()
    koniec_c = now.strftime("%H:%M:%S")

    frappe.db.set_value("Dennik hovorov", call_id, {
        "koniec_datum": koniec_d,
        "koniec_cas": koniec_c,
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
        frappe.log_error(frappe.get_traceback(), "Duration calc error")

    # Token logika
    if doc.pouzity_token and getattr(doc, "prijaty", 0):
        try:
            mins = int(math.ceil(duration / 360.0)) * 6
            frappe.db.set_value("Dennik hovorov", call_id, "minuty_pouzite", mins)

            token_doc = frappe.get_doc("Token", doc.pouzity_token)
            rem = max(0, int(token_doc.minuty_ostavajuce or 0) - mins)

            token_doc.db_set("minuty_ostavajuce", rem)
            if rem <= 0:
                token_doc.db_set("stav", "spent")
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Token error")

    frappe.db.commit()

    return {
        "success": True,
        "callId": call_id,
        "duration": duration,
        "end_time": koniec_c,
    }


# ----------------------------------------------------------------------
# CALL HISTORY
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str):
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    if clerk_id != userId:
        frappe.throw(_("Forbidden"), frappe.PermissionError)

    actor_name, _ = get_actor_name_and_type(userId)

    calls = frappe.get_all(
        "Dennik hovorov",
        filters=[
            ["volajuci", "=", actor_name],
            ["poradca", "=", actor_name],
        ],
        or_filters=True,
        fields=[
            "name",
            "volajuci",
            "poradca",
            "zaciatok_datum",
            "zaciatok_cas",
            "trvanie_s",
            "pouzity_token",
        ],
        order_by="zaciatok_datum desc, zaciatok_cas desc",
    )

    return {"success": True, "calls": calls}
