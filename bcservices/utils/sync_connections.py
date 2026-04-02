import frappe

DOCTYPE_MAP = {
    "Poradca": "Klient",
    "Klient": "Poradca"
}

def sync_connections(doc, method):
    """
    Keď sa uloží Poradca alebo Klient, zabezpeč že každý
    priradený používateľ má aj spätnú väzbu.
    """
    for row in doc.get("poradcovia") or []:
        linked_doctype = row.typ_uzivatela  # "Poradca" alebo "Klient"
        linked_name = row.uzivatel_link

        if not linked_name:
            continue

        try:
            linked_doc = frappe.get_doc(linked_doctype, linked_name)
        except frappe.DoesNotExistError:
            continue

        # Skontroluj či spätný záznam už existuje
        already_linked = any(
            r.uzivatel_link == doc.name and r.typ_uzivatela == doc.doctype
            for r in (linked_doc.get("poradcovia") or [])
        )

        if not already_linked:
            linked_doc.append("poradcovia", {
                "typ_uzivatela": doc.doctype,
                "uzivatel_link": doc.name
            })
            # flags.in_insert zabraňuje nekonečnej rekurzii
            linked_doc.flags.ignore_permissions = True
            linked_doc.flags.ignore_version = True
            linked_doc.save()
