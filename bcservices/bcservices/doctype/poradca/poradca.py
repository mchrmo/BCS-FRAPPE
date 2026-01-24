import frappe
import html
from frappe.model.document import Document

class Poradca(Document):

    @frappe.whitelist()
    def send_welcome_email(self):
        if not self.email or not self.heslo:
            frappe.msgprint("Poradca nemá vyplnený email alebo heslo.")
            return

        subject = "Vaše prihlasovacie údaje"

       # HTML-safe verzia hesla
        password_safe = html.escape(self.heslo or "")

        subject = "Vaše prihlasovacie údaje"
        message = f"""
        Dobrý deň {self.username or 'používateľ'},<br><br>
        boli vám vytvorené prihlasovacie údaje do systému.<br><br>
        📧 <b>Email:</b> {email}<br>
        🔐 <b>Heslo:</b> {password_safe}<br><br>
        Prosím, prihláste sa do systému a heslo si v prípade potreby zmeňte.<br><br>
        S pozdravom,<br>
        Váš tím
        """

        frappe.sendmail(
            recipients=self.email,
            subject=subject,
            message=message,
            now=True
        )
