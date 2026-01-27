import frappe
from frappe import _
from .utils import verify_clerk_bearer_and_get_sub, clerk_api

@frappe.whitelist(methods=["POST"], allow_guest=True)
def register_device():
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}

    voip_token = data.get("voip_token") or data.get("voipToken")
    apns_token = data.get("apns_token") or data.get("apnsToken")

    if not voip_token and not apns_token:
        frappe.throw("Missing device token")

    # 1) role z Clerk (server-side)
    role = None
    try:
        u = clerk_api(f"/v1/users/{clerk_id}")
        role = (u.get("public_metadata") or {}).get("role")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"register_device: clerk_api failed: {e}")

    # 2) vyber doctype podľa role
    if role == "admin":
        doctype = "Poradca"
    else:
        doctype = "Klient"

    name = frappe.db.get_value(doctype, {"clerk_id": clerk_id}, "name")
    if not name:
        frappe.throw(_(f"{doctype} not found for clerk_id"), frappe.PermissionError)

    doc = frappe.get_doc(doctype, name)

    # 3) append do child table "zariadenie"
    # (bez duplicity logiky – najprv jednoduché uloženie nech vieme že to ide)
    doc.append("zariadenie", {
        "voip_token": voip_token,
        "apns_token": apns_token
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "success": True,
        "doctype": doctype,
        "name": name,
        "role": role
    }
