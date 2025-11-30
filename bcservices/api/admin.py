import frappe
from frappe.utils import now_datetime
from .utils import verify_clerk_bearer_and_get_sub, clerk_api


# -----------------------------------------------------------------------------
# INTERNAL – CHECK ADMIN ROLE
# -----------------------------------------------------------------------------
def _require_admin():
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    u = clerk_api(f"/v1/users/{clerk_id}")
    role = (u.get("public_metadata") or {}).get("role")
    if role != "admin":
        frappe.throw("Forbidden", frappe.PermissionError)
    return clerk_id


# -----------------------------------------------------------------------------
# ADMIN – LIST ALL CLIENTS
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"], allow_guest=True)
def list_clients():
    _require_admin()

    users = frappe.get_all(
        "Pouzivatel",
        fields=["name", "clerk_id", "email"]
    )

    out = []
    for u in users:
        devices = frappe.get_all(
            "Zariadenie",
            filters={"parent": u["name"]},
            fields=["voip_token", "apns_token", "modified"]
        )

        tokens = frappe.get_all(
            "Token",
            filters={"aktualny_drzitel": u["name"]},
            fields=["minuty_ostavajuce", "stav"]
        )

        username = None
        try:
            cu = clerk_api(f"/v1/users/{u['clerk_id']}")
            username = (
                cu.get("username")
                or cu.get("first_name")
                or (cu.get("email_addresses")[0]["email_address"]
                    if cu.get("email_addresses") else None)
            )
        except Exception:
            pass

        out.append({
            **u,
            "devices": devices,
            "tokens": tokens,
            "username": username
        })

    return {"success": True, "clients": out}


# -----------------------------------------------------------------------------
# ADMIN – MINT TOKENS
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def admin_mint():
    _require_admin()

    data = frappe.request.get_json() or {}

    qty = int(data.get("quantity") or 0)
    price = float(data.get("priceEur") or 0)
    year = int(data.get("year") or now_datetime().year)

    if qty <= 0 or price <= 0:
        frappe.throw("Invalid quantity or priceEur", frappe.ValidationError)

    created = []

    for _ in range(qty):
        doc = frappe.get_doc({
<<<<<<< HEAD
            "doctype": "BC Token",
=======
            "doctype": "Token",
>>>>>>> cbb2b3e (Added naming rule + auto password + email sending for Pouzivatel)
            "minuty_ostavajuce": 60,
            "stav": "active",
            "povodna_cena_eur": price,
            "vydany_rok": year,
            "aktualny_drzitel": None,
        })
        doc.insert(ignore_permissions=True)
        created.append(doc.name)

    return {
        "success": True,
        "minted": qty,
        "token_names": created,
        "priceEur": price,
        "year": year
    }


# -----------------------------------------------------------------------------
# ADMIN – CHANGE TOKEN PRICE
# -----------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"], allow_guest=True)
def admin_set_price():
    _require_admin()

    data = frappe.request.get_json() or {}

    new_price = float(data.get("newPrice") or 0)
    reprice = bool(data.get("repriceTreasury") or False)

    if new_price <= 0:
        frappe.throw("Invalid newPrice", frappe.ValidationError)

    updated = []

    if reprice:
        treasury_tokens = frappe.get_all(
<<<<<<< HEAD
            "BC Token",
=======
            "Token",
>>>>>>> cbb2b3e (Added naming rule + auto password + email sending for Pouzivatel)
            filters={
                "stav": "active",
                "aktualny_drzitel": ["is", "null"],
            },
            pluck="name"
        )
        for token_name in treasury_tokens:
            frappe.db.set_value(
<<<<<<< HEAD
                "BC Token", token_name,
=======
                "Token", token_name,
>>>>>>> cbb2b3e (Added naming rule + auto password + email sending for Pouzivatel)
                "povodna_cena_eur", new_price
            )
        updated = treasury_tokens

    return {
        "success": True,
        "priceEur": new_price,
        "updatedCount": len(updated),
        "updatedTokens": updated
<<<<<<< HEAD
    }
=======
    }
>>>>>>> cbb2b3e (Added naming rule + auto password + email sending for Pouzivatel)
