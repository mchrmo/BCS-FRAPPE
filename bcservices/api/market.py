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
def history(userId: str = None):
    if not userId:
        frappe.throw("Missing userId", frappe.ValidationError)

    # nájdi BC Pouzivatel
    user_doc = frappe.get_all(
        "Pouzivatel",
        filters={"clerk_id": userId},
        limit=1
    )

    if not user_doc:
        return {"success": True, "items": []}

    bc_user = user_doc[0].name

    # 1) transakcie kde JE user predavajuci
    sold = frappe.get_all(
        "BC Transakcia",
        filters={"predavajuci": bc_user},
        fields=["name", "predavajuci", "kupujuci", "token", "suma_eur", "datum"],
        order_by="datum desc"
    )

    # 2) transakcie kde JE user kupujuci
    bought = frappe.get_all(
        "Transakcia",
        filters={"kupujuci": bc_user},
        fields=["name", "predavajuci", "kupujuci", "token", "suma_eur", "datum"],
        order_by="datum desc"
    )

    rows = sold + bought

    out = []

    for row in rows:
        token = frappe.get_doc("Token", row.token)

        # urč smer
        if row.predavajuci == bc_user:
            direction = "sell"    # user zarobil
        elif row.kupujuci == bc_user:
            direction = "buy"     # user minul
        else:
            continue

        out.append({
            "id": row.name,
            "type": "trade",
            "direction": direction,
            "price": float(row.suma_eur or 0),
            "year": token.vydany_rok,
            "createdAt": row.datum,
        })

    out = sorted(out, key=lambda x: x["createdAt"], reverse=True)

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

    # 👇 Nájdi BC Pouzivatel podľa Clerk ID
    user_doc = frappe.get_all(
        "Pouzivatel",
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
