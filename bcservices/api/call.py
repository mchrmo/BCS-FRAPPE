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
# START CALL (Obojstranný)
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    debug_id = frappe.generate_hash(length=4)
    log_tag = f"BC DEBUG [{debug_id}]"
    data = frappe.local.form_dict or {}
    
    c1_id = data.get("callerId")
    c2_id = data.get("advisorId")

    frappe.log_error(f"--- ŠTART --- ID1: {c1_id}, ID2: {c2_id}", log_tag)

    try:
        # 1. Overenie kto volá (cez token)
        auth_clerk_id, _ = verify_clerk_bearer_and_get_sub()

        # 2. Musíme nájsť, kto je kto v našej DB bez ohľadu na to, čo poslal mobil
        # Skúsime nájsť oboch v oboch tabuľkách
        p1_klient = frappe.db.get_value("Klient", {"clerk_id": c1_id}, "name")
        p1_poradca = frappe.db.get_value("Poradca", {"clerk_id": c1_id}, "name")
        
        p2_klient = frappe.db.get_value("Klient", {"clerk_id": c2_id}, "name")
        p2_poradca = frappe.db.get_value("Poradca", {"clerk_id": c2_id}, "name")

        # Určíme, kto je reálny KLIENT a kto PORADCA pre tento hovor
        real_klient = p1_klient or p2_klient
        real_poradca = p1_poradca or p2_poradca

        if not real_klient or not real_poradca:
            frappe.log_error(f"Nenájdená dvojica! Klient: {real_klient}, Poradca: {real_poradca}", log_tag)
            return {"success": False, "error": "Participants mismatch"}

        # 3. Kto má dostať PUSH? (Ten, kto teraz NEVOLÁ)
        if auth_clerk_id == c1_id:
            # Volá ID1, push dostane ID2
            target_doctype = "Poradca" if p2_poradca else "Klient"
            target_id = p2_poradca or p2_klient
            display_name = p1_poradca or p1_klient
        else:
            # Volá ID2, push dostane ID1
            target_doctype = "Poradca" if p1_poradca else "Klient"
            target_id = p1_poradca or p1_klient
            display_name = p2_poradca or p2_klient

        # 4. Zápis hovoru a PUSH (zvyšok ostáva rovnaký)
        now = now_datetime()
        call_doc = frappe.get_doc({
            "doctype": "Dennik hovorov",
            "volajuci": real_klient,
            "poradca": real_poradca,
            "zaciatok_datum": now.date(),
            "zaciatok_cas": now.strftime("%H:%M:%S"),
        })
        call_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        target_doc = frappe.get_doc(target_doctype, target_id)
        devices = target_doc.get("zariadenie") or []
        sent_count = 0
        for d in devices:
            token = getattr(d, "voip_token", None) or getattr(d, "voipToken", None)
            if token and send_voip_push(token, {"callId": call_doc.name, "callerName": display_name}):
                sent_count += 1

        return {"success": True, "callId": call_doc.name, "sent_to": sent_count}

    except Exception:
        frappe.log_error(traceback.format_exc(), log_tag)
        return {"success": False, "error": "Error"}

# ----------------------------------------------------------------------
# ACCEPT CALL (Opravená autorizácia)
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
        # Hľadáme meno v oboch tabuľkách podľa clerk_id
        is_valid = False
        klient_name = frappe.db.get_value("Klient", {"clerk_id": clerk_id}, "name")
        advisor_name = frappe.db.get_value("Poradca", {"clerk_id": clerk_id}, "name")

        if (klient_name and doc.volajuci == klient_name) or (advisor_name and doc.poradca == advisor_name):
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
# END CALL & HISTORY (Ponechané bez zmeny)
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

        # Použijeme frappe.db.set_value pre rýchlosť a obídenie validácií
        frappe.db.set_value("Dennik hovorov", call_id, {
            "koniec_datum": now.date(),
            "koniec_cas": now.strftime("%H:%M:%S")
        })

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

@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str):
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    if clerk_id != userId:
        frappe.throw(_("Forbidden"), frappe.PermissionError)

    klient_name = get_klient_by_clerk_or_throw(userId)
    calls = frappe.get_all(
        "Dennik hovorov",
        filters={"volajuci": klient_name},
        fields=["name", "poradca", "zaciatok_datum", "zaciatok_cas", "trvanie_s"],
        order_by="zaciatok_datum desc, zaciatok_cas desc",
        limit_page_length=20
    )
    return {"success": True, "calls": calls}
