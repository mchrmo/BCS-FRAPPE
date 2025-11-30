import frappe

def after_insert(doc, method):
    # pripravíme text emailu
    subject = "Vaše prihlasovacie údaje"
    message = f"""
Dobrý deň,

bol Vám vytvorený nový účet.

Prihlasovacie údaje:
Email: {doc.email}
Heslo: {doc.heslo}

Môžete sa prihlásiť tu:
https://tvoj-web.sk/login

S pozdravom,
Váš tím
"""

    # pošleme email
    frappe.sendmail(
        recipients=[doc.email],
        subject=subject,
        message=message
    )
