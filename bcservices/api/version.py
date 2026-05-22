import frappe

@frappe.whitelist(allow_guest=True)
def get_min_version():
    min_version = frappe.db.get_single_value("Nastavenie", "min_ios_version")
    return {
        "min_version": min_version or "1.0.0"
    }
