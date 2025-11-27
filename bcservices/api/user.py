# apps/bcservices/bcservices/api/user.py

import frappe
from .utils import (
    verify_clerk_bearer_and_get_sub,
    ensure_bc_user_by_clerk
)

# 🔥 MUST HAVE → inak Frappe hlási "not whitelisted"
@frappe.whitelist(methods=["GET"], allow_guest=True)
def balance(userId: str = None):
    """
    Return total remaining minutes for a user.
    iOS volá: /api/method/bcservices.api.user.balance?userId=<clerk_id>

    Overí:
    - Clerk JWT (X-Clerk-Authorization: Bearer <jwt>)
    - že user si pýta balans iba pre seba
    """

    # 👇 Over Clerk JWT z headeru
    clerk_id, payload = verify_clerk_bearer_and_get_sub()

    if not userId:
        frappe.throw("Missing userId", frappe.ValidationError)

    # 👇 user môže vidieť LEN svoj balans
    if userId != clerk_id:
        frappe.throw("Forbidden", frappe.PermissionError)

    # 👇 nájdi / vytvor BC Pouzivatel
    user_doc = ensure_bc_user_by_clerk(clerk_id)

    # 👇 nájdi minúty z tokenov
    tokens = frappe.get_all(
        "BC Token",
        filters={
            "aktualny_drzitel": user_doc.name,
            "stav": "active"
        },
        fields=["name", "minuty_ostavajuce", "vydany_rok", "stav"]
    )

    # vypočítaj súčet
    total = sum((t["minuty_ostavajuce"] or 0) for t in tokens)

    # 👇 iOS očakáva presné tvarovanie
    return {
        "userId": clerk_id,
        "totalMinutes": total,
        "tokens": [
            {
                "id": t["name"],
                "issuedYear": t.get("vydany_rok", 0),
                "minutesRemaining": t.get("minuty_ostavajuce", 0),
                "status": t.get("stav", "unknown")
            }
            for t in tokens
        ]
    }