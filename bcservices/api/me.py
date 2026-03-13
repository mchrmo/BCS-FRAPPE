# bcservices/api/auth.py

import frappe
import json
import base64
import time

# If you already have a util to verify Clerk tokens, reuse it.
# Below is a lightweight extractor that trusts the JWT and extracts `sub` as `clerk_id`.
# For production, you should verify the JWT signature against Clerk's JWKS.
def _extract_clerk_id_from_jwt(jwt_token: str) -> str | None:
    try:
        # JWT is header.payload.signature (base64url)
        parts = jwt_token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        # Pad base64 if necessary
        padding = "=" * (-len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
        payload = json.loads(payload_json)
        # Clerk user id is usually in `sub`
        return payload.get("sub")
    except Exception:
        return None

def _require_authenticated_user_and_get_clerk_id() -> str:
    # Expect header: X-Clerk-Authorization: Bearer <jwt>
    auth_header = frappe.get_request_header("X-Clerk-Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        frappe.throw("Missing or invalid authorization header", frappe.PermissionError)

    jwt = auth_header.replace("Bearer ", "").strip()
    clerk_id = _extract_clerk_id_from_jwt(jwt)
    if not clerk_id:
        frappe.throw("Invalid token", frappe.PermissionError)

    return clerk_id

@frappe.whitelist(methods=["GET"])  # ← added )
def me():
    # 1) Auth + clerk_id
    clerk_id = _require_authenticated_user_and_get_clerk_id()

    # 2) Find Klient by clerk_id
    klient = frappe.get_all(
        "Klient",
        filters={"clerk_id": clerk_id},
        fields=["name", "clerk_id", "email", "username"],  # username is your full-name field
        limit_page_length=1
    )
    if not klient:
        return {"success": False, "message": "Client not found"}

    k = klient[0]
    full_name = k.get("username") or k.get("name") or k.get("email")

    return {
        "success": True,
        "client": {
            "clerk_id": k.get("clerk_id"),
            "email": k.get("email"),
            "full_name": full_name
        }
    }
