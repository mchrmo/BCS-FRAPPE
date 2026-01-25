import frappe
import html
from frappe.model.document import Document

class Poradca(Document):

    def after_insert(self):
        # Ak chcete, aby sa mail odoslal hneď po vytvorení poradcu
        self.send_welcome_email()

    @frappe.whitelist()
    def send_welcome_email(self):
        # Overenie, či sú polia vyplnené
        if not self.email or not self.heslo:
            frappe.msgprint("Poradca nemá vyplnený email alebo heslo.")
            return

        # HTML-safe verzia hesla (prevencia proti špeciálnym znakom v HTML)
        password_safe = html.escape(str(self.heslo) or "")
        
        subject = "Vaše prihlasovacie údaje"
        
        # Opravená správa: pridané self.email a tag <code> pre lepšiu čitateľnosť
        message = f"""
        Dobrý deň {self.username or 'používateľ'},<br><br>
        boli vám vytvorené prihlasovacie údaje do systému.<br><br>
        📧 <b>Email:</b> {self.email}<br>
        🔐 <b>Heslo:</b> <code>{password_safe}</code><br><br>
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
        
        frappe.msgprint(f"E-mail s údajmi bol odoslaný na adresu {self.email}")