import frappe

@frappe.whitelist(methods=["GET"], allow_guest=True)
def listings():
    rows = frappe.get_all(
        "BC Inzerat",
        filters={"stav": "open"},
        order_by="creation desc",
        fields=["name", "token", "predavajuci", "cena_eur", "creation"]
    )

    out = []

    for row in rows:
        tok = frappe.get_doc("BC Token", row.token)

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
    """
    History of token transactions for a given user:
    - purchase from treasury
    - purchase from marketplace
    - selling to marketplace
    - trades between users
    """

    if not userId:
        frappe.throw("Missing userId", frappe.ValidationError)

    # Nájdeme BC Pouzivatela
    user_doc = frappe.get_all(
        "BC Pouzivatel",
        filters={"clerk_id": userId},
        limit=1
    )

    if not user_doc:
        return {"success": True, "items": []}

    bc_user = user_doc[0].name

    # Všetky transakcie kde bol predávajúci alebo kupujúci
    rows = frappe.get_all(
        "BC Transakcia",
        filters=[
            ["predavajuci", "in", [bc_user]],
            ["kupujuci", "in", [bc_user]]
        ],
        fields=[
            "name",
            "predavajuci",
            "kupujuci",
            "token",
            "suma_eur",
            "datum",
        ],
        order_by="datum desc"
    )

    out = []

    for row in rows:
        token = frappe.get_doc("BC Token", row.token)

        # urč typ transakcie
        if row.predavajuci == bc_user and row.kupujuci:
            direction = "sell"
            type_ = "trade"
        elif row.kupujuci == bc_user and row.predavajuci:
            direction = "buy"
            type_ = "trade"
        else:
            type_ = "purchase"
            direction = "buy"

        out.append({
            "id": row.name,
            "type": type_,
            "direction": direction,
            "price": float(row.suma_eur or 0),
            "year": token.vydany_rok,
            "createdAt": row.datum,
        })

    return {"success": True, "items": out}

@frappe.whitelist(methods=["POST"], allow_guest=False)
def list_token(sellerId: str = None, tokenId: str = None, priceEur: float = None):
    """
    Client lists a token for sale — creates BC Inzerat.
    """

    # overíme JSON body
    data = frappe.form_dict

    sellerId = data.get("sellerId") or sellerId
    tokenId = data.get("tokenId") or tokenId
    priceEur = data.get("priceEur") or priceEur

    if not sellerId or not tokenId or priceEur is None:
        frappe.throw("Missing data for listing", frappe.ValidationError)

    # najdi BC Pouzivatel podľa Clerk ID
    user_doc = frappe.get_all(
        "BC Pouzivatel",
        filters={"clerk_id": sellerId},
        limit=1
    )

    if not user_doc:
        frappe.throw("User not found", frappe.DoesNotExistError)

    bc_user = user_doc[0].name

    # načítaj token
    token = frappe.get_doc("BC Token", tokenId)

    # token musí patriť používateľovi
    if token.aktualny_drzitel != bc_user:
        frappe.throw("Token does not belong to this user", frappe.PermissionError)

    # token musí byť aktívny
    if token.stav != "active":
        frappe.throw("Token is not active", frappe.ValidationError)

    # vytvor nový inzerát
    inz = frappe.get_doc({
        "doctype": "BC Inzerat",
        "predavajuci": bc_user,
        "token": tokenId,
        "cena_eur": priceEur,
        "stav": "open"
    })
    inz.insert(ignore_permissions=True)

    # označ token ako listed
    token.stav = "listed"
    token.save(ignore_permissions=True)

    return {
        "success": True,
        "listingId": inz.name,
        "tokenId": tokenId,
        "priceEur": priceEur,
    }

