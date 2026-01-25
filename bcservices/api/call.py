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
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict or {}
    caller_clerk = data.get("callerId")
    advisor_clerk = data.get("advisorId")

    frappe.log_error(
        title="CALL START DEBUG – INPUT",
        message=f"""
AUTH clerk_id: {clerk_id}
callerId: {caller_clerk}
advisorId: {advisor_clerk}
RAW DATA: {data}
"""
    )

    if not caller_clerk or not advisor_clerk:
        frappe.throw("Missing callerId or advisorId")

    if clerk_id != caller_clerk:
        frappe.throw("Forbidden")

    # ---- ACTORS ----
    caller_name, caller_type = get_actor_name_and_type(caller_clerk)
    advisor_name, advisor_type = get_actor_name_and_type(advisor_clerk)

    frappe.log_error(
        title="CALL START DEBUG – ACTORS",
        message=f"""
CALLER:
  clerk_id={caller_clerk}
  name={caller_name}
  type={caller_type}

ADVISOR:
  clerk_id={advisor_clerk}
  name={advisor_name}
  type={advisor_type}
"""
    )

    if advisor_type != "Poradca":
        frappe.throw("Target is not Poradca")

    now = now_datetime()

    call = frappe.get_doc({
        "doctype": "Dennik hovorov",
        "volajuci": caller_name,
        "poradca": advisor_name,
        "zaciatok_datum": now.date(),
        "zaciatok_cas": now.strftime("%H:%M:%S"),
    })
    call.insert(ignore_permissions=True)

    # ---- DEVICES ----
    adv_doc = frappe.get_doc("Poradca", advisor_name)
    device_rows = adv_doc.get("zariadenie") or []

    frappe.log_error(
        title="CALL START DEBUG – DEVICES FOUND",
        message=f"""
Poradca: {advisor_name}
Devices count: {len(device_rows)}

Devices:
{chr(10).join([f"- voip_token={d.voip_token[:12] if d.voip_token else None} apns={bool(d.apns_token)}" for d in device_rows])}
"""
    )

    # ---- SEND PUSH ----
    sent = 0
    for row in device_rows:
        if not row.voip_token:
            continue

        payload = {
            "aps": {
                "content-available": 1
            },
            "callId": call.name,
            "callerId": caller_clerk,
            "callerName": caller_name,
        }

        frappe.log_error(
            title="CALL START DEBUG – SENDING VOIP PUSH",
            message=f"""
TO TOKEN: {row.voip_token}
PAYLOAD:
{payload}
"""
        )

        send_voip_push(row.voip_token, payload)
        sent += 1

    frappe.log_error(
        title="CALL START DEBUG – DONE",
        message=f"VoIP push sent to {sent} device(s)"
    )

    return {
        "success": True,
        "callId": call.name,
        "advisorName": advisor_name
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
