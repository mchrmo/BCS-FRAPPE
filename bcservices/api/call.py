import math
import traceback
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
    frappe.log_error("TEST LOG FUNGUJE", "BC DEBUG - TEST")
    return "OK, check error log"

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
    debug_id = frappe.generate_hash(length=4)
    log_tag = f"BC DEBUG [{debug_id}]"

    frappe.log_error("--- ŠTART VOLANIA ---", log_tag)

    try:
        # 1. Overenie identity cez Clerk
        auth_clerk_id, _ = verify_clerk_bearer_and_get_sub()
        
        data = frappe.local.form_dict or {}
        caller_clerk = data.get("callerId")
        advisor_clerk = data.get("advisorId")

        if not caller_clerk or not advisor_clerk:
            frappe.throw(_("Missing callerId or advisorId"))

        # 2. Získanie mien a správnych ID (Link validation fix)
        caller_name = frappe.db.get_value("Klient", {"clerk_id": caller_clerk}, "name")
        
        # TU JE OPRAVA: Musíme získať skutočné ID (napr. PRD-0001) pre Link pole
        advisor_id = frappe.db.get_value("Poradca", {"clerk_id": advisor_clerk}, "name")
        
        frappe.log_error(f"DB Lookup: Klient={caller_name}, Poradca_ID={advisor_id}", log_tag)

        if not advisor_id:
            frappe.log_error(f"Kritická chyba: Poradca s Clerk ID {advisor_clerk} neexistuje!", log_tag)
            frappe.throw(_("Advisor not found"))

        # 3. Načítanie zariadení poradcu
        advisor_doc = frappe.get_doc("Poradca", advisor_id)
        devices = advisor_doc.get("zariadenie") or advisor_doc.get("zariadenia") or []
        
        frappe.log_error(f"Počet zariadení pre push: {len(devices)}", log_tag)

        # 4. Zápis do Denníka hovorov (s ochranou proti pádu)
        call_name = "PENDING"
        try:
            now = now_datetime()
            call_doc = frappe.get_doc({
                "doctype": "Dennik hovorov",
                "volajuci": caller_name,
                "poradca": advisor_id,
                "zaciatok_datum": now.date(),
                "zaciatok_cas": now.strftime("%H:%M:%S"),
            })
            call_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            call_name = call_doc.name
            frappe.log_error(f"Záznam v Denníku vytvorený: {call_name}", log_tag)
        except Exception as db_err:
            # Ak zlyhá zápis do DB, zalogujeme to, ale necháme hovor pokračovať
            frappe.log_error(f"Chyba pri zápise do Denníka (Hovor pôjde bez záznamu): {str(db_err)}", log_tag)

        # 5. Odosielanie PUSH notifikácií
        # 5. Odosielanie PUSH notifikácií
        sent_count = 0
        for d in devices:
            token = getattr(d, "voip_token", None) or getattr(d, "voipToken", None)
            if token:
                try:
                    frappe.log_error(f"Odosielam VoIP push na: {token[:10]}...", log_tag)
                    
                    # TU JE ZMENA: Pridávame callerId, aby iOS kód nepadol na guard
                    payload = {
                        "callId": call_name,
                        "callerId": caller_clerk,  # Toto chýbalo v logoch iPhonu!
                        "callerName": caller_name or "Neznámy klient",
                        "title": "Prichádzajúci hovor"
                    }
                    
                    res = send_voip_push(token, payload)
                    if res:
                        sent_count += 1
                except Exception as p_err:
                    frappe.log_error(f"Push zlyhal pre token {token[:10]}: {str(p_err)}", log_tag)

        return {"success": True, "callId": call_name, "sent_to": sent_count}

    except Exception as e:
        frappe.log_error(f"KRITICKÁ CHYBA FUNKCIE START:\n{traceback.format_exc()}", log_tag)
        return {"success": False, "error": str(e)}


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
            return {"success": True, "note": "Call was not registered in DB"}

        doc = frappe.get_doc("Dennik hovorov", call_id)
        advisor_name = frappe.db.get_value("Poradca", {"clerk_id": clerk_id}, "name")

        if doc.poradca != advisor_name:
            frappe.throw("Unauthorized", frappe.PermissionError)

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

        doc = frappe.get_doc("Dennik hovorov", call_id)
        now = now_datetime()

        frappe.db.set_value("Dennik hovorov", call_id, {
            "koniec_datum": now.date(),
            "koniec_cas": now.strftime("%H:%M:%S")
        })

        # Výpočet trvania
        try:
            start_dt = datetime.combine(getdate(doc.zaciatok_datum), get_time(doc.zaciatok_cas))
            duration = max(0, int((now - start_dt).total_seconds()))
            frappe.db.set_value("Dennik hovorov", call_id, "trvanie_s", duration)
        except:
            pass

        frappe.db.commit()
        return {"success": True}
    except Exception as e:
        frappe.log_error(traceback.format_exc(), "BC End Error")
        return {"success": False}

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
        fields=["name", "poradca", "zaciatok_datum", "zaciatok_cas", "trvanie_s"],
        order_by="zaciatok_datum desc, zaciatok_cas desc",
        limit_page_length=20
    )
    return {"success": True, "calls": calls}
