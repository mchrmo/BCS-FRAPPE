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
    # Načítanie dynamických nastavení z Frappe
    settings = get_settings()
    admin_id = settings.admin_clerk_id

    # 1. Overenie Clerk JWT
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller_clerk = data.get("callerId")
    advisor_clerk = data.get("advisorId")

    if not caller_clerk or not advisor_clerk:
        frappe.throw(_("Missing callerId or advisorId"))

    # Bezpečnosť: užívateľ môže začať hovor len za seba, alebo ak je admin
    if clerk_id != caller_clerk and clerk_id != admin_id:
        frappe.throw(_("Forbidden"), frappe.PermissionError)

    # Mapovanie skratky "admin" na reálne ID z Nastavení
    if advisor_clerk == "admin":
        advisor_clerk = admin_id

    # 2. Lookup mien účastníkov
    caller_name = get_klient_name_from_clerk(caller_clerk)
    advisor_name = get_klient_name_from_clerk(advisor_clerk)

    if not caller_name or not advisor_name:
        frappe.throw(_("Could not find participants in Klient database"))

    # 3. Zistenie značky klienta (obojsmerne)
    zn_caller = frappe.db.get_value("Klient", {"clerk_id": caller_clerk}, "znacka_klienta")
    zn_advisor = frappe.db.get_value("Klient", {"clerk_id": advisor_clerk}, "znacka_klienta")
    finalna_znacka = zn_caller or zn_advisor

    now = now_datetime()

    # 4. Logika Tokenov (Piatok)
    token_required = is_friday(now) and caller_clerk != admin_id
    used_token = None

    if token_required:
        used_token = pick_active_token_for_holder(caller_name)
        if not used_token:
            return {
                "success": False,
                "error": "V piatok je potrebný token. Nemáte dostupné minúty."
            }

    # 5. Vytvorenie hovoru v DB
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,
        "poradca": advisor_name,
        "zaciatok_datum": now.date(),
        "zaciatok_cas": now.time().strftime("%H:%M:%S"),
        "pouzity_token": used_token,
    })
    call.insert(ignore_permissions=True)

    # 6. Google Calendar (iba ak existuje značka a nie je to hovor na token)
    if not used_token and finalna_znacka:
        try:
            from .google_calendar import create_call_event
            event_id = create_call_event(call, finalna_znacka)
            if event_id:
                call.google_event_id = event_id
                call.save(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Google Calendar Start Error")

    # ... (predošlý kód zostáva rovnaký) ...

    # 7. VoIP Push notifikácie
    devices = frappe.get_all(
        "Zariadenie",
        filters={"parent": advisor_name},
        fields=["voip_token"]
    )

    for device in devices:
        token = device.get("voip_token")
        if token:
            try:
                send_voip_push(token, {
                    "callId": call.name,
                    "callerId": caller_clerk,
                    "callerName": caller_name,
                    "title": "Prichádzajúci hovor",
                    "body": f"Volá {caller_name}",
                })
            except Exception:
                pass

    # PRIDANÉ: advisorName do návratovej hodnoty
    return {
        "success": True, 
        "callId": call.name, 
        "tokenUsed": used_token,
        "advisorName": advisor_name  # Toto meno si aplikácia prevezme
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
    # 1. Overenie identity
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    
    data = frappe.local.form_dict or {}
    call_id = data.get("callId")

    if not call_id:
        frappe.throw(_("Missing callId"))

    # 2. Načítanie dokumentu
    try:
        doc = frappe.get_doc("Dennik hovorov", call_id)
    except frappe.DoesNotExistError:
        frappe.throw(_("Hovor neexistuje"))

    now = now_datetime()
    
    # 3. PRIAMY ZÁPIS ČASU (Najistejšia metóda)
    koniec_d = now.date()
    koniec_c = now.strftime("%H:%M:%S")
    
    frappe.db.set_value("Dennik hovorov", call_id, {
        "koniec_datum": koniec_d,
        "koniec_cas": koniec_c
    })

    # 4. VÝPOČET TRVANIA
    duration = 0
    try:
        start_dt = datetime.combine(getdate(doc.zaciatok_datum), get_time(doc.zaciatok_cas))
        duration = max(0, int((now - start_dt).total_seconds()))
        
        # Zápis trvania do poľa trvanie_s (overené podľa screenshotu)
        frappe.db.set_value("Dennik hovorov", call_id, "trvanie_s", duration)
    except Exception:
        frappe.log_error(title="Chyba vypoctu trvania", message=frappe.get_traceback())

    # 5. LOGIKA TOKENOV (ak bol hovor prijatý)
    if doc.pouzity_token and getattr(doc, "prijaty", 0):
        try:
            # Výpočet: každých začatých 6 minút (360s) = 6 minút
            mins = int(math.ceil(duration / 360.0)) * 6
            frappe.db.set_value("Dennik hovorov", call_id, "minuty_pouzite", mins)

            # Odčítanie z Tokenu
            token_doc = frappe.get_doc("Token", doc.pouzity_token)
            rem = max(0, int(token_doc.minuty_ostavajuce or 0) - mins)
            
            token_doc.db_set("minuty_ostavajuce", rem)
            if rem <= 0:
                token_doc.db_set("stav", "spent")
        except Exception:
            frappe.log_error(title="Token Error", message=frappe.get_traceback())

    # 6. COMMIT A ODPOVEĎ
    # Bez commitu sa zmeny pri whitelist volaní nemusia prejaviť v DB
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
