import math
import frappe
from frappe.utils import now_datetime, getdate, get_time
from datetime import datetime
from frappe import _

from .utils import verify_clerk_bearer_and_get_sub, send_voip_push

# ----------------------------------------------------------------------
# POMOCNÉ FUNKCIE (Načítanie z Nastavení a DB)
# ----------------------------------------------------------------------
def get_settings():
    """Načíta dokument Nastavenie (Single DocType)"""
    return frappe.get_single("Nastavenie")

def get_klient_name_from_clerk(clerk_id: str | None):
    if not clerk_id:
        return None
    return frappe.db.get_value("Klient", {"clerk_id": clerk_id}, "name")

def is_friday(dt) -> bool:
    # Python: Monday=0 ... Sunday=6. Piatok je 4.
    return dt.weekday() == 4

def pick_active_token_for_holder(klient_name: str) -> str | None:
    """Vyberie jeden aktívny token pre daného klienta."""
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
    # 1. Načítanie nastavení a overenie identity
    settings = get_settings()
    admin_id = settings.admin_clerk_id
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller_clerk = data.get("callerId")
    advisor_clerk = data.get("advisorId")

    if not caller_clerk or not advisor_clerk:
        frappe.throw(_("Missing callerId or advisorId"))

    if clerk_id != caller_clerk and clerk_id != admin_id:
        frappe.throw(_("Forbidden"), frappe.PermissionError)

    if advisor_clerk == "admin":
        advisor_clerk = admin_id

    # 2. Lookup účastníkov a značky
    caller_name = get_klient_name_from_clerk(caller_clerk)
    advisor_name = get_klient_name_from_clerk(advisor_clerk)

    if not caller_name or not advisor_name:
        frappe.throw(_("Could not find participants in Klient database"))

    zn_caller = frappe.db.get_value("Klient", {"clerk_id": caller_clerk}, "znacka_klienta")
    zn_advisor = frappe.db.get_value("Klient", {"clerk_id": advisor_clerk}, "znacka_klienta")
    finalna_znacka = zn_caller or zn_advisor

    # 3. Logika Tokenov (Piatok)
    from frappe.utils import now_datetime, nowdate, nowtime
    now = now_datetime()
    token_required = is_friday(now) and caller_clerk != admin_id
    used_token = None

    if token_required:
        used_token = pick_active_token_for_holder(caller_name)
        if not used_token:
            return {
                "success": False,
                "error": "V piatok je potrebný token. Nemáte dostupné minúty."
            }

    # 4. Vytvorenie hovoru v DB
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,
        "poradca": advisor_name,
        "zaciatok_datum": nowdate(), # Zabezpečí správny formát pre kalendár
        "zaciatok_cas": nowtime(),   # Zabezpečí správny formát pre kalendár
        "pouzity_token": used_token,
    })
    call.insert(ignore_permissions=True)
    frappe.db.commit() # Uloží hovor do DB, aby ho kalendár videl

    # 5. Google Calendar (iba ak nie je token/piatok a je značka)
    if not used_token and finalna_znacka:
        try:
            from .google_calendar import create_call_event
            event_id = create_call_event(call, finalna_znacka)
            if event_id:
                call.google_event_id = event_id
                call.save(ignore_permissions=True)
                frappe.db.commit()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Google Calendar Start Error")

    # 6. VoIP Push (zjednodušené bez zbytočného try-except pass, aby si videl chyby)
    devices = frappe.get_all("Zariadenie", filters={"parent": advisor_name}, fields=["voip_token"])
    for device in devices:
        token = device.get("voip_token")
        if token:
            send_voip_push(token, {
                "callId": call.name,
                "callerId": caller_clerk,
                "callerName": caller_name,
                "title": "Prichádzajúci hovor",
                "body": f"Volá {caller_name}",
            })

    return {"success": True, "callId": call.name, "tokenUsed": used_token}

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
    user_name = get_klient_name_from_clerk(clerk_id)

    if doc.poradca != user_name:
        frappe.throw("Unauthorized", frappe.PermissionError)

    now = now_datetime()
    doc.prijaty = 1
    doc.prijaty_cas = now
    doc.save(ignore_permissions=True)

    return {"success": True, "callId": call_id}



@frappe.whitelist(methods=["POST"], allow_guest=True)
def end():
    from frappe.utils import get_datetime, nowdate, nowtime
    
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}
    call_id = data.get("callId")

    if not call_id:
        frappe.throw("Missing callId")

    doc = frappe.get_doc("Dennik hovorov", call_id)
    
    # Nastavenie konca hovoru
    doc.koniec_datum = nowdate()
    doc.koniec_cas = nowtime()

    # Robustný výpočet trvania
    try:
        start_dt = get_datetime(f"{doc.zaciatok_datum} {doc.zaciatok_cas}")
        end_dt = get_datetime(f"{doc.koniec_datum} {doc.koniec_cas}")
        doc.trvanie_s = max(0, int((end_dt - start_dt).total_seconds()))
    except Exception as e:
        frappe.log_error(f"Duration calculation error: {e}", "End Call Error")
        doc.trvanie_s = 0

    # Logika odrátania tokenov
    if doc.pouzity_token and doc.trvanie_s > 0 and getattr(doc, "prijaty", 0):
        try:
            minutes_to_deduct = int(math.ceil(doc.trvanie_s / 360.0)) * 6
            doc.minuty_pouzite = minutes_to_deduct

            token_doc = frappe.get_doc("Token", doc.pouzity_token)
            remaining = max(0, int(token_doc.minuty_ostavajuce or 0) - minutes_to_deduct)
            token_doc.minuty_ostavajuce = remaining
            token_doc.stav = "spent" if remaining == 0 else "active"
            token_doc.save(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Token Deduction Error")

    doc.save(ignore_permissions=True)
    frappe.db.commit() # Zabezpečí, že sa dáta uložia aj pri volaní cez API

    # Aktualizácia kalendára
    if doc.google_event_id:
        try:
            zn_v = frappe.db.get_value("Klient", {"name": doc.volajuci}, "znacka_klienta")
            zn_p = frappe.db.get_value("Klient", {"name": doc.poradca}, "znacka_klienta")
            from .google_calendar import update_call_event_end
            update_call_event_end(doc, zn_v or zn_p)
        except Exception:
            pass

    return {"success": True, "callId": call_id, "duration_s": doc.trvanie_s}

# ----------------------------------------------------------------------
# CALL HISTORY
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str):
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    settings = get_settings()

    if clerk_id != userId and clerk_id != settings.admin_clerk_id:
        frappe.throw("Forbidden", frappe.PermissionError)

    klient_name = get_klient_name_from_clerk(userId)

    calls = frappe.get_all(
        "Dennik hovorov",
        filters={"volajuci": klient_name},
        fields=["name", "poradca", "zaciatok_datum", "zaciatok_cas", "trvanie_s", "pouzity_token"],
        order_by="zaciatok_datum desc, zaciatok_cas desc",
    )

    return {"success": True, "calls": calls}
