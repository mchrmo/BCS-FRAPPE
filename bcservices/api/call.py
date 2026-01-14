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
@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    # Overenie Clerk JWT (caller musí byť prihlásený)
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller_clerk = data.get("callerId")
    advisor_clerk = data.get("advisorId")

    if not caller_clerk or not advisor_clerk:
        frappe.throw("Missing callerId or advisorId")

    # Bezpečnosť: user môže štartovať call iba za seba (alebo admin)
    if clerk_id != caller_clerk and clerk_id != ADMIN_CLERK_ID:
        frappe.throw("Forbidden", frappe.PermissionError)

    # Ak iOS pošle "admin", namapujeme ho na reálne Clerk ID
    if advisor_clerk == "admin":
        advisor_clerk = ADMIN_CLERK_ID

    # Lookup Klient.name
    caller_name = get_klient_name_from_clerk(caller_clerk)
    advisor_name = get_klient_name_from_clerk(advisor_clerk)

    if not caller_name:
        frappe.throw(
            f"Could not find caller in Klient: {caller_clerk}",
            frappe.LinkValidationError,
        )

    if not advisor_name:
        frappe.throw(
            f"Could not find advisor in Klient: {advisor_clerk}",
            frappe.LinkValidationError,
        )

    now = now_datetime()

    # --------------------------------------------------
    # TOKEN LOGIKA
    # --------------------------------------------------
    token_required = is_friday(now) and caller_clerk != ADMIN_CLERK_ID
    used_token = None

    if token_required:
        used_token = pick_active_token_for_holder(caller_name)
        if not used_token:
            return {
                "success": False,
                "error": (
                    "V piatok je na hovor potrebný token (minúty). "
                    "Nemáš žiadne zostávajúce minúty."
                ),
            }

    # --------------------------------------------------
    # VYTVORENIE HOVORU
    # --------------------------------------------------
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,
        "poradca": advisor_name,
        "zaciatok_datum": now.date(),
        "zaciatok_cas": now.time().strftime("%H:%M:%S"),
        "pouzity_token": used_token,
    })
    call.insert(ignore_permissions=True)
    # --------------------------------------------------
    # NÁJDEME ZARIADENIA PORADCU
    # --------------------------------------------------
    devices = frappe.get_all(
        "Zariadenie",
        filters={"parent": advisor_name},
        fields=["voip_token"],
        limit_page_length=20,
    )

    # --------------------------------------------------
    # VOIP PUSH NOTIFIKÁCIE
    # --------------------------------------------------
    for device in devices:
        token = device.get("voip_token")
        if not token:
            continue

        try:
            send_voip_push(
                token,
                {
                    "callId": call.name,
                    "callerId": caller_clerk,
                    "callerName": caller_name,
                    "title": "Prichádzajúci hovor",
                    "body": f"Volá {caller_name}",
                },
            )
        except Exception as e:
            frappe.log_error(
                f"VoIP push failed for device {token}: {e}",
                "BC VoIP Error",
            )

    return {
        "success": True,
        "callId": call.name,
        "tokenUsed": used_token,
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
# ----------------------------------------------------------------------
# END CALL
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# END CALL
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def end():
    import math
    import frappe
    from frappe.utils import now_datetime, getdate, get_time
    from datetime import datetime

    # --------------------------------------------------
    # AUTH
    # --------------------------------------------------
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}

    call_id = data.get("callId")
    if not call_id:
        frappe.throw("Missing callId")

    doc = frappe.get_doc("Dennik hovorov", call_id)
    now = now_datetime()

    # --------------------------------------------------
    # UKONČENIE HOVORU
    # --------------------------------------------------
    doc.koniec_datum = now.date()
    doc.koniec_cas = now.time().strftime("%H:%M:%S")

    # --------------------------------------------------
    # VÝPOČET TRVANIA
    # --------------------------------------------------
    try:
        start_dt = datetime.combine(
            getdate(doc.zaciatok_datum),
            get_time(doc.zaciatok_cas),
        )
        end_dt = datetime.combine(
            getdate(doc.koniec_datum),
            get_time(doc.koniec_cas),
        )

        doc.trvanie_s = max(0, int((end_dt - start_dt).total_seconds()))
    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "BC CALL DURATION ERROR",
        )
        doc.trvanie_s = doc.trvanie_s or 0

    # --------------------------------------------------
    # ODRÁTANIE TOKENU (IDEMPOTENTNE)
    # --------------------------------------------------
    try:
        should_deduct = (
            bool(getattr(doc, "pouzity_token", None))
            and (doc.trvanie_s or 0) > 0
        )

        # iba ak bol prijatý
        if hasattr(doc, "prijaty") and not getattr(doc, "prijaty"):
            should_deduct = False

        # idempotencia
        if hasattr(doc, "minuty_pouzite") and (doc.minuty_pouzite or 0) > 0:
            should_deduct = False

        if should_deduct:
            minutes_used = int(
                math.ceil((doc.trvanie_s or 0) / 360.0)
            ) * 6

            if hasattr(doc, "minuty_pouzite"):
                doc.minuty_pouzite = minutes_used

            token_doc = frappe.get_doc("Token", doc.pouzity_token)

            remaining = int(token_doc.minuty_ostavajuce or 0)
            remaining_after = max(0, remaining - minutes_used)

            token_doc.minuty_ostavajuce = remaining_after
            token_doc.stav = "spent" if remaining_after == 0 else "active"

            token_doc.save(ignore_permissions=True)

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "BC TOKEN DEDUCT ERROR",
        )

    # --------------------------------------------------
    # GOOGLE CALENDAR – VYTVORENIE EVENTU
    # --------------------------------------------------
    try:
        frappe.log_error(
            f"[CALENDAR CHECK] token={doc.pouzity_token}, trvanie={doc.trvanie_s}",
            "DEBUG CALENDAR PRECHECK",
        )

        if not doc.pouzity_token and (doc.trvanie_s or 0) > 0:
            znacka_klienta = frappe.db.get_value(
                "Klient",
                doc.volajuci,
                "znacka_klienta",
            )

            frappe.log_error(
                f"[CALENDAR CHECK] znacka_klienta={znacka_klienta}",
                "DEBUG CALENDAR BRAND",
            )

            if znacka_klienta:
                from bcservices.api.google_calendar import (
                    create_call_event_from_end,
                )

                event_id = create_call_event_from_end(
                    call_doc=doc,
                    znacka_klienta=znacka_klienta,
                )

                if hasattr(doc, "google_event_id"):
                    doc.google_event_id = event_id

                frappe.log_error(
                    f"[CALENDAR CREATED] event_id={event_id}",
                    "DEBUG CALENDAR SUCCESS",
                )

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "GOOGLE CALENDAR ERROR",
        )

    # --------------------------------------------------
    # SAVE
    # --------------------------------------------------
    doc.save(ignore_permissions=True)

    return {
        "success": True,
        "callId": call_id,
        "duration_s": doc.trvanie_s,
        "token": doc.pouzity_token,
        "minutes_deducted": getattr(doc, "minuty_pouzite", None),
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
