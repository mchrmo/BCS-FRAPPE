import frappe
import html
from frappe.model.document import Document

class Poradca(Document):
    def after_insert(self):
        self.send_welcome_email()

    @frappe.whitelist()
    def send_welcome_email(self):
        if not self.email or not self.heslo:
            frappe.msgprint("Poradca nemá vyplnený email alebo heslo.")
            return

        password_safe = html.escape(self.heslo)

        subject = "Vaše prihlasovacie údaje – Poradca"
        message = f"""
        Dobrý deň,<br><br>
        boli vám vytvorené prihlasovacie údaje do systému.<br><br>

        📧 <b>Email:</b> {self.email}<br>
		🔐 <b>Dočasný prístupový kód:</b> {password_safe}<br><br>

        Prosím, po prihlásení si heslo zmeňte.<br><br>
        S pozdravom,<br>
        Váš tím
        """

        frappe.sendmail(
            recipients=self.email,
            subject=subject,
            message=message,
            now=True
        )
