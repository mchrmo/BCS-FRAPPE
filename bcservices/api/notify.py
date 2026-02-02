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
    sender_clerk_id = data.get("from_user")  # 🔥 Od koho (Clerk ID) - pre vyhľadanie mena
    
    # Pôvodné meno z Node.js (často len ID alebo 'Niekto')
    raw_sender_name = data.get("from_name", "Neznámy")
    
    content = data.get("content", "Máte novú správu")

    if not target_clerk_id:
        return {"success": False, "error": "Missing target_clerk_id"}

    # -------------------------------------------------------------------------
    # 🔥 OPRAVA: Zistíme reálne meno odosielateľa z databázy
    # -------------------------------------------------------------------------
    real_sender_name = raw_sender_name # Default hodnota
    
    if sender_clerk_id:
        try:
            # Použijeme tú istú funkciu na hľadanie odosielateľa v DB
            _, sender_doc = get_actor_by_clerk_id(sender_clerk_id)
            
            if sender_doc:
                # Skúsime nájsť najlepšie dostupné meno v poradí: username -> full_name -> name
                real_sender_name = (
                    sender_doc.get("username") or 
                    sender_doc.get("full_name") or 
                    sender_doc.get("name") or 
                    raw_sender_name
                )
        except Exception:
            # Ak nastane chyba pri hľadaní, nevadí, použijeme pôvodné raw meno
            pass
            
    # -------------------------------------------------------------------------

    # 2. Nájdeme PRÍJEMCU v DB (Poradca alebo Klient)
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
                title=real_sender_name,  # 🔥 TU použijeme pekné meno z databázy
                body=content,            # Text správy
                custom_data={
                    "clerk_id_from": sender_clerk_id, # Aby iOS vedel otvoriť chat (používame ID)
                    "type": "chat"
                }
            )
            if success:
                sent_count += 1

    return {"success": True, "sent_to": sent_count}
