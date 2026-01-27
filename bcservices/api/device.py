# apps/bcservices/bcservices/api/device.py

import frappe
from .utils import (
    verify_clerk_bearer_and_get_sub,
    get_actor_by_clerk_id,
    upsert_child_device_for_user
)

@frappe.whitelist(methods=["POST"], allow_guest=True)
def register_device():
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    data = frappe.local.form_dict or {}

    voip_token = data.get("voip_token") or data.get("voipToken")
    apns_token = data.get("apns_token") or data.get("apnsToken")

    if not voip_token and not apns_token:
        frappe.throw("Missing device token")

    doctype, user_doc = get_actor_by_clerk_id(clerk_id)
    if not user_doc:
        frappe.throw("Unknown user")

    # --- TOTO JE TA MOŽNÁ CHYBA ---
    # Musíme sa uistiť, že objekt user_doc má čerstvé metadáta z DB
    user_doc.reload() 

    upsert_child_device_for_user(
        user_doc=user_doc,
        voip_token=voip_token,
        apns_token=apns_token
    )

    return {
        "success": True,
        "actor": doctype,
    }
