# apps/bcservices/bcservices/api/call.py

import math
import frappe
from frappe.utils import now_datetime
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
    return dt.weekday() == 1


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

    # Ak iOS posiela "admin", namapujeme ho na reálne Clerk ID
    if advisor_clerk == "admin":
        advisor_clerk = ADMIN_CLERK_ID

    # Lookup Klient.name
    caller_name = get_klient_name_from_clerk(caller_clerk)
    advisor_name = get_klient_name_from_clerk(advisor_clerk)

    if not caller_name:
        frappe.throw(
            f"Could not find caller in Klient: {caller_clerk}",
            frappe.LinkValidationError
        )

    if not advisor_name:
        frappe.throw(
            f"Could not find advisor in Klient: {advisor_clerk}",
            frappe.LinkValidationError
        )

    now = now_datetime()

    # Token sa vyžaduje len v piatok a len keď volá klient (nie admin)
    token_required = is_friday(now) and caller_clerk != ADMIN_CLERK_ID

    used_token = None
    if token_required:
        used_token = pick_active_token_for_holder(caller_name)
        if not used_token:
            # Vraciame "success": False aby iOS vedel zobraziť hlášku
            return {
                "success": False,
                "error": "V piatok je na hovor potrebný token (minúty). Nemáš žiadne zostávajúce minúty."
            }

    # Vytvor nový hovor (zapíš token len ak bol potrebný a nájdený)
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,
        "poradca": advisor_name,
        "zaciatok_datum": now.date(),
        "zaciatok_cas": now.time().strftime("%H:%M:%S"),
        "pouzity_token": used_token,  # môže byť None
    })
    call.insert(ignore_permissions=True)

    # Nájdeme všetky zariadenia poradcu (multi-device)
    devices = frappe.get_all(
        "Zariadenie",
        filters={"parent": advisor_name},
        fields=["voip_token"],
        limit_page_length=20,
    )

    # Username podľa Doctype Klient
    caller_username = frappe.db.get_value(
        "Klient",
        {"clerk_id": caller_clerk},
        "username"
    )

    # Pošleme VoIP push na všetky zariadenia poradcu
    for d in devices:
        token = d.get("voip_token")
        if not token:
            continue

        try:
            send_voip_push(
                token,
                {
                    "callId": call.name,
                    "callerId": caller_clerk,
                    "callerName": caller_username or caller_clerk,
                    "title": "Prichádzajúci hovor",
                    "body": f"Volá {caller_username or caller_clerk}",
                }
            )
        except Exception as e:
            frappe.log_error(
                f"VoIP push failed for device {token}: {e}",
                "BC VoIP Error"
            )

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
@frappe.whitelist(methods=["POST"], allow_guest=True)
def end():
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}

    call_id = data.get("callId")
    if not call_id:
        frappe.throw("Missing callId")

    doc = frappe.get_doc("Dennik hovorov", call_id)
    now = now_datetime()

    # Ulož ukončenie hovoru
    doc.koniec_datum = now.date()
    doc.koniec_cas = now.time().strftime("%H:%M:%S")

    # Výpočet trvania (sekundy)
    try:
        start_dt = datetime.combine(
            doc.zaciatok_datum,
            datetime.strptime(doc.zaciatok_cas, "%H:%M:%S").time()
        )
        end_dt = datetime.combine(
            doc.koniec_datum,
            datetime.strptime(doc.koniec_cas, "%H:%M:%S").time()
        )
        doc.trvanie_s = max(0, int((end_dt - start_dt).total_seconds()))
    except Exception as e:
        frappe.log_error(f"Duration calc error: {e}", "BC Call Duration Error")

    # --- ODRÁTANIE MINÚT Z TOKENU (len ak sa použil token) ---
    try:
        should_deduct = bool(getattr(doc, "pouzity_token", None)) and (doc.trvanie_s or 0) > 0

        # ak máš field "prijaty", tak odrátaj iba ak bol prijatý
        if hasattr(doc, "prijaty") and not getattr(doc, "prijaty"):
            should_deduct = False

        # idempotencia: ak máš field minuty_pouzite a už je vyplnený, neodrátavaj znova
        if hasattr(doc, "minuty_pouzite") and (getattr(doc, "minuty_pouzite") or 0) > 0:
            should_deduct = False

        if should_deduct:
            minutes_used = int(math.ceil((doc.trvanie_s or 0) / 60.0))

            # zapíš minuty_pouzite ak existuje
            if hasattr(doc, "minuty_pouzite"):
                doc.minuty_pouzite = minutes_used

            token_doc = frappe.get_doc("Token", doc.pouzity_token)

            remaining = int(token_doc.minuty_ostavajuce or 0)
            remaining_after = max(0, remaining - minutes_used)
            token_doc.minuty_ostavajuce = remaining_after

            # tvoje options: active / listed / spent
            if remaining_after == 0:
                token_doc.stav = "spent"
            else:
                # ak bol active, nechaj active; ak bol listed (marketplace), je na tebe,
                # ale pre istotu keď sa používa, dávam active
                token_doc.stav = "active"

            token_doc.save(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(f"Token deduct error: {e}", "BC Token Deduct Error")

    doc.save(ignore_permissions=True)
    return {"success": True, "callId": call_id}


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
