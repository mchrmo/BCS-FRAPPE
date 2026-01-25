import math
import frappe
from frappe.utils import now_datetime, getdate, get_time
from datetime import datetime
from frappe import _

from .utils import (
    verify_clerk_bearer_and_get_sub,
    send_voip_push,
    get_actor_by_clerk_id,
    get_settings
)

# ---------------------------------------------------------------------
# POMOCNÉ FUNKCIE
# --------------------------------------------------------------------

def get_actor_name_and_type(clerk_id: str):
    doctype, doc = get_actor_by_clerk_id(clerk_id)
    if not doc:
        frappe.throw("Unknown user")
    return doc.name, doctype


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


@frappe.whitelist(methods=["POST"], allow_guest=True)
def start():
    # ------------------------------------------------------------------
    # 1. AUTH + INPUT
    # ------------------------------------------------------------------
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}

    caller_clerk = data.get("callerId")
    target_clerk = data.get("advisorId")  # NÁZOV OSTÁVA, ALE JE TO RECIPIENT

    frappe.log_error(
        f"AUTH clerk_id={clerk_id}\n"
        f"callerId={caller_clerk}\n"
        f"advisorId={target_clerk}\n"
        f"RAW DATA={data}",
        "CALL START DEBUG – INPUT"
    )

    if not caller_clerk or not target_clerk:
        frappe.throw("Missing callerId or advisorId")

    if clerk_id != caller_clerk:
        frappe.throw("Forbidden: you can only start calls as yourself", frappe.PermissionError)

    # ------------------------------------------------------------------
    # 2. LOOKUP ACTORS
    # ------------------------------------------------------------------
    caller_name, caller_type = get_actor_name_and_type(caller_clerk)
    target_name, target_type = get_actor_name_and_type(target_clerk)

    frappe.log_error(
        f"CALLER:\n"
        f"  clerk_id={caller_clerk}\n"
        f"  name={caller_name}\n"
        f"  type={caller_type}\n\n"
        f"RECIPIENT:\n"
        f"  clerk_id={target_clerk}\n"
        f"  name={target_name}\n"
        f"  type={target_type}",
        "CALL START DEBUG – ACTORS"
    )

    # ------------------------------------------------------------------
    # 3. TOKEN LOGIKA (len ak volá KLIENT v PIATOK)
    # ------------------------------------------------------------------
    now = now_datetime()
    used_token = None

    if is_friday(now) and caller_type == "Klient":
        used_token = pick_active_token_for_holder(caller_name)
        if not used_token:
            return {
                "success": False,
                "error": "V piatok je potrebný token. Nemáte dostupné minúty."
            }

    # ------------------------------------------------------------------
    # 4. CREATE CALL LOG
    # ------------------------------------------------------------------
    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,
        "poradca": target_name,  # historický názov poľa, ale je to recipient
        "zaciatok_datum": now.date(),
        "zaciatok_cas": now.strftime("%H:%M:%S"),
        "pouzity_token": used_token,
    })
    call.insert(ignore_permissions=True)

    # ------------------------------------------------------------------
    # 5. LOAD RECIPIENT DEVICE(S)
    # ------------------------------------------------------------------
    if target_type == "Poradca":
        recipient_doc = frappe.get_doc("Poradca", target_name)
    elif target_type == "Klient":
        recipient_doc = frappe.get_doc("Klient", target_name)
    else:
        frappe.throw("Unknown recipient type")

    device_rows = recipient_doc.get("zariadenie") or []

    frappe.log_error(
        f"PUSH TARGET:\n"
        f"  name={target_name}\n"
        f"  type={target_type}\n"
        f"  devices={len(device_rows)}",
        "CALL START DEBUG – DEVICES"
    )

    # ------------------------------------------------------------------
    # 6. SEND VOIP PUSH
    # ------------------------------------------------------------------
    sent = 0

    for row in device_rows:
        if not row.voip_token:
            continue

        send_voip_push(
            row.voip_token,
            {
                "aps": {"content-available": 1},
                "callId": call.name,
                "callerId": caller_clerk,
                "callerName": caller_name,
            }
        )
        sent += 1

    frappe.log_error(
        f"VOIP PUSH SENT: {sent}",
        "CALL START DEBUG – PUSH SENT"
    )

    # ------------------------------------------------------------------
    # 7. RESPONSE
    # ------------------------------------------------------------------
    return {
        "success": True,
        "callId": call.name,
        "recipientName": target_name,
        "recipientType": target_type,
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

    actor_name, actor_type = get_actor_name_and_type(clerk_id)
    if actor_type != "Poradca":
        frappe.throw("Only advisor can accept call")

    doc = frappe.get_doc("Dennik hovorov", call_id)

    if doc.poradca != actor_name:
        frappe.throw("Unauthorized", frappe.PermissionError)

    now = now_datetime()
    doc.prijaty = 1
    doc.prijaty_cas = now
    doc.save(ignore_permissions=True)

    return {"success": True, "callId": call_id}


# ----------------------------------------------------------------------
# END CALL
# ----------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def end():
    verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}
    call_id = data.get("callId")

    if not call_id:
        frappe.throw(_("Missing callId"))

    try:
        doc = frappe.get_doc("Dennik hovorov", call_id)
    except frappe.DoesNotExistError:
        frappe.throw(_("Hovor neexistuje"))

    now = now_datetime()

    # priamy zápis času
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
        frappe.log_error("Chyba výpočtu trvania", frappe.get_traceback())

    # TOKENY
    if doc.pouzity_token and getattr(doc, "prijaty", 0):
        try:
            mins = int(math.ceil(duration / 360.0)) * 6
            frappe.db.set_value("Dennik hovorov", call_id, "minuty_pouzite", mins)

            token_doc = frappe.get_doc("Token", doc.pouzity_token)
            rem = max(0, int(token_doc.minuty_ostavajuce or 0) - mins)

            token_doc.db_set("minuty_ostavajuce", rem)
            if rem <= 0:
                token_doc.db_set("stav", "spent")
        except Exception:
            frappe.log_error("Token error", frappe.get_traceback())

    frappe.db.commit()

    return {
        "success": True,
        "callId": call_id,
        "duration": duration,
        "end_time": now.strftime("%H:%M:%S")
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

    name, actor_type = get_actor_name_and_type(userId)

    if actor_type == "Poradca":
        filters = {"poradca": name}
    else:
        filters = {"volajuci": name}

    calls = frappe.get_all(
        "Dennik hovorov",
        filters=filters,
        fields=[
            "name",
            "volajuci",
            "poradca",
            "zaciatok_datum",
            "zaciatok_cas",
            "trvanie_s",
            "pouzity_token",
        ],
        order_by="zaciatok_datum desc, zaciatok_cas desc",
    )

    return {"success": True, "calls": calls}
