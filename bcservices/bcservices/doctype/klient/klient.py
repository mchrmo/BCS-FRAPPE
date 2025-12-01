# klient.py
import frappe
import html
from frappe.model.document import Document

class Klient(Document):
    def after_insert(self):
        email = self.email

        # pôvodné heslo
        password_raw = self.heslo

        # HTML-safe verzia hesla (nutné pre email)
        password_safe = html.escape(password_raw or "")

        subject = "Vaše prihlasovacie údaje"

        message = f"""
Dobrý deň {self.username},

boli vám vytvorené prihlasovacie údaje.

📧 Email: {email}
🔐 Heslo: {password_safe}

Prosím, prihláste sa do systému a heslo si zmeňte.

S pozdravom,
Váš tím
"""

        frappe.sendmail(
            recipients=email,
            subject=subject,
            message=message
        )
