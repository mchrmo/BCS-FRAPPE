# klient.py
import frappe
from frappe.model.document import Document

class Klient(Document):
    def after_insert(self):
        # email klienta
        email = self.email
        
        # heslo vygenerované klient scriptom (musí byť uložené v doctype)
        password = self.heslo

        # predmet
        subject = "Vaše prihlasovacie údaje"

        # telo emailu
        message = f"""
Dobrý deň {self.username},

boli vám vytvorené prihlasovacie údaje.

📧 Email: {email}
🔐 Heslo: {password}

Prosím, prihláste sa do systému a heslo si zmeňte.

S pozdravom,
Váš tím
"""

        # odoslanie emailu
        frappe.sendmail(
            recipients=email,
            subject=subject,
            message=message
        )
