import frappe
import html
from frappe.model.document import Document

class Klient(Document):
    def after_insert(self):
        # Pri vytvorení automaticky odošleme mail
        self.send_welcome_email()

    @frappe.whitelist() # Whitelist umožní volanie metódy z frontendu (tlačidlom)
    def send_welcome_email(self):
        email = self.email
        if not email or not self.heslo:
            frappe.msgprint("Klient nemá vyplnený email alebo heslo.")
            return

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
            recipients=email,
            subject=subject,
            message=message,
            now=True # Odošle mail hneď, nečaká na scheduler
        )
