# apps/bcservices/bcservices/api/market.py

import frappe

@frappe.whitelist(methods=["GET"], allow_guest=True)
def listings():
    """
    Verejný endpoint pre frontend:
    GET /api/method/bcservices.api.market.listings

    Načíta všetky otvorené inzeráty z Doctype 'BC Inzerat'
    a pripojí základné info o tokene.
    """
    items = frappe.get_all(
        "BC Inzerat",
        filters={"stav": "open"},
        fields=[
            "name as id",
            "token",
            "predavajuci as sellerId",
            "cena_eur as priceEur",
            "stav as status",
            "creation as createdAt",
        ],
        order_by="creation desc",
    )

    # doplnenie info o tokene
    for item in items:
        tok = frappe.get_value(
            "BC Token",
            item.token,
            ["vydany_rok", "minuty_ostavajuce", "stav"],
            as_dict=True,
        )
        if tok:
            item["token"] = {
                "id": item["token"],
                "issuedYear": tok.vydany_rok,
                "minutesRemaining": tok.minuty_ostavajuce,
                "status": tok.stav,
            }

    return {"success": True, "items": items}
