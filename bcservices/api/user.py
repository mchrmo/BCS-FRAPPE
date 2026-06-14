# apps/bcservices/bcservices/api/user.py

import frappe
from .utils import verify_bearer_and_get_email

# 🔥 MUST HAVE → inak Frappe hlási "not whitelisted"
@frappe.whitelist(methods=["GET"], allow_guest=True)
def balance(userId: str = None):
    """
    Return total remaining minutes for a user.
    iOS volá: /api/method/bcservices.api.user.balance?userId=<email>

    Overí:
    - JWT (Authorization: Bearer <jwt>)
    - že user si pýta balans iba pre seba
    """

    # 👇 Over JWT z headeru
    email, payload = verify_bearer_and_get_email()

    if not userId:
        frappe.throw("Missing userId", frappe.ValidationError)

    # 👇 user môže vidieť LEN svoj balans
    if userId != email:
        frappe.throw("Forbidden", frappe.PermissionError)

    # 👇 nájdi Klient podľa emailu
    user_name = frappe.db.get_value("Klient", {"email": email}, "name")
    if not user_name:
        frappe.throw("User not found", frappe.DoesNotExistError)

    # 👇 nájdi minúty z tokenov
    tokens = frappe.get_all(
        "Token",
        filters={
            "aktualny_drzitel": user_name,
            "stav": "active"
        },
        fields=["name", "minuty_ostavajuce", "vydany_rok", "stav"]
    )

    # vypočítaj súčet
    total = sum((t["minuty_ostavajuce"] or 0) for t in tokens)

    # 👇 iOS očakáva presné tvarovanie
    return {
        "userId": email,
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