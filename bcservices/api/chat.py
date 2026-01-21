import frappe
from .utils import verify_clerk_bearer_and_get_sub

@frappe.whitelist(methods=["POST"], allow_guest=True)
def poslat_spravu():
    # 1. Overíme používateľa cez Clerk JWT (tvoja funkcia z utils.py)
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    
    data = frappe.local.form_dict
    prijemca_id = data.get("prijemca")  # clerk_id príjemcu
    obsah = data.get("obsah")

    if not prijemca_id or not obsah:
        frappe.throw("Chýba príjemca alebo obsah správy")

    # 2. Vytvoríme záznam
    doc = frappe.get_doc({
        "doctype": "Sprava Chatu",
        "odosielatel": clerk_id,
        "prijemca": prijemca_id,
        "obsah": obsah,
        "datum_cas": frappe.utils.now_datetime()
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    
    return {"success": True, "name": doc.name}

@frappe.whitelist(methods=["GET"], allow_guest=True)
def nacitat_historiu(s_kym):
    """Vráti správy medzi prihláseným userom a iným používateľom"""
    clerk_id, _ = verify_clerk_bearer_and_get_sub()
    
    spravy = frappe.get_all(
        "Sprava Chatu",
        filters=[
            ["odosielatel", "in", [clerk_id, s_kym]],
            ["prijemca", "in", [clerk_id, s_kym]]
        ],
        fields=["odosielatel", "obsah", "datum_cas"],
        order_by="datum_cas asc"
    )
    return spravy