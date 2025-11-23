# apps/bcservices/bcservices/api/payment.py

import json
import frappe
import stripe
from frappe.utils import now_datetime
<<<<<<< HEAD

from .utils import (
    verify_clerk_bearer_and_get_sub,
    ensure_bc_user_by_clerk,
    ensure_settings
)
=======
>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)

from .utils import (
    verify_clerk_bearer_and_get_sub,
    ensure_bc_user_by_clerk,
    get_settings,
)

# Stripe API key comes from Nastavenia
def _set_stripe_key():
    settings = get_settings()
    if not settings.stripe_secret_key:
        frappe.throw("Stripe secret key not set in Nastavenia", frappe.ConfigurationError)
    stripe.api_key = settings.stripe_secret_key

# -------------------------------------------------------------------------
# CHECKOUT – TREASURY
# -------------------------------------------------------------------------

@frappe.whitelist(methods=["POST"], allow_guest=True)
def checkout_treasury(userId: str = None, quantity: int = None, year: int = None):
    """
    iOS → vytvorí Stripe Checkout session na kúpu NEW tokenov z treasury.
    """
    _set_stripe_key()

    clerk_id, _ = verify_clerk_bearer_and_get_sub()

<<<<<<< HEAD
# -----------------------------------------------------------------------------
# CHECKOUT – TREASURY
# -----------------------------------------------------------------------------

@frappe.whitelist(methods=["POST"], allow_guest=True)
def checkout_treasury(userId: str = None, quantity: int = None, year: int = None):
    """
    iOS → vytvorí Stripe Checkout session na kúpu NEW tokenov z treasury.
    """
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

=======
>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)
    data = frappe.local.form_dict
    userId = userId or data.get("userId") or clerk_id
    quantity = int(quantity or data.get("quantity") or 0)
    year = int(year or data.get("year") or now_datetime().year)

    if not userId or quantity <= 0:
        frappe.throw("Missing or invalid userId/quantity", frappe.ValidationError)

    user = ensure_bc_user_by_clerk(userId)

<<<<<<< HEAD
    settings = ensure_settings()
    unit_price = float(settings.aktualna_cena_eur or 0)

    if unit_price <= 0:
        frappe.throw("Treasury price not set", frappe.ValidationError)

    # Limit 20 per year
    max_per_year = int(frappe.conf.get("max_primary_tokens_per_user") or 20)
=======
    # Load Doctype Nastavenia
    settings = get_settings()

    unit_price = float(settings.friday_base_price_eur or 0)
    if unit_price <= 0:
        frappe.throw("Treasury price not set", frappe.ValidationError)

    # Yearly limit
    max_per_year = int(settings.max_primary_tokens_per_user or 20)

>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)
    owned = frappe.db.count(
        "BC Token",
        {
            "aktualny_drzitel": user.name,
            "vydany_rok": year,
            "stav": ["in", ["active", "listed"]],
        },
    )

    if owned + quantity > max_per_year:
        frappe.throw(
            f"Primary limit is {max_per_year} tokens per user for {year}",
            frappe.ValidationError,
        )

<<<<<<< HEAD
    # Availability
=======
    # Treasury availability
>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)
    available = frappe.db.count(
        "BC Token",
        {
            "aktualny_drzitel": ["is", "null"],
            "vydany_rok": year,
            "stav": "active",
        },
    )

    if available < quantity:
        frappe.throw("Not enough tokens in treasury", frappe.ValidationError)

    amount = unit_price * quantity

    # Create BC Payment record
    p = frappe.get_doc(
        {
            "doctype": "BC Platba",
            "kupujuci": user.name,
            "typ": "treasury",
            "mnozstvo": quantity,
            "rok": year,
            "suma_eur": amount,
            "stav": "pending",
        }
    )
    p.insert(ignore_permissions=True)

<<<<<<< HEAD
    # Stripe Checkout
=======
    # Stripe Checkout — URLs from Nastavenia
    app_url = (settings.app_url or "").rstrip("/")

>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)
    session = stripe.checkout.Session.create(
        mode="payment",
        currency="eur",
        line_items=[
            {
                "price_data": {
                    "currency": "eur",
                    "unit_amount": int(round(unit_price * 100)),
<<<<<<< HEAD
                    "product_data": {
                        "name": f"Piatkový token ({year})"
                    },
=======
                    "product_data": {"name": f"Piatkový token ({year})"},
>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)
                },
                "quantity": quantity,
            }
        ],
<<<<<<< HEAD
        success_url=f'{frappe.conf.get("app_url").rstrip("/")}/?payment=success',
        cancel_url=f'{frappe.conf.get("app_url").rstrip("/")}/?payment=cancel',
=======
        success_url=f"{app_url}/?payment=success",
        cancel_url=f"{app_url}/?payment=cancel",
>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)
        metadata={
            "type": "treasury",
            "buyerId": userId,
            "quantity": str(quantity),
            "year": str(year),
            "paymentId": p.name,
        },
    )

    frappe.db.set_value("BC Platba", p.name, "stripe_session_id", session["id"])

    return {"url": session["url"]}


<<<<<<< HEAD
# -----------------------------------------------------------------------------
# CHECKOUT – LISTING (MARKET)
# -----------------------------------------------------------------------------

@frappe.whitelist(methods=["POST"], allow_guest=True)
def checkout_listing(buyerId: str = None, listingId: str = None):
    """
    iOS → Stripe Checkout pre kúpu TOKENU z marketplace listing-u.
    """
=======
# -------------------------------------------------------------------------
# CHECKOUT – LISTING
# -------------------------------------------------------------------------

@frappe.whitelist(methods=["POST"], allow_guest=True)
def checkout_listing(buyerId: str = None, listingId: str = None):
    _set_stripe_key()

>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)
    clerk_id, _ = verify_clerk_bearer_and_get_sub()

    data = frappe.local.form_dict
    buyerId = buyerId or data.get("buyerId") or clerk_id
    listingId = listingId or data.get("listingId")

    if not buyerId or not listingId:
        frappe.throw("Missing buyerId/listingId", frappe.ValidationError)
<<<<<<< HEAD

    buyer = ensure_bc_user_by_clerk(buyerId)
=======
>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)

    buyer = ensure_bc_user_by_clerk(buyerId)
    lst = frappe.get_doc("BC Inzerat", listingId)

    if lst.stav != "open":
        frappe.throw("Listing not available", frappe.ValidationError)

    if lst.predavajuci == buyer.name:
        frappe.throw("Cannot buy own listing", frappe.ValidationError)

    unit_price = float(lst.cena_eur)

    p = frappe.get_doc(
        {
            "doctype": "BC Platba",
            "kupujuci": buyer.name,
            "typ": "listing",
            "inzerat": lst.name,
            "suma_eur": unit_price,
            "stav": "pending",
        }
    )
    p.insert(ignore_permissions=True)

    # URLs from Nastavenia
    settings = get_settings()
    app_url = (settings.app_url or "").rstrip("/")

    session = stripe.checkout.Session.create(
        mode="payment",
        currency="eur",
        line_items=[
            {
                "price_data": {
                    "currency": "eur",
                    "unit_amount": int(round(unit_price * 100)),
                    "product_data": {"name": "Token z burzy"},
                },
                "quantity": 1,
            }
        ],
<<<<<<< HEAD
        success_url=f'{frappe.conf.get("app_url").rstrip("/")}/?payment=success',
        cancel_url=f'{frappe.conf.get("app_url").rstrip("/")}/?payment=cancel',
=======
        success_url=f"{app_url}/?payment=success",
        cancel_url=f"{app_url}/?payment=cancel",
>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)
        metadata={
            "type": "listing",
            "buyerId": buyerId,
            "listingId": listingId,
            "paymentId": p.name,
        },
    )

    frappe.db.set_value("BC Platba", p.name, "stripe_session_id", session["id"])

    return {"url": session["url"]}


<<<<<<< HEAD
# -----------------------------------------------------------------------------
# STRIPE WEBHOOK
# -----------------------------------------------------------------------------
=======
# -------------------------------------------------------------------------
# STRIPE WEBHOOK
# -------------------------------------------------------------------------
>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)

@frappe.whitelist(methods=["POST"], allow_guest=True)
def stripe_webhook():
    """
    Handles Stripe checkout webhooks.
    MUST be allow_guest=True — Stripe nemá session ani token.
    """
<<<<<<< HEAD
    payload = frappe.request.get_data(as_text=False)
    sig = frappe.get_request_header("Stripe-Signature")
    wh_secret = frappe.conf.get("stripe_webhook_secret")
=======
    _set_stripe_key()

    payload = frappe.request.get_data(as_text=False)
    sig = frappe.get_request_header("Stripe-Signature")

    settings = get_settings()
    wh_secret = settings.stripe_webhook_secret

    if not wh_secret:
        frappe.throw("Stripe webhook secret missing in Nastavenia", frappe.ConfigurationError)
>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)

    try:
        event = stripe.Webhook.construct_event(payload, sig, wh_secret)
    except Exception as e:
        frappe.local.response.http_status_code = 400
        return {"error": f"Webhook Error: {e}"}

    # Successful payment
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata") or {}
        payment_id = meta.get("paymentId")

        if payment_id:
            frappe.db.set_value(
                "BC Platba",
                payment_id,
                {
                    "stav": "paid",
                    "stripe_payment_intent": str(session.get("payment_intent") or "")
                }
            )

        # Treasury purchase
        if meta.get("type") == "treasury":
            _fulfill_treasury(
                buyer_clerk_id=meta.get("buyerId"),
                quantity=int(meta.get("quantity") or 0),
                year=int(meta.get("year") or now_datetime().year),
            )

        # Marketplace listing purchase
        if meta.get("type") == "listing":
            _fulfill_listing(
                buyer_clerk_id=meta.get("buyerId"),
                listing_id=meta.get("listingId")
            )

    # Cancelled / failed
    if event["type"] in (
        "checkout.session.expired",
        "checkout.session.async_payment_failed",
    ):
        session = event["data"]["object"]
        payment_id = (session.get("metadata") or {}).get("paymentId")
        if payment_id:
            frappe.db.set_value("BC Platba", payment_id, "stav", "failed")

    return {"received": True}


<<<<<<< HEAD
# -----------------------------------------------------------------------------
# FULFILLMENT HELPERS
# -----------------------------------------------------------------------------
=======
# -------------------------------------------------------------------------
# FULFILLMENT HELPERS
# -------------------------------------------------------------------------
>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)

def _fulfill_treasury(buyer_clerk_id: str, quantity: int, year: int):
    """Assign newly purchased treasury tokens to the buyer."""
    user = ensure_bc_user_by_clerk(buyer_clerk_id)

    tokens = frappe.get_all(
        "BC Token",
        filters={
            "aktualny_drzitel": ["is", "null"],
            "vydany_rok": year,
            "stav": "active",
        },
        fields=["name"],
        order_by="creation asc",
        limit_page_length=quantity,
    )

    if len(tokens) < quantity:
        frappe.throw("Treasury sold out", frappe.ValidationError)

    names = [t["name"] for t in tokens]

    # Assign tokens
    for token_name in names:
        frappe.db.set_value("BC Token", token_name, "aktualny_drzitel", user.name)

<<<<<<< HEAD
    # Create purchase items (optional)
    settings = ensure_settings()
    unit_price = float(settings.aktualna_cena_eur or 0)
=======
    # Create purchase items
    settings = get_settings()
    unit_price = float(settings.friday_base_price_eur or 0)
>>>>>>> 69f6bd8 (Refactor: Move all config values to Nastavenia doctype + update API)

    for token_name in names:
        try:
            item = frappe.get_doc(
                {
                    "doctype": "BC Polozka Nakupu",
                    "token": token_name,
                    "jednotkova_cena_eur": unit_price,
                    "rok": year,
                }
            )
            item.insert(ignore_permissions=True)
        except Exception:
            pass


def _fulfill_listing(buyer_clerk_id: str, listing_id: str):
    """Finalize marketplace listing purchase."""
    buyer = ensure_bc_user_by_clerk(buyer_clerk_id)
    lst = frappe.get_doc("BC Inzerat", listing_id)

    if lst.stav != "open":
        frappe.throw("Listing not open", frappe.ValidationError)

    # Lock listing
    frappe.db.set_value(
        "BC Inzerat",
        lst.name,
        {"stav": "sold", "uzavrete_kedy": now_datetime()}
    )

    tok = frappe.get_doc("BC Token", lst.token)

    if not (
        tok.aktualny_drzitel == lst.predavajuci
        and tok.stav == "listed"
        and (tok.minuty_ostavajuce or 0) > 0
    ):
        frappe.throw("Token not purchasable", frappe.ValidationError)

    # Transfer token
    frappe.db.set_value(
        "BC Token",
        tok.name,
        {"aktualny_drzitel": buyer.name, "stav": "active"}
    )

    # Create trade record
    trade = frappe.get_doc(
        {
            "doctype": "BC Obchod",
            "inzerat": lst.name,
            "token": tok.name,
            "predavajuci": lst.predavajuci,
            "kupujuci": buyer.name,
            "cena_eur": lst.cena_eur,
        }
    )
    trade.insert(ignore_permissions=True)

    # Ledger entries
    for (u, typ) in [
        (buyer.name, "friday_trade_buy"),
        (lst.predavajuci, "friday_trade_sell"),
    ]:
        tx = frappe.get_doc(
            {
                "doctype": "BC Transakcia",
                "pouzivatel": u,
                "typ": typ,
                "suma_eur": lst.cena_eur,
                "zmena_sekund": 0,
                "poznamka": f"listing:{lst.name}; token:{tok.name}",
            }
        )
        tx.insert(ignore_permissions=True)
        tx.submit()
