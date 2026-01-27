# apps/bcservices/bcservices/api/auth.py
from __future__ import annotations

import re
import random
import jwt
import frappe
from frappe.utils.password import get_decrypted_password

from .utils import (
    verify_clerk_bearer_and_get_sub,
    clerk_api,
    ensure_bc_user_by_clerk,
    _jwks_client,
    _clerk_issuer,
    get_settings,   # ⬅️ už importované
)


@frappe.whitelist(methods=["GET"], allow_guest=True)
def get_settings_public():
    """
    iOS volá: /api/method/bcservices.api.auth.get_settings_public
    Vráti Clerk ID administrátora, aby klient vedel komu písať čet.
    """
    settings = get_settings()
    return {
        "admin_clerk_id": settings.admin_clerk_id
    }
# -----------------------------------------------------------------------------
# PUBLIC API – iOS / CLIENTS
# -----------------------------------------------------------------------------

@frappe.whitelist(methods=["GET"], allow_guest=True)
def get_settings_public():
    """
    iOS volá: /api/method/bcservices.api.auth.get_settings_public
    Vráti Clerk ID administrátora, aby klient vedel komu písať čet.
    """
    settings = get_settings()
    return {
        "admin_clerk_id": settings.admin_clerk_id
    }

# -----------------------------------------------------------------------------
# PUBLIC API – iOS / CLIENTS
# -----------------------------------------------------------------------------

@frappe.whitelist(methods=["POST"], allow_guest=True)
def sync_user():
    """
    Syncuje IBA klientov.
    Poradca (role=admin) sa tu ignoruje.
    """

    clerk_id, payload = verify_clerk_bearer_and_get_sub()

    # Zistíme rolu z Clerk
    try:
        u = clerk_api(f"/v1/users/{clerk_id}")
        role = (u.get("public_metadata") or {}).get("role")
    except Exception:
        role = None

    # -------------------------------------------------
    # 🔴 AK JE PORADCA → NESYNCUJEME
    # -------------------------------------------------
    if role == "admin":
        return {
            "success": True,
            "skipped": True,
            "reason": "advisor"
        }

    # -------------------------------------------------
    # 🟢 KLIENT → SYNC
    # -------------------------------------------------
    doc = ensure_bc_user_by_clerk(clerk_id)

    # nastavíme default rolu len ak neexistuje
    try:
        pub = (u.get("public_metadata") or {})
        if "role" not in pub:
            pub["role"] = "client"
            clerk_api(
                f"/v1/users/{clerk_id}",
                method="PATCH",
                json_body={"public_metadata": pub}
            )
    except Exception as e:
        frappe.log_error(f"Clerk role sync failed: {e}", "BC Clerk Sync")

    return {
        "success": True,
        "userId": clerk_id
    }



# -----------------------------------------------------------------------------
# SSO – redirect flow
# -----------------------------------------------------------------------------

@frappe.whitelist(methods=["GET"], allow_guest=True)
def sso(token: str | None = None):
    """
    /api/method/bcservices.api.auth.sso?token=<clerk_jwt>

    - Overí jednorazový Clerk token
    - Vytvorí Clerk sign-in token
    - Redirect na APP_URL/sso/callback?token=<sign_in_token>
    """
    if not token:
        frappe.throw("Missing token", frappe.ValidationError)

    # Validate incoming Clerk token
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=_clerk_issuer(),
            options={"verify_aud": False},
        )
        clerk_id = payload.get("sub")
        if not clerk_id:
            frappe.throw("Invalid token (missing sub)", frappe.PermissionError)

    except Exception as e:
        frappe.throw(f"Invalid or expired token: {e}", frappe.PermissionError)

    # Create sign-in token via Clerk API
    res = clerk_api(
        "/v1/sign_in_tokens",
        method="POST",
        json_body={"user_id": clerk_id, "expires_in_seconds": 60},
    )
    sign_in_token = res.get("token")

    # ❗ App URL z Doctype Nastavenia
    settings = get_settings()
    app_url = (settings.app_url or "").rstrip("/")

    redirect_to = f"{app_url}/sso/callback?token={sign_in_token}"

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = redirect_to


# -----------------------------------------------------------------------------
# INTERNAL FUNCTIONS – Clerk username & upsert helpers
# -----------------------------------------------------------------------------

def _transliterate_slovak(text: str) -> str:
    """Konvertuje slovenské/české znaky na ich ASCII ekvivalenty."""
    mapping = {
        'á': 'a', 'ä': 'a', 'č': 'c', 'ď': 'd', 'é': 'e', 'í': 'i', 'ľ': 'l',
        'ň': 'n', 'ó': 'o', 'ô': 'o', 'ŕ': 'r', 'š': 's', 'ť': 't', 'ú': 'u',
        'ý': 'y', 'ž': 'z',
        'Á': 'A', 'Ä': 'A', 'Č': 'C', 'Ď': 'D', 'É': 'E', 'Í': 'I', 'Ľ': 'L',
        'Ň': 'N', 'Ó': 'O', 'Ô': 'O', 'Ŕ': 'R', 'Š': 'S', 'Ť': 'T', 'Ú': 'U',
        'Ý': 'Y', 'Ž': 'Z',
    }
    for char, replacement in mapping.items():
        text = text.replace(char, replacement)
    return text

def _normalize_username_base(email_or_hint: str | None) -> str:
    base = (email_or_hint or "user").split("@")[0] # odstraň 'lower()'
    
    # 1. Transliterácia na ASCII
    base = _transliterate_slovak(base)
    
    # 2. Všetko na malé písmená
    base = base.lower()
    
    # 3. Odstránenie neplatných znakov
    # Ponecháme a-z (po transliterácii), 0-9, bodky, podčiarkovníky, pomlčky
    base = re.sub(r"[^a-z0-9._-]", "", base).strip("._-")
    
    return base or "user"


def _create_clerk_user(email: str, password: str | None, preferred_username: str | None = None) -> dict:
    uname_base = _normalize_username_base(preferred_username or email)
    attempts = 6
    last_err: Exception | None = None

    for i in range(attempts):
        uname = uname_base if i == 0 else f"{uname_base}{random.randint(1000, 9999)}"
        body = {
            "email_address": [email],
            "public_metadata": {"role": "client"},
            "username": uname,
        }
        if password:
            body["password"] = password

        try:
            return clerk_api("/v1/users", method="POST", json_body=body)

        except Exception as e:
            last_err = e

            # Clerk username conflict → try again with a different suffix
            if "username" in str(e) and i < attempts - 1:
                continue

            raise

    if last_err:
        raise last_err

    frappe.throw("Failed to create Clerk user", frappe.ValidationError)


def _patch_clerk_user(clerk_id: str, email: str | None, password: str | None, new_username: str | None = None) -> None:
    patch = {"public_metadata": {"role": "client"}}

    if email:
        patch["email_address"] = [email]
    if password:
        patch["password"] = password
    if new_username:
        patch["username"] = _normalize_username_base(new_username)

    try:
        clerk_api(f"/v1/users/{clerk_id}", method="PATCH", json_body=patch)
    except Exception as e:
        # Ignore ONLY username conflict errors
        if new_username and "username" in str(e):
            frappe.log_error(f"Clerk username update failed: {e}", "BC Clerk Sync")
        else:
            raise


# -----------------------------------------------------------------------------
# HOOKS – used internally by Klient DocType
# -----------------------------------------------------------------------------

def after_insert_bc_pouzivatel(doc, method=None):
    if getattr(doc, "clerk_id", None):
        return
    if not getattr(doc, "email", None):
        return

    try:
        pw = doc.heslo   # <-- FIX

        res = _create_clerk_user(
            email=doc.email,
            password=pw,
            preferred_username=getattr(doc, "username", None),
        )

        cid = res.get("id")
        if cid:
            frappe.db.set_value("Klient", doc.name, "clerk_id", cid)

        if res.get("username") and hasattr(doc, "username"):
            frappe.db.set_value("Klient", doc.name, "username", res["username"])

    except Exception as e:
        frappe.log_error(f"Clerk create failed: {e}", "BC Clerk Sync")



def on_update_bc_pouzivatel(doc, method=None):
    if not getattr(doc, "clerk_id", None):
        return

    try:
        pw = doc.heslo   # <-- FIX

        _patch_clerk_user(
            clerk_id=doc.clerk_id,
            email=getattr(doc, "email", None),
            password=pw,
            new_username=getattr(doc, "username", None),
        )
    except Exception as e:
        frappe.log_error(f"Clerk update failed: {e}", "BC Clerk Sync")

@frappe.whitelist(methods=["POST", "GET"], allow_guest=True) 
def get_my_advisors():
    """
    Vráti zoznam poradcov priradených k prihlásenému klientovi.
    iOS volá: /api/method/bcservices.api.auth.get_my_advisors
    """
    # 1. Overenie identity klienta cez Clerk JWT v hlavičke
    try:
        clerk_id, _ = verify_clerk_bearer_and_get_sub()
    except Exception as e:
        frappe.throw(f"Neautorizovaný prístup: {e}", frappe.PermissionError)

    # 2. Vyhľadanie mena klienta v databáze Frappe
    klient_name = frappe.db.get_value("Klient", {"clerk_id": clerk_id}, "name")
    
    if not klient_name:
        return {
            "success": False,
            "error": "V systéme neexistuje klient s týmto Clerk ID."
        }

    # 3. Načítanie dokumentu klienta aj s jeho Child Table (poradcovia)
    doc = frappe.get_doc("Klient", klient_name)
    
    advisors_list = []
    
    # 4. Iterácia cez priradených poradcov
    # Predpokladáme, že fieldname pre Child Table v Doctype Klient je 'poradcovia'
    # a link field v Child Doctype sa volá 'poradca_link'
    for row in doc.get("poradcovia") or []:
        if not row.poradca_link:
            continue
            
        try:
            # Načítame detailné informácie o každom priradenom poradcovi
            p = frappe.get_doc("Poradca", row.poradca_link)
            
            # OPRAVA TU: Zmenené zo 'zariadenia' na 'zariadenie'
            devices = p.get("zariadenie") or []
            has_voip = any(d.voip_token for d in devices)

            advisors_list.append({
                "name": p.meno,
                "clerk_id": p.clerk_id,
                "email": p.email,
                "has_voip": has_voip
            })
        except frappe.DoesNotExistError:
            # Ak by bol poradca vymazaný, ale odkaz v klientovi zosta
            continue

    return {
        "success": True,
        "advisors": advisors_list
    }

