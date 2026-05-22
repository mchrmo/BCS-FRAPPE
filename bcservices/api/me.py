# bcservices/api/me.py

import frappe
import json
import base64

def _extract_clerk_id_from_jwt(jwt_token: str) -> str | None:
    try:
        parts = jwt_token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
        payload = json.loads(payload_json)
        return payload.get("sub")
    except Exception:
        return None

def _require_authenticated_user_and_get_clerk_id() -> str:
    auth_header = frappe.get_request_header("X-Clerk-Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        frappe.throw("Missing or invalid authorization header", frappe.PermissionError)

    jwt = auth_header.replace("Bearer ", "").strip()
    clerk_id = _extract_clerk_id_from_jwt(jwt)
    if not clerk_id:
        frappe.throw("Invalid token", frappe.PermissionError)

    return clerk_id

@frappe.whitelist(allow_guest=True, methods=["GET"])
def me():
    # 1) Auth + clerk_id
    clerk_id = _require_authenticated_user_and_get_clerk_id()

    # 2) Try to find Klient first
    klient = frappe.get_all(
        "Klient",
        filters={"clerk_id": clerk_id},
        fields=["name", "clerk_id", "email", "username"],  # ✅ username = meno
        limit_page_length=1
    )
    
    if klient:
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
    
    # 3) If not found, try Poradca (Advisor)
    poradca = frappe.get_all(
        "Poradca",
        filters={"clerk_id": clerk_id},
        fields=["name", "clerk_id", "email", "meno"],  # ✅ meno (nie full_name!)
        limit_page_length=1
    )
    
    if poradca:
        p = poradca[0]
        full_name = p.get("meno") or p.get("name") or p.get("email")  # ✅ meno
        return {
            "success": True,
            "advisor": {
                "clerk_id": p.get("clerk_id"),
                "email": p.get("email"),
                "full_name": full_name
            }
        }

    # 4) Not found in either table
    return {"success": False, "message": "User not found"}
