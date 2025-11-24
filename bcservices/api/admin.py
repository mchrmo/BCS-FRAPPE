# apps/bcservices/bcservices/api/admin.py

import frappe
from frappe.utils import now_datetime
from .utils import verify_clerk_bearer_and_get_sub, clerk_api, get_settings

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
    """
    iOS Admin app → /api/method/bcservices.api.admin.list_clients
    """
    _require_admin()

    users = frappe.get_all(
        "BC Pouzivatel",
        fields=["name", "clerk_id", "email"]
    )

    out = []
    for u in users:
        devices = frappe.get_all(
            "BC Zariadenie",
            filters={"parent": u["name"]},
            fields=["voip_token", "apns_token", "modified"]
        )

        tokens = frappe.get_all(
            "BC Token",
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

    return {
        "success": True,
        "clients": out
    }

# -----------------------------------------------------------------------------
# ADMIN – MINT TOKENS
# -----------------------------------------------------------------------------

@frappe.whitelist(methods=["POST"], allow_guest=True)
def mint(quantity: int = None, priceEur: float = None, year: int = None):
    _require_admin()

    data = frappe.local.form_dict
    qty = int(quantity or data.get("quantity") or 0)
    price = float(priceEur or data.get("priceEur") or 0)
    y = int(year or data.get("year") or now_datetime().year)

    if qty <= 0 or price <= 0:
        frappe.throw("Invalid quantity/priceEur", frappe.ValidationError)

    settings = get_settings()

    for _ in range(qty):
        d = frappe.get_doc({
            "doctype": "BC Token",
            "minuty_ostavajuce": 60,
            "stav": "active",
            "povodna_cena_eur": price,
            "vydany_rok": y
        })
        d.insert(ignore_permissions=True)

    settings.friday_base_price_eur = price
    settings.friday_base_year = y
    settings.save(ignore_permissions=True)

    return {
        "success": True,
        "minted": qty,
        "priceEur": price,
        "year": y
    }

# -----------------------------------------------------------------------------
# ADMIN – TEST SETTINGS ENDPOINT
# -----------------------------------------------------------------------------

@frappe.whitelist(methods=["GET"], allow_guest=False)
def test_settings():
    try:
        settings = frappe.get_single("Nastavenie")
    except Exception as e:
        frappe.throw(f"Cannot load Nastavenie: {e}", frappe.DoesNotExistError)

    return {
        "clerk": {
            "issuer": settings.clerk_issuer,
            "secret_key": "***" if settings.clerk_secret_key else None,
            "jwks_url": settings.clerk_jwks_url,
        },
        "apn": {
            "team_id": settings.apn_team_id,
            "key_id": settings.apn_key_id,
            "bundle_id": getattr(settings, "apn_bundle_id", None),
            "key_file": settings.apn_key_file,
            "production": settings.apn_production,
        },
        "stripe": {
            "secret_key": "***" if settings.stripe_secret_key else None,
            "webhook_secret": "***" if settings.stripe_webhook_secret else None,
        },
        "pricing": {
            "base_price_eur": settings.friday_base_price_eur,
            "year": settings.friday_base_year,
            "limit": settings.max_primary_tokens_per_user,
        },
        "app": {
            "app_url": settings.app_url
        }
    }

# -----------------------------------------------------------------------------
# ADMIN – CHANGE TOKEN PRICE
# -----------------------------------------------------------------------------

@frappe.whitelist(methods=["POST"], allow_guest=True)
def set_price(newPrice: float = None, repriceTreasury: int = 0):
    _require_admin()

    data = frappe.local.form_dict
    price = float(newPrice or data.get("newPrice") or 0)
    reprice = int(repriceTreasury or data.get("repriceTreasury") or 0)

    if price <= 0:
        frappe.throw("Invalid newPrice", frappe.ValidationError)

    settings = get_settings()
    settings.friday_base_price_eur = price
    settings.save(ignore_permissions=True)

    if reprice:
        treasury = frappe.get_all(
            "BC Token",
            filters={"aktualny_drzitel": ["is", "null"], "stav": "active"},
            pluck="name"
        )
        for n in treasury:
            frappe.db.set_value("BC Token", n, "povodna_cena_eur", price)

    return {"success": True, "priceEur": price}
