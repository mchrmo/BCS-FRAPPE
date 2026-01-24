import frappe
from frappe.model.document import Document

class Poradca(Document):

    @frappe.whitelist()
    def send_welcome_email(self):
        if not self.email or not self.heslo:
            frappe.msgprint("Poradca nemá vyplnený email alebo heslo.")
            return

        subject = "Vaše prihlasovacie údaje"

        message = f"""
Dobrý deň,

boli vám vytvorené prihlasovacie údaje do systému.

Email: {self.email}
Heslo: {self.heslo}

Prosím, po prihlásení si heslo zmeňte.

S pozdravom,
Váš tím
        """

        frappe.sendmail(
            recipients=self.email,
            subject=subject,
            message=message,
            now=True
        )
