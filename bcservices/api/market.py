import frappe
from .utils import verify_clerk_bearer_and_get_sub

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
            "id": row.name,
            "tokenId": tok.name,
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

    # Nájdi interné meno (Klient alebo Poradca) podľa Clerk ID
    # Skúsime obe tabuľky, aby logy videl každý
    bc_user = frappe.db.get_value("Klient", {"clerk_id": userId}, "name") or \
              frappe.db.get_value("Poradca", {"clerk_id": userId}, "name")

    if not bc_user:
        return {"success": True, "items": []}

    logs = frappe.get_all(
        "Dennik hovorov",
        filters=[
            ["klient", "=", bc_user],
            ["poradca", "=", bc_user]
        ],
        filter_condition="or",
        fields=[
            "name",
            "klient",
            "poradca",
            "kto_volal", # Pridané nové pole
            "zaciatok_datum",
            "zaciatok_cas",
            "koniec_datum",
            "koniec_cas",
            "trvanie_s",
            "pouzity_token",
        ],
        order_by="zaciatok_datum desc, zaciatok_cas desc"
    )

    # Premapovanie na čistý JSON pre appku
    out = []
    for log in logs:
        out.append({
            "id": log.name,
            "client": log.klient,
            "advisor": log.poradca,
            "callerRole": log.kto_volal, # "Klient" alebo "Poradca"
            "startedAtDate": log.zaciatok_datum,
            "startedAtTime": log.zaciatok_cas,
            "durationSeconds": log.trvanie_s or 0,
            "tokenId": log.pouzity_token
        })

    return {"success": True, "items": out}

@frappe.whitelist(methods=["GET"], allow_guest=True)
def history(userId: str = None):
    if not userId:
        return {"success": False, "error": "Missing userId"}

    bc_user = frappe.db.get_value("Klient", {"clerk_id": userId}, "name")
    
    if not bc_user:
        return {"success": True, "items": []}

    transactions = frappe.get_all(
        "Transakcia",
        filters={"docstatus": ["<", 2]},
        or_filters={"predavajuci": bc_user, "kupujuci": bc_user},
        fields=["name", "predavajuci", "kupujuci", "suma_eur", "datum", "inzerat"],
        order_by="datum desc"
    )

    out = []
    for row in transactions:
        vydany_rok = 2026
        if row.get("inzerat"):
            token_id = frappe.db.get_value("Inzerat", row.inzerat, "token")
            if token_id:
                vydany_rok = frappe.db.get_value("Token", token_id, "vydany_rok") or 2026

        direction = "sell" if row.predavajuci == bc_user else "buy"
        tx_type = "trade"
        if not row.predavajuci and row.kupujuci == bc_user:
            tx_type = "purchase"

        out.append({
            "id": row.name,
            "type": tx_type,
            "direction": direction,
            "price": float(row.suma_eur or 0),
            "year": vydany_rok,
            "createdAt": row.datum,
        })

    return {"success": True, "items": out}

@frappe.whitelist(methods=["POST"], allow_guest=True)
def cancel_listing():
    data = frappe.form_dict
    listing_id = data.get("listingId")
    
    if not listing_id:
        return {"success": False, "error": "Chýba listingId"}

    if not frappe.db.exists("Inzerat", listing_id):
        return {"success": False, "error": "Inzerát neexistuje"}
    
    listing = frappe.get_doc("Inzerat", listing_id)

    if listing.stav != "open":
        return {"success": False, "error": f"Inzerát už nie je možné zrušiť (stav: {listing.stav})"}

    try:
        listing.stav = "cancelled"
        listing.save(ignore_permissions=True)

        if listing.token:
            frappe.db.set_value("Token", listing.token, "stav", "active")

        return {"success": True}
    
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Cancel Listing Error")
        return {"success": False, "error": str(e)}

@frappe.whitelist(methods=["POST"], allow_guest=True)
def list_token(sellerId: str = None, tokenId: str = None, priceEur: float = None):
    clerk_id, payload = verify_clerk_bearer_and_get_sub()

    sellerId = sellerId or frappe.form_dict.get("sellerId")
    tokenId = tokenId or frappe.form_dict.get("tokenId")
    priceEur = priceEur or frappe.form_dict.get("priceEur")

    if not sellerId or not tokenId or priceEur is None:
        frappe.throw("Missing parameters", frappe.ValidationError)

    if sellerId != clerk_id:
        frappe.throw("Forbidden", frappe.PermissionError)

    bc_user = frappe.db.get_value("Klient", {"clerk_id": clerk_id}, "name")

    if not bc_user:
        frappe.throw("User not found", frappe.DoesNotExistError)

    token = frappe.get_doc("Token", tokenId)

    if token.aktualny_drzitel != bc_user:
        frappe.throw("Token does not belong to this user", frappe.PermissionError)

    if token.stav != "active":
        frappe.throw("Token is not active", frappe.ValidationError)

    inz = frappe.get_doc({
        "doctype": "Inzerat",
        "predavajuci": bc_user,
        "token": tokenId,
        "cena_eur": priceEur,
        "stav": "open"
    })
    inz.insert(ignore_permissions=True)

    token.stav = "listed"
    token.save(ignore_permissions=True)

    return {
        "listingId": inz.name,
        "tokenId": tokenId,
        "priceEur": float(priceEur),
        "success": True
    }
