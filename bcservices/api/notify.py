import frappe
from .utils import get_actor_by_clerk_id, send_chat_push

@frappe.whitelist(methods=["POST"], allow_guest=True)
def send_notification():
    """
    Tento endpoint bude volať Node.js server, keď je používateľ offline.
    """
    # 1. Získame dáta z requestu
    data = frappe.local.form_dict
    target_clerk_id = data.get("to_user")    # Komu (Clerk ID)
    sender_name = data.get("from_name", "Neznámy") # Kto
    content = data.get("content", "Máte novú správu")
    
    # Bezpečnostná kontrola (voliteľné, ale dobré mať)
    # if data.get("secret_key") != "TVOJE_TAJNE_HESLO_MEDZI_NODE_A_FRAPPE":
    #    frappe.throw("Unauthorized", frappe.PermissionError)

    if not target_clerk_id:
        return {"success": False, "error": "Missing target_clerk_id"}

    # 2. Nájdeme používateľa v DB (Poradca alebo Klient)
    doctype, user_doc = get_actor_by_clerk_id(target_clerk_id)
    
    if not user_doc:
        return {"success": False, "error": "User not found"}

    # 3. Získame jeho APNs tokeny zo child table 'Zariadenie'
    devices = user_doc.get("zariadenie") or []
    sent_count = 0

    for d in devices:
        # Hľadáme 'apns_token' (nie voip_token!)
        if d.apns_token:
            success = send_chat_push(
                device_token=d.apns_token,
                title=sender_name,  # Nadpis notifikácie je meno odosielateľa
                body=content,       # Text správy
                custom_data={
                    "clerk_id_from": data.get("from_user"), # Aby iOS vedel otvoriť chat
                    "type": "chat"
                }
            )
            if success:
                sent_count += 1

    return {"success": True, "sent_to": sent_count}
