import frappe
import random
import string
from frappe.model.document import Document


def generate_password(length=16):
    """Generate a strong random password."""
    chars = string.ascii_letters + string.digits + "!@#$%^&*()_+"
    return ''.join(random.choice(chars) for _ in range(length))


class Pouzivatel(Document):

    def before_insert(self):
        """
        Auto-generate password if empty.
        Runs BEFORE the document is inserted.
        """
        if not self.heslo:
            self.heslo = generate_password()

    def after_insert(self):
        """
        Automatically send welcome email with login credentials.
        Runs AFTER the document is created in the DB.
        """
        if not self.email:
            return

        subject = "Vaše prihlasovacie údaje"
        message = f"""
Dobrý deň,

bol Vám vytvorený nový účet.

Vaše prihlasovacie údaje:
Email: {self.email}
Heslo: {self.heslo}

Prihlásiť sa môžete tu:
https://tvoj-web.sk/login

S pozdravom,
Váš tím
"""

        frappe.sendmail(
            recipients=[self.email],
            subject=subject,
            message=message
        )
