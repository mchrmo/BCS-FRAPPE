import frappe

@frappe.whitelist(methods=["GET"], allow_guest=True)
def listings():
    rows = frappe.get_all(
        "Inzerat",
        filters={"stav": "open"},
        order_by="creation desc",
        fields=["name", "token", "predavajuci", "cena_eur", "creation"]
    )

    out = []

    for row in rows:
        tok = frappe.get_doc("Token", row.token)

        out.append({
            "id": row.name,                  # ID inzerátu
            "tokenId": tok.name,             # <-- TOTO MUSÍ BYŤ!
            "token": {
                "id": tok.name,
                "issuedYear": tok.vydany_rok,
                "minutesRemaining": tok.minuty_ostavajuce,
                "status": tok.stav
            },
            "sellerId": row.predavajuci,
            "priceEur": float(row.cena_eur),
            "status": "open",
            "createdAt": row.creation
        })

    return {"success": True, "items": out}

@frappe.whitelist(methods=["GET"], allow_guest=True)
def call_logs(userId: str = None):
    if not userId:
        frappe.throw("Missing userId", frappe.ValidationError)

    # Nájdi Klienta podľa Clerk ID
    user_doc = frappe.get_all(
        "Klient",
        filters={"clerk_id": userId},
        limit=1
    )

    if not user_doc:
        return {"success": True, "items": []}

    bc_user = user_doc[0].name

    # Načítaj hovory (používame interné názvy polí podľa Frappe štandardu)
    # Ak máš polia pomenované inak (napr. s diakritikou), uprav názvy v 'fields'
    logs = frappe.get_all(
        "Dennik hovorov",
        filters={"volajuci": bc_user},
        fields=[
            "name", 
            "zaciatok_datum", 
            "koniec_datum", 
            "trvanie_s", 
            "pouzity_token"
        ],
        order_by="zaciatok_datum desc"
    )

    return {"success": True, "items": logs}

@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str = None):
    if not userId:
        return {"success": False, "error": "Missing userId"}

    bc_user = frappe.db.get_value("Klient", {"clerk_id": userId}, "name", ignore_permissions=True)
    if not bc_user:
        return {"success": True, "items": []}

    # Načítame transakcie s poľom 'inzerat'
    transactions = frappe.get_all(
        "Transakcia",
        filters={"docstatus": ["<", 2]},
        or_filters={"predavajuci": bc_user, "kupujuci": bc_user},
        fields=["name", "predavajuci", "kupujuci", "suma_eur", "datum", "inzerat"], 
        ignore_permissions=True
    )

    out = []
    for row in transactions:
        vydany_rok = 2026 # Predvolená hodnota
        
        # Ak existuje link na inzerát, skúsime vytiahnuť rok z tokenu
        if row.get("inzerat"):
            token_id = frappe.db.get_value("Inzerat", row.inzerat, "token", ignore_permissions=True)
            if token_id:
                vydany_rok = frappe.db.get_value("Token", token_id, "vydany_rok", ignore_permissions=True) or 2026
        
        direction = "sell" if row.predavajuci == bc_user else "buy"

        out.append({
            "id": row.name,
            "type": "trade",
            "direction": direction,
            "price": float(row.suma_eur or 0),
            "year": vydany_rok,
            "createdAt": row.datum,
        })

    return {"success": True, "items": out}


import frappe
from .utils import verify_clerk_bearer_and_get_sub

@frappe.whitelist(methods=["POST"], allow_guest=True)
def list_token(sellerId: str = None, tokenId: str = None, priceEur: float = None):
    """
    Client lists a token for sale.
    Overí:
    - Clerk JWT (X-Clerk-Authorization: Bearer <jwt>)
    - že user listuje IBA svoj token
    """

    # 👇 Over Clerk JWT
    clerk_id, payload = verify_clerk_bearer_and_get_sub()

    # 👇 Presne ako pri balance()
    sellerId = sellerId or frappe.form_dict.get("sellerId")
    tokenId = tokenId or frappe.form_dict.get("tokenId")
    priceEur = priceEur or frappe.form_dict.get("priceEur")

    if not sellerId or not tokenId or priceEur is None:
        frappe.throw("Missing parameters", frappe.ValidationError)

    # 👇 User môže listovať iba SVOJE tokeny
    if sellerId != clerk_id:
        frappe.throw("Forbidden", frappe.PermissionError)

    # 👇 Nájdi Klient podľa Clerk ID
    user_doc = frappe.get_all(
        "Klient",
        filters={"clerk_id": clerk_id},
        limit=1
    )

    if not user_doc:
        frappe.throw("User not found", frappe.DoesNotExistError)

    bc_user = user_doc[0].name

    # 👇 Nájdi token
    token = frappe.get_doc("Token", tokenId)

    # 👇 Token musí patriť užívateľovi
    if token.aktualny_drzitel != bc_user:
        frappe.throw("Token does not belong to this user", frappe.PermissionError)

    # 👇 Token musí byť aktívny
    if token.stav != "active":
        frappe.throw("Token is not active", frappe.ValidationError)

    # 👇 Vytvor nový inzerát
    inz = frappe.get_doc({
        "doctype": "Inzerat",
        "predavajuci": bc_user,
        "token": tokenId,
        "cena_eur": priceEur,
        "stav": "open"
    })
    inz.insert(ignore_permissions=True)

    # 👇 Označ token ako listed
    token.stav = "listed"
    token.save(ignore_permissions=True)

    return {
        "listingId": inz.name,
        "tokenId": tokenId,
        "priceEur": float(priceEur),
        "success": True
    }
