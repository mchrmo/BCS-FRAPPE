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
    frappe.log_error("--- ŠTART VOLANIA (OBOJSTRANNÝ) ---", log_tag)

    try:
        # 1. Kto volá? (Overenie cez Clerk)
        auth_clerk_id, _ = verify_clerk_bearer_and_get_sub()
        
        data = frappe.local.form_dict or {}
        caller_clerk = data.get("callerId")
        advisor_clerk = data.get("advisorId")

        if not caller_clerk or not advisor_clerk:
            frappe.throw(_("Missing callerId or advisorId"))

        # 2. Identifikácia oboch strán
        # Zistíme meno klienta a ID poradcu
        klient_id = frappe.db.get_value("Klient", {"clerk_id": caller_clerk}, "name")
        advisor_id = frappe.db.get_value("Poradca", {"clerk_id": advisor_clerk}, "name")

        if not klient_id or not advisor_id:
            frappe.log_error(f"Chýba záznam v DB: Klient={klient_id}, Poradca={advisor_id}", log_tag)
            frappe.throw(_("Participant not found in database"))

        # 3. Kto je prijímateľ? (Kto má dostať PUSH?)
        # Ak auth_clerk_id je volajúci, push ide poradcovi. Ak je to poradca, push ide klientovi.
        if auth_clerk_id == caller_clerk:
            target_doctype = "Poradca"
            target_id = advisor_id
            display_name = frappe.db.get_value("Klient", klient_id, "username") or klient_id
            frappe.log_error(f"Smer: Klient -> Poradca ({target_id})", log_tag)
        else:
            target_doctype = "Klient"
            target_id = klient_id
            display_name = frappe.db.get_value("Poradca", advisor_id, "name") # Alebo iné pole pre meno
            frappe.log_error(f"Smer: Poradca -> Klient ({target_id})", log_tag)

        # 4. Zápis do Denníka hovorov
        call_name = "PENDING"
        try:
            now = now_datetime()
            call_doc = frappe.get_doc({
                "doctype": "Dennik hovorov",
                "volajuci": klient_id,
                "poradca": advisor_id,
                "zaciatok_datum": now.date(),
                "zaciatok_cas": now.strftime("%H:%M:%S"),
            })
            call_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            call_name = call_doc.name
        except Exception as db_err:
            frappe.log_error(f"DB Error: {str(db_err)}", log_tag)

        # 5. Načítanie zariadení prijímateľa (Target)
        target_doc = frappe.get_doc(target_doctype, target_id)
        devices = target_doc.get("zariadenie") or []
        
        # 6. Odoslanie PUSH
        sent_count = 0
        for d in devices:
            token = getattr(d, "voip_token", None) or getattr(d, "voipToken", None)
            if token:
                payload = {
                    "callId": call_name,
                    "callerId": auth_clerk_id,
                    "callerName": display_name,
                    "title": "Prichádzajúci hovor"
                }
                if send_voip_push(token, payload):
                    sent_count += 1

        return {"success": True, "callId": call_name, "sent_to": sent_count}

    except Exception as e:
        frappe.log_error(f"Kritická chyba: {traceback.format_exc()}", log_tag)
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
