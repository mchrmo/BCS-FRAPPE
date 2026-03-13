import frappe
import html
from frappe.model.document import Document

class Klient(Document):
    def after_insert(self):
        self.send_welcome_email()

    @frappe.whitelist()
    def send_welcome_email(self):
        email = self.email
        if not email or not self.heslo:
            frappe.msgprint("Klient nemá vyplnený email alebo heslo.")
            return
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
            now=True
        )

    @frappe.whitelist()
    def send_password_reset_email(self):
        from bcservices.api.utils import clerk_api

        email = self.email
        if not email:
            frappe.msgprint("Klient nemá vyplnený email.")
            return
        if not self.clerk_id:
            frappe.msgprint("Klient nemá priradené Clerk ID.")
            return

        try:
    # Correct Clerk endpoint for password reset link
    res = clerk_api(
        f"/v1/users/{self.clerk_id}",
        method="GET",
    )
    frappe.log_error(f"Clerk user: {res}", "BC Clerk Sync")
    
    # Generate magic link instead
    res = clerk_api(
        "/v1/sign_in_tokens",
        method="POST",
        json_body={
            "user_id": self.clerk_id,
            "expires_in_seconds": 86400  # 24 hours
        }
    )
    frappe.log_error(f"Clerk reset response: {res}", "BC Clerk Sync")
    reset_link = res.get("url") or res.get("token")
        except Exception as e:
            frappe.log_error(f"Clerk reset password failed: {e}", "BC Clerk Sync")
            frappe.msgprint(f"Nepodarilo sa vygenerovať reset link: {e}")
            return

        if not reset_link:
            frappe.msgprint("Clerk nevrátil reset link.")
            return

        subject = "Reset hesla"
        message = f"""
        Dobrý deň {self.username or 'používateľ'},<br><br>
        dostali sme žiadosť o reset vášho hesla.<br><br>
        Kliknite na odkaz nižšie pre nastavenie nového hesla:<br><br>
        <a href="{reset_link}" style="
            background-color: #4CAF50;
            color: white;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 6px;
            display: inline-block;
        ">🔐 Nastaviť nové heslo</a><br><br>
        Odkaz je platný 24 hodín.<br><br>
        Ak ste o reset hesla nežiadali, ignorujte tento email.<br><br>
        S pozdravom,<br>
        Váš tím
        """
        frappe.sendmail(
            recipients=email,
            subject=subject,
            message=message,
            now=True
        )
        frappe.msgprint(f"✅ Reset email bol odoslaný na {email}")
