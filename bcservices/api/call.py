import math
import frappe
from frappe.utils import now_datetime, getdate, get_time
from datetime import datetime
from frappe import _

from .utils import (
    verify_clerk_bearer_and_get_sub,
    send_voip_push,
    get_actor_by_clerk_id,
    get_settings
)

# ----------------------------------------------------------------------
# POMOCNÉ FUNKCIE
# ----------------------------------------------------------------------

def get_actor_name_and_type(clerk_id: str):
    doctype, doc = get_actor_by_clerk_id(clerk_id)
    if not doc:
        frappe.throw("Unknown user")
    return doc.name, doctype


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


# ----------------------------------------------------------------------
# START CALL
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    settings = get_settings()
    admin_clerk_id = settings.admin_clerk_id

    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller_clerk = data.get("callerId")
    advisor_clerk = data.get("advisorId")

    if not caller_clerk or not advisor_clerk:
        frappe.throw(_("Missing callerId or advisorId"))

    # Bezpečnosť
    if clerk_id != caller_clerk and clerk_id != admin_clerk_id:
        frappe.throw(_("Forbidden"), frappe.PermissionError)

    # alias "admin"
    if advisor_clerk == "admin":
        advisor_clerk = admin_clerk_id

    # Lookup aktérov
    caller_name, caller_type = get_actor_name_and_type(caller_clerk)
    advisor_name, advisor_type = get_actor_name_and_type(advisor_clerk)

    if advisor_type != "Poradca":
        frappe.throw("Advisor must be Poradca")

    now = now_datetime()

    # ------------------------------------------------------------------
    # ZNAČKA KLIENTA (ostáva zachované správanie)
    # ------------------------------------------------------------------
    zn_caller = frappe.db.get_value("Klient", {"clerk_id": caller_clerk}, "znacka_klienta") if caller_type == "Klient" else None
    zn_advisor = frappe.db.get_value("Klient", {"clerk_id": advisor_clerk}, "znacka_klienta")
    finalna_znacka = zn_caller or zn_advisor

    # ------------------------------------------------------------------
    # TOKEN LOGIKA (PIATOK)
    # ------------------------------------------------------------------
    used_token = None
    token_required = is_friday(now) and caller_clerk != admin_clerk_id

    if token_required and caller_type == "Klient":
        used_token = pick_active_token_for_holder(caller_name)
        if not used_token:
            return {
                "success": False,
                "error": "V piatok je potrebný token. Nemáte dostupné minúty."
            }

    # ------------------------------------------------------------------
    # VYTVORENIE HOVORU
    # ------------------------------------------------------------------
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,
        "poradca": advisor_name,
        "zaciatok_datum": now.date(),
        "zaciatok_cas": now.strftime("%H:%M:%S"),
        "pouzity_token": used_token,
    })
    call.insert(ignore_permissions=True)

    # ------------------------------------------------------------------
    # GOOGLE CALENDAR
    # ------------------------------------------------------------------
    if not used_token and finalna_znacka:
        try:
            from .google_calendar import create_call_event
            event_id = create_call_event(call, finalna_znacka)
            if event_id:
                call.google_event_id = event_id
                call.save(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Google Calendar Start Error")

   # ------------------------------------------------------------------
    # VOIP PUSH (ZJEDNODUŠENÉ PO ZMENE DOCTYPE)
    # ------------------------------------------------------------------
    try:
        # Načítame dokument poradcu (advisor_type = "Poradca")
        adv_doc = frappe.get_doc(advisor_type, advisor_name)
        
        # Po tvojej úprave JSONu sa pole volá už len 'zariadenie'
        device_rows = adv_doc.get("zariadenie") or []
        
        if not device_rows:
            frappe.logger().warning(f"⚠️ Poradca {advisor_name} nemá v tabuľke žiadne zariadenia.")

        for row in device_rows:
            if row.voip_token:
                try:
                    # Log pre kontrolu v Error Logu
                    frappe.log_error(f"Odosielam VoIP push na token: {row.voip_token[:20]}...", "VoIP Debug")
                    
                    send_voip_push(row.voip_token, {
                        "callId": call.name,
                        "callerId": caller_clerk,
                        "callerName": caller_name,
                        "title": "Prichádzajúci hovor",
                        "body": f"Volá {caller_name}",
                    })
                except Exception as e:
                    frappe.log_error(f"VoIP Push failed: {str(e)}", "BC Call Error")
                    
    except Exception as e:
        frappe.log_error(f"Chyba pri získavaní zariadení: {str(e)}", "BC Call Error")

    return {
        "success": True,
        "callId": call.name,
        "tokenUsed": used_token,
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

    actor_name, actor_type = get_actor_name_and_type(clerk_id)
    if actor_type != "Poradca":
        frappe.throw("Only advisor can accept call")

    doc = frappe.get_doc("Dennik hovorov", call_id)

    if doc.poradca != actor_name:
        frappe.throw("Unauthorized", frappe.PermissionError)

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
    verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}
    call_id = data.get("callId")

    if not call_id:
        frappe.throw(_("Missing callId"))

    try:
        doc = frappe.get_doc("Dennik hovorov", call_id)
    except frappe.DoesNotExistError:
        frappe.throw(_("Hovor neexistuje"))

    now = now_datetime()

    # priamy zápis času
    frappe.db.set_value("Dennik hovorov", call_id, {
        "koniec_datum": now.date(),
        "koniec_cas": now.strftime("%H:%M:%S")
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
        frappe.log_error("Chyba výpočtu trvania", frappe.get_traceback())

    # TOKENY
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
            frappe.log_error("Token error", frappe.get_traceback())

    frappe.db.commit()

    return {
        "success": True,
        "callId": call_id,
        "duration": duration,
        "end_time": now.strftime("%H:%M:%S")
    }


# ----------------------------------------------------------------------
# CALL HISTORY
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str):
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    settings = get_settings()

    if clerk_id != userId and clerk_id != settings.admin_clerk_id:
        frappe.throw("Forbidden", frappe.PermissionError)

    name, actor_type = get_actor_name_and_type(userId)

    if actor_type == "Poradca":
        filters = {"poradca": name}
    else:
        filters = {"volajuci": name}

    calls = frappe.get_all(
        "Dennik hovorov",
        filters=filters,
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
