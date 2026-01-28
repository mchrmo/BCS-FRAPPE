import math
import traceback
import frappe
from frappe.utils import now_datetime, getdate, get_time
from datetime import datetime
from frappe import _

# Importujeme utils, ale v start() skúsime import znova pre istotu debugovania
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
# START CALL (EXTRÉMNE LOGOVANIE)
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    # Unikátne ID logu pre tento request, aby sme sa v tom vyznali
    debug_id = frappe.generate_hash(length=4)
    log_tag = f"BC DEBUG [{debug_id}]"

    frappe.log_error("--- 1. ZAČIATOK FUNKCIE START ---", log_tag)

    try:
        # 1. Overenie tokenu
        auth_clerk_id, _ = verify_clerk_bearer_and_get_sub()
        frappe.log_error(f"Auth OK: {auth_clerk_id}", log_tag)

        data = frappe.local.form_dict or {}
        caller_clerk = data.get("callerId")
        advisor_clerk = data.get("advisorId")
        frappe.log_error(f"Vstupné dáta: Caller={caller_clerk}, Advisor={advisor_clerk}", log_tag)

        if not caller_clerk or not advisor_clerk:
            frappe.log_error("Chýbajúce ID", log_tag)
            frappe.throw(_("Missing callerId or advisorId"))

        # 2. DB Lookups
        frappe.log_error("Hľadám mená v DB...", log_tag)
        caller_name = frappe.db.get_value("Klient", {"clerk_id": caller_clerk}, "name")
        advisor_name = frappe.db.get_value("Poradca", {"clerk_id": advisor_clerk}, "name")
        
        frappe.log_error(f"Nájdené mená: Klient='{caller_name}', Poradca='{advisor_name}'", log_tag)

        if not advisor_name:
            frappe.log_error("Poradca nenájdený -> Koniec", log_tag)
            frappe.throw(_("Advisor not found"))

        # 3. Načítanie zariadení
        frappe.log_error(f"Načítavam dokument Poradca: {advisor_name}", log_tag)
        advisor_doc = frappe.get_doc("Poradca", advisor_name)
        
        frappe.log_error("Dokument načítaný. Hľadám child table 'zariadenie'...", log_tag)
        
        # Skúsime získať zariadenia a zalogovať presne čo to je
        devices = advisor_doc.get("zariadenie")
        frappe.log_error(f"Raw devices: {type(devices)}, Hodnota: {devices}", log_tag)
        
        if not devices:
            # Fallback ak sa tabuľka volá inak
            frappe.log_error("Skúšam alternatívny názov 'zariadenia'...", log_tag)
            devices = advisor_doc.get("zariadenia") or []

        frappe.log_error(f"Finálny počet zariadení na spracovanie: {len(devices)}", log_tag)

        # 4. Vytvorenie záznamu hovoru
        now = now_datetime()
        frappe.log_error("Vytváram Denník hovorov...", log_tag)
        
        call = frappe.get_doc({
            "doctype": "Dennik hovorov",
            "volajuci": caller_name,
            "poradca": advisor_name,
            "zaciatok_datum": now.date(),
            "zaciatok_cas": now.strftime("%H:%M:%S"),
        })
        call.insert(ignore_permissions=True)
        frappe.db.commit()
        
        frappe.log_error(f"Hovor vytvorený, ID: {call.name}", log_tag)

        # 5. Odosielanie PUSH (LOOP)
        sent_count = 0
        frappe.log_error("Vstupujem do cyklu zariadení...", log_tag)

        for i, d in enumerate(devices):
            try:
                frappe.log_error(f"--- Zariadenie #{i} ---", log_tag)
                
                # Extrakcia tokenu
                token = getattr(d, "voip_token", None)
                if not token:
                    frappe.log_error("Atribút 'voip_token' je prázdny, skúšam 'voipToken'", log_tag)
                    token = getattr(d, "voipToken", None)
                
                frappe.log_error(f"Token pre zariadenie #{i}: {str(token)[:15]}...", log_tag)

                if token:
                    # Payload
                    payload = {
                        "callId": call.name,
                        "callerName": caller_name,
                        "title": "Prichádzajúci hovor"
                    }
                    frappe.log_error("Payload pripravený. Volám send_voip_push...", log_tag)
                    
                    # VOLANIE PUSH
                    # Tu to často padá, takže obalíme extra try-exceptom pre istotu
                    try:
                        from .utils import send_voip_push # Lokálny import na overenie
                        res = send_voip_push(token, payload)
                        frappe.log_error(f"Výsledok send_voip_push: {res}", log_tag)
                        
                        if res:
                            sent_count += 1
                            frappe.log_error("Push označený ako úspešný.", log_tag)
                    except Exception as inner_e:
                        frappe.log_error(f"!!! CHYBA PRIAMO PRI VOLANÍ FUNKCIE PUSH: {str(inner_e)}", log_tag)
                        frappe.log_error(traceback.format_exc(), log_tag)

                else:
                    frappe.log_error("Preskakujem (žiadny token)", log_tag)

            except Exception as loop_e:
                frappe.log_error(f"Chyba vo vnútri cyklu zariadenia #{i}: {str(loop_e)}", log_tag)

        frappe.log_error(f"Koniec funkcie. Odoslané na {sent_count} zariadení.", log_tag)
        return {"success": True, "callId": call.name, "sent_to": sent_count}

    except Exception as e:
        # Hlavný catch pre celú funkciu
        frappe.log_error(f"!!! KRITICKÝ PÁD CELEJ FUNKCIE START: {str(e)}", log_tag)
        frappe.log_error(traceback.format_exc(), log_tag)
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

        if not call_id:
            frappe.throw("Missing callId")

        doc = frappe.get_doc("Dennik hovorov", call_id)
        
        advisor_name = frappe.db.get_value("Poradca", {"clerk_id": clerk_id}, "name")

        if doc.poradca != advisor_name:
            frappe.throw("Unauthorized", frappe.PermissionError)

        now = now_datetime()
        doc.prijaty = 1
        doc.prijaty_cas = now
        doc.save(ignore_permissions=True)

        return {"success": True, "callId": call_id}
    except Exception as e:
        frappe.log_error(traceback.format_exc(), "BC Accept Error")
        raise e


# ----------------------------------------------------------------------
# END CALL
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def end():
    try:
        clerk_id, _ = verify_clerk_bearer_and_get_sub()
        data = frappe.local.form_dict or {}
        call_id = data.get("callId")

        if not call_id:
            frappe.throw(_("Missing callId"))

        doc = frappe.get_doc("Dennik hovorov", call_id)
        now = now_datetime()

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
        }
    except Exception as e:
        frappe.log_error(traceback.format_exc(), "BC End Error")
        raise e

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
