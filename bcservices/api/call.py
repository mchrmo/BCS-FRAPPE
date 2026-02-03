import math
import traceback
import frappe
from frappe.utils import now_datetime, getdate, get_time
from datetime import datetime, timedelta
from frappe import _

# Importujeme pomocné funkcie z utils
from .utils import (
    verify_clerk_bearer_and_get_sub,
    send_voip_push,
    get_klient_by_clerk_or_throw
)

# Importujeme Google Calendar logiku (z nového súboru google_calendar.py)
try:
    from .google_calendar import create_call_event, update_call_event_end
except ImportError:
    # Fallback ak súbor neexistuje, aby nezhavaroval celý server, len logne chybu
    frappe.log_error("Chýba súbor google_calendar.py", "BC Import Error")
    create_call_event = None
    update_call_event_end = None

# ----------------------------------------------------------------------
# POMOCNÉ FUNKCIE
# ----------------------------------------------------------------------

@frappe.whitelist(methods=["GET"], allow_guest=True)
def test_log():
    frappe.log_error("TEST LOG FUNGUJE", "BC DEBUG - TEST")
    return "OK, check error log"

# ----------------------------------------------------------------------
# START CALL (Obojstranný)
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    debug_id = frappe.generate_hash(length=4)
    log_tag = f"BC DEBUG [{debug_id}]"
    data = frappe.local.form_dict or {}
    
    c1_id = data.get("callerId")
    c2_id = data.get("advisorId")

    try:
        # 1. Overenie kto drží telefón (autentifikovaný používateľ)
        auth_clerk_id, _ = verify_clerk_bearer_and_get_sub()

        # 2. Identifikácia účastníkov v DB
        p1_klient = frappe.db.get_value("Klient", {"clerk_id": c1_id}, "name")
        p1_poradca = frappe.db.get_value("Poradca", {"clerk_id": c1_id}, "name")
        
        p2_klient = frappe.db.get_value("Klient", {"clerk_id": c2_id}, "name")
        p2_poradca = frappe.db.get_value("Poradca", {"clerk_id": c2_id}, "name")

        real_klient = p1_klient or p2_klient
        real_poradca = p1_poradca or p2_poradca

        if not real_klient or not real_poradca:
            return {"success": False, "error": "Participants not found"}

        # 3. Určenie smeru hovoru (Kto volal)
        kto_volal = "Klient" if p1_klient else "Poradca"

        # 4. Určenie cieľa pre PUSH (vždy ten druhý, kto nie je auth_clerk_id)
        if auth_clerk_id == c1_id:
            target_doctype = "Poradca" if p2_poradca else "Klient"
            target_id = p2_poradca or p2_klient
            display_name = p1_poradca or p1_klient
        else:
            target_doctype = "Poradca" if p1_poradca else "Klient"
            target_id = p1_poradca or p1_klient
            display_name = p2_poradca or p2_klient

        # 5. Zápis do Denníka hovorov
        now = now_datetime()
        call_doc = frappe.get_doc({
            "doctype": "Dennik hovorov",
            "klient": real_klient,      # Link na Klienta
            "poradca": real_poradca,    # Link na Poradcu
            "kto_volal": kto_volal,     # "Klient" alebo "Poradca"
            "zaciatok_datum": now.date(),
            "zaciatok_cas": now.strftime("%H:%M:%S"),
        })
        call_doc.insert(ignore_permissions=True)
        frappe.db.commit() # Commit aby sme mali ID pre Google

        # --- GOOGLE CALENDAR START ---
        if create_call_event:
            try:
                # Do kalendára pošleme meno klienta ako "titul"
                event_id = create_call_event(call_doc, display_title=real_klient)
                
                if event_id:
                    # Uložíme ID udalosti späť do hovoru (bez spustenia validácií pre rýchlosť)
                    call_doc.db_set("google_event_id", event_id)
            except Exception as e:
                frappe.log_error(f"Failed to create Google Event: {e}", log_tag)
        # -----------------------------

        # 6. Odoslanie PUSH
        target_doc = frappe.get_doc(target_doctype, target_id)
        devices = target_doc.get("zariadenie") or []
        sent_count = 0
        for d in devices:
            token = getattr(d, "voip_token", None) or getattr(d, "voipToken", None)
            if token:
                payload = {
                    "callId": call_doc.name,
                    "callerId": auth_clerk_id,
                    "callerName": display_name,
                    "title": "Prichádzajúci hovor"
                }
                if send_voip_push(token, payload):
                    sent_count += 1

        return {"success": True, "callId": call_doc.name, "sent_to": sent_count}

    except Exception:
        frappe.log_error(traceback.format_exc(), log_tag)
        return {"success": False, "error": "Internal server error"}

# ----------------------------------------------------------------------
# ACCEPT CALL
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def accept():
    try:
        clerk_id, _ = verify_clerk_bearer_and_get_sub()
        data = frappe.local.form_dict or {}
        call_id = data.get("callId")

        if not call_id or call_id == "PENDING":
            return {"success": True, "note": "Call not in DB"}

        doc = frappe.get_doc("Dennik hovorov", call_id)

        # OVERENIE: Je ten, kto klikol "Prijať", jeden z účastníkov hovoru?
        is_valid = False
        klient_name = frappe.db.get_value("Klient", {"clerk_id": clerk_id}, "name")
        advisor_name = frappe.db.get_value("Poradca", {"clerk_id": clerk_id}, "name")

        # Oprava: Kontrolujeme polia 'klient' a 'poradca', nie 'volajuci'
        if (klient_name and doc.klient == klient_name) or (advisor_name and doc.poradca == advisor_name):
            is_valid = True

        if not is_valid:
            frappe.throw(_("Unauthorized to accept this call"), frappe.PermissionError)

        doc.prijaty = 1
        doc.prijaty_cas = now_datetime()
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        return {"success": True, "callId": call_id}
    except Exception as e:
        frappe.log_error(traceback.format_exc(), "BC Accept Error")
        return {"success": False, "error": str(e)}

# ----------------------------------------------------------------------
# END CALL
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def end():
    try:
        clerk_id, _ = verify_clerk_bearer_and_get_sub()
        data = frappe.local.form_dict or {}
        call_id = data.get("callId")

        if not call_id or call_id == "PENDING":
            return {"success": True}

        # Načítame dokument
        doc = frappe.get_doc("Dennik hovorov", call_id)
        now = now_datetime()

        # Nastavíme koniec
        doc.koniec_datum = now.date()
        doc.koniec_cas = now.strftime("%H:%M:%S")
        
        # Vypočítame trvanie
        try:
            start_dt = datetime.combine(getdate(doc.zaciatok_datum), get_time(doc.zaciatok_cas))
            duration = max(0, int((now - start_dt).total_seconds()))
            doc.trvanie_s = duration
        except:
            doc.trvanie_s = 0

        # Uložíme do DB
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        # --- GOOGLE CALENDAR UPDATE ---
        if update_call_event_end:
            try:
                # Reload, aby sme mali istotu, že máme čerstvé dáta
                doc.reload()
                update_call_event_end(doc, display_title=doc.klient)
            except Exception as e:
                frappe.log_error(f"Failed to update Google Event: {e}", "BC End Error")
        # ------------------------------

        return {"success": True}
    except Exception as e:
        frappe.log_error(traceback.format_exc(), "BC End Error")
        return {"success": False}

# ----------------------------------------------------------------------
# HISTORY
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str):
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    if clerk_id != userId:
        frappe.throw(_("Forbidden"), frappe.PermissionError)

    klient_name = get_klient_by_clerk_or_throw(userId)
    
    # Oprava filtra: Hľadáme podľa poľa 'klient', nie 'volajuci'
    calls = frappe.get_all(
        "Dennik hovorov",
        filters={"klient": klient_name},
        fields=["name", "poradca", "zaciatok_datum", "zaciatok_cas", "trvanie_s"],
        order_by="zaciatok_datum desc, zaciatok_cas desc",
        limit_page_length=20
    )
    return {"success": True, "calls": calls}
