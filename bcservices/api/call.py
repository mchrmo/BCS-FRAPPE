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
@frappe.whitelist(methods=["GET"], allow_guest=True)
def test_log():
    frappe.log_error("TEST LOG FUNGUJE", "BC Test")
    return "OK, check error log"


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


@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    # 1. Logovanie vstupu
    auth_clerk_id, _ = verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}
    caller_clerk = data.get("callerId")
    advisor_clerk = data.get("advisorId")

    frappe.log_error(f"1. VSTUP: Caller={caller_clerk}, Advisor={advisor_clerk}", "BC Call Debug")

    if not caller_clerk or not advisor_clerk:
        frappe.throw(_("Missing callerId or advisorId"))

    # 2. Hľadanie mien v DB
    caller_name = frappe.db.get_value("Klient", {"clerk_id": caller_clerk}, "name")
    advisor_name = frappe.db.get_value("Poradca", {"clerk_id": advisor_clerk}, "name")

    frappe.log_error(f"2. DB MENA: Klient={caller_name}, Poradca={advisor_name}", "BC Call Debug")

    if not advisor_name:
        frappe.log_error("!!! CHYBA: Poradca s týmto Clerk ID neexistuje v tabuľke Poradca", "BC Call Debug")
        frappe.throw(_("Advisor not found"))

    # 3. Načítanie dokumentu poradcu a jeho zariadení
    try:
        advisor_doc = frappe.get_doc("Poradca", advisor_name)
        # Tu skúsime oba názvy, ak by si mal preklep v Doctype
        devices = advisor_doc.get("zariadenie") or advisor_doc.get("zariadenia") or []
        
        frappe.log_error(f"3. ZARIADENIA: Nájdených {len(devices)} v tabuľke pre {advisor_name}", "BC Call Debug")
    except Exception as e:
        frappe.log_error(f"!!! CHYBA pri get_doc: {str(e)}", "BC Call Debug")
        frappe.throw(str(e))

    # 4. Vytvorenie hovoru (zjednodušené pre test)
    now = now_datetime()
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,
        "poradca": advisor_name,
        "zaciatok_datum": now.date(),
        "zaciatok_cas": now.strftime("%H:%M:%S"),
    })
    call.insert(ignore_permissions=True)
    frappe.db.commit()
    
    frappe.log_error(f"4. HOVOR VYTVORENÝ: {call.name}", "BC Call Debug")

    # 5. Odosielanie PUSH
    sent_count = 0
    for d in devices:
        token = getattr(d, "voip_token", None) or getattr(d, "voipToken", None)
        if token:
            frappe.log_error(f"5. SKÚŠAM PUSH: Token začína na {token[:10]}", "BC Call Debug")
            try:
                send_voip_push(token, {
                    "callId": call.name,
                    "callerName": caller_name,
                    "title": "Prichádzajúci hovor"
                })
                sent_count += 1
            except Exception as e:
                frappe.log_error(f"!!! PUSH FAIL: {str(e)}", "BC Call Debug")

    return {"success": True, "callId": call.name, "sent_to": sent_count}

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
