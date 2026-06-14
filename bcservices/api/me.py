# bcservices/api/me.py

import frappe
from .utils import verify_clerk_bearer_and_get_sub

def _require_authenticated_user_and_get_clerk_id() -> str:
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    if not clerk_id:
        frappe.throw("Invalid token", frappe.PermissionError)
    return clerk_id

@frappe.whitelist(allow_guest=True, methods=["GET"])
def me():
    try:
        # 1) Auth + clerk_id
        clerk_id = _require_authenticated_user_and_get_clerk_id()

        # 2) Try to find Klient first
        try:
            klient = frappe.get_all(
                "Klient",
                filters={"clerk_id": clerk_id},
                fields=["name", "clerk_id", "email", "username"],
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
        except Exception as e:
            frappe.log_error(f"Error fetching Klient: {str(e)}")
        
        # 3) If not found, try Poradca (Advisor)
        try:
            poradca = frappe.get_all(
                "Poradca",
                filters={"clerk_id": clerk_id},
                fields=["name", "clerk_id", "email", "meno"],
                limit_page_length=1
            )
            
            if poradca:
                p = poradca[0]
                full_name = p.get("meno") or p.get("name") or p.get("email")
                return {
                    "success": True,
                    "advisor": {
                        "clerk_id": p.get("clerk_id"),
                        "email": p.get("email"),
                        "full_name": full_name
                    }
                }
        except Exception as e:
            frappe.log_error(f"Error fetching Poradca: {str(e)}")

        # 4) Not found in either table
        return {"success": False, "message": "User not found"}
        
    except Exception as e:
        frappe.log_error(f"Error in me() endpoint: {str(e)}")
        return {"success": False, "message": str(e)}
