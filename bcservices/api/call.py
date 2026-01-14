# apps/bcservices/bcservices/api/call.py

import math
import frappe
from frappe.utils import now_datetime, getdate, get_time
from datetime import datetime


from .utils import verify_clerk_bearer_and_get_sub, send_voip_push


# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
ADMIN_CLERK_ID = "user_30p94nuw9O2UHOEsXmDhV2SgP8N"  # tvoj admin Clerk ID


# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def get_klient_name_from_clerk(clerk_id: str | None):
    if not clerk_id:
        return None
    return frappe.db.get_value("Klient", {"clerk_id": clerk_id}, "name")


def is_friday(dt) -> bool:
    # Python: Monday=0 ... Sunday=6
    return dt.weekday() == 4


def pick_active_token_for_holder(klient_name: str) -> str | None:
    """
    Vyberie 1 token pre klienta, ktorý je:
      - aktualny_drzitel = klient_name
      - stav = "active"
      - minuty_ostavajuce > 0
    Vracia Token.name alebo None.
    """
    rows = frappe.get_all(
        "Token",
        filters={
            "aktualny_drzitel": klient_name,
            "stav": "active",
            "minuty_ostavajuce": [">", 0],
        },
        fields=["name", "minuty_ostavajuce", "modified"],
        order_by="modified asc",
        limit_page_length=1,
    )
    if not rows:
        return None
    return rows[0]["name"]


# ----------------------------------------------------------------------
# START CALL
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# START CALL
# ----------------------------------------------------------------------
import frappe
from frappe.utils import now_datetime
from frappe import _

ADMIN_CLERK_ID = "ADMIN_CLERK_ID_HERE"


@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    # 1. AUTENTIFIKÁCIA
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller_clerk = data.get("callerId")
    advisor_clerk = data.get("advisorId")

    if not caller_clerk or not advisor_clerk:
        frappe.throw(_("Missing callerId or advisorId"))

    # Bezpečnosť: užívateľ volá za seba alebo je to admin
    if clerk_id != caller_clerk and clerk_id != ADMIN_CLERK_ID:
        frappe.throw(_("Forbidden"), frappe.PermissionError)

    if advisor_clerk == "admin":
        advisor_clerk = ADMIN_CLERK_ID

    # 2. ZÍSKANIE MIEN (Prepojenie Clerk ID -> Frappe Klient Name)
    caller_name = get_klient_name_from_clerk(caller_clerk)
    advisor_name = get_klient_name_from_clerk(advisor_clerk)

    if not caller_name or not advisor_name:
        frappe.throw(_("Could not find caller or advisor in Klient database"))

    # 3. NAČÍTANIE DOPLNKOVÝCH DÁT (Značka a Username)
    # Tu vyťahujeme pole 'znacka_klienta', ktoré rozhoduje o kalendári
    klient_info = frappe.db.get_value(
        "Klient", 
        {"clerk_id": caller_clerk}, 
        ["username", "znacka_klienta"], 
        as_dict=True
    )
    
    znacka = klient_info.get("znacka_klienta") if klient_info else None
    caller_username = klient_info.get("username") if klient_info else None

    now = now_datetime()

    # 4. TOKEN LOGIKA (Len v piatok)
    token_required = is_friday(now) and caller_clerk != ADMIN_CLERK_ID
    used_token = None

    if token_required:
        used_token = pick_active_token_for_holder(caller_name)
        if not used_token:
            return {
                "success": False,
                "error": "V piatok je potrebný token. Nemáte minúty."
            }

    # 5. ZÁPIS DO DATABÁZY (Denník hovorov)
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,
        "poradca": advisor_name,
        "zaciatok_datum": now.date(),
        "zaciatok_cas": now.time().strftime("%H:%M:%S"),
        "pouzity_token": used_token,
    })
    call.insert(ignore_permissions=True)

    # 6. GOOGLE CALENDAR LOGIKA (Nová úprava)
    # Podmienka: Ak nie je token (v piatok) A ZÁROVEŇ existuje 'znacka'
    if not used_token and znacka:
        try:
            from .google_calendar import create_call_event
            
            # Posielame 'znacka' ako názov udalosti
            event_id = create_call_event(call, znacka)
            
            if event_id:
                call.google_event_id = event_id
                call.save(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Google Calendar Error")

    # 7. VOIP PUSH NOTIFIKÁCIE
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

    return {
        "success": True, 
        "callId": call.name, 
        "tokenUsed": used_token
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

    advisor_name = get_klient_name_from_clerk(clerk_id)
    if doc.poradca != advisor_name:
        frappe.throw("You cannot accept someone else's call", frappe.PermissionError)

    # Označ, že hovor bol prijatý (ak field existuje)
    now = now_datetime()
    if hasattr(doc, "prijaty"):
        doc.prijaty = 1
    if hasattr(doc, "prijaty_cas"):
        doc.prijaty_cas = now

    doc.save(ignore_permissions=True)
    return {"success": True, "callId": call_id}

# ----------------------------------------------------------------------
# END CALL
# ----------------------------------------------------------------------
import math
import frappe
from frappe.utils import now_datetime, getdate, get_time
from datetime import datetime


@frappe.whitelist(methods=["POST"], allow_guest=True)
def end():
    # --------------------------------------------------
    # Overenie Clerk JWT
    # --------------------------------------------------
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    call_id = data.get("callId")

    if not call_id:
        frappe.throw("Missing callId")

    # --------------------------------------------------
    # Načítanie hovoru
    # --------------------------------------------------
    doc = frappe.get_doc("Dennik hovorov", call_id)

    now = now_datetime()

    # --------------------------------------------------
    # Uloženie ukončenia hovoru
    # --------------------------------------------------
    doc.koniec_datum = now.date()
    doc.koniec_cas = now.time().strftime("%H:%M:%S")

    # --------------------------------------------------
    # Robustný výpočet trvania (string / time safe)
    # --------------------------------------------------
    try:
        start_date = getdate(doc.zaciatok_datum)
        start_time = get_time(doc.zaciatok_cas)

        end_date = getdate(doc.koniec_datum)
        end_time = get_time(doc.koniec_cas)

        start_dt = datetime.combine(start_date, start_time)
        end_dt = datetime.combine(end_date, end_time)

        doc.trvanie_s = max(0, int((end_dt - start_dt).total_seconds()))

    except Exception as e:
        frappe.log_error(
            f"Duration calc error: {e}",
            "BC Call Duration Error",
        )
        doc.trvanie_s = doc.trvanie_s or 0

    # --------------------------------------------------
    # ODRÁTANIE MINÚT Z TOKENU (len ak sa použil)
    # --------------------------------------------------
    try:
        should_deduct = (
            bool(getattr(doc, "pouzity_token", None))
            and (doc.trvanie_s or 0) > 0
        )

        # Ak máš field "prijaty", odrátaj len ak bol prijatý
        if hasattr(doc, "prijaty") and not getattr(doc, "prijaty"):
            should_deduct = False

        # Idempotencia – ak už boli minúty odrátané
        if (
            hasattr(doc, "minuty_pouzite")
            and (getattr(doc, "minuty_pouzite") or 0) > 0
        ):
            should_deduct = False

        if should_deduct:
            # Každých začatých 6 minút = celý 6-min blok
            minutes_used = (
                int(math.ceil((doc.trvanie_s or 0) / 360.0)) * 6
            )

            if hasattr(doc, "minuty_pouzite"):
                doc.minuty_pouzite = minutes_used

            token_doc = frappe.get_doc("Token", doc.pouzity_token)

            remaining = int(token_doc.minuty_ostavajuce or 0)
            remaining_after = max(0, remaining - minutes_used)

            token_doc.minuty_ostavajuce = remaining_after
            token_doc.stav = (
                "spent" if remaining_after == 0 else "active"
            )

            token_doc.save(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(
            f"Token deduct error: {e}",
            "BC Token Deduct Error",
        )

    # --------------------------------------------------
    # Uloženie hovoru
    # --------------------------------------------------
    doc.save(ignore_permissions=True)

    return {
        "success": True,
        "callId": call_id,
        "duration_s": doc.trvanie_s,
        "token": getattr(doc, "pouzity_token", None),
        "minutes_deducted": (
            getattr(doc, "minuty_pouzite", None)
            if hasattr(doc, "minuty_pouzite")
            else None
        ),
    }




# ----------------------------------------------------------------------
# CALL HISTORY
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str):
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    if clerk_id != userId:
        frappe.throw("Forbidden", frappe.PermissionError)

    klient_name = get_klient_name_from_clerk(userId)

    calls = frappe.get_all(
        "Dennik hovorov",
        filters={"volajuci": klient_name},
        fields=[
            "name",
            "poradca",
            "zaciatok_datum",
            "zaciatok_cas",
            "koniec_datum",
            "koniec_cas",
            "trvanie_s",
            "pouzity_token",
        ],
        order_by="zaciatok_datum desc, zaciatok_cas desc",
    )

    return {"success": True, "calls": calls}
