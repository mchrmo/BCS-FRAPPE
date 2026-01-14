# apps/bcservices/bcservices/api/google_calendar.py

import os
import frappe
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

SCOPES = ["https://www.googleapis.com/auth/calendar"]

SERVICE_ACCOUNT_FILE = frappe.get_site_path(
    "private",
    "files",
    "summer-heaven-478513-q6-323b705c6baa.json",
)

ADMIN_CALENDAR_ID = "andrej.cernak2007@gmail.com"
TIMEZONE = "Europe/Bratislava"

# --------------------------------------------------
# INTERNAL HELPER
# --------------------------------------------------

def _get_calendar_service():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(
            f"Google Calendar JSON not found: {SERVICE_ACCOUNT_FILE}"
        )

    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )

    return build("calendar", "v3", credentials=credentials)

# --------------------------------------------------
# PUBLIC API – JEDINÁ FUNKCIA, KTORÚ POUŽÍVAŠ
# --------------------------------------------------

def create_call_event_from_end(call_doc, znacka_klienta: str):
    """
    Vytvorí Google Calendar event PO UKONČENÍ hovoru.
    Používa sa výhradne z call.end().
    """

    service = _get_calendar_service()

    start_dt = datetime.combine(
        call_doc.zaciatok_datum,
        datetime.strptime(call_doc.zaciatok_cas, "%H:%M:%S").time(),
    )

    end_dt = datetime.combine(
        call_doc.koniec_datum,
        datetime.strptime(call_doc.koniec_cas, "%H:%M:%S").time(),
    )

    duration_min = max(1, int((call_doc.trvanie_s or 0) / 60))

    event = {
        "summary": znacka_klienta,
        "description": f"daný telefonát ({duration_min} min)",
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": TIMEZONE,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": TIMEZONE,
        },
    }

    created_event = service.events().insert(
        calendarId=ADMIN_CALENDAR_ID,
        body=event,
    ).execute()

    return created_event.get("id")
